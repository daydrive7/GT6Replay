"""Optional local savedata configuration shared by the viewer and decoder."""

from pathlib import Path
import json
import os
import re
import tempfile

from .bitstream import DecodeError


def settings_path():
    root = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / ".local/share")))
    return root / "GT6Replay" / "settings.json"


def key_file_path(explicit=None):
    if explicit:
        return Path(explicit).expanduser().resolve()
    environment = os.environ.get("GT6REPLAY_KEY_FILE", "").strip()
    if environment:
        return Path(environment).expanduser().resolve()
    config = settings_path()
    if not config.is_file():
        return None
    try:
        with config.open("r", encoding="utf-8") as stream:
            text = stream.read(65537)
        if len(text) > 65536:
            raise ValueError()
        value = json.loads(text).get("savedata_key_file")
        if value is not None and not isinstance(value, str):
            raise ValueError()
    except (ValueError, AttributeError, OSError) as error:
        raise DecodeError("Could not read the local decoder settings.") from error
    return Path(value).expanduser().resolve() if value else None


def load_keys(explicit=None):
    from .savedata import SavedataKeys, SavedataKeyRequired

    path = key_file_path(explicit)
    if path is None:
        raise SavedataKeyRequired(
            "Encrypted exports require a savedata key configuration. "
            "Choose a key file in Tools or use --keys PATH."
        )
    try:
        with path.open("r", encoding="utf-8-sig") as stream:
            text = stream.read(4097)
        if len(text) > 4096:
            raise ValueError()
        config = json.loads(text)
        values = [config[field] for field in ("portability_key", "secure_file_id")]
        if any(
            not isinstance(value, str) or not re.fullmatch(r"[0-9a-fA-F]{32}", value)
            for value in values
        ):
            raise ValueError()
        return SavedataKeys(*(bytes.fromhex(value) for value in values))
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise DecodeError(
            "Invalid savedata key file. Expected portability_key and secure_file_id, "
            "each containing 32 hexadecimal characters."
        ) from error


def configure_key_file(path):
    resolved = key_file_path(path)
    load_keys(resolved)
    target = settings_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    pending = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=target.parent, delete=False
        ) as stream:
            pending = Path(stream.name)
            json.dump({"savedata_key_file": str(resolved)}, stream)
        pending.replace(target)
    finally:
        if pending is not None:
            pending.unlink(missing_ok=True)


def clear_key_file():
    settings_path().unlink(missing_ok=True)
