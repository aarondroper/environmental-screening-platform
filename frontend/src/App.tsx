import type { FeatureCollection } from "geojson";
import { useCallback, useEffect, useState } from "react";

import {
  fetchHealth,
  getFeatures,
  getScreening,
  submitScreening,
  type AoiGeometry,
  type Health,
  type Screening,
} from "./api";
import { DatasetsPanel } from "./components/DatasetsPanel";
import { ScreeningForm } from "./components/ScreeningForm";
import { ScreeningResults } from "./components/ScreeningResults";
import { MapView } from "./MapView";

export const POLL_MS = 1000;

type HealthState = { kind: "loading" } | { kind: "loaded"; health: Health } | { kind: "error" };

export function SystemStatus() {
  const [state, setState] = useState<HealthState>({ kind: "loading" });

  useEffect(() => {
    const controller = new AbortController();
    fetchHealth(controller.signal)
      .then((health) => setState({ kind: "loaded", health }))
      .catch((error: unknown) => {
        if (!controller.signal.aborted) {
          console.error(error);
          setState({ kind: "error" });
        }
      });
    return () => controller.abort();
  }, []);

  if (state.kind === "loading") return <span className="status">Checking system…</span>;
  if (state.kind === "error" || state.health.status !== "ok") {
    return <span className="status status--down">System degraded</span>;
  }
  return (
    <span className="status status--ok" title={`PostGIS ${state.health.postgis_version}`}>
      System operational · v{state.health.version}
    </span>
  );
}

function screeningIdFromUrl(): string | null {
  return new URLSearchParams(window.location.search).get("screening");
}

function setScreeningIdInUrl(id: string | null) {
  const url = new URL(window.location.href);
  if (id) url.searchParams.set("screening", id);
  else url.searchParams.delete("screening");
  window.history.pushState(null, "", url);
}

interface Loaded {
  id: string;
  screening: Screening | null;
  features: FeatureCollection | null;
  error: string | null;
}

/** Loads a screening and polls it until it reaches a terminal state. */
function useScreening(id: string | null) {
  const [loaded, setLoaded] = useState<Loaded | null>(null);

  useEffect(() => {
    if (!id) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const update = (patch: Partial<Loaded>) =>
      setLoaded((prev) => ({
        ...(prev?.id === id ? prev : { id, screening: null, features: null, error: null }),
        ...patch,
      }));

    async function poll(screeningId: string) {
      try {
        const current = await getScreening(screeningId);
        if (cancelled) return;
        update({ screening: current });
        if (current.status === "queued" || current.status === "running") {
          timer = setTimeout(() => void poll(screeningId), POLL_MS);
        } else if (current.results.some((r) => r.dataset_id === "ssurgo" && r.metrics)) {
          const collection = await getFeatures(screeningId, "ssurgo");
          if (!cancelled) update({ features: collection });
        }
      } catch (e) {
        if (!cancelled) update({ error: e instanceof Error ? e.message : String(e) });
      }
    }
    void poll(id);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [id]);

  // Ignore state that belongs to a previously viewed screening.
  const current = loaded && loaded.id === id ? loaded : null;
  return {
    screening: current?.screening ?? null,
    features: current?.features ?? null,
    error: current?.error ?? null,
  };
}

type Tab = "screening" | "data";

export function App() {
  const [tab, setTab] = useState<Tab>("screening");
  const [screeningId, setScreeningId] = useState<string | null>(screeningIdFromUrl);
  const [draftAoi, setDraftAoi] = useState<AoiGeometry | null>(null);
  const [drawing, setDrawing] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const { screening, features, error: loadError } = useScreening(screeningId);

  useEffect(() => {
    const onPop = () => setScreeningId(screeningIdFromUrl());
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  const handleDrawn = useCallback((geometry: AoiGeometry) => {
    setDraftAoi(geometry);
    setDrawing(false);
  }, []);

  async function handleSubmit(name: string, aoi: AoiGeometry) {
    setSubmitting(true);
    setSubmitError(null);
    try {
      const created = await submitScreening(name, aoi);
      setScreeningId(created.id);
      setScreeningIdInUrl(created.id);
      setDraftAoi(null);
    } catch (e) {
      setSubmitError(e instanceof Error ? e.message : String(e));
    } finally {
      setSubmitting(false);
    }
  }

  function startNew() {
    setScreeningId(null);
    setScreeningIdInUrl(null);
  }

  const mapAoi = screeningId ? (screening?.aoi ?? null) : draftAoi;

  return (
    <div className="app">
      <header className="topbar">
        <h1>Environmental Screening Platform</h1>
        <SystemStatus />
      </header>
      <aside className="panel">
        <nav className="tabs" role="tablist">
          <button role="tab" aria-selected={tab === "screening"} onClick={() => setTab("screening")}>
            Screening
          </button>
          <button role="tab" aria-selected={tab === "data"} onClick={() => setTab("data")}>
            Data sources
          </button>
        </nav>
        {tab === "data" ? (
          <DatasetsPanel />
        ) : screeningId ? (
          <>
            <div className="panel-section panel-section--compact">
              <button type="button" className="button button--link" onClick={startNew}>
                ← New screening
              </button>
            </div>
            {loadError && (
              <p className="error panel-section" role="alert">
                Could not load screening: {loadError}
              </p>
            )}
            {screening && <ScreeningResults screening={screening} />}
          </>
        ) : (
          <ScreeningForm
            aoi={draftAoi}
            drawing={drawing}
            submitting={submitting}
            error={submitError}
            onAoi={setDraftAoi}
            onDrawingChange={setDrawing}
            onSubmit={handleSubmit}
          />
        )}
      </aside>
      <main className="workspace">
        <MapView
          aoi={mapAoi}
          features={screeningId ? features : null}
          drawing={drawing && !screeningId}
          onDrawn={handleDrawn}
        />
      </main>
    </div>
  );
}
