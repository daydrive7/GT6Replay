"""Read decrypted RPLY metadata. Header references: Nenkai/PDTools (MIT)."""

from __future__ import annotations
import datetime as _dt
import hashlib, re, struct
from pathlib import Path


class ReplayError(ValueError):
    pass


class EncryptedReplayError(ReplayError):
    pass


_INVALID_TIME = 1209599999
_FRAME_RATE = 60
_DECODE_REASON = "Motion playback requires a matching decoded .gt6r file."
_CAR_NAMES = {}
_COURSE_NAMES = {}


def _range(data: bytes, offset: int, size: int, label: str) -> bytes:
    if offset < 0 or size < 0 or offset + size > len(data):
        raise ReplayError(f"{label} points outside the file (input is truncated).")
    return data[offset : offset + size]


def _u32(data: bytes, offset: int) -> int:
    return struct.unpack(">I", _range(data, offset, 4, "Replay field"))[0]


def _text(data: bytes) -> str:
    value = data.split(b"\x00", 1)[0]
    try:
        return value.decode("utf-8").strip()
    except UnicodeDecodeError:
        return value.decode("cp1252", "replace").strip()


def _sfo(path: Path) -> dict:
    if not path.is_file():
        return {}
    with path.open("rb") as stream:
        data = stream.read(1024**2 + 1)
    if len(data) > 1024**2:
        raise ReplayError("PARAM.SFO exceeds the supported size.")
    if len(data) < 20 or data[:4] != b"\x00PSF":
        raise ReplayError("PARAM.SFO has an invalid PSF header.")
    _, _, key_offset, data_offset, count = struct.unpack_from("<4s4I", data)
    if count > 4096 or 20 + 16 * count > len(data):
        raise ReplayError("PARAM.SFO has an invalid index table.")
    result = {}
    for index in range(count):
        key_pos, fmt, length, maximum, value_pos = struct.unpack_from(
            "<HHIII", data, 20 + index * 16
        )
        if length > maximum:
            raise ReplayError("PARAM.SFO has an invalid value length.")
        key = _text(_range(data, key_offset + key_pos, len(data) - key_offset - key_pos, "SFO key"))
        value = _range(data, data_offset + value_pos, length, "SFO value")
        if fmt == 516:
            result[key] = _text(value)
        elif fmt == 1028 and length == 4:
            result[key] = struct.unpack("<I", value)[0]
    return result


def _part_paths(folder: Path) -> list[Path]:
    parts = {}
    for path in folder.iterdir():
        match = re.fullmatch("REPLAY\\.(\\d+)", path.name, re.IGNORECASE)
        if match and path.is_file():
            index = int(match.group(1))
            if index in parts:
                raise ReplayError("Replay folder contains duplicate chunk numbers.")
            parts[index] = path
    if not parts or 0 not in parts:
        raise ReplayError("The selected folder does not contain REPLAY.0.")
    if max(parts) > 4096:
        raise ReplayError("The replay folder has an invalid chunk number.")
    if sorted(parts) != list(range(max(parts) + 1)):
        raise ReplayError("The replay is incomplete: a REPLAY.N chunk is missing.")
    return [parts[index] for index in sorted(parts)]


def _case_file(folder: Path, name: str) -> Path:
    return next(
        (p for p in folder.iterdir() if p.name.casefold() == name.casefold()), folder / name
    )


def _time(value: int) -> int | None:
    return value if 0 < value < _INVALID_TIME else None


def _parse_native(data: bytes, sfo: dict, warnings: list[str]) -> tuple[dict, list[dict]]:
    if len(data) < 768 or data[:4] != b"RPLY":
        raise ReplayError("Decoded input does not have a GT6 RPLY header.")
    version = _u32(data, 8)
    if version != 115:
        raise ReplayError(
            f"Replay version {version} is unsupported. This build supports the verified GT6 version 115 layout."
        )
    maximum = _u32(data, 576)
    entry_offset = _u32(data, 580)
    stride = struct.unpack_from(">H", data, 642)[0]
    if not 0 < maximum <= 32 or not 112 <= stride <= 4096:
        raise ReplayError("The replay entrant table has invalid dimensions.")
    _range(data, entry_offset, maximum * stride, "Replay entrant table")
    orders = struct.unpack_from(">32h", data, 128)
    totals = struct.unpack_from(">32I", data, 192)
    bests = struct.unpack_from(">32I", data, 320)
    entries = []
    for slot in range(maximum):
        offset = entry_offset + slot * stride
        index, car_offset = struct.unpack_from(">ii", data, offset)
        if index == -1:
            continue
        if not 0 <= index < 32:
            raise ReplayError(f"Entrant slot {slot} has an invalid index.")
        name = _text(_range(data, offset + 96, 16, "Entrant name")) or f"Driver {index + 1}"
        car_version = _u32(data, car_offset)
        car_code = None
        if car_version in (108, 109):
            car_code = struct.unpack(">i", _range(data, car_offset + 96, 4, "Car code"))[0]
        else:
            warnings.append(
                f"The car parameter version for {name} ({car_version}) is unsupported; its car code is unavailable."
            )
        sectors = list(struct.unpack(">16I", _range(data, offset + 32, 64, "Sector times")))
        sectors = [value for value in sectors if value < _INVALID_TIME]
        if (
            not sectors
            or any((value <= 0 for value in sectors))
            or any((a >= b for a, b in zip(sectors, sectors[1:])))
        ):
            sectors = []
        total = _time(totals[slot])
        entries.append(
            {
                "slot": slot,
                "entry_index": index,
                "name": name,
                "position": (
                    orders[slot] + 1 if total is not None and 0 <= orders[slot] < maximum else None
                ),
                "finish_order_raw": orders[slot],
                "total_time_ms": total,
                "best_lap_ms": _time(bests[slot]),
                "sector_times_ms": sectors,
                "car_code": car_code,
                "car_name": _CAR_NAMES.get(
                    car_code, f"Car #{car_code}" if car_code is not None else "Unknown car"
                ),
                "car_parameter_version": car_version,
            }
        )
    detail_lines = sfo.get("DETAIL", "").splitlines()
    title = sfo.get("TITLE", "Gran Turismo 6 Replay").replace("�", " ")
    track = detail_lines[1] if len(detail_lines) > 1 else "Unknown track"
    car = detail_lines[2] if len(detail_lines) > 2 else ""
    driver = detail_lines[3].removeprefix("Driver:") if len(detail_lines) > 3 else ""
    try:
        raw_date = struct.unpack_from(">Q", data, 40)[0]
        recorded = _dt.datetime.fromtimestamp(raw_date - 210866760000, _dt.timezone.utc)
        if not 1990 <= recorded.year <= 2200:
            raise ValueError("Date out of expected range")
        recorded_utc = recorded.isoformat()
    except (ValueError, OverflowError, OSError):
        recorded_utc = None
        warnings.append("The native replay date could not be decoded.")
    game_size = _u32(data, 528)
    game_offset = _u32(data, 532)
    game_parameter = _range(data, game_offset, game_size, "Game parameter")
    event = None
    room_marker = game_parameter.find(bytes.fromhex("E6E6D845"))
    if room_marker >= 0 and room_marker + 12 <= len(game_parameter):
        comment_size = _u32(game_parameter, room_marker + 8)
        if 0 < comment_size <= 1024 and room_marker + 12 + comment_size <= len(game_parameter):
            event = (
                _text(game_parameter[room_marker + 12 : room_marker + 12 + comment_size]) or None
            )
    course_code = None
    course_marker = game_parameter.find(bytes.fromhex("E6E6C344"))
    if course_marker >= 0 and course_marker + 20 <= len(game_parameter):
        course_version = _u32(game_parameter, course_marker + 4)
        if course_version in (101, 102, 103):
            course_code = struct.unpack_from(">Q", game_parameter, course_marker + 12)[0]
            if track == "Unknown track":
                track = _COURSE_NAMES.get(course_code, f"Course #{course_code}")
    frames = _u32(data, 584)
    _range(data, _u32(data, 612), 1, "Native frame stream")
    metadata = {
        "title": title,
        "track": track,
        "course_code": course_code,
        "car": car,
        "driver": driver,
        "race_type": detail_lines[0] if detail_lines else "",
        "recorded_at": detail_lines[4] if len(detail_lines) > 4 else recorded_utc,
        "recorded_at_utc": recorded_utc,
        "event": event,
        "version": version,
        "gt_behavior_version": _u32(data, 32),
        "specdb_version": _u32(data, 36),
        "total_frames": frames,
        "duration_seconds": frames / _FRAME_RATE,
        "fps_assumed": _FRAME_RATE,
        "entry_count": len(entries),
        "header_entry_count": _u32(data, 636),
        "race_completed": bool(_u32(data, 116)),
        "best_lap_only": bool(_u32(data, 120)),
        "size_bytes": len(data),
        "frame_stream_offset": _u32(data, 612),
        "active_driver_mask": _u32(data, 648),
        "seek_entry_count": _u32(data, 652),
        "seek_table_size": _u32(data, 656),
        "seek_table_offset": _u32(data, 660),
    }
    if metadata["header_entry_count"] != len(entries):
        warnings.append(
            "The replay's recorded entrant count differs from its active entrant table."
        )
    warnings.append("Replay duration uses GT6's 60 Hz frame clock.")
    warnings.append(_DECODE_REASON)
    return (metadata, entries)


def replay_from_bytes(data, source, source_type, files, sfo=None, protected=False):
    warnings = []
    metadata, entries = _parse_native(data, sfo or {}, warnings)
    return {
        "source_path": str(Path(source).resolve()),
        "source_type": source_type,
        "native_sha256": hashlib.sha256(data).hexdigest(),
        "protected": protected,
        "metadata": metadata,
        "entries": entries,
        "files": list(files),
        "warnings": warnings,
        "frames": [],
        "native_decode_available": False,
        "decode_reason": _DECODE_REASON,
    }


def load_replay(path):
    if path == "":
        raise ReplayError("Choose a replay file or save folder.")
    try:
        source = Path(path).expanduser().resolve()
    except (TypeError, ValueError, OSError) as exc:
        raise ReplayError("Invalid replay path.") from exc
    if not source.exists():
        raise ReplayError("Replay input does not exist.")
    sfo = {}
    warnings = []
    files = []
    if source.is_file() and source.suffix.lower() == ".rply":
        parts = [source]
        source_type = "raw_rply"
    else:
        folder = source if source.is_dir() else source.parent
        if (
            source.is_file()
            and source.name.lower() not in ("param.sfo", "param.pfd")
            and not re.fullmatch(r"replay\.\d+", source.name, re.I)
        ):
            raise ReplayError("Choose a replay folder, REPLAY.0, or .rply file.")
        parts = _part_paths(folder)
        sfo = _sfo(_case_file(folder, "PARAM.SFO"))
        source_type = "raw_replay_folder"
    decoded = []
    for i, part in enumerate(parts):
        data = part.read_bytes()
        if i == 0 and not data.startswith(b"RPLY"):
            raise EncryptedReplayError(
                "This save needs an external decoder. Open its decoded .gt6r file or configure a decoder."
            )
        if not data:
            raise ReplayError("A replay part is empty.")
        files.append(
            {"name": part.name, "size_bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
        )
        decoded.append(data)
    data = b"".join(decoded)
    return replay_from_bytes(data, source, source_type, files, sfo)


inspect_replay = load_replay
