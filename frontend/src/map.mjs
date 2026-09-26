import L from "leaflet";
import { parseAoiGeometry } from "./aoi-geometry.mjs";

const setMapState = (element, state, message) => {
  const status = element.querySelector("[data-map-status]");
  if (!status) return;
  status.className = `map-state map-state-${state}`;
  status.textContent = message;
  status.hidden = state === "ready";
};

const layerControl = (element) => element.parentElement?.querySelector("[data-layer-count]")?.closest(".workspace-layer-control");

const setNlcdState = (element, state, message) => {
  const control = layerControl(element);
  if (!control) return;
  const visibility = control.querySelector("[data-nlcd-visibility]");
  const status = control.querySelector("[data-nlcd-status]");
  const error = control.querySelector("[data-nlcd-error]");
  const count = control.querySelector("[data-layer-count]");
  if (state === "loading") {
    if (visibility) visibility.disabled = true;
    if (status) status.textContent = "Loading display preview…";
    if (error) error.hidden = true;
    if (count) count.textContent = "1 rendered";
    return;
  }
  if (state === "available") {
    if (visibility) visibility.disabled = false;
    if (status) status.textContent = "Visible · display derivative";
    if (error) error.hidden = true;
    if (count) count.textContent = "2 rendered";
    return;
  }
  if (visibility) {
    visibility.checked = false;
    visibility.disabled = true;
  }
  if (status) status.textContent = "Unavailable · preview not loaded";
  if (error) {
    error.textContent = message;
    error.hidden = false;
  }
  if (count) count.textContent = "1 rendered";
};

const validatePreviewMetadata = (metadata, preview, aoi) => {
  if (!metadata || metadata.status !== "available" || metadata.display_derivative !== true) {
    throw new Error("NLCD preview metadata is not available as a display derivative");
  }
  const source = metadata.source || {};
  const alignment = metadata.alignment || {};
  if (source.source_version_id !== preview.source_version_id || source.sha256 !== preview.source_sha256) {
    throw new Error("NLCD preview source version or checksum does not match the recorded report");
  }
  if (metadata.aoi?.revision !== preview.aoi_revision || metadata.aoi?.geometry_sha256 !== preview.aoi_geometry_sha256 || alignment.aoi_geometry_sha256 !== aoi.geometry_sha256) {
    throw new Error("NLCD preview AOI provenance does not match the recorded AOI");
  }
  const bounds = alignment.overlay_bounds_wgs84;
  if (!Array.isArray(bounds) || bounds.length !== 4 || bounds.some((value) => !Number.isFinite(Number(value)))) {
    throw new Error("NLCD preview has no valid WGS84 overlay bounds");
  }
  return bounds;
};

const mountNlcdPreview = (element, map, boundary, aoi, preview) => {
  if (preview?.status !== "available") return;
  setNlcdState(element, "loading", "Loading NLCD preview…");
  fetch(preview.metadata_url)
    .then((response) => {
      if (!response.ok) throw new Error(`metadata request failed (${response.status})`);
      return response.json();
    })
    .then((metadata) => {
      const bounds = validatePreviewMetadata(metadata, preview, aoi).map(Number);
      const imageBounds = [[bounds[1], bounds[0]], [bounds[3], bounds[2]]];
      const overlay = L.imageOverlay(preview.asset_url, imageBounds, {
        opacity: Number(preview.opacity_default ?? 0.58),
        interactive: false,
      });
      overlay.once("load", () => {
        boundary.bringToFront();
        setNlcdState(element, "available", "");
      });
      overlay.once("error", () => setNlcdState(element, "error", "The NLCD preview asset could not be loaded."));
      const control = layerControl(element);
      const visibility = control?.querySelector("[data-nlcd-visibility]");
      const opacity = control?.querySelector("[data-nlcd-opacity]");
      visibility?.addEventListener("change", () => {
        if (visibility.checked) overlay.addTo(map);
        else map.removeLayer(overlay);
        boundary.bringToFront();
      });
      opacity?.addEventListener("input", () => overlay.setOpacity(Number(opacity.value)));
      overlay.addTo(map);
    })
    .catch((error) => setNlcdState(element, "error", `NLCD preview unavailable: ${error.message}`));
};

export const mountAoiMap = (element, aoi, previews = {}) => {
  if (!element) throw new Error("AOI map container is missing");
  const feature = parseAoiGeometry(aoi);
  setMapState(element, "loading", "Loading public basemap…");
  const map = L.map(element, { zoomControl: true, attributionControl: true, scrollWheelZoom: false });
  const tileLayer = L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    minZoom: 2,
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
  }).addTo(map);
  const layer = L.geoJSON(feature, {
    style: { color: "#075f52", weight: 3, opacity: 1, fillColor: "#58aa96", fillOpacity: 0.36 },
  }).addTo(map);
  map.fitBounds(layer.getBounds(), { padding: [28, 28], maxZoom: 16 });
  mountNlcdPreview(element, map, layer, aoi, previews.annual_nlcd);
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
