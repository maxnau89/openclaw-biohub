-- ============================================================
-- DB: apple_health_raw.db  (raw Apple Health samples)
-- ============================================================
-- Apple Health is a stream of typed samples, not a paged API.
-- We store samples generically (one table) and sleep + workouts
-- separately because they have interval semantics, not point-in-time.

-- metric_samples: one row per HKQuantitySample / HKCategorySample
CREATE TABLE IF NOT EXISTS metric_samples (
    id TEXT PRIMARY KEY,             -- "<metric>:<iso_date>" if no UUID given
    metric_name TEXT NOT NULL,       -- "heart_rate", "step_count", "hrv", "spo2", ...
    date TEXT NOT NULL,              -- ISO 8601, sample timestamp
    value REAL,
    unit TEXT,
    source TEXT,                      -- "Apple Watch", "iPhone", ...
    created_at INTEGER DEFAULT (strftime('%s','now') * 1000)
);
CREATE INDEX IF NOT EXISTS idx_ah_metric_name_date ON metric_samples(metric_name, date);
CREATE INDEX IF NOT EXISTS idx_ah_metric_date ON metric_samples(date);

-- sleep_samples: HKCategorySample of HKCategoryTypeIdentifierSleepAnalysis
-- One row per sleep "phase" interval (InBed / Awake / Asleep / REM / Deep / Core / Unspecified)
CREATE TABLE IF NOT EXISTS sleep_samples (
    id TEXT PRIMARY KEY,
    sleep_start TEXT NOT NULL,        -- ISO 8601
    sleep_end TEXT NOT NULL,
    value TEXT NOT NULL,              -- one of: "InBed" | "Awake" | "Asleep" | "REM" | "Deep" | "Core" | "Unspecified"
    source TEXT,
    created_at INTEGER DEFAULT (strftime('%s','now') * 1000)
);
CREATE INDEX IF NOT EXISTS idx_ah_sleep_start ON sleep_samples(sleep_start);

-- workout_samples: HKWorkout
CREATE TABLE IF NOT EXISTS workout_samples (
    id TEXT PRIMARY KEY,
    workout_type TEXT,                -- "Running", "Cycling", "Strength Training", ...
    start_date TEXT,
    end_date TEXT,
    total_energy_burned REAL,         -- kcal
    total_distance REAL,              -- meters
    source TEXT,
    created_at INTEGER DEFAULT (strftime('%s','now') * 1000)
);
CREATE INDEX IF NOT EXISTS idx_ah_workout_start ON workout_samples(start_date);

-- import_log: track which files have been imported (idempotency)
CREATE TABLE IF NOT EXISTS import_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_path TEXT NOT NULL,
    file_mtime INTEGER,               -- for re-importing if file changes
    imported_at INTEGER DEFAULT (strftime('%s','now') * 1000),
    records_count INTEGER,
    success BOOLEAN,
    error_message TEXT,
    UNIQUE (file_path, file_mtime)
);
