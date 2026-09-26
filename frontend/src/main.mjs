import { renderReport } from "./app.mjs";

const root = document.querySelector("#app");

fetch("demo/report.json")
  .then((response) => {
    if (!response.ok) throw new Error(`Report request failed (${response.status})`);
    return response.json();
  })
  .then((report) => {
    root.innerHTML = renderReport(report);
    document.title = `${report.project?.name || "Environmental Screening"} | Operations Console`;
  })
  .catch((error) => {
    root.innerHTML = `<section class="panel error"><h1>Report unavailable</h1><p>${error.message}</p><p>Serve the built console over HTTP so the report fixture can be loaded.</p></section>`;
  });
