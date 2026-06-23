# Security

Beckham Share exposes a **public** upload form to the internet, so its security
posture is deliberately split: a tightly constrained anonymous tier and an
identity-gated member tier. This document covers the authentication model, the
abuse controls, the data handled, and the threat model.

## 1. Authentication & authorization

- **Protocol.** OIDC Authorization Code flow against Authentik
  (`auth.beckham.ai`), via Authlib. See [`app/auth.py`](../app/auth.py).
- **Session.** On success the app stores `{sub, email, name, groups}` in a
  signed, `Secure`, `SameSite=Lax` session cookie (Starlette's
  `SessionMiddleware`, signed with `SECRET_KEY`). The app owns its own session;
  it does not rely on a proxy to inject identity.
- **Two-layer group gate.** The workspace is restricted to members of the
  `dropbox` group in two independent places:
  1. **At Authentik** — the application is bound to the group, so non-members
     can't complete the flow at the IdP.
  2. **In-app backstop** — `/app` and every management route re-check the
     `groups` claim (`CurrentUser.in_required_group`).
- **No-groups fallback.** If a token arrives with no `groups` claim (scope
  mapping missing), the app trusts Authentik's application-level binding rather
  than locking everyone out, and logs a warning so the gap is visible. Keep the
  `groups` scope configured so the in-app check is authoritative.

## 2. Anonymous-upload abuse controls

The landing page is a public form. Four layers keep it from becoming a dump:

### Size cap
Anonymous uploads are capped at `ANON_MAX_UPLOAD_BYTES` (default 100 MiB),
enforced *while streaming* — the upload is aborted and the partial file deleted
the moment it exceeds the limit (`app/storage.py`), so an oversized file is never
fully buffered. Members have a separate, larger cap (`MAX_UPLOAD_BYTES`).

### Rate limiting
`app/ratelimit.py` enforces a rolling-window budget:

- `ANON_UPLOADS_PER_HOUR` (default 5) in the last hour, and
- `ANON_UPLOADS_PER_DAY` (default 20) in the last 24 hours.

The count is taken from the `upload_events` audit rows, keyed by **IP _or_
fingerprint** (`OR`), so rotating just one signal does not reset the budget.
Because it counts rows that already exist in the database, the limit holds across
worker processes and restarts with no separate store. Over-budget requests get
`429` with a `Retry-After` header.

### Short auto-expiry
Anonymous links always expire after `ANON_SHARE_EXPIRY_HOURS` (default 24 h);
there is no "never" option for them. The blob carries the same hard expiry.

### Audit trail + fingerprinting
Every upload writes an `upload_events` row for review — see below.

## 3. Fingerprinting & the audit trail

`app/fingerprint.py` records, per upload:

- **Client IP** — from `X-Forwarded-For` / `X-Real-IP` when `TRUST_FORWARDED_FOR`
  is set (the real client IP is preserved through HAProxy's PROXY protocol),
  otherwise the socket peer.
- **User agent** — raw, plus a parsed `browser` / `os` / `device` breakdown for
  human-readable review.
- **Accept-Language**.
- **Fingerprint hash** — a SHA-256 over either the client-supplied browser
  fingerprint (canvas / WebGL / screen / timezone signals, richer) or, for
  JS-less clients, a header/network-derived basis so they are still grouped.
- **Raw fingerprint bundle** (`fingerprint_data`) for later inspection.

> Fingerprinting here is a **deterrent and an audit aid, not a security
> boundary.** It can be spoofed; it exists to make casual abuse traceable and
> rate-limitable, not to authenticate anyone.

## 4. Data handling

- **Filename privacy.** The original filename never appears in a URL or an
  on-disk path. Blobs are stored under `{DATA_DIR}/blobs/<uuid>`; the real name
  lives only in the database and is restored in the download's
  `Content-Disposition`.
- **Opaque links.** Share URLs contain only a random UUID token; they are
  unguessable and reveal nothing about the file.
- **Integrity.** Each blob's SHA-256 is computed on upload and stored.
- **Deletion.** Deleting a file soft-deletes the row and removes the blob from
  disk; expired/revoked links stop serving immediately.
- **Secrets.** `SECRET_KEY`, `DB_PASSWORD`, the OIDC client secret, and SMTP
  credentials live only in the host's `.env` (gitignored) — never in the repo.

## 5. Transport & network

- **HTTPS everywhere.** TLS is terminated by the shared Caddy front (Let's
  Encrypt); the smoke test asserts a valid certificate after each deploy.
- **Database isolation.** PostgreSQL is on an internal Docker network with no
  host port published.
- **Canonical host.** The session cookie and OIDC redirect URIs are bound to
  `BASE_URL`; other hostnames redirect the authenticated flow there, so a cookie
  can't be set on an unexpected origin.

## 6. Threat model (summary)

| Threat | Mitigation |
|---|---|
| Anonymous form used to host abusive material | Size cap, rate limit, short auto-expiry, IP + fingerprint audit trail. |
| Link guessing / enumeration | UUID tokens; no filename or sequential ID in URLs. |
| Unauthorized workspace access | OIDC + group binding at the IdP, re-checked in-app. |
| Public share page abused as a spam relay | Server-side email is members-only; anonymous uses `mailto:`. |
| Oversized-upload resource exhaustion | Streaming write with an early abort + partial-file cleanup. |
| Session forgery | Signed session cookie (`SECRET_KEY`); `Secure` + `SameSite=Lax`. |
| Spoofed client IP | Real IP preserved via PROXY protocol; `X-Forwarded-For` trusted only behind the front. |

## 7. Operational guidance

- Set a strong, unique `SECRET_KEY` in production; rotating it invalidates all
  sessions.
- Keep the `groups` scope mapping configured so the in-app group check is
  authoritative rather than relying on the fallback.
- Review the `upload_events` table periodically for anomalous IPs/fingerprints.
- Tune `ANON_*` limits to the host's tolerance; they are all environment-driven.
