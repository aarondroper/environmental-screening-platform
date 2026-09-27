export interface Health {
  status: "ok" | "degraded";
  version: string;
  database: "ok" | "unavailable";
  postgis_version: string | null;
  schema_revision: string | null;
}

export async function fetchHealth(signal?: AbortSignal): Promise<Health> {
  const response = await fetch("/api/health", { signal });
  // 503 still carries a Health body describing what is down.
  if (!response.ok && response.status !== 503) {
    throw new Error(`Health check failed: HTTP ${response.status}`);
  }
  return (await response.json()) as Health;
}
