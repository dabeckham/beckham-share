#!/usr/bin/env sh
# Run the backend test suite against a throwaway PostgreSQL database created in
# the running stack's db container. Run on the host from the project directory.
set -eu
cd "$(dirname "$0")/.."

DBPASS=$(grep '^DB_PASSWORD=' .env | cut -d= -f2-)

echo ">> (re)creating testdb"
docker compose exec -T db psql -U share -d share -c "DROP DATABASE IF EXISTS testdb;" >/dev/null
docker compose exec -T db psql -U share -d share -c "CREATE DATABASE testdb;" >/dev/null

echo ">> running pytest in a throwaway container"
set +e
docker compose run --rm --no-deps --user root -v "$(pwd):/srv" \
  -e DATABASE_URL="postgresql+psycopg2://share:${DBPASS}@db:5432/testdb" \
  app sh -c "pip install -q -r requirements-dev.txt && python -m pytest"
rc=$?
set -e

echo ">> dropping testdb"
docker compose exec -T db psql -U share -d share -c "DROP DATABASE IF EXISTS testdb;" >/dev/null
exit $rc
