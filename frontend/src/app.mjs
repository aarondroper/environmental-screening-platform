const SOURCE_LABELS = {
  annual_nlcd: "Annual NLCD 2025",
  "3dep": "USGS 3DEP",
  ssurgo: "NRCS SSURGO",
  padus: "PAD-US",
  fema_nfhl: "FEMA NFHL",
};

const STAGE_LABELS = {
  acquired: "Acquired",
  validated: "Validated",
  promoted: "Promoted",
  screened: "Screened",
};

const STATUS_LABELS = {
  observed: "Observed",
  partial: "Partial",
  conditional: "Conditional",
  screened: "Screened",
  promoted: "Promoted",
  validated: "Validated",
  acquired: "Acquired",
  incomplete: "Incomplete",
  unavailable: "Unavailable",
  rejected: "Rejected",
  unknown: "Unknown",
  blocked: "Blocked",
  quarantined: "Quarantined",
  failed: "Failed",
  not_started: "Not started",
};

const STATUS_HELP = {
  observed: "A source-specific screening observation was recorded.",
  partial: "The recorded screening includes different source completion states.",
  conditional: "The source remains conditional and is not fully validated for this report.",
  screened: "A source-specific screening result was recorded.",
  promoted: "An AOI-scoped source version is active.",
  validated: "A candidate passed source validation but is not active.",
  acquired: "An artifact was acquired but later lifecycle stages are not recorded.",
  incomplete: "The source has incomplete coverage or processing evidence.",
  unavailable: "The source could not be used for this run.",
  rejected: "A candidate or promotion decision was rejected.",
  unknown: "The report does not establish an observation for this source.",
  blocked: "Provider access or a source gate blocked processing.",
  quarantined: "Source geometry or observations were retained for review and not accepted.",
  failed: "An acquisition or processing attempt failed.",
  not_started: "No lifecycle record was found.",
};

const escapeHtml = (value) => String(value ?? "—")
  .replaceAll("&", "&amp;")
  .replaceAll("<", "&lt;")
  .replaceAll(">", "&gt;")
  .replaceAll('"', "&quot;")
  .replaceAll("'", "&#039;");

const formatBytes = (value) => {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "—";
  const bytes = Number(value);
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 ** 3) return `${(bytes / 1024 ** 2).toFixed(1)} MB`;
  return `${(bytes / 1024 ** 3).toFixed(2)} GB`;
};

const formatNumber = (value, digits = 2) => {
  if (value === null || value === undefined || value === "") return "—";
  const number = Number(value);
  return Number.isFinite(number) ? number.toLocaleString(undefined, { maximumFractionDigits: digits }) : String(value);
};

const lifecycleState = (source = {}) => {
  const lifecycle = source.lifecycle || {};
  for (const state of ["blocked", "unavailable", "incomplete", "failed", "unknown", "quarantined"]) {
    if ((lifecycle[state] || []).length) return state;
  }
  for (const stage of ["screened", "promoted", "validated", "acquired"]) {
    if (lifecycle[stage]?.observed) return stage;
  }
  return lifecycle.stopped_at || "not_started";
};

const candidateDispositionState = (row = {}) => {
  const source = row.source || {};
  const lifecycle = row.lifecycle || {};
  const decisions = source.promotion_decisions || [];
  if (decisions.some((decision) => decision.decision === "rejected") || lifecycle.rejected?.length) return "rejected";
  if (lifecycle.promoted?.observed) return "promoted";
  const candidate = source.candidates?.at(-1);
  if (candidate?.status === "incomplete" || lifecycle.incomplete?.length) return "incomplete";
  if (candidate?.status === "validated" || lifecycle.validated?.observed) return "validated";
  if (candidate?.status === "acquired" || lifecycle.acquired?.observed) return "acquired";
  return "unknown";
};

const stageApplicable = (row, stage) => {
  const lifecycle = row.lifecycle || {};
  if (lifecycle[stage]?.observed) return true;
  if (["blocked", "unavailable", "unknown", "quarantined"].includes(row.state)) return false;
  if (["planned", "acquired", "validated"].includes(stage)) {
    return Boolean(row.source.parent_summaries?.length || row.source.ingestion_runs?.length || row.source.candidates?.length || row.source.source_versions?.length || row.source.screening?.length);
  }
  if (stage === "promoted") return Boolean(row.source.candidates?.length || row.source.promotion_decisions?.length || lifecycle.validated?.observed);
  if (stage === "screened") return Boolean(row.source.screening?.length || lifecycle.promoted?.observed || lifecycle.validated?.observed);
  return false;
};

export const summarizeStage = (rows, stage) => {
  const applicableRows = rows.filter((row) => stageApplicable(row, stage));
  const observed = applicableRows.filter((row) => stage === "planned"
    ? Boolean(row.source.parent_summaries?.length)
    : row.lifecycle[stage]?.observed).length;
  return { observed, applicable: applicableRows.length, excluded: rows.length - applicableRows.length };
};

export const sourceRows = (report = {}) => {
  const sourceMap = report.sources || {};
  const ids = report.selected_sources || Object.keys(sourceMap);
  return ids.map((sourceId) => {
    const source = sourceMap[sourceId] || { source_id: sourceId };
    return {
      id: sourceId,
      label: SOURCE_LABELS[sourceId] || sourceId,
      source,
      state: lifecycleState(source),
      lifecycle: source.lifecycle || {},
      result: source.screening?.at(-1)?.result?.[0] || null,
    };
  });
};

const statusBadge = (state) => `<span class="badge badge-${escapeHtml(state)}" title="${escapeHtml(STATUS_HELP[state] || "Source lifecycle state")}">${escapeHtml(STATUS_LABELS[state] || state)}</span>`;

const valueList = (items) => items.length ? items.map((item) => `<code>${escapeHtml(item)}</code>`).join(" ") : "—";

const sourceMetrics = (row) => {
  const metrics = row.result?.metrics || row.source.candidates?.at(-1)?.validation?.metrics || {};
  const coverage = metrics.coverage || {};
  const pixels = metrics.pixel_accounting || {};
  const fields = [];
  if (row.id === "annual_nlcd") {
    fields.push(["AOI coverage", coverage.covered_aoi_percentage === undefined ? null : `${formatNumber(coverage.covered_aoi_percentage)}%`]);
    fields.push(["Valid pixels", metrics.valid_pixel_count ?? pixels.valid_pixel_count]);
    fields.push(["Nodata pixels", metrics.nodata_pixel_count ?? pixels.nodata_pixel_count]);
    fields.push(["Classes observed", Object.keys(metrics.classes || {}).join(", ") || null]);
    fields.push(["Raster", metrics.raster ? `${metrics.raster.crs || "—"}, ${metrics.raster.width || "—"}×${metrics.raster.height || "—"}, ${metrics.raster.nodata ?? "—"} nodata` : null]);
  } else if (row.id === "3dep") {
    fields.push(["AOI coverage", coverage.covered_aoi_percentage === undefined ? null : `${formatNumber(coverage.covered_aoi_percentage)}%`]);
    fields.push(["Valid cells", metrics.valid_cell_count ?? pixels.valid_pixel_count]);
    fields.push(["Nodata cells", metrics.nodata_cell_count ?? pixels.nodata_pixel_count]);
    fields.push(["Elevation", metrics.minimum_elevation === undefined ? null : `${formatNumber(metrics.minimum_elevation)}–${formatNumber(metrics.maximum_elevation)} ${metrics.elevation_units || "units"}`]);
    fields.push(["Mean", metrics.mean_elevation === undefined ? null : `${formatNumber(metrics.mean_elevation)} ${metrics.elevation_units || "units"}`]);
    fields.push(["Raster", metrics.raster ? `${metrics.raster.crs || metrics.raster.source_crs || "—"}, ${metrics.raster.width || metrics.raster.dimensions?.width || "—"}×${metrics.raster.height || metrics.raster.dimensions?.height || "—"}` : null]);
  } else if (Object.keys(metrics).length) {
    fields.push(...Object.entries(metrics).slice(0, 5).map(([key, value]) => [key.replaceAll("_", " "), typeof value === "object" ? JSON.stringify(value) : value]));
  }
  return fields.filter(([, value]) => value !== null && value !== undefined).map(([label, value]) => `<div class="metric"><dt>${escapeHtml(label)}</dt><dd>${escapeHtml(value)}</dd></div>`).join("") || `<p class="muted">No source-specific screening metrics recorded.</p>`;
};

const sourceDetail = (row) => {
  const source = row.source;
  const lifecycle = row.lifecycle;
  const candidate = source.candidates?.at(-1) || {};
  const version = source.active_aoi_versions?.at(-1) || source.source_versions?.at(-1) || {};
  const attempts = source.ingestion_runs?.flatMap((run) => run.acquisition_attempts || []) || [];
  const result = row.result || {};
  const provenance = result.provenance || {};
  const error = lifecycle.incomplete?.at(-1)?.reason || lifecycle.failed?.at(-1)?.reason || lifecycle.blocked?.at(-1)?.reason || lifecycle.unknown?.at(-1)?.reason || source.status_only_reason || result.reason;
  const disposition = candidateDispositionState(row);
  return `<article class="source-card" data-source="${escapeHtml(row.id)}">
    <div class="source-card-heading"><div><p class="eyebrow">Source pathway</p><h3>${escapeHtml(row.label)}</h3></div>${statusBadge(row.state)}</div>
    <div class="lifecycle" aria-label="${escapeHtml(row.label)} lifecycle">
      ${Object.entries(STAGE_LABELS).map(([stage, label]) => `<span class="stage ${lifecycle[stage]?.observed ? "stage-done" : ""}"><i></i>${label}</span>`).join("")}
    </div>
    <dl class="metrics">${sourceMetrics(row)}</dl>
    <div class="evidence-grid">
      <div><span class="label">Plans</span><strong>${source.parent_summaries?.length || 0}</strong></div>
      <div><span class="label">Attempts</span><strong>${attempts.length || lifecycle.acquired?.attempt_count || 0}</strong></div>
      <div><span class="label">Artifacts</span><strong>${lifecycle.acquired?.artifact_count || 0}</strong></div>
      <div><span class="label">Bytes</span><strong>${formatBytes(source.acquisition_summary?.bytes_downloaded?.at(-1) || candidate.byte_size)}</strong></div>
    </div>
    <dl class="provenance">
      <div><dt>Candidate</dt><dd><code>${escapeHtml(candidate.candidate_id)}</code> · ${escapeHtml(candidate.status || "—")}</dd></div>
      <div><dt>Lifecycle</dt><dd>${statusBadge(row.state)} <small>${escapeHtml(lifecycle.stopped_at || row.state)}</small></dd></div>
      <div><dt>Candidate disposition</dt><dd>${statusBadge(disposition)}</dd></div>
      ${source.availability_status ? `<div><dt>Availability</dt><dd>${statusBadge(source.availability_status)}</dd></div>` : ""}
      <div><dt>Active version</dt><dd><code>${escapeHtml(version.version_id || lifecycle.promoted?.active_version_ids?.at(-1))}</code></dd></div>
      <div><dt>Checksum</dt><dd><code class="hash">${escapeHtml(candidate.sha256 || version.sha256 || provenance.sha256)}</code></dd></div>
      <div><dt>Artifact path</dt><dd class="path">${escapeHtml(candidate.artifact_path || version.artifact_path)}</dd></div>
      <div><dt>Source snapshot</dt><dd><code>${escapeHtml(provenance.source_snapshot_id || row.source.screening?.at(-1)?.source_snapshots?.[0]?.snapshot_id)}</code></dd></div>
    </dl>
    ${error ? `<div class="callout callout-${escapeHtml(row.state)}"><strong>${escapeHtml(STATUS_LABELS[row.state] || "State")}</strong><p>${escapeHtml(typeof error === "object" ? JSON.stringify(error) : error)}</p></div>` : ""}
    <details><summary>Raw source evidence</summary><pre>${escapeHtml(JSON.stringify({ candidate, version, result, lifecycle }, null, 2))}</pre></details>
  </article>`;
};

const screeningStatus = (row) => {
  if (row.id === "padus") return `${statusBadge("conditional")} ${statusBadge("unknown")}`;
  if (row.id === "fema_nfhl") return `${statusBadge("blocked")} ${statusBadge("unavailable")}`;
  if (row.result?.observation_status === "data_observed") return statusBadge("observed");
  return statusBadge(row.state);
};

const screeningMetric = (label, value) => `<div class="screening-metric"><dt>${escapeHtml(label)}</dt><dd>${escapeHtml(value)}</dd></div>`;

const screeningMetrics = (row) => {
  const metrics = row.result?.metrics || {};
  const coverage = metrics.coverage || {};
  if (row.id === "annual_nlcd" && row.result) {
    const classes = Object.values(metrics.classes || {}).map((item) => `${item.class_name || "class"}: ${formatNumber(item.pixel_count, 0)}`).join(" · ");
    return [
      screeningMetric("AOI coverage", `${formatNumber(coverage.covered_aoi_percentage)}% covered`),
      screeningMetric("Valid pixels", formatNumber(metrics.valid_pixel_count, 0)),
      screeningMetric("Nodata pixels", formatNumber(metrics.nodata_pixel_count, 0)),
      screeningMetric("Observed classes", classes || "—"),
    ];
  }
  if (row.id === "3dep" && row.result) {
    const raster = metrics.raster || {};
    return [
      screeningMetric("AOI coverage", `${formatNumber(coverage.covered_aoi_percentage)}% covered`),
      screeningMetric("Valid cells", formatNumber(metrics.valid_cell_count, 0)),
      screeningMetric("Nodata cells", formatNumber(metrics.nodata_cell_count, 0)),
      screeningMetric("Elevation", `${formatNumber(metrics.minimum_elevation)}–${formatNumber(metrics.maximum_elevation)} ${metrics.elevation_units || "units"}`),
      screeningMetric("Mean", `${formatNumber(metrics.mean_elevation)} ${metrics.elevation_units || "units"}`),
      screeningMetric("Grid", `${raster.source_crs || raster.crs || "—"} · ${raster.nodata ?? "—"} nodata`),
    ];
  }
  if (row.id === "ssurgo") {
    return [
      screeningMetric("Coverage", "Incomplete / partial"),
      screeningMetric("Screening result", "Not recorded"),
      screeningMetric("Candidate", "Rejected for incomplete coverage"),
      screeningMetric("Interpretation", "Soil indicator only"),
    ];
  }
  if (row.id === "fema_nfhl") {
    return [
      screeningMetric("Availability", "Unavailable — provider access blocked"),
      screeningMetric("Effective / pending", "Sample validation incomplete"),
      screeningMetric("Unmapped areas", "Unknown, not hazard-free"),
    ];
  }
  return [
    screeningMetric("Validation", "Conditional / quarantined"),
    screeningMetric("Coverage", "Unknown"),
    screeningMetric("Screening result", "Not recorded"),
  ];
};

const screeningProvenance = (row) => {
  const source = row.source;
  const candidate = source.candidates?.at(-1) || {};
  const version = source.active_aoi_versions?.at(-1) || source.source_versions?.at(-1) || {};
  const result = row.result || {};
  const provenance = result.provenance || {};
  const versionId = version.version_id || result.source_version_id;
  const snapshotId = provenance.source_snapshot_id || result.source_snapshot_id;
  const checksum = candidate.sha256 || version.sha256 || provenance.sha256;
  if (!versionId && !snapshotId && !checksum) return `<p class="muted">No source version or screening snapshot was recorded for this status-only source.</p>`;
  return `<dl class="screening-provenance">
    <div><dt>Source version</dt><dd><code>${escapeHtml(versionId)}</code></dd></div>
    <div><dt>Screening snapshot</dt><dd><code>${escapeHtml(snapshotId)}</code></dd></div>
    <div><dt>Checksum</dt><dd><code class="hash">${escapeHtml(checksum)}</code></dd></div>
  </dl>`;
};

const screeningSourceCard = (row) => {
  const source = row.source;
  const limitation = row.id === "ssurgo"
    ? "Hydric-soil information; not a wetlands inventory or regulatory determination."
    : row.id === "fema_nfhl"
      ? "FEMA was not screened; provider access is blocked and unavailable areas remain unknown."
      : row.id === "padus"
        ? "PAD-US remains conditional/quarantined; regional coverage is unknown and no screening was performed."
        : "Independent source result; no cross-source score or suitability conclusion is calculated.";
  return `<article class="screening-card" data-screening-source="${escapeHtml(row.id)}">
    <div class="screening-card-head"><div><p class="eyebrow">${escapeHtml(row.id)}</p><h3>${escapeHtml(row.label)}</h3></div><div class="status-stack">${screeningStatus(row)}</div></div>
    <p class="screening-observation">${escapeHtml(row.result ? (row.result.observation_status === "data_observed" ? "Observed in the recorded AOI result." : row.result.observation_status) : source.status_only_reason || "No source-specific screening result was recorded.")}</p>
    <dl class="screening-metrics">${screeningMetrics(row).join("")}</dl>
    <p class="screening-limitation">${escapeHtml(limitation)}</p>
    <details><summary>Source provenance and details</summary>${screeningProvenance(row)}</details>
  </article>`;
};

const renderAoiMap = (aoi) => {
  return `<div class="aoi-map" data-aoi-map><div class="map-state map-state-loading" data-map-status role="status">Loading public basemap…</div></div>`;
};

const layerState = (row) => {
  if (row.id === "annual_nlcd" || row.id === "3dep") {
    return { state: row.result ? "observed" : "unknown", label: "Metrics only", detail: "Recorded raster metrics; no browser-ready raster overlay is included." };
  }
  if (row.id === "ssurgo") return { state: "incomplete", label: "Incomplete", detail: "Fixture coverage is incomplete; no soil layer is rendered." };
  if (row.id === "padus") return { state: "conditional", label: "Conditional / unknown", detail: "Regional coverage and repair statistics remain unverified." };
  if (row.id === "fema_nfhl") return { state: "unavailable", label: "Unavailable / blocked", detail: "Provider access is blocked; no flood layer was screened." };
  return { state: row.state, label: STATUS_LABELS[row.state] || row.state, detail: STATUS_HELP[row.state] || "No renderable layer was recorded." };
};

const workspaceSourceRow = (row) => {
  const layer = layerState(row);
  const metric = screeningMetrics(row).join("");
  return `<article class="workspace-source" data-screening-source="${escapeHtml(row.id)}">
    <div class="workspace-source-heading"><div><strong>${escapeHtml(row.label)}</strong><span class="workspace-source-id">${escapeHtml(row.id)}</span></div><div class="status-stack">${screeningStatus(row)}</div></div>
    <div class="workspace-source-state"><span class="layer-state layer-state-${escapeHtml(layer.state)}">${escapeHtml(layer.label)}</span><span>${escapeHtml(layer.detail)}</span></div>
    ${metric ? `<dl class="workspace-metrics">${metric}</dl>` : ""}
    <details><summary>Source provenance and details</summary><div class="workspace-detail-copy"><p>${escapeHtml(row.result ? (row.result.observation_status === "data_observed" ? "Observed in the recorded AOI result." : row.result.observation_status) : row.source.status_only_reason || "No source-specific screening result was recorded.")}</p>${screeningProvenance(row)}<p class="muted">${escapeHtml(row.id === "ssurgo" ? "Hydric-soil information; not a wetlands inventory or regulatory determination." : row.id === "fema_nfhl" ? "Unmapped or unavailable FEMA areas remain unknown, not hazard-free." : row.id === "padus" ? "No PAD-US geometry is rendered because the source remains conditional/quarantined." : "No cross-source score or suitability conclusion is calculated.")}</p></div></details>
  </article>`;
};

const workspaceLayerControl = (rows) => `<aside class="workspace-layer-control" aria-label="Map layer availability">
  <div class="workspace-layer-heading"><div><p class="eyebrow">Map layers</p><strong>Recorded spatial content</strong></div><span class="layer-count">1 rendered</span></div>
  <label class="workspace-layer workspace-layer-active"><input type="checkbox" checked disabled><span class="layer-swatch aoi-swatch"></span><span><strong>AOI boundary</strong><small>Rendered from the recorded WGS84 geometry</small></span></label>
  ${rows.map((row) => { const layer = layerState(row); return `<div class="workspace-layer workspace-layer-${escapeHtml(layer.state)}"><span class="layer-swatch source-swatch"></span><span><strong>${escapeHtml(row.label)}</strong><small>${escapeHtml(layer.label)} · ${escapeHtml(layer.detail)}</small></span></div>`; }).join("")}
  <p class="workspace-layer-note">Source overlays appear only when browser-ready geometry or raster previews are present in the report. This demonstration contains AOI geometry and source metrics, not source overlays.</p>
</aside>`;

const workspaceTabs = (activeTab) => {
  const tabs = [["results", "Screening results"], ["reports", "Reports / exports"], ["sources", "Data sources"], ["activity", "Activity / provenance"]];
  return `<nav class="workspace-tabs" aria-label="Screening workspace sections">${tabs.map(([id, label]) => `<a class="workspace-tab ${activeTab === id ? "workspace-tab-active" : ""}" aria-current="${activeTab === id ? "page" : "false"}" href="?tab=${id}">${label}</a>`).join("")}</nav>`;
};

const workspaceResultsPanel = (rows) => `<div class="workspace-panel-content"><div class="workspace-panel-heading"><div><p class="eyebrow">Source summary</p><h2>Independent findings</h2></div><span class="muted">No composite environmental score</span></div><div class="workspace-source-list">${rows.map(workspaceSourceRow).join("")}</div><p class="workspace-guardrail">Unknown, unavailable, incomplete, nodata, pending, and quarantined states are not “no constraint observed.”</p></div>`;

const workspaceReportsPanel = () => `<div class="workspace-panel-content"><div class="workspace-panel-heading"><div><p class="eyebrow">Recorded outputs</p><h2>Reports and exports</h2></div></div><p class="muted">These controls expose only artifacts present in the recorded demonstration. No live processing or provider access is performed.</p><div class="workspace-action-list"><a class="workspace-action workspace-action-primary" href="demo/report.json" download>Download JSON report</a><span class="workspace-action workspace-action-disabled" aria-disabled="true">CSV not included in fixture</span><span class="workspace-action workspace-action-disabled" aria-disabled="true">GeoJSON not included in fixture</span><a class="workspace-action" href="demo/report.json" target="_blank" rel="noreferrer">View underlying JSON</a></div></div>`;

const workspaceSourcesPanel = (rows) => `<div class="workspace-panel-content"><div class="workspace-panel-heading"><div><p class="eyebrow">Source catalog</p><h2>What is available to this report</h2></div></div><div class="workspace-source-catalog">${rows.map((row) => { const layer = layerState(row); const source = row.source; const candidate = source.candidates?.at(-1) || {}; const version = source.active_aoi_versions?.at(-1) || source.source_versions?.at(-1) || {}; return `<div class="workspace-catalog-row"><div><strong>${escapeHtml(row.label)}</strong><small>${escapeHtml(source.provider_release || candidate.provider_release || version.provider_release || "Release not recorded")}</small></div><div>${screeningStatus(row)}<small>${escapeHtml(layer.label)}</small></div><p>${escapeHtml(layer.detail)}</p></div>`; }).join("")}</div><p class="workspace-guardrail">PAD-US and FEMA are shown as source states only. Hydric-soil information is soil information, not a wetlands inventory or regulatory determination.</p></div>`;

const workspaceActivityPanel = (report, rows, parent) => { const snapshots = rows.flatMap((row) => row.source.screening?.flatMap((job) => job.source_snapshots || []) || []); return `<div class="workspace-panel-content"><div class="workspace-panel-heading"><div><p class="eyebrow">Technical provenance</p><h2>Recorded activity</h2></div><a class="workspace-action" href="?view=operations">Open operations console</a></div><dl class="workspace-activity"><div><dt>Parent ingestion run</dt><dd><code>${escapeHtml(parent.parent_run_id || "—")}</code> · ${escapeHtml(parent.status || "recorded")}</dd></div><div><dt>Screening jobs</dt><dd>${formatNumber(report.screening_jobs?.length || 0, 0)} recorded</dd></div><div><dt>Source snapshots</dt><dd>${formatNumber(snapshots.length, 0)} immutable references<br>${snapshots.map((snapshot) => `<code>${escapeHtml(snapshot.snapshot_id)}</code>`).join(" · ") || "—"}</dd></div><div><dt>Geometry hash</dt><dd><code class="hash">${escapeHtml(report.aoi?.geometry_sha256)}</code></dd></div></dl><p class="workspace-guardrail">The operations console contains acquisition attempts, retries, candidates, promotion decisions, checksums, and detailed lifecycle evidence.</p></div>`; };

export const renderScreeningReport = (report = {}, requestedTab = "results") => {
  const project = report.project || {};
  const aoi = report.aoi || {};
  const area = aoi.area || {};
  const rows = sourceRows(report);
  const parent = report.parent_ingestion_runs?.[0] || {};
  const screenedRows = rows.filter((row) => row.result);
  const timestamp = report.report_timestamp || parent.started_at || "Recorded fixture";
  const activeTab = ["results", "reports", "sources", "activity"].includes(requestedTab) ? requestedTab : "results";
  const tabPanel = activeTab === "reports" ? workspaceReportsPanel() : activeTab === "sources" ? workspaceSourcesPanel(rows) : activeTab === "activity" ? workspaceActivityPanel(report, rows, parent) : workspaceResultsPanel(rows);
  return `<div class="workspace-shell">
    <header class="workspace-header"><div class="workspace-brand"><span class="workspace-mark">ES</span><div><p class="eyebrow">Environmental Screening</p><strong>Preliminary workspace</strong></div></div><div class="workspace-header-meta"><span class="demo-badge">Recorded demonstration</span><a class="workspace-tech-link" href="?view=operations">Technical operations view</a></div></header>
    <section class="workspace-project-header"><div><a class="workspace-backlink" href="?tab=results">Projects / recorded screening</a><div class="workspace-title-line"><h1>${escapeHtml(project.name || "Recorded environmental screening")}</h1><span class="badge badge-partial">Partial result</span></div><p class="workspace-meta-line">AOI ${escapeHtml(aoi.aoi_id)} · revision ${escapeHtml(aoi.revision)} · ${formatNumber(area.value_sqkm, 5)} km² · ${escapeHtml(aoi.policy || "generic")} policy · recorded ${escapeHtml(timestamp)}</p></div><div class="workspace-header-actions"><a class="workspace-action" href="?tab=results">Load recorded screening</a><a class="workspace-action workspace-action-primary" href="demo/report.json" download>Export JSON</a></div></section>
    <div class="workspace-notice"><strong>Preliminary screening only.</strong> No composite score, regulatory determination, safety conclusion, or suitability recommendation is produced.</div>
    ${workspaceTabs(activeTab)}
    <main class="workspace-main"><section class="workspace-map-stage"><div class="workspace-map-toolbar"><div><p class="eyebrow">Map workspace</p><strong>Recorded area of interest</strong><span>WGS84 · ${escapeHtml(aoi.policy || "generic")} · geometry-only preview</span></div><span class="workspace-map-status">${formatNumber(screenedRows.length, 0)} of ${formatNumber(rows.length, 0)} sources observed</span></div><div class="workspace-map-wrap">${renderAoiMap(aoi)}${workspaceLayerControl(rows)}</div><div class="map-caption"><span>Recorded AOI geometry boundary only; source overlays are not present in this fixture.</span><code>${escapeHtml(aoi.geometry_sha256)}</code></div></section><aside class="workspace-sidebar"><div class="workspace-sidebar-head"><div><p class="eyebrow">${activeTab === "results" ? "Screening summary" : "Workspace view"}</p><h2>${escapeHtml(activeTab === "results" ? "Source findings" : activeTab === "reports" ? "Reports / exports" : activeTab === "sources" ? "Data sources" : "Activity / provenance")}</h2></div><span class="workspace-sidebar-count">${formatNumber(rows.length, 0)} sources</span></div>${tabPanel}</aside></main>
    <footer class="workspace-footer"><span>Read-only recorded projection · independent source metrics</span><a href="?view=operations">Open technical operations report</a></footer>
  </div>`;
};

export const renderReport = (report = {}) => {
  const project = report.project || {};
  const aoi = report.aoi || {};
  const area = aoi.area || {};
  const rows = sourceRows(report);
  const parent = report.parent_ingestion_runs?.[0] || {};
  const plan = parent.plan_record?.plan || parent.summary || {};
  const overall = parent.status || report.job_outcome?.overall_status || "recorded";
  const timeline = ["planned", "acquired", "validated", "promoted", "screened"].map((stage, index) => {
    const summary = summarizeStage(rows, stage);
    const complete = summary.applicable > 0 && summary.observed === summary.applicable;
    const partial = summary.observed > 0 && !complete;
    const state = summary.applicable === 0 ? "not_applicable" : complete ? "complete" : partial ? "partial" : "pending";
    const detail = summary.applicable === 0 ? "No applicable source evidence" : `${summary.observed} of ${summary.applicable} applicable source${summary.applicable === 1 ? "" : "s"}`;
    const visualState = state === "complete" ? "done" : state === "not_applicable" ? "na" : state;
    return `<div class="timeline-step timeline-${visualState}"><span>${index + 1}</span><strong>${escapeHtml(stage[0].toUpperCase() + stage.slice(1))}</strong><small>${escapeHtml(state === "partial" ? `Partial · ${detail}` : state === "complete" ? detail : state === "not_applicable" ? detail : `Pending · ${detail}`)}</small></div>`;
  }).join("");
  return `<div class="console-header">
    <div><p class="eyebrow">Environmental Screening &amp; GeoData Operations Platform</p><h1>Operations console</h1><p class="lede">A read-only projection of one deterministic AOI lifecycle.</p></div>
    <nav aria-label="Application views"><span class="demo-badge">Recorded demonstration</span><a class="secondary-link" href="./">Screening report</a></nav>
  </div>
  <div class="notice"><strong>Recorded demonstration result.</strong> This console reads a checked-in <code>report-aoi-run</code> JSON fixture from the retained Washington, DC smoke scenario. It does not contact providers, run jobs, or imply regulatory, safety, or suitability conclusions.</div>
  <section class="panel identity"><div class="section-heading"><div><p class="eyebrow">Run identity</p><h2>Project and AOI</h2></div><span class="status-text">Parent run: ${escapeHtml(overall)}</span></div>
    <div class="identity-grid">
      <div><span class="label">Project</span><strong>${escapeHtml(project.name)}</strong><code>${escapeHtml(project.project_id)}</code></div>
      <div><span class="label">AOI revision</span><strong>${escapeHtml(aoi.aoi_id)} / rev ${escapeHtml(aoi.revision)}</strong><code>policy: ${escapeHtml(aoi.policy)}</code></div>
      <div><span class="label">Area</span><strong>${formatNumber(area.value_sqkm, 5)} km²</strong><span>${escapeHtml(area.crs || "—")}</span></div>
      <div class="wide"><span class="label">Immutable geometry hash</span><code class="hash">${escapeHtml(aoi.geometry_sha256)}</code></div>
    </div>
  </section>
  <section class="panel lifecycle-panel"><div class="section-heading"><div><p class="eyebrow">Control-plane evidence</p><h2>Ingestion lifecycle</h2></div><a class="button" href="demo/report.json" download>Download JSON report</a></div>
    <div class="run-summary"><div><span class="label">Deterministic plan</span><strong>${escapeHtml(parent.plan_id || plan.plan_id || "—")}</strong><span>${escapeHtml(parent.plan_record?.observed_size_bytes ?? parent.summary?.plan_size_bytes ?? "—")} bytes · ${escapeHtml(parent.plan_record?.observed_sha256 || parent.summary?.plan_sha256 || "checksum unavailable")}</span></div><div><span class="label">Sources selected</span><strong>${rows.length}</strong><span>${valueList(rows.map((row) => row.label))}</span></div><div><span class="label">Parent run</span><strong>${escapeHtml(parent.parent_run_id || "—")}</strong><span>${escapeHtml(parent.started_at || "Recorded fixture")}</span></div></div>
    <div class="timeline">${timeline}</div>
  </section>
  <section class="panel"><div class="section-heading"><div><p class="eyebrow">Independent source state</p><h2>Source lifecycle matrix</h2></div><p class="muted">Each source is evaluated independently; there is no composite score.</p></div>
    <div class="table-wrap"><table><thead><tr><th>Source</th><th>Lifecycle stop</th><th>Coverage / observation</th><th>Jobs / snapshots</th><th>Warnings / disposition</th></tr></thead><tbody>${rows.map((row) => { const l=row.lifecycle; const result=row.result||{}; const warningState = l.failed?.length ? "failed" : l.blocked?.length ? "blocked" : l.unavailable?.length ? "unavailable" : l.rejected?.length ? "rejected" : l.incomplete?.length ? "incomplete" : l.quarantined?.length ? "quarantined" : l.unknown?.length ? "unknown" : null; return `<tr><th>${escapeHtml(row.label)}<small>${escapeHtml(row.id)}</small></th><td>${statusBadge(row.state)}<small>${escapeHtml(l.stopped_at || row.state)}</small></td><td><span>${escapeHtml(result.coverage_status || l.coverage_statuses?.at(-1) || "unknown")}</span><small>${escapeHtml(result.observation_status || l.observation_statuses?.at(-1) || "unknown")}</small></td><td><span>${l.screened?.job_ids?.length || 0} screened</span><small>${l.screened?.snapshot_ids?.length || 0} immutable snapshots</small></td><td>${warningState ? statusBadge(warningState) : "—"}${warningState === "rejected" || row.source.promotion_decisions?.some((decision) => decision.decision === "rejected") ? ` ${statusBadge("rejected")}` : ""}</td></tr>`; }).join("")}</tbody></table></div>
  </section>
  <section class="source-grid">${rows.map(sourceDetail).join("")}</section>
  <section class="panel warnings"><div class="section-heading"><div><p class="eyebrow">Interpretation guardrails</p><h2>Warnings and limitations</h2></div></div><ul>${(report.warnings || []).map((warning) => `<li>${escapeHtml(warning)}</li>`).join("") || "<li>No additional warnings recorded.</li>"}</ul><p class="muted">Unknown, unavailable, incomplete, nodata, pending, and quarantined states are not “no constraint observed.”</p></section>
  <footer><span>Read-only local projection · no provider access</span><a href="demo/report.json">View underlying report JSON</a></footer>`;
};

export { formatBytes, lifecycleState, candidateDispositionState };
