# Contributing

Thanks for working on Beckham Share. This guide covers local setup, the workflow,
and the conventions a change is expected to follow.

## Local setup

```sh
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
pip install -r requirements-dev.txt        # test + tooling deps

# Point DATABASE_URL at a local Postgres (or run the compose db service), then:
uvicorn app.main:app --reload
```

The landing page, anonymous uploads, share pages, and downloads all work without
OIDC configured. Only the `/app` workspace requires Authentik — see
[Configuration](docs/CONFIGURATION.md) for the `OIDC_*` variables.

## Workflow

- **Never commit or push to `main`.** Branch, push, open a pull request, merge,
  then delete the branch.
- **One focused change per pull request.** Keep diffs reviewable.
- **Use issues for tracking.** File bugs with the `bug` label and planned work
  with `enhancement`. Reference the issue from the PR.
- Branch names describe the change, e.g. `add-download-analytics`,
  `fix-share-modal`.

## Tests are part of the change

A feature is not done until its real behavior is covered by an automated test —
"the endpoint returns 200" is not "the feature works". Pick the layer that fits
(full detail in [docs/TESTING.md](docs/TESTING.md)):

- New route or business rule → a **backend** test (`tests/backend`, pytest).
- New button / component / page interaction → a **browser E2E** test
  (`tests/e2e`, Playwright) so the rendered behavior is covered.
- New deploy-time invariant (a hostname, a provider setting) → a check in
  `scripts/smoke.sh`.

Run the relevant suite before opening a PR:

```sh
sh scripts/run-tests.sh   # backend integration (throwaway Postgres)
sh scripts/run-e2e.sh     # browser end-to-end (throwaway local instance)
```

CI runs the backend and E2E layers on every push and pull request; the PR must be
green before merge.

## Conventions

- **Configuration goes through `app/config.py`.** Don't read `os.environ`
  elsewhere; add a typed setting and document it in
  [docs/CONFIGURATION.md](docs/CONFIGURATION.md).
- **Keep the access tiers explicit.** Public, member, and infra routes are
  distinct; member routes must check `in_required_group`.
- **Never expose the original filename in a URL or path.** Use the UUID; restore
  the name only in `Content-Disposition`.
- **Secrets never enter the repo.** `.env`, `secrets/`, and host-specific files
  are gitignored; document new settings with safe placeholders in `.env.example`.
- **Update the docs with the code.** A change that adds a route, a setting, or an
  operational step updates the matching document under `docs/`.
- **Strip metadata from generated binaries before committing them.** Anything
  produced by a tool — a PDF rendered from HTML, an exported image — carries an
  embedded record of the machine that made it: source filename, the rendering
  engine and its version, the operating system, a timestamp. None of it is
  visible in the document and none of it belongs in a public repository.
  `exiftool -all= file.pdf` clears it, or `qpdf` if you prefer to keep the
  document structure untouched.
- Match the surrounding code's style; keep functions small and the modules'
  single responsibilities intact (see [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)).

## Project layout

```
app/            FastAPI application (routes, models, auth, storage, templates, static)
caddy/          reverse-proxy route snippet for the shared Caddy front
scripts/        deploy, secret generation, Authentik setup, test runners
tests/          backend (pytest) + e2e (Playwright) suites
docs/           architecture, configuration, operations, security, API, testing
```
