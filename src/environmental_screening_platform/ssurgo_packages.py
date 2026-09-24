"""Bounded acquisition and archive validation for official SSURGO packages.

This module deliberately validates package containers only.  It does not parse
or promote regional SSURGO map-unit data, and it does not replace the existing
AOI-clipped SDA fixture adapter.
"""

from __future__ import annotations

import io
import json
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .models import (
    Acquisition,
    AttemptStatus,
    Coverage,
    Maturity,
    Observation,
    SourceResult,
)
from .store import fetch_raw

SSURGO_REGIONAL_SIZING = Path("ssurgo/ssurgo_regional_sizing_2026-09-24.json")
SSURGO_PACKAGE_MAX_BYTES = 100_000_000
APPROVED_GEOIDS = frozenset({"08013", "08069", "08123"})
OFFICIAL_PACKAGE_HOST = "websoilsurvey.sc.egov.usda.gov"
SSURGO_TERMS_URL = (
    "https://www.nrcs.usda.gov/resources/data-and-reports/soil-survey-geographic-database-ssurgo"
)


@dataclass(frozen=True)
class SsurgoPackageSpec:
    areasymbol: str
    areaname: str
    provider_package_identifier: str
    saversion: int
    saverest_provider: str
    package_url: str
    format: str
    provider_reported_size_bytes: int
    mapunit_count: int

    @property
    def provider_release(self) -> str:
        return (
            f"SSURGO {self.areasymbol} saversion {self.saversion} saverest {self.saverest_provider}"
        )


def load_ssurgo_package_specs(path: Path) -> tuple[SsurgoPackageSpec, ...]:
    """Load and validate the immutable 19-area sizing record."""
    record = json.loads(path.read_text(encoding="utf-8"))
    boundary = record.get("approved_boundary")
    if not isinstance(boundary, dict):
        raise ValueError("SSURGO sizing record is missing approved_boundary metadata")
    geoids = {str(item.get("geoid")) for item in boundary.get("counties", [])}
    if geoids != APPROVED_GEOIDS:
        raise ValueError("SSURGO sizing record does not describe the approved county set")
    if (
        boundary.get("vintage") != 2025
        or boundary.get("union_geometry_type") != "MultiPolygon"
        or boundary.get("union_component_count") != 3
        or boundary.get("union_valid") is not True
    ):
        raise ValueError("SSURGO sizing record does not describe the validated three-component AOI")

    raw_areas = record.get("survey_areas")
    if not isinstance(raw_areas, list) or len(raw_areas) != 19:
        raise ValueError("SSURGO sizing record must contain exactly 19 survey areas")
    specs: list[SsurgoPackageSpec] = []
    seen: set[str] = set()
    for raw in raw_areas:
        try:
            symbol = str(raw["areasymbol"])
            url = str(raw["package_url"])
            reported_size = int(raw["compressed_size_bytes"])
            spec = SsurgoPackageSpec(
                areasymbol=symbol,
                areaname=str(raw["areaname"]),
                provider_package_identifier=str(raw["provider_package_identifier"]),
                saversion=int(raw["saversion"]),
                saverest_provider=str(raw["saverest_provider"]),
                package_url=url,
                format=str(raw["format"]),
                provider_reported_size_bytes=reported_size,
                mapunit_count=int(raw["mapunit_count"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("SSURGO sizing record contains an incomplete survey-area row") from exc
        parsed = urlparse(spec.package_url)
        if parsed.scheme != "https" or parsed.hostname != OFFICIAL_PACKAGE_HOST:
            raise ValueError(f"SSURGO package URL is not the approved official HTTPS route: {url}")
        if not symbol or symbol in seen or reported_size <= 0:
            raise ValueError(f"SSURGO sizing record has an invalid or duplicate area: {symbol}")
        if raw.get("size_status") != "reported_by_provider_http_content_length":
            raise ValueError(f"SSURGO package size status is not provider-reported for {symbol}")
        seen.add(symbol)
        specs.append(spec)
    return tuple(sorted(specs, key=lambda item: item.areasymbol))


def validate_ssurgo_package(body: bytes, spec: SsurgoPackageSpec) -> dict[str, Any]:
    """Validate ZIP CRC and the minimum official SSURGO package structure."""
    try:
        archive = zipfile.ZipFile(io.BytesIO(body))
    except zipfile.BadZipFile as exc:
        raise ValueError(f"{spec.areasymbol} response is not a valid ZIP archive") from exc
    with archive:
        bad_member = archive.testzip()
        if bad_member is not None:
            raise ValueError(f"{spec.areasymbol} ZIP CRC failure in {bad_member}")
        members = [name for name in archive.namelist() if not name.endswith("/")]
        lowered = [name.lower().replace("\\", "/") for name in members]
        has_spatial = any("/spatial/" in f"/{name}" for name in lowered)
        has_tabular = any("/tabular/" in f"/{name}" for name in lowered)
        symbol_present = any(spec.areasymbol.lower() in name for name in lowered)
        if not members:
            raise ValueError(f"{spec.areasymbol} ZIP archive contains no files")
        if not has_spatial or not has_tabular:
            raise ValueError(
                f"{spec.areasymbol} ZIP archive lacks expected spatial and tabular package content"
            )
        if not symbol_present:
            raise ValueError(f"{spec.areasymbol} ZIP archive does not identify its survey area")
        return {
            "archive_valid": True,
            "crc_test": "passed",
            "member_count": len(members),
            "compressed_member_bytes": sum(info.compress_size for info in archive.infolist()),
            "uncompressed_member_bytes": sum(info.file_size for info in archive.infolist()),
            "has_spatial_directory": has_spatial,
            "has_tabular_directory": has_tabular,
            "areasymbol_present_in_member_names": symbol_present,
        }


def acquire_ssurgo_package(
    session: Any,
    data_root: Path,
    spec: SsurgoPackageSpec,
    *,
    acquisition_callback: Callable[[Acquisition], None] | None = None,
) -> Any:
    """Acquire and structurally validate one official survey-area package."""
    body, metadata = fetch_raw(
        session,
        source_id="ssurgo",
        provider="USDA NRCS Web Soil Survey",
        release=spec.provider_release,
        url=spec.package_url,
        params=None,
        data_root=data_root,
        terms_url=SSURGO_TERMS_URL,
        max_bytes=SSURGO_PACKAGE_MAX_BYTES,
        media_type="application/zip",
        acquisition_callback=acquisition_callback,
    )
    if metadata.provider_reported_size_bytes != spec.provider_reported_size_bytes:
        raise ValueError(
            f"{spec.areasymbol} provider size changed: sizing record reported "
            f"{spec.provider_reported_size_bytes}, response reported "
            f"{metadata.provider_reported_size_bytes}"
        )
    archive_validation = validate_ssurgo_package(body, spec)
    metrics = {
        "areasymbol": spec.areasymbol,
        "areaname": spec.areaname,
        "provider_package_identifier": spec.provider_package_identifier,
        "provider_reported_size_bytes": spec.provider_reported_size_bytes,
        "actual_size_bytes": metadata.size_bytes,
        "size_status": "provider_reported_and_locally_measured",
        "size_match": metadata.size_bytes == spec.provider_reported_size_bytes,
        "archive_validation": archive_validation,
        "regional_intersection_status": "survey area intersects exact approved AOI",
        "mapunit_count_from_sizing_record": spec.mapunit_count,
        "data_use": "inactive validation-only package; not regional canonical coverage",
    }
    if not metrics["size_match"]:
        raise ValueError(
            f"{spec.areasymbol} measured size {metadata.size_bytes} does not match "
            f"provider-reported size {spec.provider_reported_size_bytes}"
        )
    result = SourceResult(
        source_id="ssurgo",
        validation_status=Maturity.VALIDATED,
        validation_scope=(
            "Official SSURGO survey-area ZIP CRC and package-structure validation only; "
            "not full regional canonical coverage"
        ),
        coverage_status=Coverage.PARTIAL,
        observation_status=Observation.INCOMPLETE_SOURCE,
        product_status="inactive regional SSURGO package candidate",
        attempt_status=AttemptStatus.VALIDATED,
        metrics=metrics,
        provenance={
            **metadata.to_dict(),
            "survey_area": {
                "areasymbol": spec.areasymbol,
                "areaname": spec.areaname,
                "provider_package_identifier": spec.provider_package_identifier,
                "saversion": spec.saversion,
                "saverest_provider": spec.saverest_provider,
                "sizing_record_provider_reported_size_bytes": spec.provider_reported_size_bytes,
            },
            "archive_validation": archive_validation,
        },
        warnings=[
            "Archive validation is inactive and validation-only; no SSURGO package is promoted.",
            "A survey-area package is not evidence that the full approved AOI has canonical coverage.",
            "Hydric-soil attributes remain soil information, not a wetlands inventory or regulatory determination.",
        ],
        reason="Survey-area package is structurally validated but regional canonical coverage is incomplete.",
    )
    from .adapters import ProviderData

    return ProviderData(result=result, value=archive_validation)
