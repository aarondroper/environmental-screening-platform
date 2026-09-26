const isCoordinate = (value) => Array.isArray(value)
  && value.length >= 2
  && Number.isFinite(Number(value[0]))
  && Number.isFinite(Number(value[1]))
  && Number(value[0]) >= -180
  && Number(value[0]) <= 180
  && Number(value[1]) >= -90
  && Number(value[1]) <= 90;

const validRing = (ring) => Array.isArray(ring)
  && ring.length >= 4
  && ring.every(isCoordinate)
  && ring[0][0] === ring.at(-1)[0]
  && ring[0][1] === ring.at(-1)[1];

export const parseAoiGeometry = (aoi = {}) => {
  const geometry = aoi.geometry;
  if (!geometry || typeof geometry !== "object") throw new Error("AOI geometry is missing from the recorded report");
  if (!(["Polygon", "MultiPolygon"].includes(geometry.type))) {
    throw new Error(`Unsupported AOI geometry type: ${geometry.type || "unknown"}`);
  }
  const polygons = geometry.type === "Polygon" ? [geometry.coordinates] : geometry.coordinates;
  if (!Array.isArray(polygons) || !polygons.length || !polygons.every((polygon) => Array.isArray(polygon) && polygon.length && polygon.every(validRing))) {
    throw new Error("AOI geometry has invalid polygon rings");
  }
  return {
    type: "Feature",
    properties: { source: "recorded_aoi_geometry" },
    geometry: {
      type: geometry.type,
      coordinates: geometry.coordinates,
    },
  };
};
