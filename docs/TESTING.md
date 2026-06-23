# Testing

Beckham Share is tested in three layers, each catching a different class of bug.
The guiding rule: *"pages return 200" is not "the feature works"* — a feature is
not done until its real behavior (UI included) is exercised by an automated test.

| Layer | Tool | Runs where | Catches |
|---|---|---|---|
| Backend integration | pytest | container / CI | routes, business logic, auth gate, abuse controls |
| Browser end-to-end | Playwright | Playwright image / CI | real rendering, buttons, JS — the component layer |
| Live smoke + config | shell | the host, post-deploy | TLS, routing, a real round-trip, Authentik provider config |

```
tests/
  backend/      pytest integration tests (TestClient)
  e2e/          Playwright browser tests
scripts/
  run-tests.sh  backend suite against a throwaway Postgres db
  run-e2e.sh    browser suite against a throwaway local instance
  smoke.sh      post-deploy checks against the live deployment
.github/workflows/ci.yml   runs the backend + e2e layers on every push / PR
```

## 1. Backend integration tests (`tests/backend`)

**Covers:** anonymous + member uploads, UUID share links, configurable expiry,
revoke, delete, the `dropbox`-group gate, the canonical-host redirect, and the
abuse controls (rate limit, size cap, audit trail).

**Run it:**
```sh
# On the host (uses a throwaway "testdb" inside the running db container):
sh scripts/run-tests.sh
# Anywhere with Postgres + Python:
pip install -r requirements-dev.txt
DATABASE_URL=postgresql+psycopg2://share:share@localhost:5432/testdb python -m pytest
```

**How it works:** `tests/backend/conftest.py` configures the app via environment
variables *before importing it* (settings are read at import time), then drives
it with Starlette's `TestClient` (in-process — no running server). Fixtures:
- `client` — a `TestClient` whose base URL is the canonical host, so the
  host-canonicalization redirect doesn't fire on every request.
- `member` / `nonmember` — monkeypatch `app.main.get_current_user` to simulate a
  logged-in user in / out of the `dropbox` group (auth is checked in-app, so this
  is the seam; no real OIDC round-trip needed).
- `_clean_tables` (autouse) wipes all rows after each test for isolation.

**Gotchas:**
- **Postgres, not SQLite.** The models use timezone-aware timestamps; SQLite
  drops the tz and breaks aware/naive comparisons. Tests run against Postgres to
  match production exactly (CI provides it as a service container).
- Abuse limits are intentionally tiny in the test env (`ANON_UPLOADS_PER_HOUR=3`,
  `ANON_MAX_UPLOAD_BYTES=2000`) so they are cheap to exercise — set in `conftest.py`.

## 2. Browser end-to-end tests (`tests/e2e`)

**Covers:** the public landing flow (hidden elements stay hidden on load; a file
upload yields a UUID link + working copy/email buttons) and the **share modal**
(hidden on load → opens on *Share* → closes on the X) — the exact regression that
once shipped as a stuck modal.

**Run it:**
```sh
# On the host — spins a throwaway local instance and runs the Playwright image:
sh scripts/run-e2e.sh
```
In CI the app is run with `uvicorn` and Playwright/Chromium is installed directly.

**How it works:**
- `scripts/run-e2e.sh` creates a throwaway `e2edb`, starts a one-off app container
  on a published port with a known `SECRET_KEY`, then runs the official Playwright
  image against it. No local browser install required.
- The public landing tests (`test_landing.py`) need no auth.
- The workspace test (`test_workspace.py`) needs a logged-in session without a real
  OIDC round-trip, so it **forges the Starlette session cookie**: it signs
  `{"user": {...}}` with the app's `SECRET_KEY` using `itsdangerous` (the same
  signer Starlette uses) and injects it as the `session` cookie. The app reads it
  on the next request as a `dropbox` member. This is why the runner uses a known
  secret and why the test is skipped unless `E2E_SECRET` is set.

**Gotchas:**
- **Pin Playwright to the image tag.** `pytest-playwright` otherwise pulls the
  latest Playwright, whose browser build won't exist in the pinned image
  (`Executable doesn't exist ...`). `requirements-e2e.txt` pins `playwright` to
  match `PLAYWRIGHT_IMAGE` in `run-e2e.sh`; bump both together.
- `itsdangerous` must be present in the E2E environment (it's listed in
  `requirements-e2e.txt`) — it's what forges the session cookie.
- The forged-cookie host must equal the base-URL host (cookie `domain`), so point
  E2E at the local instance, not the live site, for workspace tests.
- Pointing the **landing** tests at the live site works but creates real anonymous
  uploads (rate-limited 5/hr) — prefer the local instance.
- `tests/backend` and `tests/e2e` are split so each runs with only its own deps;
  `pytest.ini` defaults to `tests/backend`, and the e2e suite is invoked by path.

## 3. Live smoke + config check (`scripts/smoke.sh`)

Run on the host **after every deploy**. Verifies what integration tests can't:

- `/healthz` on `share`, `dropbox`, and `buckets`;
- a real anonymous **upload → share page → download** round-trip (byte-exact);
- the canonical redirect (`dropbox/app` → `share`);
- a valid Let's Encrypt certificate;
- the **Authentik provider configuration** — that `grant_types` includes
  `authorization_code` and the `share` callback is registered. (An empty
  `grant_types` is exactly what once broke sign-in; this check guards it.)

```sh
sh scripts/smoke.sh   # exits non-zero on the first failure
```

## Continuous integration

`.github/workflows/ci.yml` runs on every push and pull request:
- **backend** — Postgres service + `python -m pytest`;
- **e2e** — Postgres service, `playwright install chromium`, app via `uvicorn`,
  then `python -m pytest tests/e2e`.

## Adding tests

- New route / rule → add to `tests/backend` (fast, deterministic).
- New button / component / page interaction → add to `tests/e2e` so the rendered
  behavior is covered, not just the endpoint.
- New deploy-time invariant (a hostname, a provider setting) → add to `smoke.sh`.
