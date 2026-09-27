"""Immutable raw snapshots, stored content-addressed: <raw_dir>/<dataset>/<sha[:2]>/<sha><ext>."""

import hashlib
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from esp.models import RawSnapshot


@dataclass(frozen=True)
class StoredFile:
    path: Path
    sha256: str
    size_bytes: int


def store_file(source: Path, raw_dir: Path, dataset_id: str) -> StoredFile:
    """Copy a downloaded file into the raw store. Idempotent: identical content lands once."""
    digest = hashlib.sha256()
    with source.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    sha = digest.hexdigest()
    target = raw_dir / dataset_id / sha[:2] / f"{sha}{source.suffix}"
    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        with (
            tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as tmp,
            source.open("rb") as stream,
        ):
            shutil.copyfileobj(stream, tmp)
        Path(tmp.name).replace(target)
    return StoredFile(target, sha, target.stat().st_size)


def record_snapshot(
    session: Session, dataset_id: str, url: str, provider_release: str, stored: StoredFile
) -> RawSnapshot:
    existing = session.scalar(
        select(RawSnapshot).where(
            RawSnapshot.dataset_id == dataset_id, RawSnapshot.sha256 == stored.sha256
        )
    )
    if existing:
        return existing
    snapshot = RawSnapshot(
        dataset_id=dataset_id,
        url=url,
        provider_release=provider_release,
        sha256=stored.sha256,
        size_bytes=stored.size_bytes,
        storage_path=str(stored.path),
    )
    session.add(snapshot)
    session.flush()
    return snapshot
