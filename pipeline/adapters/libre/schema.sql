-- libre_raw.db — FreeStyle Libre 3 / LibreView continuous-glucose data.
--
-- Populated by the Libre adapter from LibreView CSV exports or Health-Auto-
-- Export-style JSON dumps. Glucose is sub-daily (a reading every ~5-15 min),
-- so it lives in its own tables rather than the daily_metrics rollup; the
-- glucose_analytics.py helper + the dashboard "Glucose" tab read it here.

CREATE TABLE IF NOT EXISTS glucose_data (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device TEXT,
    serial_number TEXT,
    timestamp DATETIME NOT NULL,
    record_type INTEGER,          -- 0=historic, 1=scan, 2=strip, 5=insulin, 6=meal, 7=long-acting
    glucose_mgdl REAL,            -- historic or scan glucose (mg/dL)
    notes TEXT,
    carbohydrates_g REAL,
    source TEXT DEFAULT 'libreview',
    imported_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(serial_number, timestamp, record_type)
);

CREATE INDEX IF NOT EXISTS idx_glucose_timestamp ON glucose_data(timestamp);

-- Raw dual-column form some LibreView exports use (separate history/scan
-- columns per row). Kept for fidelity; glucose_data is the query surface.
CREATE TABLE IF NOT EXISTS cgm_glucose (
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

CREATE TABLE IF NOT EXISTS import_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_path TEXT,
    file_mtime REAL,
    records_count INTEGER,
    success INTEGER,
    error_message TEXT,
    imported_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(file_path, file_mtime)
);
