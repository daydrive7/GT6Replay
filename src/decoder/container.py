"""Version-115 motion-stream index and per-slot encoding parameters."""

from dataclasses import dataclass
import math
import struct

from .bitstream import BitReader, DecodeError


def _coefficients(reader, count):
    values = tuple(reader.f32() for _ in range(count))
    if not all(math.isfinite(value) for value in values):
        raise DecodeError("Motion encoding parameters contain non-finite coefficients.")
    return values


@dataclass(frozen=True)
class VectorEncoding:
    width: int
    coefficients: tuple[float, ...]

    @classmethod
    def read(cls, reader):
        width = reader.read(6)
        return cls(width, _coefficients(reader, 6))


@dataclass(frozen=True)
class ScalarEncoding:
    width: int
    flags: tuple[bool, bool]
    coefficients: tuple[float, ...]

    @classmethod
    def read(cls, reader):
        width = reader.read(6)
        flags = (reader.flag(), reader.flag())
        return cls(width, flags, _coefficients(reader, 3))


@dataclass(frozen=True)
class WheelEncoding:
    reference_words: tuple[int, int]
    vector: VectorEncoding
    scalar: ScalarEncoding

    @classmethod
    def read(cls, reader):
        reference = (reader.read(32), reader.read(32))
        return cls(reference, VectorEncoding.read(reader), ScalarEncoding.read(reader))


@dataclass(frozen=True)
class SlotEncoding:
    reference_words: tuple[int, int]
    wheels: tuple[WheelEncoding, ...]
    control_widths: tuple[int, int]
    vectors: tuple[VectorEncoding, ...]
    scalars: tuple[ScalarEncoding, ...]

    @classmethod
    def read(cls, reader):
        reference = (reader.read(32), reader.read(32))
        wheels = tuple(WheelEncoding.read(reader) for _ in range(4))
        widths = (reader.read(6), reader.read(6))
        vectors, scalars = [], []
        for _ in range(2):
            vectors.append(VectorEncoding.read(reader))
            scalars.append(ScalarEncoding.read(reader))
        vectors.append(VectorEncoding.read(reader))
        vectors.append(VectorEncoding.read(reader))
        scalars.append(ScalarEncoding.read(reader))
        vectors.append(VectorEncoding.read(reader))
        vectors.append(VectorEncoding.read(reader))
        for _ in range(6):
            vectors.append(VectorEncoding.read(reader))
            scalars.append(ScalarEncoding.read(reader))
        vectors.append(VectorEncoding.read(reader))
        scalars.append(ScalarEncoding.read(reader))
        vectors.append(VectorEncoding.read(reader))
        scalars.extend(ScalarEncoding.read(reader) for _ in range(4))
        return cls(reference, wheels, widths, tuple(vectors), tuple(scalars))


@dataclass(frozen=True)
class SeekPoint:
    byte_offset: int
    frame: int


@dataclass(frozen=True)
class ReplayIndex:
    frame_count: int
    protocols: tuple[int, int, int]
    seek_points: tuple[SeekPoint, ...]
    encodings: tuple[SlotEncoding, ...]
    parameter_end_bit: int

    @classmethod
    def read(cls, data: bytes):
        if len(data) < 0x300 or data[:4] != b"RPLY":
            raise DecodeError("Expected a decrypted GT6 RPLY file.")

        def u32(offset):
            return struct.unpack_from(">I", data, offset)[0]

        if u32(8) != 115:
            raise DecodeError("The independent reader currently supports RPLY version 115.")
        protocols = struct.unpack_from(">3I", data, 0x10)
        if protocols != (21, 17, 49):
            raise DecodeError(f"Unsupported motion protocols: {protocols}.")
        frames = u32(0x248)
        stream, count, table = u32(0x264), u32(0x28C), u32(0x294)
        if not 0 < frames <= 60 * 60 * 60 * 24:
            raise DecodeError("Invalid replay frame count.")
        if not 2 <= count <= 4096 or table < 0x300 or table + count * 8 > len(data):
            raise DecodeError("Invalid replay seek table.")
        points = tuple(
            SeekPoint(*struct.unpack_from(">II", data, table + i * 8)) for i in range(count)
        )
        if points[0].frame != 0 or points[-1].frame != frames:
            raise DecodeError("Seek table does not span the recorded frames.")
        if not 0x300 <= stream < points[0].byte_offset:
            raise DecodeError("Invalid replay parameter offset.")
        if any(not stream < point.byte_offset < len(data) for point in points):
            raise DecodeError("Seek point lies outside the motion stream.")
        if any(
            a.frame >= b.frame or a.byte_offset >= b.byte_offset for a, b in zip(points, points[1:])
        ):
            raise DecodeError("Seek points must increase in both frame and byte position.")
        slots = data[stream]
        if not 1 <= slots <= 32:
            raise DecodeError("Invalid number of motion encoding slots.")
        reader = BitReader(data, (stream + 1) * 8, points[0].byte_offset * 8)
        encodings = tuple(SlotEncoding.read(reader) for _ in range(slots))
        padding = reader.end - reader.position
        if padding > 7 or reader.read(padding):
            raise DecodeError("Unexpected bytes after the motion parameters.")
        return cls(frames, protocols, points, encodings, reader.position - padding)
