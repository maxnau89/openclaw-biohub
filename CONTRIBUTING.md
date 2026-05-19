# Contributing

Patches, bug reports, and ideas are welcome.

## Before you open a PR

1. **Discuss bigger changes first.** Open an issue describing what you
   want to change and why. Small fixes (typos, obvious bugs, parsing
   edge cases) don't need this.
2. **Don't include real biometric data** in tests, fixtures, or
   examples. The repo ships only synthetic data — keep it that way.
3. **Run the test suite locally.** `pytest tests/ -v` from the repo
   root.
4. **For dashboard changes,** run `npm run build` in `dashboard/` and
   make sure there are no TypeScript errors.

## Development setup

See [CONFIGURATION.md](CONFIGURATION.md) for the full setup. The TL;DR
for contributors:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r tests/requirements.txt

# Generate fixtures so tests have data
OPENCLAW_BIOHUB_HOME=$PWD/.local-data python3 fixtures/seed.py

# Run tests
pytest tests/ -v
```

## Code style

- Python: 4-space indent, type hints on public functions, prefer
  standard-library + the existing pandas/numpy/sklearn stack over
  introducing new dependencies.
- TypeScript: follow the existing patterns. The dashboard uses Next.js
  app router + better-sqlite3 + Tailwind.

## Areas where help is especially welcome

- **Blood-panel parsers** for additional lab formats (the shipped
  parser targets a specific German lab layout — `parse_blood_panel.py`).
- **WHOOP API edge cases** — schema drift, missing fields, rate-limit
  recovery.
- **Documentation** — especially deployment recipes (Docker compose,
  systemd templates for non-Debian distros, fly.io, etc.).
- **Internationalization** — the dashboard is currently English-only.

## Scope guidance

This project is intentionally narrow: **personal-scale, single-user,
self-hosted, biometric + supplement + blood analytics, with an optional
OpenClaw agent layer**. Out of scope:

- Multi-user / multi-tenant features.
- Hosted SaaS.
- Clinical / regulatory workflows (HIPAA, GDPR data-processor
  obligations, EHR integration).
- Wearables other than WHOOP — happy to accept *separate* pipelines
  (e.g. `pipeline/oura_sync.py`) but not a unified abstraction layer.
