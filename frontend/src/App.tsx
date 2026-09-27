import { useEffect, useState } from "react";

import { fetchHealth, type Health } from "./api";
import { MapView } from "./MapView";

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

export function App() {
  return (
    <div className="app">
      <header className="topbar">
        <h1>Environmental Screening Platform</h1>
        <SystemStatus />
      </header>
      <main className="workspace">
        <MapView />
      </main>
    </div>
  );
}
