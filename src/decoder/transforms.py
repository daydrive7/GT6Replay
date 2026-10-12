"""Absolute transform record used at replay seek checkpoints."""

from dataclasses import dataclass
import math

from .bitstream import DecodeError


@dataclass(frozen=True)
class Transform:
    position: tuple[float, float, float]
    velocity: tuple[float, float, float]
    angular_velocity: tuple[float, float, float]
    quaternion: tuple[float, float, float, float]

    @classmethod
    def read_absolute(cls, reader):
        velocity = tuple(reader.f32() for _ in range(3))
        position = tuple(reader.f32() for _ in range(3))
        angular = tuple(reader.f32() for _ in range(3))
        quaternion = tuple(reader.f32() for _ in range(4))
        if not all(math.isfinite(value) for value in (*position, *velocity, *angular, *quaternion)):
            raise DecodeError("Replay transform contains non-finite values.")
        norm = sum(value * value for value in quaternion)
        if not 0.5 < norm < 1.5:
            raise DecodeError("Replay transform contains an invalid quaternion.")
        return cls(position, velocity, angular, quaternion)
