"""Interface to a decoder supplied by the user."""

from pathlib import Path
import os, subprocess, sys, shutil, uuid
from native_motion import load_native_replay


def find_decoder_program(program_directory=None, cli=False):
    directory = (
        Path(program_directory)
        if program_directory
        else Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).parent
    )
    name = "GT6ReplayDecoderCLI.exe" if cli else "GT6ReplayDecoder.exe"
    for path in (
        directory / "Decoder" / name,
        directory / name,
        directory.parent / "GT6ReplayDecoder" / name,
    ):
        if path.is_file():
            return [str(path)]
    if not getattr(sys, "frozen", False):
        script = directory / "decoder_program.py"
        if script.is_file():
            return [sys.executable, str(script), "--cli" if cli else "--gui"]
    return None


def has_motion_converter():
    return bool(os.environ.get("GT6REPLAY_DECODER", "").strip())


def launch_decoder(program_directory=None):
    command = find_decoder_program(program_directory)
    if command is None:
        raise ValueError(
            "GT6Replay Decoder is missing. Install the complete development package or build it with scripts/build_decoder.ps1."
        )
    options = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
    return subprocess.Popen(command, **options)


def find_local_converter(program_directory=None):
    value = os.environ.get("GT6REPLAY_DECODER", "").strip()
    if not value:
        return find_decoder_program(program_directory, cli=True)
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


def convert_path(path, progress, expected_sha256=None, program_directory=None):
    if not has_motion_converter():
        from decoder.operations import MotionUnavailableError

        raise MotionUnavailableError(
            "The included decoder exports decrypted replay data and race reports. Full motion conversion is not yet available."
        )
    command = find_local_converter(program_directory)
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
    try:
        native = load_native_replay(pending, expected_sha256)
        output = directory / (native.metadata["native_sha256"] + ".gt6r")
        pending.replace(output)
        native.path = output
        return native
    finally:
        pending.unlink(missing_ok=True)


def convert_local_replay(replay, program_directory, progress):
    return convert_path(
        replay["source_path"], progress, replay.get("native_sha256"), program_directory
    )
