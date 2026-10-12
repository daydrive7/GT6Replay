"""Bounded, most-significant-bit-first replay stream reader."""

import struct


class DecodeError(ValueError):
    pass


class BitReader:
    def __init__(self, data: bytes, start=0, end=None):
        self.data = memoryview(data)
        self.position = start
        self.end = len(data) * 8 if end is None else end
        if not 0 <= start <= self.end <= len(data) * 8:
            raise DecodeError("Invalid bitstream bounds.")

    def read(self, width: int) -> int:
        if not isinstance(width, int) or not 0 <= width <= 64:
            raise DecodeError("Bit fields must have a width from 0 to 64.")
        finish = self.position + width
        if finish > self.end:
            raise DecodeError(f"Truncated replay at bit {self.position}.")
        if width == 0:
            return 0
        first = self.position // 8
        last = (finish + 7) // 8
        value = int.from_bytes(self.data[first:last], "big")
        self.position = finish
        return (value >> (-finish % 8)) & ((1 << width) - 1)

    def signed(self, width: int) -> int:
        if width == 0:
            return 0
        value = self.read(width)
        return value - (1 << width) if value & (1 << (width - 1)) else value

    def flag(self) -> bool:
        return bool(self.read(1))

    def f32(self) -> float:
        return struct.unpack(">f", self.read(32).to_bytes(4, "big"))[0]

    def skip(self, width: int):
        if not isinstance(width, int) or width < 0 or self.position + width > self.end:
            raise DecodeError(f"Truncated replay at bit {self.position}.")
        self.position += width
