import L from "leaflet";
import { parseAoiGeometry } from "./aoi-geometry.mjs";
import { identifyNlcdPixel } from "./nlcd-identify.mjs";

const setMapState = (element, state, message) => {
  const status = element.querySelector("[data-map-status]");
  if (!status) return;
  status.className = `map-state map-state-${state}`;
  status.textContent = message;
  status.hidden = state === "ready";
};

const layerControl = (element) => element.parentElement?.querySelector("[data-layer-count]")?.closest(".workspace-layer-control");

const updateVisibleLayerCount = (element) => {
  const control = layerControl(element);
  const count = control?.querySelector("[data-layer-count]");
  if (!count) return;
  const visible = 1 + [...control.querySelectorAll("[data-nlcd-visibility], [data-3dep-visibility]")]
    .filter((input) => input.checked && !input.disabled).length;
  count.textContent = `${visible} visible`;
};

const setPreviewState = (element, key, state, message) => {
  const control = layerControl(element);
  if (!control) return;
  const visibility = control.querySelector(`[data-${key}-visibility]`);
  const status = control.querySelector(`[data-${key}-status]`);
  const error = control.querySelector(`[data-${key}-error]`);
  if (state === "loading") {
    if (visibility) visibility.disabled = true;
    if (status) status.textContent = "Loading display preview…";
    if (error) error.hidden = true;
    updateVisibleLayerCount(element);
    return;
  }
  if (state === "available") {
    if (visibility) visibility.disabled = false;
    if (status) status.textContent = visibility?.checked ? "Visible · display derivative" : "Available · click to show";
    if (error) error.hidden = true;
    updateVisibleLayerCount(element);
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
  updateVisibleLayerCount(element);
};

const setIdentifyMessage = (element, result) => {
  const target = element.closest(".workspace-map-stage")?.querySelector("[data-nlcd-identify]");
  if (!target) return;
  target.textContent = result.message;
  target.dataset.identifyState = result.status;
  target.className = `map-identify map-identify-${result.status}`;
};

const createNlcdIdentifyHandler = (element, overlay, metadata, aoi) => {
  const image = overlay.getElement?.();
  if (!image || typeof document === "undefined") return null;
  const canvas = document.createElement("canvas");
  const displayRaster = metadata.display_raster || metadata.raster;
  canvas.width = Number(displayRaster?.width || image.naturalWidth);
  canvas.height = Number(displayRaster?.height || image.naturalHeight);
  const context = canvas.getContext("2d", { willReadFrequently: true });
  if (!context || !canvas.width || !canvas.height) return null;
  let imageData;
  try {
    context.drawImage(image, 0, 0, canvas.width, canvas.height);
    imageData = context.getImageData(0, 0, canvas.width, canvas.height);
  } catch {
    return null;
  }
  return (event) => setIdentifyMessage(
    element,
    identifyNlcdPixel(event.latlng, metadata, imageData, aoi),
  );
};

const validatePreviewMetadata = (metadata, preview, aoi, sourceLabel) => {
  if (!metadata || metadata.status !== "available" || metadata.display_derivative !== true) {
    throw new Error(`${sourceLabel} preview metadata is not available as a display derivative`);
  }
  const source = metadata.source || {};
  const alignment = metadata.alignment || {};
  const displayRaster = metadata.display_raster || metadata.raster || {};
  if (source.source_id && source.source_id !== preview.source_id) {
    throw new Error(`${sourceLabel} preview source identity does not match the recorded report`);
  }
  if (source.source_version_id !== preview.source_version_id || source.sha256 !== preview.source_sha256) {
    throw new Error(`${sourceLabel} preview source version or checksum does not match the recorded report`);
  }
  if (source.source_snapshot_id !== preview.source_snapshot_id) {
    throw new Error(`${sourceLabel} preview source snapshot does not match the recorded report`);
  }
  if (metadata.aoi?.revision !== preview.aoi_revision || metadata.aoi?.geometry_sha256 !== preview.aoi_geometry_sha256 || alignment.aoi_geometry_sha256 !== aoi.geometry_sha256) {
    throw new Error(`${sourceLabel} preview AOI provenance does not match the recorded AOI`);
  }
  const bounds = alignment.overlay_bounds_wgs84;
  if (!Array.isArray(bounds) || bounds.length !== 4 || bounds.some((value) => !Number.isFinite(Number(value)))) {
    throw new Error(`${sourceLabel} preview has no valid WGS84 overlay bounds`);
  }
  if (displayRaster.crs !== "EPSG:4326" && displayRaster.crs !== "EPSG:3857") {
    throw new Error(`${sourceLabel} preview display CRS is not web compatible`);
  }
  if (!Number.isInteger(Number(displayRaster.width)) || !Number.isInteger(Number(displayRaster.height))
    || Number(displayRaster.width) <= 0 || Number(displayRaster.height) <= 0) {
    throw new Error(`${sourceLabel} preview has invalid display dimensions`);
  }
  const transform = displayRaster.transform || alignment.display_transform;
  if (!Array.isArray(transform) || transform.length < 6
    || Number(transform[1]) !== 0 || Number(transform[3]) !== 0) {
    throw new Error(`${sourceLabel} preview display transform is not north-up`);
  }
  return bounds;
};

const mountRasterPreview = (element, map, boundary, aoi, preview, key, sourceLabel, zIndex, onIdentifyReady) => {
  if (preview?.status !== "available") return;
  setPreviewState(element, key, "loading", `Loading ${sourceLabel} preview…`);
  fetch(preview.metadata_url)
    .then((response) => {
      if (!response.ok) throw new Error(`metadata request failed (${response.status})`);
      return response.json();
    })
    .then((metadata) => {
      const bounds = validatePreviewMetadata(metadata, preview, aoi, sourceLabel).map(Number);
      const imageBounds = [[bounds[1], bounds[0]], [bounds[3], bounds[2]]];
      const overlay = L.imageOverlay(preview.asset_url, imageBounds, {
        opacity: Number(preview.opacity_default ?? 0.5),
        interactive: false,
        zIndex,
      });
      const defaultVisible = preview.default_visible === true || (preview.default_visible === undefined && key === "nlcd");
      overlay.once("load", () => {
        if (!defaultVisible) map.removeLayer(overlay);
        boundary.bringToFront();
        if (key === "nlcd") {
          const identifyHandler = createNlcdIdentifyHandler(element, overlay, metadata, aoi);
          onIdentifyReady?.(identifyHandler);
          if (!identifyHandler) {
            setIdentifyMessage(element, { status: "unavailable", message: "NLCD identify unavailable: the display image could not be read." });
          }
        }
        setPreviewState(element, key, "available", "");
      });
      overlay.once("error", () => {
        map.removeLayer(overlay);
        if (key === "nlcd") setIdentifyMessage(element, { status: "unavailable", message: "NLCD identify unavailable: the AOI-specific preview could not be loaded." });
        setPreviewState(element, key, "error", `The ${sourceLabel} preview asset could not be loaded.`);
      });
      const control = layerControl(element);
      const visibility = control?.querySelector(`[data-${key}-visibility]`);
      const opacity = control?.querySelector(`[data-${key}-opacity]`);
      visibility?.addEventListener("change", () => {
        if (visibility.checked) overlay.addTo(map);
        else map.removeLayer(overlay);
        boundary.bringToFront();
        setPreviewState(element, key, "available", "");
      });
      opacity?.addEventListener("input", () => overlay.setOpacity(Number(opacity.value)));
      overlay.addTo(map);
    })
    .catch((error) => {
      if (key === "nlcd") {
        onIdentifyReady?.(null);
        setIdentifyMessage(element, { status: "unavailable", message: `NLCD identify unavailable: ${error.message}` });
      }
      setPreviewState(element, key, "error", `${sourceLabel} preview unavailable: ${error.message}`);
    });
};

export const fitMapToAoi = (map, boundary) => map.fitBounds(boundary.getBounds(), { padding: [28, 28], maxZoom: 16 });

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
  fitMapToAoi(map, layer);
  let nlcdIdentifyHandler = null;
  map.on("click", (event) => {
    if (nlcdIdentifyHandler) {
      nlcdIdentifyHandler(event);
      return;
    }
    setIdentifyMessage(element, previews.annual_nlcd?.status === "available"
      ? { status: "loading", message: "NLCD identify is still loading. Try the map again shortly." }
      : { status: "unavailable", message: "NLCD identify unavailable: no AOI-specific preview is attached." });
  });
  mountRasterPreview(element, map, layer, aoi, previews["3dep"], "3dep", "3DEP terrain", 200);
  mountRasterPreview(
    element,
    map,
    layer,
    aoi,
    previews.annual_nlcd,
    "nlcd",
    "NLCD",
    300,
    (handler) => { nlcdIdentifyHandler = handler; },
  );
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
