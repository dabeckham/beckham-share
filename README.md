# Beckham Share

A self-hosted file-sharing service for `beckham.ai`. Upload a file, get a
private link addressed by an opaque UUID, and share it with an expiry you
control. A public landing page lets unregistered visitors send a one-off file;
the full workspace is reserved for members of the `dropbox` group, authenticated
through the organization's Authentik identity provider.

Runs in containers on the internal host and is served at
**https://share.beckham.ai** (also reachable at `dropbox.beckham.ai` and
`buckets.beckham.ai`, which redirect the authenticated flow to the canonical host).

## Features

- **Upload &amp; share by link** — every share link is a random UUID; the original
  filename never appears in the URL (it is restored only in the download's
  `Content-Disposition`).
- **Configurable expiry** — per-link expiry (1 hour … 30 days, or never) with
  copy-to-clipboard and email-link actions. Links can be revoked at any time.
- **Public landing page** — unregistered visitors can upload a single file and
  receive a short-lived link, with no account.
- **Identity-gated workspace** — the authenticated interface is restricted to
  members of the `dropbox` group via Authentik (OIDC), enforced both at the IdP
  and in the app.
- **Abuse controls** — the public upload form is rate-limited per client, size
  capped, and every upload is recorded with its source IP, user agent, and a
  browser fingerprint for review.

## Architecture

```
                 https://share.beckham.ai
Browser ──▶ HAProxy (SNI, :443) ──▶ Caddy ──▶ beckham-share-app :8000
                                                              │
                                              PostgreSQL (private network)
                                              File blobs (local volume)

Authentication: app ──OIDC──▶ Authentik (auth.beckham.ai)
```

- **app** — FastAPI service (this repo). Renders the UI, handles uploads,
  share links, downloads, and the OIDC login flow.
- **db** — PostgreSQL for file/link metadata and the upload audit trail.
- **storage** — file blobs on a local volume, keyed by UUID.
- The app attaches to the existing `idp_proxy` Docker network so the shared
  Caddy front (`idp-caddy`) can route `dropbox.beckham.ai` to it. TLS is issued
  automatically by Caddy. See [`caddy/dropbox.beckham.ai.caddy`](caddy/dropbox.beckham.ai.caddy).

## Tech stack

Python 3.12 · FastAPI · SQLAlchemy · PostgreSQL · Jinja2 · Authlib (OIDC) ·
Docker Compose · Caddy · Authentik.

## Configuration

All configuration is via environment variables (see [`.env.example`](.env.example)).
`scripts/generate-secrets.sh` creates `.env` with random `SECRET_KEY` and
`DB_PASSWORD`; the OIDC client credentials are filled in after running the
Authentik setup. Notable settings:

| Variable | Purpose |
|---|---|
| `BASE_URL` | Public origin, used to build share links |
| `OIDC_DISCOVERY_URL` / `OIDC_CLIENT_ID` / `OIDC_CLIENT_SECRET` | Authentik OIDC provider |
| `REQUIRED_GROUP` | Group required for the workspace (default `dropbox`) |
| `ANON_MAX_UPLOAD_BYTES`, `ANON_UPLOADS_PER_HOUR`, `ANON_UPLOADS_PER_DAY` | Anonymous-upload limits |
| `SHARE_EXPIRY_OPTIONS_HOURS`, `DEFAULT_SHARE_EXPIRY_HOURS` | Expiry choices |
| `SMTP_*` | Optional server-side "Email link" (falls back to `mailto:` if unset) |

## Deployment

The host already runs Authentik and the shared Caddy front. To deploy:

```sh
# 1. Ensure DNS: share/dropbox/buckets.beckham.ai -> the public IP (one-time, manual).
# 2. Ship + build + start on the host:
sh scripts/deploy.sh

# 3. Configure Authentik (creates the group, members, OIDC app):
docker compose -p idp exec -T authentik-server ak shell < scripts/setup-authentik.py
#    Copy the printed OIDC_CLIENT_ID / OIDC_CLIENT_SECRET into .env, then:
docker compose up -d app

# 4. Add the Caddy route (caddy/dropbox.beckham.ai.caddy) to ~/idp/caddy/Caddyfile
#    and reload idp-caddy.
```

## Local development

```sh
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
# Point DATABASE_URL at a local Postgres (or run the compose db service).
uvicorn app.main:app --reload
```

The landing page, uploads, share pages, and downloads work without OIDC
configured; only the `/app` workspace requires Authentik.

## Testing

Three layers — backend integration (pytest), browser end-to-end (Playwright),
and a live smoke + configuration check — run in CI on every push and pull
request. Full details in [docs/TESTING.md](docs/TESTING.md).

```sh
sh scripts/run-tests.sh   # backend integration tests (throwaway Postgres db)
sh scripts/run-e2e.sh     # browser end-to-end tests (throwaway local instance)
sh scripts/smoke.sh       # post-deploy checks against the live deployment
```

## Project layout

```
app/            FastAPI application (routes, models, auth, storage, templates, static)
caddy/          reverse-proxy route snippet for the shared Caddy front
scripts/        deploy, secret generation, Authentik setup
docs/           project notes
```
