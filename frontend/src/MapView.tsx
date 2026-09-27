import type { FeatureCollection } from "geojson";
import * as maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
// MapLibre locates its web worker relative to its own module, which does not survive
// bundling; ship the worker as a Vite-built asset and point MapLibre at it.
import maplibreWorkerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url";
import { useEffect, useRef, useState } from "react";
import { TerraDraw, TerraDrawPolygonMode } from "terra-draw";
import { TerraDrawMapLibreGLAdapter } from "terra-draw-maplibre-gl-adapter";

import type { AoiGeometry } from "./api";
import { HYDRIC_COLORS } from "./hydric";

maplibregl.setWorkerUrl(maplibreWorkerUrl);

const BASEMAP_STYLE = "https://tiles.openfreemap.org/styles/positron";
// Colorado, the platform's screening region.
const COLORADO_BOUNDS: maplibregl.LngLatBoundsLike = [
  [-109.06, 36.99],
  [-102.04, 41.0],
];
const EMPTY: FeatureCollection = { type: "FeatureCollection", features: [] };

interface Props {
  aoi: AoiGeometry | null;
  features: FeatureCollection | null;
  drawing: boolean;
  onDrawn: (geometry: AoiGeometry) => void;
}

export function MapView({ aoi, features, drawing, onDrawn }: Props) {
  const container = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const drawRef = useRef<TerraDraw | null>(null);
  const onDrawnRef = useRef(onDrawn);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    onDrawnRef.current = onDrawn;
  }, [onDrawn]);

  useEffect(() => {
    if (!container.current) return;
    const map = new maplibregl.Map({
      container: container.current,
      style: BASEMAP_STYLE,
      bounds: COLORADO_BOUNDS,
      fitBoundsOptions: { padding: 24 },
    });
    map.addControl(new maplibregl.NavigationControl(), "top-right");
    map.addControl(new maplibregl.ScaleControl({ unit: "metric" }), "bottom-right");
    map.on("load", () => {
      map.addSource("features", { type: "geojson", data: EMPTY });
      map.addLayer({
        id: "features-fill",
        type: "fill",
        source: "features",
        paint: {
          "fill-color": [
            "match",
            ["get", "class"],
            ...Object.entries(HYDRIC_COLORS).flat(),
            "#a8a8a8",
          ] as unknown as maplibregl.ExpressionSpecification,
          "fill-opacity": 0.75,
        },
      });
      map.addLayer({
        id: "features-line",
        type: "line",
        source: "features",
        paint: { "line-color": "#ffffff", "line-width": 0.5, "line-opacity": 0.8 },
      });
      map.addSource("aoi", { type: "geojson", data: EMPTY });
      map.addLayer({
        id: "aoi-line",
        type: "line",
        source: "aoi",
        paint: { "line-color": "#c2410c", "line-width": 2.5 },
      });
      map.on("click", "features-fill", (event) => {
        const props = event.features?.[0]?.properties;
        if (!props) return;
        const pct = props.hydric_pct ?? "not rated";
        new maplibregl.Popup({ closeButton: false })
          .setLngLat(event.lngLat)
          .setHTML(
            `<strong>${escapeHtml(String(props.muname))}</strong><br/>` +
              `Hydric components: ${escapeHtml(String(pct))}${pct === "not rated" ? "" : "%"}` +
              `<br/><span class="muted">Map unit key ${escapeHtml(String(props.mukey))}</span>`,
          )
          .addTo(map);
      });
      map.on("mouseenter", "features-fill", () => (map.getCanvas().style.cursor = "pointer"));
      map.on("mouseleave", "features-fill", () => (map.getCanvas().style.cursor = ""));

      const draw = new TerraDraw({
        adapter: new TerraDrawMapLibreGLAdapter({ map }),
        modes: [new TerraDrawPolygonMode()],
      });
      draw.on("finish", (id) => {
        const feature = draw.getSnapshotFeature(id);
        draw.clear();
        if (feature?.geometry.type === "Polygon") onDrawnRef.current(feature.geometry);
      });
      drawRef.current = draw;
      setReady(true);
    });
    mapRef.current = map;
    return () => {
      drawRef.current?.stop();
      map.remove();
    };
  }, []);

  useEffect(() => {
    const draw = drawRef.current;
    if (!ready || !draw) return;
    if (drawing) {
      if (!draw.enabled) draw.start();
      draw.setMode("polygon");
    } else if (draw.enabled) {
      draw.clear();
      draw.stop();
    }
  }, [drawing, ready]);

  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map) return;
    const source = map.getSource<maplibregl.GeoJSONSource>("aoi");
    source?.setData(aoi ? { type: "Feature", geometry: aoi, properties: {} } : EMPTY);
    if (aoi) {
      const bounds = new maplibregl.LngLatBounds();
      const rings = aoi.type === "Polygon" ? [aoi.coordinates] : aoi.coordinates;
      rings.flat(2).forEach(([lng, lat]) => bounds.extend([lng, lat]));
      map.fitBounds(bounds, { padding: 60, maxZoom: 15, duration: 600 });
    }
  }, [aoi, ready]);

  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map) return;
    map.getSource<maplibregl.GeoJSONSource>("features")?.setData(features ?? EMPTY);
  }, [features, ready]);

  return <div ref={container} className="map" data-testid="map" />;
}

function escapeHtml(value: string): string {
  return value.replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);
}
