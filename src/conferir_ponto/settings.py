from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any


BASE_DIR = Path(__file__).resolve().parents[2]
SETTINGS_PATH = BASE_DIR / "data" / "settings" / "apuracao.json"
DEFAULT_WORKING_WEEKDAYS = (0, 1, 2, 3, 4)


@dataclass(frozen=True)
class JourneyRuleSettings:
    count_overtime_before_start: bool = True
    late_tolerance_minutes: int = 0


@dataclass(frozen=True)
class ApuracaoSettings:
    default_schedule_start: str = "07:45"
    default_schedule_lunch_start: str = "12:00"
    default_schedule_lunch_end: str = "13:00"
    default_schedule_end: str = "17:00"
    working_weekdays: tuple[int, ...] = DEFAULT_WORKING_WEEKDAYS
    payable_weekends: bool = True
    payable_holidays: bool = True
    payable_status_codes: tuple[str, ...] = ("CO", "FE", "RE")
    journey_rules: dict[str, JourneyRuleSettings] = field(
        default_factory=lambda: {
            "0004": JourneyRuleSettings(
                count_overtime_before_start=False,
                late_tolerance_minutes=5,
            )
        }
    )

    def rule_for(self, journey_code: str | None) -> JourneyRuleSettings:
        if not journey_code or not self.journey_rules:
            return JourneyRuleSettings()
        return self.journey_rules.get(normalize_journey_code(journey_code), JourneyRuleSettings())


def default_settings_payload() -> dict[str, Any]:
    return {
        "defaultSchedule": {
            "start": "07:45",
            "lunchStart": "12:00",
            "lunchEnd": "13:00",
            "end": "17:00",
        },
        "workingWeekdays": [0, 1, 2, 3, 4],
        "paidHours": {
            "weekends": True,
            "holidays": True,
            "statusCodes": ["CO", "FE", "RE"],
        },
        "journeyRules": {
            "0004": {
                "countOvertimeBeforeStart": False,
                "lateToleranceMinutes": 5,
            }
        },
    }


def ensure_settings_file() -> None:
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not SETTINGS_PATH.exists():
        SETTINGS_PATH.write_text(
            json.dumps(default_settings_payload(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


def load_settings() -> ApuracaoSettings:
    ensure_settings_file()
    raw_payload = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    return parse_settings_payload(raw_payload)


def save_settings(raw_payload: dict[str, Any]) -> ApuracaoSettings:
    settings = parse_settings_payload(raw_payload)
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_PATH.write_text(
        json.dumps(settings_to_payload(settings), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return settings


def settings_to_payload(settings: ApuracaoSettings) -> dict[str, Any]:
    journey_rules = settings.journey_rules or {}
    return {
        "defaultSchedule": {
            "start": settings.default_schedule_start,
            "lunchStart": settings.default_schedule_lunch_start,
            "lunchEnd": settings.default_schedule_lunch_end,
            "end": settings.default_schedule_end,
        },
        "workingWeekdays": list(settings.working_weekdays),
        "paidHours": {
            "weekends": settings.payable_weekends,
            "holidays": settings.payable_holidays,
            "statusCodes": list(settings.payable_status_codes),
        },
        "journeyRules": {
            code: {
                "countOvertimeBeforeStart": rule.count_overtime_before_start,
                "lateToleranceMinutes": rule.late_tolerance_minutes,
            }
            for code, rule in sorted(journey_rules.items())
        },
    }


def parse_settings_payload(raw_payload: dict[str, Any] | None) -> ApuracaoSettings:
    payload = raw_payload or {}
    default_payload = default_settings_payload()
    default_schedule = payload.get("defaultSchedule", {})
    paid_hours = payload.get("paidHours", {})
    journey_rules_payload = payload.get("journeyRules", {})

    working_weekdays = tuple(
        sorted(
            {
                int(day)
                for day in payload.get("workingWeekdays", default_payload["workingWeekdays"])
                if int(day) in range(0, 7)
            }
        )
    ) or DEFAULT_WORKING_WEEKDAYS

    payable_status_codes = tuple(
        sorted(
            {
                str(code).strip().upper()
                for code in paid_hours.get("statusCodes", default_payload["paidHours"]["statusCodes"])
                if str(code).strip()
            }
        )
    ) or tuple(default_payload["paidHours"]["statusCodes"])

    journey_rules = {
        normalize_journey_code(code): JourneyRuleSettings(
            count_overtime_before_start=bool(rule_payload.get("countOvertimeBeforeStart", True)),
            late_tolerance_minutes=max(0, int(rule_payload.get("lateToleranceMinutes", 0))),
        )
        for code, rule_payload in journey_rules_payload.items()
        if str(code).strip()
    }

    if "0004" not in journey_rules:
        journey_rules["0004"] = JourneyRuleSettings(count_overtime_before_start=False, late_tolerance_minutes=5)

    return ApuracaoSettings(
        default_schedule_start=str(default_schedule.get("start", default_payload["defaultSchedule"]["start"])),
        default_schedule_lunch_start=str(default_schedule.get("lunchStart", default_payload["defaultSchedule"]["lunchStart"])),
        default_schedule_lunch_end=str(default_schedule.get("lunchEnd", default_payload["defaultSchedule"]["lunchEnd"])),
        default_schedule_end=str(default_schedule.get("end", default_payload["defaultSchedule"]["end"])),
        working_weekdays=working_weekdays,
        payable_weekends=bool(paid_hours.get("weekends", default_payload["paidHours"]["weekends"])),
        payable_holidays=bool(paid_hours.get("holidays", default_payload["paidHours"]["holidays"])),
        payable_status_codes=payable_status_codes,
        journey_rules=journey_rules,
    )


def normalize_journey_code(code: str) -> str:
    return str(code).zfill(4)
