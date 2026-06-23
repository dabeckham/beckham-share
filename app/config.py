"""Application configuration, loaded from the environment.

All tunables live here so the rest of the code never reads ``os.environ``
directly. Values are supplied via the container environment (see ``.env``).
"""
from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # ── Identity / branding ──────────────────────────────────────────────
    app_name: str = "Beckham Share"
    brand_domain: str = "beckham.ai"
    # Public origin the app is served from (used to build absolute share links).
    base_url: str = "https://share.beckham.ai"
    # Source-repository link surfaced in the signed-in workspace. Set empty to hide.
    source_url: str = "https://github.com/dabeckham/beckham-share"

    # Signs the session cookie. MUST be set to a long random value in prod.
    secret_key: str = "dev-insecure-change-me"

    # ── Storage ──────────────────────────────────────────────────────────
    data_dir: str = "/data"            # blobs live under {data_dir}/blobs
    database_url: str = "postgresql+psycopg2://share:share@db:5432/share"

    # ── OIDC (Authentik) ─────────────────────────────────────────────────
    # Discovery doc for the per-application OIDC provider in Authentik, e.g.
    # https://auth.beckham.ai/application/o/beckham-share/.well-known/openid-configuration
    oidc_discovery_url: str = ""
    oidc_client_id: str = ""
    oidc_client_secret: str = ""
    oidc_scopes: str = "openid profile email groups"
    # Only members of this group may use the authenticated interface. Authentik
    # also gates the application by this group; this is the in-app backstop.
    required_group: str = "dropbox"

    # ── Upload limits & abuse controls ───────────────────────────────────
    # Authenticated members get a generous cap; anonymous (landing page) is tight.
    max_upload_bytes: int = 5 * 1024 * 1024 * 1024          # 5 GiB
    anon_max_upload_bytes: int = 100 * 1024 * 1024          # 100 MiB
    # Rolling-window rate limits for anonymous uploads, keyed by IP + fingerprint.
    anon_uploads_per_hour: int = 5
    anon_uploads_per_day: int = 20

    # ── Share-link expiry ────────────────────────────────────────────────
    # Allowed expiry choices (hours) offered in the UI. 0 == "never".
    share_expiry_options_hours: str = "1,24,168,720,0"      # 1h, 1d, 7d, 30d, never
    default_share_expiry_hours: int = 168                   # 7 days
    # Anonymous uploads always auto-expire (no "never" option for them).
    anon_share_expiry_hours: int = 24

    # ── Email (share-by-email) — optional, off until SMTP is configured ──
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = "Beckham Share <share@beckham.ai>"
    smtp_use_tls: bool = True

    # Whether to trust X-Forwarded-For (true when behind the Caddy/HAProxy front).
    trust_forwarded_for: bool = True

    @property
    def email_enabled(self) -> bool:
        return bool(self.smtp_host and self.smtp_user and self.smtp_password)

    @property
    def expiry_options(self) -> list[int]:
        return [int(x) for x in self.share_expiry_options_hours.split(",") if x.strip() != ""]

    @property
    def oidc_configured(self) -> bool:
        return bool(self.oidc_discovery_url and self.oidc_client_id and self.oidc_client_secret)


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
