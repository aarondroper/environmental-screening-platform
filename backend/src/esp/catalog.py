"""Dataset version lifecycle: loading → validated → active → superseded (or → failed)."""

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from esp.models import Dataset, DatasetVersion


@dataclass(frozen=True)
class DatasetInfo:
    id: str
    title: str
    provider: str
    license: str
    homepage: str


def ensure_dataset(session: Session, info: DatasetInfo) -> Dataset:
    dataset = session.get(Dataset, info.id)
    if dataset is None:
        dataset = Dataset(id=info.id)
        session.add(dataset)
    dataset.title, dataset.provider = info.title, info.provider
    dataset.license, dataset.homepage = info.license, info.homepage
    session.flush()
    return dataset


def find_loaded_version(
    session: Session, dataset_id: str, content_sha256: str
) -> DatasetVersion | None:
    """A non-failed version with identical raw content, if one exists."""
    return session.scalar(
        select(DatasetVersion).where(
            DatasetVersion.dataset_id == dataset_id,
            DatasetVersion.content_sha256 == content_sha256,
            DatasetVersion.status != "failed",
        )
    )


def active_version(session: Session, dataset_id: str) -> DatasetVersion | None:
    dataset = session.get(Dataset, dataset_id)
    if dataset is None or dataset.active_version_id is None:
        return None
    return session.get(DatasetVersion, dataset.active_version_id)


def active_versions(session: Session) -> dict[str, str]:
    rows = session.execute(
        select(Dataset.id, Dataset.active_version_id).where(Dataset.active_version_id.is_not(None))
    )
    return {dataset_id: str(version_id) for dataset_id, version_id in rows}


def mark_validated(session: Session, version: DatasetVersion, validation: dict[str, Any]) -> None:
    version.status = "validated"
    version.validation = validation
    version.validated_at = func.now()
    session.flush()


def mark_failed(session: Session, version_id: uuid.UUID, validation: dict[str, Any]) -> None:
    session.execute(
        update(DatasetVersion)
        .where(DatasetVersion.id == version_id)
        .values(status="failed", validation=validation)
    )


class PromotionError(Exception):
    pass


def promote(session: Session, version_id: uuid.UUID) -> None:
    """Atomically make a validated version the active one; the previous becomes superseded."""
    version = session.get(DatasetVersion, version_id, with_for_update=True)
    if version is None or version.status != "validated":
        status = version.status if version else "missing"
        raise PromotionError(f"version {version_id} is {status}, not validated")
    # Lock the dataset row so concurrent promotions serialize.
    dataset = session.get(Dataset, version.dataset_id, with_for_update=True)
    assert dataset is not None
    if dataset.active_version_id is not None:
        session.execute(
            update(DatasetVersion)
            .where(DatasetVersion.id == dataset.active_version_id)
            .values(status="superseded")
        )
        session.flush()
    version.status = "active"
    version.activated_at = func.now()
    dataset.active_version_id = version.id
    session.flush()
