-- ============================================================
-- DB: fitbit_raw.db  (raw Fitbit Web API payloads)
-- ============================================================
-- Fitbit endpoints under https://api.fitbit.com/{1,1.2}/user/-/...
-- Auth: OAuth 2.0; refresh tokens rotate on each refresh.
-- Rate limit: 150 req/h per user — adapter prefers range endpoints.

-- sleep_summary: one row per day; sleep stage minutes flattened
CREATE TABLE IF NOT EXISTS sleep_summary (
    date TEXT PRIMARY KEY,                   -- ISO YYYY-MM-DD (dateOfSleep)
    log_id TEXT,
    duration_ms INTEGER,                      -- total in-bed in milliseconds
    minutes_asleep INTEGER,
    minutes_awake INTEGER,
    minutes_to_fall_asleep INTEGER,
    minutes_after_wakeup INTEGER,
    time_in_bed INTEGER,                      -- minutes
    efficiency INTEGER,                       -- percentage 0-100
    rem_minutes INTEGER,
    deep_minutes INTEGER,
    light_minutes INTEGER,
    wake_minutes INTEGER,
    is_main_sleep INTEGER DEFAULT 1,
    start_time TEXT,
    end_time TEXT,
    created_at INTEGER DEFAULT (strftime('%s','now') * 1000)
);

-- heart_summary: one row per day; resting HR + HR-zone calories
CREATE TABLE IF NOT EXISTS heart_summary (
    date TEXT PRIMARY KEY,
    resting_heart_rate INTEGER,
    out_of_range_minutes INTEGER,
    fat_burn_minutes INTEGER,
    cardio_minutes INTEGER,
    peak_minutes INTEGER,
    out_of_range_calories REAL,
    fat_burn_calories REAL,
    cardio_calories REAL,
    peak_calories REAL,
    created_at INTEGER DEFAULT (strftime('%s','now') * 1000)
);

-- activity_summary: one row per day; steps, calories, distance, active mins
CREATE TABLE IF NOT EXISTS activity_summary (
    date TEXT PRIMARY KEY,
    steps INTEGER,
    calories_out INTEGER,
    activity_calories INTEGER,
    sedentary_minutes INTEGER,
    lightly_active_minutes INTEGER,
    fairly_active_minutes INTEGER,
    very_active_minutes INTEGER,
    distance_total REAL,                      -- in default unit (km or mi based on user setting)
    floors INTEGER,
    elevation REAL,
    created_at INTEGER DEFAULT (strftime('%s','now') * 1000)
);

-- spo2_summary: one row per day
CREATE TABLE IF NOT EXISTS spo2_summary (
    date TEXT PRIMARY KEY,
    avg REAL,                                 -- percentage
    min REAL,
    max REAL,
    created_at INTEGER DEFAULT (strftime('%s','now') * 1000)
);

-- hrv_summary: one row per day; Fitbit reports nightly RMSSD
CREATE TABLE IF NOT EXISTS hrv_summary (
    date TEXT PRIMARY KEY,
    daily_rmssd REAL,                         -- ms
    deep_rmssd REAL,                          -- ms during deep sleep specifically
    created_at INTEGER DEFAULT (strftime('%s','now') * 1000)
);

-- temp_summary: nightly wrist/skin temperature deviation
CREATE TABLE IF NOT EXISTS temp_summary (
    date TEXT PRIMARY KEY,
    nightly_relative REAL,                    -- deviation from baseline in default unit
    created_at INTEGER DEFAULT (strftime('%s','now') * 1000)
);

-- body_weight: log entries
CREATE TABLE IF NOT EXISTS body_weight (
    log_id TEXT PRIMARY KEY,
    date TEXT NOT NULL,
    time TEXT,
    weight REAL,                              -- in default unit (kg or lb)
    bmi REAL,
    fat REAL,
    source TEXT,
    created_at INTEGER DEFAULT (strftime('%s','now') * 1000)
);
CREATE INDEX IF NOT EXISTS idx_fitbit_body_weight_date ON body_weight(date);

-- profile: single row
CREATE TABLE IF NOT EXISTS profile (
    encoded_id TEXT PRIMARY KEY,
    display_name TEXT,
    timezone TEXT,
    distance_unit TEXT,
    weight_unit TEXT,
    height REAL,
    weight REAL,
    age INTEGER,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- Sync log
CREATE TABLE IF NOT EXISTS download_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    data_type TEXT,
    download_date DATETIME DEFAULT CURRENT_TIMESTAMP,
    records_count INTEGER,
    success BOOLEAN,
    error_message TEXT
);
