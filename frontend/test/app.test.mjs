import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { sourceRows, renderReport, lifecycleState, candidateDispositionState, formatBytes } from "../src/app.mjs";

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
