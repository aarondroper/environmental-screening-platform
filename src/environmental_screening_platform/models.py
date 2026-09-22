"""Contract vocabularies and small immutable domain records."""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


class Maturity(StrEnum):
    VALIDATED = "validated"
    CONDITIONALLY_VALIDATED = "conditionally_validated"
    ACCESS_BLOCKED = "access_blocked"
    FAILED = "failed"
    NOT_ACQUIRED = "not_acquired"


class Coverage(StrEnum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    UNKNOWN = "unknown"
    UNAVAILABLE = "unavailable"
    NOT_ASSESSED = "not_assessed"


class Observation(StrEnum):
    CONSTRAINT_OBSERVED = "constraint_observed"
    NO_CONSTRAINT_OBSERVED = "no_constraint_observed"
    DATA_OBSERVED = "data_observed"
    NOT_COVERED = "not_covered"
    UNAVAILABLE = "unavailable"
    PENDING_DATA = "pending_data"
    INCOMPLETE_SOURCE = "incomplete_source"
    GEOMETRY_QUARANTINED = "geometry_quarantined"
    NOT_ASSESSED = "not_assessed"


class JobStatus(StrEnum):
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class AttemptStatus(StrEnum):
    NOT_ACQUIRED = "not_acquired"
    ACQUIRED = "acquired"
    VALIDATED = "validated"
    ACCESS_BLOCKED = "access_blocked"
    FAILED = "failed"


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def source_version_id(source_id: str, release: str, sha256: str) -> str:
    """Stable identifier for one logical source release and exact artifact bytes."""
    digest = hashlib.sha256(f"{source_id}\0{release}\0{sha256}".encode()).hexdigest()
    return f"{source_id}:{digest}"


@dataclass(frozen=True)
class Acquisition:
    source_id: str
    provider: str
    release: str
    source_url: str
    acquired_at: str
    media_type: str
    raw_path: str
    size_bytes: int
    sha256: str
    terms_url: str
    attempts: int = 1
    request_parameters: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["version_id"] = source_version_id(self.source_id, self.release, self.sha256)
        return data


@dataclass
class SourceResult:
    source_id: str
    validation_status: Maturity
    validation_scope: str
    coverage_status: Coverage
    observation_status: Observation
    product_status: str
    attempt_status: AttemptStatus = AttemptStatus.NOT_ACQUIRED
    metrics: dict[str, Any] = field(default_factory=dict)
    provenance: dict[str, Any] | None = None
    warnings: list[str] = field(default_factory=list)
    reason: str | None = None
    quarantined_ids: list[str] = field(default_factory=list)
    features: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "validation_status": self.validation_status.value,
            "validation_scope": self.validation_scope,
            "coverage_status": self.coverage_status.value,
            "observation_status": self.observation_status.value,
            "product_status": self.product_status,
            "attempt_status": self.attempt_status.value,
            "metrics": self.metrics,
            "provenance": self.provenance,
            "warnings": self.warnings,
            "reason": self.reason,
            "quarantined_ids": self.quarantined_ids,
            "features": self.features,
        }


def classify_constraint_observation(
    *,
    intersecting_features: int | None,
    coverage_status: Coverage,
    validation_status: Maturity,
    validation_scope_complete: bool = False,
    pending: bool = False,
    quarantined: bool = False,
) -> Observation:
    """Only complete, fully validated zero-feature coverage can support observed absence."""
    if quarantined:
        return Observation.GEOMETRY_QUARANTINED
    if pending:
        return Observation.PENDING_DATA
    if coverage_status == Coverage.UNAVAILABLE:
        return Observation.UNAVAILABLE
    if intersecting_features is not None and intersecting_features > 0:
        return Observation.CONSTRAINT_OBSERVED
    if coverage_status in {Coverage.PARTIAL, Coverage.UNKNOWN, Coverage.NOT_ASSESSED}:
        return (
            Observation.NOT_COVERED
            if coverage_status == Coverage.PARTIAL
            else Observation.INCOMPLETE_SOURCE
        )
    if intersecting_features is None:
        return Observation.NOT_ASSESSED
    if (
        coverage_status == Coverage.COMPLETE
        and validation_status == Maturity.VALIDATED
        and validation_scope_complete
    ):
        return Observation.NO_CONSTRAINT_OBSERVED
    return Observation.INCOMPLETE_SOURCE


MATURITY = {
    "census_boundary": (
        Maturity.VALIDATED,
        "Official 2025 TIGER/Line county boundary; approved three GEOIDs",
    ),
    "annual_nlcd": (
        Maturity.VALIDATED,
        "Representative 2025 WCS sample only; not full regional completeness",
    ),
    "3dep": (
        Maturity.VALIDATED,
        "Representative 1/3 arc-second tile; regional inventory is bounded estimate",
    ),
    "ssurgo": (
        Maturity.VALIDATED,
        "Representative SDA query/sample; complete package scale not measured",
    ),
    "padus": (
        Maturity.CONDITIONALLY_VALIDATED,
        "Five-feature sample; accepted unchanged and repaired-candidate quarantines; regional coverage unverified",
    ),
    "fema_nfhl": (
        Maturity.ACCESS_BLOCKED,
        "Selected source; provider access blocked; technical suitability and effective/pending sample validation incomplete.",
    ),
}
