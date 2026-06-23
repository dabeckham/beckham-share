# Documentation

Reference documentation for Beckham Share. Start with the [project README](../README.md)
for a high-level overview; the documents below go deeper.

| Document | What it covers |
|---|---|
| [Architecture](ARCHITECTURE.md) | Components, request flows, the data model, and how the service plugs into the host's reverse-proxy / identity stack. |
| [Configuration](CONFIGURATION.md) | Every environment variable — purpose, default, and how it is used. |
| [Operations](OPERATIONS.md) | First deploy, the Authentik / Caddy wiring, and the day-two runbook (logs, backups, upgrades, recovery). |
| [Security](SECURITY.md) | Authentication, the group gate, the anonymous-upload abuse controls, fingerprinting, and the threat model. |
| [API reference](API.md) | Every HTTP route — method, auth tier, parameters, and responses. |
| [Testing](TESTING.md) | The three test layers (backend, browser E2E, live smoke) and how to run and extend them. |
| [Contributing](../CONTRIBUTING.md) | Local setup, the branch/PR workflow, and the conventions a change must follow. |
| [Changelog](../CHANGELOG.md) | Notable changes, newest first. |

## Troubleshooting notes

Longer-form write-ups of specific problems and how they were diagnosed live in
[`troubleshooting/`](troubleshooting/):

- [Why is the upload page asking for my microphone?](troubleshooting/android-file-picker.md)
  — an Android file-input / `accept`-attribute investigation.
