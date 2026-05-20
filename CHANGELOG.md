# Changelog

All notable changes to openclaw-biohub are recorded here. The format
follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); this
project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
v0.x means the schema and CLI may break between minor versions.

## [Unreleased]

## [0.2.0] — TBD

### ⚠️ Breaking changes

- **`whoop_daily` table renamed to `daily_metrics` with a composite
  primary key `(source, date)`.** All v0.1 users must run
  `python3 db/migrate_v0.1_to_v0.2.py` once before syncing — the script
  renames the table, adds `source='whoop'` to every existing row, and
  is idempotent. The dashboard, the agent persona, and the analytics
  scripts have all been updated to query `daily_metrics`.

### Added

- **`BiometricAdapter` ABC** (`pipeline/adapters/base.py`) — every
  wearable adapter now implements the same four-method lifecycle:
  `setup_instructions()`, `configure_interactive()`, `sync()`,
  `rollup_to_health_db()`.
- **Four new adapters**, all built and tested without owning the
  device (fixtures captured from public API docs):
  - **Oura Ring** (`adapters/oura/`) — Personal Access Token, 6
    endpoints (sleep, readiness, activity, SpO₂, sleep sessions,
    workouts). Stability: **stable**.
  - **Apple Health** (`adapters/apple_health/`) — file-based. Reads
    JSON dumps from the "Health Auto Export" iOS app, or the native
    Health.app `export.xml`. Stability: **stable**.
  - **Fitbit** (`adapters/fitbit/`) — OAuth 2.0 with a one-shot
    localhost callback server. Range-endpoint friendly (stays under
    the 150 req/h rate limit). Sleep stages, HR zones, activity,
    SpO₂, HRV, skin temperature. Stability: **stable**.
  - **Garmin Connect** (`adapters/garmin/`) — via the unofficial
    `garth` library (consumer Garmin Connect Web). Sleep with score,
    activity, resting HR, stress, body battery, HRV. Stability:
    **EXPERIMENTAL** — Garmin can break this at any time.
- **Shared OAuth helpers** (`pipeline/adapters/_oauth_helpers.py`) —
  stateless primitives for the standard OAuth 2.0 flow: load/save
  credentials with merge semantics (so refresh responses don't drop
  the refresh_token), expiry check, authorize-URL builder,
  code-exchange + token-refresh with form-creds OR HTTP Basic auth,
  and an `ensure_fresh_access_token` convenience wrapper.
- **`biohub` CLI** (`biohub/`, exposed via `pip install -e .`):
  - `biohub list-adapters` — table of slug / name / stability / configured?
  - `biohub connect <slug>` — interactive credential setup with a
    sanity sync (and `--dry-run` to preview without writing)
  - `biohub sync <slug>` / `biohub sync --all` — pull + roll up.
    `--dry-run` skips the network; `--since YYYY-MM-DD` for incremental.
  - Experimental adapters print a warning banner on every invocation.
- **`pyproject.toml`** declares the package + `biohub` script entry
  point. Optional dependencies: `[analytics]` for sklearn/scipy/pandas
  (needed by `whoop_pattern_engine.py`), `[dev]` for pytest.
- **`pipeline/adapters/<slug>/schema.sql`** convention — each adapter
  owns its raw-DB schema, applied idempotently via
  `CREATE TABLE IF NOT EXISTS`.
- **Migration script** `db/migrate_v0.1_to_v0.2.py` (see "Breaking
  changes" above).

### Changed

- `db/schema.sql` now describes only `health.db`. Raw-DB schemas live
  with their adapters going forward (WHOOP's block remains in the
  central file as a historical exception).
- `pipeline/whoop_pattern_engine.py`, `blood_marker_analytics.py`,
  `supplement_analytics.py`, and `dashboard/src/lib/whoop.ts` now
  query `daily_metrics` instead of `whoop_daily`.
- WHOOP adapter (`pipeline/adapters/whoop/sync.py`) refactored to
  expose `WhoopAdapter(BiometricAdapter)`; the existing `main()`
  thin-wraps the adapter so the systemd-driven sync keeps working.
- `pipeline/paths.py` and `dashboard/src/lib/paths.ts` gained
  `OURA_DB`, `APPLE_HEALTH_DB`, `FITBIT_DB`, and `GARMIN_DB`.
- README, CONFIGURATION, CONTRIBUTING, and SECURITY all updated to
  cover the multi-adapter world. CONTRIBUTING's earlier "no unified
  abstraction" hedge is removed — the abstraction earned its place
  the moment adapter count went above 1.

### Tests + CI

- 98 tests (was 15 in v0.1). One new test file per new adapter (Oura,
  Apple Health, Fitbit, Garmin, OAuth helpers, CLI, migration).
- All five adapters are validated against fixtures; no test requires
  network, OAuth credentials, or owning the device.

## [0.1.0] — 2026-05-19

### Added

Initial public release. Self-hosted personal-health hub for OpenClaw
with WHOOP as the only adapter wired end-to-end. Next.js dashboard
(recovery / sleep / strain / blood-work / supplements), Python
pipeline (WHOOP API sync, OAuth handler, blood-panel PDF parser,
biomarker + supplement analytics, ML pattern engine), OpenClaw
wellness-coach persona pack, systemd unit + templated secrets file,
synthetic fixtures (`fixtures/seed.py`), 15 pytest tests, GitHub
Actions CI.

[Unreleased]: https://github.com/maxnau89/openclaw-biohub/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/maxnau89/openclaw-biohub/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/maxnau89/openclaw-biohub/releases/tag/v0.1.0
