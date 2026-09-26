import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { sourceRows, renderReport, lifecycleState, formatBytes } from "../src/app.mjs";

const report = JSON.parse(await readFile(new URL("../public/demo/report.json", import.meta.url), "utf8"));

test("loads the recorded report and renders AOI and source lifecycle evidence", () => {
  const html = renderReport(report);
  assert.match(html, /Recorded demonstration/);
  assert.match(html, new RegExp(report.aoi.geometry_sha256));
  assert.match(html, /Annual NLCD 2025/);
  assert.match(html, /USGS 3DEP/);
  assert.match(html, /NRCS SSURGO/);
  assert.match(html, /Download JSON report/);
  assert.equal(sourceRows(report).length, 3);
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
