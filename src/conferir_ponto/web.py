from __future__ import annotations

from collections import OrderedDict
from datetime import datetime
from hashlib import sha256
import hmac
import json
import logging
import os
import secrets
from time import perf_counter
from pathlib import Path
import re
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

from conferir_ponto.persistence import (
    append_user_audit_entry,
    create_user,
    delete_report_record,
    d1_status,
    list_user_audit_entries,
    list_users,
    list_recent_report_records,
    load_report_record,
    load_user_by_username,
    persistence_backend_name,
    sync_local_state_to_d1,
    stale_report_ids,
    update_user,
    upsert_user,
    upsert_report_record,
)
from conferir_ponto.settings import (
    append_settings_history,
    load_settings,
    load_settings_history,
    save_settings,
    settings_to_payload,
)
from conferir_ponto.storage import ReportStorage, build_report_object_key, storage_from_env
from conferir_ponto.timecard import (
    build_summary_payload,
    export_analysis_to_pdf,
    parse_timecard_bytes,
)


BASE_DIR = Path(__file__).resolve().parents[2]
STATIC_DIR = BASE_DIR / "web" / "static"
REPORTS_DIR = BASE_DIR / "data" / "reports"
MAX_UPLOAD_SIZE_BYTES = 10 * 1024 * 1024
MAX_STORED_REPORTS = 32
RECENT_REPORTS_LIMIT = 6
APP_VERSION = "1.15.1"
ADMIN_SESSION_COOKIE = "agent_admin_session"
APP_SESSION_COOKIE = "agent_app_session"
ADMIN_SESSION_TTL_SECONDS = 60 * 60 * 12
APP_SESSION_TTL_SECONDS = 60 * 60 * 12
PASSWORD_HASH_ITERATIONS = 390000
SAFE_DOWNLOAD_NAME = re.compile(r"[^A-Za-z0-9._-]+")
ENABLE_API_DOCS = os.getenv("ENABLE_API_DOCS", "").strip().lower() in {"1", "true", "yes", "on"}
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": (
        "default-src 'self'; "
        "script-src 'self'; "
        "style-src 'self'; "
        "img-src 'self' data:; "
        "object-src 'none'; "
        "base-uri 'none'; "
        "frame-ancestors 'none'; "
        "form-action 'self'"
    ),
}
app = FastAPI(
    title="Agent IA Ponto",
    version="1.0.0",
    docs_url="/docs" if ENABLE_API_DOCS else None,
    redoc_url="/redoc" if ENABLE_API_DOCS else None,
    openapi_url="/openapi.json" if ENABLE_API_DOCS else None,
)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

REPORTS: OrderedDict[str, dict[str, Any]] = OrderedDict()
LOGGER = logging.getLogger("conferir_ponto.web")
_REPORT_STORAGE: ReportStorage | None = None


@app.exception_handler(Exception)
async def handle_unexpected_exception(request: Request, exc: Exception) -> JSONResponse:
    LOGGER.exception(
        "unhandled_request_error",
        extra={"path": request.url.path, "method": request.method},
    )
    return JSONResponse(
        {"detail": "Erro interno ao processar a solicitacao."},
        status_code=500,
    )


@app.middleware("http")
async def apply_security_headers(request: Request, call_next) -> Response:
    response = await call_next(request)
    for header, value in SECURITY_HEADERS.items():
        response.headers.setdefault(header, value)
    if request.url.path.startswith("/api/"):
        response.headers.setdefault("Cache-Control", "no-store")
        response.headers.setdefault("Pragma", "no-cache")
    return response


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> Response:
    if not is_app_authenticated(request):
        return RedirectResponse(url="/login", status_code=303)
    return HTMLResponse((STATIC_DIR / "index.html").read_text(encoding="utf-8"))


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request) -> Response:
    if is_app_authenticated(request):
        return RedirectResponse(url="/", status_code=303)
    return HTMLResponse((STATIC_DIR / "login.html").read_text(encoding="utf-8"))


@app.get("/admin", response_class=HTMLResponse)
async def admin_page(request: Request) -> Response:
    if not is_admin_authenticated(request):
        return RedirectResponse(url="/admin/login", status_code=303)
    return HTMLResponse((STATIC_DIR / "admin.html").read_text(encoding="utf-8"))


@app.get("/admin/login", response_class=HTMLResponse)
async def admin_login_page(request: Request) -> Response:
    if is_admin_authenticated(request):
        return RedirectResponse(url="/admin", status_code=303)
    return HTMLResponse((STATIC_DIR / "admin-login.html").read_text(encoding="utf-8"))


@app.get("/healthz")
async def healthcheck() -> JSONResponse:
    return JSONResponse(
        {
            "status": "ok",
            "version": APP_VERSION,
            "storageBackend": report_storage().backend_name,
            "persistenceBackend": persistence_backend_name(),
        }
    )


@app.get("/api/session")
async def app_session_status(request: Request) -> JSONResponse:
    current_user = get_authenticated_app_user(request)
    return JSONResponse(
        {
            "authenticated": current_user is not None,
            "user": sanitize_user(current_user) if current_user else None,
        }
    )


@app.post("/api/session")
async def app_session_login(request: Request, payload: dict[str, Any]) -> JSONResponse:
    provided_username = str(payload.get("username", "")).strip()
    provided_password = str(payload.get("password", ""))
    app_user = authenticate_app_user(provided_username, provided_password)
    if app_user is None:
        raise HTTPException(status_code=401, detail="Credenciais invalidas.")

    response = JSONResponse({"authenticated": True, "user": sanitize_user(app_user)})
    response.set_cookie(
        key=APP_SESSION_COOKIE,
        value=create_app_session_token(app_user["username"]),
        httponly=True,
        samesite="lax",
        max_age=APP_SESSION_TTL_SECONDS,
        secure=should_set_secure_cookie(request),
    )
    return response


@app.delete("/api/session")
async def app_session_logout(request: Request) -> JSONResponse:
    response = JSONResponse({"authenticated": False})
    response.delete_cookie(
        APP_SESSION_COOKIE,
        httponly=True,
        samesite="lax",
        secure=should_set_secure_cookie(request),
    )
    return response


@app.post("/api/session/password")
async def app_session_change_password(request: Request, payload: dict[str, Any]) -> JSONResponse:
    current_user = ensure_app_user(request)
    current_password = str(payload.get("currentPassword", ""))
    new_password = str(payload.get("newPassword", ""))
    confirm_password = str(payload.get("confirmPassword", ""))

    if not current_password or not new_password or not confirm_password:
        raise HTTPException(status_code=400, detail="Preencha a senha atual, a nova senha e a confirmação.")
    if new_password != confirm_password:
        raise HTTPException(status_code=400, detail="A confirmação da nova senha não confere.")
    if len(new_password) < 6:
        raise HTTPException(status_code=400, detail="A nova senha precisa ter pelo menos 6 caracteres.")
    if not verify_password(current_password, current_user.get("passwordHash")):
        raise HTTPException(status_code=401, detail="A senha atual está incorreta.")
    if verify_password(new_password, current_user.get("passwordHash")):
        raise HTTPException(status_code=400, detail="A nova senha precisa ser diferente da senha atual.")

    updated_user = update_user(
        current_user["username"],
        password_hash=hash_password(new_password),
    )
    append_user_audit_entry(
        actor=current_user["username"],
        target_username=current_user["username"],
        action="self-password-change",
        changes=["Senha alterada pelo próprio usuário."],
    )
    return JSONResponse({"updated": True, "user": sanitize_user(updated_user)})


@app.get("/api/admin/session")
async def admin_session_status(request: Request) -> JSONResponse:
    current_user = get_authenticated_admin_user(request)
    return JSONResponse(
        {
            "authenticated": current_user is not None,
            "user": sanitize_user(current_user) if current_user else None,
        }
    )


@app.post("/api/admin/session")
async def admin_session_login(request: Request, payload: dict[str, Any]) -> JSONResponse:
    provided_username = str(payload.get("username", "")).strip()
    provided_password = str(payload.get("password", ""))
    admin_user = authenticate_admin_user(provided_username, provided_password)
    if admin_user is None:
        _, password = get_admin_credentials()
        if not password:
            raise HTTPException(status_code=503, detail="Painel administrativo nao configurado.")
        raise HTTPException(status_code=401, detail="Credenciais invalidas.")

    response = JSONResponse({"authenticated": True, "user": sanitize_user(admin_user)})
    response.set_cookie(
        key=ADMIN_SESSION_COOKIE,
        value=create_admin_session_token(admin_user["username"]),
        httponly=True,
        samesite="lax",
        max_age=ADMIN_SESSION_TTL_SECONDS,
        secure=should_set_secure_cookie(request),
    )
    return response


@app.delete("/api/admin/session")
async def admin_session_logout() -> JSONResponse:
    response = JSONResponse({"authenticated": False})
    response.delete_cookie(ADMIN_SESSION_COOKIE, httponly=True, samesite="lax")
    return response


@app.get("/api/admin/users")
async def admin_list_users(request: Request) -> JSONResponse:
    ensure_admin(request)
    items = list_users()
    return JSONResponse({"items": items, "count": len(items)})


@app.get("/api/admin/users/history")
async def admin_user_history(request: Request) -> JSONResponse:
    ensure_admin(request)
    items = list_user_audit_entries()
    return JSONResponse({"items": items, "count": len(items)})


@app.get("/api/admin/persistence")
async def admin_persistence_status(request: Request) -> JSONResponse:
    ensure_admin(request)
    return JSONResponse(d1_status())


@app.post("/api/admin/persistence/sync-d1")
async def admin_sync_d1(request: Request) -> JSONResponse:
    ensure_admin(request)
    try:
        summary = sync_local_state_to_d1()
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return JSONResponse({"synced": True, "summary": summary, "status": d1_status()})


@app.post("/api/admin/users")
async def admin_create_user(request: Request, payload: dict[str, Any]) -> JSONResponse:
    ensure_admin(request)
    username = str(payload.get("username", "")).strip()
    password = str(payload.get("password", ""))
    role = str(payload.get("role", "user")).strip().lower() or "user"
    if role not in {"admin", "user"}:
        raise HTTPException(status_code=400, detail="Perfil inválido.")
    if not username or not password:
        raise HTTPException(status_code=400, detail="Usuário e senha são obrigatórios.")
    try:
        user = create_user(
            username=username,
            password_hash=hash_password(password),
            role=role,
            email=str(payload.get("email", "")).strip() or None,
            display_name=str(payload.get("displayName", "")).strip() or None,
            is_active=bool(payload.get("isActive", True)),
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    append_user_audit_entry(
        actor=get_authenticated_admin_username(request),
        target_username=user["username"],
        action="create",
        changes=[
            f"Usuário {user['username']} criado com perfil {user['role']}.",
            f"Status inicial: {'ativo' if user['isActive'] else 'inativo'}.",
        ],
    )
    return JSONResponse(sanitize_user(user), status_code=201)


@app.put("/api/admin/users/{username}")
async def admin_update_user(username: str, request: Request, payload: dict[str, Any]) -> JSONResponse:
    ensure_admin(request)
    previous_user = load_user_by_username(username)
    if previous_user is None:
        raise HTTPException(status_code=404, detail="Usuário não encontrado.")
    role = payload.get("role")
    normalized_role = str(role).strip().lower() if role is not None else None
    if normalized_role is not None and normalized_role not in {"admin", "user"}:
        raise HTTPException(status_code=400, detail="Perfil inválido.")
    password = str(payload.get("password", ""))
    normalized_email = None
    normalized_display_name = None
    if "email" in payload:
        normalized_email = str(payload.get("email", "")).strip() or None
    if "displayName" in payload:
        normalized_display_name = str(payload.get("displayName", "")).strip() or None
    try:
        user = update_user(
            username,
            password_hash=hash_password(password) if password else None,
            role=normalized_role,
            email=normalized_email,
            display_name=normalized_display_name,
            is_active=bool(payload.get("isActive")) if "isActive" in payload else None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    changes = build_user_change_summary(previous_user, user, password_changed=bool(password))
    append_user_audit_entry(
        actor=get_authenticated_admin_username(request),
        target_username=user["username"],
        action="update",
        changes=changes,
    )
    return JSONResponse(sanitize_user(user))


@app.get("/api/reports/recent")
async def recent_reports(request: Request) -> JSONResponse:
    current_user = ensure_app_user(request)
    items = load_recent_report_items(limit=RECENT_REPORTS_LIMIT, current_user=current_user)
    return JSONResponse({"items": items, "count": len(items)})


@app.get("/api/settings/public")
async def get_public_settings() -> JSONResponse:
    return JSONResponse(settings_to_payload(load_settings()))


@app.get("/api/settings")
async def get_settings(request: Request) -> JSONResponse:
    ensure_admin(request)
    return JSONResponse(settings_to_payload(load_settings()))


@app.get("/api/settings/history")
async def get_settings_history(request: Request) -> JSONResponse:
    ensure_admin(request)
    items = load_settings_history()
    return JSONResponse({"items": items, "count": len(items)})


@app.put("/api/settings")
async def update_settings(request: Request, payload: dict[str, Any]) -> JSONResponse:
    ensure_admin(request)
    previous_payload = settings_to_payload(load_settings())
    try:
        settings = save_settings(payload)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    persisted_payload = settings_to_payload(settings)
    append_settings_history(
        actor=get_authenticated_admin_username(request),
        before_payload=previous_payload,
        after_payload=persisted_payload,
    )
    return JSONResponse(persisted_payload)


@app.get("/api/reports/{report_id}")
async def report_details(report_id: str, request: Request) -> JSONResponse:
    current_user = ensure_app_user(request)
    report = REPORTS.get(report_id)
    if report is None:
        report = load_report_from_disk(report_id)
    if report is None or "payload" not in report:
        raise HTTPException(status_code=404, detail="Relatorio nao encontrado.")
    ensure_report_access(current_user, report)
    return JSONResponse(report["payload"])


@app.post("/api/process")
async def process_pdf(request: Request, file: UploadFile = File(...)) -> JSONResponse:
    current_user = ensure_app_user(request)
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Envie um arquivo PDF valido.")

    start_time = perf_counter()
    try:
        content = await file.read(MAX_UPLOAD_SIZE_BYTES + 1)
    finally:
        await file.close()

    if len(content) > MAX_UPLOAD_SIZE_BYTES:
        raise HTTPException(
            status_code=413,
            detail="O PDF excede o limite de 10 MB permitido para processamento.",
        )

    settings = load_settings()
    try:
        analysis = parse_timecard_bytes(content, settings=settings)
    except Exception as exc:
        LOGGER.warning(
            "process_failed",
            extra={
                "filename": file.filename,
                "size_bytes": len(content),
                "error": str(exc),
            },
        )
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    payload = build_summary_payload(analysis)
    payload["settings"] = settings_to_payload(settings)
    report_id = uuid4().hex
    processing_duration_ms = int((perf_counter() - start_time) * 1000)
    created_at = datetime.now().isoformat(timespec="seconds")
    payload["meta"] = {
        **payload.get("meta", {}),
        "reportId": report_id,
        "filename": file.filename,
        "generatedAt": created_at,
        "processingDurationMs": processing_duration_ms,
        "version": APP_VERSION,
    }
    payload["meta"]["owner"] = sanitize_user(current_user)
    while len(REPORTS) >= MAX_STORED_REPORTS:
        REPORTS.popitem(last=False)
    REPORTS[report_id] = {
        "filename": file.filename,
        "pdf": export_analysis_to_pdf(analysis),
        "recent": build_recent_report_item(report_id, file.filename, payload),
        "payload": payload,
    }
    persistence_warning = None
    try:
        persist_report(report_id, REPORTS[report_id], source_pdf=content)
        prune_persisted_reports()
    except Exception as exc:
        persistence_warning = "Historico indisponivel nesta apuracao; resultado entregue sem persistencia."
        payload["meta"]["persistenceWarning"] = persistence_warning
        REPORTS[report_id]["payload"] = payload
        REPORTS[report_id]["recent"] = build_recent_report_item(report_id, file.filename, payload)
        LOGGER.warning(
            "report_persistence_failed",
            extra={
                "report_id": report_id,
                "upload_name": file.filename,
                "error": str(exc),
            },
        )
    LOGGER.info(
        "process_completed",
        extra={
            "report_id": report_id,
            "filename": file.filename,
            "size_bytes": len(content),
            "duration_ms": processing_duration_ms,
            "issues": payload["summary"]["inconsistencyCount"],
            "included_days": payload["summary"]["businessDaysProcessed"],
            "persisted": persistence_warning is None,
        },
    )
    payload["reportId"] = report_id
    return JSONResponse(payload)


@app.get("/api/export/{report_id}")
async def export_report(report_id: str, request: Request) -> Response:
    current_user = ensure_app_user(request)
    report = REPORTS.get(report_id)
    if report is None:
        report = load_report_from_disk(report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="Relatorio nao encontrado.")
    ensure_report_access(current_user, report)

    original_name = sanitize_download_name(report["filename"])
    return Response(
        content=report["pdf"],
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{original_name}_apuracao.pdf"'
        },
    )


def sanitize_download_name(filename: str) -> str:
    sanitized = SAFE_DOWNLOAD_NAME.sub("_", Path(filename).stem).strip("._")
    return sanitized or "relatorio"


def sanitize_user(user: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": user.get("id"),
        "username": user.get("username"),
        "email": user.get("email"),
        "displayName": user.get("displayName"),
        "role": user.get("role"),
        "isActive": bool(user.get("isActive", False)),
        "createdAt": user.get("createdAt"),
        "updatedAt": user.get("updatedAt"),
    }


def build_user_change_summary(
    previous_user: dict[str, Any],
    updated_user: dict[str, Any],
    *,
    password_changed: bool,
) -> list[str]:
    changes: list[str] = []
    if previous_user.get("role") != updated_user.get("role"):
        changes.append(f"Perfil alterado de {previous_user.get('role')} para {updated_user.get('role')}.")
    if previous_user.get("displayName") != updated_user.get("displayName"):
        changes.append(
            "Nome de exibição alterado para "
            + (updated_user.get("displayName") or "não informado")
            + "."
        )
    if previous_user.get("email") != updated_user.get("email"):
        changes.append("E-mail atualizado.")
    if bool(previous_user.get("isActive")) != bool(updated_user.get("isActive")):
        changes.append("Status alterado para " + ("ativo." if updated_user.get("isActive") else "inativo."))
    if password_changed:
        changes.append("Senha redefinida.")
    if not changes:
        changes.append("Registro salvo sem alteração material detectada.")
    return changes


def hash_password(password: str, *, salt: str | None = None) -> str:
    normalized_password = str(password or "")
    if not normalized_password:
        raise ValueError("Senha é obrigatória.")
    effective_salt = salt or secrets.token_hex(16)
    digest = sha256(
        normalized_password.encode("utf-8") + effective_salt.encode("utf-8")
    ).hexdigest()
    for _ in range(PASSWORD_HASH_ITERATIONS // 1000):
        digest = sha256((digest + effective_salt).encode("utf-8")).hexdigest()
    return f"sha256${PASSWORD_HASH_ITERATIONS}${effective_salt}${digest}"


def verify_password(password: str, stored_hash: str | None) -> bool:
    if not stored_hash:
        return False
    try:
        algorithm, iterations, salt, expected_digest = stored_hash.split("$", 3)
    except ValueError:
        return False
    if algorithm != "sha256":
        return False
    digest = sha256(str(password or "").encode("utf-8") + salt.encode("utf-8")).hexdigest()
    for _ in range(int(iterations) // 1000):
        digest = sha256((digest + salt).encode("utf-8")).hexdigest()
    return hmac.compare_digest(digest, expected_digest)


def get_admin_credentials() -> tuple[str, str]:
    return (
        os.getenv("ADMIN_USERNAME", "admin").strip() or "admin",
        os.getenv("ADMIN_PASSWORD", "").strip(),
    )


def sync_admin_user_from_env() -> dict[str, Any] | None:
    username, password = get_admin_credentials()
    if not password:
        return None
    existing_user = load_user_by_username(username)
    needs_sync = existing_user is None or existing_user.get("role") != "admin"
    if existing_user is not None and existing_user.get("passwordHash"):
        needs_sync = not verify_password(password, existing_user.get("passwordHash"))
    if not needs_sync:
        return existing_user
    return upsert_user(
        username=username,
        password_hash=hash_password(password),
        role="admin",
        display_name=username,
        is_active=True,
    )


def authenticate_admin_user(username: str, password: str) -> dict[str, Any] | None:
    sync_admin_user_from_env()
    user = load_user_by_username(username)
    if user and user.get("isActive") and user.get("role") == "admin":
        if verify_password(password, user.get("passwordHash")):
            return user
    env_username, env_password = get_admin_credentials()
    if env_password and hmac.compare_digest(username, env_username) and hmac.compare_digest(password, env_password):
        return {
            "id": None,
            "username": env_username,
            "displayName": env_username,
            "email": None,
            "role": "admin",
            "isActive": True,
            "createdAt": None,
            "updatedAt": None,
        }
    return None


def authenticate_app_user(username: str, password: str) -> dict[str, Any] | None:
    sync_admin_user_from_env()
    user = load_user_by_username(username)
    if user and user.get("isActive") and verify_password(password, user.get("passwordHash")):
        return user
    return None


def get_authenticated_admin_user(request: Request) -> dict[str, Any] | None:
    if not is_admin_authenticated(request):
        return None
    token = request.cookies.get(ADMIN_SESSION_COOKIE, "")
    if token:
        try:
            token_username, _, _ = token.split(":", 2)
        except ValueError:
            token_username = ""
        if token_username:
            user = load_user_by_username(token_username)
            if user and user.get("isActive") and user.get("role") == "admin":
                return user
            env_username, _ = get_admin_credentials()
            if token_username == env_username:
                return {
                    "id": None,
                    "username": env_username,
                    "displayName": env_username,
                    "email": None,
                    "role": "admin",
                    "isActive": True,
                    "createdAt": None,
                    "updatedAt": None,
                }
    return None


def get_authenticated_app_user(request: Request) -> dict[str, Any] | None:
    if not is_app_authenticated(request):
        return None
    token = request.cookies.get(APP_SESSION_COOKIE, "")
    if not token:
        return None
    try:
        token_username, _, _ = token.split(":", 2)
    except ValueError:
        return None
    user = load_user_by_username(token_username)
    if user and user.get("isActive"):
        return user
    return None


def admin_session_secret() -> str:
    configured_secret = os.getenv("ADMIN_SESSION_SECRET", "").strip()
    if configured_secret:
        return configured_secret
    username, password = get_admin_credentials()
    return sha256(f"{username}:{password}:agent-ia-ponto".encode("utf-8")).hexdigest()


def create_admin_session_token(username: str) -> str:
    issued_at = int(datetime.now().timestamp())
    expires_at = issued_at + ADMIN_SESSION_TTL_SECONDS
    payload = f"{username}:{expires_at}"
    signature = hmac.new(
        admin_session_secret().encode("utf-8"),
        payload.encode("utf-8"),
        sha256,
    ).hexdigest()
    return f"{payload}:{signature}"


def app_session_secret() -> str:
    configured_secret = os.getenv("APP_SESSION_SECRET", "").strip()
    if configured_secret:
        return configured_secret
    fallback_secret = os.getenv("ADMIN_SESSION_SECRET", "").strip()
    if fallback_secret:
        return sha256(f"app:{fallback_secret}".encode("utf-8")).hexdigest()
    username, password = get_admin_credentials()
    return sha256(f"{username}:{password}:agent-ia-ponto-app".encode("utf-8")).hexdigest()


def create_app_session_token(username: str) -> str:
    issued_at = int(datetime.now().timestamp())
    expires_at = issued_at + APP_SESSION_TTL_SECONDS
    payload = f"{username}:{expires_at}"
    signature = hmac.new(
        app_session_secret().encode("utf-8"),
        payload.encode("utf-8"),
        sha256,
    ).hexdigest()
    return f"{payload}:{signature}"


def is_admin_authenticated(request: Request) -> bool:
    sync_admin_user_from_env()
    username, password = get_admin_credentials()
    has_env_admin = bool(password)
    token = request.cookies.get(ADMIN_SESSION_COOKIE, "")
    if not token:
        return False
    try:
        token_username, token_expires, token_signature = token.split(":", 2)
        expires_at = int(token_expires)
    except ValueError:
        return False
    payload = f"{token_username}:{expires_at}"
    expected_signature = hmac.new(
        admin_session_secret().encode("utf-8"),
        payload.encode("utf-8"),
        sha256,
    ).hexdigest()
    if not hmac.compare_digest(token_signature, expected_signature):
        return False
    if expires_at < int(datetime.now().timestamp()):
        return False
    user = load_user_by_username(token_username)
    if user is not None:
        return bool(user.get("isActive")) and user.get("role") == "admin"
    if has_env_admin and hmac.compare_digest(token_username, username):
        return True
    return False


def is_app_authenticated(request: Request) -> bool:
    token = request.cookies.get(APP_SESSION_COOKIE, "")
    if not token:
        return False
    try:
        token_username, token_expires, token_signature = token.split(":", 2)
        expires_at = int(token_expires)
    except ValueError:
        return False
    payload = f"{token_username}:{expires_at}"
    expected_signature = hmac.new(
        app_session_secret().encode("utf-8"),
        payload.encode("utf-8"),
        sha256,
    ).hexdigest()
    if not hmac.compare_digest(token_signature, expected_signature):
        return False
    if expires_at < int(datetime.now().timestamp()):
        return False
    user = load_user_by_username(token_username)
    return bool(user and user.get("isActive"))


def ensure_admin(request: Request) -> None:
    if not is_admin_authenticated(request):
        raise HTTPException(status_code=401, detail="Autenticacao administrativa necessaria.")


def ensure_app_user(request: Request) -> dict[str, Any]:
    user = get_authenticated_app_user(request)
    if user is None:
        raise HTTPException(status_code=401, detail="Autenticacao necessaria.")
    return user


def get_authenticated_admin_username(request: Request) -> str:
    token = request.cookies.get(ADMIN_SESSION_COOKIE, "")
    if token:
        try:
            token_username, _, _ = token.split(":", 2)
        except ValueError:
            token_username = ""
        if token_username:
            return token_username
    username, _ = get_admin_credentials()
    return username


def should_set_secure_cookie(request: Request) -> bool:
    forwarded_proto = request.headers.get("x-forwarded-proto", "")
    if "https" in forwarded_proto.lower():
        return True
    return request.url.scheme == "https"


def build_recent_report_item(report_id: str, filename: str, payload: dict[str, Any]) -> dict[str, Any]:
    owner = payload.get("meta", {}).get("owner", {})
    return {
        "reportId": report_id,
        "filename": filename,
        "employeeName": payload.get("employeeName"),
        "periodStart": payload.get("periodStart"),
        "periodEnd": payload.get("periodEnd"),
        "processedAt": payload.get("processedAt"),
        "createdAt": payload.get("meta", {}).get("generatedAt"),
        "processingDurationMs": payload.get("meta", {}).get("processingDurationMs"),
        "ownerUsername": owner.get("username"),
        "ownerDisplayName": owner.get("displayName"),
        "ownerRole": owner.get("role"),
        "summary": {
            "businessDaysProcessed": payload.get("summary", {}).get("businessDaysProcessed"),
            "inconsistencyCount": payload.get("summary", {}).get("inconsistencyCount"),
            "balance": payload.get("summary", {}).get("balance"),
            "paidOvertime": payload.get("summary", {}).get("paidOvertime"),
        },
        "diagnostics": payload.get("diagnostics", {}),
    }


def can_access_report(user: dict[str, Any], report: dict[str, Any] | None) -> bool:
    if not user or report is None:
        return False
    if user.get("role") == "admin":
        return True
    owner = report.get("payload", {}).get("meta", {}).get("owner", {})
    owner_username = owner.get("username") or report.get("ownerUsername")
    return bool(owner_username and owner_username == user.get("username"))


def ensure_report_access(user: dict[str, Any], report: dict[str, Any] | None) -> None:
    if not can_access_report(user, report):
        raise HTTPException(status_code=403, detail="Acesso negado para este relatorio.")


def filter_recent_items_for_user(
    items: list[dict[str, Any]],
    current_user: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    if current_user is None or current_user.get("role") == "admin":
        return items
    username = current_user.get("username")
    return [item for item in items if item.get("ownerUsername") == username]


def ensure_reports_dir() -> Path:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    return REPORTS_DIR


def report_storage() -> ReportStorage:
    global _REPORT_STORAGE
    if _REPORT_STORAGE is None:
        _REPORT_STORAGE = storage_from_env(ensure_reports_dir())
    return _REPORT_STORAGE


def metadata_object_key(report_id: str) -> str:
    return build_report_object_key(report_id, "metadata.json")


def export_pdf_object_key(report_id: str) -> str:
    return build_report_object_key(report_id, "export.pdf")


def source_pdf_object_key(report_id: str) -> str:
    return build_report_object_key(report_id, "source.pdf")


def persist_report(report_id: str, report: dict[str, Any], *, source_pdf: bytes | None = None) -> None:
    storage = report_storage()
    metadata = {
        "reportId": report_id,
        "filename": report["filename"],
        "recent": report.get("recent", {}),
        "payload": report.get("payload", {}),
    }
    metadata_result = storage.write_bytes(
        metadata_object_key(report_id),
        json.dumps(metadata, ensure_ascii=False, indent=2).encode("utf-8"),
    )
    export_result = storage.write_bytes(export_pdf_object_key(report_id), report["pdf"])
    source_result = None
    source_pdf_path = None
    if source_pdf is not None:
        source_result = storage.write_bytes(source_pdf_object_key(report_id), source_pdf)
        source_pdf_path = source_result.location
    upsert_report_record(
        report_id,
        report["filename"],
        report.get("recent", {}),
        report.get("payload", {}),
        owner_user_id=metadata.get("payload", {}).get("meta", {}).get("owner", {}).get("id"),
        owner_username=metadata.get("payload", {}).get("meta", {}).get("owner", {}).get("username"),
        source_pdf_key=source_result.key if source_result else None,
        export_pdf_key=export_result.key,
        source_pdf_path=source_pdf_path,
        export_pdf_path=export_result.location,
    )


def load_report_from_disk(report_id: str) -> dict[str, Any] | None:
    storage = report_storage()
    metadata_bytes = storage.read_bytes(metadata_object_key(report_id))
    export_bytes = storage.read_bytes(export_pdf_object_key(report_id))
    if metadata_bytes is None or export_bytes is None:
        record = load_report_record(report_id)
        export_key = record.get("exportPdfKey") if record else None
        if record and export_key:
            export_bytes = storage.read_bytes(export_key)
        if record is None or export_bytes is None:
            return None
        report = {
            "filename": record.get("filename", f"{report_id}.pdf"),
            "pdf": export_bytes,
            "recent": record.get("recent", {}),
            "payload": record.get("payload", {}),
        }
        REPORTS[report_id] = report
        return report

    metadata = json.loads(metadata_bytes.decode("utf-8"))
    report = {
        "filename": metadata.get("filename", f"{report_id}.pdf"),
        "pdf": export_bytes,
        "recent": metadata.get("recent", {}),
        "payload": metadata.get("payload", {}),
    }
    REPORTS[report_id] = report
    return report


def load_recent_report_items(
    limit: int = RECENT_REPORTS_LIMIT,
    *,
    current_user: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    seen_report_ids: set[str] = set()
    db_items = list_recent_report_records(limit)
    for recent in db_items:
        report_id = recent.get("reportId") if recent else None
        if recent and report_id and report_id not in seen_report_ids:
            items.append(recent)
            seen_report_ids.add(report_id)
    if len(items) >= limit:
        return items[:limit]
    if REPORTS_DIR.exists():
        for metadata_path in sorted(
            REPORTS_DIR.glob("reports/*/metadata.json"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        ):
            try:
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            recent = metadata.get("recent")
            report_id = recent.get("reportId") if recent else None
            if recent and report_id and report_id not in seen_report_ids:
                items.append(recent)
                seen_report_ids.add(report_id)
            if len(items) >= limit:
                break

    for report in reversed(REPORTS.values()):
        recent = report.get("recent")
        if not recent:
            continue
        report_id = recent.get("reportId")
        if not report_id or report_id in seen_report_ids:
            continue
        items.append(recent)
        seen_report_ids.add(report_id)
        if len(items) >= limit:
            break

    items.sort(key=lambda item: item.get("createdAt") or item.get("processedAt") or "", reverse=True)
    return filter_recent_items_for_user(items[:limit], current_user)


def prune_persisted_reports() -> None:
    stale_ids = stale_report_ids(MAX_STORED_REPORTS)
    storage = report_storage()
    for report_id in stale_ids:
        delete_report_record(report_id)
        try:
            storage.delete(metadata_object_key(report_id))
            storage.delete(export_pdf_object_key(report_id))
            storage.delete(source_pdf_object_key(report_id))
        except OSError:
            LOGGER.warning("persisted_report_cleanup_failed", extra={"report_id": report_id})
    if not REPORTS_DIR.exists():
        return
    metadata_files = sorted(
        REPORTS_DIR.glob("reports/*/metadata.json"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    for stale_path in metadata_files[MAX_STORED_REPORTS:]:
        report_id = stale_path.parent.name
        try:
            storage.delete(metadata_object_key(report_id))
            storage.delete(export_pdf_object_key(report_id))
            storage.delete(source_pdf_object_key(report_id))
        except OSError:
            LOGGER.warning("persisted_report_cleanup_failed", extra={"report_id": report_id})
