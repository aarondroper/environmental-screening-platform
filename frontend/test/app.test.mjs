import test from "node:test";
import assert from "node:assert/strict";
import { webcrypto } from "node:crypto";
import { readFile } from "node:fs/promises";
import { sourceRows, renderReport, renderScreeningReport, lifecycleState, candidateDispositionState, formatBytes } from "../src/app.mjs";
import { createAoiContext, rebindReportToAoi } from "../src/aoi-input.mjs";

if (!globalThis.crypto) globalThis.crypto = webcrypto;

const report = JSON.parse(await readFile(new URL("../public/demo/report.json", import.meta.url), "utf8"));

test("loads the recorded report and renders AOI and source lifecycle evidence", () => {
  const html = renderReport(report);
  assert.match(html, /Recorded demonstration/);
  assert.match(html, new RegExp(report.aoi.geometry_sha256));
  assert.match(html, /Annual NLCD 2025/);
  assert.match(html, /USGS 3DEP/);
  assert.match(html, /NRCS SSURGO/);
  assert.match(html, /FEMA NFHL/);
  assert.match(html, /PAD-US/);
  assert.match(html, /Availability<\/dt><dd>.*Unavailable/);
  assert.match(html, /Availability<\/dt><dd>.*Unknown/);
  assert.match(html, /provider access blocked/);
  assert.match(html, /conditionally validated\/quarantined/);
  assert.match(html, /Download JSON report/);
  assert.equal(sourceRows(report).length, 5);
});

test("renders explicit incomplete and unknown states instead of absence", () => {
  const modified = {
    selected_sources: ["fema_nfhl", "padus"],
    sources: {
      fema_nfhl: { source_id: "fema_nfhl", lifecycle: { blocked: [{ reason: "provider unavailable" }], stopped_at: "blocked" } },
      padus: { source_id: "padus", lifecycle: { unknown: [{ reason: "coverage not verified" }], stopped_at: "unknown" } },
    },
    warnings: ["Unknown data is not no constraint observed."],
  };
  const html = renderReport(modified);
  assert.match(html, /Blocked/);
  assert.match(html, /Unknown/);
  assert.match(html, /Unknown data is not no constraint observed/);
  assert.equal(lifecycleState(modified.sources.fema_nfhl), "blocked");
  assert.equal(lifecycleState(modified.sources.padus), "unknown");
});

test("renders unavailable and unknown as explicit status-only states", () => {
  const modified = {
    selected_sources: ["unavailable_source", "unknown_source"],
    sources: {
      unavailable_source: { lifecycle: { unavailable: [{ reason: "artifact is not available" }], stopped_at: "unavailable" } },
      unknown_source: { lifecycle: { unknown: [{ reason: "coverage was not established" }], stopped_at: "unknown" } },
    },
  };
  const html = renderReport(modified);
  assert.match(html, /Unavailable/);
  assert.match(html, /Unknown/);
  assert.match(html, /artifact is not available/);
  assert.match(html, /coverage was not established/);
});

test("keeps SSURGO lifecycle incomplete separate from rejected disposition", () => {
  const row = sourceRows(report).find((source) => source.id === "ssurgo");
  assert.equal(row.state, "incomplete");
  assert.equal(candidateDispositionState(row), "rejected");
  const html = renderReport(report);
  const card = html.slice(html.indexOf('data-source="ssurgo"'), html.indexOf('data-source="padus"'));
  assert.match(card, /Lifecycle<\/dt><dd>.*Incomplete/);
  assert.match(card, /Candidate disposition<\/dt><dd>.*Rejected/);
  assert.match(card, /Regional canonical coverage is incomplete/);
});

test("aggregates the global promotion stage across applicable sources", () => {
  const html = renderReport(report);
  assert.match(html, /Promoted<\/strong><small>Partial · 2 of 3 applicable sources/);
  assert.doesNotMatch(html, /Promotion<\/strong><small>2 of 2/);
});

test("handles missing optional report fields without inventing results", () => {
  const html = renderReport({ project: {}, aoi: {}, selected_sources: ["ssurgo"], sources: { ssurgo: {} }, warnings: [] });
  assert.match(html, /No source-specific screening metrics recorded/);
  assert.match(html, /No lifecycle record was found/);
  assert.match(html, /Unknown/);
});

test("formats artifact sizes without changing recorded values", () => {
  assert.equal(formatBytes(863154), "842.9 KB");
  assert.equal(formatBytes(null), "—");
});

test("renders the environmental screening workspace as the primary map-centric experience", () => {
  const html = renderScreeningReport(report);
  assert.match(html, /workspace-shell/);
  assert.match(html, /workspace-header-project/);
  assert.match(html, /Screening/);
  assert.match(html, /Reports/);
  assert.match(html, /Data sources/);
  assert.doesNotMatch(html, /Activity \/ provenance/);
  assert.match(html, /data-screening-source="annual_nlcd"/);
  assert.match(html, /data-screening-source="3dep"/);
  assert.match(html, /data-screening-source="ssurgo"/);
  assert.match(html, /data-screening-source="fema_nfhl"/);
  assert.match(html, /data-screening-source="padus"/);
  assert.match(html, /class="aoi-map"/);
  assert.match(html, /Recorded AOI boundary/);
  assert.match(html, /Technical view/);
  assert.match(html, /No composite score/);
  assert.match(html, /Recorded AOI boundary/);
  assert.match(html, /data-run-screening/);
  assert.match(html, /Run screening/);
});

test("renders queued, running, succeeded, and failed screening states without inventing metrics", () => {
  for (const status of ["queued", "running", "succeeded", "failed"]) {
    const html = renderScreeningReport({
      ...report,
      aoi_context: { ...report.aoi_context, origin: "user_provided" },
      screening_run: { status, phase: status, job_id: "job-1" },
    });
    assert.match(html, /data-screening-status/);
    assert.match(html, new RegExp(status === "succeeded" ? "Screened" : status[0].toUpperCase() + status.slice(1)));
    assert.match(html, /Run screening|Annual NLCD/);
  }
});

test("shows recorded NLCD and 3DEP metrics without inventing a cross-source result", () => {
  const html = renderScreeningReport(report);
  assert.match(html, /AOI coverage.*100% covered/);
  assert.match(html, /Valid pixels.*62/);
  assert.match(html, /Observed land cover.*Developed High Intensity/);
  assert.match(html, /Developed High Intensity.*51,264\.1 m² · 91\.94%/);
  assert.match(html, /Valid cells.*484/);
  assert.match(html, /Elevation.*18\.52–22\.55 meters/);
  assert.match(html, /Mean.*20\.71 meters/);
  assert.doesNotMatch(html, /overall suitability/);
});

test("keeps the observed NLCD class summary visible while secondary sources stay collapsed", () => {
  const html = renderScreeningReport(report);
  assert.match(html, /data-screening-source="annual_nlcd" open/);
  assert.match(html, /Observed land cover/);
  assert.match(html, /Annual NLCD observations only/);
  assert.match(html, /class="workspace-secondary-sources"/);
  assert.doesNotMatch(html, /data-screening-source="3dep" open/);
});

test("renders unavailable, incomplete, rejected, conditional, unknown, and nodata semantics", () => {
  const html = renderScreeningReport(report);
  assert.match(html, /Blocked/);
  assert.match(html, /Unavailable — provider access blocked/);
  assert.match(html, /Incomplete \/ partial/);
  assert.match(html, /Rejected for incomplete coverage/);
  assert.match(html, /Conditional/);
  assert.match(html, /Coverage.*Unknown/);
  assert.match(html, /Nodata pixels.*0/);
  assert.match(html, /Nodata cells.*0/);
});

test("provides provenance disclosures and only claims available export artifacts", () => {
  const html = renderScreeningReport(report);
  assert.match(html, /View source details and provenance/);
  assert.doesNotMatch(html, /annual_nlcd:a8bcc633fd343366a5a135a3390eb02b8ec1f263a1886f9a344284/);
  assert.match(html, /Export JSON/);
  const sources = renderScreeningReport(report, "sources");
  assert.match(sources, /Version and provenance/);
  assert.match(sources, /annual_nlcd:a8bcc633fd343366a5a135a3390eb02b8ecb21ce14ecd1f263a1886f9a344284/);
  assert.match(sources, /recorded-nlcd-snapshot/);
  const exports = renderScreeningReport(report, "reports");
  assert.match(exports, /Download JSON report/);
  assert.match(exports, /CSV not included in fixture/);
  assert.match(exports, /GeoJSON not included in fixture/);
});

test("keeps the persistent layer control truthful about rendered and non-rendered sources", () => {
  const html = renderScreeningReport(report);
  assert.match(html, /class="workspace-layer-control" aria-label="Map layer availability"/);
  assert.doesNotMatch(html, /class="workspace-layer-control" aria-label="Map layer availability" open/);
  assert.match(html, /data-aoi-visibility/);
  assert.match(html, /AOI boundary/);
  assert.match(html, /Annual NLCD 2025.*Display preview/);
  assert.match(html, /data-nlcd-visibility/);
  assert.match(html, /data-nlcd-opacity/);
  assert.match(html, /Screening layers/);
  assert.match(html, /data-3dep-visibility/);
  assert.match(html, /data-3dep-opacity/);
  assert.match(html, /3DEP terrain.*Available · click to show/);
  assert.match(html, /terrain-legend/);
  assert.match(html, /Illumination only; no elevation value, unit, or datum is displayed/);
  assert.match(html, /nlcd-legend/);
  assert.match(html, /Developed High Intensity/);
  assert.match(html, /USGS 3DEP/);
  assert.match(html, /3DEP terrain preview/);
  assert.match(html, /NRCS SSURGO.*Incomplete/);
  assert.match(html, /PAD-US.*Conditional \/ unknown/);
  assert.match(html, /FEMA NFHL.*Unavailable \/ blocked/);
  assert.match(html, /display derivative/);
});

test("renders the NLCD preview as optional and honest when its metadata is absent", () => {
  const withoutPreview = { ...report, browser_previews: undefined };
  const html = renderScreeningReport(withoutPreview);
  assert.doesNotMatch(html, /data-nlcd-visibility/);
  assert.match(html, /Annual NLCD 2025.*Metrics only/);
  assert.match(html, /no browser-ready raster overlay is included/);
});

test("renders the 3DEP preview as an optional terrain layer with honest metadata limits", () => {
  const html = renderScreeningReport(report);
  assert.match(html, /3DEP terrain/);
  assert.match(html, /data-3dep-visibility/);
  assert.match(html, /data-3dep-opacity/);
  assert.match(html, /relative hillshade/);
  assert.match(html, /no elevation value, unit, or datum/);
  assert.doesNotMatch(html, /3DEP terrain.*checked data-3dep-visibility/);
});

test("keeps 3DEP metrics-only when the browser preview is unavailable", () => {
  const withoutPreview = { ...report, browser_previews: { annual_nlcd: report.browser_previews.annual_nlcd } };
  const html = renderScreeningReport(withoutPreview);
  assert.doesNotMatch(html, /data-3dep-visibility/);
  assert.match(html, /3DEP terrain.*Metrics only · no preview/);
});

test("keeps the primary source list compact while retaining expandable evidence", () => {
  const html = renderScreeningReport(report);
  assert.match(html, /class="workspace-source" data-screening-source="annual_nlcd"/);
  assert.match(html, /class="workspace-source-summary"/);
  assert.match(html, /100% AOI/);
  assert.match(html, /View source details and provenance/);
  assert.match(html, /class="workspace-info"/);
  assert.match(html, new RegExp(report.aoi.geometry_sha256));
});

test("renders secondary data-source and activity views without changing the recorded data", () => {
  const sources = renderScreeningReport(report, "sources");
  assert.match(sources, /Source catalog/);
  assert.match(sources, /Annual NLCD Collection 1.2, 2025 land cover/);
  assert.match(sources, /Provider access is blocked/);
  assert.match(sources, /Hydric-soil information is soil information/);
  assert.match(sources, /Operations view/);
  assert.match(sources, /recorded-nlcd-snapshot/);
  assert.match(sources, /Display derivative/);
  assert.match(sources, /demo\/nlcd-preview\.json/);
  assert.match(sources, /3DEP terrain preview/);
  assert.match(sources, /demo\/3dep-preview\.json/);
  assert.doesNotMatch(sources, /Activity \/ provenance/);
});

test("renders reports and export availability explicitly", () => {
  const html = renderScreeningReport(report, "reports");
  assert.match(html, /Reports and exports/);
  assert.match(html, /Download JSON report/);
  assert.match(html, /CSV not included in fixture/);
  assert.match(html, /GeoJSON not included in fixture/);
});

test("keeps responsive layout hooks for desktop and mobile screening views", async () => {
  const css = await readFile(new URL("../styles.css", import.meta.url), "utf8");
  assert.match(css, /\.screening-hero\s*\{\s*display: grid/);
  assert.match(css, /@media \(max-width: 800px\)/);
  assert.match(css, /@media \(max-width: 560px\)/);
  assert.match(css, /\.screening-grid\s*\{\s*grid-template-columns: 1fr/);
  assert.match(css, /\.workspace-source-summary\s*\{\s*display: grid/);
  assert.match(css, /\.workspace-layer-control\s*>\s*summary/);
  assert.match(css, /\.workspace-tabs\s*\{\s*gap/);
});

test("offers file and pasted GeoJSON loading without making the compact map-first view technical", () => {
  const html = renderScreeningReport(report);
  assert.match(html, /Load AOI/);
  assert.match(html, /data-aoi-file/);
  assert.match(html, /data-aoi-paste/);
  assert.match(html, /data-aoi-error/);
  assert.match(html, /AOI details/);
});

test("replacement AOIs show explicit not-evaluated states and no stale metrics or previews", async () => {
  const context = await createAoiContext({ type: "Feature", geometry: { type: "Polygon", coordinates: [[[-80, 35], [-79.99, 35], [-79.99, 35.01], [-80, 35.01], [-80, 35]]] } });
  const rebound = rebindReportToAoi(report, context);
  const html = renderScreeningReport(rebound);
  assert.match(html, /User-provided environmental screening/);
  assert.match(html, /Not evaluated/);
  assert.match(html, /Loaded AOI · source results not evaluated/);
  assert.match(html, /Existing DC metrics and display previews are not reused/);
  assert.match(html, /NLCD identify unavailable: no AOI-specific preview is attached/);
  assert.doesNotMatch(html, /Valid pixels.*62/);
  assert.doesNotMatch(html, /data-nlcd-visibility/);
  assert.doesNotMatch(html, /data-3dep-visibility/);
});
