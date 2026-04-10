from pathlib import Path
import sys
import unittest

from fastapi.testclient import TestClient


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from conferir_ponto.web import app


class WebAppTests(unittest.TestCase):
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
        self.assertIn("reportId", payload)


if __name__ == "__main__":
    unittest.main()
