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
- **A missing `groups` claim is refused.** Authentik is configured to send the
  claim (a `groups` scope mapping is bound to the provider), so a token without
  one means the provider's configuration has drifted — not that the user belongs
  to nothing. Admitting them would quietly reduce a deliberately two-layer gate
  to Authentik's binding alone, which is the layer this check exists not to
  depend on. The request is refused and the reason is logged.
- **Escape hatch.** `ALLOW_MISSING_GROUPS_CLAIM` (default `false`) restores the
  old behaviour so a broken scope mapping can be repaired without locking the
  members out of their own files. It re-opens the gap it exists to close, so the
  app logs a warning at startup for as long as it is set. Clear it once the
  mapping is fixed.

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
fingerprint** (`OR`), so rotating just one signal does not reset the budget. The
two keys carry different weight on purpose: the address is established by the
infrastructure (see `TRUSTED_PROXIES` below), while the browser fingerprint is
supplied by the client and can be changed at will. The fingerprint's job is to
catch one device rotating addresses; it is an additional key, never a
substitute for the address.
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

- **Client IP** — the address the request arrived from, unless it arrived from a
  peer listed in `TRUSTED_PROXIES`, in which case that peer's
  `X-Forwarded-For` / `X-Real-IP` is believed instead. The real client IP is
  preserved to the front through HAProxy's PROXY protocol.

  `X-Forwarded-For` is read **right to left**: trusted hops are skipped and the
  first untrusted address is the closest one a trusted proxy actually observed.
  Reading left to right would return whatever the client itself put in the
  header, because proxies append. This matters because the anonymous rate limit
  is keyed on the address — an address the client can choose is an address that
  resets the budget.
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

## 4. The download record

Every request to `/d/{token}` writes a `download_events` row. This records
people **Don deliberately sent a link to**, which is a different group from the
strangers the section above is about, so it is worth being explicit about what
is kept and why.

**Why it exists.** `share_links.download_count` counts requests, and on its own
it reads high: a browser that ranges, retries, or aborts a large file is several
requests and one download. Measured on a 105 MB recording, the counter read 6
against two distinct clients and roughly three complete transfers. Asked who had
downloaded a file, the app could not answer at all, and the question was only
answerable from a proxy log that keeps about a week.

**What is recorded per request:** the client address, user agent (raw and parsed
to browser / OS / device), `Accept-Language`, referer, whether it was a range
request, how long the response took, and whether the client stayed to the end.

**Completion is not a byte count.** Once the peer is gone the server accepts the
application's remaining writes and returns without putting them on the wire, so
an abandoned transfer still totals the whole file at that layer. `completed`
therefore comes from the client disconnecting or not, and `bytes_streamed` is
what the application wrote rather than what arrived. Throughput is reported only
for transfers that finished, because for the others the duration is real and the
byte count is not.

**Naming the client.** The address is resolved to a PTR record after the
response, off the request path, and cached per address. A name separates a
person from automation far better than a guessed location: measured, ordinary
ISP clients resolve (`107-222-110-44.lightspeed.hstntx.sbcglobal.net`), as do
crawlers (`crawl-66-249-66-1.googlebot.com`, `msnbot-40-77-167-1.search.msn.com`)
and Google Cloud (`googleusercontent.com`). No geolocation database is used, so
nothing about a recipient is sent anywhere to obtain it.

The honest limitation: plenty of addresses have no PTR at all. Checked against
three independent resolvers, both an AWS address and Microsoft's mail-scanning
ranges returned nothing. So a missing name is not a failure and not evidence of
anything on its own. Read it together with the two signals that do survive: the
user agent, and whether a fingerprint was reported at all.

**Fingerprinting the downloader.** The share page computes the same browser
fingerprint as the upload form and reports it, so repeat downloads by one device
can be grouped even across addresses. Two honest notes. First, this is a
deliberate extension of a control the brief scoped to the public upload form,
made on request. Second, it only works where a browser ran: a link fetched by
`curl`, a mail scanner, or a link preview has no fingerprint, and that absence
is itself a useful signal rather than a gap.

**The counter keeps its meaning.** `download_count` still counts requests and
still feeds `max_downloads`, which is the right thing for a quota: an abandoned
transfer spent the bandwidth regardless. The workspace shows completed downloads
instead, with the request and client counts behind it, so the number on screen
is the number people mean.

## 5. Data handling

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

## 6. Transport & network

- **HTTPS everywhere.** TLS is terminated by the shared Caddy front (Let's
  Encrypt); the smoke test asserts a valid certificate after each deploy.
- **Database isolation.** PostgreSQL is on an internal Docker network with no
  host port published.
- **Canonical host.** The session cookie and OIDC redirect URIs are bound to
  `BASE_URL`; other hostnames redirect the authenticated flow there, so a cookie
  can't be set on an unexpected origin.

## 7. Threat model (summary)

| Threat | Mitigation |
|---|---|
| Anonymous form used to host abusive material | Size cap, rate limit, short auto-expiry, IP + fingerprint audit trail. |
| Link guessing / enumeration | UUID tokens; no filename or sequential ID in URLs. |
| Unauthorized workspace access | OIDC + group binding at the IdP, re-checked in-app. |
| Public share page abused as a spam relay | Server-side email is members-only; anonymous uses `mailto:`. |
| Oversized-upload resource exhaustion | Streaming write with an early abort + partial-file cleanup. |
| Session forgery | Signed session cookie (`SECRET_KEY`); `Secure` + `SameSite=Lax`. |
| No record of who received a shared file | One `download_events` row per request, with address, user agent, and whether the transfer finished. |
| Spoofed client IP (to reset the rate limit or poison the audit trail) | Forwarded headers are honoured only from peers in `TRUSTED_PROXIES`, and the chain is read right to left so client-appended hops are discarded. Everything else is attributed to the address it arrived from. |

## 8. Operational guidance

- Set a strong, unique `SECRET_KEY` in production; rotating it invalidates all
  sessions.
- Keep the `groups` scope mapping bound to the provider. Without it nobody
  reaches the workspace, which is the intended failure direction — check
  `docker compose logs app` for the "no groups claim" warning if sign-in starts
  ending in a 403.
- Review the `upload_events` table periodically for anomalous IPs/fingerprints.
- Tune `ANON_*` limits to the host's tolerance; they are all environment-driven.
