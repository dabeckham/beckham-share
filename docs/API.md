# API reference

Every HTTP route exposed by the application, grouped by access tier. Routes are
defined in [`app/main.py`](../app/main.py). The interactive OpenAPI docs
(`/docs`, `/redoc`) are intentionally disabled.

Auth tiers:

- **Public** — no authentication.
- **Member** — requires a valid OIDC session **and** membership in the
  `REQUIRED_GROUP` (`dropbox`). Otherwise `403`.
- **Infra** — health/operational endpoints.

## Public — pages

### `GET /`
The landing page. If the request already has a valid member session, redirects to
`/app` (302). Otherwise renders the public upload page.

### `GET /s/{token}`
Human-facing share page for a link: filename, size, expiry, and copy / email
actions. Returns `404` if the link is unknown or its file was deleted, `410` if
the link has expired.

### `GET /d/{token}`
Downloads the file bytes for a link. Increments the link's `download_count`.
Restores the original filename via `Content-Disposition`. Returns `404` if
missing/deleted, `410` if expired.

## Public — anonymous upload

### `POST /api/anon-upload`
Constrained, account-free upload from the landing page.

**Body** (`multipart/form-data`):

| Field | Type | Notes |
|---|---|---|
| `file` | file | **Required.** The upload. Capped at `ANON_MAX_UPLOAD_BYTES`. |
| `fp` | string | Optional client-computed fingerprint hash. |
| `fp_data` | string | Optional JSON bundle of raw fingerprint signals. |

**Responses:**

- `200` — `{ ok: true, token, share_url, filename, size, expires_at }`. The
  anonymous link expires after `ANON_SHARE_EXPIRY_HOURS`.
- `413` — `{ ok: false, error }` when the file exceeds the anonymous size cap.
- `429` — `{ ok: false, error }` with a `Retry-After` header when the client is
  over its hourly or daily budget (keyed by IP **or** fingerprint).

Every call writes an `upload_events` audit row (IP, UA, fingerprint). See
[Security](SECURITY.md).

## Authentication

### `GET /login`
Starts the OIDC Authorization Code flow (redirects to Authentik). Redirects to
the canonical host first if reached on a non-canonical hostname. Returns `503` if
OIDC is not configured.

### `GET /auth/callback`
OIDC redirect target. Exchanges the code for tokens, reads `userinfo` (including
the `groups` claim), stores the identity in the session cookie, and redirects to
`/app`. On failure, renders a friendly error page with status `400`.

### `GET /logout`
Clears the session and redirects to `/`.

## Member — workspace & file management

### `GET /app`
The authenticated workspace: the signed-in member's files, each with its share
link, expiry, download count, and management actions. Redirects to `/login` if
unauthenticated; renders a `403` "not authorized" page for a signed-in
non-member.

### `POST /api/files`
Upload a file as a member.

**Body** (`multipart/form-data`):

| Field | Type | Notes |
|---|---|---|
| `file` | file | **Required.** Capped at `MAX_UPLOAD_BYTES`. |
| `expiry_hours` | int | One of `SHARE_EXPIRY_OPTIONS_HOURS`; invalid values fall back to the default. |
| `fp`, `fp_data` | string | Optional fingerprint signals (recorded on the audit row). |

**Responses:** `200` `{ ok: true, ...file_row }`; `403` if not a member; `413` if
over the size cap.

### `POST /api/shares/{token}/expiry`
Change a link's expiry. Body: `expiry_hours` (must be an allowed option; `400`
otherwise). Clears any prior revocation. Owner-only (`404` for a token the caller
doesn't own). Returns `{ ok: true, token, expires_at }`.

### `POST /api/shares/{token}/revoke`
Revoke a link immediately (it then reads as expired). Owner-only. Returns
`{ ok: true }`.

### `DELETE /api/files/{file_id}`
Soft-delete a file and remove its blob from disk. Owner-only (`404` otherwise),
member-gated (`403` otherwise). Returns `{ ok: true }`.

### `POST /api/shares/{token}/email`
Send the share link by email via the server-side SMTP relay. Body: `to` (the
recipient). **Members only** — anonymous visitors use a `mailto:` link instead,
so the public share page can't be turned into a spam relay.

**Responses:** `200` `{ ok: true }`; `403` for non-members; `404` if the link is
missing/expired; `503` `{ ok:false, reason:"email_not_configured" }` if SMTP is
unset; `502` `{ ok:false, reason:"send_failed" }` on a send error.

## Infra

### `GET /healthz`
Returns `{ status: "ok" }`. Used by the container health check and the smoke
test. Hidden from the schema.

## Conventions

- JSON API endpoints return `{ ok: true, ... }` on success and `{ ok: false,
  error | reason }` on handled failures, with an appropriate HTTP status.
- The only identifier in any public URL is the share-link `token` (a UUID). File
  IDs appear only in member-authenticated management calls.
- All cookies are `Secure`, `HttpOnly` is managed by Starlette's session
  middleware, and `SameSite=Lax`.
