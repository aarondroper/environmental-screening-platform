import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";

import type { Screening } from "./api";
import { App } from "./App";

// MapLibre needs WebGL, which jsdom lacks; the map is exercised by the compose smoke test.
vi.mock("./MapView", () => ({ MapView: () => <div data-testid="map" /> }));

const HEALTH = {
  status: "ok",
  version: "0.1.0",
  database: "ok",
  postgis_version: "3.6.1",
  schema_revision: "0002",
};

function screening(overrides: Partial<Screening>): Screening {
  return {
    id: "3f6c1d2e-0000-4000-8000-000000000001",
    name: "Poudre River example",
    status: "queued",
    attempts: 0,
    error: null,
    created_at: "2026-09-27T10:00:00Z",
    started_at: null,
    finished_at: null,
    aoi_area_m2: 8_470_000,
    aoi: { type: "MultiPolygon", coordinates: [] },
    dataset_versions: { ssurgo: "ecfbb1f5-a29a-46fb-88f0-497986c1a474" },
    results: [],
    ...overrides,
  };
}

const SSURGO_RESULT = {
  dataset_id: "ssurgo",
  dataset_title: "SSURGO hydric soil rating",
  version_id: "ecfbb1f5-a29a-46fb-88f0-497986c1a474",
  status: "partial_coverage" as const,
  error: null,
  metrics: {
    aoi_area_m2: 8_470_000,
    covered_area_m2: 6_776_000,
    covered_pct: 80,
    classes: [
      { class: "hydric_66_99", label: "66–99% hydric components", area_m2: 34_700, pct_of_aoi: 0.41, mapunits: 1 },
      { class: "hydric_1_32", label: "1–32% hydric components", area_m2: 4_759_000, pct_of_aoi: 56.19, mapunits: 9 },
      { class: "hydric_0", label: "Less than 1% hydric components", area_m2: 0, pct_of_aoi: 0, mapunits: 0 },
    ],
  },
};

type Route = (init?: RequestInit) => { status?: number; body: unknown };

function mockApi(routes: Record<string, Route | Route[]>) {
  const calls: { url: string; init?: RequestInit }[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      calls.push({ url, init });
      const key = `${init?.method ?? "GET"} ${url}`;
      const route = routes[key];
      if (!route) return new Response("not found", { status: 404 });
      const handler = Array.isArray(route) ? (route.length > 1 ? route.shift()! : route[0]) : route;
      const { status = 200, body } = handler(init);
      return new Response(JSON.stringify(body), { status });
    }),
  );
  return calls;
}

beforeEach(() => window.history.replaceState(null, "", "/"));
afterEach(() => vi.unstubAllGlobals());

test("shows operational status from the health endpoint", async () => {
  mockApi({ "GET /api/health": () => ({ body: HEALTH }) });

  render(<App />);

  expect(await screen.findByText(/System operational · v0.1.0/)).toBeInTheDocument();
});

test("shows degraded status when the database is unavailable", async () => {
  mockApi({
    "GET /api/health": () => ({ status: 503, body: { ...HEALTH, status: "degraded" } }),
  });

  render(<App />);

  expect(await screen.findByText("System degraded")).toBeInTheDocument();
});

test("submits an AOI, polls the job, and shows per-dataset results", async () => {
  const id = screening({}).id;
  const calls = mockApi({
    "GET /api/health": () => ({ body: HEALTH }),
    "POST /api/screenings": () => ({ status: 202, body: screening({}) }),
    [`GET /api/screenings/${id}`]: [
      () => ({ body: screening({ status: "running", attempts: 1 }) }),
      () => ({ body: screening({ status: "succeeded", attempts: 1, results: [SSURGO_RESULT] }) }),
    ],
    [`GET /api/screenings/${id}/features/ssurgo`]: () => ({
      body: { type: "FeatureCollection", features: [] },
    }),
  });

  render(<App />);
  fireEvent.click(screen.getByRole("button", { name: "Use example" }));
  fireEvent.click(screen.getByRole("button", { name: "Run screening" }));

  expect(await screen.findByRole("status")).toHaveTextContent("Processing");
  expect(await screen.findByText("Complete", {}, { timeout: 3000 })).toBeInTheDocument();

  const post = calls.find((c) => c.init?.method === "POST")!;
  const body = JSON.parse(String(post.init!.body));
  expect(body).toMatchObject({ name: "Poudre River example", geometry: { type: "Polygon" } });
  expect(new Headers(post.init!.headers).get("Idempotency-Key")).toBeTruthy();
  expect(window.location.search).toBe(`?screening=${id}`);

  const card = screen.getByRole("article", { name: "SSURGO hydric soil rating" });
  expect(card).toHaveTextContent("Dataset covers 80% of the AOI; the rest is not assessed");
  const rows = within(card).getAllByRole("row");
  expect(rows.map((r) => r.textContent)).toEqual([
    "Hydric ratingArea% of AOI",
    "66–99% hydric components3.5 ha0.4%",
    "1–32% hydric components475.9 ha56.2%",
  ]);
  expect(card).toHaveTextContent("Not a wetland delineation");
  await waitFor(() => expect(calls.some((c) => c.url.endsWith("/features/ssurgo"))).toBe(true));
});

test("shows the server's reason when an AOI is rejected", async () => {
  mockApi({
    "GET /api/health": () => ({ body: HEALTH }),
    "POST /api/screenings": () => ({
      status: 422,
      body: { detail: "AOI must lie within Colorado" },
    }),
  });

  render(<App />);
  fireEvent.click(screen.getByRole("button", { name: "Use example" }));
  fireEvent.click(screen.getByRole("button", { name: "Run screening" }));

  expect(await screen.findByRole("alert")).toHaveTextContent("AOI must lie within Colorado");
  expect(window.location.search).toBe("");
});

test("loads a shared screening from the URL", async () => {
  const done = screening({ status: "failed", attempts: 3, error: "database went away" });
  window.history.replaceState(null, "", `/?screening=${done.id}`);
  mockApi({
    "GET /api/health": () => ({ body: HEALTH }),
    [`GET /api/screenings/${done.id}`]: () => ({ body: done }),
  });

  render(<App />);

  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Screening failed after 3 attempts: database went away",
  );
});

test("reports an unreadable upload without submitting", async () => {
  const calls = mockApi({ "GET /api/health": () => ({ body: HEALTH }) });

  render(<App />);
  const file = new File(['{"type":"Point","coordinates":[0,0]}'], "aoi.geojson");
  fireEvent.change(screen.getByTestId("aoi-file"), { target: { files: [file] } });

  expect(await screen.findByRole("alert")).toHaveTextContent("No Polygon or MultiPolygon");
  expect(screen.getByRole("button", { name: "Run screening" })).toBeDisabled();
  expect(calls.every((c) => c.init?.method !== "POST")).toBe(true);
});

test("data sources tab lists the active version and last ingestion", async () => {
  mockApi({
    "GET /api/health": () => ({ body: HEALTH }),
    "GET /api/datasets": () => ({
      body: [
        {
          id: "ssurgo",
          title: "SSURGO hydric soil rating",
          provider: "USDA NRCS",
          license: "Public domain",
          homepage: "https://example.org",
          active_version: {
            id: "ecfbb1f5-a29a-46fb-88f0-497986c1a474",
            activated_at: "2026-09-27T10:15:58Z",
            provider_release: { CO644: "2025-08-29T16:38:56" },
            stats: { polygons: 12846 },
          },
          last_run: {
            id: "r1",
            status: "unchanged",
            started_at: "2026-09-27T11:00:00Z",
            finished_at: "2026-09-27T11:00:02Z",
            error: null,
          },
        },
      ],
    }),
  });

  render(<App />);
  fireEvent.click(screen.getByRole("tab", { name: "Data sources" }));

  const card = await screen.findByRole("article");
  expect(card).toHaveTextContent("ecfbb1f5");
  expect(card).toHaveTextContent("CO644 2025-08-29");
  expect(card).toHaveTextContent("unchanged");
});
