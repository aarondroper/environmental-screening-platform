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
  screened: "Screened",
  promoted: "Promoted",
  validated: "Validated",
  acquired: "Acquired",
  incomplete: "Incomplete",
  unavailable: "Unavailable",
  rejected: "Rejected",
  unknown: "Unknown",
  blocked: "Blocked",
  failed: "Failed",
  not_started: "Not started",
};

const STATUS_HELP = {
  screened: "A source-specific screening result was recorded.",
  promoted: "An AOI-scoped source version is active.",
  validated: "A candidate passed source validation but is not active.",
  acquired: "An artifact was acquired but later lifecycle stages are not recorded.",
  incomplete: "The source has incomplete coverage or processing evidence.",
  unavailable: "The source could not be used for this run.",
  rejected: "A candidate or promotion decision was rejected.",
  unknown: "The report does not establish an observation for this source.",
  blocked: "Provider access or a source gate blocked processing.",
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
  for (const state of ["blocked", "rejected", "unavailable", "incomplete", "failed", "unknown"]) {
    if ((lifecycle[state] || []).length) return state;
  }
  for (const stage of ["screened", "promoted", "validated", "acquired"]) {
    if (lifecycle[stage]?.observed) return stage;
  }
  return lifecycle.stopped_at || "not_started";
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
  const error = lifecycle.incomplete?.at(-1)?.reason || lifecycle.failed?.at(-1)?.reason || result.reason;
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
      <div><dt>Promotion</dt><dd>${lifecycle.promoted?.observed ? statusBadge("promoted") : statusBadge(row.state === "incomplete" ? "incomplete" : "unknown")}</dd></div>
      <div><dt>Active version</dt><dd><code>${escapeHtml(version.version_id || lifecycle.promoted?.active_version_ids?.at(-1))}</code></dd></div>
      <div><dt>Checksum</dt><dd><code class="hash">${escapeHtml(candidate.sha256 || version.sha256 || provenance.sha256)}</code></dd></div>
      <div><dt>Artifact path</dt><dd class="path">${escapeHtml(candidate.artifact_path || version.artifact_path)}</dd></div>
      <div><dt>Source snapshot</dt><dd><code>${escapeHtml(provenance.source_snapshot_id || row.source.screening?.at(-1)?.source_snapshots?.[0]?.snapshot_id)}</code></dd></div>
    </dl>
    ${error ? `<div class="callout callout-${escapeHtml(row.state)}"><strong>${escapeHtml(STATUS_LABELS[row.state] || "State")}</strong><p>${escapeHtml(typeof error === "object" ? JSON.stringify(error) : error)}</p></div>` : ""}
    <details><summary>Raw source evidence</summary><pre>${escapeHtml(JSON.stringify({ candidate, version, result, lifecycle }, null, 2))}</pre></details>
  </article>`;
};

export const renderReport = (report = {}) => {
  const project = report.project || {};
  const aoi = report.aoi || {};
  const area = aoi.area || {};
  const rows = sourceRows(report);
  const parent = report.parent_ingestion_runs?.[0] || {};
  const plan = parent.plan_record?.plan || parent.summary || {};
  const overall = parent.status || report.job_outcome?.overall_status || "recorded";
  return `<div class="console-header">
    <div><p class="eyebrow">Environmental Screening &amp; GeoData Operations Platform</p><h1>Operations console</h1><p class="lede">A read-only projection of one deterministic AOI lifecycle.</p></div>
    <span class="demo-badge">Recorded demonstration</span>
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
    <div class="timeline">${["planned", "acquired", "validated", "promoted", "screened"].map((stage, index) => `<div class="timeline-step ${index < 4 ? "timeline-done" : ""}"><span>${index + 1}</span><strong>${escapeHtml(stage[0].toUpperCase() + stage.slice(1))}</strong><small>${stage === "screened" ? `${report.screening_jobs?.length || 0} job(s)` : stage === "planned" ? `${report.parent_ingestion_runs?.length || 0} plan(s)` : "Source-specific evidence"}</small></div>`).join("")}</div>
  </section>
  <section class="panel"><div class="section-heading"><div><p class="eyebrow">Independent source state</p><h2>Source lifecycle matrix</h2></div><p class="muted">Each source is evaluated independently; there is no composite score.</p></div>
    <div class="table-wrap"><table><thead><tr><th>Source</th><th>Lifecycle stop</th><th>Coverage / observation</th><th>Jobs / snapshots</th><th>Warnings</th></tr></thead><tbody>${rows.map((row) => { const l=row.lifecycle; const result=row.result||{}; return `<tr><th>${escapeHtml(row.label)}<small>${escapeHtml(row.id)}</small></th><td>${statusBadge(row.state)}<small>${escapeHtml(l.stopped_at || row.state)}</small></td><td><span>${escapeHtml(result.coverage_status || l.coverage_statuses?.at(-1) || "unknown")}</span><small>${escapeHtml(result.observation_status || l.observation_statuses?.at(-1) || "unknown")}</small></td><td><span>${l.screened?.job_ids?.length || 0} screened</span><small>${l.screened?.snapshot_ids?.length || 0} immutable snapshots</small></td><td>${(l.failed?.length || 0) + (l.incomplete?.length || 0) + (l.unknown?.length || 0) > 0 ? statusBadge(l.failed?.length ? "failed" : "incomplete") : "—"}</td></tr>`; }).join("")}</tbody></table></div>
  </section>
  <section class="source-grid">${rows.map(sourceDetail).join("")}</section>
  <section class="panel warnings"><div class="section-heading"><div><p class="eyebrow">Interpretation guardrails</p><h2>Warnings and limitations</h2></div></div><ul>${(report.warnings || []).map((warning) => `<li>${escapeHtml(warning)}</li>`).join("") || "<li>No additional warnings recorded.</li>"}</ul><p class="muted">Unknown, unavailable, incomplete, nodata, pending, and quarantined states are not “no constraint observed.”</p></section>
  <footer><span>Read-only local projection · no provider access</span><a href="demo/report.json">View underlying report JSON</a></footer>`;
};

export { formatBytes, lifecycleState };
