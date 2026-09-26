import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { sourceRows, renderReport, renderScreeningReport, lifecycleState, candidateDispositionState, formatBytes } from "../src/app.mjs";

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
  assert.match(html, /Environmental Screening/);
  assert.match(html, /Screening results/);
  assert.match(html, /Reports \/ exports/);
  assert.match(html, /Data sources/);
  assert.match(html, /Activity \/ provenance/);
  assert.match(html, /data-screening-source="annual_nlcd"/);
  assert.match(html, /data-screening-source="3dep"/);
  assert.match(html, /data-screening-source="ssurgo"/);
  assert.match(html, /data-screening-source="fema_nfhl"/);
  assert.match(html, /data-screening-source="padus"/);
  assert.match(html, /class="aoi-map"/);
  assert.match(html, /Recorded AOI geometry/);
  assert.match(html, /Technical operations view/);
  assert.match(html, /No composite environmental score/);
  assert.match(html, /Recorded AOI geometry boundary/);
});

test("shows recorded NLCD and 3DEP metrics without inventing a cross-source result", () => {
  const html = renderScreeningReport(report);
  assert.match(html, /AOI coverage.*100% covered/);
  assert.match(html, /Valid pixels.*62/);
  assert.match(html, /Observed classes.*developed_high_intensity: 57/);
  assert.match(html, /Valid cells.*484/);
  assert.match(html, /Elevation.*18\.52–22\.55 meters/);
  assert.match(html, /Mean.*20\.71 meters/);
  assert.doesNotMatch(html, /overall suitability/);
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
  assert.match(html, /Source provenance and details/);
  assert.match(html, /annual_nlcd:a8bcc633fd343366a5a135a3390eb02b8ecb21ce14ecd1f263a1886f9a344284/);
  assert.match(html, /recorded-nlcd-snapshot/);
  assert.match(html, /Export JSON/);
  const exports = renderScreeningReport(report, "reports");
  assert.match(exports, /Download JSON report/);
  assert.match(exports, /CSV not included in fixture/);
  assert.match(exports, /GeoJSON not included in fixture/);
});

test("keeps the persistent layer control truthful about rendered and non-rendered sources", () => {
  const html = renderScreeningReport(report);
  assert.match(html, /Map layer availability/);
  assert.match(html, /AOI boundary/);
  assert.match(html, /Annual NLCD 2025.*Metrics only/);
  assert.match(html, /USGS 3DEP.*Metrics only/);
  assert.match(html, /NRCS SSURGO.*Incomplete/);
  assert.match(html, /PAD-US.*Conditional \/ unknown/);
  assert.match(html, /FEMA NFHL.*Unavailable \/ blocked/);
  assert.match(html, /no browser-ready raster overlay is included/);
});

test("renders secondary data-source and activity views without changing the recorded data", () => {
  const sources = renderScreeningReport(report, "sources");
  assert.match(sources, /Source catalog/);
  assert.match(sources, /Annual NLCD Collection 1.2, 2025 land cover/);
  assert.match(sources, /Provider access is blocked/);
  assert.match(sources, /Hydric-soil information is soil information/);

  const activity = renderScreeningReport(report, "activity");
  assert.match(activity, /Technical provenance/);
  assert.match(activity, /dc-smoke-parent-run/);
  assert.match(activity, /recorded-nlcd-snapshot/);
  assert.match(activity, /Open operations console/);
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
});
