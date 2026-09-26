import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { parseAoiGeometry } from "../src/aoi-geometry.mjs";

const report = JSON.parse(await readFile(new URL("../public/demo/report.json", import.meta.url), "utf8"));

test("parses the recorded AOI geometry as a WGS84 GeoJSON feature", () => {
  const feature = parseAoiGeometry(report.aoi);
  assert.equal(feature.type, "Feature");
  assert.equal(feature.geometry.type, "Polygon");
  assert.deepEqual(feature.geometry.coordinates, report.aoi.geometry.coordinates);
  assert.deepEqual(feature.geometry.coordinates[0][0], [-77.041, 38.9]);
});

test("rejects missing, unsupported, and malformed AOI geometry", () => {
  assert.throws(() => parseAoiGeometry({}), /geometry is missing/);
  assert.throws(() => parseAoiGeometry({ geometry: { type: "Point", coordinates: [-77, 38] } }), /Unsupported AOI geometry/);
  assert.throws(() => parseAoiGeometry({ geometry: { type: "Polygon", coordinates: [[[1, 2], [3, 4], [1, 2]]] } }), /invalid polygon rings/);
  assert.throws(() => parseAoiGeometry({ geometry: { type: "Polygon", coordinates: [[[-181, 2], [-181, 3], [-180, 3], [-181, 2]]] } }), /invalid polygon rings/);
});

test("the browser route has explicit map loading and error states", async () => {
  const main = await readFile(new URL("../src/main.mjs", import.meta.url), "utf8");
  const app = await readFile(new URL("../src/app.mjs", import.meta.url), "utf8");
  assert.match(app, /data-aoi-map/);
  assert.match(app, /Loading public basemap/);
  assert.match(main, /AOI map unavailable/);
  assert.match(main, /mountAoiMap/);
});
