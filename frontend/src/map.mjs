import L from "leaflet";
import { parseAoiGeometry } from "./aoi-geometry.mjs";

const setMapState = (element, state, message) => {
  const status = element.querySelector("[data-map-status]");
  if (!status) return;
  status.className = `map-state map-state-${state}`;
  status.textContent = message;
  status.hidden = state === "ready";
};

export const mountAoiMap = (element, aoi) => {
  if (!element) throw new Error("AOI map container is missing");
  const feature = parseAoiGeometry(aoi);
  setMapState(element, "loading", "Loading public basemap…");
  const map = L.map(element, { zoomControl: true, attributionControl: true, scrollWheelZoom: false });
  const layer = L.geoJSON(feature, {
    style: { color: "#075f52", weight: 3, opacity: 1, fillColor: "#58aa96", fillOpacity: 0.36 },
  }).addTo(map);
  const tileLayer = L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    minZoom: 2,
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
  }).addTo(map);
  map.fitBounds(layer.getBounds(), { padding: [28, 28], maxZoom: 16 });
  tileLayer.once("load", () => setMapState(element, "ready", ""));
  tileLayer.on("tileerror", () => setMapState(element, "error", "Public basemap unavailable. The recorded AOI boundary remains shown, but map context could not be loaded."));
  window.setTimeout(() => {
    if (element.querySelector("[data-map-status]")?.classList.contains("map-state-loading")) {
      setMapState(element, "error", "Public basemap is taking too long to load. Check network access; the AOI boundary remains shown.");
    }
  }, 8000);
  window.setTimeout(() => map.invalidateSize(), 0);
  return { map, layer, tileLayer };
};
