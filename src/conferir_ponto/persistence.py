from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
import json
from pathlib import Path
import sqlite3
from typing import Any, Iterator
from uuid import uuid4


BASE_DIR = Path(__file__).resolve().parents[2]
APP_DB_PATH = BASE_DIR / "data" / "app.db"

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS reports (
    report_id TEXT PRIMARY KEY,
    filename TEXT NOT NULL,
    employee_name TEXT,
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

CREATE INDEX IF NOT EXISTS idx_reports_created_at
    ON reports(created_at DESC);

CREATE TABLE IF NOT EXISTS settings_current (
    scope TEXT PRIMARY KEY,
    payload_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS settings_audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    changed_at TEXT NOT NULL,
    actor TEXT NOT NULL,
    changes_json TEXT NOT NULL,
    settings_json TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_settings_audit_changed_at
    ON settings_audit(changed_at DESC);

CREATE TABLE IF NOT EXISTS users (
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
"""


def ensure_app_db() -> Path:
    APP_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(APP_DB_PATH)
    try:
        connection.executescript(SCHEMA_SQL)
        ensure_column(connection, "reports", "source_pdf_key", "TEXT")
        ensure_column(connection, "reports", "export_pdf_key", "TEXT")
        connection.commit()
    finally:
        connection.close()
    return APP_DB_PATH


def ensure_column(connection: sqlite3.Connection, table_name: str, column_name: str, column_type: str) -> None:
    columns = {
        row[1]
        for row in connection.execute(f"PRAGMA table_info({table_name})").fetchall()
    }
    if column_name not in columns:
        connection.execute(
            f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}"
        )


@contextmanager
def open_db() -> Iterator[sqlite3.Connection]:
    ensure_app_db()
    connection = sqlite3.connect(APP_DB_PATH)
    connection.row_factory = sqlite3.Row
    try:
        yield connection
        connection.commit()
    finally:
        connection.close()


def save_current_settings_payload(payload: dict[str, Any]) -> None:
    updated_at = datetime.now().isoformat(timespec="seconds")
    with open_db() as connection:
        connection.execute(
            """
            INSERT INTO settings_current (scope, payload_json, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(scope) DO UPDATE SET
                payload_json = excluded.payload_json,
                updated_at = excluded.updated_at
            """,
            ("global", json.dumps(payload, ensure_ascii=False), updated_at),
        )


def load_current_settings_payload() -> dict[str, Any] | None:
    if not APP_DB_PATH.exists():
        return None
    with open_db() as connection:
        row = connection.execute(
            "SELECT payload_json FROM settings_current WHERE scope = ?",
            ("global",),
        ).fetchone()
    if row is None:
        return None
    return json.loads(row["payload_json"])


def append_settings_audit_entry(entry: dict[str, Any]) -> None:
    with open_db() as connection:
        connection.execute(
            """
            INSERT INTO settings_audit (changed_at, actor, changes_json, settings_json)
            VALUES (?, ?, ?, ?)
            """,
            (
                entry["changedAt"],
                entry["actor"],
                json.dumps(entry.get("changes", []), ensure_ascii=False),
                json.dumps(entry.get("settings", {}), ensure_ascii=False),
            ),
        )


def load_settings_audit_entries(limit: int = 12) -> list[dict[str, Any]]:
    if not APP_DB_PATH.exists():
        return []
    with open_db() as connection:
        rows = connection.execute(
            """
            SELECT changed_at, actor, changes_json, settings_json
            FROM settings_audit
            ORDER BY changed_at DESC
            LIMIT ?
            """,
            (max(0, int(limit)),),
        ).fetchall()
    return [
        {
            "changedAt": row["changed_at"],
            "actor": row["actor"],
            "changes": json.loads(row["changes_json"]),
            "settings": json.loads(row["settings_json"]),
        }
        for row in rows
    ]


def upsert_report_record(
    report_id: str,
    filename: str,
    recent: dict[str, Any],
    payload: dict[str, Any],
    *,
    source_pdf_key: str | None = None,
    export_pdf_key: str | None = None,
    source_pdf_path: str | None = None,
    export_pdf_path: str | None = None,
) -> None:
    created_at = (
        recent.get("createdAt")
        or payload.get("meta", {}).get("generatedAt")
        or datetime.now().isoformat(timespec="seconds")
    )
    with open_db() as connection:
        connection.execute(
            """
            INSERT INTO reports (
                report_id,
                filename,
                employee_name,
                period_start,
                period_end,
                processed_at,
                created_at,
                processing_duration_ms,
                recent_json,
                payload_json,
                source_pdf_key,
                export_pdf_key,
                source_pdf_path,
                export_pdf_path
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(report_id) DO UPDATE SET
                filename = excluded.filename,
                employee_name = excluded.employee_name,
                period_start = excluded.period_start,
                period_end = excluded.period_end,
                processed_at = excluded.processed_at,
                created_at = excluded.created_at,
                processing_duration_ms = excluded.processing_duration_ms,
                recent_json = excluded.recent_json,
                payload_json = excluded.payload_json,
                source_pdf_key = excluded.source_pdf_key,
                export_pdf_key = excluded.export_pdf_key,
                source_pdf_path = excluded.source_pdf_path,
                export_pdf_path = excluded.export_pdf_path
            """,
            (
                report_id,
                filename,
                payload.get("employeeName"),
                payload.get("periodStart"),
                payload.get("periodEnd"),
                payload.get("processedAt"),
                created_at,
                payload.get("meta", {}).get("processingDurationMs"),
                json.dumps(recent, ensure_ascii=False),
                json.dumps(payload, ensure_ascii=False),
                source_pdf_key,
                export_pdf_key,
                source_pdf_path,
                export_pdf_path,
            ),
        )


def load_report_record(report_id: str) -> dict[str, Any] | None:
    if not APP_DB_PATH.exists():
        return None
    with open_db() as connection:
        row = connection.execute(
            """
            SELECT filename, recent_json, payload_json, source_pdf_key, export_pdf_key, source_pdf_path, export_pdf_path
            FROM reports
            WHERE report_id = ?
            """,
            (report_id,),
        ).fetchone()
    if row is None:
        return None
    return {
        "reportId": report_id,
        "filename": row["filename"],
        "recent": json.loads(row["recent_json"]),
        "payload": json.loads(row["payload_json"]),
        "sourcePdfKey": row["source_pdf_key"],
        "exportPdfKey": row["export_pdf_key"],
        "sourcePdfPath": row["source_pdf_path"],
        "exportPdfPath": row["export_pdf_path"],
    }


def list_recent_report_records(limit: int) -> list[dict[str, Any]]:
    if not APP_DB_PATH.exists():
        return []
    with open_db() as connection:
        rows = connection.execute(
            """
            SELECT recent_json
            FROM reports
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (max(0, int(limit)),),
        ).fetchall()
    return [json.loads(row["recent_json"]) for row in rows]


def stale_report_ids(max_records: int) -> list[str]:
    if not APP_DB_PATH.exists():
        return []
    with open_db() as connection:
        rows = connection.execute(
            """
            SELECT report_id
            FROM reports
            ORDER BY created_at DESC
            LIMIT -1 OFFSET ?
            """,
            (max(0, int(max_records)),),
        ).fetchall()
    return [row["report_id"] for row in rows]


def delete_report_record(report_id: str) -> None:
    if not APP_DB_PATH.exists():
        return
    with open_db() as connection:
        connection.execute("DELETE FROM reports WHERE report_id = ?", (report_id,))


def load_user_by_username(username: str) -> dict[str, Any] | None:
    if not APP_DB_PATH.exists():
        return None
    normalized_username = str(username or "").strip()
    if not normalized_username:
        return None
    with open_db() as connection:
        row = connection.execute(
            """
            SELECT id, username, email, display_name, password_hash, role, is_active, created_at, updated_at
            FROM users
            WHERE username = ?
            """,
            (normalized_username,),
        ).fetchone()
    if row is None:
        return None
    return {
        "id": row["id"],
        "username": row["username"],
        "email": row["email"],
        "displayName": row["display_name"],
        "passwordHash": row["password_hash"],
        "role": row["role"],
        "isActive": bool(row["is_active"]),
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
    }


def list_users(limit: int = 100) -> list[dict[str, Any]]:
    if not APP_DB_PATH.exists():
        return []
    with open_db() as connection:
        rows = connection.execute(
            """
            SELECT id, username, email, display_name, role, is_active, created_at, updated_at
            FROM users
            ORDER BY created_at ASC
            LIMIT ?
            """,
            (max(1, int(limit)),),
        ).fetchall()
    return [
        {
            "id": row["id"],
            "username": row["username"],
            "email": row["email"],
            "displayName": row["display_name"],
            "role": row["role"],
            "isActive": bool(row["is_active"]),
            "createdAt": row["created_at"],
            "updatedAt": row["updated_at"],
        }
        for row in rows
    ]


def create_user(
    *,
    username: str,
    password_hash: str,
    role: str = "user",
    email: str | None = None,
    display_name: str | None = None,
    is_active: bool = True,
) -> dict[str, Any]:
    normalized_username = str(username or "").strip()
    if not normalized_username:
        raise ValueError("Nome de usuário é obrigatório.")
    now = datetime.now().isoformat(timespec="seconds")
    user_id = uuid4().hex
    with open_db() as connection:
        existing = connection.execute(
            "SELECT 1 FROM users WHERE username = ?",
            (normalized_username,),
        ).fetchone()
        if existing is not None:
            raise ValueError("Usuário já existe.")
        connection.execute(
            """
            INSERT INTO users (
                id, username, email, display_name, password_hash, role, is_active, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                normalized_username,
                email,
                display_name,
                password_hash,
                role,
                1 if is_active else 0,
                now,
                now,
            ),
        )
    return load_user_by_username(normalized_username) or {}


def upsert_user(
    *,
    username: str,
    password_hash: str,
    role: str = "user",
    email: str | None = None,
    display_name: str | None = None,
    is_active: bool = True,
) -> dict[str, Any]:
    normalized_username = str(username or "").strip()
    if not normalized_username:
        raise ValueError("Nome de usuário é obrigatório.")
    existing = load_user_by_username(normalized_username)
    now = datetime.now().isoformat(timespec="seconds")
    with open_db() as connection:
        if existing is None:
            connection.execute(
                """
                INSERT INTO users (
                    id, username, email, display_name, password_hash, role, is_active, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    uuid4().hex,
                    normalized_username,
                    email,
                    display_name,
                    password_hash,
                    role,
                    1 if is_active else 0,
                    now,
                    now,
                ),
            )
        else:
            connection.execute(
                """
                UPDATE users
                SET email = ?, display_name = ?, password_hash = ?, role = ?, is_active = ?, updated_at = ?
                WHERE username = ?
                """,
                (
                    email,
                    display_name,
                    password_hash,
                    role,
                    1 if is_active else 0,
                    now,
                    normalized_username,
                ),
            )
    return load_user_by_username(normalized_username) or {}
