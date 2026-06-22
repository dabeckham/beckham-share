#!/usr/bin/env sh
# Ship this project to the host and (re)build/start the stack.
# Run from anywhere; uses tar|ssh (rsync is often missing on Windows git-bash).
# Secrets stay on the host: .env and secrets/ are never synced.
#
# Host connection details come from scripts/deploy.env (gitignored) if present,
# or from the SHARE_HOST / SHARE_SSH_KEY / SHARE_DEST environment variables.
set -eu

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

[ -f scripts/deploy.env ] && . ./scripts/deploy.env

HOST="${SHARE_HOST:?set SHARE_HOST (e.g. user@host) in scripts/deploy.env}"
KEY="${SHARE_SSH_KEY:-$HOME/.ssh/id_ed25519}"
DEST="${SHARE_DEST:-/opt/beckham-share}"
SSH="ssh -i ${KEY} -o StrictHostKeyChecking=no"

echo ">> Shipping ${ROOT} -> ${HOST}:${DEST}"
$SSH "$HOST" "mkdir -p '${DEST}'"
tar czf - \
  --exclude=.git --exclude=.env --exclude=secrets --exclude=data \
  --exclude=__pycache__ --exclude='*.pyc' . \
  | $SSH "$HOST" "tar xzf - -C '${DEST}'"

echo ">> Building + starting on host"
$SSH "$HOST" "set -eu; cd '${DEST}'; \
  [ -f .env ] || sh scripts/generate-secrets.sh; \
  docker compose up -d --build; \
  docker compose ps"

echo ">> Done."
