import { parseAoi } from "./geojson";

const square = {
  type: "Polygon",
  coordinates: [[[-105, 40], [-104.9, 40], [-104.9, 40.1], [-105, 40], [-105, 40]]],
};

test("accepts a bare geometry, a Feature, or a single-feature FeatureCollection", () => {
  const feature = { type: "Feature", properties: {}, geometry: square };
  expect(parseAoi(JSON.stringify(square))).toEqual(square);
  expect(parseAoi(JSON.stringify(feature))).toEqual(square);
  expect(parseAoi(JSON.stringify({ type: "FeatureCollection", features: [feature] }))).toEqual(square);
});

test("rejects files without exactly one polygonal AOI", () => {
  const feature = { type: "Feature", properties: {}, geometry: square };
  expect(() => parseAoi("not json")).toThrow("not valid JSON");
  expect(() => parseAoi('{"type":"LineString","coordinates":[]}')).toThrow("No Polygon");
  expect(() =>
    parseAoi(JSON.stringify({ type: "FeatureCollection", features: [feature, feature] })),
  ).toThrow("Found 2 polygon features");
});
