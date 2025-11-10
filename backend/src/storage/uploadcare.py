"""Uploadcare helper (Phase 1).

This module provides a thin helper wrapper around Uploadcare HTTP APIs.

Phase 1 constraints:
- Importing this module must have no side-effects (no network calls, no prints).
- Functions raise ValueError on invalid responses or missing required configuration.
- TODO: Confirm exact Uploadcare REST endpoints and auth scheme; current calls are written
  to be easy to adapt and are covered by unit tests which mock requests.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional, Dict, Any

import requests


@dataclass
class UploadcareFileMeta:
    file_id: str
    cdn_url: Optional[str] = None
    file_size: Optional[int] = None
    file_checksum: Optional[str] = None


def _get_env_bool(name: str, default: bool = False) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return val.lower() in ("1", "true", "yes")


def _get_config() -> Dict[str, Any]:
    return {
        "enabled": _get_env_bool("UPLOADCARE_ENABLED", False),
        "public_key": os.getenv("UPLOAD_CARE_PUBLIC_KEY"),
        "secret_key": os.getenv("UPLOAD_CARE_SECRET_KEY"),
        "api_base": os.getenv("UPLOADCARE_API_BASE_URL", "https://api.uploadcare.com"),
    }


def _require_credentials(cfg: Dict[str, Any]) -> None:
    if not cfg.get("public_key") or not cfg.get("secret_key"):
        raise ValueError(
            "Uploadcare public/secret keys are required. Set UPLOAD_CARE_PUBLIC_KEY and UPLOAD_CARE_SECRET_KEY in environment."
        )


def upload_file_direct(file_bytes: bytes, file_name: str) -> UploadcareFileMeta:
    """Upload bytes to Uploadcare and return metadata.

    Note: This function performs a network call. In Phase 1 we only provide this helper;
    it is not wired into production code. Unit tests must mock requests.

    Raises:
        ValueError: if configuration is missing or the upload returned a non-2xx status.
    """
    cfg = _get_config()
    if not cfg["enabled"]:
        raise ValueError("UPLOADCARE_ENABLED is not true; upload_file_direct should not be called in this mode.")

    _require_credentials(cfg)

    # TODO: Confirm the exact Uploadcare endpoint and auth scheme. Current implementation
    # posts to {api_base}/files/ with multipart/form-data. Unit tests mock requests and
    # validate expected behavior.
    url = f"{cfg['api_base'].rstrip('/')}/files/"

    headers = {"Accept": "application/json"}

    # Many Uploadcare API variants require an API key/secret. We place them in HTTP basic
    # auth for now so the test harness can assert the request is made; adjust as needed.
    auth = (cfg["public_key"], cfg["secret_key"])

    files = {"file": (file_name, file_bytes)}

    resp = requests.post(url, headers=headers, files=files, auth=auth, timeout=30)

    if not (200 <= resp.status_code < 300):
        raise ValueError(f"Upload failed: status={resp.status_code} body={resp.text}")

    try:
        data = resp.json()
    except Exception as exc:  # pragma: no cover - defensive
        raise ValueError(f"Failed to parse Uploadcare response JSON: {exc}")

    # Try common keys used by different Uploadcare responses; callers should validate.
    file_id = data.get("file_id") or data.get("uuid") or data.get("id")
    cdn_url = data.get("cdn_url") or data.get("file_url") or data.get("cdn")
    file_size = data.get("size") or data.get("file_size")
    file_checksum = data.get("checksum")

    if not file_id:
        raise ValueError(f"Upload response missing file id: {data}")

    return UploadcareFileMeta(file_id=str(file_id), cdn_url=cdn_url, file_size=file_size, file_checksum=file_checksum)


def calculate_checksum(path: str) -> str:
    """Calculate SHA-256 checksum for a local file path and return hex digest."""
    import hashlib

    h = hashlib.sha256()
    # read in chunks to avoid large memory usage
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def download_file(file_id: str, dest_path: str) -> str:
    """Download a file from Uploadcare to dest_path and return dest_path.

    The implementation streams the HTTP response to disk. Tests should mock requests.get.
    """
    cfg = _get_config()
    _require_credentials(cfg)

    # TODO: confirm correct download endpoint. Using a simple file resource endpoint here.
    url = f"{cfg['api_base'].rstrip('/')}/files/{file_id}/"
    auth = (cfg["public_key"], cfg["secret_key"])

    resp = requests.get(url, stream=True, auth=auth, timeout=30)
    if not (200 <= resp.status_code < 300):
        raise ValueError(f"Download failed: status={resp.status_code} body={resp.text}")

    # Stream to disk
    with open(dest_path, "wb") as fh:
        for chunk in resp.iter_content(8192):
            if chunk:
                fh.write(chunk)

    return dest_path


def delete_file(file_id: str) -> bool:
    """Delete an Uploadcare file by id. Returns True on success (200/204), False otherwise."""
    cfg = _get_config()
    _require_credentials(cfg)

    url = f"{cfg['api_base'].rstrip('/')}/files/{file_id}/"
    auth = (cfg["public_key"], cfg["secret_key"])

    resp = requests.delete(url, auth=auth, timeout=30)
    return resp.status_code in (200, 204)
