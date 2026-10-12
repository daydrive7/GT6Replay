import hashlib
import hmac
import struct
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))
from decoder.bitstream import BitReader, DecodeError
from decoder.container import ReplayIndex, ScalarEncoding, VectorEncoding
from decoder.savedata import ProtectedFile, SavedataKeys, decrypt_chunk, read_export, read_pfd
from decoder.transforms import Transform
from native_motion import NativeReplay
from compare_decoders import compare


def encryption_fixture(plaintext, name="REPLAY.0"):
    keys = SavedataKeys(bytes(range(16, 32)), bytes(range(16)))
    authentication = keys.authentication_key
    file_key = bytes(range(32, 48))
    wrap = Cipher(algorithms.AES(keys.portability), modes.CBC(authentication[:16])).encryptor()
    key_material = wrap.update(file_key + bytes(48)) + wrap.finalize()
    padded = plaintext + bytes(-len(plaintext) % 16)
    counter_bytes = b"".join(struct.pack(">QQ", i, 0) for i in range(len(padded) // 16))
    mask_cipher = Cipher(algorithms.AES(file_key), modes.ECB()).encryptor()
    mask = mask_cipher.update(counter_bytes) + mask_cipher.finalize()
    masked = bytes(a ^ b for a, b in zip(padded, mask, strict=True))
    cipher = Cipher(algorithms.AES(file_key), modes.ECB()).encryptor()
    encrypted = cipher.update(masked) + cipher.finalize()
    record = ProtectedFile(
        name, key_material, hmac.digest(authentication, encrypted, "sha1"), len(plaintext)
    )
    return keys, encrypted, record


def pfd_fixture(records, version=3):
    data = bytearray(128 + 272 * len(records))
    struct.pack_into(">QQ", data, 0, 0x50464442, version)
    struct.pack_into(">QQQ", data, 96, 1, len(records), len(records))
    for i, record in enumerate(records):
        base = 128 + i * 272
        name = record.name.encode("ascii")
        data[base + 8 : base + 8 + len(name)] = name
        data[base + 80 : base + 144] = record.key_material
        data[base + 144 : base + 164] = record.content_mac
        struct.pack_into(">Q", data, base + 264, record.size)
    return bytes(data)


def index_fixture():
    # One zero-filled parameter record occupies 5768 bits; all dimensions come
    # from the documented version-49 field layout, not a generated game sample.
    data = bytearray(0x630)
    data[:4] = b"RPLY"
    struct.pack_into(">I", data, 8, 115)
    struct.pack_into(">3I", data, 0x10, 21, 17, 49)
    struct.pack_into(">I", data, 0x248, 3)
    struct.pack_into(">I", data, 0x264, 0x340)
    struct.pack_into(">I", data, 0x28C, 2)
    struct.pack_into(">I", data, 0x294, 0x300)
    struct.pack_into(">4I", data, 0x300, 0x612, 0, 0x620, 3)
    data[0x340] = 1
    data[0x612] = 0x80
    return data


def motion_fixture(slots=(0, 2)):
    motion = np.zeros((4, len(slots), 13), np.float32)
    motion[:, :, 9] = 1
    motion[:, :, 10] = 2000
    motion[:, :, 11] = 1
    motion[:, :, 12] = 1
    for i, slot in enumerate(slots):
        motion[:, i, 0] = np.arange(4) + slot * 20
    metadata = {"native_sha256": "a" * 64, "frame_count": 4, "fps": 60, "slots": list(slots)}
    return NativeReplay("synthetic.gt6r", motion, metadata, {})


class BitReaderTests(unittest.TestCase):
    def test_unaligned_fields_and_signed_values(self):
        reader = BitReader(bytes.fromhex("b3e14a"))
        self.assertEqual(reader.read(3), 5)
        self.assertEqual(reader.read(7), 79)
        self.assertEqual(reader.signed(6), -31)
        self.assertEqual(reader.read(8), 74)

    def test_explicit_end_is_enforced_without_advancing(self):
        reader = BitReader(b"\xff\xff", 2, 9)
        self.assertEqual(reader.read(7), 127)
        with self.assertRaises(DecodeError):
            reader.read(1)
        self.assertEqual(reader.position, 9)
        with self.assertRaises(DecodeError):
            reader.skip(1)

    def test_invalid_bounds_and_widths(self):
        for start, end in ((-1, 8), (0, 9), (7, 2)):
            with self.assertRaises(DecodeError):
                BitReader(b"\0", start, end)
        reader = BitReader(b"\0" * 9)
        for width in (-1, 65, 1.5):
            with self.assertRaises(DecodeError):
                reader.read(width)
        self.assertEqual(reader.read(0), 0)


class ContainerTests(unittest.TestCase):
    def test_nonfinite_encoding_coefficients_are_rejected(self):
        value = (2 << 192) | (0x7FC00000 << 160)
        vector = (value << 2).to_bytes(25, "big")
        scalar = b"\0" + struct.pack(">3f", float("inf"), 0, 0)
        for encoding, data in ((VectorEncoding, vector), (ScalarEncoding, scalar)):
            with self.assertRaises(DecodeError):
                encoding.read(BitReader(data))

    def test_parameter_end_and_seek_range(self):
        index = ReplayIndex.read(index_fixture())
        self.assertEqual(index.parameter_end_bit, 0x612 * 8)
        self.assertEqual(index.frame_count, 3)
        self.assertEqual(len(index.encodings), 1)
        self.assertEqual(len(index.encodings[0].vectors), 14)
        self.assertEqual(len(index.encodings[0].scalars), 14)

    def test_unsupported_protocol_and_seek_corruption(self):
        for offset, value in (
            (8, 114),
            (0x18, 48),
            (0x248, 4),
            (0x300, 0x900),
            (0x304, 1),
            (0x28C, 0xFFFFFFFF),
        ):
            data = index_fixture()
            struct.pack_into(">I", data, offset, value)
            with self.assertRaises(DecodeError):
                ReplayIndex.read(data)

    def test_parameter_count_cannot_overrun_seek_point(self):
        data = index_fixture()
        data[0x340] = 32
        with self.assertRaises(DecodeError):
            ReplayIndex.read(data)


class SavedataTests(unittest.TestCase):
    def test_cipher_counter_spans_batch_boundary_and_padding(self):
        plaintext = b"RPLY" + bytes(range(256)) * 256 + b"end"
        keys, ciphertext, record = encryption_fixture(plaintext)
        self.assertEqual(decrypt_chunk(ciphertext, record, keys), plaintext)

    def test_corruption_wrong_key_and_truncation_are_rejected(self):
        keys, ciphertext, record = encryption_fixture(b"RPLY" + bytes(767))
        corrupt = bytearray(ciphertext)
        corrupt[4] ^= 1
        for data, test_keys in (
            (bytes(corrupt), keys),
            (ciphertext[:-1], keys),
            (ciphertext, SavedataKeys(keys.portability, bytes(16))),
        ):
            with self.assertRaises(DecodeError):
                decrypt_chunk(data, record, test_keys)

    def test_pfd_v3_v4_names_and_dimensions(self):
        _, _, record = encryption_fixture(b"RPLY" + bytes(767))
        for version in (3, 4):
            self.assertEqual(read_pfd(pfd_fixture([record], version))["replay.0"], record)
        for data in (
            pfd_fixture([record])[:-1],
            pfd_fixture([record, record]),
            pfd_fixture(
                [ProtectedFile("../REPLAY.0", record.key_material, record.content_mac, record.size)]
            ),
        ):
            with self.assertRaises(DecodeError):
                read_pfd(data)

    def test_original_chunk_import_is_read_only_and_case_insensitive(self):
        plaintext = b"RPLY" + bytes(range(256)) * 3
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            records = []
            for i, part in enumerate((plaintext[:400], plaintext[400:])):
                keys, encrypted, record = encryption_fixture(part, f"REPLAY.{i}")
                (folder / f"replay.{i}").write_bytes(encrypted)
                records.append(record)
            (folder / "param.pfd").write_bytes(pfd_fixture(records))
            before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.iterdir()}
            result = read_export(folder / "replay.0", keys)
            self.assertEqual(result.data, plaintext)
            self.assertTrue(result.protected)
            self.assertEqual(len(result.source_files), 2)
            self.assertEqual(
                before,
                {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.iterdir()},
            )

    def test_missing_pfd_chunks_and_extra_chunk_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            keys, encrypted, record = encryption_fixture(b"RPLY" + bytes(767))
            (folder / "REPLAY.0").write_bytes(encrypted)
            with self.assertRaisesRegex(DecodeError, "PARAM.PFD"):
                read_export(folder, keys)
            (folder / "PARAM.PFD").write_bytes(pfd_fixture([record]))
            with self.assertRaisesRegex(DecodeError, "key configuration"):
                read_export(folder)
            (folder / "REPLAY.1").write_bytes(encrypted)
            with self.assertRaisesRegex(DecodeError, "do not match"):
                read_export(folder, keys)
            (folder / "REPLAY.1").unlink()
            (folder / "REPLAY.2").write_bytes(encrypted)
            with self.assertRaisesRegex(DecodeError, "consecutive"):
                read_export(folder, keys)

    def test_decrypted_chunks_and_rply_need_no_keys(self):
        plaintext = b"RPLY" + bytes(range(256)) * 3
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            (folder / "REPLAY.0").write_bytes(plaintext[:400])
            (folder / "REPLAY.1").write_bytes(plaintext[400:])
            result = read_export(folder)
            self.assertEqual(result.data, plaintext)
            self.assertFalse(result.protected)
            raw = folder / "test.rply"
            raw.write_bytes(plaintext)
            self.assertEqual(read_export(raw).data, plaintext)


class TransformTests(unittest.TestCase):
    def test_absolute_transform_float_order_and_bit_alignment(self):
        values = (1, 2, 3, 100, -25.5, 17, 0, 0.1, -0.1, 0, 0, 0, 1)
        body = struct.pack(">13f", *values)
        unaligned = ((5 << len(body) * 8 | int.from_bytes(body, "big")) << 5).to_bytes(
            len(body) + 1, "big"
        )
        reader = BitReader(unaligned, 3, 3 + len(body) * 8)
        transform = Transform.read_absolute(reader)
        self.assertEqual(transform.velocity, (1, 2, 3))
        self.assertEqual(transform.position, (100, -25.5, 17))
        self.assertEqual(transform.quaternion, (0, 0, 0, 1))
        self.assertEqual(reader.position, reader.end)

    def test_invalid_transform_is_not_displayable_motion(self):
        for values in ([0] * 13, [float("nan")] + [0] * 11 + [1]):
            with self.assertRaises(DecodeError):
                Transform.read_absolute(BitReader(struct.pack(">13f", *values)))


class AccuracyTests(unittest.TestCase):
    def test_slot_order_and_quaternion_sign_are_equivalent(self):
        reference, candidate = motion_fixture(), motion_fixture((2, 0))
        candidate.motion[:, :, 6:10] *= -1
        self.assertTrue(compare(candidate, reference)["passed"])

    def test_errors_report_the_original_frame_and_driver(self):
        reference, candidate = motion_fixture(), motion_fixture()
        candidate.motion[2, 1, 0] += 1
        candidate.motion[3, 1, 11] = 2
        report = compare(candidate, reference)
        self.assertFalse(report["passed"])
        fields = report["drivers"][1]["fields"]
        self.assertEqual(fields["position_metres"]["first_mismatch_frame"], 2)
        self.assertEqual(fields["gear"]["first_mismatch_frame"], 3)

    def test_missing_driver_frame_and_wrong_replay_are_rejected(self):
        reference, candidate = motion_fixture(), motion_fixture()
        reference.motion[1, 1, :] = np.nan
        self.assertEqual(compare(candidate, reference)["drivers"][1]["visibility_mismatches"], 1)
        candidate.metadata["native_sha256"] = "b" * 64
        with self.assertRaises(ValueError):
            compare(candidate, reference)

    def test_invalid_tolerance_and_zero_quaternion_cannot_pass(self):
        reference, candidate = motion_fixture(), motion_fixture()
        with self.assertRaises(ValueError):
            compare(candidate, reference, position_tolerance=float("nan"))
        candidate.motion[:, :, 9] = 0
        with self.assertRaises(ValueError):
            compare(candidate, reference)


if __name__ == "__main__":
    unittest.main()
