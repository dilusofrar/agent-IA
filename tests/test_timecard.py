from pathlib import Path
import sys
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from conferir_ponto.settings import ApuracaoSettings
from conferir_ponto.timecard import (
    build_diagnostics_payload,
    build_summary_payload,
    format_minutes,
    parse_timecard_pdf,
    parse_timecard_text,
)


class TimecardTests(unittest.TestCase):
    def test_sample_pdf_analysis(self):
        pdf_path = PROJECT_ROOT / "data" / "inputs" / "fev2026.pdf"
        analysis = parse_timecard_pdf(pdf_path)

        self.assertEqual(analysis.period_start.isoformat(), "2026-01-16")
        self.assertEqual(analysis.period_end.isoformat(), "2026-02-15")
        self.assertEqual(len(analysis.days), 31)
        self.assertEqual(analysis.schedule.start.strftime("%H:%M"), "07:45")
        self.assertEqual(analysis.schedule.end.strftime("%H:%M"), "17:00")
        self.assertEqual(sorted(analysis.schedule.working_weekdays), [0, 1, 2, 3, 4])

        self.assertEqual(len(analysis.included_days), 22)

        january_16 = next(day for day in analysis.days if day.work_date.isoformat() == "2026-01-16")
        self.assertEqual(january_16.first_entry, "08:04")
        self.assertEqual(january_16.last_exit, "17:23")
        self.assertEqual(format_minutes(january_16.balance_minutes), "00:19")

        january_21 = next(day for day in analysis.days if day.work_date.isoformat() == "2026-01-21")
        self.assertEqual(format_minutes(january_21.late_minutes), "00:10")

        january_31 = next(day for day in analysis.days if day.work_date.isoformat() == "2026-01-31")
        self.assertFalse(january_31.ignored)
        self.assertEqual(format_minutes(january_31.worked_minutes), "01:00")
        self.assertEqual(format_minutes(january_31.balance_minutes), "00:00")
        self.assertEqual(format_minutes(january_31.payable_overtime_minutes), "01:00")

    def test_vacation_days_are_ignored_without_inconsistencies(self):
        pdf_path = PROJECT_ROOT / "data" / "inputs" / "marco2026.pdf"
        analysis = parse_timecard_pdf(pdf_path)

        self.assertEqual(analysis.period_start.isoformat(), "2026-02-16")
        self.assertEqual(analysis.period_end.isoformat(), "2026-03-15")
        self.assertEqual(analysis.schedule.start.strftime("%H:%M"), "07:45")
        self.assertEqual(len(analysis.included_days), 8)
        self.assertEqual(len(analysis.issues), 0)

        march_2 = next(day for day in analysis.days if day.work_date.isoformat() == "2026-03-02")
        self.assertTrue(march_2.ignored)
        self.assertEqual(march_2.ignored_reason, "Ferias")
        self.assertEqual(march_2.issues, [])

    def test_weekend_work_is_counted_as_overtime(self):
        text = """
Início Ponto: 01/03/2026
Fim Ponto: 02/03/2026
Matrícula: 1 - 1 TESTE USUARIO
01 Dom
RE
08:00 o 12:00 i 13:00 o 17:00 i
02 Seg
TB
07:45 o 12:00 i 13:00 o 17:00 i
"""
        analysis = parse_timecard_text(text)

        sunday = next(day for day in analysis.days if day.work_date.isoformat() == "2026-03-01")
        summary = build_summary_payload(analysis)["summary"]
        self.assertFalse(sunday.ignored)
        self.assertTrue(sunday.included_in_totals)
        self.assertEqual(format_minutes(sunday.worked_minutes), "08:00")
        self.assertEqual(format_minutes(sunday.expected_minutes), "00:00")
        self.assertEqual(format_minutes(sunday.balance_minutes), "00:00")
        self.assertEqual(format_minutes(sunday.payable_overtime_minutes), "08:00")
        self.assertEqual(format_minutes(sunday.overtime_before_lunch_minutes), "04:00")
        self.assertEqual(format_minutes(sunday.overtime_after_lunch_minutes), "04:00")
        self.assertEqual(sunday.issues, [])
        self.assertEqual(summary["paidOvertime"], "08:00")
        self.assertEqual(summary["positiveBank"], "00:00")

    def test_diagnostics_payload_counts_ignored_and_issue_days(self):
        text = """
Início Ponto: 01/03/2026
Fim Ponto: 04/03/2026
Matrícula: 1 - 1 TESTE USUARIO
01 Dom
RE
08:00 o 12:00 i 13:00 o 17:00 i
02 Seg
TB
07:45 o 12:00 i 13:00 o 17:00 i
03 Ter
TB
07:45 o
04 Qua
TB
FERIAS
"""
        analysis = parse_timecard_text(text)
        diagnostics = build_diagnostics_payload(analysis)
        payload = build_summary_payload(analysis)

        self.assertEqual(diagnostics["calendarDays"], 4)
        self.assertEqual(diagnostics["includedDays"], 2)
        self.assertEqual(diagnostics["paidOvertimeDays"], 1)
        self.assertEqual(diagnostics["daysWithIssues"], 1)
        self.assertEqual(diagnostics["missingPunchDays"], 1)
        self.assertEqual(diagnostics["ignoredDays"], 1)
        self.assertEqual(diagnostics["weekendWorkedDays"], 1)
        self.assertEqual(diagnostics["ignoredBreakdown"][0]["label"], "Ferias")
        self.assertEqual(payload["diagnostics"]["ignoredDays"], 1)
        self.assertEqual(payload["meta"]["calendarDays"], 4)

    def test_weekend_work_can_be_ignored_by_settings(self):
        text = """
Início Ponto: 01/03/2026
Fim Ponto: 01/03/2026
Matrícula: 1 - 1 TESTE USUARIO
01 Dom
RE
08:00 o 12:00 i 13:00 o 17:00 i
"""
        settings = ApuracaoSettings(
            payable_weekends=False,
            payable_holidays=False,
            payable_status_codes=(),
        )
        analysis = parse_timecard_text(text, settings=settings)
        sunday = analysis.days[0]

        self.assertTrue(sunday.ignored)
        self.assertFalse(sunday.included_in_totals)
        self.assertEqual(format_minutes(sunday.payable_overtime_minutes), "00:00")

    def test_known_journey_code_uses_persisted_schedule_when_pdf_has_no_definition(self):
        text = """
Início Ponto: 01/03/2026
Fim Ponto: 02/03/2026
Matrícula: 1 - 1 TESTE USUARIO
01 Dom
0999
RE
08:00 o 12:00 i 13:00 o 17:00 i
02 Seg
0048
TB
07:52 o 12:00 i 13:00 o 17:00 i
"""
        analysis = parse_timecard_text(text)

        sunday = next(day for day in analysis.days if day.work_date.isoformat() == "2026-03-01")
        monday = next(day for day in analysis.days if day.work_date.isoformat() == "2026-03-02")

        self.assertEqual(sunday.journey_code, "0999")
        self.assertEqual(sunday.applied_schedule_label, "08:00-12:00 / 13:00-17:00")
        self.assertEqual(monday.journey_code, "0048")
        self.assertEqual(monday.applied_schedule_label, "07:45-12:00 / 13:00-17:00")
        self.assertEqual(format_minutes(monday.late_minutes), "00:07")

    def test_compensation_day_with_punches_is_counted(self):
        pdf_path = PROJECT_ROOT / "data" / "inputs" / "nov2025.pdf"
        if not pdf_path.exists():
            self.skipTest("Fixture nov2025.pdf nao esta disponivel neste clone.")
        analysis = parse_timecard_pdf(pdf_path)
        summary = build_summary_payload(analysis)["summary"]

        december_13 = next(day for day in analysis.days if day.work_date.isoformat() == "2025-12-13")
        self.assertEqual(analysis.schedule.start.strftime("%H:%M"), "08:00")
        self.assertEqual(analysis.schedule.end.strftime("%H:%M"), "17:00")
        self.assertFalse(december_13.ignored)
        self.assertTrue(december_13.included_in_totals)
        self.assertEqual(december_13.status_code, "CO")
        self.assertEqual(format_minutes(december_13.worked_minutes), "15:40")
        self.assertEqual(format_minutes(december_13.balance_minutes), "00:00")
        self.assertEqual(format_minutes(december_13.payable_overtime_minutes), "15:40")
        self.assertEqual(format_minutes(december_13.overtime_before_lunch_minutes), "04:12")
        self.assertEqual(format_minutes(december_13.overtime_after_lunch_minutes), "10:28")
        self.assertEqual(december_13.issues, [])

        november_17 = next(day for day in analysis.days if day.work_date.isoformat() == "2025-11-17")
        self.assertEqual(november_17.first_entry, "08:10")
        self.assertEqual(format_minutes(november_17.late_minutes), "00:10")
        self.assertEqual(summary["paidOvertime"], "15:40")

    def test_february_2026_mixes_normal_and_compensation_schedules(self):
        pdf_path = PROJECT_ROOT / "data" / "inputs" / "fev2026.pdf"
        analysis = parse_timecard_pdf(pdf_path)
        summary = build_summary_payload(analysis)["summary"]

        january_16 = next(day for day in analysis.days if day.work_date.isoformat() == "2026-01-16")
        february_2 = next(day for day in analysis.days if day.work_date.isoformat() == "2026-02-02")
        january_31 = next(day for day in analysis.days if day.work_date.isoformat() == "2026-01-31")

        self.assertEqual(format_minutes(january_16.late_minutes), "00:00")
        self.assertEqual(format_minutes(january_16.balance_minutes), "00:19")
        self.assertEqual(format_minutes(next(day for day in analysis.days if day.work_date.isoformat() == "2026-01-21").late_minutes), "00:10")
        self.assertEqual(format_minutes(february_2.late_minutes), "00:27")
        self.assertEqual(format_minutes(january_31.payable_overtime_minutes), "01:00")
        self.assertEqual(summary["positiveBank"], "13:50")
        self.assertEqual(summary["negativeBank"], "06:55")
        self.assertEqual(summary["balance"], "06:55")
        self.assertEqual(summary["paidOvertime"], "01:00")


if __name__ == "__main__":
    unittest.main()
