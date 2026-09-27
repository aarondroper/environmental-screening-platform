import { render, screen } from "@testing-library/react";

import { App } from "./App";

// MapLibre needs WebGL, which jsdom lacks; the map is covered by the e2e smoke.
vi.mock("./MapView", () => ({ MapView: () => <div data-testid="map" /> }));

function mockHealth(status: number, body: object) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response(JSON.stringify(body), { status })),
  );
}

afterEach(() => vi.unstubAllGlobals());

test("shows operational status from the health endpoint", async () => {
  mockHealth(200, {
    status: "ok",
    version: "0.1.0",
    database: "ok",
    postgis_version: "3.5.3",
    schema_revision: "0001",
  });

  render(<App />);

  expect(await screen.findByText(/System operational · v0.1.0/)).toBeInTheDocument();
  expect(screen.getByTestId("map")).toBeInTheDocument();
});

test("shows degraded status when the database is unavailable", async () => {
  mockHealth(503, {
    status: "degraded",
    version: "0.1.0",
    database: "unavailable",
    postgis_version: null,
    schema_revision: null,
  });

  render(<App />);

  expect(await screen.findByText("System degraded")).toBeInTheDocument();
});

test("shows degraded status when the API is unreachable", async () => {
  vi.spyOn(console, "error").mockImplementation(() => {});
  vi.stubGlobal("fetch", vi.fn(async () => { throw new TypeError("network"); }));

  render(<App />);

  expect(await screen.findByText("System degraded")).toBeInTheDocument();
});
