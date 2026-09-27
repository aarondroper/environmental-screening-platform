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
  not_evaluated: "Not evaluated",
  unknown: "Unknown",
  blocked: "Blocked",
  quarantined: "Quarantined",
  failed: "Failed",
  not_started: "Not started",
  queued: "Queued",
  running: "Running",
  succeeded: "Screened",
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
  not_evaluated: "This source was not evaluated for the currently loaded AOI.",
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

export const humanizeNlcdClassName = (value) => String(value || "Unknown class")
  .replaceAll("_", " ")
  .replace(/\b\w/g, (character) => character.toUpperCase());

const nlcdClassSummary = (metrics) => {
  const classes = Object.entries(metrics.classes || {}).map(([code, item]) => ({ ...item, class_value: item.class_value || code })).sort((left, right) => (
    Number(right.pixel_count || 0) - Number(left.pixel_count || 0)
  ));
  const validPixels = Number(metrics.valid_pixel_count || 0);
  const resolution = metrics.raster?.resolution || [];
  const cellArea = Number(resolution[0]) * Number(resolution[1]);
  if (!classes.length) return `<p class="muted">No observed NLCD classes in valid pixels.</p>`;
  const rows = classes.map((item) => {
    const pixels = Number(item.pixel_count || 0);
    const percentage = item.percentage_of_valid_pixels ?? (validPixels ? (pixels / validPixels) * 100 : null);
    const area = item.estimated_area_sqm ?? (Number.isFinite(cellArea) ? pixels * cellArea : null);
    return `<li class="nlcd-class-row"><span class="nlcd-class-name"><strong>${escapeHtml(humanizeNlcdClassName(item.class_name || item.class_label))}</strong><small>NLCD ${escapeHtml(item.class_value || "")}</small></span><span class="nlcd-class-bar" aria-hidden="true"><i style="width:${Math.min(100, Math.max(0, Number(percentage || 0)))}%"></i></span><span class="nlcd-class-value">${escapeHtml(formatNumber(area))} m² · ${escapeHtml(formatNumber(percentage))}%</span></li>`;
  }).join("");
  return `<div class="nlcd-observed-summary"><strong>Observed land cover</strong><ul class="nlcd-class-summary">${rows}</ul><small>Annual NLCD observations only; these classes are not suitability or regulatory conclusions.</small></div>`;
};

const lifecycleState = (source = {}) => {
  const lifecycle = source.lifecycle || {};
  for (const state of ["not_evaluated", "blocked", "unavailable", "incomplete", "failed", "unknown", "quarantined"]) {
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
      notEvaluated: Boolean(report.aoi_context?.stale_recorded_results),
    };
  });
};

const statusBadge = (state) => `<span class="badge badge-${escapeHtml(state)}" title="${escapeHtml(STATUS_HELP[state] || "Source lifecycle state")}">${escapeHtml(STATUS_LABELS[state] || state)}</span>`;

const valueList = (items) => items.length ? items.map((item) => `<code>${escapeHtml(item)}</code>`).join(" ") : "—";

const sourceMetrics = (row) => {
  if (row.notEvaluated) return `<div class="metric"><dt>Evaluation</dt><dd>Not evaluated for this AOI</dd></div>`;
  const metrics = row.result?.metrics || row.source.candidates?.at(-1)?.validation?.metrics || {};
  const coverage = metrics.coverage || metrics;
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
  if (row.notEvaluated) return statusBadge("not_evaluated");
  if (row.id === "padus") return `${statusBadge("conditional")} ${statusBadge("unknown")}`;
  if (row.id === "fema_nfhl") return `${statusBadge("blocked")} ${statusBadge("unavailable")}`;
  if (row.result?.observation_status === "data_observed") return statusBadge("observed");
  return statusBadge(row.state);
};

const screeningMetric = (label, value) => `<div class="screening-metric"><dt>${escapeHtml(label)}</dt><dd>${escapeHtml(value)}</dd></div>`;

const screeningMetrics = (row) => {
  if (row.notEvaluated) return [screeningMetric("Evaluation", "Not evaluated for this AOI")];
  const metrics = row.result?.metrics || {};
  const coverage = metrics.coverage || metrics;
  if (row.id === "annual_nlcd" && row.result) {
    return [
      screeningMetric("AOI coverage", `${formatNumber(coverage.covered_aoi_percentage)}% covered`),
      screeningMetric("Valid pixels", formatNumber(metrics.valid_pixel_count, 0)),
      screeningMetric("Nodata pixels", formatNumber(metrics.nodata_pixel_count, 0)),
      nlcdClassSummary(metrics),
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

const renderAoiMap = (aoi, previews = {}) => {
  const identifyMessage = previews.annual_nlcd?.status === "available"
    ? "Click the map to inspect Annual NLCD."
    : "NLCD identify unavailable: no AOI-specific preview is attached.";
  return `<div class="aoi-map" data-aoi-map><div class="map-state map-state-loading" data-map-status role="status">Loading public basemap…</div><div class="map-identify-panel map-identify map-identify-idle" data-nlcd-identify aria-live="polite">${identifyMessage}</div></div>`;
};

const layerState = (row, previews = {}) => {
  if (row.notEvaluated) return { state: "not_evaluated", label: "Not evaluated", detail: "No recorded source layer is tied to this AOI." };
  if (row.id === "annual_nlcd") {
    const preview = previews.annual_nlcd;
    if (preview?.status === "available") {
      return { state: "observed", label: "NLCD 2025 preview", detail: "Categorical display derivative; source metrics remain authoritative." };
    }
    if (preview?.status && preview.status !== "available") {
      return { state: "unavailable", label: "Preview unavailable", detail: "The recorded NLCD raster is available, but no browser preview can be used." };
    }
    return { state: row.result ? "observed" : "unknown", label: "Metrics only", detail: "Recorded raster metrics; no browser-ready raster overlay is included." };
  }
  if (row.id === "3dep") {
    const preview = previews["3dep"];
    if (preview?.status === "available") {
      return { state: "observed", label: "3DEP terrain preview", detail: "Relative hillshade display derivative; source metrics remain authoritative and no elevation units or datum are converted." };
    }
    if (preview?.status && preview.status !== "available") {
      return { state: "unavailable", label: "Preview unavailable", detail: "The recorded 3DEP raster is available, but no browser preview can be used." };
    }
    return { state: row.result ? "observed" : "unknown", label: "Metrics only", detail: "Recorded raster metrics; no browser-ready raster overlay is included." };
  }
  if (row.id === "ssurgo") return { state: "incomplete", label: "Incomplete", detail: "Fixture coverage is incomplete; no soil layer is rendered." };
  if (row.id === "padus") return { state: "conditional", label: "Conditional / unknown", detail: "Regional coverage and repair statistics remain unverified." };
  if (row.id === "fema_nfhl") return { state: "unavailable", label: "Unavailable / blocked", detail: "Provider access is blocked; no flood layer was screened." };
  return { state: row.state, label: STATUS_LABELS[row.state] || row.state, detail: STATUS_HELP[row.state] || "No renderable layer was recorded." };
};

const workspaceMetricSummary = (row) => {
  if (row.notEvaluated) return "Not evaluated for this AOI";
  const metrics = row.result?.metrics || {};
  const coverage = metrics.coverage || metrics;
  if (row.id === "annual_nlcd" && row.result) return `${formatNumber(coverage.covered_aoi_percentage)}% AOI · ${formatNumber(metrics.valid_pixel_count, 0)} valid pixels`;
  if (row.id === "3dep" && row.result) return `${formatNumber(coverage.covered_aoi_percentage)}% AOI · mean ${formatNumber(metrics.mean_elevation)} ${metrics.elevation_units || "units"}`;
  if (row.id === "ssurgo") return "Coverage incomplete · rejected candidate";
  if (row.id === "padus") return "No screening result · coverage unknown";
  if (row.id === "fema_nfhl") return "No screening result · provider blocked";
  return "No source-specific metric recorded";
};

const workspaceSourceRow = (row, previews = {}, open = false) => {
  const layer = layerState(row, previews);
  return `<details class="workspace-source" data-screening-source="${escapeHtml(row.id)}"${open ? " open" : ""}>
    <summary class="workspace-source-summary"><span class="workspace-source-name"><strong>${escapeHtml(row.label)}</strong><small>${escapeHtml(row.id)}</small></span><span class="workspace-source-teaser">${escapeHtml(workspaceMetricSummary(row))}</span><span class="status-stack">${screeningStatus(row)}</span></summary>
    <div class="workspace-source-detail"><div class="workspace-source-state"><span class="layer-state layer-state-${escapeHtml(layer.state)}">${escapeHtml(layer.label)}</span><span>${escapeHtml(layer.detail)}</span></div><dl class="workspace-metrics">${screeningMetrics(row).join("")}</dl><p>${escapeHtml(row.result ? (row.result.observation_status === "data_observed" ? "Observed in the recorded AOI result." : row.result.observation_status) : row.source.status_only_reason || "No source-specific screening result was recorded.")}</p><a class="workspace-secondary-link" href="?tab=sources">View source details and provenance</a><p class="muted">${escapeHtml(row.id === "ssurgo" ? "Hydric-soil information; not a wetlands inventory or regulatory determination." : row.id === "fema_nfhl" ? "Unmapped or unavailable FEMA areas remain unknown, not hazard-free." : row.id === "padus" ? "No PAD-US geometry is rendered because the source remains conditional/quarantined." : "No cross-source score or suitability conclusion is calculated.")}</p></div>
  </details>`;
};

const workspaceLayerControl = (rows, previews = {}) => {
  const nlcdPreview = previews.annual_nlcd;
  const terrainPreview = previews["3dep"];
  const nlcdAvailable = nlcdPreview?.status === "available";
  const terrainAvailable = terrainPreview?.status === "available";
  const visibleCount = 1 + [nlcdAvailable && nlcdPreview.default_visible !== false, terrainAvailable && terrainPreview.default_visible === true].filter(Boolean).length;
  const nlcdLegend = nlcdAvailable && nlcdPreview.legend?.length ? `<div class="nlcd-legend" aria-label="Annual NLCD 2025 observed classes"><strong>NLCD observed classes</strong>${nlcdPreview.legend.map((item) => `<span><i style="background:${escapeHtml(item.color)}"></i><b>${escapeHtml(item.value)}</b> ${escapeHtml(humanizeNlcdClassName(item.label))}</span>`).join("")}</div>` : "";
  const terrainLegend = terrainAvailable && terrainPreview.legend?.length ? `<div class="terrain-legend" aria-label="3DEP terrain preview explanation"><strong>3DEP relative hillshade</strong>${terrainPreview.legend.map((item) => `<span><i style="background:${escapeHtml(item.color)}"></i>${escapeHtml(item.label)}</span>`).join("")}<small>Illumination only; no elevation value, unit, or datum is displayed.</small></div>` : "";
  const nlcdLayer = nlcdAvailable
    ? `<div class="workspace-layer workspace-layer-active"><label class="workspace-layer-toggle"><input type="checkbox" ${nlcdPreview.default_visible !== false ? "checked" : ""} data-nlcd-visibility aria-label="Toggle Annual NLCD 2025 preview"><span class="layer-swatch nlcd-swatch"></span><span><strong>Annual NLCD 2025</strong><small data-nlcd-status>${nlcdPreview.default_visible !== false ? "Display preview · visible" : "Available · click to show"}</small></span></label><span class="layer-opacity"><span>Opacity</span><input id="nlcd-opacity" type="range" min="0.25" max="0.9" step="0.05" value="${escapeHtml(nlcdPreview.opacity_default ?? 0.58)}" data-nlcd-opacity aria-label="Annual NLCD preview opacity"></span><small class="layer-error" data-nlcd-error hidden></small></div>`
    : `<div class="workspace-layer workspace-layer-${escapeHtml(layerState(rows.find((row) => row.id === "annual_nlcd") || { id: "annual_nlcd", result: null }, previews).state)}"><span class="layer-swatch source-swatch"></span><span><strong>Annual NLCD 2025</strong><small>${escapeHtml(nlcdPreview?.status ? "Preview unavailable" : "Metrics only · no preview")}</small></span></div>`;
  const terrainLayer = terrainAvailable
    ? `<div class="workspace-layer workspace-layer-active"><label class="workspace-layer-toggle"><input type="checkbox" ${terrainPreview.default_visible === true ? "checked" : ""} data-3dep-visibility aria-label="Toggle 3DEP terrain preview"><span class="layer-swatch terrain-swatch"></span><span><strong>3DEP terrain</strong><small data-3dep-status>${terrainPreview.default_visible === true ? "Relative hillshade · visible" : "Available · click to show"}</small></span></label><span class="layer-opacity"><span>Opacity</span><input id="3dep-opacity" type="range" min="0.2" max="0.75" step="0.05" value="${escapeHtml(terrainPreview.opacity_default ?? 0.42)}" data-3dep-opacity aria-label="3DEP terrain preview opacity"></span><small class="layer-error" data-3dep-error hidden></small></div>`
    : `<div class="workspace-layer workspace-layer-${escapeHtml(layerState(rows.find((row) => row.id === "3dep") || { id: "3dep", result: null }, previews).state)}"><span class="layer-swatch source-swatch"></span><span><strong>3DEP terrain</strong><small>${escapeHtml(terrainPreview?.status ? "Preview unavailable" : "Metrics only · no preview")}</small></span></div>`;
  return `<details class="workspace-layer-control" aria-label="Map layer availability">
  <summary><span><strong>Layers</strong><small>AOI and screening layers</small></span><span class="layer-count" data-layer-count>${visibleCount} visible</span></summary>
  <div class="workspace-layer-list"><label class="workspace-layer workspace-layer-active"><input type="checkbox" checked data-aoi-visibility aria-label="Toggle AOI boundary"><span class="layer-swatch aoi-swatch"></span><span><strong>AOI boundary</strong><small>Visible on map</small></span></label>
  <section class="workspace-layer-group"><div class="workspace-layer-group-heading"><strong>Screening layers</strong><small>Optional display derivatives</small></div>${nlcdLayer}${terrainLayer}${nlcdLegend}${terrainLegend}</section>
  ${rows.filter((row) => !["annual_nlcd", "3dep"].includes(row.id)).map((row) => { const layer = layerState(row, previews); return `<div class="workspace-layer workspace-layer-${escapeHtml(layer.state)}"><span class="layer-swatch source-swatch"></span><span><strong>${escapeHtml(row.label)}</strong><small>${escapeHtml(layer.label)}</small></span></div>`; }).join("")}</div>
  <details class="workspace-layer-limitations"><summary>Layer limitations</summary><p>The NLCD preview is a categorical display derivative masked to the AOI with nodata and outside-AOI pixels transparent. The 3DEP preview is a relative hillshade display derivative; the retained raster does not declare vertical units or datum, so no elevation value or conversion is shown. SSURGO, PAD-US, and FEMA are not rendered as environmental overlays.</p></details>
</details>`;
};

const workspaceTabs = (activeTab) => {
  const tabs = [["results", "Screening"], ["reports", "Reports"], ["sources", "Data sources"]];
  return `<nav class="workspace-tabs" aria-label="Screening workspace sections">${tabs.map(([id, label]) => `<a class="workspace-tab ${activeTab === id ? "workspace-tab-active" : ""}" aria-current="${activeTab === id ? "page" : "false"}" href="?tab=${id}">${label}</a>`).join("")}</nav>`;
};

const workspaceResultsPanel = (rows, previews = {}) => {
  const primary = rows.find((row) => row.id === "annual_nlcd");
  const secondary = rows.filter((row) => row.id !== "annual_nlcd");
  return `<div class="workspace-panel-content"><div class="workspace-panel-heading"><div><p class="eyebrow">Source summary</p><h2>Annual NLCD findings</h2></div><span class="muted">No composite score</span></div>${primary ? `<div class="workspace-primary-source">${workspaceSourceRow(primary, previews, true)}</div>` : ""}<details class="workspace-secondary-sources"><summary>Other source status <span>${secondary.length}</span></summary><div class="workspace-source-list">${secondary.map((row) => workspaceSourceRow(row, previews)).join("")}</div></details><details class="workspace-info"><summary>Interpretation limits</summary><p>These are source observations only. Unknown, unavailable, incomplete, nodata, pending, and quarantined states are not “no constraint observed.” No regulatory, safety, or suitability conclusion is produced.</p></details></div>`;
};

const workspaceReportsPanel = (report = {}) => {
  const userAoi = report.aoi_context?.origin === "user_provided";
  const screened = report.screening_run?.status === "succeeded" || report.aoi_context?.screened;
  return `<div class="workspace-panel-content"><div class="workspace-panel-heading"><div><p class="eyebrow">Recorded outputs</p><h2>Reports and exports</h2></div></div><p class="muted">${userAoi && !screened ? "This loaded AOI has not been screened. The recorded DC report cannot be exported as a result for this geometry." : userAoi ? "This local result is screened for the exact loaded AOI. Only export artifacts actually returned by the bridge are exposed." : "These controls expose only artifacts present in the recorded demonstration. No live processing or provider access is performed."}</p><div class="workspace-action-list">${userAoi ? `<span class="workspace-action workspace-action-disabled" aria-disabled="true">JSON export unavailable from local bridge</span>` : `<a class="workspace-action workspace-action-primary" href="demo/report.json" download>Download JSON report</a>`}<span class="workspace-action workspace-action-disabled" aria-disabled="true">CSV not included in fixture</span><span class="workspace-action workspace-action-disabled" aria-disabled="true">GeoJSON not included in fixture</span>${userAoi ? "" : `<a class="workspace-action" href="demo/report.json" target="_blank" rel="noreferrer">View underlying JSON</a>`}</div></div>`;
};

const workspaceSourcesPanel = (rows, previews = {}) => `<div class="workspace-panel-content"><div class="workspace-panel-heading"><div><p class="eyebrow">Source catalog</p><h2>Data sources</h2></div><a class="workspace-secondary-link" href="?view=operations">Operations view</a></div><div class="workspace-source-catalog">${rows.map((row) => { const layer = layerState(row, previews); const preview = previews[row.id]; const source = row.source; const candidate = source.candidates?.at(-1) || {}; const version = source.active_aoi_versions?.at(-1) || source.source_versions?.at(-1) || {}; return `<div class="workspace-catalog-row"><div><strong>${escapeHtml(row.label)}</strong><small>${escapeHtml(source.provider_release || candidate.provider_release || version.provider_release || "Release not recorded")}</small></div><div>${screeningStatus(row)}<small>${escapeHtml(layer.label)}</small></div><p>${escapeHtml(layer.detail)}</p>${preview?.status === "available" ? `<p class="workspace-preview-provenance"><strong>Display derivative</strong> · ${escapeHtml(preview.representation || "browser preview")} · source version <code>${escapeHtml(preview.source_version_id)}</code> · <a href="${escapeHtml(preview.metadata_url)}" target="_blank" rel="noreferrer">metadata</a></p>` : ""}<details><summary>Version and provenance</summary>${screeningProvenance(row)}</details></div>`; }).join("")}</div><p class="workspace-guardrail">PAD-US and FEMA are shown as source states only. Hydric-soil information is soil information, not a wetlands inventory or regulatory determination.</p></div>`;

export const renderScreeningReport = (report = {}, requestedTab = "results") => {
  const project = report.project || {};
  const aoi = report.aoi || {};
  const area = aoi.area || {};
  const rows = sourceRows(report);
  const previews = report.browser_previews || {};
  const screenedRows = rows.filter((row) => row.result);
  const activeTab = ["results", "reports", "sources"].includes(requestedTab) ? requestedTab : "results";
  const userAoi = report.aoi_context?.origin === "user_provided";
  const bounds = report.aoi?.spatial_validation?.bounds || report.aoi_context?.bounds;
  const boundsText = Array.isArray(bounds) ? bounds.map((value) => Number(value).toFixed(6)).join(", ") : "Not recorded";
  const aoiDetails = `<details class="workspace-aoi-details"><summary>AOI details</summary><dl><div><dt>Input</dt><dd>${escapeHtml(userAoi ? "User-provided GeoJSON" : "Recorded demonstration")}</dd></div><div><dt>Bounds</dt><dd><code>${escapeHtml(boundsText)}</code></dd></div><div><dt>Geometry hash</dt><dd><code class="hash">${escapeHtml(aoi.geometry_sha256)}</code></dd></div></dl></details>`;
  const loadAoiControl = `<details class="workspace-aoi-loader"><summary class="workspace-action workspace-action-primary">Load AOI</summary><div class="workspace-aoi-form"><p><strong>Load a GeoJSON AOI</strong></p><p class="muted">WGS84 Polygon or MultiPolygon only. Loading validates the geometry locally; Run screening sends only this AOI to the local Annual NLCD bridge.</p><label>GeoJSON file<input type="file" accept=".geojson,application/geo+json,application/json" data-aoi-file></label><label>Paste GeoJSON<textarea rows="4" placeholder="{ &quot;type&quot;: &quot;Feature&quot;, … }" data-aoi-paste></textarea></label><div class="workspace-aoi-form-actions"><button type="button" class="workspace-action workspace-action-primary" data-aoi-apply>Load geometry</button>${userAoi ? `<button type="button" class="workspace-action" data-aoi-reset>Use DC demo</button>` : ""}</div><p class="workspace-aoi-error" data-aoi-error role="alert" hidden></p></div></details>`;
  const run = report.screening_run || null;
  const screenedCurrent = run?.status === "succeeded" || report.aoi_context?.screened;
  const running = run && ["queued", "running"].includes(run.status);
  const statusLabel = run ? STATUS_LABELS[run.status] || run.status : userAoi ? "Not evaluated" : "Recorded demo";
  const statusDetail = run ? (run.reason || (run.phase === "completed" ? "Annual NLCD result recorded" : `Annual NLCD ${run.phase || run.status}`)) : userAoi ? "Load an AOI, then run Annual NLCD" : `${formatNumber(screenedRows.length, 0)} of ${formatNumber(rows.length, 0)} recorded sources observed`;
  const runAction = `<button type="button" class="workspace-action workspace-action-primary" data-run-screening ${running ? "disabled" : ""}>${running ? `${escapeHtml(statusLabel)} Annual NLCD…` : "Run screening"}</button>`;
  const exportAction = userAoi ? `<span class="workspace-action workspace-action-disabled" aria-disabled="true">Export unavailable</span>` : `<a class="workspace-action workspace-action-primary" href="demo/report.json" download>Export JSON</a>`;
  const tabPanel = activeTab === "reports" ? workspaceReportsPanel(report) : activeTab === "sources" ? workspaceSourcesPanel(rows, previews) : workspaceResultsPanel(rows, previews);
  return `<div class="workspace-shell">
    <header class="workspace-header"><div class="workspace-header-project"><span class="workspace-mark">ES</span><div><h1>${escapeHtml(userAoi ? "User-provided environmental screening" : project.name || "Recorded environmental screening")}</h1><span>${area.value_sqkm === null || area.value_sqkm === undefined ? "Area not calculated in browser" : `${formatNumber(area.value_sqkm, 5)} km²`} · AOI revision ${escapeHtml(aoi.revision)} · ${escapeHtml(userAoi ? "local AOI session" : "recorded demonstration")}</span></div></div><div class="workspace-header-status"><span class="badge badge-${escapeHtml(run?.status || (userAoi ? "not_evaluated" : "partial"))}">${escapeHtml(statusLabel)}</span><span data-screening-status>${escapeHtml(statusDetail)}</span></div><div class="workspace-header-actions">${runAction}${loadAoiControl}${exportAction}<a class="workspace-tech-link" href="?view=operations">Technical view</a></div></header>
    ${workspaceTabs(activeTab)}
    <main class="workspace-main"><section class="workspace-map-stage"><div class="workspace-map-toolbar"><div><strong>Area of interest</strong><span>WGS84 · ${escapeHtml(aoi.policy || "generic")}</span>${aoiDetails}</div><span class="workspace-map-status">${escapeHtml(userAoi ? (screenedCurrent ? "Loaded AOI · Annual NLCD screened" : "Loaded AOI · source results not evaluated") : "Recorded AOI boundary")}</span></div><div class="workspace-map-wrap">${renderAoiMap(aoi, previews)}${workspaceLayerControl(rows, previews)}</div><div class="map-caption"><span>${escapeHtml(userAoi ? (screenedCurrent ? "Annual NLCD result is bound to this exact AOI revision; other sources remain not evaluated." : "Loaded AOI shown. Existing DC metrics and display previews are not reused.") : "Recorded AOI boundary and optional NLCD/3DEP display previews shown; source metrics remain independent.")}</span></div></section><aside class="workspace-sidebar"><div class="workspace-sidebar-head"><div><p class="eyebrow">${activeTab === "results" ? "Screening summary" : "Workspace view"}</p><h2>${escapeHtml(activeTab === "results" ? "Source findings" : activeTab === "reports" ? "Reports" : "Data sources")}</h2><span class="workspace-preliminary">${userAoi ? (screenedCurrent ? "AOI loaded · Annual NLCD screened" : "AOI loaded · screening not run") : "Preliminary screening · no composite score"}</span></div><span class="workspace-sidebar-count">${formatNumber(rows.length, 0)} sources</span></div>${tabPanel}</aside></main>
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
