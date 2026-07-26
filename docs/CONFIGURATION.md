# Configuration

All configuration is read from the environment at startup by
[`app/config.py`](../app/config.py); the rest of the code never touches
`os.environ` directly. In production the values are supplied through the
container's `.env` file (see [`.env.example`](../.env.example)), which is **never
committed**. `scripts/generate-secrets.sh` creates a `.env` with a random
`SECRET_KEY` and `DB_PASSWORD`; the OIDC credentials are filled in after the
Authentik setup step (see [Operations](OPERATIONS.md)).

Settings are typed and validated by `pydantic-settings`; unknown variables are
ignored. Booleans accept `true`/`false`/`1`/`0`.

## Identity & branding

| Variable | Default | Purpose |
|---|---|---|
| `APP_NAME` | `Beckham Share` | Display name used in the UI and outgoing email. |
| `BRAND_DOMAIN` | `beckham.ai` | Brand domain shown in email footers. |
| `BASE_URL` | `https://share.beckham.ai` | **Canonical public origin.** Used to build absolute share links and the OIDC redirect URI, and to decide the canonical host for redirects. |

## Security & sessions

| Variable | Default | Purpose |
|---|---|---|
| `SECRET_KEY` | `dev-insecure-change-me` | Signs the session cookie. **Must** be a long random value in production — rotating it logs everyone out. |
| `TRUST_FORWARDED_FOR` | `true` | Trust `X-Forwarded-For` / `X-Real-IP` for the client IP. Correct when behind the Caddy/HAProxy front; set `false` only if the app is exposed directly. |

## Storage & database

| Variable | Default | Purpose |
|---|---|---|
| `DATA_DIR` | `/data` | Blob root; files live under `{DATA_DIR}/blobs/`. Backed by the `share-data` volume. |
| `DATABASE_URL` | `postgresql+psycopg2://share:share@db:5432/share` | SQLAlchemy database URL. Compose injects the real password via `DB_PASSWORD`. |

## OIDC (Authentik)

| Variable | Default | Purpose |
|---|---|---|
| `OIDC_DISCOVERY_URL` | *(empty)* | The provider's OpenID discovery document, e.g. `https://auth.beckham.ai/application/o/beckham-share/.well-known/openid-configuration`. |
| `OIDC_CLIENT_ID` | *(empty)* | OAuth2 client ID from the Authentik provider. |
| `OIDC_CLIENT_SECRET` | *(empty)* | OAuth2 client secret. |
| `OIDC_SCOPES` | `openid profile email groups` | Requested scopes. The `groups` scope is required for the in-app group check. |
| `REQUIRED_GROUP` | `dropbox` | Group required for the authenticated workspace. Enforced at Authentik **and** in-app. |

> Sign-in stays disabled until all three of discovery URL, client ID, and client
> secret are set (`settings.oidc_configured`). The public landing page, uploads,
> share pages, and downloads all work without OIDC configured.

## Upload limits & abuse controls

| Variable | Default | Purpose |
|---|---|---|
| `MAX_UPLOAD_BYTES` | `5368709120` (5 GiB) | Per-file cap for authenticated members. |
| `ANON_MAX_UPLOAD_BYTES` | `104857600` (100 MiB) | Per-file cap for anonymous landing-page uploads. |
| `ANON_UPLOADS_PER_HOUR` | `5` | Rolling 1-hour anonymous upload budget per client (IP or fingerprint). |
| `ANON_UPLOADS_PER_DAY` | `20` | Rolling 24-hour anonymous upload budget per client. |

See [Security](SECURITY.md) for how the limits are keyed and enforced.

## Share-link expiry

| Variable | Default | Purpose |
|---|---|---|
| `SHARE_EXPIRY_OPTIONS_HOURS` | `1,24,168,720,0` | Expiry choices offered in the UI, in hours (`0` = never). Default set is 1 h, 1 d, 7 d, 30 d, never. |
| `DEFAULT_SHARE_EXPIRY_HOURS` | `168` (7 days) | Default expiry for member uploads. |
| `ANON_SHARE_EXPIRY_HOURS` | `24` | Fixed expiry for anonymous uploads (they never get a "never" option). |

## Email (share-by-email)

Optional. Until SMTP is configured, the front end falls back to a `mailto:` link,
and the server-side relay (members only) returns a "not configured" response.

| Variable | Default | Purpose |
|---|---|---|
| `SMTP_HOST` | *(empty)* | SMTP server hostname. Setting host + user + password enables server-side email (`settings.email_enabled`). |
| `SMTP_PORT` | `587` | SMTP port (587 for STARTTLS). |
| `SMTP_USER` | *(empty)* | SMTP username. |
| `SMTP_PASSWORD` | *(empty)* | SMTP password. |
| `SMTP_FROM` | `Beckham Share <share@beckham.ai>` | `From` header on outgoing mail. |
| `SMTP_USE_TLS` | `true` | Use STARTTLS before authenticating. |

The relay used in production presents a shared `*.eigbox.net` certificate, so the
app has to connect by that hostname for STARTTLS verification to succeed — but
the hostname's public DNS record points at a pool member the container network
cannot reach. `docker-compose.yml` therefore pins the name to an address that
answers, via `extra_hosts`. Two variables control the pin:

| Variable | Default | Purpose |
|---|---|---|
| `SMTP_RELAY_HOST` | `mail.eigbox.net` | Hostname the certificate is valid for, and the value `SMTP_HOST` should use. |
| `SMTP_RELAY_IP` | `66.96.134.48` | Address that hostname is pinned to inside the container. |

> Read by Compose when the stack starts, not by `app/config.py` — they shape the
> container's `/etc/hosts` rather than the application's settings. When mail
> starts failing to connect, this pin is the first thing to check;
> [Operations](OPERATIONS.md) has the procedure.

## Derived settings (not environment variables)

These are computed properties on the settings object:

- `email_enabled` — true when `SMTP_HOST`, `SMTP_USER`, and `SMTP_PASSWORD` are all set.
- `expiry_options` — `SHARE_EXPIRY_OPTIONS_HOURS` parsed into a list of ints.
- `oidc_configured` — true when discovery URL, client ID, and client secret are all set.
