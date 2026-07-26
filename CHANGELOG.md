# Changelog

Notable changes to Beckham Share, newest first. The project follows a simple
pre-1.0 scheme; dates are when the change reached `main`.

## Unreleased

### Added
- Full reference documentation under `docs/`: architecture, configuration,
  operations runbook, security model, and API reference, with a docs index and
  a `CONTRIBUTING` guide.

### Security
- Updated dependencies to clear published advisories against the pinned
  versions: Authlib 1.4.0 → 1.7.2 (signature-verification bypass in JWS JWK
  header handling, CVE-2026-27962, plus nine further advisories on the OIDC
  path), python-multipart 0.0.20 → 0.0.32 (denial-of-service and parameter
  smuggling in multipart parsing, reachable from the public upload form), and
  Jinja2 3.1.5 → 3.1.6 (CVE-2025-27516).

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
