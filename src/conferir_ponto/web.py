from __future__ import annotations

from collections import OrderedDict
from datetime import datetime
import json
import logging
import os
from time import perf_counter
from pathlib import Path
import re
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

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
APP_VERSION = "1.1.0"
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
async def index() -> HTMLResponse:
    return HTMLResponse((STATIC_DIR / "index.html").read_text(encoding="utf-8"))


@app.get("/healthz")
async def healthcheck() -> JSONResponse:
    return JSONResponse({"status": "ok", "version": APP_VERSION})


@app.get("/api/reports/recent")
async def recent_reports() -> JSONResponse:
    items = load_recent_report_items(limit=RECENT_REPORTS_LIMIT)
    return JSONResponse({"items": items, "count": len(items)})


@app.post("/api/process")
async def process_pdf(file: UploadFile = File(...)) -> JSONResponse:
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

    try:
        analysis = parse_timecard_bytes(content)
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
    while len(REPORTS) >= MAX_STORED_REPORTS:
        REPORTS.popitem(last=False)
    REPORTS[report_id] = {
        "filename": file.filename,
        "pdf": export_analysis_to_pdf(analysis),
        "recent": build_recent_report_item(report_id, file.filename, payload),
    }
    persist_report(report_id, REPORTS[report_id])
    prune_persisted_reports()
    LOGGER.info(
        "process_completed",
        extra={
            "report_id": report_id,
            "filename": file.filename,
            "size_bytes": len(content),
            "duration_ms": processing_duration_ms,
            "issues": payload["summary"]["inconsistencyCount"],
            "included_days": payload["summary"]["businessDaysProcessed"],
        },
    )
    payload["reportId"] = report_id
    return JSONResponse(payload)


@app.get("/api/export/{report_id}")
async def export_report(report_id: str) -> Response:
    report = REPORTS.get(report_id)
    if report is None:
        report = load_report_from_disk(report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="Relatorio nao encontrado.")

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


def build_recent_report_item(report_id: str, filename: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "reportId": report_id,
        "filename": filename,
        "employeeName": payload.get("employeeName"),
        "periodStart": payload.get("periodStart"),
        "periodEnd": payload.get("periodEnd"),
        "processedAt": payload.get("processedAt"),
        "createdAt": payload.get("meta", {}).get("generatedAt"),
        "processingDurationMs": payload.get("meta", {}).get("processingDurationMs"),
        "summary": {
            "businessDaysProcessed": payload.get("summary", {}).get("businessDaysProcessed"),
            "inconsistencyCount": payload.get("summary", {}).get("inconsistencyCount"),
            "balance": payload.get("summary", {}).get("balance"),
            "paidOvertime": payload.get("summary", {}).get("paidOvertime"),
        },
        "diagnostics": payload.get("diagnostics", {}),
    }


def ensure_reports_dir() -> Path:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    return REPORTS_DIR


def metadata_path_for(report_id: str) -> Path:
    return ensure_reports_dir() / f"{report_id}.json"


def pdf_path_for(report_id: str) -> Path:
    return ensure_reports_dir() / f"{report_id}.pdf"


def persist_report(report_id: str, report: dict[str, Any]) -> None:
    metadata = {
        "reportId": report_id,
        "filename": report["filename"],
        "recent": report.get("recent", {}),
    }
    metadata_path_for(report_id).write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    pdf_path_for(report_id).write_bytes(report["pdf"])


def load_report_from_disk(report_id: str) -> dict[str, Any] | None:
    metadata_path = metadata_path_for(report_id)
    pdf_path = pdf_path_for(report_id)
    if not metadata_path.exists() or not pdf_path.exists():
        return None

    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    report = {
        "filename": metadata.get("filename", f"{report_id}.pdf"),
        "pdf": pdf_path.read_bytes(),
        "recent": metadata.get("recent", {}),
    }
    REPORTS[report_id] = report
    return report


def load_recent_report_items(limit: int = RECENT_REPORTS_LIMIT) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    if REPORTS_DIR.exists():
        for metadata_path in sorted(
            REPORTS_DIR.glob("*.json"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        ):
            try:
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            recent = metadata.get("recent")
            if recent:
                items.append(recent)
            if len(items) >= limit:
                break

    for report in reversed(REPORTS.values()):
        recent = report.get("recent")
        if not recent:
            continue
        if any(item.get("reportId") == recent.get("reportId") for item in items):
            continue
        items.append(recent)
        if len(items) >= limit:
            break

    items.sort(key=lambda item: item.get("createdAt") or item.get("processedAt") or "", reverse=True)
    return items[:limit]


def prune_persisted_reports() -> None:
    if not REPORTS_DIR.exists():
        return
    metadata_files = sorted(
        REPORTS_DIR.glob("*.json"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    for stale_path in metadata_files[MAX_STORED_REPORTS:]:
        report_id = stale_path.stem
        try:
            stale_path.unlink(missing_ok=True)
            pdf_path_for(report_id).unlink(missing_ok=True)
        except OSError:
            LOGGER.warning("persisted_report_cleanup_failed", extra={"report_id": report_id})
