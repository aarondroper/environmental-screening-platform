import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { parseAoiGeometry } from "../src/aoi-geometry.mjs";
import { identifyNlcdPixel } from "../src/nlcd-identify.mjs";

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

test("supports a provenance-checked NLCD image overlay with controls", async () => {
  const map = await readFile(new URL("../src/map.mjs", import.meta.url), "utf8");
  assert.match(map, /validatePreviewMetadata/);
  assert.match(map, /imageOverlay/);
  assert.match(map, /overlay_bounds_wgs84/);
  assert.match(map, /displayRaster/);
  assert.match(map, /north-up/);
  assert.match(map, /data-nlcd-visibility/);
  assert.match(map, /data-\$\{key\}-opacity/);
  assert.match(map, /source version or checksum/);
});

test("supports a provenance-checked 3DEP terrain overlay beneath the AOI boundary", async () => {
  const map = await readFile(new URL("../src/map.mjs", import.meta.url), "utf8");
  assert.match(map, /data-3dep-visibility/);
  assert.match(map, /data-\$\{key\}-opacity/);
  assert.match(map, /3DEP terrain/);
  assert.match(map, /zIndex/);
  assert.match(map, /mountRasterPreview\(element, map, layer, aoi, previews\["3dep"\]/);
  assert.match(map, /boundary\.bringToFront\(\)/);
});

test("fits the interactive map to the loaded AOI bounds", async () => {
  const map = await readFile(new URL("../src/map.mjs", import.meta.url), "utf8");
  assert.match(map, /export const fitMapToAoi/);
  assert.match(map, /fitMapToAoi\(map, layer\)/);
  assert.match(map, /fitBounds\(boundary\.getBounds\(\)/);
});

test("wires the loaded AOI to the local NLCD screening bridge", async () => {
  const main = await readFile(new URL("../src/main.mjs", import.meta.url), "utf8");
  assert.match(main, /data-run-screening/);
  assert.match(main, /\/api\/screening\/nlcd/);
  assert.match(main, /\/api\/screening-jobs/);
  assert.match(main, /rebindReportToAoi\(recordedReport, context\)/);
});

test("discovers the job-scoped Annual NLCD preview by source key", async () => {
  assert.equal(report.browser_previews.annual_nlcd.status, "available");
  assert.match(report.browser_previews.annual_nlcd.metadata_url, /demo\/nlcd-preview\.json/);
  const main = await readFile(new URL("../src/main.mjs", import.meta.url), "utf8");
  const app = await readFile(new URL("../src/app.mjs", import.meta.url), "utf8");
  assert.match(main, /activeReport\.browser_previews \|\| \{\}/);
  assert.match(app, /previews\.annual_nlcd/);
});

test("identifies an NLCD class by human-readable name and preserves unknown states", () => {
  const metadata = {
    raster: { width: 2, height: 2 },
    alignment: { overlay_bounds_wgs84: [0, 0, 2, 2] },
    legend: [{ value: 24, label: "developed_high_intensity", color: "#ab0000" }],
  };
  const imageData = { width: 2, height: 2, data: new Uint8ClampedArray([
    171, 0, 0, 255, 0, 0, 0, 0,
    0, 0, 0, 0, 0, 0, 0, 0,
  ]) };
  const aoi = { geometry: { type: "Polygon", coordinates: [[[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]]] } };
  const observed = identifyNlcdPixel({ latitude: 1.5, longitude: 0.5 }, { ...metadata, source_year: 2025 }, imageData, aoi);
  assert.equal(observed.message, "Annual NLCD 2025 class Developed High Intensity (24) · inside loaded AOI");
  assert.equal(observed.source_year, 2025);
  assert.equal(observed.inside_aoi, true);
  assert.equal(identifyNlcdPixel({ latitude: 1.5, longitude: 1.5 }, metadata, imageData, aoi).status, "nodata");
  assert.equal(identifyNlcdPixel({ latitude: 3, longitude: 1 }, metadata, imageData, aoi).status, "outside_coverage");
  assert.equal(identifyNlcdPixel({ latitude: 1, longitude: 3 }, metadata, imageData, aoi).status, "outside_coverage");
});

test("identifies a location outside the loaded AOI separately from raster coverage", () => {
  const metadata = { raster: { width: 1, height: 1 }, alignment: { overlay_bounds_wgs84: [0, 0, 2, 2] }, legend: [] };
  const imageData = { width: 1, height: 1, data: new Uint8ClampedArray([0, 0, 0, 255]) };
  const aoi = { geometry: { type: "Polygon", coordinates: [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]] } };
  assert.equal(identifyNlcdPixel({ latitude: 1.5, longitude: 1.5 }, metadata, imageData, aoi).status, "outside_aoi");
});

test("maps all four display-grid corners to the correct categorical pixels", () => {
  const metadata = {
    display_raster: {
      crs: "EPSG:4326",
      width: 2,
      height: 2,
      transform: [1, 0, 0, 0, -1, 2],
      nodata: 250,
    },
    alignment: { overlay_bounds_wgs84: [0, 0, 2, 2] },
    legend: [
      { value: 22, label: "developed_low_intensity", color: "#d99282" },
      { value: 23, label: "developed_medium_intensity", color: "#eb0000" },
    ],
  };
  const imageData = {
    width: 2,
    height: 2,
    data: new Uint8ClampedArray([
      217, 146, 130, 255, 235, 0, 0, 255,
      235, 0, 0, 255, 217, 146, 130, 255,
    ]),
  };
  const aoi = { geometry: { type: "Polygon", coordinates: [[[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]]] } };
  assert.equal(identifyNlcdPixel({ latitude: 1.75, longitude: 0.25 }, metadata, imageData, aoi).class_value, 22);
  assert.equal(identifyNlcdPixel({ latitude: 1.75, longitude: 1.75 }, metadata, imageData, aoi).class_value, 23);
  assert.equal(identifyNlcdPixel({ latitude: 0.25, longitude: 0.25 }, metadata, imageData, aoi).class_value, 23);
  assert.equal(identifyNlcdPixel({ latitude: 0.25, longitude: 1.75 }, metadata, imageData, aoi).class_value, 22);
});

test("always exposes explicit identify behavior while the preview is loading or unavailable", async () => {
  const map = await readFile(new URL("../src/map.mjs", import.meta.url), "utf8");
  const identify = await readFile(new URL("../src/nlcd-identify.mjs", import.meta.url), "utf8");
  assert.match(map, /map\.on\("click"/);
  assert.match(map, /NLCD identify is still loading/);
  assert.match(identify, /Outside the loaded AOI/);
  assert.match(identify, /No NLCD observation at this location/);
});
