"""Working decoder stages and atomic exports used by both front ends."""

from pathlib import Path
import json
import os
import re
import tempfile

from version import VERSION
from replay_data import replay_from_bytes, _sfo, _case_file
from .bitstream import DecodeError
from .container import ReplayIndex
from .savedata import read_export, SavedataKeyRequired
from .settings import load_keys

CAPABILITIES = {
    "savedata_decryption": True,
    "race_metadata": True,
    "rply_export": True,
    "motion_archive": False,
}


class MotionUnavailableError(DecodeError):
    pass


def inspect_input(path, key_file=None, progress=None):
    notify = progress or (lambda message: None)
    notify("Reading replay files…")
    try:
        container = read_export(path)
    except SavedataKeyRequired:
        notify("Decrypting replay files…")
        container = read_export(path, load_keys(key_file))
    source = Path(path).expanduser().resolve()
    folder = source if source.is_dir() else source.parent
    sfo = {} if source.suffix.lower() == ".rply" else _sfo(_case_file(folder, "PARAM.SFO"))
    replay = replay_from_bytes(
        container.data,
        source,
        "ps3_savedata" if container.protected else "raw_rply",
        container.source_files,
        sfo,
        container.protected,
    )
    notify("Reading race information…")
    index_info = None
    try:
        index = ReplayIndex.read(container.data)
        index_info = {
            "frame_count": index.frame_count,
            "encoding_slots": len(index.encodings),
            "seek_segments": len(index.seek_points) - 1,
            "protocols": list(index.protocols),
        }
    except DecodeError as error:
        replay["warnings"].append(str(error))
    report = {
        "format": "gt6-decoder-inspection-v1",
        "version": VERSION,
        "capabilities": dict(CAPABILITIES),
        "motion_index": index_info,
        "replay": replay,
    }
    return container, report


def validate_output(source, output):
    source, output = Path(source).expanduser().resolve(), Path(output).expanduser().resolve()
    if source == output:
        raise DecodeError("The output must not replace the input replay.")
    folder = source if source.is_dir() else source.parent
    if source.is_dir() or source.suffix.lower() != ".rply":
        if output.is_relative_to(folder):
            raise DecodeError("Choose an output outside the original save folder.")
    if output.suffix.lower() in (".pfd", ".sfo") or re.fullmatch(r"replay\.\d+", output.name, re.I):
        raise DecodeError("The output must not replace a savedata file.")
    return output


def atomic_export(path, payload, overwrite=False):
    path = Path(path)
    if path.exists() and not overwrite:
        raise DecodeError("The output already exists. Choose another filename or use --overwrite.")
    path.parent.mkdir(parents=True, exist_ok=True)
    pending = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=path.parent, prefix=".gt6-export-", suffix=".part", delete=False
        ) as stream:
            pending = Path(stream.name)
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        if overwrite:
            pending.replace(path)
        elif os.name == "nt":
            pending.rename(path)
        else:
            os.link(pending, path)
        return path
    finally:
        if pending is not None:
            pending.unlink(missing_ok=True)


def export_input(source, output, format="rply", key_file=None, overwrite=False, progress=None):
    if format == "motion":
        raise MotionUnavailableError(
            "Full motion conversion is not available in this development build. "
            "Use --format rply to export decrypted data, or --format report for race information."
        )
    if format not in ("rply", "report"):
        raise DecodeError("Unknown export format.")
    output = validate_output(source, output)
    suffix = ".rply" if format == "rply" else ".json"
    if output.suffix.lower() != suffix:
        raise DecodeError(f"Choose a {suffix} filename for this export format.")
    if output.exists() and not overwrite:
        raise DecodeError("The output already exists. Choose another filename or use --overwrite.")
    container, report = inspect_input(source, key_file, progress)
    if format == "rply":
        payload = container.data
    else:
        payload = (json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode(
            "utf-8"
        )
    if progress:
        progress("Writing export…")
    atomic_export(output, payload, overwrite)
    return report
