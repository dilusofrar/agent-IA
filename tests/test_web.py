from pathlib import Path
import sys
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
        pdf_path = PROJECT_ROOT / "data" / "inputs" / "DIEGO_LUCAS_SOARES_DE_FREITAS_ARAUJO.pdf"
        client = TestClient(app)

        with pdf_path.open("rb") as file:
            response = client.post(
                "/api/process",
                files={"file": (pdf_path.name, file, "application/pdf")},
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["summary"]["businessDaysProcessed"], 19)
        self.assertEqual(payload["schedule"]["start"], "07:45")
        self.assertEqual(payload["schedule"]["end"], "17:00")
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
        self.assertEqual(response.headers["x-frame-options"], "DENY")
        self.assertIn("frame-ancestors 'none'", response.headers["content-security-policy"])

    def test_report_cache_discards_oldest_entry_when_limit_is_reached(self):
        client = TestClient(app)
        for index in range(32):
            REPORTS[f"existing-{index}"] = {
                "filename": f"report-{index}.pdf",
                "pdf": b"%PDF-1.4\ncached\n",
            }

        fake_payload = {
            "employeeName": "Teste",
            "periodStart": "2026-04-01",
            "periodEnd": "2026-04-30",
            "processedAt": "2026-04-11T10:00:00",
            "schedule": {"start": "07:45", "lunchStart": "12:00", "lunchEnd": "13:00", "end": "17:00", "workingWeekdays": [0, 1, 2, 3, 4], "source": None},
            "summary": {"businessDaysProcessed": 1, "ignoredDays": 0, "inconsistencyCount": 0, "worked": "08:00", "expected": "08:00", "balance": "00:00", "positiveBank": "00:00", "negativeBank": "00:00", "compensated": "00:00", "paidOvertime": "00:00", "overtimeBeforeLunch": "00:00", "overtimeAfterLunch": "00:00", "late": "00:00", "earlyLeave": "00:00"},
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


class WebHelpersTests(unittest.TestCase):
    def test_sanitize_download_name_removes_unsafe_characters(self):
        self.assertEqual(
            sanitize_download_name(' ../evil"\r\nname?.pdf '),
            "evil_name",
        )


if __name__ == "__main__":
    unittest.main()
