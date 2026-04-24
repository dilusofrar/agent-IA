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

CREATE TABLE IF NOT EXISTS user_audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    changed_at TEXT NOT NULL,
    actor TEXT NOT NULL,
    target_username TEXT NOT NULL,
    action TEXT NOT NULL,
    changes_json TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_user_audit_changed_at
    ON user_audit(changed_at DESC);
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


def _is_missing_d1_table_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return "no such table" in message and "sqlite_error" in message


def _row_to_user(row: Any) -> dict[str, Any]:
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


def _merge_user_records(primary: dict[str, Any] | None, fallback: dict[str, Any] | None) -> dict[str, Any] | None:
    if primary is None:
        return fallback
    if fallback is None:
        return primary
    merged = dict(primary)
    for key in ("id", "email", "displayName", "passwordHash", "role", "createdAt", "updatedAt"):
        if merged.get(key) in {None, ""} and fallback.get(key) not in {None, ""}:
            merged[key] = fallback.get(key)
    return merged


def _prefer_newer_user_record(local_user: dict[str, Any] | None, d1_user: dict[str, Any] | None) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    if local_user is None or d1_user is None:
        return local_user, d1_user
    local_updated = str(local_user.get("updatedAt") or "")
    d1_updated = str(d1_user.get("updatedAt") or "")
    if local_updated and (not d1_updated or local_updated >= d1_updated):
        return local_user, d1_user
    return d1_user, local_user


def _mirror_user_record(user: dict[str, Any]) -> None:
    if not user:
        return
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
            user.get("id"),
            user.get("username"),
            user.get("email"),
            user.get("displayName"),
            user.get("passwordHash"),
            user.get("role"),
            1 if user.get("isActive") else 0,
            user.get("createdAt"),
            user.get("updatedAt"),
        ),
    )


def _retry_d1_with_schema(
    operation_name: str,
    sql: str,
    callback,
):
    client = d1_client()
    if client is None:
        return None
    try:
        return callback(client)
    except Exception as exc:
        if not _is_missing_d1_table_error(exc):
            raise
        LOGGER.warning(
            "d1_schema_retry_after_missing_table",
            extra={"error": str(exc), "sql": sql, "operation": operation_name},
        )
        client.ensure_schema(force=True)
        return callback(client)


def mirror_execute(sql: str, params: tuple[Any, ...] | list[Any] = ()) -> None:
    try:
        _retry_d1_with_schema(
            "execute",
            sql,
            lambda client: client.execute(sql, list(params)),
        )
    except Exception as exc:
        LOGGER.warning("d1_mirror_execute_failed", extra={"error": str(exc), "sql": sql})


def mirror_fetch_one(sql: str, params: tuple[Any, ...] | list[Any] = ()) -> dict[str, Any] | None:
    try:
        rows = _retry_d1_with_schema(
            "fetch_one",
            sql,
            lambda client: client.query(sql, list(params)),
        )
    except Exception as exc:
        LOGGER.warning("d1_mirror_fetch_failed", extra={"error": str(exc), "sql": sql})
        return None
    if rows is None:
        return None
    return rows[0] if rows else None


def mirror_fetch_all(sql: str, params: tuple[Any, ...] | list[Any] = ()) -> list[dict[str, Any]]:
    try:
        rows = _retry_d1_with_schema(
            "fetch_all",
            sql,
            lambda client: client.query(sql, list(params)),
        )
    except Exception as exc:
        LOGGER.warning("d1_mirror_fetch_failed", extra={"error": str(exc), "sql": sql})
        return []
    return rows or []


def sync_local_state_to_d1() -> dict[str, int]:
    client = d1_client()
    if client is None:
        raise RuntimeError("D1 não configurado.")
    ensure_app_db()
    summary = {"settingsCurrent": 0, "settingsAudit": 0, "reports": 0, "users": 0, "userAudit": 0}
    client.execute_script(
        """
        DELETE FROM settings_current;
        DELETE FROM settings_audit;
        DELETE FROM reports;
        DELETE FROM users;
        DELETE FROM user_audit;
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

        user_audit_rows = connection.execute(
            """
            SELECT changed_at, actor, target_username, action, changes_json
            FROM user_audit
            ORDER BY id ASC
            """
        ).fetchall()
        for row in user_audit_rows:
            client.execute(
                """
                INSERT INTO user_audit (changed_at, actor, target_username, action, changes_json)
                VALUES (?, ?, ?, ?, ?)
                """,
                [
                    row["changed_at"],
                    row["actor"],
                    row["target_username"],
                    row["action"],
                    row["changes_json"],
                ],
            )
            summary["userAudit"] += 1
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
    effective_password_hash = password_hash if password_hash is not None else existing.get("passwordHash")
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
                effective_password_hash,
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
            effective_password_hash,
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
    local_user: dict[str, Any] | None = None
    d1_user: dict[str, Any] | None = None
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
            d1_user = _row_to_user(selected_row)
    if not APP_DB_PATH.exists():
        if d1_user is not None:
            return d1_user
        selected_row = mirror_fetch_one(
            """
            SELECT id, username, email, display_name, password_hash, role, is_active, created_at, updated_at
            FROM users
            WHERE username = ?
            """,
            (normalized_username,),
        )
        return _row_to_user(selected_row) if selected_row is not None else None
    with open_db() as connection:
        row = connection.execute(
            """
            SELECT id, username, email, display_name, password_hash, role, is_active, created_at, updated_at
            FROM users
            WHERE username = ?
            """,
            (normalized_username,),
        ).fetchone()
    if row is not None:
        local_user = _row_to_user(row)
    if local_user is None and d1_user is None:
        selected_row = mirror_fetch_one(
            """
            SELECT id, username, email, display_name, password_hash, role, is_active, created_at, updated_at
            FROM users
            WHERE username = ?
            """,
            (normalized_username,),
        )
        d1_user = _row_to_user(selected_row) if selected_row is not None else None
    if local_user is not None and d1_user is None and d1_client() is not None:
        _mirror_user_record(local_user)
    primary_user, fallback_user = (
        _prefer_newer_user_record(local_user, d1_user)
        if prefer_d1_reads()
        else (local_user, d1_user)
    )
    return _merge_user_records(primary_user, fallback_user)


def list_users(limit: int = 100) -> list[dict[str, Any]]:
    def normalize_row(row: Any) -> dict[str, Any]:
        return {
            "id": row["id"],
            "username": row["username"],
            "email": row["email"],
            "displayName": row["display_name"],
            "role": row["role"],
            "isActive": bool(row["is_active"]),
            "createdAt": row["created_at"],
            "updatedAt": row["updated_at"],
        }

    query = """
        SELECT id, username, email, display_name, role, is_active, created_at, updated_at
        FROM users
        ORDER BY created_at ASC
        LIMIT ?
    """
    effective_limit = max(1, int(limit))
    d1_users = [
        normalize_row(row)
        for row in mirror_fetch_all(query, (effective_limit,))
    ]
    if not APP_DB_PATH.exists():
        return d1_users

    with open_db() as connection:
        local_rows = connection.execute(query, (effective_limit,)).fetchall()
    local_users = [normalize_row(row) for row in local_rows]

    if not local_users:
        return d1_users
    if not d1_users:
        for user in local_users:
            full_user = load_user_by_username(user["username"])
            if full_user is not None:
                _mirror_user_record(full_user)
        return local_users

    d1_by_username = {user["username"]: user for user in d1_users}
    merged_users: list[dict[str, Any]] = []
    for local_user in local_users:
        d1_user = d1_by_username.pop(local_user["username"], None)
        if d1_user is None:
            full_user = load_user_by_username(local_user["username"])
            if full_user is not None:
                _mirror_user_record(full_user)
            merged_users.append(local_user)
            continue
        primary_user, fallback_user = (
            _prefer_newer_user_record(local_user, d1_user)
            if prefer_d1_reads()
            else (local_user, d1_user)
        )
        merged_users.append(_merge_user_records(primary_user, fallback_user) or local_user)

    merged_users.extend(d1_by_username.values())
    merged_users.sort(key=lambda item: str(item.get("createdAt") or ""))
    return merged_users[:effective_limit]


def append_user_audit_entry(
    *,
    actor: str,
    target_username: str,
    action: str,
    changes: list[str],
) -> None:
    changed_at = datetime.now().isoformat(timespec="seconds")
    changes_json = json.dumps(changes, ensure_ascii=False)
    with open_db() as connection:
        connection.execute(
            """
            INSERT INTO user_audit (changed_at, actor, target_username, action, changes_json)
            VALUES (?, ?, ?, ?, ?)
            """,
            (changed_at, actor, target_username, action, changes_json),
        )
    mirror_execute(
        """
        INSERT INTO user_audit (changed_at, actor, target_username, action, changes_json)
        VALUES (?, ?, ?, ?, ?)
        """,
        (changed_at, actor, target_username, action, changes_json),
    )


def list_user_audit_entries(limit: int = 20) -> list[dict[str, Any]]:
    def normalize(rows: list[Any]) -> list[dict[str, Any]]:
        return [
            {
                "changedAt": row["changed_at"],
                "actor": row["actor"],
                "targetUsername": row["target_username"],
                "action": row["action"],
                "changes": json.loads(row["changes_json"]),
            }
            for row in rows
        ]

    if d1_client() is not None and prefer_d1_reads():
        selected_rows = mirror_fetch_all(
            """
            SELECT changed_at, actor, target_username, action, changes_json
            FROM user_audit
            ORDER BY changed_at DESC
            LIMIT ?
            """,
            (max(1, int(limit)),),
        )
        if selected_rows:
            return normalize(selected_rows)
    if not APP_DB_PATH.exists():
        return normalize(
            mirror_fetch_all(
                """
                SELECT changed_at, actor, target_username, action, changes_json
                FROM user_audit
                ORDER BY changed_at DESC
                LIMIT ?
                """,
                (max(1, int(limit)),),
            )
        )
    with open_db() as connection:
        rows = connection.execute(
            """
            SELECT changed_at, actor, target_username, action, changes_json
            FROM user_audit
            ORDER BY changed_at DESC
            LIMIT ?
            """,
            (max(1, int(limit)),),
        ).fetchall()
    selected_rows: Any = rows
    if not selected_rows:
        selected_rows = mirror_fetch_all(
            """
            SELECT changed_at, actor, target_username, action, changes_json
            FROM user_audit
            ORDER BY changed_at DESC
            LIMIT ?
            """,
            (max(1, int(limit)),),
        )
    return normalize(selected_rows)


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
