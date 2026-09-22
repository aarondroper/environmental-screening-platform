"""Atomic local records and immutable, checksummed raw response storage."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

import requests

from .models import Acquisition, utc_now


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n"
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".part", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(body)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_bytes_atomic(path: Path, body: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".part", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(body)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)


def fetch_raw(
    session: requests.Session,
    *,
    source_id: str,
    provider: str,
    release: str,
    url: str,
    params: dict[str, Any] | None,
    data_root: Path,
    terms_url: str,
    max_bytes: int,
    timeout: tuple[float, float] = (10, 90),
    json_body: dict[str, Any] | None = None,
    form_body: dict[str, Any] | None = None,
    media_type: str | None = None,
) -> tuple[bytes, Acquisition]:
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError("Source acquisition requires an absolute HTTPS URL")
    if json_body is not None and form_body is not None:
        raise ValueError("Choose one POST body encoding")
    request_kwargs: dict[str, Any] = {"timeout": timeout, "stream": True}
    method: Callable[..., requests.Response]
    if json_body is not None:
        request_kwargs["json"] = json_body
        method = session.post
    elif form_body is not None:
        request_kwargs["data"] = form_body
        method = session.post
    else:
        request_kwargs["params"] = params
        method = session.get
    response = None
    for attempt in range(1, 4):
        try:
            response = method(url, **request_kwargs)
            if response.status_code in {408, 429, 500, 502, 503, 504} and attempt < 3:
                response.close()
                time.sleep(0.2 * (2 ** (attempt - 1)))
                continue
            response.raise_for_status()
            break
        except (requests.Timeout, requests.ConnectionError):
            if attempt == 3:
                raise
            if response is not None:
                response.close()
            time.sleep(0.2 * (2 ** (attempt - 1)))
    assert response is not None
    final_url = urlparse(response.url)
    if final_url.scheme != "https" or final_url.hostname != parsed.hostname:
        response.close()
        raise ValueError(f"Provider redirected to an unapproved host or scheme: {response.url}")
    declared = response.headers.get("Content-Length")
    if declared and int(declared) > max_bytes:
        raise ValueError(f"Response exceeds configured {max_bytes}-byte acquisition limit")
    chunks: list[bytes] = []
    size = 0
    for chunk in response.iter_content(1024 * 1024):
        if not chunk:
            continue
        size += len(chunk)
        if size > max_bytes:
            raise ValueError(f"Response exceeds configured {max_bytes}-byte acquisition limit")
        chunks.append(chunk)
    body = b"".join(chunks)
    if not body:
        raise ValueError("Provider returned an empty response")
    digest = hashlib.sha256(body).hexdigest()
    raw_dir = data_root / "raw" / source_id / digest[:2]
    raw_dir.mkdir(parents=True, exist_ok=True)
    actual_content_type = response.headers.get("Content-Type", "application/octet-stream")
    content_type = actual_content_type.lower()
    suffix = (
        ".tif"
        if "tiff" in content_type
        else ".zip"
        if "zip" in content_type
        else ".json"
        if "json" in content_type
        else ".bin"
    )
    raw_path = raw_dir / f"{digest}{suffix}"
    if not raw_path.exists():
        _write_bytes_atomic(raw_path, body)
    actual_url = response.url
    response.close()
    acquisition = Acquisition(
        source_id=source_id,
        provider=provider,
        release=release,
        source_url=actual_url,
        acquired_at=utc_now(),
        media_type=actual_content_type,
        raw_path=str(raw_path),
        size_bytes=len(body),
        sha256=digest,
        terms_url=terms_url,
        attempts=attempt,
        request_parameters=params or form_body or (json_body or {}),
    )
    event_json = (
        json.dumps(acquisition.to_dict(), ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    )
    event_hash = hashlib.sha256(event_json.encode("utf-8")).hexdigest()
    event_path = raw_path.parent / "acquisitions" / f"{event_hash}-{uuid4().hex}.json"
    write_json(event_path, acquisition.to_dict())
    return body, acquisition
