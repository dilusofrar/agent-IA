from __future__ import annotations

from pathlib import Path
from typing import Dict
from uuid import uuid4

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from conferir_ponto.timecard import (
    build_summary_payload,
    export_analysis_to_pdf,
    export_analysis_to_xlsx,
    parse_timecard_bytes,
)


BASE_DIR = Path(__file__).resolve().parents[2]
STATIC_DIR = BASE_DIR / "web" / "static"
app = FastAPI(title="Agent IA Ponto", version="1.0.0")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

REPORTS: Dict[str, dict] = {}


@app.get("/", response_class=HTMLResponse)
async def index() -> HTMLResponse:
    return HTMLResponse((STATIC_DIR / "index.html").read_text(encoding="utf-8"))


@app.post("/api/process")
async def process_pdf(file: UploadFile = File(...)) -> JSONResponse:
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Envie um arquivo PDF valido.")

    content = await file.read()

    try:
        analysis = parse_timecard_bytes(content)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    payload = build_summary_payload(analysis)
    report_id = uuid4().hex
    REPORTS[report_id] = {
        "filename": file.filename,
        "pdf": export_analysis_to_pdf(analysis),
    }
    payload["reportId"] = report_id
    return JSONResponse(payload)


@app.get("/api/export/{report_id}")
async def export_report(report_id: str) -> Response:
    report = REPORTS.get(report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="Relatorio nao encontrado.")

    original_name = Path(report["filename"]).stem
    return Response(
        content=report["pdf"],
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{original_name}_apuracao.pdf"'
        },
    )
