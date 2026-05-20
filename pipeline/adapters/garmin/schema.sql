-- ============================================================
-- DB: garmin_raw.db  (raw Garmin Connect Web payloads)
-- ============================================================
-- Garmin does NOT expose a public Health API for individual users.
-- This adapter uses the `garth` library, which authenticates against
-- the consumer Garmin Connect Web site. EXPERIMENTAL: Garmin can
-- break this at any time without notice.

CREATE TABLE IF NOT EXISTS sleep_summary (
    date TEXT PRIMARY KEY,
    sleep_score INTEGER,                      -- 0-100; recent Garmin watches
    total_sleep_seconds INTEGER,
    deep_sleep_seconds INTEGER,
    light_sleep_seconds INTEGER,
    rem_sleep_seconds INTEGER,
    awake_seconds INTEGER,
    sleep_start_gmt TEXT,
    sleep_end_gmt TEXT,
    average_respiration REAL,
    average_spo2 REAL,
    average_hrv REAL,                         -- ms; some watches; daily_rmssd
    average_stress_during_sleep INTEGER,
    created_at INTEGER DEFAULT (strftime('%s','now') * 1000)
);

CREATE TABLE IF NOT EXISTS activity_summary (
    date TEXT PRIMARY KEY,
    total_steps INTEGER,
    total_distance_meters REAL,
    active_kilocalories REAL,
    bmr_kilocalories REAL,
    sedentary_minutes INTEGER,
    moderate_intensity_minutes INTEGER,
    vigorous_intensity_minutes INTEGER,
    floors_climbed INTEGER,
    created_at INTEGER DEFAULT (strftime('%s','now') * 1000)
);

CREATE TABLE IF NOT EXISTS heart_rate_summary (
    date TEXT PRIMARY KEY,
    resting_heart_rate INTEGER,
    min_heart_rate INTEGER,
    max_heart_rate INTEGER,
    last_seven_days_avg_resting_hr INTEGER,
    created_at INTEGER DEFAULT (strftime('%s','now') * 1000)
);

CREATE TABLE IF NOT EXISTS stress_summary (
    date TEXT PRIMARY KEY,
    average_stress_level INTEGER,             -- 0-100
    max_stress_level INTEGER,
    body_battery_charged INTEGER,
    body_battery_drained INTEGER,
    body_battery_highest INTEGER,
    body_battery_lowest INTEGER,
    created_at INTEGER DEFAULT (strftime('%s','now') * 1000)
);

CREATE TABLE IF NOT EXISTS hrv_summary (
    date TEXT PRIMARY KEY,
    weekly_avg REAL,
    last_night_avg REAL,
    last_night_5_min_high REAL,
    status TEXT,                              -- "BALANCED" | "LOW" | "POOR" | "UNBALANCED"
    feedback_phrase TEXT,
    created_at INTEGER DEFAULT (strftime('%s','now') * 1000)
);

CREATE TABLE IF NOT EXISTS download_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    data_type TEXT,
    download_date DATETIME DEFAULT CURRENT_TIMESTAMP,
    records_count INTEGER,
    success BOOLEAN,
    error_message TEXT
);
