# Architecture

Beckham Share is a small FastAPI service backed by PostgreSQL, fronted by the
host's shared reverse-proxy and identity infrastructure. This document describes
the moving parts, the request flows, and the data model.

## 1. Components

```
                         https://share.beckham.ai
                         https://dropbox.beckham.ai   (redirect → share)
                         https://buckets.beckham.ai   (redirect → share)
                                     │
                                     ▼
        ┌─────────────────────────────────────────────────────┐
        │  HAProxy  (public :443, SNI routing, PROXY protocol)  │
        └─────────────────────────────────────────────────────┘
                                     │  real client IP preserved
                                     ▼
        ┌─────────────────────────────────────────────────────┐
        │  idp-caddy  (shared Caddy front; issues TLS certs)    │
        └─────────────────────────────────────────────────────┘
                                     │  reverse_proxy
                                     ▼
   ┌───────────────────────────────────────────────────────────────┐
   │  beckham-share-app : 8000   (FastAPI / Uvicorn, this repo)      │
   │                                                                 │
   │   routes ── auth (OIDC) ── storage ── fingerprint ── ratelimit  │
   └───────────────────────────────────────────────────────────────┘
            │                                   │
            │ SQLAlchemy                        │ file blobs
            ▼                                   ▼
   ┌──────────────────┐               ┌────────────────────────┐
   │ PostgreSQL (db)  │               │ share-data volume       │
   │ metadata + audit │               │ {data_dir}/blobs/<uuid> │
   └──────────────────┘               └────────────────────────┘

   Authentication:  app ──OIDC (Authorization Code)──▶ Authentik (auth.beckham.ai)
   Email (members): app ──SMTP STARTTLS──▶ relay (mail.eigbox.net)
```

Two containers are defined in [`docker-compose.yml`](../docker-compose.yml) under
the project name `beckham-share`:

- **app** — the FastAPI application. Renders the UI, handles uploads, share
  links, downloads, the OIDC login flow, and the audit trail.
- **db** — PostgreSQL 16, holding file/link metadata and the upload-event audit
  log. It stays on a private Docker network with no host port exposure.

The app attaches to two networks: the **external `idp_proxy`** network (created
by the `idp` project) so the shared `idp-caddy` front can route to it, and an
**internal** network shared only with the database.

### Application modules

| Module | Responsibility |
|---|---|
| [`app/main.py`](../app/main.py) | FastAPI app, HTTP routes, request orchestration. |
| [`app/config.py`](../app/config.py) | Typed settings loaded from the environment (`pydantic-settings`). |
| [`app/db.py`](../app/db.py) | Engine, session factory, `Base`, table creation. |
| [`app/models.py`](../app/models.py) | ORM models: `File`, `ShareLink`, `UploadEvent`. |
| [`app/auth.py`](../app/auth.py) | OIDC client, session user, group-membership check. |
| [`app/storage.py`](../app/storage.py) | Streaming blob storage on the local volume. |
| [`app/fingerprint.py`](../app/fingerprint.py) | Client IP, UA parsing, fingerprint hashing. |
| [`app/ratelimit.py`](../app/ratelimit.py) | Rolling-window anonymous-upload limits. |
| [`app/emailer.py`](../app/emailer.py) | Server-side "email this link" over SMTP. |
| `app/templates/`, `app/static/` | Jinja2 templates and the front-end assets. |

## 2. Access tiers

Every route falls into one of three tiers (see [API reference](API.md) for the
full list):

1. **Public, anonymous** — the landing page (`/`), the anonymous upload endpoint
   (`/api/anon-upload`), and the public share/download routes (`/s/{token}`,
   `/d/{token}`). No account required; constrained by the abuse controls.
2. **Authenticated member** — the workspace (`/app`) and the file-management API
   (`/api/files`, expiry/revoke/delete, server-side email). Requires a valid
   OIDC session **and** membership in the `dropbox` group.
3. **Infrastructure** — `/healthz`, used by the container health check and smoke
   tests.

## 3. Request flows

### Anonymous upload (the first-order feature)

```
Browser                      app                         db / disk
  │  POST /api/anon-upload     │                            │
  │  (multipart: file, fp)     │                            │
  │ ─────────────────────────▶ │                            │
  │                            │ compute fingerprint        │
  │                            │ check_anonymous() ─────────▶ count recent events
  │                            │ (429 if over budget)       │
  │                            │ stream to {data}/blobs/id ─▶ blob written, sha256
  │                            │ insert File + ShareLink ──▶ rows committed
  │                            │ record UploadEvent ───────▶ audit row
  │ ◀───────────────────────── │                            │
  │  { token, share_url, ... } │                            │
```

The response carries a `share_url` of the form `BASE_URL/s/<uuid>`. The original
filename is **not** in the URL — it is stored in the database and restored only
in the download's `Content-Disposition` header.

### Member sign-in (OIDC Authorization Code)

```
/login ─▶ redirect to Authentik authorize endpoint
        ◀─ user authenticates, Authentik enforces the `dropbox` application binding
/auth/callback ─▶ exchange code for tokens, read userinfo (incl. `groups` claim)
              ─▶ store {sub, email, name, groups} in the signed session cookie
              ─▶ redirect to /app
```

`/app` re-checks the `groups` claim as an in-app backstop; non-members get a
403 "not authorized" page. Because the session cookie is bound to one host, the
auth routes always run on the canonical host (`BASE_URL`); requests arriving on
`dropbox.` or `buckets.` are redirected there first (`ensure_canonical_host`).

### Download

```
GET /d/{token} ─▶ look up ShareLink ─▶ 404 if missing/deleted, 410 if expired
              ─▶ increment download_count
              ─▶ FileResponse(blob, filename=original_name)
```

`/s/{token}` is the human-facing share page (file name, size, expiry, copy /
email actions); `/d/{token}` is the raw byte stream.

## 4. Data model

Three tables, defined in [`app/models.py`](../app/models.py):

### `files`
The uploaded blob and its metadata. The primary key is a UUID that **doubles as
the on-disk storage key** and is never exposed in a URL. A `NULL` `owner_sub`
marks an anonymous (landing-page) upload. `expires_at` is a hard expiry for the
blob itself (anonymous uploads always get one); `deleted` is a soft-delete flag.

### `share_links`
A UUID-addressed link to a file — the `token` is the only identifier that ever
appears in a URL. A link is considered expired (`is_expired`) when it is
`revoked`, past its `expires_at`, or has reached an optional `max_downloads`.
`download_count` is incremented on every successful download.

### `upload_events`
One row per upload attempt — the abuse-review audit trail. Captures `ip`,
`user_agent`, `accept_language`, a stable `fingerprint` hash plus the raw
`fingerprint_data` bundle, and a parsed UA breakdown (`ua_browser`, `ua_os`,
`ua_device`). The rate limiter counts these rows; see [Security](SECURITY.md).

```
files (1) ───< (N) share_links
   │
   └──────────< (N) upload_events
```

## 5. Hostnames and the canonical host

The service answers on three hostnames, but share links and the OIDC session
cookie are tied to a single canonical origin (`BASE_URL`,
`https://share.beckham.ai`). `dropbox.beckham.ai` and `buckets.beckham.ai`
resolve to the same app but redirect the authenticated flow (`/login`, `/app`,
`/auth/callback`) to the canonical host so the session cookie and redirect URIs
stay consistent. The Caddy snippet that performs the routing is
[`caddy/dropbox.beckham.ai.caddy`](../caddy/dropbox.beckham.ai.caddy).

## 6. Why these choices

- **App-side OIDC (not proxy `forward_auth`).** The app needs the `groups` claim
  and its own session to distinguish members from anonymous visitors on the same
  origin; doing auth in-app keeps the public landing page and the gated workspace
  under one service.
- **UUID storage keys.** Using the file UUID as both the URL token's backing
  record and the on-disk name means the real filename never touches a path or a
  URL — only the database and the download header.
- **Database-backed rate limiting.** Counting the audit rows that already exist
  means the limit holds across worker processes and restarts with no extra
  store. See [Security](SECURITY.md).
- **Streaming uploads with an early size cap.** Blobs are written in 1 MiB chunks
  and aborted (with cleanup) the moment they exceed the limit, so an oversized
  upload never has to be fully buffered.
