import { renderReport, renderScreeningReport } from "./app.mjs";
import { mountAoiMap } from "./map.mjs";

const root = document.querySelector("#app");

fetch("demo/report.json")
  .then((response) => {
    if (!response.ok) throw new Error(`Report request failed (${response.status})`);
    return response.json();
  })
  .then((report) => {
    const searchParams = new URLSearchParams(window.location.search);
    const operations = searchParams.get("view") === "operations";
    const activeTab = searchParams.get("tab") || "results";
    root.classList.toggle("shell", operations);
    root.innerHTML = operations ? renderReport(report) : renderScreeningReport(report, activeTab);
    document.title = `${report.project?.name || "Environmental Screening"} | ${operations ? "Operations" : "Screening Report"}`;
    if (!operations) {
      try {
        const mountedMap = mountAoiMap(root.querySelector("[data-aoi-map]"), report.aoi, report.browser_previews || {});
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
    }
  })
  .catch((error) => {
    root.innerHTML = `<section class="panel error"><h1>Report unavailable</h1><p>${error.message}</p><p>Serve the built console over HTTP so the report fixture can be loaded.</p></section>`;
  });
