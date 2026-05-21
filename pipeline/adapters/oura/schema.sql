-- ============================================================
-- DB: oura_raw.db  (raw Oura Ring API v2 payloads)
-- ============================================================
-- Endpoints under https://api.ouraring.com/v2/usercollection/
-- Auth: Personal Access Token (Bearer) — no OAuth needed.
-- All times are ISO 8601 UTC strings unless noted.

-- /daily_sleep — one row per day, sleep score breakdown
CREATE TABLE IF NOT EXISTS daily_sleep (
    id TEXT PRIMARY KEY,                -- Oura's stable id
    day TEXT NOT NULL UNIQUE,           -- ISO YYYY-MM-DD
    score INTEGER,                       -- 0-100 overall sleep score
    timestamp TEXT,
    contributors_deep_sleep INTEGER,
    contributors_efficiency INTEGER,
    contributors_latency INTEGER,
    contributors_rem_sleep INTEGER,
    contributors_restfulness INTEGER,
    contributors_timing INTEGER,
    contributors_total_sleep INTEGER,
    created_at INTEGER DEFAULT (strftime('%s','now') * 1000)
);

-- /sleep — detailed sleep sessions (long sleep + naps)
CREATE TABLE IF NOT EXISTS sleep_session (
    id TEXT PRIMARY KEY,
    day TEXT NOT NULL,                  -- ISO YYYY-MM-DD this session is anchored to
    bedtime_start TEXT,
    bedtime_end TEXT,
    type TEXT,                          -- "long_sleep" | "nap" | "deleted"
    total_sleep_duration INTEGER,       -- seconds
    awake_time INTEGER,
    light_sleep_duration INTEGER,
    rem_sleep_duration INTEGER,
    deep_sleep_duration INTEGER,
    time_in_bed INTEGER,
    sleep_efficiency REAL,
    latency INTEGER,
    average_breath REAL,
    average_heart_rate REAL,
    lowest_heart_rate REAL,
    average_hrv REAL,                   -- ms — Oura's nightly HRV
    restless_periods INTEGER,
    created_at INTEGER DEFAULT (strftime('%s','now') * 1000)
);
CREATE INDEX IF NOT EXISTS idx_sleep_session_day ON sleep_session(day);

-- /daily_readiness — daily readiness score (Oura's analogue to "recovery")
CREATE TABLE IF NOT EXISTS daily_readiness (
    id TEXT PRIMARY KEY,
    day TEXT NOT NULL UNIQUE,
    score INTEGER,                       -- 0-100
    temperature_deviation REAL,          -- °C deviation from baseline
    temperature_trend_deviation REAL,
    timestamp TEXT,
    contributors_activity_balance INTEGER,
    contributors_body_temperature INTEGER,
    contributors_hrv_balance INTEGER,
    contributors_previous_day_activity INTEGER,
    contributors_previous_night INTEGER,
    contributors_recovery_index INTEGER,
    contributors_resting_heart_rate INTEGER,
    contributors_sleep_balance INTEGER,
    created_at INTEGER DEFAULT (strftime('%s','now') * 1000)
);

-- /daily_activity — daily activity summary
CREATE TABLE IF NOT EXISTS daily_activity (
    id TEXT PRIMARY KEY,
    day TEXT NOT NULL UNIQUE,
    score INTEGER,
    steps INTEGER,
    active_calories INTEGER,
    total_calories INTEGER,
    target_calories INTEGER,
    equivalent_walking_distance INTEGER,
    high_activity_time INTEGER,
    medium_activity_time INTEGER,
    low_activity_time INTEGER,
    sedentary_time INTEGER,
    non_wear_time INTEGER,
    resting_time INTEGER,
    average_met_minutes REAL,
    timestamp TEXT,
    created_at INTEGER DEFAULT (strftime('%s','now') * 1000)
);

-- /daily_spo2 — daily SpO₂ aggregate
CREATE TABLE IF NOT EXISTS daily_spo2 (
    id TEXT PRIMARY KEY,
    day TEXT NOT NULL UNIQUE,
    spo2_percentage_average REAL,
    spo2_percentage_lowest REAL,
    breathing_disturbance_index REAL,
    created_at INTEGER DEFAULT (strftime('%s','now') * 1000)
);

-- /personal_info — user profile (single row)
CREATE TABLE IF NOT EXISTS personal_info (
    id TEXT PRIMARY KEY,
    age INTEGER,
    weight REAL,
    height REAL,
    biological_sex TEXT,
    email TEXT,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- /workout — workout sessions
CREATE TABLE IF NOT EXISTS workout (
    id TEXT PRIMARY KEY,
    day TEXT NOT NULL,
    activity TEXT,
    start_datetime TEXT,
    end_datetime TEXT,
    distance REAL,
    calories REAL,
    intensity TEXT,
    label TEXT,
    source TEXT,
    created_at INTEGER DEFAULT (strftime('%s','now') * 1000)
);
CREATE INDEX IF NOT EXISTS idx_workout_day ON workout(day);

-- Sync log (mirrors WHOOP's download_log pattern)
CREATE TABLE IF NOT EXISTS download_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    data_type TEXT,
    download_date DATETIME DEFAULT CURRENT_TIMESTAMP,
    records_count INTEGER,
    success BOOLEAN,
    error_message TEXT
);
