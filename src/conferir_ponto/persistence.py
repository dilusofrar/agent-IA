from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
import json
import logging
import os
from pathlib import Path
import sqlite3
from typing import Any, Iterator
from uuid import uuid4

from conferir_ponto.d1_api import D1ApiClient, d1_from_env


BASE_DIR = Path(__file__).resolve().parents[2]
APP_DB_PATH = BASE_DIR / "data" / "app.db"
LOGGER = logging.getLogger("conferir_ponto.persistence")
_D1_CLIENT: D1ApiClient | None | bool = False

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS reports (
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
        ensure_column(connection, "reports", "owner_user_id", "TEXT")
        ensure_column(connection, "reports", "owner_username", "TEXT")
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


def d1_client() -> D1ApiClient | None:
    global _D1_CLIENT
    if _D1_CLIENT is False:
        client = d1_from_env()
        if client is not None:
            try:
                client.ensure_schema()
            except Exception as exc:
                LOGGER.warning("d1_schema_ensure_failed", extra={"error": str(exc)})
                client = None
        _D1_CLIENT = client
    return _D1_CLIENT if _D1_CLIENT is not False else None


def persistence_backend_name() -> str:
    return "sqlite+d1" if d1_client() is not None else "sqlite"


def prefer_d1_reads() -> bool:
    raw_value = os.getenv("D1_PREFER_READS", "true").strip().lower()
    return raw_value not in {"0", "false", "no", "off"}


def d1_status() -> dict[str, Any]:
    client = d1_client()
    return {
        "enabled": client is not None,
        "backend": persistence_backend_name(),
        "preferReads": bool(client is not None and prefer_d1_reads()),
        "databaseId": getattr(client, "database_id", None) if client is not None else None,
        "accountId": getattr(client, "account_id", None) if client is not None else None,
    }


def mirror_execute(sql: str, params: tuple[Any, ...] | list[Any] = ()) -> None:
    client = d1_client()
    if client is None:
        return
    try:
        client.execute(sql, list(params))
    except Exception as exc:
        LOGGER.warning("d1_mirror_execute_failed", extra={"error": str(exc), "sql": sql})


def mirror_fetch_one(sql: str, params: tuple[Any, ...] | list[Any] = ()) -> dict[str, Any] | None:
    client = d1_client()
    if client is None:
        return None
    try:
        rows = client.query(sql, list(params))
    except Exception as exc:
        LOGGER.warning("d1_mirror_fetch_failed", extra={"error": str(exc), "sql": sql})
        return None
    return rows[0] if rows else None


def mirror_fetch_all(sql: str, params: tuple[Any, ...] | list[Any] = ()) -> list[dict[str, Any]]:
    client = d1_client()
    if client is None:
        return []
    try:
        return client.query(sql, list(params))
    except Exception as exc:
        LOGGER.warning("d1_mirror_fetch_failed", extra={"error": str(exc), "sql": sql})
        return []


def sync_local_state_to_d1() -> dict[str, int]:
    client = d1_client()
    if client is None:
        raise RuntimeError("D1 não configurado.")
    ensure_app_db()
    summary = {"settingsCurrent": 0, "settingsAudit": 0, "reports": 0, "users": 0}
    client.execute_script(
        """
        DELETE FROM settings_current;
        DELETE FROM settings_audit;
        DELETE FROM reports;
        DELETE FROM users;
        """
    )
    with open_db() as connection:
        settings_rows = connection.execute(
            "SELECT scope, payload_json, updated_at FROM settings_current"
        ).fetchall()
        for row in settings_rows:
            client.execute(
                """
                INSERT INTO settings_current (scope, payload_json, updated_at)
                VALUES (?, ?, ?)
                """,
                [row["scope"], row["payload_json"], row["updated_at"]],
            )
            summary["settingsCurrent"] += 1

        audit_rows = connection.execute(
            "SELECT changed_at, actor, changes_json, settings_json FROM settings_audit ORDER BY id ASC"
        ).fetchall()
        for row in audit_rows:
            client.execute(
                """
                INSERT INTO settings_audit (changed_at, actor, changes_json, settings_json)
                VALUES (?, ?, ?, ?)
                """,
                [row["changed_at"], row["actor"], row["changes_json"], row["settings_json"]],
            )
            summary["settingsAudit"] += 1

        report_rows = connection.execute(
            """
            SELECT report_id, filename, employee_name, owner_user_id, owner_username, period_start, period_end,
                   processed_at, created_at, processing_duration_ms, recent_json, payload_json, source_pdf_key,
                   export_pdf_key, source_pdf_path, export_pdf_path
            FROM reports
            ORDER BY created_at ASC
            """
        ).fetchall()
        for row in report_rows:
            client.execute(
                """
                INSERT INTO reports (
                    report_id, filename, employee_name, owner_user_id, owner_username, period_start, period_end,
                    processed_at, created_at, processing_duration_ms, recent_json, payload_json, source_pdf_key,
                    export_pdf_key, source_pdf_path, export_pdf_path
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    row["report_id"],
                    row["filename"],
                    row["employee_name"],
                    row["owner_user_id"],
                    row["owner_username"],
                    row["period_start"],
                    row["period_end"],
                    row["processed_at"],
                    row["created_at"],
                    row["processing_duration_ms"],
                    row["recent_json"],
                    row["payload_json"],
                    row["source_pdf_key"],
                    row["export_pdf_key"],
                    row["source_pdf_path"],
                    row["export_pdf_path"],
                ],
            )
            summary["reports"] += 1

        user_rows = connection.execute(
            """
            SELECT id, username, email, display_name, password_hash, role, is_active, created_at, updated_at
            FROM users
            ORDER BY created_at ASC
            """
        ).fetchall()
        for row in user_rows:
            client.execute(
                """
                INSERT INTO users (
                    id, username, email, display_name, password_hash, role, is_active, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    row["id"],
                    row["username"],
                    row["email"],
                    row["display_name"],
                    row["password_hash"],
                    row["role"],
                    row["is_active"],
                    row["created_at"],
                    row["updated_at"],
                ],
            )
            summary["users"] += 1
    return summary


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
    mirror_execute(
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
    if d1_client() is not None and prefer_d1_reads():
        d1_row = mirror_fetch_one(
            "SELECT payload_json FROM settings_current WHERE scope = ?",
            ("global",),
        )
        if d1_row is not None:
            return json.loads(d1_row["payload_json"])
    if not APP_DB_PATH.exists():
        d1_row = mirror_fetch_one(
            "SELECT payload_json FROM settings_current WHERE scope = ?",
            ("global",),
        )
        if d1_row is None:
            return None
        return json.loads(d1_row["payload_json"])
    with open_db() as connection:
        row = connection.execute(
            "SELECT payload_json FROM settings_current WHERE scope = ?",
            ("global",),
        ).fetchone()
    if row is not None:
        return json.loads(row["payload_json"])
    d1_row = mirror_fetch_one(
        "SELECT payload_json FROM settings_current WHERE scope = ?",
        ("global",),
    )
    if d1_row is None:
        return None
    return json.loads(d1_row["payload_json"])


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
    mirror_execute(
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
    if d1_client() is not None and prefer_d1_reads():
        d1_rows = mirror_fetch_all(
            """
            SELECT changed_at, actor, changes_json, settings_json
            FROM settings_audit
            ORDER BY changed_at DESC
            LIMIT ?
            """,
            (max(0, int(limit)),),
        )
        if d1_rows:
            return [
                {
                    "changedAt": row["changed_at"],
                    "actor": row["actor"],
                    "changes": json.loads(row["changes_json"]),
                    "settings": json.loads(row["settings_json"]),
                }
                for row in d1_rows
            ]
    if not APP_DB_PATH.exists():
        d1_rows = mirror_fetch_all(
            """
            SELECT changed_at, actor, changes_json, settings_json
            FROM settings_audit
            ORDER BY changed_at DESC
            LIMIT ?
            """,
            (max(0, int(limit)),),
        )
        return [
            {
                "changedAt": row["changed_at"],
                "actor": row["actor"],
                "changes": json.loads(row["changes_json"]),
                "settings": json.loads(row["settings_json"]),
            }
            for row in d1_rows
        ]
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
    if rows:
        return [
            {
                "changedAt": row["changed_at"],
                "actor": row["actor"],
                "changes": json.loads(row["changes_json"]),
                "settings": json.loads(row["settings_json"]),
            }
            for row in rows
        ]
    d1_rows = mirror_fetch_all(
        """
        SELECT changed_at, actor, changes_json, settings_json
        FROM settings_audit
        ORDER BY changed_at DESC
        LIMIT ?
        """,
        (max(0, int(limit)),),
    )
    return [
        {
            "changedAt": row["changed_at"],
            "actor": row["actor"],
            "changes": json.loads(row["changes_json"]),
            "settings": json.loads(row["settings_json"]),
        }
        for row in d1_rows
    ]


def upsert_report_record(
    report_id: str,
    filename: str,
    recent: dict[str, Any],
    payload: dict[str, Any],
    *,
    owner_user_id: str | None = None,
    owner_username: str | None = None,
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
                owner_user_id,
                owner_username,
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
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(report_id) DO UPDATE SET
                filename = excluded.filename,
                employee_name = excluded.employee_name,
                owner_user_id = excluded.owner_user_id,
                owner_username = excluded.owner_username,
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
                owner_user_id,
                owner_username,
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
    mirror_execute(
        """
        INSERT INTO reports (
            report_id,
            filename,
            employee_name,
            owner_user_id,
            owner_username,
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
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(report_id) DO UPDATE SET
            filename = excluded.filename,
            employee_name = excluded.employee_name,
            owner_user_id = excluded.owner_user_id,
            owner_username = excluded.owner_username,
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
            owner_user_id,
            owner_username,
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
    if d1_client() is not None and prefer_d1_reads():
        selected_row = mirror_fetch_one(
            """
            SELECT filename, owner_user_id, owner_username, recent_json, payload_json, source_pdf_key, export_pdf_key, source_pdf_path, export_pdf_path
            FROM reports
            WHERE report_id = ?
            """,
            (report_id,),
        )
        if selected_row is not None:
            return {
                "reportId": report_id,
                "filename": selected_row["filename"],
                "ownerUserId": selected_row["owner_user_id"],
                "ownerUsername": selected_row["owner_username"],
                "recent": json.loads(selected_row["recent_json"]),
                "payload": json.loads(selected_row["payload_json"]),
                "sourcePdfKey": selected_row["source_pdf_key"],
                "exportPdfKey": selected_row["export_pdf_key"],
                "sourcePdfPath": selected_row["source_pdf_path"],
                "exportPdfPath": selected_row["export_pdf_path"],
            }
    if not APP_DB_PATH.exists():
        selected_row = mirror_fetch_one(
            """
            SELECT filename, owner_user_id, owner_username, recent_json, payload_json, source_pdf_key, export_pdf_key, source_pdf_path, export_pdf_path
            FROM reports
            WHERE report_id = ?
            """,
            (report_id,),
        )
        if selected_row is None:
            return None
        return {
            "reportId": report_id,
            "filename": selected_row["filename"],
            "ownerUserId": selected_row["owner_user_id"],
            "ownerUsername": selected_row["owner_username"],
            "recent": json.loads(selected_row["recent_json"]),
            "payload": json.loads(selected_row["payload_json"]),
            "sourcePdfKey": selected_row["source_pdf_key"],
            "exportPdfKey": selected_row["export_pdf_key"],
            "sourcePdfPath": selected_row["source_pdf_path"],
            "exportPdfPath": selected_row["export_pdf_path"],
        }
    with open_db() as connection:
        row = connection.execute(
            """
            SELECT filename, owner_user_id, owner_username, recent_json, payload_json, source_pdf_key, export_pdf_key, source_pdf_path, export_pdf_path
            FROM reports
            WHERE report_id = ?
            """,
            (report_id,),
        ).fetchone()
    selected_row: Any = row
    if selected_row is None:
        selected_row = mirror_fetch_one(
            """
            SELECT filename, owner_user_id, owner_username, recent_json, payload_json, source_pdf_key, export_pdf_key, source_pdf_path, export_pdf_path
            FROM reports
            WHERE report_id = ?
            """,
            (report_id,),
        )
    if selected_row is None:
        return None
    return {
        "reportId": report_id,
        "filename": selected_row["filename"],
        "ownerUserId": selected_row["owner_user_id"],
        "ownerUsername": selected_row["owner_username"],
        "recent": json.loads(selected_row["recent_json"]),
        "payload": json.loads(selected_row["payload_json"]),
        "sourcePdfKey": selected_row["source_pdf_key"],
        "exportPdfKey": selected_row["export_pdf_key"],
        "sourcePdfPath": selected_row["source_pdf_path"],
        "exportPdfPath": selected_row["export_pdf_path"],
    }


def list_recent_report_records(limit: int) -> list[dict[str, Any]]:
    if d1_client() is not None and prefer_d1_reads():
        d1_rows = mirror_fetch_all(
            """
            SELECT recent_json
            FROM reports
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (max(0, int(limit)),),
        )
        if d1_rows:
            return [json.loads(row["recent_json"]) for row in d1_rows]
    if not APP_DB_PATH.exists():
        d1_rows = mirror_fetch_all(
            """
            SELECT recent_json
            FROM reports
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (max(0, int(limit)),),
        )
        return [json.loads(row["recent_json"]) for row in d1_rows]
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
    if rows:
        return [json.loads(row["recent_json"]) for row in rows]
    d1_rows = mirror_fetch_all(
        """
        SELECT recent_json
        FROM reports
        ORDER BY created_at DESC
        LIMIT ?
        """,
        (max(0, int(limit)),),
    )
    return [json.loads(row["recent_json"]) for row in d1_rows]


def update_user(
    username: str,
    *,
    password_hash: str | None = None,
    role: str | None = None,
    email: str | None = None,
    display_name: str | None = None,
    is_active: bool | None = None,
) -> dict[str, Any]:
    normalized_username = str(username or "").strip()
    if not normalized_username:
        raise ValueError("Nome de usuário é obrigatório.")
    existing = load_user_by_username(normalized_username)
    if existing is None:
        raise ValueError("Usuário não encontrado.")
    now = datetime.now().isoformat(timespec="seconds")
    with open_db() as connection:
        connection.execute(
            """
            UPDATE users
            SET email = ?, display_name = ?, password_hash = ?, role = ?, is_active = ?, updated_at = ?
            WHERE username = ?
            """,
            (
                email if email is not None else existing.get("email"),
                display_name if display_name is not None else existing.get("displayName"),
                password_hash if password_hash is not None else existing.get("passwordHash"),
                role if role is not None else existing.get("role"),
                1 if (is_active if is_active is not None else existing.get("isActive")) else 0,
                now,
                normalized_username,
            ),
        )
    mirror_execute(
        """
        INSERT INTO users (
            id, username, email, display_name, password_hash, role, is_active, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(username) DO UPDATE SET
            email = excluded.email,
            display_name = excluded.display_name,
            password_hash = excluded.password_hash,
            role = excluded.role,
            is_active = excluded.is_active,
            updated_at = excluded.updated_at
        """,
        (
            existing.get("id"),
            normalized_username,
            email if email is not None else existing.get("email"),
            display_name if display_name is not None else existing.get("displayName"),
            password_hash if password_hash is not None else existing.get("passwordHash"),
            role if role is not None else existing.get("role"),
            1 if (is_active if is_active is not None else existing.get("isActive")) else 0,
            existing.get("createdAt"),
            now,
        ),
    )
    return load_user_by_username(normalized_username) or {}


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
        mirror_execute("DELETE FROM reports WHERE report_id = ?", (report_id,))
        return
    with open_db() as connection:
        connection.execute("DELETE FROM reports WHERE report_id = ?", (report_id,))
    mirror_execute("DELETE FROM reports WHERE report_id = ?", (report_id,))


def load_user_by_username(username: str) -> dict[str, Any] | None:
    normalized_username = str(username or "").strip()
    if not normalized_username:
        return None
    if d1_client() is not None and prefer_d1_reads():
        selected_row = mirror_fetch_one(
            """
            SELECT id, username, email, display_name, password_hash, role, is_active, created_at, updated_at
            FROM users
            WHERE username = ?
            """,
            (normalized_username,),
        )
        if selected_row is not None:
            return {
                "id": selected_row["id"],
                "username": selected_row["username"],
                "email": selected_row["email"],
                "displayName": selected_row["display_name"],
                "passwordHash": selected_row["password_hash"],
                "role": selected_row["role"],
                "isActive": bool(selected_row["is_active"]),
                "createdAt": selected_row["created_at"],
                "updatedAt": selected_row["updated_at"],
            }
    if not APP_DB_PATH.exists():
        selected_row = mirror_fetch_one(
            """
            SELECT id, username, email, display_name, password_hash, role, is_active, created_at, updated_at
            FROM users
            WHERE username = ?
            """,
            (normalized_username,),
        )
        if selected_row is None:
            return None
        return {
            "id": selected_row["id"],
            "username": selected_row["username"],
            "email": selected_row["email"],
            "displayName": selected_row["display_name"],
            "passwordHash": selected_row["password_hash"],
            "role": selected_row["role"],
            "isActive": bool(selected_row["is_active"]),
            "createdAt": selected_row["created_at"],
            "updatedAt": selected_row["updated_at"],
        }
    with open_db() as connection:
        row = connection.execute(
            """
            SELECT id, username, email, display_name, password_hash, role, is_active, created_at, updated_at
            FROM users
            WHERE username = ?
            """,
            (normalized_username,),
        ).fetchone()
    selected_row: Any = row
    if selected_row is None:
        selected_row = mirror_fetch_one(
            """
            SELECT id, username, email, display_name, password_hash, role, is_active, created_at, updated_at
            FROM users
            WHERE username = ?
            """,
            (normalized_username,),
        )
    if selected_row is None:
        return None
    return {
        "id": selected_row["id"],
        "username": selected_row["username"],
        "email": selected_row["email"],
        "displayName": selected_row["display_name"],
        "passwordHash": selected_row["password_hash"],
        "role": selected_row["role"],
        "isActive": bool(selected_row["is_active"]),
        "createdAt": selected_row["created_at"],
        "updatedAt": selected_row["updated_at"],
    }


def list_users(limit: int = 100) -> list[dict[str, Any]]:
    if d1_client() is not None and prefer_d1_reads():
        selected_rows = mirror_fetch_all(
            """
            SELECT id, username, email, display_name, role, is_active, created_at, updated_at
            FROM users
            ORDER BY created_at ASC
            LIMIT ?
            """,
            (max(1, int(limit)),),
        )
        if selected_rows:
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
                for row in selected_rows
            ]
    if not APP_DB_PATH.exists():
        selected_rows = mirror_fetch_all(
            """
            SELECT id, username, email, display_name, role, is_active, created_at, updated_at
            FROM users
            ORDER BY created_at ASC
            LIMIT ?
            """,
            (max(1, int(limit)),),
        )
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
            for row in selected_rows
        ]
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
    selected_rows: Any = rows
    if not selected_rows:
        selected_rows = mirror_fetch_all(
            """
            SELECT id, username, email, display_name, role, is_active, created_at, updated_at
            FROM users
            ORDER BY created_at ASC
            LIMIT ?
            """,
            (max(1, int(limit)),),
        )
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
        for row in selected_rows
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
    mirror_execute(
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
    mirror_execute(
        """
        INSERT INTO users (
            id, username, email, display_name, password_hash, role, is_active, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(username) DO UPDATE SET
            email = excluded.email,
            display_name = excluded.display_name,
            password_hash = excluded.password_hash,
            role = excluded.role,
            is_active = excluded.is_active,
            updated_at = excluded.updated_at
        """,
        (
            existing.get("id") if existing else uuid4().hex,
            normalized_username,
            email,
            display_name,
            password_hash,
            role,
            1 if is_active else 0,
            existing.get("createdAt") if existing else now,
            now,
        ),
    )
    return load_user_by_username(normalized_username) or {}
