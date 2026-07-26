# Changelog

Notable changes to Beckham Share, newest first. The project follows a simple
pre-1.0 scheme; dates are when the change reached `main`.

## Unreleased

### Security
- The client address behind the anonymous rate limit and the upload audit trail
  is no longer take-your-word-for-it. Forwarded headers are honoured only from
  peers listed in the new `TRUSTED_PROXIES` setting, and `X-Forwarded-For` is
  read right to left so hops appended by the client are discarded. Previously
  any caller that could open a socket to the app could name itself, which reset
  the rate-limit budget and wrote a false address into the audit trail;
  `TRUST_FORWARDED_FOR=false` did not prevent it, because the server was
  rewriting the peer address before the application saw it. That setting is
  replaced by `TRUSTED_PROXIES`.

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
