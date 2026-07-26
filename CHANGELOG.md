# Changelog

Notable changes to Beckham Share, newest first. The project follows a simple
pre-1.0 scheme; dates are when the change reached `main`.

## Unreleased

### Security
- An OIDC token that carries no `groups` claim is now refused instead of being
  admitted on the strength of Authentik's application binding. The provider is
  configured to send the claim, so its absence means the configuration has
  drifted — and falling back reduced a deliberately two-layer gate to the one
  layer the in-app check exists not to depend on. `ALLOW_MISSING_GROUPS_CLAIM`
  (default `false`) restores the old behaviour for repairing a broken scope
  mapping, and warns at startup for as long as it is set.

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
