import * as maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { useEffect, useRef } from "react";

const BASEMAP_STYLE = "https://tiles.openfreemap.org/styles/positron";
// Colorado, the platform's screening region.
const COLORADO_BOUNDS: maplibregl.LngLatBoundsLike = [
  [-109.06, 36.99],
  [-102.04, 41.0],
];

export function MapView() {
  const container = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!container.current) return;
    const map = new maplibregl.Map({
      container: container.current,
      style: BASEMAP_STYLE,
      bounds: COLORADO_BOUNDS,
      fitBoundsOptions: { padding: 24 },
    });
    map.addControl(new maplibregl.NavigationControl(), "top-right");
    map.addControl(new maplibregl.ScaleControl({ unit: "metric" }), "bottom-left");
    return () => map.remove();
  }, []);

  return <div ref={container} className="map" data-testid="map" />;
}
