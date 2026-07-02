# Changelog

All notable changes to openclaw-biohub are recorded here. The format
follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); this
project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
v0.x means the schema and CLI may break between minor versions.

## [Unreleased]

## [0.5.0] — 2026-07-02

### Added

- **FreeStyle Libre 3 / LibreView CGM adapter** (`libre`). File-based
  (LibreView has no public API): drop a CSV export or JSON dump into a
  watch folder and `biohub sync libre` ingests it into its own
  `libre_raw.db`. Auto-detects `,`/`;` delimiter, EN/DE headers, and
  mg/dL vs mmol/L. New **Glucose** dashboard tab + `glucose_analytics.py`
  (mean, SD, CV, GMI/estimated-HbA1c, time-in-range, day-vs-overnight
  means, overnight-glucose ↔ next-day-recovery correlation).
- **Physiological Age** — a WHOOP-Age-style biological-age estimate
  (`physiological_age.py` + **Bio Age** tab). Scores nine markers
  (sleep consistency/hours, HR-zone time, strength, steps, VO₂max via
  the Uth-Sørensen estimator, resting HR, lean mass %) into a
  chronological-age delta with a per-marker breakdown. Reverse-
  engineered from WHOOP's unpublished model, validated to ±0.15 yr per
  marker; computed entirely from data biohub already ingests. Directional
  wellness score, not clinical.
- **Apple Health live push receiver** — the Apple Health adapter now
  accepts a live feed from the *Health Auto Export* iOS app via a
  token-authenticated HTTP receiver
  (`python3 -m adapters.apple_health.receiver`, binds 127.0.0.1 by
  default). Pushed JSON/CSV lands in the watch folder and ingests
  immediately. The adapter also gained a Health Auto Export **CSV**
  parser (alongside JSON/XML/zip).
- **Automated bulk ingest** for blood panels and supplements:
  `blood_panel_import.py` (watch-folder lab-PDF/text → `blood_panels`
  + `blood_markers`) and `supplement_import.py` (CSV/JSON →
  `supplement_log`, auto-creating unknown supplements). Both deduped
  per file, cron-safe.
- `date_of_birth` column on `user_profile` (drives the biological-age
  absolute number).

### Fixed

- **Body-sim morph composition** rebuilt on MakeHuman's bilinear macro
  grid (14 morphs incl. the four corners) instead of additively summing
  the muscle + weight axes — eliminates the surface rippling / hard
  breaks on strongly-modified figures (additive error measured at
  60–138 % of the deformation). Visible muscularity is now gated by
  leanness so a high-FFMI-but-obese body reads as fat rather than
  muscular.

## [0.4.0] — 2026-06-02

### Added

- **3D body composition simulator** under
  `/health?tab=body-comp` (or the standalone `/health/body-composition`).
  Loads a sex-specific anatomical mannequin and deforms it live from
  the user's body-comp data. Three signals drive the shape:
  - **FFMI (lean body mass / height²)** → MakeHuman muscle macro morph
  - **Body-fat %** → MakeHuman weight macro morph (+ a dedicated
    breast morph for female bodies, since MH's weight macro barely
    touches chest tissue)
  - **7-site Jackson-Pollock caliper data** → regional fat
    distribution via per-landmark vertex displacement
    (`MeshDeformer.ts`) — apple, pear, and even distributions all
    read distinctly.
  Compare-mode renders current vs. projected (driven by the existing
  Forward Simulator's sliders) side-by-side, with the goal body
  tinted green.
- **Bake pipeline** at `pipeline/body-sim/` (`fetch_mh_data.sh` +
  `bake_meshes.py`) that pulls MakeHuman's CC0 base mesh + macro
  targets and produces `male-base.glb` + `female-base.glb` with 4–6
  morph targets each. No MakeHuman install required (only its data
  files are consumed). Blender 5.x needed; documented in
  `pipeline/body-sim/README.md`.
- **`anthropometrics.ts`** (typed TypeScript port of the Nacht-Session
  POC's math engine): sex-specific US Navy BF % (cm-metric Hodgdon-
  Beckett / Siri form), FFMI, `predictGirths`, forward simulator
  (cut / bulk / maintenance with protein guard rails + lifter level),
  reverse planner. Bug fixed vs. POC: original used the inches-
  coefficient Navy form with cm inputs, returning BF % ~6 pts high.
- **`MeshDeformer.ts`**: caliper-driven vertex deformation on the
  loaded GLB. Per-vertex weights are computed once at mesh load from
  smoothstep-gated normal directions + Y-Gaussian falloff at each
  caliper site; `apply(params)` re-displaces vertices along normals
  by sqrt-falloff-scaled skinfold deltas. Composes additively in the
  Three.js vertex shader with the GLB's morph targets.
- **Vitest infrastructure** for the dashboard package (`vitest.config.ts`
  + jsdom env). Math engine + MeshDeformer + BodyModel3D smoke test
  → 33 cases total covering Navy roundtrip both sexes, FFMI sanity,
  forward/reverse sim paths, regional deformation (apple/pear/lean),
  smoothstep filter integrity, React mount/unmount under jsdom.
- **`docs/screenshots/gallery/`** — self-contained static HTML page
  that renders 11 body profiles (muscle × weight × both sexes) with
  localStorage-backed notes textareas. Used for iterative QA between
  fine-tuning passes; no server required.

### Changed

- `dashboard/src/components/health/BodyCompTab.tsx` —
  `ForwardSim`'s state lifted into a shared `useForwardSim(data)`
  hook so the new `BodySimCard` can read the projected weight + BF %
  for compare-mode. Existing text-based forward simulator card
  unchanged below the new 3D card.
- `dashboard/src/app/api/body-composition/route.ts` — disable the
  10-minute response cache when `NODE_ENV !== 'production'`. Iterative
  DB edits during dev now show up immediately on the next request;
  prod behaviour unchanged.

### No breaking changes

Database schema is unchanged from v0.3. No migration needed.

### Tests + CI

- 33 dashboard tests (math engine, MeshDeformer, BodyModel3D smoke).
- 141 Python tests still green from v0.3.
- CI pipeline now runs dashboard `npm test` alongside the existing
  Python matrix + dashboard build.

## [0.3.0] — 2026-05-22

### ⚠️ Breaking changes

- **New tables `body_composition` and `tracking_phases` in `health.db`.**
  v0.2 users must run `python3 db/migrate_v0.2_to_v0.3.py` once before
  using the Body Comp tab or `biohub log-measurement` / `log-phase`.
  The script is idempotent and only adds the two missing tables — no
  existing rows are touched.

### Added

- **Body composition tracking** (`body_composition` table, one row per
  date). Records the method (`jackson-pollock-7`, `jackson-pollock-3`,
  `scale`, `dexa`, `apple-health`, `manual`), weight, body-fat %, lean
  + fat mass, and the 7 Jackson-Pollock skinfold sites in mm. Caliper
  entries take precedence over Apple Health weights via a filtered
  upsert (`ON CONFLICT … WHERE method IS NULL OR method = 'apple-health'`).
- **`tracking_phases` table** — user-defined windows (bulks, cuts,
  supplement courses, training blocks, medication, sober months, …) to
  overlay on the body-comp timeline. Categories are open-ended; the
  CLI ships sensible default chip colors for `training`, `diet`,
  `supplement`, `medication`, and `lifestyle`. `end_date IS NULL` means
  the phase is currently active.
- **Dashboard `/health/body-composition`** standalone route + a new
  **Body Comp** tab under `/health?tab=body-comp`. Renders caliper
  history, weight + lean/fat trends, intake (calories + macros), and
  per-phase summaries with colored chips. A 30-day forward simulator
  uses the textbook ΔWeight/day ≈ (kcal − TDEE) / 7700 model.
- **`/api/body-composition`** route reads only from `health.db`.
  Returns `{ entries, tracking_phases, weights, intake, phases,
  insights, computed_at }`; each caliper row carries an
  `active_phases: string[]` of phase names whose window contains that
  date.
- **Apple Health adapter extension** (`pipeline/adapters/apple_health/sync.py`):
  - `HKQuantityTypeIdentifierBodyMass` samples (latest per day) →
    `body_composition(date, method='apple-health', weight_kg)`. The
    upsert is caliper-preserving.
  - Dietary energy + protein + carbs + fat (and water + fiber) →
    `nutrition_logs`, one row per day with `meal_type='day_total'`.
  - Three independent rollup cursors (`last_metrics`, `last_weight`,
    `last_nutrition`) so each stream advances on its own.
- **CLI: `biohub log-measurement`** — flag-driven or interactive entry
  of a body-composition snapshot. Computes body-fat % from skinfolds
  via JP-7 + Siri when only skinfolds + sex + age are given.
- **CLI: `biohub log-phase {start, end, list}`** — open, close, and
  inspect tracking phases. `start` defaults to today; `end` closes the
  most-recent open phase by name match; `list --open-only` filters.
- **`biohub/body_comp.py`** — extracted body-comp logic
  (`compute_bf_jp7`, `derive_mass`, `log_measurement`, `start_phase`,
  `end_phase`, `list_phases`, `default_color`). Importable from
  `biohub` so downstream tools can reuse the math.
- **Seed fixtures**: 8 caliper entries tracing a 90-day recomp arc +
  2 generic `tracking_phases` (`Sample Cut` closed, `Sample Bulk`
  ongoing). Source-agnostic — runs for every `fixtures/seed.py --source`
  mode.
- **Migration script** `db/migrate_v0.2_to_v0.3.py` (see "Breaking
  changes" above).

### Changed

- `db/schema.sql` adds `body_composition` + `tracking_phases` under
  `-- DB 1: health.db`, with `idx_body_composition_date` and
  `idx_tracking_phases_dates`.
- README + CONTRIBUTING gained a "Body composition" section covering
  the recomp arc, phase categories, and the JP-7 entry path.
- `agent/SKILL.md` + `agent/AGENTS.md` list body-comp + tracking-phases
  in the data inventory and explain when to surface phase chips.

### Tests + CI

- 129 tests (was 115 at the end of v0.2). New coverage: schema +
  migration round-trip, Apple Health weight + macro rollup paths,
  JP-7 + Siri math, log-measurement / log-phase dry-runs +
  persistence, seeded caliper arc, seed phase open/closed shape.

## [0.2.0] — 2026-05-21

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

- 106 tests (was 15 in v0.1). One new test file per new adapter (Oura,
  Apple Health, Fitbit, Garmin, OAuth helpers, CLI, migration,
  multi-source seed).
- All five adapters are validated against fixtures; no test requires
  network, OAuth credentials, or owning the device.
- The four non-WHOOP adapters have **not** yet been validated against
  real devices. Contributions of device-validation reports are
  explicitly invited — see
  [CONTRIBUTING.md](CONTRIBUTING.md#filing-a-device-validation-report).

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

[Unreleased]: https://github.com/maxnau89/openclaw-biohub/compare/v0.4.0...HEAD
[0.4.0]: https://github.com/maxnau89/openclaw-biohub/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/maxnau89/openclaw-biohub/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/maxnau89/openclaw-biohub/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/maxnau89/openclaw-biohub/releases/tag/v0.1.0
