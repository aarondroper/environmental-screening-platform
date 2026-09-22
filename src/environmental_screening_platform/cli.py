"""Small operator CLI for the local job-oriented vertical slice."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

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
    else:  # pragma: no cover - argparse prevents this branch
        raise AssertionError(args.command)
    print(json.dumps(outcome, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
