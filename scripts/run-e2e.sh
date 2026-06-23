#!/usr/bin/env sh
# Browser E2E against a throwaway LOCAL instance (so the workspace modal test can
# use a forged session). Run on the host from the project directory. Uses the
# official Playwright image — no local browser install needed.
set -eu
cd "$(dirname "$0")/.."

PORT="${E2E_PORT:-8099}"
SECRET="e2e-secret-$(date +%s)"
DBPASS=$(grep '^DB_PASSWORD=' .env | cut -d= -f2-)
PWIMG="${PLAYWRIGHT_IMAGE:-mcr.microsoft.com/playwright/python:v1.49.0-noble}"
NET=$(docker inspect beckham-share-db -f '{{range $k,$v := .NetworkSettings.Networks}}{{$k}} {{end}}' | tr ' ' '\n' | grep internal | head -1)

cleanup() {
  docker rm -f bshare-e2e >/dev/null 2>&1 || true
  docker compose exec -T db psql -U share -d share -c "DROP DATABASE IF EXISTS e2edb;" >/dev/null 2>&1 || true
}
trap cleanup EXIT
cleanup

echo ">> creating e2edb + starting app on :$PORT"
docker compose exec -T db psql -U share -d share -c "CREATE DATABASE e2edb;" >/dev/null
docker run -d --name bshare-e2e --network "$NET" -p "$PORT:8000" \
  -e DATABASE_URL="postgresql+psycopg2://share:${DBPASS}@db:5432/e2edb" \
  -e SECRET_KEY="$SECRET" -e BASE_URL="http://localhost:$PORT" \
  beckham-share:latest >/dev/null
for _ in $(seq 1 30); do curl -sf "http://localhost:$PORT/healthz" >/dev/null 2>&1 && break; sleep 1; done

echo ">> running playwright suite"
docker run --rm --network host -v "$(pwd):/work" -w /work \
  -e E2E_BASE="http://localhost:$PORT" -e E2E_SECRET="$SECRET" \
  "$PWIMG" sh -c "pip install -q -r requirements-e2e.txt && python -m pytest tests/e2e"
