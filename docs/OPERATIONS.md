# Operations

How to deploy Beckham Share and run it day to day. The service runs as two
containers (`app` + `db`) behind the host's shared Caddy/HAProxy front and signs
in against an existing Authentik identity provider.

Host-specific connection details (SSH target, destination path) live in
`scripts/deploy.env`, which is **gitignored**. `deploy.sh` reads it, or falls
back to the `SHARE_HOST` / `SHARE_SSH_KEY` / `SHARE_DEST` environment variables.

## Prerequisites

- A host running Docker with the shared `idp` stack already up: Authentik, the
  `idp-caddy` front, and the external `idp_proxy` Docker network.
- DNS for `share` / `dropbox` / `buckets.beckham.ai` pointing at the public IP
  (one-time, manual).
- An SMTP mailbox if server-side email is wanted (optional; the UI falls back to
  `mailto:` until it exists).

## First deploy

```sh
# 1. Ship the code, build the image, and start the stack on the host.
#    (tar | ssh; secrets and data are never synced. Generates .env on first run.)
sh scripts/deploy.sh

# 2. Configure Authentik: create the OIDC provider/application, the `dropbox`
#    group, and its members. Prints OIDC_CLIENT_ID / OIDC_CLIENT_SECRET.
docker compose -p idp exec -T authentik-server ak shell < scripts/setup-authentik.py

# 3. Put the printed OIDC_CLIENT_ID / OIDC_CLIENT_SECRET (and OIDC_DISCOVERY_URL)
#    into the host's .env, then restart the app.
docker compose up -d app

# 4. Wire the reverse proxy: add caddy/dropbox.beckham.ai.caddy to the shared
#    Caddyfile and reload Caddy.
docker compose -p idp exec caddy caddy reload --config /etc/caddy/Caddyfile

# 5. Verify.
sh scripts/smoke.sh
```

`scripts/generate-secrets.sh` writes a `.env` with a random `SECRET_KEY` and
`DB_PASSWORD` on first deploy; everything else has a sane default (see
[Configuration](CONFIGURATION.md)).

## Routine deploy (subsequent changes)

```sh
sh scripts/deploy.sh   # re-ships, rebuilds, restarts
sh scripts/smoke.sh    # confirm health, a real round-trip, TLS, provider config
```

`deploy.sh` ships the working tree with `tar | ssh` (no rsync dependency),
excluding `.git`, `.env`, `secrets/`, and `data/`, then runs
`docker compose up -d --build` on the host. Secrets and uploaded blobs stay on
the host across deploys (the `share-data` and `share-db` volumes persist).

## Day-two runbook

### Logs
```sh
# On the host, in the deploy directory:
docker compose logs -f app      # application log (uploads, auth, email)
docker compose logs db          # database
docker compose ps               # container status / health
```
The app logs each anonymous upload with its id, IP, fingerprint prefix, and size,
and warns on OIDC callback failures or email send failures.

### Health
`GET /healthz` returns `{ "status": "ok" }` and backs the container health check.
`scripts/smoke.sh` exercises health on all three hostnames plus a full
upload → share → download round-trip, the canonical redirect, the TLS
certificate, and the Authentik provider configuration.

### Backups
Two pieces of state to back up:
- **Database** — `docker compose exec db pg_dump -U share share > backup.sql`.
- **Blobs** — the `share-data` volume (`{DATA_DIR}/blobs/`). Back up the volume
  directory or `docker run --rm -v beckham-share_share-data:/data ...` to tar it.

A blob is only meaningful alongside its database row, so snapshot both together.

### Restart / recover
```sh
docker compose restart app          # restart just the app
docker compose up -d --force-recreate   # recreate both containers
```
On startup the app ensures the blob directory exists and creates any missing
tables (`init_db`), so a fresh container against the existing volumes comes back
clean.

### Rotating secrets
- `SECRET_KEY` — changing it invalidates all sessions (everyone re-logs in).
- OIDC client secret — rotate in Authentik, update `.env`, `docker compose up -d app`.
- SMTP password — update `.env`, restart the app.

## Authentik configuration

`scripts/setup-authentik.py` is idempotent — re-running it reconciles the
provider, application, group, members, the `groups` scope mapping, and the policy
binding. It configures three redirect URIs (the `share`, `dropbox`, and `buckets`
callbacks) and ensures the provider's grant types include `authorization_code`
and `refresh_token`.

> A historical sign-in outage was caused by an **empty `grant_types`** on the
> provider. The setup script sets them explicitly, and `smoke.sh` asserts that
> `authorization_code` is present and the `share` callback is registered, so the
> same failure can't ship silently again.

## Reverse proxy

`caddy/dropbox.beckham.ai.caddy` is a plain `reverse_proxy` to
`beckham-share-app:8000` — **authentication is in-app (OIDC), not Caddy
`forward_auth`.** Add the snippet to the shared Caddyfile and reload Caddy. TLS
certificates are issued and renewed automatically by Caddy.

## Common issues

| Symptom | Likely cause | Check |
|---|---|---|
| Sign-in returns `400` immediately | Provider misconfiguration (e.g. empty grant types) | `smoke.sh` provider check; re-run `setup-authentik.py`. |
| `503` on `/login` | OIDC not configured | `OIDC_*` set in `.env`? |
| Anonymous upload `429` | Rate limit hit | Expected; tune `ANON_UPLOADS_PER_*`. |
| Email returns `email_not_configured` | SMTP unset | Set `SMTP_*`; STARTTLS host mapping present. |
| Member sees "not authorized" | Not in the `dropbox` group | Group membership in Authentik; `groups` scope mapped. |
