-- openclaw-biohub schema
-- Multi-source personal-health schema. health.db is source-agnostic
-- (any adapter rolls daily metrics into daily_metrics). Each adapter
-- keeps its own raw payload DB.
--
-- Apply each `-- DB N:` block to its own SQLite file.
--
-- Note: adapter-specific raw schemas live with their adapters:
--   pipeline/adapters/<slug>/schema.sql
-- The WHOOP raw schema below is historical; new adapters (Oura, Fitbit,
-- Apple Health, Garmin, …) own their own. See CONTRIBUTING.md.

-- ============================================================
-- DB 1: health.db  (source-agnostic — blood, supplements, nutrition,
--                   plus daily_metrics rollup from any adapter)
-- ============================================================

-- daily_metrics: one row per (source, date). Adapters INSERT OR REPLACE
-- on the composite primary key. Columns are best-effort common ground;
-- a missing column for a given source is simply NULL.
CREATE TABLE daily_metrics (
    source TEXT NOT NULL,            -- "whoop" | "oura" | "fitbit" | "apple-health" | "garmin"
    date TEXT NOT NULL,              -- ISO YYYY-MM-DD in the user's local TZ
    recovery_score INTEGER,
    hrv_ms REAL,
    resting_hr INTEGER,
    spo2 REAL,
    skin_temp_c REAL,
    sleep_performance INTEGER,
    sleep_hours REAL,
    sleep_efficiency REAL,
    rem_hours REAL,
    deep_sleep_hours REAL,
    light_sleep_hours REAL,
    day_strain REAL,
    calories_burned INTEGER,
    steps INTEGER,                   -- added for non-WHOOP sources
    active_minutes INTEGER,          -- added for non-WHOOP sources
    notes TEXT,
    created_at INTEGER DEFAULT (strftime('%s','now') * 1000),
    PRIMARY KEY (source, date)
);
CREATE INDEX idx_daily_metrics_date ON daily_metrics(date DESC);
CREATE INDEX idx_daily_metrics_source ON daily_metrics(source);

CREATE TABLE blood_panels (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    panel_date TEXT NOT NULL,
    lab_name TEXT,
    notes TEXT,
    source_filename TEXT,
    raw_text TEXT,
    created_at INTEGER DEFAULT (strftime('%s','now') * 1000)
);

CREATE TABLE blood_markers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    panel_id INTEGER REFERENCES blood_panels(id) ON DELETE CASCADE,
    marker_name TEXT NOT NULL,
    value REAL,
    unit TEXT,
    ref_low REAL,
    ref_high REAL,
    status TEXT CHECK(status IN ('low','normal','high','unknown')),
    created_at INTEGER DEFAULT (strftime('%s','now') * 1000)
);
CREATE INDEX idx_blood_markers_panel ON blood_markers(panel_id);

CREATE TABLE nutrition_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    log_date TEXT NOT NULL,
    meal_type TEXT DEFAULT 'day_total',
    calories INTEGER,
    protein_g REAL,
    carbs_g REAL,
    fat_g REAL,
    fiber_g REAL,
    water_ml INTEGER,
    notes TEXT,
    created_at INTEGER DEFAULT (strftime('%s','now') * 1000)
);
CREATE INDEX idx_nutrition_date ON nutrition_logs(log_date DESC);

CREATE TABLE supplements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    active_ingredient TEXT,
    brand TEXT,
    dose_mg REAL,
    dose_unit TEXT DEFAULT 'mg',
    form TEXT,
    amazon_asin TEXT,
    default_lag_hours INTEGER DEFAULT 24,
    notes TEXT,
    created_at INTEGER DEFAULT (strftime('%s','now') * 1000)
);
CREATE INDEX idx_supplements_asin ON supplements(amazon_asin);

CREATE TABLE supplement_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    supplement_id INTEGER REFERENCES supplements(id) ON DELETE CASCADE,
    taken_at TEXT NOT NULL,
    dose_mg REAL,
    dose_unit TEXT,
    notes TEXT,
    source TEXT DEFAULT 'manual',
    intake_start TEXT,
    intake_end TEXT,
    duration_days INTEGER,
    is_period INTEGER DEFAULT 0,
    amazon_order_id TEXT,
    created_at INTEGER DEFAULT (strftime('%s','now') * 1000)
);
CREATE INDEX idx_supplement_log_supplement_id ON supplement_log(supplement_id);
CREATE INDEX idx_supplement_log_taken_at ON supplement_log(taken_at);

-- body_composition: one row per date. `method` records how the
-- numbers were derived (jackson-pollock-7 / jackson-pollock-3 / scale /
-- dexa / apple-health / manual). Skinfold sites are optional — scale
-- and Apple Health rows only fill weight_kg.
CREATE TABLE body_composition (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL UNIQUE,
    method TEXT,
    body_fat_pct REAL,
    weight_kg REAL,
    lean_mass_kg REAL,
    fat_mass_kg REAL,
    chest_mm REAL,
    abdominal_mm REAL,
    thigh_mm REAL,
    tricep_mm REAL,
    subscapular_mm REAL,
    suprailiac_mm REAL,
    midaxillary_mm REAL,
    notes TEXT,
    created_at INTEGER DEFAULT (strftime('%s','now') * 1000)
);
CREATE INDEX idx_body_composition_date ON body_composition(date);

-- tracking_phases: user-defined windows the user wants overlaid on
-- their body-comp / metrics timeline. Categories are open-ended
-- ('training', 'diet', 'supplement', 'medication', 'lifestyle', or
-- anything else). end_date IS NULL means the phase is currently active.
CREATE TABLE tracking_phases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    category TEXT,
    start_date TEXT NOT NULL,
    end_date TEXT,
    color TEXT,
    notes TEXT,
    created_at INTEGER DEFAULT (strftime('%s','now') * 1000)
);
CREATE INDEX idx_tracking_phases_dates ON tracking_phases(start_date, end_date);

-- ============================================================
-- DB 2: whoop_raw.db  (was: whoop_analytics.db, all WHOOP API data)
-- ============================================================

CREATE TABLE user_profile (
    user_id INTEGER PRIMARY KEY,
    first_name TEXT,
    last_name TEXT,
    email TEXT,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE body_measurements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    height_meter REAL,
    weight_kilogram REAL,
    max_heart_rate INTEGER,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES user_profile (user_id)
);

CREATE TABLE recovery_data (
    cycle_id INTEGER PRIMARY KEY,
    sleep_id TEXT,
    user_id INTEGER,
    created_at DATETIME,
    updated_at DATETIME,
    score_state TEXT,
    user_calibrating BOOLEAN,
    recovery_score INTEGER,
    resting_heart_rate INTEGER,
    hrv_rmssd_milli REAL,
    spo2_percentage REAL,
    skin_temp_celsius REAL,
    FOREIGN KEY (user_id) REFERENCES user_profile (user_id)
);

CREATE TABLE sleep_data (
    id TEXT PRIMARY KEY,
    cycle_id INTEGER,
    v1_id INTEGER,
    user_id INTEGER,
    created_at DATETIME,
    updated_at DATETIME,
    start_time DATETIME,
    end_time DATETIME,
    timezone_offset TEXT,
    nap BOOLEAN,
    score_state TEXT,
    total_in_bed_time_milli INTEGER,
    total_awake_time_milli INTEGER,
    total_no_data_time_milli INTEGER,
    total_light_sleep_time_milli INTEGER,
    total_slow_wave_sleep_time_milli INTEGER,
    total_rem_sleep_time_milli INTEGER,
    sleep_cycle_count INTEGER,
    disturbance_count INTEGER,
    baseline_milli INTEGER,
    need_from_sleep_debt_milli INTEGER,
    need_from_recent_strain_milli INTEGER,
    need_from_recent_nap_milli INTEGER,
    respiratory_rate REAL,
    sleep_performance_percentage INTEGER,
    sleep_consistency_percentage INTEGER,
    sleep_efficiency_percentage REAL,
    FOREIGN KEY (user_id) REFERENCES user_profile (user_id)
);

CREATE TABLE workout_data (
    id TEXT PRIMARY KEY,
    v1_id INTEGER,
    user_id INTEGER,
    created_at DATETIME,
    updated_at DATETIME,
    start_time DATETIME,
    end_time DATETIME,
    timezone_offset TEXT,
    sport_name TEXT,
    sport_id INTEGER,
    score_state TEXT,
    strain REAL,
    average_heart_rate INTEGER,
    max_heart_rate INTEGER,
    kilojoule REAL,
    percent_recorded REAL,
    distance_meter REAL,
    altitude_gain_meter REAL,
    altitude_change_meter REAL,
    zone_zero_milli INTEGER,
    zone_one_milli INTEGER,
    zone_two_milli INTEGER,
    zone_three_milli INTEGER,
    zone_four_milli INTEGER,
    zone_five_milli INTEGER,
    FOREIGN KEY (user_id) REFERENCES user_profile (user_id)
);

CREATE TABLE cycles_data (
    id INTEGER PRIMARY KEY,
    user_id INTEGER,
    created_at DATETIME,
    updated_at DATETIME,
    start_time DATETIME,
    end_time DATETIME,
    timezone_offset TEXT,
    score_state TEXT,
    strain REAL,
    kilojoule REAL,
    average_heart_rate INTEGER,
    max_heart_rate INTEGER,
    FOREIGN KEY (user_id) REFERENCES user_profile (user_id)
);

CREATE TABLE download_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    data_type TEXT,
    download_date DATETIME DEFAULT CURRENT_TIMESTAMP,
    records_count INTEGER,
    success BOOLEAN,
    error_message TEXT
);

CREATE TABLE glucose_data (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device TEXT,
    serial_number TEXT,
    timestamp DATETIME NOT NULL,
    record_type INTEGER,
    glucose_mgdl REAL,
    notes TEXT,
    carbohydrates_g REAL,
    source TEXT DEFAULT 'libreview',
    imported_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(serial_number, timestamp, record_type)
);

CREATE TABLE cgm_glucose (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device TEXT,
    serial_number TEXT,
    timestamp TEXT,
    record_type INTEGER,
    glucose_history_mgdl REAL,
    glucose_scan_mgdl REAL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(serial_number, timestamp, record_type)
);
