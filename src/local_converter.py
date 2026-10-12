"""Interface to a decoder supplied by the user."""

from pathlib import Path
import os, subprocess, sys, shutil, uuid
from native_motion import load_native_replay


def find_local_converter(program_directory=None):
    value = os.environ.get("GT6REPLAY_DECODER", "").strip()
    if not value:
        return None
    decoder = Path(value).expanduser().resolve()
    if not decoder.is_file():
        raise ValueError("The configured decoder does not exist.")
    if decoder.suffix.lower() == ".py":
        python = shutil.which("python") if getattr(sys, "frozen", False) else sys.executable
        if not python:
            raise ValueError("The configured Python decoder needs a Python installation.")
        return [python, str(decoder)]
    return [str(decoder)]


def cache_directory():
    root = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / ".local/share")))
    return root / "GT6Replay" / "Native"


def convert_path(path, progress, expected_sha256=None):
    command = find_local_converter()
    if command is None:
        raise ValueError(
            "This save needs an external decoder. Open a decoded .gt6r replay or set GT6REPLAY_DECODER to a decoder you have installed."
        )
    directory = cache_directory()
    directory.mkdir(parents=True, exist_ok=True)
    pending = directory / (uuid.uuid4().hex + ".part")
    command += ["--input", str(Path(path).resolve()), "--output", str(pending)]
    lines = []
    progress("Converting replay…")
    with subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    ) as process:
        for line in process.stdout:
            line = line.strip()
            if line:
                lines = (lines + [line])[-8:]
            if "frames verified" in line:
                progress("Converting replay · " + line.split(";")[0])
        code = process.wait()
    if code:
        pending.unlink(missing_ok=True)
        raise ValueError("Decoder failed: " + "\n".join(lines))
    native = load_native_replay(pending, expected_sha256)
    output = directory / (native.metadata["native_sha256"] + ".gt6r")
    pending.replace(output)
    native.path = output
    return native


def convert_local_replay(replay, program_directory, progress):
    return convert_path(replay["source_path"], progress, replay.get("native_sha256"))
