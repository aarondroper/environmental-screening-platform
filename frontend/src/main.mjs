import { renderReport, renderScreeningReport } from "./app.mjs";

const root = document.querySelector("#app");

fetch("demo/report.json")
  .then((response) => {
    if (!response.ok) throw new Error(`Report request failed (${response.status})`);
    return response.json();
  })
  .then((report) => {
    const operations = new URLSearchParams(window.location.search).get("view") === "operations";
    root.innerHTML = operations ? renderReport(report) : renderScreeningReport(report);
    document.title = `${report.project?.name || "Environmental Screening"} | ${operations ? "Operations" : "Screening Report"}`;
  })
  .catch((error) => {
    root.innerHTML = `<section class="panel error"><h1>Report unavailable</h1><p>${error.message}</p><p>Serve the built console over HTTP so the report fixture can be loaded.</p></section>`;
  });
