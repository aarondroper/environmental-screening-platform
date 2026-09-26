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

export const renderScreeningReport = (report = {}) => {
  const project = report.project || {};
  const aoi = report.aoi || {};
  const area = aoi.area || {};
  const rows = sourceRows(report);
  const parent = report.parent_ingestion_runs?.[0] || {};
  const screenedRows = rows.filter((row) => row.result);
  const timestamp = report.report_timestamp || parent.started_at || "Recorded fixture";
  return `<div class="screening-app">
    <header class="screening-header"><div><p class="eyebrow">Environmental Screening &amp; GeoData Operations Platform</p><h1>Environmental screening report</h1><p class="lede">A preliminary source-by-source review for one recorded area of interest.</p></div><nav aria-label="Application views"><span class="demo-badge">Recorded demonstration</span><a class="secondary-link" href="?view=operations">Technical operations view</a></nav></header>
    <div class="screening-notice"><strong>Preliminary screening only.</strong> This recorded Washington, DC result is read-only. It does not provide a composite score, regulatory determination, safety conclusion, or suitability recommendation.</div>
    <main>
      <section class="screening-hero">
        <div class="map-panel"><div class="section-heading"><div><p class="eyebrow">Study area</p><h2>Area of interest</h2></div><span class="map-crs">WGS84 · ${escapeHtml(aoi.policy || "generic")}</span></div>${renderAoiMap(aoi)}<div class="map-caption"><span>Recorded AOI geometry · source geometries not included</span><code>${escapeHtml(aoi.geometry_sha256)}</code></div></div>
        <aside class="screening-summary"><p class="eyebrow">Report status</p><div class="report-status"><span class="badge badge-partial">Partial recorded result</span><span>${formatNumber(screenedRows.length, 0)} of ${formatNumber(rows.length, 0)} selected source pathways have screening results</span></div><dl class="summary-details"><div><dt>Project</dt><dd>${escapeHtml(project.name)}</dd><dd><code>${escapeHtml(project.project_id)}</code></dd></div><div><dt>AOI revision</dt><dd>${escapeHtml(aoi.aoi_id)} · revision ${escapeHtml(aoi.revision)}</dd></div><div><dt>Area</dt><dd>${formatNumber(area.value_sqkm, 5)} km² · ${escapeHtml(area.crs || "—")}</dd></div><div><dt>Recorded at</dt><dd>${escapeHtml(timestamp)}</dd></div></dl><div class="summary-warning"><strong>Interpretation guardrail</strong><p>Unknown, unavailable, incomplete, nodata, pending, and quarantined states are not “no constraint observed.”</p></div></aside>
      </section>
      <section class="results-section"><div class="section-heading"><div><p class="eyebrow">Independent source results</p><h2>What the recorded sources show</h2></div><span class="muted">No composite environmental score</span></div><div class="screening-grid">${rows.map(screeningSourceCard).join("")}</div></section>
      <section class="screening-footer-panel"><div><p class="eyebrow">Recorded report outputs</p><h2>Review and export</h2><p class="muted">Use the details disclosures on each source for exact version and checksum lineage. Provider access and live processing are not required for this demonstration.</p></div><div class="export-actions"><a class="button primary-button" href="demo/report.json" download>Download JSON report</a><span class="button disabled-button" aria-disabled="true">CSV not included in fixture</span><span class="button disabled-button" aria-disabled="true">GeoJSON not included in fixture</span></div></section>
    </main>
    <footer><span>Recorded screening projection · source metrics remain independent</span><a href="?view=operations">Open technical operations report</a></footer>
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
