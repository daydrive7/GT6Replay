"""Read PS3 replay exports without modifying their files.

PFD layout and cipher construction are documented by flatz's pfdtool.
This implementation does not import that tool or game executable code.
"""

from dataclasses import dataclass
from pathlib import Path
import hashlib
import hmac
import re
import struct

import numpy as np

from .bitstream import DecodeError

MAX_REPLAY_BYTES = 512 * 1024**2
MAX_PFD_BYTES = 1024**2


class SavedataKeyRequired(DecodeError):
    pass


@dataclass(frozen=True)
class SavedataKeys:
    portability: bytes
    file_id: bytes

    def __post_init__(self):
        if (
            not isinstance(self.portability, bytes)
            or not isinstance(self.file_id, bytes)
            or len(self.portability) != 16
            or len(self.file_id) != 16
        ):
            raise DecodeError("Savedata keys must contain exactly 16 bytes each.")

    @property
    def authentication_key(self):
        source = iter(self.file_id)
        insertions = {1: 11, 2: 15, 5: 14, 8: 10}
        return bytes(insertions[i] if i in insertions else next(source) for i in range(20))


@dataclass(frozen=True)
class ProtectedFile:
    name: str
    key_material: bytes
    content_mac: bytes
    size: int


@dataclass(frozen=True)
class ReplayBytes:
    data: bytes
    source_files: tuple[dict, ...]
    protected: bool

    @property
    def sha256(self):
        return hashlib.sha256(self.data).hexdigest()


def read_pfd(data: bytes) -> dict[str, ProtectedFile]:
    if not 120 <= len(data) <= MAX_PFD_BYTES:
        raise DecodeError("Invalid PARAM.PFD size.")
    magic, version = struct.unpack_from(">QQ", data)
    if magic != 0x50464442 or version not in (3, 4):
        raise DecodeError("Unsupported PARAM.PFD header.")
    buckets, reserved, used = struct.unpack_from(">QQQ", data, 96)
    if not 1 <= buckets <= 4096 or not 0 <= used <= reserved <= 4096:
        raise DecodeError("Invalid PARAM.PFD table dimensions.")
    start = 120 + buckets * 8
    if start + reserved * 272 > len(data):
        raise DecodeError("Truncated PARAM.PFD entry table.")
    entries = {}
    for index in range(used):
        record = memoryview(data)[start + index * 272 : start + (index + 1) * 272]
        filename_field = bytes(record[8:73])
        if b"\0" not in filename_field:
            raise DecodeError("PARAM.PFD contains an unterminated filename.")
        raw_name = filename_field.split(b"\0", 1)[0]
        try:
            name = raw_name.decode("ascii")
        except UnicodeDecodeError as error:
            raise DecodeError("PARAM.PFD contains an invalid filename.") from error
        if not name or name in (".", "..") or any(c in name for c in "/\\:"):
            raise DecodeError("PARAM.PFD filenames must identify files in the export folder.")
        canonical = name.casefold()
        if canonical in entries:
            raise DecodeError("PARAM.PFD contains duplicate filenames.")
        size = struct.unpack_from(">Q", record, 264)[0]
        entries[canonical] = ProtectedFile(
            name, bytes(record[80:144]), bytes(record[144:164]), size
        )
    return entries


def decrypt_chunk(ciphertext: bytes, entry: ProtectedFile, keys: SavedataKeys) -> bytes:
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

    if not 0 < len(ciphertext) <= MAX_REPLAY_BYTES or len(ciphertext) % 16:
        raise DecodeError(f"{entry.name}: invalid encrypted chunk length.")
    if entry.size <= 0 or (entry.size + 15) // 16 * 16 != len(ciphertext):
        raise DecodeError(f"{entry.name}: recorded and actual sizes differ.")
    authentication = keys.authentication_key
    mac = hmac.digest(authentication, ciphertext, "sha1")
    if not hmac.compare_digest(mac, entry.content_mac):
        raise DecodeError(f"{entry.name}: content integrity check failed.")
    if len(entry.key_material) != 64:
        raise DecodeError(f"{entry.name}: invalid wrapped key length.")
    unwrap = Cipher(algorithms.AES(keys.portability), modes.CBC(authentication[:16])).decryptor()
    file_key = (unwrap.update(entry.key_material) + unwrap.finalize())[:16]
    decrypt = Cipher(algorithms.AES(file_key), modes.ECB()).decryptor()
    masks = Cipher(algorithms.AES(file_key), modes.ECB()).encryptor()
    plaintext = bytearray()
    batch_size = 65536
    for offset in range(0, len(ciphertext), batch_size):
        batch = ciphertext[offset : offset + batch_size]
        count = len(batch) // 16
        counters = np.zeros((count, 2), dtype=">u8")
        counters[:, 0] = np.arange(offset // 16, offset // 16 + count, dtype=np.uint64)
        mask = masks.update(counters.tobytes())
        decoded = decrypt.update(batch)
        plaintext.extend(
            np.bitwise_xor(
                np.frombuffer(decoded, dtype=np.uint8), np.frombuffer(mask, dtype=np.uint8)
            ).tobytes()
        )
    decrypt.finalize()
    masks.finalize()
    return bytes(plaintext[: entry.size])


def read_export(path, keys: SavedataKeys | None = None) -> ReplayBytes:
    source = Path(path).expanduser().resolve()
    if source.is_file() and source.suffix.casefold() == ".rply":
        if not 0 < source.stat().st_size <= MAX_REPLAY_BYTES:
            raise DecodeError("Replay exceeds the supported input size.")
        with source.open("rb") as stream:
            data = stream.read(MAX_REPLAY_BYTES + 1)
        if len(data) > MAX_REPLAY_BYTES:
            raise DecodeError("Replay exceeds the supported input size.")
        if not data.startswith(b"RPLY"):
            raise DecodeError("The .rply file does not contain a decrypted replay.")
        return ReplayBytes(
            data,
            (
                {
                    "name": source.name,
                    "size_bytes": len(data),
                    "sha256": hashlib.sha256(data).hexdigest(),
                },
            ),
            False,
        )
    if source.is_file() and not re.fullmatch(r"REPLAY\.\d+|PARAM\.(?:PFD|SFO)", source.name, re.I):
        raise DecodeError("Choose a replay export folder, REPLAY.N, or .rply file.")
    folder = source if source.is_dir() else source.parent
    if not source.exists() or not folder.is_dir():
        raise DecodeError("Replay input does not exist.")
    files = {}
    chunks = {}
    for candidate in folder.iterdir():
        if not candidate.is_file():
            continue
        canonical = candidate.name.casefold()
        if canonical in files:
            raise DecodeError("The export contains ambiguous filenames.")
        files[canonical] = candidate
        match = re.fullmatch(r"replay\.(\d+)", canonical)
        if match:
            number = int(match[1])
            if number in chunks:
                raise DecodeError("The export contains duplicate chunk numbers.")
            chunks[number] = candidate
    if not chunks or len(chunks) > 4096 or sorted(chunks) != list(range(len(chunks))):
        raise DecodeError("The export must contain consecutive REPLAY.N chunks starting at zero.")
    sizes = [chunks[i].stat().st_size for i in range(len(chunks))]
    if min(sizes) <= 0 or sum(sizes) > MAX_REPLAY_BYTES:
        raise DecodeError("Replay chunks are empty or exceed the supported input size.")
    with chunks[0].open("rb") as first:
        protected = first.read(4) != b"RPLY"
    records = {}
    if protected:
        if "param.pfd" not in files:
            raise DecodeError("Encrypted chunks require PARAM.PFD from the same export.")
        pfd = files["param.pfd"]
        if pfd.stat().st_size > MAX_PFD_BYTES:
            raise DecodeError("PARAM.PFD exceeds the supported size.")
        with pfd.open("rb") as stream:
            records = read_pfd(stream.read(MAX_PFD_BYTES + 1))
        expected = {name for name in records if re.fullmatch(r"replay\.\d+", name)}
        actual = {chunk.name.casefold() for chunk in chunks.values()}
        if expected != actual:
            raise DecodeError("Replay chunks do not match PARAM.PFD.")
        if keys is None:
            raise SavedataKeyRequired(
                "Encrypted exports require a savedata key configuration. "
                "Choose a key file in Tools or use --keys PATH."
            )
    decoded, fingerprints = [], []
    for number in range(len(chunks)):
        chunk = chunks[number]
        with chunk.open("rb") as stream:
            content = stream.read(sizes[number] + 1)
        if len(content) != sizes[number]:
            raise DecodeError("Replay files changed while they were being read.")
        fingerprints.append(
            {
                "name": chunk.name,
                "size_bytes": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
            }
        )
        decoded.append(
            decrypt_chunk(content, records[chunk.name.casefold()], keys) if protected else content
        )
    data = b"".join(decoded)
    if len(data) < 0x300 or not data.startswith(b"RPLY"):
        raise DecodeError("The decoded export has no valid RPLY header.")
    return ReplayBytes(data, tuple(fingerprints), protected)
