"""Read verified, decoded GT6 motion archives without a console or game engine."""

from __future__ import annotations
from collections.abc import Sequence
from pathlib import Path
import json, re, hashlib, zipfile, math
import numpy as np

COLUMNS = ("x", "y", "z", "vx", "vy", "vz", "qx", "qy", "qz", "qw", "rpm", "gear", "lap")


class NativeFrames(Sequence):
    def __init__(self, data, fps, slot, car_code=None):
        valid = np.isfinite(data[:, :3]).all(axis=1)
        self.frame_ids = np.flatnonzero(valid)
        self.data = data[valid]
        self.times = self.frame_ids.astype(np.float64) / fps
        self.speeds = np.linalg.norm(self.data[:, 3:6].astype(np.float64), axis=1) * 3.6
        self.slot, self.car_code = slot, car_code
        self.max_speed = float(self.speeds.max()) if len(self.data) else 0
        if len(self.data):
            low = self.data[:, :3].min(axis=0)
            high = self.data[:, :3].max(axis=0)
            self.coordinate_bounds = tuple(
                map(float, (low[0], high[0], low[1], high[1], low[2], high[2]))
            )
        else:
            self.coordinate_bounds = None

    def __len__(self):
        return len(self.data)

    def __getitem__(self, index):
        if isinstance(index, slice):
            return [self[i] for i in range(*index.indices(len(self)))]
        if index < 0:
            index += len(self)
        if index < 0 or index >= len(self):
            raise IndexError(index)
        row = self.data[index]
        frame = {name: float(value) for name, value in zip(COLUMNS, row) if np.isfinite(value)}
        frame.update(
            time_seconds=float(self.times[index]),
            speed_kmh=float(self.speeds[index]),
            packet_id=int(self.frame_ids[index]),
            native_slot=self.slot,
        )
        if self.car_code is not None:
            frame["car_code"] = self.car_code
        for key in ("gear", "lap"):
            if key in frame:
                frame[key] = int(frame[key])
        return frame


class NativeReplay:
    def __init__(self, path, motion, metadata, replay):
        self.path = Path(path)
        self.motion = motion
        self.metadata = metadata
        self.replay = replay
        self._frames = {}

    def frames_for_slot(self, slot, car_code=None):
        slots = self.metadata["slots"]
        if slot not in slots:
            return []
        key = (slot, car_code)
        if key not in self._frames:
            self._frames[key] = NativeFrames(
                self.motion[:, slots.index(slot), :], self.metadata["fps"], slot, car_code
            )
        return self._frames[key]


def _check_archive_headers(path):
    with zipfile.ZipFile(path) as container:
        limits = {"motion.npy": 512 * 1024**2, "metadata.npy": 1024**2, "replay.npy": 8 * 1024**2}
        for name, limit in limits.items():
            info = container.getinfo(name)
            if info.file_size > limit:
                raise ValueError("Replay exceeds the supported size limit.")
            with container.open(name) as stream:
                version = np.lib.format.read_magic(stream)
                reader = (
                    np.lib.format.read_array_header_1_0
                    if version == (1, 0)
                    else np.lib.format.read_array_header_2_0 if version == (2, 0) else None
                )
                if reader is None:
                    raise ValueError("Unsupported replay array header.")
                shape, fortran, dtype = reader(stream)
                if name == "motion.npy":
                    if (
                        dtype != np.dtype(np.float32)
                        or len(shape) != 3
                        or shape[1] < 1
                        or shape[1] > 32
                        or shape[2] != len(COLUMNS)
                    ):
                        raise ValueError("Unsupported native motion layout.")
                elif shape != () or dtype.kind not in ("U", "S"):
                    raise ValueError("Invalid replay metadata array.")
                length = math.prod(shape) * dtype.itemsize
                if length > limit or length + stream.tell() != info.file_size:
                    raise ValueError("Replay array size does not match its header.")


def load_native_replay(path, expected_sha256=None):
    path = Path(path)
    _check_archive_headers(path)
    with np.load(path, allow_pickle=False) as archive:
        metadata = json.loads(archive["metadata"].item())
        replay = json.loads(archive["replay"].item())
        motion = archive["motion"]
    if not isinstance(metadata, dict) or not isinstance(replay, dict):
        raise ValueError("Invalid replay metadata.")
    if metadata.get("format") != "gt6-native-motion-v1":
        raise ValueError("Unsupported native motion archive version.")
    digest = metadata.get("native_sha256", "")
    if not isinstance(digest, str) or not re.fullmatch("[0-9a-f]{64}", digest):
        raise ValueError("Native archive has no valid replay fingerprint.")
    if expected_sha256 is not None and digest != expected_sha256:
        raise ValueError("Decoded motion belongs to a different native replay.")
    slots = metadata.get("slots")
    fps = metadata.get("fps")
    frames = metadata.get("frame_count")
    if (
        not isinstance(slots, list)
        or not slots
        or len(slots) > 32
        or any(type(s) is not int or not 0 <= s < 32 for s in slots)
        or len(set(slots)) != len(slots)
    ):
        raise ValueError("Invalid native driver slots.")
    if fps != 60 or type(frames) is not int or frames <= 0:
        raise ValueError("Invalid native frame clock.")
    if (
        metadata.get("columns") != list(COLUMNS)
        or motion.dtype != np.float32
        or motion.shape != (frames, len(slots), len(COLUMNS))
    ):
        raise ValueError("Native motion array does not match its declared layout.")
    race = replay.get("metadata")
    entries = replay.get("entries")
    if not isinstance(race, dict) or not isinstance(entries, list) or not 1 <= len(entries) <= 32:
        raise ValueError("Missing race metadata or entrants.")
    entry_slots = []
    for entry in entries:
        if (
            not isinstance(entry, dict)
            or type(entry.get("slot")) is not int
            or entry["slot"] not in slots
            or not isinstance(entry.get("name"), str)
            or len(entry["name"]) > 512
        ):
            raise ValueError("Invalid replay entrant.")
        entry_slots.append(entry["slot"])
        for field in ("position", "total_time_ms", "best_lap_ms", "car_code"):
            value = entry.get(field)
            if value is not None and type(value) is not int:
                raise ValueError("Invalid result value.")
        if entry.get("car_name") is not None and not isinstance(entry["car_name"], str):
            raise ValueError("Invalid car name.")
    if len(set(entry_slots)) != len(entry_slots) or set(entry_slots) != set(slots):
        raise ValueError("Replay entrants do not match driver slots.")
    for field in ("track", "event", "title", "race_type", "recorded_at", "driver"):
        if race.get(field) is not None and not isinstance(race[field], str):
            raise ValueError("Invalid race description.")
    valid = np.isfinite(motion[:, :, :3]).all(axis=2)
    if not valid.any():
        raise ValueError("Native archive contains no decoded positions.")
    if not np.isfinite(motion[valid]).all():
        raise ValueError("Native archive contains incomplete instrument values.")
    if (
        replay.get("native_sha256") != digest
        or replay.get("metadata", {}).get("total_frames") != frames
    ):
        raise ValueError("Native motion does not match its race metadata.")
    return NativeReplay(path, motion, metadata, replay)


def find_native_replay(replay, directory):
    digest = replay.get("native_sha256")
    if not digest:
        return None
    for path in Path(directory).glob("*.gt6r"):
        try:
            _check_archive_headers(path)
            with np.load(path, allow_pickle=False) as archive:
                metadata = json.loads(archive["metadata"].item())
            if isinstance(metadata, dict) and metadata.get("native_sha256") == digest:
                return load_native_replay(path, digest)
        except (ValueError, KeyError, TypeError, OSError, zipfile.BadZipFile):
            continue
    return None


def find_native_for_input(source, directories):
    source = Path(source).resolve()
    if not source.exists():
        return None
    if (
        source.is_file()
        and source.suffix.lower() != ".rply"
        and source.name.casefold() not in ("param.sfo", "param.pfd")
        and not re.fullmatch(r"REPLAY\.\d+", source.name, re.I)
    ):
        return None
    folder = source if source.is_dir() else source.parent
    if source.is_file() and source.suffix.lower() == ".rply":
        parts = [source]
    else:
        parts = sorted(
            p
            for p in folder.iterdir()
            if p.is_file() and re.fullmatch(r"REPLAY\.\d+", p.name, re.I)
        )
    if not parts:
        return None
    actual = None
    for directory in directories:
        for path in Path(directory).glob("*.gt6r"):
            try:
                _check_archive_headers(path)
                with np.load(path, allow_pickle=False) as archive:
                    replay = json.loads(archive["replay"].item())
                if not isinstance(replay, dict):
                    continue
                recorded = {
                    item["name"].casefold(): item["sha256"] for item in replay.get("files", [])
                }
                if set(recorded) != {p.name.casefold() for p in parts}:
                    continue
                if actual is None:
                    actual = {}
                    for part in parts:
                        digest = hashlib.sha256()
                        with part.open("rb") as stream:
                            for block in iter(lambda: stream.read(1024**2), b""):
                                digest.update(block)
                        actual[part.name.casefold()] = digest.hexdigest()
                if actual == recorded:
                    return load_native_replay(path)
            except (ValueError, KeyError, TypeError, AttributeError, OSError, zipfile.BadZipFile):
                continue
    return None
