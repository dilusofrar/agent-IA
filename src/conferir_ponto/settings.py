from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import json
from pathlib import Path
from typing import Any


BASE_DIR = Path(__file__).resolve().parents[2]
SETTINGS_PATH = BASE_DIR / "data" / "settings" / "apuracao.json"
SETTINGS_HISTORY_PATH = BASE_DIR / "data" / "settings" / "apuracao-history.jsonl"
DEFAULT_WORKING_WEEKDAYS = (0, 1, 2, 3, 4)
MAX_SETTINGS_HISTORY_ENTRIES = 100


@dataclass(frozen=True)
class JourneyRuleSettings:
    count_overtime_before_start: bool = True
    late_tolerance_minutes: int = 0


@dataclass(frozen=True)
class JourneyScheduleSettings:
    start: str
    lunch_start: str
    lunch_end: str
    end: str


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
    journey_schedules: dict[str, JourneyScheduleSettings] = field(
        default_factory=lambda: {
            "0004": JourneyScheduleSettings("08:00", "12:00", "13:00", "17:00"),
            "0048": JourneyScheduleSettings("07:45", "12:00", "13:00", "17:00"),
            "0999": JourneyScheduleSettings("08:00", "12:00", "13:00", "17:00"),
        }
    )
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
        "journeySchedules": {
            "0004": {
                "start": "08:00",
                "lunchStart": "12:00",
                "lunchEnd": "13:00",
                "end": "17:00",
            },
            "0048": {
                "start": "07:45",
                "lunchStart": "12:00",
                "lunchEnd": "13:00",
                "end": "17:00",
            },
            "0999": {
                "start": "08:00",
                "lunchStart": "12:00",
                "lunchEnd": "13:00",
                "end": "17:00",
            },
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
        "journeySchedules": {
            code: {
                "start": schedule.start,
                "lunchStart": schedule.lunch_start,
                "lunchEnd": schedule.lunch_end,
                "end": schedule.end,
            }
            for code, schedule in sorted((settings.journey_schedules or {}).items())
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
    journey_schedules_payload = payload.get("journeySchedules", {})
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

    journey_schedules = {
        normalize_journey_code(code): JourneyScheduleSettings(
            start=str(schedule_payload.get("start", default_payload["journeySchedules"]["0004"]["start"])),
            lunch_start=str(schedule_payload.get("lunchStart", default_payload["journeySchedules"]["0004"]["lunchStart"])),
            lunch_end=str(schedule_payload.get("lunchEnd", default_payload["journeySchedules"]["0004"]["lunchEnd"])),
            end=str(schedule_payload.get("end", default_payload["journeySchedules"]["0004"]["end"])),
        )
        for code, schedule_payload in journey_schedules_payload.items()
        if str(code).strip()
    }

    for code, schedule_payload in default_payload["journeySchedules"].items():
        normalized_code = normalize_journey_code(code)
        if normalized_code not in journey_schedules:
            journey_schedules[normalized_code] = JourneyScheduleSettings(
                start=str(schedule_payload["start"]),
                lunch_start=str(schedule_payload["lunchStart"]),
                lunch_end=str(schedule_payload["lunchEnd"]),
                end=str(schedule_payload["end"]),
            )

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
        journey_schedules=journey_schedules,
        journey_rules=journey_rules,
    )


def normalize_journey_code(code: str) -> str:
    return str(code).zfill(4)


def load_settings_history(limit: int = 12) -> list[dict[str, Any]]:
    if not SETTINGS_HISTORY_PATH.exists():
        return []

    items: list[dict[str, Any]] = []
    with SETTINGS_HISTORY_PATH.open("r", encoding="utf-8") as history_file:
        for line in history_file:
            raw_line = line.strip()
            if not raw_line:
                continue
            try:
                items.append(json.loads(raw_line))
            except json.JSONDecodeError:
                continue

    items.sort(key=lambda item: item.get("changedAt", ""), reverse=True)
    return items[: max(0, int(limit))]


def append_settings_history(
    actor: str,
    before_payload: dict[str, Any],
    after_payload: dict[str, Any],
) -> dict[str, Any] | None:
    changes = summarize_settings_changes(before_payload, after_payload)
    if not changes:
        return None

    SETTINGS_HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "changedAt": datetime.now().isoformat(timespec="seconds"),
        "actor": actor or "admin",
        "changes": changes,
        "settings": after_payload,
    }
    with SETTINGS_HISTORY_PATH.open("a", encoding="utf-8") as history_file:
        history_file.write(json.dumps(entry, ensure_ascii=False) + "\n")
    prune_settings_history()
    return entry


def prune_settings_history() -> None:
    if not SETTINGS_HISTORY_PATH.exists():
        return
    lines = SETTINGS_HISTORY_PATH.read_text(encoding="utf-8").splitlines()
    if len(lines) <= MAX_SETTINGS_HISTORY_ENTRIES:
        return
    SETTINGS_HISTORY_PATH.write_text(
        "\n".join(lines[-MAX_SETTINGS_HISTORY_ENTRIES:]) + "\n",
        encoding="utf-8",
    )


def summarize_settings_changes(
    before_payload: dict[str, Any] | None,
    after_payload: dict[str, Any] | None,
) -> list[str]:
    before = before_payload or {}
    after = after_payload or {}
    changes: list[str] = []

    before_schedule = describe_schedule(before.get("defaultSchedule", {}))
    after_schedule = describe_schedule(after.get("defaultSchedule", {}))
    if before_schedule != after_schedule:
        changes.append(f"Jornada padrão: {before_schedule} -> {after_schedule}")

    before_weekdays = describe_weekdays(before.get("workingWeekdays"))
    after_weekdays = describe_weekdays(after.get("workingWeekdays"))
    if before_weekdays != after_weekdays:
        changes.append(f"Dias úteis: {before_weekdays} -> {after_weekdays}")

    before_paid = before.get("paidHours", {})
    after_paid = after.get("paidHours", {})
    if bool(before_paid.get("weekends")) != bool(after_paid.get("weekends")):
        changes.append(
            "Horas em fim de semana: "
            + ("pagas" if bool(after_paid.get("weekends")) else "ignoradas")
        )
    if bool(before_paid.get("holidays")) != bool(after_paid.get("holidays")):
        changes.append(
            "Horas em feriado: "
            + ("pagas" if bool(after_paid.get("holidays")) else "ignoradas")
        )

    before_codes = tuple(sorted(str(code).strip().upper() for code in before_paid.get("statusCodes", []) if str(code).strip()))
    after_codes = tuple(sorted(str(code).strip().upper() for code in after_paid.get("statusCodes", []) if str(code).strip()))
    if before_codes != after_codes:
        changes.append(
            "Status pagos: "
            + (", ".join(before_codes) if before_codes else "nenhum")
            + " -> "
            + (", ".join(after_codes) if after_codes else "nenhum")
        )

    before_rule = (before.get("journeyRules", {}) or {}).get("0004", {})
    after_rule = (after.get("journeyRules", {}) or {}).get("0004", {})
    before_tolerance = int(before_rule.get("lateToleranceMinutes", 0) or 0)
    after_tolerance = int(after_rule.get("lateToleranceMinutes", 0) or 0)
    if before_tolerance != after_tolerance:
        changes.append(
            f"JRND 0004: tolerância de atraso {before_tolerance} min -> {after_tolerance} min"
        )
    before_extra = bool(before_rule.get("countOvertimeBeforeStart"))
    after_extra = bool(after_rule.get("countOvertimeBeforeStart"))
    if before_extra != after_extra:
        changes.append(
            "JRND 0004: extra antes do início "
            + ("ativada" if after_extra else "desativada")
        )

    return changes


def describe_schedule(schedule_payload: dict[str, Any] | None) -> str:
    schedule = schedule_payload or {}
    start = str(schedule.get("start", "--:--"))
    lunch_start = str(schedule.get("lunchStart", "--:--"))
    lunch_end = str(schedule.get("lunchEnd", "--:--"))
    end = str(schedule.get("end", "--:--"))
    return f"{start}-{lunch_start} / {lunch_end}-{end}"


def describe_weekdays(values: list[int] | tuple[int, ...] | None) -> str:
    weekday_names = ("Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom")
    selected = [weekday_names[int(value)] for value in values or [] if int(value) in range(0, 7)]
    return ", ".join(selected) if selected else "nenhum"
    before_schedules = before.get("journeySchedules", {}) or {}
    after_schedules = after.get("journeySchedules", {}) or {}
    for code in ("0004", "0048", "0999"):
        before_label = describe_schedule(before_schedules.get(code))
        after_label = describe_schedule(after_schedules.get(code))
        if before_label != after_label:
            changes.append(f"JRND {code}: {before_label} -> {after_label}")
