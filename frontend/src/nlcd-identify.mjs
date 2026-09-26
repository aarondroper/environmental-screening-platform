const pointInRing = ([x, y], ring) => {
  let inside = false;
  for (let index = 0, previous = ring.length - 1; index < ring.length; previous = index++) {
    const [xi, yi] = ring[index];
    const [xj, yj] = ring[previous];
    const crosses = ((yi > y) !== (yj > y)) && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi;
    if (crosses) inside = !inside;
  }
  return inside;
};

const pointInPolygon = (point, polygon) => pointInRing(point, polygon[0])
  && polygon.slice(1).every((ring) => !pointInRing(point, ring));

const pointInAoi = (point, aoi) => {
  const geometry = aoi?.geometry || aoi;
  if (!geometry) return false;
  const polygons = geometry.type === "Polygon" ? [geometry.coordinates] : geometry.coordinates || [];
  return polygons.some((polygon) => pointInPolygon(point, polygon));
};

const humanizeClassName = (value) => String(value || "Unknown class")
  .replaceAll("_", " ")
  .replace(/\b\w/g, (character) => character.toUpperCase());

const hexRgb = (value) => {
  const match = String(value || "").match(/^#([0-9a-f]{6})$/i);
  return match ? [1, 3, 5].map((offset) => Number.parseInt(match[1].slice(offset - 1, offset + 1), 16)) : null;
};

export const identifyNlcdPixel = ({ latitude, longitude }, metadata, imageData, aoi) => {
  const bounds = metadata?.alignment?.overlay_bounds_wgs84;
  if (!Array.isArray(bounds) || bounds.length !== 4) {
    return { status: "outside_coverage", message: "No NLCD observation: coverage bounds are unavailable." };
  }
  const [west, south, east, north] = bounds.map(Number);
  if (![west, south, east, north].every(Number.isFinite)
    || longitude < west || longitude > east || latitude < south || latitude > north) {
    return { status: "outside_coverage", message: "No NLCD observation: this location is outside NLCD coverage." };
  }
  if (aoi && !pointInAoi([longitude, latitude], aoi)) {
    return { status: "outside_aoi", message: "No NLCD observation: this location is outside the loaded AOI." };
  }
  const width = Number(imageData?.width || metadata.raster?.width);
  const height = Number(imageData?.height || metadata.raster?.height);
  if (!Number.isFinite(width) || !Number.isFinite(height) || width <= 0 || height <= 0) {
    return { status: "unknown", message: "No NLCD observation: raster dimensions are unavailable." };
  }
  const x = Math.min(width - 1, Math.max(0, Math.floor(((longitude - west) / (east - west)) * width)));
  const y = Math.min(height - 1, Math.max(0, Math.floor(((north - latitude) / (north - south)) * height)));
  const offset = (y * width + x) * 4;
  const alpha = Number(imageData?.data?.[offset + 3] || 0);
  if (!alpha) {
    return { status: "nodata", message: "No NLCD observation: this pixel is nodata or outside the AOI mask." };
  }
  const rgb = [...imageData.data.slice(offset, offset + 3)];
  const legend = (metadata.legend || []).find((item) => {
    const color = hexRgb(item.color);
    return color && color.every((component, index) => component === rgb[index]);
  });
  if (!legend) return { status: "unknown", message: "No NLCD observation: the display pixel has no recognized class." };
  const className = humanizeClassName(legend.label);
  return {
    status: "observed",
    class_value: Number(legend.value),
    class_name: className,
    message: `NLCD class ${className} (${legend.value})`,
  };
};
