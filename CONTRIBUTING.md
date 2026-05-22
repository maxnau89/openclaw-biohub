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

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .[dev,analytics]

# Generate fixtures so tests have data
OPENCLAW_BIOHUB_HOME=$PWD/.local-data python3 fixtures/seed.py

# Run tests
pytest tests/ -v

# Try the CLI
biohub list-adapters
```

## Adding a new adapter (Polar, Withings, Garmin Health API, …)

The `BiometricAdapter` interface (defined in
[`pipeline/adapters/base.py`](pipeline/adapters/base.py)) is the
contract every adapter implements. Adding one means writing about
~400 lines of mostly mechanical code plus fixtures + tests.

### 1. Create the adapter directory

```
pipeline/adapters/<slug>/
├── __init__.py            # exports the adapter class
├── sync.py                # the BiometricAdapter subclass + main()
├── client.py              # thin HTTP client (or file/library wrapper)
├── schema.sql             # CREATE TABLE blocks for this provider's raw DB
└── fixtures/              # captured/synthetic API responses for tests
```

Use one of the existing adapters as a template — the closest analog
depends on the source's auth model:

- **PAT / no auth dance** → mirror `pipeline/adapters/oura/`
- **OAuth 2.0 with browser redirect** → mirror `pipeline/adapters/fitbit/`
- **File-based** (no network) → mirror `pipeline/adapters/apple_health/`
- **Unofficial library / scraping** → mirror `pipeline/adapters/garmin/`
  (and mark `stability = "experimental"`)

### 2. Subclass `BiometricAdapter`

Five class attributes + four methods:

```python
class YourAdapter(BiometricAdapter):
    slug = "your-source"                # CLI subcommand target
    display_name = "Your Source"
    raw_db_name = "your_source_raw.db"  # under $OPENCLAW_BIOHUB_HOME/data/
    stability = "stable"                # or "beta" / "experimental"
    requires_oauth = False              # informational

    def setup_instructions(self) -> str: ...
    def configure_interactive(self) -> None: ...
    def sync(self, since=None, limit=None) -> SyncResult: ...
    def rollup_to_health_db(self) -> int: ...
```

If your source uses OAuth 2.0, **use the helpers** in
[`pipeline/adapters/_oauth_helpers.py`](pipeline/adapters/_oauth_helpers.py)
— `build_authorize_url`, `exchange_code_for_tokens`,
`refresh_access_token`, `ensure_fresh_access_token`. They support both
form-encoded and HTTP-Basic client credentials.

### 3. Add a `paths.py` constant

In `pipeline/paths.py`:

```python
YOUR_SOURCE_DB = Path(os.environ.get(
    "YOUR_SOURCE_DB_PATH", BIOHUB_HOME / "data" / "your_source_raw.db",
))
```

And mirror it in `dashboard/src/lib/paths.ts`.

### 4. Register in the CLI

`biohub/registry.py`:

```python
from adapters.your_source.sync import YourAdapter

_ADAPTER_CLASSES = [
    ...,
    YourAdapter,    # at the end (stable) or after stable ones (experimental)
]
```

### 5. Roll up to `daily_metrics`

The dashboard and agent only ever read from `health.db`'s
`daily_metrics` table — they're source-agnostic. Your
`rollup_to_health_db()` must:

- INSERT OR REPLACE on the composite PK `(source, date)`
- Track a `MAX(date) WHERE source = ?` cursor in `daily_metrics` so the
  next rollup is incremental
- NULL out columns the source can't provide (don't make up values)

Cross-source columns currently in `daily_metrics`:
`recovery_score`, `hrv_ms`, `resting_hr`, `spo2`, `skin_temp_c`,
`sleep_performance`, `sleep_hours`, `sleep_efficiency`, `rem_hours`,
`deep_sleep_hours`, `light_sleep_hours`, `day_strain`,
`calories_burned`, `steps`, `active_minutes`.

If your source has a metric none of the existing adapters expose,
add the column to `db/schema.sql` AND include the change in the next
version's migration script.

### 6. Tests + fixtures

- One fixture file per provider endpoint (see `pipeline/adapters/oura/fixtures/`).
- Tests must pass without network access — populate the raw DB
  directly from fixtures (see `tests/test_oura.py` for the pattern),
  not via the live client.
- Tests must pass without owning the device — that's the whole point of
  fixtures.
- Cover at minimum: identity (class attrs), setup_instructions content,
  each parser, end-to-end rollup against fixtures, idempotency.

## Code style

- Python: 4-space indent, type hints on public functions, prefer
  standard-library + the existing pandas/numpy/sklearn stack over
  introducing new dependencies. The Garmin adapter's `garth` is the
  one exception (gated as an optional dep via lazy import).
- TypeScript: follow the existing patterns. The dashboard uses Next.js
  app router + better-sqlite3 + Tailwind.

## Filing a device-validation report

The four non-WHOOP adapters (Oura, Fitbit, Apple Health, Garmin) were
written from public API docs and tested against captured fixture JSON.
Nobody with a real device has confirmed they work end-to-end yet —
that's the single most valuable contribution anyone with one of these
devices can make.

If you own one and want to help:

1. **Run the adapter.** `pip install -e .[analytics]` from the repo
   root, then `biohub connect <slug>` and `biohub sync <slug>`.
2. **Open an issue** at
   <https://github.com/maxnau89/openclaw-biohub/issues/new> with:
   - Title: `device-validation: <slug>` (one of `oura`, `fitbit`,
     `apple-health`, `garmin`)
   - Label: `device-validation`
   - **Watch/device model + firmware version** (Fitbit Charge 6,
     Oura Gen3, Apple Watch Series 10, Garmin Fenix 8, etc.).
   - **What worked**: `biohub connect` reached completion, `biohub sync`
     produced N records across these resources, daily_metrics has
     rows with sensible values for `recovery_score`/`hrv_ms`/`sleep_hours`.
   - **What didn't**: which resource errored, the error message, and —
     ideally — the raw provider response with anything personal redacted.
3. **For schema gaps** (the adapter writes `NULL` where the provider
   actually returns data), include the column name + the raw value
   you see in the response. We'll add the column to the schema and
   wire the parser.
4. **Do not paste real biometric data** in the issue. Sanitize numbers
   to round, plausible-but-fake values; we just need the shape of the
   response, not the contents.

The fixture pattern means once you've validated one resource, the
fixture you contribute lives in `pipeline/adapters/<slug>/fixtures/`
and the next person doesn't have to do that part again.

## Areas where help is especially welcome

- **Device validation** of Oura, Fitbit, Apple Health, and Garmin (see
  the section above — this is the most valuable contribution right now).
- **Blood-panel parsers** for additional lab formats. The shipped
  parser targets a specific German lab layout
  (`pipeline/parse_blood_panel.py`).
- **Garmin Health API adapter** — the existing Garmin adapter scrapes
  Garmin Connect via `garth`. A proper partnership-gated Health API
  adapter would deserve `stability="stable"`. Requires a Garmin
  partnership and a Health API key.
- **More adapters**: Polar, Withings, Strava, Google Fit, Dexcom CGM,
  FreeStyle Libre. The interface is ready.
- **Cross-source pattern engine** — `whoop_pattern_engine.py` is
  WHOOP-schema-bound. A v0.4 refactor should query `daily_metrics`
  source-agnostically so anomaly detection works for Oura users too.
- **Documentation** — especially deployment recipes (Docker compose,
  systemd templates for non-Debian distros, fly.io, etc.).
- **Internationalization** — the dashboard is currently English-only.

## Tracking-phase categories

`tracking_phases.category` is an open-ended free-text column — users
can put whatever string makes sense to them ("PRP injection",
"vacation", "shift work"). The CLI ships sensible default chip
colors for five canonical categories, and the dashboard falls back to
slate for anything else. The default palette:

| Category     | Color    | Hex       | Typical phases |
|--------------|----------|-----------|----------------|
| `training`   | emerald  | `#34d399` | strength block, mesocycle, deload |
| `diet`       | amber    | `#fbbf24` | cut, bulk, recomp, fast, refeed |
| `supplement` | violet   | `#a78bfa` | creatine loading, NAC trial, vitamin-D protocol |
| `medication` | rose     | `#f87171` | antibiotics, accutane, TRT |
| `lifestyle`  | sky      | `#38bdf8` | sober month, no-caffeine week, jet-lag, illness |

When adding analysis surfaces that read `tracking_phases`, please
respect the user's category strings as-is (don't normalize them) and
use `tracking_phases.color` if set; only fall back to the table above
when the column is NULL. The dashboard already does this — see
`dashboard/src/components/health/BodyCompTab.tsx`'s `colorForPhase()`.

If you find yourself wanting a sixth canonical category that fits the
"personal-scale, single-user" scope, open an issue first so we can
agree on a color before it ships.

## Scope guidance

This project is intentionally narrow: **personal-scale, single-user,
self-hosted, biometric + supplement + blood analytics, with an
optional OpenClaw agent layer**. Out of scope:

- Multi-user / multi-tenant features.
- Hosted SaaS.
- Clinical / regulatory workflows (HIPAA, GDPR data-processor
  obligations, EHR integration).
- Any change that requires accumulating user data on third-party
  infrastructure.
