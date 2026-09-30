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

# .gitattributes declares `* text=auto eol=lf`, so the repository and any fresh
# checkout use LF. This ships the WORKING TREE with tar, which that never
# touches, and a shell script carrying CRLF fails on the host with
# "set: Illegal option -" because dash reads the carriage return as part of the
# option. Cheap to check, thoroughly confusing to debug. Learned by doing it:
# an editor wrote CRLF into scripts/smoke.sh and broke it on the host.
#
# Three things here are deliberate, each of which took a wrong version first:
#
#   * `tr`, not awk or grep. This script runs on the developer's machine, and
#     under Git Bash on Windows awk reads a CRLF file in text mode and strips the
#     carriage return before the program sees it: a file that `xxd` shows as
#     `0d 0a` arrives at awk as length 7 with no CR. Any awk or grep test passes
#     on every file and the guard silently never fires. `tr` reads the bytes.
#   * the octal escape rather than a literal carriage return, so this check
#     cannot match its own source file. The obvious spelling flags itself.
#   * the test inside `if`, not after `&&`. A false `&&` as the last statement in
#     a loop body exits non-zero, which `set -e` turns into a silent failure of
#     the whole script before it prints anything.
crlf=""
for candidate in $(find . -name '*.sh' -not -path './.git/*'); do
  if [ "$(tr -cd '\015' < "$candidate" | wc -c | tr -d ' ')" -gt 0 ]; then
    crlf="${crlf}  ${candidate}
"
  fi
done
if [ -n "$crlf" ]; then
  echo "ERROR: these shell scripts have CRLF line endings and would fail on the host:" >&2
  printf '%s' "$crlf" >&2
  echo "Fix with: git checkout -- <file>" >&2
  exit 1
fi

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
