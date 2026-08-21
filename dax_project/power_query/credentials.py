from __future__ import annotations

import base64
import ctypes
import ctypes.wintypes
import datetime as _dt
import hashlib
import hmac
import json
import os
import re
import secrets
import uuid
from pathlib import Path
from typing import Any, Mapping


_SENSITIVE_KEY_RE = re.compile(r"(password|pwd|secret|token|api[_-]?key|authorization|account[_-]?key|access[_-]?key)", re.I)
_CONNECTION_SECRET_RE = re.compile(
    r"(?i)\b(password|pwd|token|access token|api key|apikey|secret|accountkey)\s*=\s*([^;]+)"
)
_BEARER_RE = re.compile(r"(?i)\b(Bearer)\s+[A-Za-z0-9._~+/\-=]+")

PROFILE_METADATA_KEYS = (
    "tenant_id",
    "authority",
    "scopes",
    "resource_url",
    "site_id",
    "drive_id",
    "list_id",
    "workspace_id",
    "dataflow_id",
    "server",
    "database",
    "account_url",
    "container",
    "api_version",
)

PROFILE_CERTIFICATION_KEYS = (
    "live_certification",
    "last_certified_at",
    "last_certification_result",
    "certified_functions",
    "missing_permissions",
    "missing_sdk",
    "smoke_resource",
)


def _now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat()


def credential_profiles_path(project_root: str | os.PathLike[str]) -> Path:
    root = Path(project_root or ".")
    return root / ".dummy_bi" / "power_query_credential_profiles.json"


def _secret_store_path() -> Path:
    override = os.environ.get("DUMMY_BI_PQ_SECRET_STORE")
    if override:
        return Path(override)
    base = os.environ.get("LOCALAPPDATA")
    if base:
        return Path(base) / "DummyBI" / "power_query_secret_store.json"
    return Path.home() / ".dummy_bi" / "power_query_secret_store.json"


def redact_text(value: str) -> str:
    text = str(value)
    text = _CONNECTION_SECRET_RE.sub(lambda match: f"{match.group(1)}=***REDACTED***", text)
    text = _BEARER_RE.sub(lambda match: f"{match.group(1)} ***REDACTED***", text)
    return text


def redact_secret_value(value: Any, *, key: str = "") -> Any:
    if key in {"secret_ref", "credential_profile_id", "profile_id"}:
        return redact_text(value) if isinstance(value, str) else value
    if key and _SENSITIVE_KEY_RE.search(key):
        return "***REDACTED***"
    if isinstance(value, Mapping):
        return {str(k): redact_secret_value(v, key=str(k)) for k, v in value.items()}
    if isinstance(value, list):
        return [redact_secret_value(item) for item in value]
    if isinstance(value, tuple):
        return [redact_secret_value(item) for item in value]
    if isinstance(value, str):
        return redact_text(value)
    return value


def _json_bytes(payload: Mapping[str, Any]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _dpapi_crypt(data: bytes, *, protect: bool) -> bytes:
    class DATA_BLOB(ctypes.Structure):
        _fields_ = [
            ("cbData", ctypes.wintypes.DWORD),
            ("pbData", ctypes.POINTER(ctypes.c_char)),
        ]

    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    in_buffer = ctypes.create_string_buffer(data)
    in_blob = DATA_BLOB(len(data), ctypes.cast(in_buffer, ctypes.POINTER(ctypes.c_char)))
    out_blob = DATA_BLOB()
    if protect:
        ok = crypt32.CryptProtectData(
            ctypes.byref(in_blob),
            None,
            None,
            None,
            None,
            0,
            ctypes.byref(out_blob),
        )
    else:
        ok = crypt32.CryptUnprotectData(
            ctypes.byref(in_blob),
            None,
            None,
            None,
            None,
            0,
            ctypes.byref(out_blob),
        )
    if not ok:
        raise OSError("Windows DPAPI secret operation failed")
    try:
        return ctypes.string_at(out_blob.pbData, out_blob.cbData)
    finally:
        kernel32.LocalFree(out_blob.pbData)


def _fallback_key_path() -> Path:
    override = os.environ.get("DUMMY_BI_PQ_SECRET_KEY")
    if override:
        return Path(override)
    return _secret_store_path().with_suffix(".key")


def _fallback_key() -> bytes:
    path = _fallback_key_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        return base64.b64decode(path.read_text(encoding="utf-8"))
    key = secrets.token_bytes(32)
    path.write_text(base64.b64encode(key).decode("ascii"), encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return key


def _xor_stream(key: bytes, nonce: bytes, length: int) -> bytes:
    chunks: list[bytes] = []
    counter = 0
    while sum(len(chunk) for chunk in chunks) < length:
        chunks.append(hmac.new(key, nonce + counter.to_bytes(8, "big"), hashlib.sha256).digest())
        counter += 1
    return b"".join(chunks)[:length]


def encrypt_secret_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    data = _json_bytes(payload)
    if os.name == "nt":
        blob = _dpapi_crypt(data, protect=True)
        return {"scheme": "dpapi.v1", "blob": base64.b64encode(blob).decode("ascii")}
    key = _fallback_key()
    nonce = secrets.token_bytes(16)
    stream = _xor_stream(key, nonce, len(data))
    cipher = bytes(a ^ b for a, b in zip(data, stream))
    tag = hmac.new(key, nonce + cipher, hashlib.sha256).digest()
    return {
        "scheme": "local-hmac-stream.v1",
        "nonce": base64.b64encode(nonce).decode("ascii"),
        "blob": base64.b64encode(cipher).decode("ascii"),
        "tag": base64.b64encode(tag).decode("ascii"),
    }


def decrypt_secret_payload(encrypted: Mapping[str, Any]) -> dict[str, Any]:
    scheme = str(encrypted.get("scheme") or "")
    if scheme == "dpapi.v1":
        data = _dpapi_crypt(base64.b64decode(str(encrypted.get("blob") or "")), protect=False)
        return json.loads(data.decode("utf-8"))
    if scheme == "local-hmac-stream.v1":
        key = _fallback_key()
        nonce = base64.b64decode(str(encrypted.get("nonce") or ""))
        cipher = base64.b64decode(str(encrypted.get("blob") or ""))
        tag = base64.b64decode(str(encrypted.get("tag") or ""))
        expected = hmac.new(key, nonce + cipher, hashlib.sha256).digest()
        if not hmac.compare_digest(tag, expected):
            raise ValueError("Power Query credential secret payload failed integrity check")
        stream = _xor_stream(key, nonce, len(cipher))
        data = bytes(a ^ b for a, b in zip(cipher, stream))
        return json.loads(data.decode("utf-8"))
    raise ValueError(f"Unsupported Power Query secret scheme: {scheme!r}")


def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Secret payloads reach this shared sink only after DPAPI or authenticated
    # local encryption; profile metadata is recursively redacted.  The security
    # contract test asserts that known plaintext never reaches either file.
    path.write_text(  # lgtm[py/clear-text-storage-sensitive-data]
        json.dumps(payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _load_secret_store() -> dict[str, Any]:
    data = _load_json(_secret_store_path(), {"version": 1, "profiles": {}})
    if not isinstance(data, dict):
        return {"version": 1, "profiles": {}}
    profiles = data.get("profiles")
    if not isinstance(profiles, dict):
        data["profiles"] = {}
    return data


def _write_secret_store(data: Mapping[str, Any]) -> None:
    path = _secret_store_path()
    _write_json(path, data)
    try:
        path.chmod(0o600)
    except OSError:
        pass


def list_credential_profiles(project_root: str | os.PathLike[str]) -> list[dict[str, Any]]:
    path = credential_profiles_path(project_root)
    data = _load_json(path, {"version": 1, "profiles": []})
    profiles = data.get("profiles") if isinstance(data, Mapping) else []
    if not isinstance(profiles, list):
        return []
    return [redact_secret_value(dict(item)) for item in profiles if isinstance(item, Mapping)]


def get_credential_profile(project_root: str | os.PathLike[str] | None, profile_id: str | None) -> dict[str, Any] | None:
    if not profile_id:
        return None
    for profile in list_credential_profiles(project_root or "."):
        if str(profile.get("profile_id") or "") == str(profile_id):
            return profile
    return None


def upsert_credential_profile(project_root: str | os.PathLike[str], payload: Mapping[str, Any]) -> dict[str, Any]:
    path = credential_profiles_path(project_root)
    data = _load_json(path, {"version": 1, "profiles": []})
    profiles = data.get("profiles") if isinstance(data, Mapping) else []
    if not isinstance(profiles, list):
        profiles = []
    profile_id = str(payload.get("profile_id") or uuid.uuid4().hex)
    now = _now_iso()
    existing = next((dict(item) for item in profiles if isinstance(item, Mapping) and str(item.get("profile_id") or "") == profile_id), {})
    connector_id = str(payload.get("connector_id") or existing.get("connector_id") or "").strip()
    if not connector_id:
        raise ValueError("connector_id is required")
    properties = dict(existing.get("properties") or {})
    if isinstance(payload.get("properties"), Mapping):
        properties.update(dict(payload.get("properties") or {}))
    for metadata_key in PROFILE_METADATA_KEYS:
        if metadata_key in payload:
            properties[metadata_key] = payload.get(metadata_key)
    profile = {
        "profile_id": profile_id,
        "connector_id": connector_id,
        "display_name": str(payload.get("display_name") or existing.get("display_name") or connector_id),
        "privacy_level": str(payload.get("privacy_level") or existing.get("privacy_level") or "organizational"),
        "auth_type": str(payload.get("auth_type") or existing.get("auth_type") or "basic"),
        "properties": redact_secret_value(properties),
        "created_at": str(existing.get("created_at") or now),
        "updated_at": now,
        "secret_ref": f"power_query:{profile_id}",
    }
    for certification_key in PROFILE_CERTIFICATION_KEYS:
        if certification_key in payload:
            profile[certification_key] = redact_secret_value(payload.get(certification_key), key=certification_key)
        elif certification_key in existing:
            profile[certification_key] = redact_secret_value(existing.get(certification_key), key=certification_key)
    next_profiles = [item for item in profiles if not (isinstance(item, Mapping) and str(item.get("profile_id") or "") == profile_id)]
    next_profiles.append(profile)
    _write_json(path, {"version": 1, "profiles": sorted(next_profiles, key=lambda item: str(item.get("display_name") or ""))})

    if isinstance(payload.get("secrets"), Mapping):
        store = _load_secret_store()
        store_profiles = store.setdefault("profiles", {})
        store_profiles[profile_id] = {
            "updated_at": now,
            "payload": encrypt_secret_payload(dict(payload.get("secrets") or {})),
        }
        _write_secret_store(store)
    return redact_secret_value(profile)


def delete_credential_profile(project_root: str | os.PathLike[str], profile_id: str) -> bool:
    path = credential_profiles_path(project_root)
    data = _load_json(path, {"version": 1, "profiles": []})
    profiles = data.get("profiles") if isinstance(data, Mapping) else []
    if not isinstance(profiles, list):
        profiles = []
    remaining = [item for item in profiles if not (isinstance(item, Mapping) and str(item.get("profile_id") or "") == str(profile_id))]
    _write_json(path, {"version": 1, "profiles": remaining})
    store = _load_secret_store()
    store_profiles = store.setdefault("profiles", {})
    existed = str(profile_id) in store_profiles or len(remaining) != len(profiles)
    store_profiles.pop(str(profile_id), None)
    _write_secret_store(store)
    return existed


def get_credential_secrets(profile_id: str | None) -> dict[str, Any]:
    if not profile_id:
        return {}
    store = _load_secret_store()
    encrypted = ((store.get("profiles") or {}).get(str(profile_id)) or {}).get("payload")
    if not isinstance(encrypted, Mapping):
        return {}
    return decrypt_secret_payload(encrypted)
