import { useEffect, useState } from "react";

import { listDatasets, type DatasetSummary } from "../api";
import { formatDateTime } from "../format";

export function DatasetsPanel() {
  const [datasets, setDatasets] = useState<DatasetSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    listDatasets()
      .then(setDatasets)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)));
  }, []);

  if (error) return <p className="error panel-section">Could not load datasets: {error}</p>;
  if (!datasets) return <p className="panel-section hint">Loading datasets…</p>;
  if (datasets.length === 0) {
    return <p className="panel-section hint">No datasets have been ingested yet.</p>;
  }
  return (
    <section className="panel-section" aria-label="Data sources">
      <h2>Data sources</h2>
      {datasets.map((d) => (
        <article key={d.id} className="dataset-card">
          <header>
            <h3>
              <a href={d.homepage} target="_blank" rel="noreferrer">
                {d.title}
              </a>
            </h3>
            <span className="coverage">
              {d.provider} · {d.license}
            </span>
          </header>
          <dl className="facts">
            <dt>Active version</dt>
            <dd className="mono">{d.active_version ? d.active_version.id.slice(0, 8) : "none"}</dd>
            {d.active_version?.activated_at && (
              <>
                <dt>Activated</dt>
                <dd>{formatDateTime(d.active_version.activated_at)}</dd>
              </>
            )}
            {d.active_version && (
              <>
                <dt>Provider release</dt>
                <dd>
                  {Object.entries(d.active_version.provider_release)
                    .map(([area, release]) => `${area} ${release.slice(0, 10)}`)
                    .join(", ")}
                </dd>
              </>
            )}
            {d.last_run && (
              <>
                <dt>Last ingestion</dt>
                <dd>
                  <span className={`pill pill--run-${d.last_run.status}`}>{d.last_run.status}</span>{" "}
                  {formatDateTime(d.last_run.started_at)}
                </dd>
              </>
            )}
          </dl>
          {d.last_run?.error && <p className="error">{d.last_run.error}</p>}
        </article>
      ))}
    </section>
  );
}
