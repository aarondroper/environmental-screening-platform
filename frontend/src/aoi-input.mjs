import { parseAoiGeometry } from "./aoi-geometry.mjs";

const areaTypes = new Set(["Polygon", "MultiPolygon"]);

const sameCoordinate = (left, right) => left[0] === right[0] && left[1] === right[1];

const ringArea = (ring) => Math.abs(ring.reduce((sum, point, index) => {
  const next = ring[(index + 1) % ring.length];
  return sum + (point[0] * next[1]) - (next[0] * point[1]);
}, 0) / 2);

const orientation = (a, b, c) => ((b[0] - a[0]) * (c[1] - a[1])) - ((b[1] - a[1]) * (c[0] - a[0]));

const onSegment = (a, b, point) => Math.min(a[0], b[0]) <= point[0]
  && point[0] <= Math.max(a[0], b[0])
  && Math.min(a[1], b[1]) <= point[1]
  && point[1] <= Math.max(a[1], b[1]);

const segmentsIntersect = (a, b, c, d) => {
  const abC = orientation(a, b, c);
  const abD = orientation(a, b, d);
  const cdA = orientation(c, d, a);
  const cdB = orientation(c, d, b);
  const epsilon = 1e-12;
  if (Math.abs(abC) < epsilon && onSegment(a, b, c)) return true;
  if (Math.abs(abD) < epsilon && onSegment(a, b, d)) return true;
  if (Math.abs(cdA) < epsilon && onSegment(c, d, a)) return true;
  if (Math.abs(cdB) < epsilon && onSegment(c, d, b)) return true;
  return ((abC > 0) !== (abD > 0)) && ((cdA > 0) !== (cdB > 0));
};

const ringIsSimple = (ring) => {
  const edges = ring.slice(0, -1).map((point, index) => [point, ring[index + 1]]);
  return edges.every(([a, b], index) => edges.every(([c, d], otherIndex) => {
    if (index === otherIndex || Math.abs(index - otherIndex) === 1 || (index === 0 && otherIndex === edges.length - 1) || (otherIndex === 0 && index === edges.length - 1)) return true;
    return !segmentsIntersect(a, b, c, d);
  }));
};

const validateAreaGeometry = (geometry) => {
  if (!geometry || typeof geometry !== "object") throw new Error("GeoJSON geometry is missing");
  if (!areaTypes.has(geometry.type)) throw new Error("AOI must be a Polygon or MultiPolygon");
  const polygons = geometry.type === "Polygon" ? [geometry.coordinates] : geometry.coordinates;
  if (!Array.isArray(polygons) || polygons.length === 0) throw new Error("AOI geometry is empty");
  if (polygons.some((polygon) => !Array.isArray(polygon) || polygon.length === 0)) throw new Error("AOI geometry is empty");
  for (const polygon of polygons) {
    for (const ring of polygon) {
      if (!Array.isArray(ring) || ring.length < 4 || !ring.every((point) => Array.isArray(point) && point.length === 2 && Number.isFinite(point[0]) && Number.isFinite(point[1]))) {
        throw new Error("AOI geometry has invalid polygon coordinates");
      }
      if (!sameCoordinate(ring[0], ring.at(-1))) throw new Error("AOI polygon rings must be closed");
      if (!ringIsSimple(ring)) throw new Error("AOI geometry contains a self-intersecting ring");
      if (ringArea(ring) <= 1e-12) throw new Error("AOI geometry contains an empty or zero-area ring");
    }
  }
  return geometry;
};

const extractGeometry = (input) => {
  if (!input || typeof input !== "object") throw new Error("GeoJSON must be an object");
  if (input.type === "Feature") return input.geometry;
  if (input.type === "FeatureCollection") {
    const features = (input.features || []).filter((feature) => feature?.geometry);
    if (features.length !== 1) throw new Error("GeoJSON FeatureCollection must contain exactly one area feature");
    return features[0].geometry;
  }
  return input;
};

export const parseUserGeoJson = (value) => {
  let input;
  try {
    input = typeof value === "string" ? JSON.parse(value) : value;
  } catch {
    throw new Error("GeoJSON could not be parsed");
  }
  const geometry = validateAreaGeometry(extractGeometry(input));
  const feature = parseAoiGeometry({ geometry });
  return feature.geometry;
};

const coordinatePairs = (coordinates) => {
  if (!Array.isArray(coordinates)) return [];
  if (coordinates.length >= 2 && coordinates.every((value) => Number.isFinite(Number(value)))) return [[Number(coordinates[0]), Number(coordinates[1])]];
  return coordinates.flatMap(coordinatePairs);
};

export const geometryBounds = (geometry) => {
  const coordinates = coordinatePairs(geometry.coordinates);
  if (!coordinates.length) throw new Error("AOI geometry has no coordinates");
  const longitudes = coordinates.map(([longitude]) => longitude);
  const latitudes = coordinates.map(([, latitude]) => latitude);
  return [Math.min(...longitudes), Math.min(...latitudes), Math.max(...longitudes), Math.max(...latitudes)];
};

const stableValue = (value) => {
  if (Array.isArray(value)) return value.map(stableValue);
  if (value && typeof value === "object") return Object.fromEntries(Object.keys(value).sort().map((key) => [key, stableValue(value[key])]));
  return value;
};

export const geometryHash = async (geometry) => {
  if (!globalThis.crypto?.subtle) throw new Error("This browser does not support SHA-256 geometry hashing");
  const canonical = JSON.stringify(stableValue({ type: geometry.type, coordinates: geometry.coordinates }));
  const digest = await globalThis.crypto.subtle.digest("SHA-256", new TextEncoder().encode(canonical));
  return [...new Uint8Array(digest)].map((byte) => byte.toString(16).padStart(2, "0")).join("");
};

export const createAoiContext = async (value) => {
  const geometry = parseUserGeoJson(value);
  return {
    geometry,
    bounds: geometryBounds(geometry),
    geometry_sha256: await geometryHash(geometry),
    crs: "EPSG:4326",
    origin: "user_provided",
    validation_policy: "generic_browser_aoi",
  };
};

const emptySourceForAoi = (source, reason) => ({
  source_id: source.source_id,
  provider_release: source.provider_release,
  status_only_reason: reason,
  lifecycle: { stopped_at: "not_evaluated", not_evaluated: [{ reason }] },
  screening: [],
  candidates: [],
  source_versions: [],
  active_aoi_versions: [],
  promotion_decisions: [],
  ingestion_runs: [],
  parent_summaries: [],
});

export const rebindReportToAoi = (report, context) => {
  const reason = "Not evaluated for this user-provided AOI; recorded Washington, DC source results are not reused.";
  const rebound = JSON.parse(JSON.stringify(report));
  rebound.aoi = {
    aoi_id: "session-user-aoi",
    revision: 1,
    policy: context.validation_policy,
    geometry_sha256: context.geometry_sha256,
    geometry: context.geometry,
    area: { value_sqkm: null, crs: "EPSG:4326", status: "not_calculated_in_browser" },
    spatial_validation: { crs: context.crs, bounds: context.bounds, status: "validated" },
  };
  rebound.aoi_context = { ...context, stale_recorded_results: true };
  rebound.browser_previews = {};
  rebound.screening_jobs = [];
  rebound.parent_ingestion_runs = [];
  rebound.warnings = [reason, "Source-specific acquisition and screening are not run by this browser-only AOI loader."];
  rebound.sources = Object.fromEntries(Object.entries(rebound.sources || {}).map(([id, source]) => [id, emptySourceForAoi(source, reason)]));
  rebound.demo_notice = "User-provided AOI loaded locally; no recorded environmental results are attached to this geometry.";
  return rebound;
};
