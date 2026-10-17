"""API-key authentication, CORS configuration and upload validation helpers."""
import logging
import os
import re
import secrets
from dataclasses import dataclass

from fastapi import Header, HTTPException, UploadFile

logger = logging.getLogger(__name__)

ANONYMOUS = "anonymous"
DEFAULT_CORS_ORIGINS = "http://localhost:5173,http://127.0.0.1:5173"
DEFAULT_MAX_UPLOAD_MB = 25


@dataclass(frozen=True)
class Principal:
    """Who is making the request. ``authenticated`` is False when auth is disabled."""
    name: str
    authenticated: bool


def _load_api_keys() -> dict[str, str]:
    """Parse API_KEYS="key1:alice,key2:bob" (a bare "key" maps to user "api-user")."""
    keys: dict[str, str] = {}
    for item in os.environ.get("API_KEYS", "").split(","):
        item = item.strip()
        if not item:
            continue
        key, _, name = item.partition(":")
        keys[key.strip()] = name.strip() or "api-user"
    return keys


def auth_enabled() -> bool:
    return bool(_load_api_keys())


def require_api_key(x_api_key: str | None = Header(default=None)) -> Principal:
    """FastAPI dependency. With API_KEYS unset, auth is off (local development)."""
    keys = _load_api_keys()
    if not keys:
        return Principal(ANONYMOUS, authenticated=False)
    if x_api_key:
        for key, name in keys.items():
            if secrets.compare_digest(key, x_api_key):
                return Principal(name, authenticated=True)
    raise HTTPException(status_code=401, detail="Missing or invalid API key")


def resolve_actor(principal: Principal, claimed: str | None) -> str:
    """The audit-trail actor: the authenticated user, never a client-supplied name."""
    if principal.authenticated:
        return principal.name
    return claimed or "reviewer"


def cors_origins() -> list[str]:
    raw = os.environ.get("CORS_ORIGINS", DEFAULT_CORS_ORIGINS)
    return [o.strip() for o in raw.split(",") if o.strip()]


def max_upload_bytes() -> int:
    try:
        mb = float(os.environ.get("MAX_UPLOAD_MB", DEFAULT_MAX_UPLOAD_MB))
    except ValueError:
        mb = DEFAULT_MAX_UPLOAD_MB
    return int(mb * 1024 * 1024)


_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")


def safe_filename(filename: str | None, default: str = "upload") -> str:
    """Strip directories and unsafe characters so the name can't escape the upload dir."""
    name = os.path.basename((filename or "").replace("\\", "/"))
    name = _UNSAFE.sub("_", name).lstrip(".")
    return name or default


def read_upload(file: UploadFile, *, extension: str, magic: bytes | None = None) -> bytes:
    """Read an upload fully, enforcing extension, size cap and (optionally) magic bytes."""
    name = (file.filename or "").lower()
    if not name.endswith(extension):
        raise HTTPException(status_code=400, detail=f"Only {extension} files are supported")

    limit = max_upload_bytes()
    data = file.file.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(
            status_code=413, detail=f"File exceeds the {limit // (1024 * 1024)} MB upload limit"
        )
    if not data:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")
    if magic and not data.startswith(magic):
        raise HTTPException(status_code=400, detail=f"File is not a valid {extension} document")
    return data
