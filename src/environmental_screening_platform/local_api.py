"""Development-only local HTTP bridge for one AOI-scoped NLCD screening run.

The bridge intentionally delegates acquisition, promotion, snapshot binding, and
screening to the existing workflow. It is not a deployed API or a second
catalog; its job record is the existing local screening job with a small bridge
status envelope for the frontend.
"""

from __future__ import annotations

import hashlib
import json
import threading
from concurrent.futures import Executor, ThreadPoolExecutor
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .catalog import SQLiteSourceRepository
from .ingestion import ingest_nlcd_aoi
from .nlcd_preview import generate_nlcd_preview
from .store import read_json, write_json
from .workflow import (
    bind_job_snapshots,
    create_job,
    create_project_from_geojson,
    fail_job,
    queue_failed_job,
    run_job,
)

BRIDGE_SOURCES = ("annual_nlcd", "3dep", "ssurgo", "padus", "fema_nfhl")
MAX_AOI_BYTES = 2_000_000


def _paths(data_root: Path) -> dict[str, Path]:
    return {
        "projects": data_root / "workspace" / "projects",
        "jobs": data_root / "workspace" / "jobs",
    }


def _job_path(data_root: Path, job_id: str) -> Path:
    return _paths(data_root)["jobs"] / job_id / "job.json"


def _source_states(
    *, status: str = "not_evaluated", reason: str | None = None
) -> dict[str, dict[str, Any]]:
    return {
        source_id: {
            "source_id": source_id,
            "status": status if source_id == "annual_nlcd" else "not_evaluated",
            "reason": reason
            if source_id == "annual_nlcd"
            else "Not selected; this local slice evaluates Annual NLCD only.",
        }
        for source_id in BRIDGE_SOURCES
    }


def _update_job(data_root: Path, job_id: str, **updates: Any) -> dict[str, Any]:
    path = _job_path(data_root, job_id)
    job = read_json(path)
    job.update(updates)
    write_json(path, job)
    return job


def _set_phase(data_root: Path, job_id: str, phase: str, **updates: Any) -> dict[str, Any]:
    job = read_json(_job_path(data_root, job_id))
    bridge = dict(job.get("bridge") or {})
    bridge.update({"status": "running", "phase": phase, **updates})
    job["bridge"] = bridge
    write_json(_job_path(data_root, job_id), job)
    return job


def _revision(data_root: Path, project_id: str, aoi_id: str) -> dict[str, Any]:
    path = _paths(data_root)["projects"] / project_id / "aoi-revisions" / f"{aoi_id}.json"
    return read_json(path)


def _source_record(
    source_id: str,
    *,
    source_result: dict[str, Any] | None = None,
    candidate: dict[str, Any] | None = None,
    active: dict[str, Any] | None = None,
    reason: str | None = None,
) -> dict[str, Any]:
    if source_result is None:
        message = reason or "Not selected; this local slice evaluates Annual NLCD only."
        return {
            "source_id": source_id,
            "status_only_reason": message,
            "lifecycle": {"stopped_at": "not_evaluated", "not_evaluated": [{"reason": message}]},
            "screening": [],
            "candidates": [],
            "source_versions": [],
            "active_aoi_versions": [],
            "promotion_decisions": [],
        }
    source_status = source_result.get("source_status") or "active_aoi"
    successful = source_result.get("attempt_status") == "validated"
    state = "screened" if successful else "failed"
    lifecycle: dict[str, Any] = {
        "stopped_at": state,
        "screened": {"observed": successful},
    }
    if candidate:
        lifecycle["acquired"] = {"observed": bool(candidate.get("artifact_path"))}
        lifecycle["validated"] = {"observed": candidate.get("status") == "validated"}
    if active:
        lifecycle["promoted"] = {"observed": True, "active_version_ids": [active["version_id"]]}
    if not successful:
        lifecycle["failed"] = [{"reason": source_result.get("reason") or "NLCD screening failed"}]
    return {
        "source_id": source_id,
        "provider_release": (source_result.get("provenance") or {}).get("provider_release"),
        "availability_status": "available" if successful else "unavailable",
        "lifecycle": lifecycle,
        "candidates": [candidate] if candidate else [],
        "source_versions": [active] if active else [],
        "active_aoi_versions": [active] if active else [],
        "promotion_decisions": [],
        "screening": [{"result": [source_result]}],
        "status_only_reason": None if successful else source_result.get("reason"),
        "source_status": source_status,
    }


def _lineage_issue(
    data_root: Path,
    job: dict[str, Any],
    result: dict[str, Any],
    source_result: dict[str, Any],
    revision: dict[str, Any],
) -> str | None:
    """Reject a presentation result unless its immutable lineage is exact."""
    if result.get("project_id") != job["project_id"] or result.get("aoi_id") != job["aoi_id"]:
        return "Stored result project or AOI identity does not match this job"
    if int(result.get("aoi_revision", -1)) != int(job["aoi_revision"]):
        return "Stored result AOI revision does not match this job"
    if result.get("aoi_geometry_sha256") != revision["geometry_sha256"]:
        return "Stored result geometry hash does not match the immutable AOI revision"
    snapshots = SQLiteSourceRepository(data_root).get_job_snapshots(job["job_id"])
    snapshot = next((item for item in snapshots if item["source_id"] == "annual_nlcd"), None)
    if snapshot is None:
        return "No immutable Annual NLCD source snapshot is attached to this job"
    expected = {
        "source_snapshot_id": snapshot["snapshot_id"],
        "source_version_id": snapshot.get("version_id"),
        "candidate_id": snapshot.get("candidate_id"),
        "ingestion_run_id": snapshot.get("ingestion_run_id"),
        "aoi_geometry_sha256": revision["geometry_sha256"],
    }
    for field, expected_value in expected.items():
        if source_result.get(field) != expected_value:
            return f"Stored Annual NLCD result {field} does not match its immutable source snapshot"
    provenance = source_result.get("provenance") or {}
    if provenance.get("aoi_geometry_sha256") != revision["geometry_sha256"]:
        return "Annual NLCD provenance geometry hash does not match the immutable AOI revision"
    expected_checksum = snapshot.get("provenance", {}).get("sha256")
    if expected_checksum and provenance.get("sha256") != expected_checksum:
        return "Annual NLCD result checksum does not match the snapshotted source version"
    artifact_path = provenance.get("artifact_path")
    if artifact_path and expected_checksum:
        artifact = Path(artifact_path)
        if not artifact.exists():
            return "The snapshotted Annual NLCD artifact is unavailable"
        digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
        if digest != expected_checksum:
            return "The snapshotted Annual NLCD artifact checksum no longer matches"
    return None


def _generate_nlcd_browser_preview(
    data_root: Path, job: dict[str, Any], result: dict[str, Any]
) -> dict[str, Any]:
    """Create the job-scoped NLCD display derivative after screening succeeds."""
    source_result = next(
        item for item in result.get("source_results", []) if item["source_id"] == "annual_nlcd"
    )
    provenance = source_result.get("provenance") or {}
    artifact_path = provenance.get("artifact_path")
    if not artifact_path:
        # Mocked workflow results and catalog-only callers have no raster to display.
        # They retain the existing report shape; a real successful bridge run always
        # has an artifact path from the promoted AOI-scoped version.
        return {}
    if not provenance.get("sha256"):
        raise ValueError("Validated NLCD result has no source checksum for browser preview lineage")
    revision = _revision(data_root, job["project_id"], job["aoi_id"])
    source_metadata = {
        "source_id": "annual_nlcd",
        "source_snapshot_id": source_result.get("source_snapshot_id"),
        "source_version_id": source_result.get("source_version_id"),
        "candidate_id": source_result.get("candidate_id"),
        "ingestion_run_id": source_result.get("ingestion_run_id"),
        "sha256": provenance.get("sha256"),
        "source_year": (source_result.get("metrics") or {}).get("source_year", 2025),
        "provider_release": provenance.get("provider_release"),
        "source_url": provenance.get("source_url"),
        "retrieved_at": provenance.get("retrieved_at"),
        "terms_url": provenance.get("terms_url"),
        "aoi_geometry_sha256": revision["geometry_sha256"],
    }
    preview_dir = data_root / "workspace" / "jobs" / job["job_id"] / "browser-previews"
    preview_png = preview_dir / "annual-nlcd-preview.png"
    metadata_json = preview_dir / "annual-nlcd-preview.json"
    metadata = generate_nlcd_preview(
        Path(artifact_path),
        preview_png,
        metadata_json,
        aoi_geometry=revision["geometry"],
        aoi_revision=int(revision["revision"]),
        aoi_geometry_sha256=revision["geometry_sha256"],
        source_metadata=source_metadata,
    )
    return {
        "status": "available",
        "display_derivative": True,
        "source_id": "annual_nlcd",
        "source_year": metadata["source_year"],
        "source_snapshot_id": source_result.get("source_snapshot_id"),
        "source_version_id": source_result.get("source_version_id"),
        "candidate_id": source_result.get("candidate_id"),
        "ingestion_run_id": source_result.get("ingestion_run_id"),
        "source_sha256": metadata["source"]["sha256"],
        "aoi_revision": int(revision["revision"]),
        "aoi_geometry_sha256": revision["geometry_sha256"],
        "asset_url": f"/api/screening-jobs/{job['job_id']}/nlcd-preview/asset",
        "metadata_url": f"/api/screening-jobs/{job['job_id']}/nlcd-preview/metadata",
        "opacity_default": metadata["display"]["opacity_default"],
        "default_visible": True,
        "legend": metadata["legend"],
        "representation": "AOI-specific categorical RGBA display derivative",
    }


def _normalize_browser_previews(browser_previews: dict[str, Any] | None) -> dict[str, Any]:
    """Return the source-keyed preview shape expected by the presentation layer.

    Jobs written by the first AOI-preview implementation stored the single
    Annual NLCD preview object directly. Normalize that legacy shape when it
    is read so an already-completed job cannot regress to metrics-only display.
    """
    if not browser_previews:
        return {}
    if browser_previews.get("source_id") == "annual_nlcd" and "status" in browser_previews:
        return {"annual_nlcd": browser_previews}
    return browser_previews


def _presentation_report(
    data_root: Path,
    job: dict[str, Any],
    result: dict[str, Any] | None,
    *,
    bridge_status: str,
    bridge_phase: str,
    failure_reason: str | None = None,
    browser_previews: dict[str, Any] | None = None,
) -> dict[str, Any]:
    revision = _revision(data_root, job["project_id"], job["aoi_id"])
    project = read_json(_paths(data_root)["projects"] / job["project_id"] / "project.json")
    spatial = revision["spatial_validation"]
    aoi = dict(revision)
    aoi["policy"] = revision.get("validation_policy", "generic")
    aoi["revision"] = int(revision["revision"])
    aoi["area"] = {
        "value_sqkm": spatial.get("area_sqkm"),
        "crs": spatial.get("area_crs", "EPSG:5070"),
    }
    source_result = None
    candidate = None
    active = None
    if result:
        source_result = next(
            (
                item
                for item in result.get("source_results", [])
                if item["source_id"] == "annual_nlcd"
            ),
            None,
        )
        lineage_issue = (
            _lineage_issue(data_root, job, result, source_result, revision)
            if source_result
            else "Stored result has no Annual NLCD source result"
        )
        if lineage_issue:
            failure_reason = lineage_issue
            source_result = None
            bridge_status = "failed"
            bridge_phase = "lineage_validation"
        if source_result and source_result.get("candidate_id"):
            candidate = SQLiteSourceRepository(data_root).get_candidate(
                source_result["candidate_id"]
            )
        active = SQLiteSourceRepository(data_root).get_active(
            "annual_nlcd",
            project_id=job["project_id"],
            aoi_id=job["aoi_id"],
            aoi_revision=int(job["aoi_revision"]),
        )
    sources = {source_id: _source_record(source_id) for source_id in BRIDGE_SOURCES}
    if source_result:
        sources["annual_nlcd"] = _source_record(
            "annual_nlcd", source_result=source_result, candidate=candidate, active=active
        )
    elif failure_reason:
        sources["annual_nlcd"] = _source_record("annual_nlcd", reason=failure_reason)
        sources["annual_nlcd"]["lifecycle"] = {
            "stopped_at": "failed",
            "failed": [{"reason": failure_reason}],
        }
        sources["annual_nlcd"]["status_only_reason"] = failure_reason
    return {
        "project": project,
        "aoi": aoi,
        "selected_sources": list(BRIDGE_SOURCES),
        "sources": sources,
        "browser_previews": _normalize_browser_previews(browser_previews),
        "aoi_context": {
            "origin": "user_provided",
            "screened": bool(source_result and bridge_status == "succeeded"),
            "stale_recorded_results": False,
            "geometry_sha256": revision["geometry_sha256"],
        },
        "screening_run": {
            "status": bridge_status,
            "phase": bridge_phase,
            "job_id": job["job_id"],
            "aoi_id": job["aoi_id"],
            "aoi_revision": job["aoi_revision"],
            "aoi_geometry_sha256": revision["geometry_sha256"],
            "source_id": "annual_nlcd",
            "reason": failure_reason,
        },
        "warnings": [
            "This local run evaluates Annual NLCD only; 3DEP, SSURGO, FEMA, and PAD-US remain not evaluated.",
            "No browser preview is attached unless its AOI, revision, source version, snapshot, and checksum lineage exactly matches this run.",
        ],
        **({"result": result} if result else {}),
    }


class LocalScreeningBridge:
    """Run one local generic-AOI NLCD acquisition/screening lifecycle."""

    def __init__(self, data_root: Path, *, executor: Executor | None = None) -> None:
        self.data_root = data_root.resolve()
        self._executor = executor or ThreadPoolExecutor(
            max_workers=2, thread_name_prefix="nlcd-screen"
        )
        self._owns_executor = executor is None
        self._lock = threading.Lock()

    def close(self) -> None:
        if self._owns_executor and isinstance(self._executor, ThreadPoolExecutor):
            self._executor.shutdown(wait=True, cancel_futures=False)

    def submit(self, *, project_name: str, geojson: dict[str, Any]) -> dict[str, Any]:
        created = create_project_from_geojson(project_name, geojson, self.data_root)
        project = created["project"]
        revision = created["aoi_revision"]
        job = create_job(
            project["project_id"],
            self.data_root,
            revision["aoi_id"],
            source_ids=("annual_nlcd",),
            screening_mode="active_aoi",
            require_aoi_scoped_active=True,
            defer_source_snapshot=True,
        )
        job["bridge"] = {
            "status": "queued",
            "phase": "queued",
            "source_statuses": _source_states(),
            "attempt": 1,
        }
        write_json(_job_path(self.data_root, job["job_id"]), job)
        self._executor.submit(self._execute, job["job_id"])
        return self.status(job["job_id"])

    def retry(self, job_id: str) -> dict[str, Any]:
        job = queue_failed_job(job_id, self.data_root)
        bridge = dict(job.get("bridge") or {})
        bridge["status"] = "queued"
        bridge["phase"] = "queued"
        bridge["attempt"] = int(bridge.get("attempt", 1)) + 1
        job["bridge"] = bridge
        write_json(_job_path(self.data_root, job_id), job)
        self._executor.submit(self._execute, job_id)
        return self.status(job_id)

    def _execute(self, job_id: str) -> None:
        job = read_json(_job_path(self.data_root, job_id))
        result: dict[str, Any] | None = None
        try:
            if not job.get("source_snapshot_ids"):
                _set_phase(self.data_root, job_id, "acquiring")
                acquisition = ingest_nlcd_aoi(
                    self.data_root,
                    project_id=job["project_id"],
                    aoi_id=job["aoi_id"],
                )
                candidate = acquisition.get("candidate") or {}
                if candidate.get("status") != "validated":
                    raise ValueError(
                        f"NLCD acquisition did not produce a validated candidate: {candidate.get('status', 'missing')}"
                    )
                _set_phase(
                    self.data_root,
                    job_id,
                    "promoting",
                    source_statuses={
                        **_source_states(),
                        "annual_nlcd": {
                            "source_id": "annual_nlcd",
                            "status": "validated",
                            "candidate_id": candidate.get("candidate_id"),
                            "source_version_id": candidate.get("version_id"),
                        },
                    },
                )
                promotion = SQLiteSourceRepository(self.data_root).promote(
                    candidate["candidate_id"],
                    project_id=job["project_id"],
                    aoi_id=job["aoi_id"],
                    aoi_revision=int(job["aoi_revision"]),
                )
                if promotion.get("decision") != "promoted":
                    raise ValueError(
                        f"NLCD candidate promotion was rejected: {promotion.get('reason')}"
                    )
                bind_job_snapshots(job_id, self.data_root, require_aoi_scoped_active=True)
            _set_phase(self.data_root, job_id, "screening")
            result = run_job(job_id, self.data_root)
            source_result = next(
                item for item in result["source_results"] if item["source_id"] == "annual_nlcd"
            )
            if source_result["attempt_status"] != "validated":
                raise ValueError(source_result.get("reason") or "NLCD screening failed")
            nlcd_preview = _generate_nlcd_browser_preview(
                self.data_root,
                read_json(_job_path(self.data_root, job_id)),
                result,
            )
            # Presentation reports expose previews keyed by source identifier.
            # Keep the single-source generator focused on creating one preview,
            # then normalize its result at the bridge boundary so the frontend
            # can discover the job-scoped Annual NLCD asset reliably.
            browser_previews = {"annual_nlcd": nlcd_preview} if nlcd_preview else {}
            report = _presentation_report(
                self.data_root,
                read_json(_job_path(self.data_root, job_id)),
                result,
                bridge_status="succeeded",
                bridge_phase="completed",
                browser_previews=browser_previews,
            )
            result["local_bridge"] = report["screening_run"]
            result["browser_previews"] = browser_previews
            write_json(self.data_root / "workspace" / "jobs" / job_id / "result.json", result)
            job = read_json(_job_path(self.data_root, job_id))
            job["bridge"] = {
                **dict(job.get("bridge") or {}),
                "status": "succeeded",
                "phase": "completed",
                "source_statuses": {
                    "annual_nlcd": {"source_id": "annual_nlcd", "status": "succeeded"},
                    **{
                        source_id: {"source_id": source_id, "status": "not_evaluated"}
                        for source_id in BRIDGE_SOURCES
                        if source_id != "annual_nlcd"
                    },
                },
            }
            write_json(_job_path(self.data_root, job_id), job)
        except Exception as exc:
            reason = f"{type(exc).__name__}: {exc}"
            fail_job(job_id, self.data_root, reason)
            job = read_json(_job_path(self.data_root, job_id))
            job["bridge"] = {
                **dict(job.get("bridge") or {}),
                "status": "failed",
                "phase": "failed",
                "source_statuses": {
                    **_source_states(status="failed", reason=reason),
                    "annual_nlcd": {
                        "source_id": "annual_nlcd",
                        "status": "failed",
                        "reason": reason,
                    },
                },
            }
            write_json(_job_path(self.data_root, job_id), job)
            failed_report = _presentation_report(
                self.data_root,
                job,
                result,
                bridge_status="failed",
                bridge_phase="failed",
                failure_reason=reason,
            )
            write_json(
                self.data_root / "workspace" / "jobs" / job_id / "bridge-report.json", failed_report
            )

    def status(self, job_id: str) -> dict[str, Any]:
        job = read_json(_job_path(self.data_root, job_id))
        result_path = self.data_root / "workspace" / "jobs" / job_id / "result.json"
        bridge_report_path = self.data_root / "workspace" / "jobs" / job_id / "bridge-report.json"
        result = read_json(result_path) if result_path.exists() else None
        report = None
        if result and job.get("bridge", {}).get("status") == "succeeded":
            report = _presentation_report(
                self.data_root,
                job,
                result,
                bridge_status="succeeded",
                bridge_phase="completed",
                browser_previews=result.get("browser_previews", {}),
            )
        elif bridge_report_path.exists():
            report = read_json(bridge_report_path)
        return {
            "job_id": job_id,
            "status": (job.get("bridge") or {}).get("status", job.get("status")),
            "phase": (job.get("bridge") or {}).get("phase", job.get("status")),
            "job": job,
            "project_id": job.get("project_id"),
            "aoi_id": job.get("aoi_id"),
            "aoi_revision": job.get("aoi_revision"),
            "aoi_geometry_sha256": _revision(self.data_root, job["project_id"], job["aoi_id"])[
                "geometry_sha256"
            ],
            "source_statuses": (job.get("bridge") or {}).get("source_statuses", _source_states()),
            "result": result,
            "report": report,
        }


def serve_local_api(
    data_root: Path,
    *,
    frontend_dir: Path | None = None,
    host: str = "127.0.0.1",
    port: int = 8080,
) -> None:
    """Serve the static frontend and local screening bridge from one origin."""
    bridge = LocalScreeningBridge(data_root)
    static_root = (frontend_dir or Path("frontend/dist")).resolve()

    class Handler(SimpleHTTPRequestHandler):
        """Serve API routes and the built frontend from one local origin."""

        def translate_path(self, path: str) -> str:
            return str(static_root / path.lstrip("/"))

        def _json(self, status: int, body: dict[str, Any]) -> None:
            payload = json.dumps(body, ensure_ascii=False, sort_keys=True).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(payload)

        def _body(self) -> dict[str, Any]:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > MAX_AOI_BYTES:
                raise ValueError("Request body is empty or exceeds the local AOI size limit")
            body = json.loads(self.rfile.read(length))
            if not isinstance(body, dict):
                raise ValueError("Request body must be a GeoJSON object")
            return body

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path.startswith("/api/screening-jobs/"):
                parts = parsed.path.strip("/").split("/")
                job_id = parts[2] if len(parts) >= 3 else ""
                try:
                    if parts[3:] == ["nlcd-preview", "metadata"]:
                        path = self._job_preview_path(job_id, "annual-nlcd-preview.json")
                        self._json(200, read_json(path))
                        return
                    if parts[3:] == ["nlcd-preview", "asset"]:
                        path = self._job_preview_path(job_id, "annual-nlcd-preview.png")
                        payload = path.read_bytes()
                        self.send_response(200)
                        self.send_header("Content-Type", "image/png")
                        self.send_header("Content-Length", str(len(payload)))
                        self.send_header("Cache-Control", "no-store")
                        self.end_headers()
                        self.wfile.write(payload)
                        return
                    self._json(200, bridge.status(job_id))
                except (FileNotFoundError, ValueError, KeyError) as exc:
                    self._json(404, {"error": str(exc)})
                return
            super().do_GET()

        def _job_preview_path(self, job_id: str, name: str) -> Path:
            if not job_id or "/" in job_id or "\\" in job_id:
                raise FileNotFoundError("Invalid screening job identifier")
            path = self.server_data_root / "workspace" / "jobs" / job_id / "browser-previews" / name
            if not path.is_file():
                raise FileNotFoundError(path)
            return path

        @property
        def server_data_root(self) -> Path:
            return data_root.resolve()

        def do_POST(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            try:
                if parsed.path == "/api/screening/nlcd":
                    body = self._body()
                    geojson = (
                        body
                        if body.get("type")
                        in {"Feature", "FeatureCollection", "Polygon", "MultiPolygon"}
                        else body.get("aoi") or body.get("geojson")
                    )
                    if not isinstance(geojson, dict):
                        raise ValueError("Request must contain an AOI GeoJSON object")
                    status = bridge.submit(
                        project_name=str(
                            body.get("project_name") or "Local environmental screening"
                        ),
                        geojson=geojson,
                    )
                    self._json(202, status)
                    return
                if parsed.path.endswith("/retry") and parsed.path.startswith(
                    "/api/screening-jobs/"
                ):
                    job_id = parsed.path.split("/")[-2]
                    self._json(202, bridge.retry(job_id))
                    return
                self._json(404, {"error": "Unknown local screening endpoint"})
            except (ValueError, json.JSONDecodeError, FileNotFoundError) as exc:
                self._json(400, {"error": str(exc)})

    server = ThreadingHTTPServer((host, port), Handler)
    try:
        server.serve_forever()
    finally:
        bridge.close()
        server.server_close()
