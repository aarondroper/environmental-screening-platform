"""Small operator CLI for the local job-oriented vertical slice."""

from __future__ import annotations

import argparse
import json
import os
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from .aoi import (
    GENERIC_AOI_POLICY,
    NORTHERN_COLORADO_REGRESSION_POLICY,
    policy_by_id,
)
from .aoi_ingestion import ingest_aoi
from .catalog import SQLiteSourceRepository
from .ingestion import (
    REQUEST_URLS,
    ingest_3dep,
    ingest_nlcd_aoi,
    ingest_nlcd_regional,
    ingest_source,
    ingest_ssurgo_regional_packages,
    retry_ingestion,
)
from .report import build_aoi_run_report, render_aoi_run_summary
from .spatial import PostGISRepository, PostGISUnavailable, census_boundary_record
from .ssurgo import parse_ssurgo_fixture
from .ssurgo_aoi import ingest_ssurgo_aoi
from .ssurgo_regional import (
    audit_ssurgo_regional_discrepancies,
    validate_ssurgo_regional_packages,
)
from .ssurgo_regional_candidate import materialize_staged_ssurgo_candidate
from .ssurgo_regional_coverage import analyze_ssurgo_regional_coverage
from .ssurgo_regional_staging import stage_ssurgo_regional_packages
from .workflow import (
    FIXTURE_SCREENING_SOURCES,
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
    create.add_argument(
        "--aoi-policy",
        choices=(GENERIC_AOI_POLICY, NORTHERN_COLORADO_REGRESSION_POLICY),
        default=GENERIC_AOI_POLICY,
        help="AOI validation policy; Northern Colorado is an explicit regression/demo policy",
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
    submit.add_argument(
        "--database-url",
        help="Optional PostGIS URL for snapshot-pinned SSURGO fixture consumption",
    )

    fixture_submit = sub.add_parser(
        "screen-ssurgo-fixture",
        help="Run one explicitly fixture-only SSURGO screening job",
    )
    fixture_submit.add_argument("--project-id", required=True)
    fixture_submit.add_argument("--aoi-id")
    fixture_submit.add_argument("--database-url")

    nlcd_submit = sub.add_parser(
        "screen-nlcd-fixture",
        help="Run one explicitly fixture-only Annual NLCD screening job",
    )
    nlcd_submit.add_argument("--project-id", required=True)
    nlcd_submit.add_argument("--aoi-id")

    dep_submit = sub.add_parser(
        "screen-3dep-fixture",
        help="Run one explicitly fixture-only 3DEP elevation screening job",
    )
    dep_submit.add_argument("--project-id", required=True)
    dep_submit.add_argument("--aoi-id")

    active_submit = sub.add_parser(
        "screen-active",
        help="Run snapshot-pinned screening from AOI-scoped active NLCD/3DEP versions",
    )
    active_submit.add_argument("--project-id", required=True)
    active_submit.add_argument("--aoi-id", required=True)
    active_submit.add_argument(
        "--sources",
        nargs="+",
        choices=("nlcd", "3dep"),
        required=True,
        help="AOI-scoped active sources to screen",
    )

    report_run = sub.add_parser(
        "report-aoi-run",
        help="Report the read-only ingestion and screening lifecycle for one AOI revision",
    )
    report_run.add_argument("--project-id", required=True)
    report_run.add_argument("--aoi-id", required=True)
    report_run.add_argument("--aoi-revision", type=int, required=True)
    report_run.add_argument(
        "--format",
        dest="output_format",
        choices=("json", "summary"),
        default="json",
        help="Output format; JSON is machine-readable and summary is terminal-oriented",
    )

    fixtures_submit = sub.add_parser(
        "screen-fixtures",
        help="Run the bounded multi-source fixture screening workflow",
    )
    fixtures_submit.add_argument("--project-id", required=True)
    fixtures_submit.add_argument("--aoi-id")
    fixtures_submit.add_argument(
        "--database-url",
        help="Optional PostGIS URL for snapshot-pinned SSURGO fixture consumption",
    )

    status = sub.add_parser("job-status", help="Show job lifecycle and source attempts")
    status.add_argument("--job-id", required=True)

    retry = sub.add_parser("retry", help="Retry a failed job with the same AOI revision")
    retry.add_argument("--job-id", required=True)
    retry.add_argument("--database-url")

    export = sub.add_parser("export", help="Write result JSON, source CSV, and AOI GeoJSON")
    export.add_argument("--job-id", required=True)
    export.add_argument("--output-dir", type=Path, required=True)

    ingest = sub.add_parser("ingest", help="Acquire and validate a source as an inactive candidate")
    ingest.add_argument("--source", choices=sorted(REQUEST_URLS), required=True)
    ingest.add_argument("--project-id")
    ingest.add_argument("--aoi-id")

    regional_ingest = sub.add_parser(
        "ingest-ssurgo-regional",
        help="Acquire all official regional SSURGO packages as inactive validation candidates",
    )
    regional_ingest.add_argument("--sizing-record", type=Path)

    nlcd_regional_ingest = sub.add_parser(
        "ingest-nlcd-regional",
        help="Acquire the approved three-county Annual NLCD 2025 WCS window as an inactive candidate",
    )
    nlcd_regional_ingest.add_argument("--boundary", type=Path)

    nlcd_ingest = sub.add_parser(
        "ingest-nlcd",
        help="Acquire bounded Annual NLCD for a persisted project AOI",
    )
    nlcd_ingest.add_argument("--project-id", required=True)
    nlcd_ingest.add_argument("--aoi-id")

    dep_ingest = sub.add_parser(
        "ingest-3dep",
        help="Plan and acquire bounded official 3DEP tiles for a persisted project AOI",
    )
    dep_ingest.add_argument("--project-id", required=True)
    dep_ingest.add_argument("--aoi-id")

    ssurgo_ingest = sub.add_parser(
        "ingest-ssurgo",
        help="Discover and acquire bounded official SSURGO packages for a persisted AOI",
    )
    ssurgo_ingest.add_argument("--project-id", required=True)
    ssurgo_ingest.add_argument("--aoi-id")
    ssurgo_ingest.add_argument("--max-survey-areas", type=int, default=16)
    ssurgo_ingest.add_argument("--max-total-bytes", type=int, default=500_000_000)

    aoi_ingest = sub.add_parser(
        "ingest-aoi",
        help="Plan and independently acquire selected sources for one immutable AOI revision",
    )
    aoi_ingest.add_argument("--project-id", required=True)
    aoi_ingest.add_argument("--aoi-id", required=True, help="Immutable AOI revision identifier")
    aoi_ingest.add_argument(
        "--sources",
        nargs="+",
        choices=("nlcd", "3dep", "ssurgo"),
        required=True,
        help="Selected generic source adapters",
    )
    aoi_ingest.add_argument(
        "--max-source-bytes",
        action="append",
        default=[],
        metavar="SOURCE=BYTES",
        help="Override one source byte limit; repeat for multiple sources",
    )
    aoi_ingest.add_argument(
        "--max-source-artifacts",
        action="append",
        default=[],
        metavar="SOURCE=COUNT",
        help="Override one source artifact/tile/package count limit",
    )
    aoi_ingest.add_argument("--max-total-bytes", type=int, default=1_000_000_000)
    aoi_ingest.add_argument("--dry-run", action="store_true")
    aoi_ingest.add_argument("--retry-parent-run-id")
    aoi_ingest.add_argument("--retry-sources", nargs="+", choices=("nlcd", "3dep", "ssurgo"))

    regional_validate = sub.add_parser(
        "validate-ssurgo-regional",
        help="Validate all acquired regional SSURGO packages without promotion",
    )
    regional_validate.add_argument("--sizing-record", type=Path)
    regional_validate.add_argument("--boundary", type=Path)

    regional_audit = sub.add_parser(
        "audit-ssurgo-regional-discrepancies",
        help="Audit acquired SSURGO discrepancies without changing source state",
    )
    regional_audit.add_argument("--sizing-record", type=Path)
    regional_audit.add_argument("--lookup-record", type=Path)
    regional_audit.add_argument("--boundary", type=Path)

    regional_stage = sub.add_parser(
        "stage-ssurgo-regional",
        help="Stage acquired regional SSURGO packages using the audited repair policy",
    )
    regional_stage.add_argument("--sizing-record", type=Path)
    regional_stage.add_argument("--boundary", type=Path)
    regional_stage.add_argument("--database-url")

    regional_candidate = sub.add_parser(
        "materialize-ssurgo-regional-candidate",
        help="Record the existing regional SSURGO staging result as an inactive candidate",
    )
    regional_candidate.add_argument("--staging-report", type=Path)

    regional_coverage = sub.add_parser(
        "analyze-ssurgo-regional-coverage",
        help="Analyze existing staged SSURGO coverage without modifying PostGIS data",
    )
    regional_coverage.add_argument("--candidate-id", required=True)
    regional_coverage.add_argument("--database-url")

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
    promote.add_argument("--project-id")
    promote.add_argument("--aoi-id")
    promote.add_argument("--aoi-revision", type=int)

    active = sub.add_parser("active-version", help="Show the active source version, if any")
    active.add_argument("--source", required=True)
    active.add_argument("--project-id")
    active.add_argument("--aoi-id")
    active.add_argument("--aoi-revision", type=int)

    postgis_migrate = sub.add_parser(
        "postgis-migrate", help="Apply the local canonical spatial schema to PostGIS"
    )
    postgis_migrate.add_argument("--database-url")

    load_boundary = sub.add_parser(
        "postgis-load-boundary", help="Load the validated three-county boundary into PostGIS"
    )
    load_boundary.add_argument("--database-url")
    load_boundary.add_argument("--boundary", type=Path, required=True)
    load_boundary.add_argument("--project-id", required=True)
    load_boundary.add_argument("--aoi-id", required=True)
    load_boundary.add_argument("--aoi-revision", type=int, required=True)
    load_boundary.add_argument("--source-snapshot-id", required=True)
    load_boundary.add_argument("--source-version-id", required=True)

    load_ssurgo = sub.add_parser(
        "postgis-load-ssurgo-fixture",
        help="Stage, validate, and fixture-promote a representative SSURGO response",
    )
    load_ssurgo.add_argument("--database-url")
    load_ssurgo.add_argument("--fixture", type=Path, required=True)
    load_ssurgo.add_argument("--metadata", type=Path)
    load_ssurgo.add_argument("--batch-id", required=True)
    load_ssurgo.add_argument("--source-snapshot-id", required=True)
    load_ssurgo.add_argument("--source-version-id", required=True)
    load_ssurgo.add_argument("--ingestion-run-id")
    load_ssurgo.add_argument("--candidate-id")

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    outcome: Any

    def parse_source_limits(
        byte_values: Sequence[str], artifact_values: Sequence[str]
    ) -> dict[str, dict[str, int]]:
        limits: dict[str, dict[str, int]] = {}
        for raw, key in [
            *((value, "max_bytes") for value in byte_values),
            *((value, "max_artifacts") for value in artifact_values),
        ]:
            if "=" not in raw:
                raise ValueError(f"Expected SOURCE=VALUE, got {raw!r}")
            source, value = raw.split("=", 1)
            if source not in {"nlcd", "3dep", "ssurgo"}:
                raise ValueError(f"Unknown source limit key: {source}")
            try:
                parsed = int(value)
            except ValueError as exc:
                raise ValueError(f"Source limit must be an integer: {raw}") from exc
            limits.setdefault(source, {})[key] = parsed
        return limits

    if args.command == "project-create":
        outcome = create_project(
            args.name,
            args.aoi,
            args.data_dir,
            validation_policy=policy_by_id(args.aoi_policy),
        )
    elif args.command == "aoi-revise":
        outcome = revise_aoi(args.project_id, args.aoi, args.data_dir)
    elif args.command == "screen":
        job = create_job(args.project_id, args.data_dir, args.aoi_id)
        spatial_repository = PostGISRepository(args.database_url) if args.database_url else None
        result = run_job(job["job_id"], args.data_dir, spatial_repository=spatial_repository)
        outcome = {"job": job_status(job["job_id"], args.data_dir), "result": result}
    elif args.command == "screen-ssurgo-fixture":
        job = create_job(
            args.project_id,
            args.data_dir,
            args.aoi_id,
            source_ids=("ssurgo",),
            screening_mode="ssurgo_fixture_only",
        )
        spatial_repository = PostGISRepository(args.database_url)
        spatial_repository.migrate()
        result = run_job(
            job["job_id"],
            args.data_dir,
            spatial_repository=spatial_repository,
        )
        outcome = {"job": job_status(job["job_id"], args.data_dir), "result": result}
    elif args.command == "screen-nlcd-fixture":
        job = create_job(
            args.project_id,
            args.data_dir,
            args.aoi_id,
            source_ids=("annual_nlcd",),
            screening_mode="nlcd_fixture_only",
        )
        result = run_job(job["job_id"], args.data_dir)
        outcome = {"job": job_status(job["job_id"], args.data_dir), "result": result}
    elif args.command == "screen-3dep-fixture":
        job = create_job(
            args.project_id,
            args.data_dir,
            args.aoi_id,
            source_ids=("3dep",),
            screening_mode="3dep_fixture_only",
        )
        result = run_job(job["job_id"], args.data_dir)
        outcome = {"job": job_status(job["job_id"], args.data_dir), "result": result}
    elif args.command == "screen-active":
        source_ids = tuple("annual_nlcd" if source == "nlcd" else "3dep" for source in args.sources)
        job = create_job(
            args.project_id,
            args.data_dir,
            args.aoi_id,
            source_ids=source_ids,
            screening_mode="active_aoi",
            require_aoi_scoped_active=True,
        )
        result = run_job(job["job_id"], args.data_dir)
        outcome = {"job": job_status(job["job_id"], args.data_dir), "result": result}
    elif args.command == "report-aoi-run":
        outcome = build_aoi_run_report(
            args.data_dir,
            project_id=args.project_id,
            aoi_id=args.aoi_id,
            aoi_revision=args.aoi_revision,
        )
    elif args.command == "screen-fixtures":
        job = create_job(
            args.project_id,
            args.data_dir,
            args.aoi_id,
            source_ids=FIXTURE_SCREENING_SOURCES,
            screening_mode="fixtures",
        )
        spatial_repository = None
        if args.database_url or os.environ.get("ESGP_POSTGIS_URL"):
            try:
                spatial_repository = PostGISRepository(args.database_url)
                spatial_repository.migrate()
            except PostGISUnavailable:
                spatial_repository = None
        result = run_job(
            job["job_id"],
            args.data_dir,
            spatial_repository=spatial_repository,
        )
        outcome = {"job": job_status(job["job_id"], args.data_dir), "result": result}
    elif args.command == "job-status":
        outcome = job_status(args.job_id, args.data_dir)
    elif args.command == "retry":
        spatial_repository = PostGISRepository(args.database_url) if args.database_url else None
        outcome = retry_job(args.job_id, args.data_dir, spatial_repository=spatial_repository)
    elif args.command == "export":
        outcome = [str(path) for path in export_result(args.job_id, args.data_dir, args.output_dir)]
    elif args.command == "ingest":
        outcome = ingest_source(
            args.source,
            args.data_dir,
            project_id=args.project_id,
            aoi_id=args.aoi_id,
        )
    elif args.command == "ingest-ssurgo-regional":
        outcome = ingest_ssurgo_regional_packages(
            args.data_dir,
            sizing_record=args.sizing_record,
        )
    elif args.command == "ingest-nlcd-regional":
        outcome = ingest_nlcd_regional(args.data_dir, boundary_path=args.boundary)
    elif args.command == "ingest-nlcd":
        outcome = ingest_nlcd_aoi(
            args.data_dir,
            project_id=args.project_id,
            aoi_id=args.aoi_id,
        )
    elif args.command == "ingest-3dep":
        outcome = ingest_3dep(
            args.data_dir,
            project_id=args.project_id,
            aoi_id=args.aoi_id,
        )
    elif args.command == "ingest-ssurgo":
        outcome = ingest_ssurgo_aoi(
            args.data_dir,
            project_id=args.project_id,
            aoi_id=args.aoi_id,
            max_survey_areas=args.max_survey_areas,
            max_total_bytes=args.max_total_bytes,
        )
    elif args.command == "ingest-aoi":
        outcome = ingest_aoi(
            args.data_dir,
            project_id=args.project_id,
            aoi_id=args.aoi_id,
            sources=args.sources,
            per_source_limits=parse_source_limits(args.max_source_bytes, args.max_source_artifacts),
            max_total_bytes=args.max_total_bytes,
            dry_run=args.dry_run,
            retry_parent_run_id=args.retry_parent_run_id,
            retry_sources=args.retry_sources,
        )
    elif args.command == "validate-ssurgo-regional":
        outcome = validate_ssurgo_regional_packages(
            args.data_dir,
            sizing_record=args.sizing_record,
            boundary_path=args.boundary,
        )
    elif args.command == "audit-ssurgo-regional-discrepancies":
        outcome = audit_ssurgo_regional_discrepancies(
            args.data_dir,
            sizing_record=args.sizing_record,
            lookup_record=args.lookup_record,
            boundary_path=args.boundary,
        )
    elif args.command == "stage-ssurgo-regional":
        outcome = stage_ssurgo_regional_packages(
            args.data_dir,
            database_url=args.database_url,
            sizing_record=args.sizing_record,
            boundary_path=args.boundary,
        )
    elif args.command == "materialize-ssurgo-regional-candidate":
        outcome = materialize_staged_ssurgo_candidate(
            args.data_dir,
            staging_report=args.staging_report,
        )
    elif args.command == "analyze-ssurgo-regional-coverage":
        outcome = analyze_ssurgo_regional_coverage(
            args.data_dir,
            candidate_id=args.candidate_id,
            database_url=args.database_url,
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
        outcome = SQLiteSourceRepository(args.data_dir).promote(
            args.candidate_id,
            project_id=args.project_id,
            aoi_id=args.aoi_id,
            aoi_revision=args.aoi_revision,
        )
    elif args.command == "active-version":
        outcome = SQLiteSourceRepository(args.data_dir).get_active(
            args.source,
            project_id=args.project_id,
            aoi_id=args.aoi_id,
            aoi_revision=args.aoi_revision,
        )
    elif args.command == "postgis-migrate":
        PostGISRepository(args.database_url).migrate()
        outcome = {"status": "migrated"}
    elif args.command == "postgis-load-boundary":
        repository = PostGISRepository(args.database_url)
        repository.migrate()
        record = census_boundary_record(
            args.boundary,
            project_id=args.project_id,
            aoi_id=args.aoi_id,
            aoi_revision=args.aoi_revision,
            source_snapshot_id=args.source_snapshot_id,
            source_version_id=args.source_version_id,
        )
        outcome = repository.insert_aoi_revision(record)
    elif args.command == "postgis-load-ssurgo-fixture":
        repository = PostGISRepository(args.database_url)
        repository.migrate()
        batch = parse_ssurgo_fixture(
            args.fixture,
            batch_id=args.batch_id,
            source_snapshot_id=args.source_snapshot_id,
            source_version_id=args.source_version_id,
            metadata_path=args.metadata,
            ingestion_run_id=args.ingestion_run_id,
            candidate_id=args.candidate_id,
        )
        staged = repository.stage_ssurgo_batch(batch)
        validation = repository.validate_ssurgo_batch(batch.batch_id)
        if validation["validation_status"] != "validated":
            outcome = {"staged": staged, "validation": validation, "promotion": None}
        else:
            outcome = {
                "staged": staged,
                "validation": validation,
                "promotion": repository.promote_ssurgo_batch(batch.batch_id),
            }
    else:  # pragma: no cover - argparse prevents this branch
        raise AssertionError(args.command)
    if args.command == "report-aoi-run" and args.output_format == "summary":
        print(render_aoi_run_summary(outcome))
    else:
        print(json.dumps(outcome, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
