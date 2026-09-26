import test from "node:test";
import assert from "node:assert/strict";
import { webcrypto } from "node:crypto";
import { readFile } from "node:fs/promises";
import { createAoiContext, geometryBounds, parseUserGeoJson, rebindReportToAoi } from "../src/aoi-input.mjs";

if (!globalThis.crypto) globalThis.crypto = webcrypto;

const polygon = {
  type: "Feature",
  properties: { name: "Test AOI" },
  geometry: { type: "Polygon", coordinates: [[[-80, 35], [-79.99, 35], [-79.99, 35.01], [-80, 35.01], [-80, 35]]] },
};

test("accepts a valid pasted GeoJSON AOI and calculates bounds and a deterministic hash", async () => {
  const context = await createAoiContext(JSON.stringify(polygon));
  assert.deepEqual(context.bounds, [-80, 35, -79.99, 35.01]);
  assert.match(context.geometry_sha256, /^[0-9a-f]{64}$/);
  assert.deepEqual(geometryBounds(context.geometry), context.bounds);
  assert.equal(context.crs, "EPSG:4326");
});
test("accepts a raw MultiPolygon and rejects non-area, empty, malformed, and self-intersecting input", () => {
  const multi = { type: "MultiPolygon", coordinates: [[[[1, 1], [1.01, 1], [1.01, 1.01], [1, 1.01], [1, 1]]]] };
  assert.equal(parseUserGeoJson(multi).type, "MultiPolygon");
  assert.throws(() => parseUserGeoJson({ type: "Point", coordinates: [1, 1] }), /Polygon or MultiPolygon/);
  assert.throws(() => parseUserGeoJson({ type: "Polygon", coordinates: [] }), /empty/);
  assert.throws(() => parseUserGeoJson({ type: "Polygon", coordinates: [[[-1, -1], [1, 1], [-1, 1], [1, -1], [-1, -1]]] }), /self-intersecting/);
  assert.throws(() => parseUserGeoJson({ type: "FeatureCollection", features: [] }), /exactly one/);
});

test("rebinds a report without presenting recorded DC metrics for a replacement AOI", async () => {
  const report = JSON.parse(await readFile(new URL("../public/demo/report.json", import.meta.url), "utf8"));
  const rebound = rebindReportToAoi(report, await createAoiContext(polygon));
  assert.equal(rebound.aoi_context.stale_recorded_results, true);
  assert.equal(rebound.sources.annual_nlcd.screening.length, 0);
  assert.equal(rebound.browser_previews.annual_nlcd, undefined);
  assert.match(rebound.warnings[0], /not reused/);
});
