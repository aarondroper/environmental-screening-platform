import type { AoiGeometry } from "./api";

/**
 * Extract a single Polygon/MultiPolygon from uploaded GeoJSON (a geometry, a Feature, or a
 * FeatureCollection with exactly one polygonal feature). The server does the real
 * validation (validity, size, region); this only gives an early, specific message.
 */
export function parseAoi(text: string): AoiGeometry {
  let data: unknown;
  try {
    data = JSON.parse(text);
  } catch {
    throw new Error("The file is not valid JSON.");
  }
  const candidates = collect(data);
  if (candidates.length === 0) {
    throw new Error("No Polygon or MultiPolygon found in the file.");
  }
  if (candidates.length > 1) {
    throw new Error(`Found ${candidates.length} polygon features; upload exactly one AOI.`);
  }
  return candidates[0];
}

function collect(value: unknown): AoiGeometry[] {
  if (!isObject(value)) return [];
  switch (value.type) {
    case "Polygon":
    case "MultiPolygon":
      return Array.isArray(value.coordinates) ? [value as unknown as AoiGeometry] : [];
    case "Feature":
      return collect(value.geometry);
    case "FeatureCollection":
      return Array.isArray(value.features) ? value.features.flatMap(collect) : [];
    default:
      return [];
  }
}

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

/** A small AOI along the Cache la Poudre River in Fort Collins, for trying the app. */
export const EXAMPLE_AOI: AoiGeometry = {
  type: "Polygon",
  coordinates: [
    [
      [-105.078, 40.573],
      [-105.042, 40.573],
      [-105.042, 40.598],
      [-105.078, 40.598],
      [-105.078, 40.573],
    ],
  ],
};
