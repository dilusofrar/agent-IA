from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from conferir_ponto.web import REPORTS, app, sanitize_download_name


class WebAppTests(unittest.TestCase):
    def setUp(self):
        REPORTS.clear()

    def test_process_endpoint_returns_summary(self):
        pdf_path = PROJECT_ROOT / "data" / "inputs" / "fev2026.pdf"
        client = TestClient(app)

        with pdf_path.open("rb") as file:
            response = client.post(
                "/api/process",
                files={"file": (pdf_path.name, file, "application/pdf")},
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["summary"]["businessDaysProcessed"], 22)
        self.assertEqual(payload["schedule"]["start"], "07:45")
        self.assertEqual(payload["schedule"]["end"], "17:00")
        self.assertIn("diagnostics", payload)
        self.assertIn("meta", payload)
        self.assertIn("processingDurationMs", payload["meta"])
        self.assertIn("paidOvertime", payload["summary"])
        self.assertIn("journeyCode", payload["days"][0])
        self.assertIn("appliedSchedule", payload["days"][0])
        self.assertIn("reportId", payload)

    def test_export_endpoint_returns_pdf(self):
        pdf_path = PROJECT_ROOT / "data" / "inputs" / "DIEGO_LUCAS_SOARES_DE_FREITAS_ARAUJO.pdf"
        client = TestClient(app)

        with pdf_path.open("rb") as file:
            process_response = client.post(
                "/api/process",
                files={"file": (pdf_path.name, file, "application/pdf")},
            )

        report_id = process_response.json()["reportId"]
        export_response = client.get(f"/api/export/{report_id}")

        self.assertEqual(export_response.status_code, 200)
        self.assertEqual(export_response.headers["content-type"], "application/pdf")
        self.assertIn(".pdf", export_response.headers["content-disposition"])
        self.assertEqual(export_response.headers["cache-control"], "no-store")
        self.assertEqual(export_response.headers["x-content-type-options"], "nosniff")
        self.assertTrue(export_response.content.startswith(b"%PDF"))

    def test_process_endpoint_rejects_large_pdf(self):
        client = TestClient(app)
        oversized_content = b"%PDF-1.4\n" + (b"0" * (10 * 1024 * 1024))

        response = client.post(
            "/api/process",
            files={"file": ("grande.pdf", oversized_content, "application/pdf")},
        )

        self.assertEqual(response.status_code, 413)
        self.assertIn("10 MB", response.json()["detail"])

    def test_export_endpoint_sanitizes_download_filename(self):
        client = TestClient(app)
        REPORTS["report-safe"] = {
            "filename": 'evil"\r\nX-Test: injected.pdf',
            "pdf": b"%PDF-1.4\nsafe\n",
        }

        response = client.get("/api/export/report-safe")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.headers["content-disposition"],
            'attachment; filename="evil_X-Test_injected_apuracao.pdf"',
        )

    def test_frontend_renders_pdf_content_without_inner_html_injection(self):
        app_js = (PROJECT_ROOT / "web" / "static" / "app.js").read_text(encoding="utf-8")

        self.assertNotIn("issuesListEl.innerHTML", app_js)
        self.assertNotIn("daysTableEl.innerHTML", app_js)
        self.assertNotIn("summaryGridEl.innerHTML", app_js)
        self.assertIn("createTextNode", app_js)

    def test_api_docs_are_disabled_by_default(self):
        client = TestClient(app)

        response = client.get("/docs")

        self.assertEqual(response.status_code, 404)

    def test_healthcheck_returns_security_headers(self):
        client = TestClient(app)

        response = client.get("/healthz")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["version"], "1.1.0")
        self.assertEqual(response.headers["x-frame-options"], "DENY")
        self.assertIn("frame-ancestors 'none'", response.headers["content-security-policy"])

    def test_recent_reports_endpoint_returns_latest_items(self):
        client = TestClient(app)
        with TemporaryDirectory() as temp_dir, patch("conferir_ponto.web.REPORTS_DIR", Path(temp_dir)):
            REPORTS["first"] = {
                "filename": "a.pdf",
                "pdf": b"%PDF-1.4\n",
                "recent": {
                    "reportId": "first",
                    "filename": "a.pdf",
                    "employeeName": "Primeiro",
                    "periodStart": "2026-04-01",
                    "periodEnd": "2026-04-30",
                    "processedAt": "2026-04-22T10:00:00",
                    "createdAt": "2026-04-22T10:00:00",
                    "processingDurationMs": 120,
                    "summary": {"businessDaysProcessed": 20, "inconsistencyCount": 1, "balance": "00:10", "paidOvertime": "00:00"},
                    "diagnostics": {"ignoredDays": 2},
                },
            }
            REPORTS["second"] = {
                "filename": "b.pdf",
                "pdf": b"%PDF-1.4\n",
                "recent": {
                    "reportId": "second",
                    "filename": "b.pdf",
                    "employeeName": "Segundo",
                    "periodStart": "2026-05-01",
                    "periodEnd": "2026-05-31",
                    "processedAt": "2026-05-22T10:00:00",
                    "createdAt": "2026-05-22T10:00:00",
                    "processingDurationMs": 95,
                    "summary": {"businessDaysProcessed": 21, "inconsistencyCount": 0, "balance": "01:00", "paidOvertime": "02:00"},
                    "diagnostics": {"ignoredDays": 0},
                },
            }

            response = client.get("/api/reports/recent")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["count"], 2)
        self.assertEqual(payload["items"][0]["reportId"], "second")
        self.assertEqual(payload["items"][1]["reportId"], "first")

    def test_recent_reports_endpoint_reads_persisted_items(self):
        client = TestClient(app)
        with TemporaryDirectory() as temp_dir:
            reports_dir = Path(temp_dir)
            reports_dir.joinpath("older.json").write_text(
                '{"reportId":"older","filename":"older.pdf","recent":{"reportId":"older","filename":"older.pdf","employeeName":"Mais antigo","createdAt":"2026-04-22T10:00:00","summary":{"balance":"00:10","inconsistencyCount":1,"paidOvertime":"00:00","businessDaysProcessed":20},"diagnostics":{}}}',
                encoding="utf-8",
            )
            reports_dir.joinpath("newer.json").write_text(
                '{"reportId":"newer","filename":"newer.pdf","recent":{"reportId":"newer","filename":"newer.pdf","employeeName":"Mais novo","createdAt":"2026-04-23T10:00:00","summary":{"balance":"01:00","inconsistencyCount":0,"paidOvertime":"02:00","businessDaysProcessed":21},"diagnostics":{}}}',
                encoding="utf-8",
            )
            with patch("conferir_ponto.web.REPORTS_DIR", reports_dir):
                response = client.get("/api/reports/recent")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["items"][0]["reportId"], "newer")
        self.assertEqual(payload["items"][1]["reportId"], "older")

    def test_export_endpoint_falls_back_to_persisted_report(self):
        client = TestClient(app)
        with TemporaryDirectory() as temp_dir:
            reports_dir = Path(temp_dir)
            report_id = "persisted-report"
            reports_dir.joinpath(f"{report_id}.json").write_text(
                '{"reportId":"persisted-report","filename":"persisted.pdf","recent":{"reportId":"persisted-report","filename":"persisted.pdf","createdAt":"2026-04-23T10:00:00","summary":{"balance":"00:00","inconsistencyCount":0,"paidOvertime":"00:00","businessDaysProcessed":1},"diagnostics":{}},"payload":{"reportId":"persisted-report","employeeName":"Persistido"}}',
                encoding="utf-8",
            )
            reports_dir.joinpath(f"{report_id}.pdf").write_bytes(b"%PDF-1.4\npersisted\n")

            with patch("conferir_ponto.web.REPORTS_DIR", reports_dir):
                response = client.get(f"/api/export/{report_id}")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "application/pdf")
        self.assertIn("persisted_apuracao.pdf", response.headers["content-disposition"])
        self.assertTrue(response.content.startswith(b"%PDF"))

    def test_report_details_endpoint_returns_persisted_payload(self):
        client = TestClient(app)
        with TemporaryDirectory() as temp_dir:
            reports_dir = Path(temp_dir)
            report_id = "persisted-report"
            reports_dir.joinpath(f"{report_id}.json").write_text(
                '{"reportId":"persisted-report","filename":"persisted.pdf","recent":{"reportId":"persisted-report"},"payload":{"reportId":"persisted-report","employeeName":"Persistido","summary":{"businessDaysProcessed":3}}}',
                encoding="utf-8",
            )
            reports_dir.joinpath(f"{report_id}.pdf").write_bytes(b"%PDF-1.4\npersisted\n")

            with patch("conferir_ponto.web.REPORTS_DIR", reports_dir):
                response = client.get(f"/api/reports/{report_id}")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["reportId"], "persisted-report")
        self.assertEqual(payload["employeeName"], "Persistido")
        self.assertEqual(payload["summary"]["businessDaysProcessed"], 3)

    def test_report_cache_discards_oldest_entry_when_limit_is_reached(self):
        client = TestClient(app)
        for index in range(32):
            REPORTS[f"existing-{index}"] = {
                "filename": f"report-{index}.pdf",
                "pdf": b"%PDF-1.4\ncached\n",
                "recent": {"reportId": f"existing-{index}"},
            }

        fake_payload = {
            "employeeName": "Teste",
            "periodStart": "2026-04-01",
            "periodEnd": "2026-04-30",
            "processedAt": "2026-04-11T10:00:00",
            "meta": {"calendarDays": 30, "includedDays": 1},
            "schedule": {"start": "07:45", "lunchStart": "12:00", "lunchEnd": "13:00", "end": "17:00", "workingWeekdays": [0, 1, 2, 3, 4], "source": None},
            "summary": {"businessDaysProcessed": 1, "ignoredDays": 0, "inconsistencyCount": 0, "worked": "08:00", "expected": "08:00", "balance": "00:00", "positiveBank": "00:00", "negativeBank": "00:00", "compensated": "00:00", "paidOvertime": "00:00", "overtimeBeforeLunch": "00:00", "overtimeAfterLunch": "00:00", "late": "00:00", "earlyLeave": "00:00"},
            "diagnostics": {"calendarDays": 30, "includedDays": 1, "ignoredDays": 0, "daysWithIssues": 0, "paidOvertimeDays": 0, "lateDays": 0, "earlyLeaveDays": 0, "weekendWorkedDays": 0, "holidayWorkedDays": 0, "missingPunchDays": 0, "ignoredBreakdown": []},
            "days": [],
        }

        with patch("conferir_ponto.web.parse_timecard_bytes", return_value=object()), patch(
            "conferir_ponto.web.build_summary_payload", return_value=fake_payload
        ), patch("conferir_ponto.web.export_analysis_to_pdf", return_value=b"%PDF-1.4\nnew\n"):
            response = client.post(
                "/api/process",
                files={"file": ("novo.pdf", b"%PDF-1.4\nfake\n", "application/pdf")},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(REPORTS), 32)
        self.assertNotIn("existing-0", REPORTS)

    def test_process_endpoint_persists_report_files(self):
        client = TestClient(app)
        fake_payload = {
            "employeeName": "Teste",
            "periodStart": "2026-04-01",
            "periodEnd": "2026-04-30",
            "processedAt": "2026-04-11T10:00:00",
            "meta": {"calendarDays": 30, "includedDays": 1},
            "schedule": {"start": "07:45", "lunchStart": "12:00", "lunchEnd": "13:00", "end": "17:00", "workingWeekdays": [0, 1, 2, 3, 4], "source": None},
            "summary": {"businessDaysProcessed": 1, "ignoredDays": 0, "inconsistencyCount": 0, "worked": "08:00", "expected": "08:00", "balance": "00:00", "positiveBank": "00:00", "negativeBank": "00:00", "compensated": "00:00", "paidOvertime": "00:00", "overtimeBeforeLunch": "00:00", "overtimeAfterLunch": "00:00", "late": "00:00", "earlyLeave": "00:00"},
            "diagnostics": {"calendarDays": 30, "includedDays": 1, "ignoredDays": 0, "daysWithIssues": 0, "paidOvertimeDays": 0, "lateDays": 0, "earlyLeaveDays": 0, "weekendWorkedDays": 0, "holidayWorkedDays": 0, "missingPunchDays": 0, "ignoredBreakdown": []},
            "days": [],
        }
        with TemporaryDirectory() as temp_dir, patch("conferir_ponto.web.REPORTS_DIR", Path(temp_dir)), patch(
            "conferir_ponto.web.parse_timecard_bytes", return_value=object()
        ), patch("conferir_ponto.web.build_summary_payload", return_value=fake_payload), patch(
            "conferir_ponto.web.export_analysis_to_pdf", return_value=b"%PDF-1.4\npersisted\n"
        ):
            response = client.post(
                "/api/process",
                files={"file": ("persistir.pdf", b"%PDF-1.4\nfake\n", "application/pdf")},
            )

            self.assertEqual(response.status_code, 200)
            response_payload = response.json()
            report_id = response_payload["reportId"]
            persisted_metadata = Path(temp_dir, f"{report_id}.json")
            self.assertTrue(persisted_metadata.exists())
            self.assertTrue(Path(temp_dir, f"{report_id}.pdf").exists())
            self.assertIn('"payload"', persisted_metadata.read_text(encoding="utf-8"))
            self.assertIn(response_payload["reportId"], persisted_metadata.read_text(encoding="utf-8"))


class WebHelpersTests(unittest.TestCase):
    def test_sanitize_download_name_removes_unsafe_characters(self):
        self.assertEqual(
            sanitize_download_name(' ../evil"\r\nname?.pdf '),
            "evil_name",
        )


if __name__ == "__main__":
    unittest.main()
