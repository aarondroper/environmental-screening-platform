"""Small operator CLI for the local job-oriented vertical slice."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from .catalog import SQLiteSourceRepository
from .ingestion import REQUEST_URLS, ingest_source, retry_ingestion
from .workflow import (
    create_job,
    create_project,
    export_result,
    job_status,
    retry_job,
    revise_aoi,
    run_job,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="screening", description="Preliminary environmental screening prototype"
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        required=True,
        help="External project/raw-data directory; must be outside this repository",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    create = sub.add_parser(
        "project-create", help="Create a project and immutable first AOI revision"
    )
    create.add_argument("--name", required=True)
    create.add_argument(
        "--aoi", type=Path, required=True, help="WGS84 Polygon/MultiPolygon GeoJSON"
    )

    revise = sub.add_parser("aoi-revise", help="Create a new immutable AOI revision")
    revise.add_argument("--project-id", required=True)
    revise.add_argument("--aoi", type=Path, required=True)

    submit = sub.add_parser(
        "screen", help="Create a job, execute its worker, and print the job ID/result"
    )
    submit.add_argument("--project-id", required=True)
    submit.add_argument(
        "--aoi-id", help="Optional immutable AOI revision ID; defaults to current revision"
    )

    status = sub.add_parser("job-status", help="Show job lifecycle and source attempts")
    status.add_argument("--job-id", required=True)

    retry = sub.add_parser("retry", help="Retry a failed job with the same AOI revision")
    retry.add_argument("--job-id", required=True)

    export = sub.add_parser("export", help="Write result JSON, source CSV, and AOI GeoJSON")
    export.add_argument("--job-id", required=True)
    export.add_argument("--output-dir", type=Path, required=True)

    ingest = sub.add_parser("ingest", help="Acquire and validate a source as an inactive candidate")
    ingest.add_argument("--source", choices=sorted(REQUEST_URLS), required=True)
    ingest.add_argument("--project-id")
    ingest.add_argument("--aoi-id")

    retry_ingest = sub.add_parser("retry-ingestion", help="Create a linked retry ingestion run")
    retry_ingest.add_argument("--run-id", required=True)

    runs = sub.add_parser("ingestion-runs", help="List durable source ingestion runs")
    runs.add_argument("--source")

    versions = sub.add_parser("source-versions", help="List checksum-identified source versions")
    versions.add_argument("--source")

    candidates = sub.add_parser("candidates", help="List source candidates and their states")
    candidates.add_argument("--source")
    candidates.add_argument("--status")

    candidate = sub.add_parser("candidate-status", help="Inspect a candidate and validation record")
    candidate.add_argument("--candidate-id", required=True)

    promote = sub.add_parser("promote-candidate", help="Explicitly promote an eligible candidate")
    promote.add_argument("--candidate-id", required=True)

    active = sub.add_parser("active-version", help="Show the active source version, if any")
    active.add_argument("--source", required=True)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    outcome: Any
    if args.command == "project-create":
        outcome = create_project(args.name, args.aoi, args.data_dir)
    elif args.command == "aoi-revise":
        outcome = revise_aoi(args.project_id, args.aoi, args.data_dir)
    elif args.command == "screen":
        job = create_job(args.project_id, args.data_dir, args.aoi_id)
        result = run_job(job["job_id"], args.data_dir)
        outcome = {"job": job_status(job["job_id"], args.data_dir), "result": result}
    elif args.command == "job-status":
        outcome = job_status(args.job_id, args.data_dir)
    elif args.command == "retry":
        outcome = retry_job(args.job_id, args.data_dir)
    elif args.command == "export":
        outcome = [str(path) for path in export_result(args.job_id, args.data_dir, args.output_dir)]
    elif args.command == "ingest":
        outcome = ingest_source(
            args.source,
            args.data_dir,
            project_id=args.project_id,
            aoi_id=args.aoi_id,
        )
    elif args.command == "retry-ingestion":
        outcome = retry_ingestion(args.run_id, args.data_dir)
    elif args.command == "ingestion-runs":
        outcome = SQLiteSourceRepository(args.data_dir).list_runs(args.source)
    elif args.command == "source-versions":
        outcome = SQLiteSourceRepository(args.data_dir).list_versions(args.source)
    elif args.command == "candidates":
        outcome = SQLiteSourceRepository(args.data_dir).list_candidates(args.source, args.status)
    elif args.command == "candidate-status":
        outcome = SQLiteSourceRepository(args.data_dir).get_candidate(args.candidate_id)
        if outcome is None:
            raise FileNotFoundError(f"Unknown candidate {args.candidate_id}")
    elif args.command == "promote-candidate":
        outcome = SQLiteSourceRepository(args.data_dir).promote(args.candidate_id)
    elif args.command == "active-version":
        outcome = SQLiteSourceRepository(args.data_dir).get_active(args.source)
    else:  # pragma: no cover - argparse prevents this branch
        raise AssertionError(args.command)
    print(json.dumps(outcome, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
