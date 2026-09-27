#!/usr/bin/env bash
# End-to-end smoke test against a running `docker compose` stack:
# health → ingest the SSURGO fixture → submit a screening via the web proxy →
# worker processes it → results and features are served.
set -euo pipefail

BASE="${BASE_URL:-http://localhost:${WEB_PORT:-8090}}"
cd "$(dirname "$0")/.."

# Evaluate a Python expression against JSON on stdin (bound to `d`); fail if falsy.
check() { python3 -c "import json,sys; d=json.load(sys.stdin); v=$1; print(v); sys.exit(0 if v else 1)"; }

echo "== waiting for $BASE/api/health"
for _ in $(seq 60); do
  health=$(curl -fsS "$BASE/api/health" 2>/dev/null) && break
  sleep 3
done
echo "$health" | check 'd["status"] == "ok" and d["database"] == "ok"'

echo "== frontend is served"
curl -fsS "$BASE/" | grep -q '<div id="root">'

echo "== ingest SSURGO fixture inside the stack"
docker compose run --rm -T -v "$PWD/backend/tests/fixtures/ssurgo:/fixtures:ro" api \
  esp ingest ssurgo --areas CO644 --package-dir /fixtures | tail -1

echo "== submit screening"
job=$(curl -fsS -X POST "$BASE/api/screenings" -H 'Content-Type: application/json' -d '{
  "name": "Smoke test",
  "geometry": {"type": "Polygon", "coordinates": [[[-105.075, 40.575], [-105.0405, 40.575],
    [-105.0405, 40.597], [-105.075, 40.597], [-105.075, 40.575]]]}}' | check 'd["id"]')

for _ in $(seq 30); do
  result=$(curl -fsS "$BASE/api/screenings/$job")
  echo "$result" | check 'd["status"] not in ("queued", "running")' > /dev/null && break
  sleep 1
done
echo "$result" | check '[(r["dataset_id"], r["status"], r["metrics"]["covered_pct"]) for r in d["results"]]'
echo "$result" | check 'd["status"] == "succeeded" and any(r["dataset_id"] == "ssurgo" and r["status"] == "complete" for r in d["results"])'

echo "== features"
curl -fsS "$BASE/api/screenings/$job/features/ssurgo" | check 'len(d["features"])'
echo "smoke test passed"
