#!/usr/bin/env python3
"""Generate the checked-in demo 3DEP browser derivative."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from environmental_screening_platform.three_dep_preview import generate_3dep_preview


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-raster", type=Path, required=True)
    parser.add_argument("--acquisition-record", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--generated-at", required=True)
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    report: dict[str, Any] = json.loads(args.report.read_text(encoding="utf-8"))
    acquisition: dict[str, Any] = json.loads(args.acquisition_record.read_text(encoding="utf-8"))
    source = report["sources"]["3dep"]
    candidate = source["candidates"][0]
    snapshot = source["screening"][0]["source_snapshots"][0]
    attempt = source["ingestion_runs"][0]["acquisition_attempts"][0]
    request = acquisition.get("request_parameters", {})
    tile_id = request.get("tile_id")
    if not tile_id:
        marker = "/historical/"
        url = acquisition["requested_url"]
        tile_id = url.split(marker, 1)[1].split("/", 1)[0] if marker in url else None
    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    metadata = generate_3dep_preview(
        args.source_raster,
        output_dir / "3dep-preview.png",
        output_dir / "3dep-preview.json",
        aoi_geometry=report["aoi"]["geometry"],
        aoi_revision=int(report["aoi"]["revision"]),
        aoi_geometry_sha256=report["aoi"]["geometry_sha256"],
        source_metadata={
            "source_id": "3dep",
            "source_snapshot_id": snapshot["snapshot_id"],
            "source_version_id": candidate["version_id"],
            "candidate_id": candidate["candidate_id"],
            "ingestion_run_id": source["ingestion_runs"][0]["run_id"],
            "release": candidate["provider_release"],
            "source_url": acquisition["requested_url"],
            "retrieved_at": acquisition["acquired_at"],
            "terms_url": acquisition["terms_url"],
            "tile_id": tile_id,
            "request_parameters": request,
            "response_headers": acquisition.get("response_headers", {}),
            "attempt_id": attempt.get("attempt_id"),
        },
        generated_at=args.generated_at,
    )
    print(json.dumps(metadata, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
