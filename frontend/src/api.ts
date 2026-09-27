import type { FeatureCollection, MultiPolygon, Polygon } from "geojson";

export interface Health {
  status: "ok" | "degraded";
  version: string;
  database: "ok" | "unavailable";
  postgis_version: string | null;
  schema_revision: string | null;
}

export type AoiGeometry = Polygon | MultiPolygon;

export type JobStatus = "queued" | "running" | "succeeded" | "failed";
export type ResultStatus =
  | "complete"
  | "partial_coverage"
  | "not_covered"
  | "unavailable"
  | "failed";

export interface ClassMetric {
  class: string;
  label: string;
  area_m2: number;
  pct_of_aoi: number;
  mapunits: number;
}

export interface DatasetResult {
  dataset_id: string;
  dataset_title: string;
  version_id: string | null;
  status: ResultStatus;
  metrics: {
    aoi_area_m2: number;
    covered_area_m2: number;
    covered_pct: number;
    classes: ClassMetric[];
  } | null;
  error: string | null;
}

export interface Screening {
  id: string;
  name: string;
  status: JobStatus;
  attempts: number;
  error: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  aoi_area_m2: number;
  aoi: MultiPolygon;
  dataset_versions: Record<string, string>;
  results: DatasetResult[];
}

export interface DatasetSummary {
  id: string;
  title: string;
  provider: string;
  license: string;
  homepage: string;
  active_version: {
    id: string;
    activated_at: string | null;
    provider_release: Record<string, string>;
    stats: Record<string, unknown> | null;
  } | null;
  last_run: {
    id: string;
    status: string;
    started_at: string;
    finished_at: string | null;
    error: string | null;
  } | null;
}

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  if (!response.ok) {
    let message = `HTTP ${response.status}`;
    try {
      const body = (await response.json()) as { detail?: unknown };
      if (typeof body.detail === "string") message = body.detail;
      else if (Array.isArray(body.detail)) message = "The AOI must be a GeoJSON Polygon or MultiPolygon.";
    } catch {
      // Non-JSON error body: keep the status message.
    }
    throw new ApiError(response.status, message);
  }
  return (await response.json()) as T;
}

export async function fetchHealth(signal?: AbortSignal): Promise<Health> {
  const response = await fetch("/api/health", { signal });
  // 503 still carries a Health body describing what is down.
  if (!response.ok && response.status !== 503) {
    throw new Error(`Health check failed: HTTP ${response.status}`);
  }
  return (await response.json()) as Health;
}

export function submitScreening(name: string, geometry: AoiGeometry): Promise<Screening> {
  return request<Screening>("/api/screenings", {
    method: "POST",
    body: JSON.stringify({ name, geometry }),
    headers: { "Idempotency-Key": crypto.randomUUID() },
  });
}

export function getScreening(id: string, signal?: AbortSignal): Promise<Screening> {
  return request<Screening>(`/api/screenings/${id}`, { signal });
}

export function getFeatures(id: string, datasetId: string): Promise<FeatureCollection> {
  return request<FeatureCollection>(`/api/screenings/${id}/features/${datasetId}`);
}

export function listDatasets(): Promise<DatasetSummary[]> {
  return request<DatasetSummary[]>("/api/datasets");
}
