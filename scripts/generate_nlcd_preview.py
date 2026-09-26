#!/usr/bin/env python3
"""Generate the checked-in demo Annual NLCD browser derivative."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from environmental_screening_platform.nlcd_preview import generate_nlcd_preview


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-raster", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--generated-at", required=True)
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    report: dict[str, Any] = json.loads(args.report.read_text(encoding="utf-8"))
    evidence: dict[str, Any] = json.loads(args.evidence.read_text(encoding="utf-8"))
    candidate = evidence["candidate"]
    snapshot = report["sources"]["annual_nlcd"]["screening"][0]["source_snapshots"][0]
    aoi = report["aoi"]
    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    metadata = generate_nlcd_preview(
        args.source_raster,
        output_dir / "nlcd-preview.png",
        output_dir / "nlcd-preview.json",
        aoi_geometry=aoi["geometry"],
        aoi_revision=int(aoi["revision"]),
        aoi_geometry_sha256=aoi["geometry_sha256"],
        source_metadata={
            "source_snapshot_id": snapshot["snapshot_id"],
            "source_version_id": candidate["version_id"],
            "candidate_id": candidate["candidate_id"],
            "release": candidate["provider_release"],
            "source_url": candidate["source_url"],
            "retrieved_at": candidate["retrieved_at"],
            "terms_url": candidate["terms_url"],
            "sha256": candidate["sha256"],
            "source_year": 2025,
        },
        generated_at=args.generated_at,
    )
    print(json.dumps(metadata, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
