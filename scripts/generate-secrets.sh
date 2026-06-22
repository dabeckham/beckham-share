#!/usr/bin/env sh
# Create .env with random secrets on the host (run once). Idempotent: if .env
# already exists it is left untouched so secrets stay stable across deploys.
set -eu
cd "$(dirname "$0")/.."

if [ -f .env ]; then
  echo ".env already exists — leaving it untouched."
  exit 0
fi

SECRET_KEY=$(openssl rand -hex 32)
DB_PASSWORD=$(openssl rand -hex 16)

sed -e "s|^SECRET_KEY=.*|SECRET_KEY=${SECRET_KEY}|" \
    -e "s|^DB_PASSWORD=.*|DB_PASSWORD=${DB_PASSWORD}|" \
    .env.example > .env

chmod 600 .env
echo "Wrote .env (SECRET_KEY + DB_PASSWORD generated; OIDC fields still blank)."
