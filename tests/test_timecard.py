from pathlib import Path
import sys
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from conferir_ponto.timecard import format_minutes, parse_timecard_pdf


class TimecardTests(unittest.TestCase):
    def test_sample_pdf_analysis(self):
        pdf_path = PROJECT_ROOT / "data" / "inputs" / "DIEGO_LUCAS_SOARES_DE_FREITAS_ARAUJO.pdf"
        analysis = parse_timecard_pdf(pdf_path)

        self.assertEqual(analysis.period_start.isoformat(), "2025-04-16")
        self.assertEqual(analysis.period_end.isoformat(), "2025-05-15")
        self.assertEqual(len(analysis.days), 30)

        self.assertEqual(len(analysis.included_days), 18)

        april_16 = next(day for day in analysis.days if day.work_date.isoformat() == "2025-04-16")
        self.assertEqual(april_16.first_entry, "07:58")
        self.assertEqual(april_16.last_exit, "17:16")
        self.assertEqual(format_minutes(april_16.balance_minutes), "00:03")

        may_1 = next(day for day in analysis.days if day.work_date.isoformat() == "2025-05-01")
        self.assertTrue(may_1.ignored)


if __name__ == "__main__":
    unittest.main()
