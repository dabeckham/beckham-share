# Changelog

Notable changes to Beckham Share, newest first. The project follows a simple
pre-1.0 scheme; dates are when the change reached `main`.

## Unreleased

### Changed
- The SMTP relay's pinned address is now set by `SMTP_RELAY_HOST` /
  `SMTP_RELAY_IP` instead of being hard-coded in `docker-compose.yml`, so it can
  be corrected from `.env` when the provider's pool changes. Added a runbook
  entry for diagnosing it, since the failure looks like nothing else breaking.

### Added
- Full reference documentation under `docs/`: architecture, configuration,
  operations runbook, security model, and API reference, with a docs index and
  a `CONTRIBUTING` guide.

## 2026-06-23

### Added
- Troubleshooting write-up for the Android upload "microphone" prompt, plus a
  standalone file-picker diagnostic page kept for reference (#10).

### Fixed
- CI: use a writable `DATA_DIR` for the end-to-end job and stop duplicate
  workflow runs.

## 2026-06-22

### Added
- **Initial release.** Upload a file and share it by an opaque UUID link with a
  configurable expiry; copy-to-clipboard and email actions.
- Public landing page with a constrained anonymous upload (size cap, rate limit,
  short auto-expiry, IP + fingerprint audit trail).
- Identity-gated workspace: OIDC sign-in against Authentik, restricted to the
  `dropbox` group at the IdP and re-checked in-app.
- Server-side "email this link" over SMTP, restricted to signed-in members;
  anonymous visitors fall back to a `mailto:` link.
- Per-link management: change expiry, revoke, delete; download counting.
- Brand logo and favicon.
- Three-layer automated test suite (backend integration, browser E2E, live
  smoke + configuration check) with continuous integration on every push and
  pull request, plus `docs/TESTING.md`.

### Fixed
- Sign-in failure caused by an empty `grant_types` on the OIDC provider; the
  Authentik setup script now sets them explicitly and the smoke test guards it.
- Share modal that could open stuck and uncloseable.
