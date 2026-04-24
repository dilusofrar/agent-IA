CREATE TABLE reports (
    report_id TEXT PRIMARY KEY,
    filename TEXT NOT NULL,
    employee_name TEXT,
    owner_user_id TEXT,
    owner_username TEXT,
    period_start TEXT,
    period_end TEXT,
    processed_at TEXT,
    created_at TEXT NOT NULL,
    processing_duration_ms INTEGER,
    recent_json TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    source_pdf_key TEXT,
    export_pdf_key TEXT,
    source_pdf_path TEXT,
    export_pdf_path TEXT
);

CREATE INDEX idx_reports_created_at
    ON reports(created_at DESC);

CREATE TABLE settings_current (
    scope TEXT PRIMARY KEY,
    payload_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE settings_audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    changed_at TEXT NOT NULL,
    actor TEXT NOT NULL,
    changes_json TEXT NOT NULL,
    settings_json TEXT NOT NULL
);

CREATE INDEX idx_settings_audit_changed_at
    ON settings_audit(changed_at DESC);

CREATE TABLE users (
    id TEXT PRIMARY KEY,
    username TEXT NOT NULL UNIQUE,
    email TEXT,
    display_name TEXT,
    password_hash TEXT,
    role TEXT NOT NULL DEFAULT 'user',
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
