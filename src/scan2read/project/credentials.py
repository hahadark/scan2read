"""Store one API key per AI provider, each encrypted for the current Windows user."""
import base64
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path


class _Blob(ctypes.Structure):
    _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_byte))]


def _crypt(value: bytes, protect: bool, description: str) -> bytes:
    if os.name != "nt":
        raise OSError("Secure API-key storage is currently available on Windows only")
    source_buffer = ctypes.create_string_buffer(value)
    source = _Blob(len(value), ctypes.cast(source_buffer, ctypes.POINTER(ctypes.c_byte)))
    result = _Blob()
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.LocalFree.argtypes = [wintypes.HLOCAL]
    kernel32.LocalFree.restype = wintypes.HLOCAL
    function = crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
    if protect:
        ok = function(ctypes.byref(source), description, None, None, None,
                      0x1, ctypes.byref(result))
    else:
        ok = function(ctypes.byref(source), None, None, None, None, 0x1, ctypes.byref(result))
    if not ok:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return ctypes.string_at(result.data, result.size)
    finally:
        kernel32.LocalFree(result.data)


def _load_record(path: Path) -> dict:
    """Read the on-disk record, migrating a v1 (single OpenAI key) file into
    the v2 per-provider shape without touching its still-encrypted bytes."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return {"version": 2, "keys": {}}
    if data.get("version") == 1 and "ciphertext" in data:
        return {"version": 2, "keys": {"openai": {"ciphertext": data["ciphertext"]}}}
    if data.get("version") == 2 and isinstance(data.get("keys"), dict):
        return data
    return {"version": 2, "keys": {}}


def save_api_key(path: Path, provider: str, api_key: str) -> None:
    key = api_key.strip()
    record = _load_record(path)
    if key:
        encrypted = _crypt(key.encode("utf-8"), True, f"Scan2Read {provider} API key")
        record["keys"][provider] = {"ciphertext": base64.b64encode(encrypted).decode("ascii")}
    else:
        record["keys"].pop(provider, None)
    if not record["keys"]:
        path.unlink(missing_ok=True)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(record), encoding="utf-8")
    temporary.replace(path)


def load_api_key(path: Path, provider: str) -> str:
    entry = _load_record(path)["keys"].get(provider)
    if not entry:
        return ""
    try:
        encrypted = base64.b64decode(entry["ciphertext"], validate=True)
        return _crypt(encrypted, False, "").decode("utf-8")
    except (OSError, ValueError, KeyError, UnicodeError, json.JSONDecodeError):
        return ""
