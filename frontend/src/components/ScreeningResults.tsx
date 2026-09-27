import type { DatasetResult, Screening } from "../api";
import { formatDateTime, formatHa, formatPct } from "../format";
import { HYDRIC_COLORS, HYDRIC_NOTE } from "../hydric";

const JOB_LABELS: Record<Screening["status"], string> = {
  queued: "Queued",
  running: "Processing",
  succeeded: "Complete",
  failed: "Failed",
};

export function ScreeningResults({ screening }: { screening: Screening }) {
  const pending = screening.status === "queued" || screening.status === "running";
  return (
    <section className="panel-section" aria-label="Screening results">
      <div className="result-header">
        <h2>{screening.name}</h2>
        <span className={`pill pill--${screening.status}`} role="status">
          {pending && <span className="spinner" aria-hidden />}
          {JOB_LABELS[screening.status]}
        </span>
      </div>
      <dl className="facts">
        <dt>Area</dt>
        <dd>{formatHa(screening.aoi_area_m2)}</dd>
        <dt>Submitted</dt>
        <dd>{formatDateTime(screening.created_at)}</dd>
        <dt>Job</dt>
        <dd className="mono">{screening.id.slice(0, 8)}</dd>
      </dl>
      {screening.status === "failed" && (
        <p className="error" role="alert">
          Screening failed after {screening.attempts} attempts: {screening.error}
        </p>
      )}
      {screening.results.map((result) => (
        <DatasetCard key={result.dataset_id} result={result} />
      ))}
      <p className="disclaimer">
        Preliminary screening information from the dataset versions listed. Not a regulatory,
        legal, engineering, or wetland determination.
      </p>
    </section>
  );
}

function coverageText(result: DatasetResult): string {
  switch (result.status) {
    case "complete":
      return "Dataset covers the whole AOI";
    case "partial_coverage":
      return `Dataset covers ${formatPct(result.metrics?.covered_pct ?? 0)} of the AOI; the rest is not assessed`;
    case "not_covered":
      return "Dataset does not cover this AOI; not assessed";
    case "unavailable":
      return "No validated dataset version was available";
    case "failed":
      return `Could not be computed: ${result.error ?? "unknown error"}`;
  }
}

function DatasetCard({ result }: { result: DatasetResult }) {
  const classes = result.metrics?.classes.filter((c) => c.area_m2 > 0) ?? [];
  return (
    <article className="dataset-card" aria-label={result.dataset_title}>
      <header>
        <h3>{result.dataset_title}</h3>
        <span className={`coverage coverage--${result.status}`}>{coverageText(result)}</span>
      </header>
      {classes.length > 0 && (
        <table className="metrics">
          <thead>
            <tr>
              <th scope="col">Hydric rating</th>
              <th scope="col" className="num">Area</th>
              <th scope="col" className="num">% of AOI</th>
            </tr>
          </thead>
          <tbody>
            {classes.map((c) => (
              <tr key={c.class}>
                <td>
                  <span className="swatch" style={{ background: HYDRIC_COLORS[c.class] }} />
                  {c.label}
                </td>
                <td className="num">{formatHa(c.area_m2)}</td>
                <td className="num">{formatPct(c.pct_of_aoi)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {result.dataset_id === "ssurgo" && <p className="note">{HYDRIC_NOTE}</p>}
      {result.version_id && (
        <p className="provenance">
          Dataset version <span className="mono">{result.version_id.slice(0, 8)}</span>
        </p>
      )}
    </article>
  );
}
