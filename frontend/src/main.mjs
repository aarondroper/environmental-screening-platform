import { renderReport, renderScreeningReport } from "./app.mjs";
import { createAoiContext, rebindReportToAoi } from "./aoi-input.mjs";
import { mountAoiMap } from "./map.mjs";

const root = document.querySelector("#app");
let recordedReport;
let activeReport;
let mountedMap;

const currentView = () => {
  const searchParams = new URLSearchParams(window.location.search);
  return { operations: searchParams.get("view") === "operations", tab: searchParams.get("tab") || "results" };
};

const setAoiError = (message) => {
  const error = root.querySelector("[data-aoi-error]");
  if (!error) return;
  error.textContent = message;
  error.hidden = !message;
};

const mountPrimaryMap = () => {
  try {
    mountedMap = mountAoiMap(root.querySelector("[data-aoi-map]"), activeReport.aoi, activeReport.browser_previews || {});
    const visibility = root.querySelector("[data-aoi-visibility]");
    visibility?.addEventListener("change", () => {
      if (visibility.checked) mountedMap.layer.addTo(mountedMap.map);
      else mountedMap.map.removeLayer(mountedMap.layer);
    });
  } catch (error) {
    const status = root.querySelector("[data-map-status]");
    if (status) {
      status.className = "map-state map-state-error";
      status.textContent = `AOI map unavailable: ${error.message}`;
      status.hidden = false;
    }
  }
};

const readAoiInput = async () => {
  const file = root.querySelector("[data-aoi-file]")?.files?.[0];
  const pasted = root.querySelector("[data-aoi-paste]")?.value.trim();
  if (file && pasted) throw new Error("Choose a GeoJSON file or paste GeoJSON, not both");
  if (file) return file.text();
  if (pasted) return pasted;
  throw new Error("Choose a GeoJSON file or paste GeoJSON before loading");
};

const wireAoiLoader = () => {
  const apply = root.querySelector("[data-aoi-apply]");
  apply?.addEventListener("click", async () => {
    setAoiError("");
    apply.disabled = true;
    try {
      const context = await createAoiContext(await readAoiInput());
      activeReport = rebindReportToAoi(recordedReport, context);
      render();
    } catch (error) {
      setAoiError(error.message);
    } finally {
      apply.disabled = false;
    }
  });
  root.querySelector("[data-aoi-reset]")?.addEventListener("click", () => {
    activeReport = recordedReport;
    render();
  });
};

const render = () => {
  mountedMap?.map.remove();
  mountedMap = undefined;
  const { operations, tab } = currentView();
  root.classList.toggle("shell", operations);
  root.innerHTML = operations ? renderReport(activeReport) : renderScreeningReport(activeReport, tab);
  document.title = `${activeReport.project?.name || "Environmental Screening"} | ${operations ? "Operations" : "Screening"}`;
  if (!operations) {
    mountPrimaryMap();
    wireAoiLoader();
  }
};

fetch("demo/report.json")
  .then((response) => {
    if (!response.ok) throw new Error(`Report request failed (${response.status})`);
    return response.json();
  })
  .then((report) => {
    recordedReport = report;
    activeReport = report;
    render();
  })
  .catch((error) => {
    root.innerHTML = `<section class="panel error"><h1>Report unavailable</h1><p>${error.message}</p><p>Serve the built console over HTTP so the report fixture can be loaded.</p></section>`;
  });
