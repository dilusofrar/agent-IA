from __future__ import annotations

from datetime import datetime
import json
import logging
from typing import Any
from uuid import uuid4

from conferir_ponto.d1_api import D1ApiClient, d1_from_env


LOGGER = logging.getLogger("conferir_ponto.persistence")
_D1_CLIENT: D1ApiClient | None | bool = False
_MEMORY_STORE: dict[str, Any] = {}


def reset_memory_store() -> None:
    global _MEMORY_STORE
    _MEMORY_STORE = {
        "settings_current": {},
        "settings_audit": [],
        "reports": {},
        "users": {},
        "user_audit": [],
    }


reset_memory_store()


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
    return "d1" if d1_client() is not None else "memory"


def prefer_d1_reads() -> bool:
    return d1_client() is not None


def d1_status() -> dict[str, Any]:
    client = d1_client()
    return {
        "enabled": client is not None,
        "backend": persistence_backend_name(),
        "preferReads": bool(client is not None and prefer_d1_reads()),
        "databaseId": getattr(client, "database_id", None) if client is not None else None,
        "accountId": getattr(client, "account_id", None) if client is not None else None,
    }


def _extract_count_value(row: Any) -> int:
    if row is None:
        return 0
    raw_value = _row_value(row, "total", 0)
    try:
        return int(raw_value)
    except (TypeError, ValueError):
        return 0


def _local_upsert_settings_current(scope: str, payload_json: str, updated_at: str) -> None:
    _MEMORY_STORE["settings_current"][scope] = {
        "scope": scope,
        "payload_json": payload_json,
        "updated_at": updated_at,
    }


def _local_replace_settings_audit(rows: list[dict[str, Any]]) -> None:
    _MEMORY_STORE["settings_audit"] = [dict(row) for row in rows]


def _local_upsert_report_row(
    *,
    report_id: str,
    filename: str,
    employee_name: str | None,
    owner_user_id: str | None,
    owner_username: str | None,
    period_start: str | None,
    period_end: str | None,
    processed_at: str | None,
    created_at: str,
    processing_duration_ms: int | None,
    recent_json: str,
    payload_json: str,
    source_pdf_key: str | None,
    export_pdf_key: str | None,
    source_pdf_path: str | None,
    export_pdf_path: str | None,
) -> None:
    _MEMORY_STORE["reports"][report_id] = {
        "report_id": report_id,
        "filename": filename,
        "employee_name": employee_name,
        "owner_user_id": owner_user_id,
        "owner_username": owner_username,
        "period_start": period_start,
        "period_end": period_end,
        "processed_at": processed_at,
        "created_at": created_at,
        "processing_duration_ms": processing_duration_ms,
        "recent_json": recent_json,
        "payload_json": payload_json,
        "source_pdf_key": source_pdf_key,
        "export_pdf_key": export_pdf_key,
        "source_pdf_path": source_pdf_path,
        "export_pdf_path": export_pdf_path,
    }


def _local_replace_reports(rows: list[dict[str, Any]]) -> None:
    _MEMORY_STORE["reports"] = {row["report_id"]: dict(row) for row in rows}


def _local_upsert_user_row(
    *,
    user_id: str,
    username: str,
    email: str | None,
    display_name: str | None,
    password_hash: str | None,
    role: str,
    is_active: bool,
    created_at: str,
    updated_at: str,
) -> None:
    _MEMORY_STORE["users"][username] = {
        "id": user_id,
        "username": username,
        "email": email,
        "display_name": display_name,
        "password_hash": password_hash,
        "role": role,
        "is_active": 1 if is_active else 0,
        "created_at": created_at,
        "updated_at": updated_at,
    }


def _local_replace_users(rows: list[dict[str, Any]]) -> None:
    _MEMORY_STORE["users"] = {row["username"]: dict(row) for row in rows}


def _local_append_user_audit(changed_at: str, actor: str, target_username: str, action: str, changes_json: str) -> None:
    _MEMORY_STORE["user_audit"].append(
        {
            "changed_at": changed_at,
            "actor": actor,
            "target_username": target_username,
            "action": action,
            "changes_json": changes_json,
        }
    )


def _local_replace_user_audit(rows: list[dict[str, Any]]) -> None:
    _MEMORY_STORE["user_audit"] = [dict(row) for row in rows]


def _is_missing_d1_schema_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return "no such table" in message or "no such column" in message


def _load_json_payload(raw_value: str | None, *, context: str) -> Any | None:
    if raw_value in {None, ""}:
        return None
    try:
        return json.loads(raw_value)
    except (TypeError, json.JSONDecodeError) as exc:
        LOGGER.warning(
            "persistence_json_decode_failed",
            extra={"context": context, "error": str(exc)},
        )
        return None


def _row_value(row: Any, key: str, default: Any = None) -> Any:
    if row is None:
        return default
    if hasattr(row, "keys") and key in row.keys():
        return row[key]
    if isinstance(row, dict):
        return row.get(key, default)
    return default


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
        if not _is_missing_d1_schema_error(exc):
            raise
        LOGGER.warning(
            "d1_schema_retry_after_missing_object",
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


def best_effort_d1_write(sql: str, params: tuple[Any, ...] | list[Any] = ()) -> None:
    client = d1_client()
    if client is not None and hasattr(client, "execute"):
        mirror_execute(sql, params)


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


def persistence_record_counts() -> dict[str, Any]:
    table_queries = {
        "users": "SELECT COUNT(*) AS total FROM users",
        "userAudit": "SELECT COUNT(*) AS total FROM user_audit",
        "reports": "SELECT COUNT(*) AS total FROM reports",
        "settingsCurrent": "SELECT COUNT(*) AS total FROM settings_current",
        "settingsAudit": "SELECT COUNT(*) AS total FROM settings_audit",
    }
    d1_counts = {key: 0 for key in table_queries}

    if d1_client() is not None:
        for key, sql in table_queries.items():
            d1_counts[key] = _extract_count_value(mirror_fetch_one(sql))
        return {
            "backend": "d1",
            "d1": d1_counts,
        }
    return {
        "backend": "memory",
        "d1": {
            "users": len(_MEMORY_STORE["users"]),
            "userAudit": len(_MEMORY_STORE["user_audit"]),
            "reports": len(_MEMORY_STORE["reports"]),
            "settingsCurrent": len(_MEMORY_STORE["settings_current"]),
            "settingsAudit": len(_MEMORY_STORE["settings_audit"]),
        },
    }


def persistence_drift_summary() -> dict[str, Any]:
    return {
        "mode": "d1-only",
        "inSync": True,
        "mismatchCount": 0,
        "mismatches": [],
    }


def save_current_settings_payload(payload: dict[str, Any]) -> None:
    updated_at = datetime.now().isoformat(timespec="seconds")
    payload_json = json.dumps(payload, ensure_ascii=False)
    best_effort_d1_write(
        """
        INSERT INTO settings_current (scope, payload_json, updated_at)
        VALUES (?, ?, ?)
        ON CONFLICT(scope) DO UPDATE SET
            payload_json = excluded.payload_json,
            updated_at = excluded.updated_at
        """,
        ["global", payload_json, updated_at],
    )
    if d1_client() is None:
        _local_upsert_settings_current("global", payload_json, updated_at)


def load_current_settings_payload() -> dict[str, Any] | None:
    client = d1_client()
    if client is not None:
        d1_row = mirror_fetch_one(
            "SELECT payload_json, updated_at FROM settings_current WHERE scope = ?",
            ("global",),
        )
        if d1_row is not None:
            decoded_payload = _load_json_payload(
                d1_row.get("payload_json"),
                context="d1.settings_current.global",
            )
            if isinstance(decoded_payload, dict):
                return decoded_payload
        return None
    row = _MEMORY_STORE["settings_current"].get("global")
    if row is not None:
        decoded_payload = _load_json_payload(
            row.get("payload_json"),
            context="memory.settings_current.global",
        )
        if isinstance(decoded_payload, dict):
            return decoded_payload
    return None


def append_settings_audit_entry(entry: dict[str, Any]) -> None:
    changes_json = json.dumps(entry.get("changes", []), ensure_ascii=False)
    settings_json = json.dumps(entry.get("settings", {}), ensure_ascii=False)
    best_effort_d1_write(
        """
        INSERT INTO settings_audit (changed_at, actor, changes_json, settings_json)
        VALUES (?, ?, ?, ?)
        """,
        [entry["changedAt"], entry["actor"], changes_json, settings_json],
    )
    if d1_client() is None:
        _MEMORY_STORE["settings_audit"].append(
            {
                "changed_at": entry["changedAt"],
                "actor": entry["actor"],
                "changes_json": changes_json,
                "settings_json": settings_json,
            }
        )


def _normalize_settings_audit_rows(rows: list[Any], *, context: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    normalized_items: list[dict[str, Any]] = []
    valid_rows: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        changes = _load_json_payload(
            _row_value(row, "changes_json"),
            context=f"{context}[{index}].changes_json",
        )
        settings = _load_json_payload(
            _row_value(row, "settings_json"),
            context=f"{context}[{index}].settings_json",
        )
        if not isinstance(changes, list) or not isinstance(settings, dict):
            continue
        normalized_items.append(
            {
                "changedAt": _row_value(row, "changed_at"),
                "actor": _row_value(row, "actor"),
                "changes": changes,
                "settings": settings,
            }
        )
        valid_rows.append(
            {
                "changed_at": _row_value(row, "changed_at"),
                "actor": _row_value(row, "actor"),
                "changes_json": _row_value(row, "changes_json"),
                "settings_json": _row_value(row, "settings_json"),
            }
        )
    return normalized_items, valid_rows


def load_settings_audit_entries(limit: int = 12) -> list[dict[str, Any]]:
    client = d1_client()
    if client is not None:
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
            normalized_items, valid_rows = _normalize_settings_audit_rows(
                d1_rows,
                context="d1.settings_audit",
            )
            if normalized_items:
                return normalized_items
        return []
    rows = sorted(
        _MEMORY_STORE["settings_audit"],
        key=lambda item: str(item.get("changed_at") or ""),
        reverse=True,
    )[: max(0, int(limit))]
    if rows:
        normalized_items, _ = _normalize_settings_audit_rows(
            rows,
            context="memory.settings_audit",
        )
        return normalized_items
    return []


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
    recent_json = json.dumps(recent, ensure_ascii=False)
    payload_json = json.dumps(payload, ensure_ascii=False)
    best_effort_d1_write(
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
        [
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
            recent_json,
            payload_json,
            source_pdf_key,
            export_pdf_key,
            source_pdf_path,
            export_pdf_path,
        ],
    )
    if d1_client() is None:
        _local_upsert_report_row(
            report_id=report_id,
            filename=filename,
            employee_name=payload.get("employeeName"),
            owner_user_id=owner_user_id,
            owner_username=owner_username,
            period_start=payload.get("periodStart"),
            period_end=payload.get("periodEnd"),
            processed_at=payload.get("processedAt"),
            created_at=created_at,
            processing_duration_ms=payload.get("meta", {}).get("processingDurationMs"),
            recent_json=recent_json,
            payload_json=payload_json,
            source_pdf_key=source_pdf_key,
            export_pdf_key=export_pdf_key,
            source_pdf_path=source_pdf_path,
            export_pdf_path=export_pdf_path,
        )


def load_report_record(report_id: str) -> dict[str, Any] | None:
    client = d1_client()
    if client is not None:
        selected_row = mirror_fetch_one(
            """
            SELECT filename, owner_user_id, owner_username, period_start, period_end, processed_at, created_at,
                   processing_duration_ms, recent_json, payload_json, source_pdf_key, export_pdf_key, source_pdf_path, export_pdf_path
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
        return None
    row = _MEMORY_STORE["reports"].get(report_id)
    if row is None:
        return None
    return {
        "reportId": report_id,
        "filename": row["filename"],
        "ownerUserId": row["owner_user_id"],
        "ownerUsername": row["owner_username"],
        "recent": json.loads(row["recent_json"]),
        "payload": json.loads(row["payload_json"]),
        "sourcePdfKey": row["source_pdf_key"],
        "exportPdfKey": row["export_pdf_key"],
        "sourcePdfPath": row["source_pdf_path"],
        "exportPdfPath": row["export_pdf_path"],
    }


def list_recent_report_records(limit: int) -> list[dict[str, Any]]:
    client = d1_client()
    if client is not None:
        d1_rows = mirror_fetch_all(
            """
            SELECT report_id, filename, employee_name, owner_user_id, owner_username, period_start, period_end,
                   processed_at, created_at, processing_duration_ms, recent_json, payload_json, source_pdf_key,
                   export_pdf_key, source_pdf_path, export_pdf_path
            FROM reports
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (max(0, int(limit)),),
        )
        if d1_rows:
            return [json.loads(row["recent_json"]) for row in d1_rows]
        return []
    rows = sorted(
        _MEMORY_STORE["reports"].values(),
        key=lambda item: str(item.get("created_at") or ""),
        reverse=True,
    )[: max(0, int(limit))]
    return [json.loads(row["recent_json"]) for row in rows]


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
    effective_email = email if email is not None else existing.get("email")
    effective_display_name = display_name if display_name is not None else existing.get("displayName")
    effective_role = role if role is not None else existing.get("role")
    effective_is_active = bool(is_active if is_active is not None else existing.get("isActive"))
    best_effort_d1_write(
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
        [
            existing.get("id"),
            normalized_username,
            effective_email,
            effective_display_name,
            effective_password_hash,
            effective_role,
            1 if effective_is_active else 0,
            existing.get("createdAt"),
            now,
        ],
    )
    if d1_client() is None:
        _local_upsert_user_row(
            user_id=existing.get("id"),
            username=normalized_username,
            email=effective_email,
            display_name=effective_display_name,
            password_hash=effective_password_hash,
            role=effective_role,
            is_active=effective_is_active,
            created_at=existing.get("createdAt"),
            updated_at=now,
        )
    return load_user_by_username(normalized_username) or {}


def stale_report_ids(max_records: int) -> list[str]:
    client = d1_client()
    if client is not None:
        rows = mirror_fetch_all(
            """
            SELECT report_id
            FROM reports
            ORDER BY created_at DESC
            LIMIT -1 OFFSET ?
            """,
            (max(0, int(max_records)),),
        )
        if rows:
            return [row["report_id"] for row in rows]
        return []
    rows = sorted(
        _MEMORY_STORE["reports"].values(),
        key=lambda item: str(item.get("created_at") or ""),
        reverse=True,
    )[max(0, int(max_records)) :]
    return [row["report_id"] for row in rows]


def delete_report_record(report_id: str) -> None:
    best_effort_d1_write("DELETE FROM reports WHERE report_id = ?", [report_id])
    if d1_client() is None:
        _MEMORY_STORE["reports"].pop(report_id, None)


def load_user_by_username(username: str) -> dict[str, Any] | None:
    normalized_username = str(username or "").strip()
    if not normalized_username:
        return None
    client = d1_client()
    if client is not None:
        selected_row = mirror_fetch_one(
            """
            SELECT id, username, email, display_name, password_hash, role, is_active, created_at, updated_at
            FROM users
            WHERE username = ?
            """,
            (normalized_username,),
        )
        if selected_row is not None:
            return _row_to_user(selected_row)
        return None
    row = _MEMORY_STORE["users"].get(normalized_username)
    return _row_to_user(row) if row is not None else None


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
        SELECT id, username, email, display_name, password_hash, role, is_active, created_at, updated_at
        FROM users
        ORDER BY created_at ASC
        LIMIT ?
    """
    effective_limit = max(1, int(limit))
    client = d1_client()
    if client is not None:
        d1_rows = mirror_fetch_all(query, (effective_limit,))
        d1_users = [normalize_row(row) for row in d1_rows]
        return d1_users
    local_rows = sorted(
        _MEMORY_STORE["users"].values(),
        key=lambda item: str(item.get("created_at") or ""),
    )[:effective_limit]
    return [normalize_row(row) for row in local_rows]


def append_user_audit_entry(
    *,
    actor: str,
    target_username: str,
    action: str,
    changes: list[str],
) -> None:
    changed_at = datetime.now().isoformat(timespec="seconds")
    changes_json = json.dumps(changes, ensure_ascii=False)
    best_effort_d1_write(
        """
        INSERT INTO user_audit (changed_at, actor, target_username, action, changes_json)
        VALUES (?, ?, ?, ?, ?)
        """,
        [changed_at, actor, target_username, action, changes_json],
    )
    if d1_client() is None:
        _local_append_user_audit(changed_at, actor, target_username, action, changes_json)


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

    client = d1_client()
    if client is not None:
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
    rows = sorted(
        _MEMORY_STORE["user_audit"],
        key=lambda item: str(item.get("changed_at") or ""),
        reverse=True,
    )[: max(1, int(limit))]
    return normalize(rows)


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
    existing = load_user_by_username(normalized_username)
    if existing is not None:
        raise ValueError("Usuário já existe.")
    best_effort_d1_write(
        """
        INSERT INTO users (
            id, username, email, display_name, password_hash, role, is_active, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            user_id,
            normalized_username,
            email,
            display_name,
            password_hash,
            role,
            1 if is_active else 0,
            now,
            now,
        ],
    )
    if d1_client() is None:
        _local_upsert_user_row(
            user_id=user_id,
            username=normalized_username,
            email=email,
            display_name=display_name,
            password_hash=password_hash,
            role=role,
            is_active=is_active,
            created_at=now,
            updated_at=now,
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
    user_id = existing.get("id") if existing else uuid4().hex
    created_at = existing.get("createdAt") if existing else now
    best_effort_d1_write(
        """
        INSERT INTO users (
            id, username, email, display_name, password_hash, role, is_active, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(username) DO UPDATE SET
            id = excluded.id,
            email = excluded.email,
            display_name = excluded.display_name,
            password_hash = excluded.password_hash,
            role = excluded.role,
            is_active = excluded.is_active,
            updated_at = excluded.updated_at
        """,
        [
            user_id,
            normalized_username,
            email,
            display_name,
            password_hash,
            role,
            1 if is_active else 0,
            created_at,
            now,
        ],
    )
    if d1_client() is None:
        _local_upsert_user_row(
            user_id=user_id,
            username=normalized_username,
            email=email,
            display_name=display_name,
            password_hash=password_hash,
            role=role,
            is_active=is_active,
            created_at=created_at,
            updated_at=now,
        )
    return load_user_by_username(normalized_username) or {}
