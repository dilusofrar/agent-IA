from __future__ import annotations

import argparse
import csv
import re
import sys
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INPUT_DIR = PROJECT_ROOT / "data" / "inputs"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "outputs"

MONTHS = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}

CSV_MONTHS = {
    1: "jan",
    2: "feb",
    3: "mar",
    4: "apr",
    5: "may",
    6: "jun",
    7: "jul",
    8: "aug",
    9: "sep",
    10: "oct",
    11: "nov",
    12: "dec",
}

PERIOD_PATTERN = re.compile(
    r"In[ií]cio Ponto:\s*(?P<start>\d{2}/\d{2}/\d{4}).*?Fim Ponto:\s*(?P<end>\d{2}/\d{2}/\d{4})",
    re.IGNORECASE | re.DOTALL,
)

DAY_HEADER_PATTERN = re.compile(
    r"^(?P<day>\d{2})\s+(Seg|Ter|Qua|Qui|Sex|Sab|Dom)$",
    re.IGNORECASE,
)

PUNCHES_PATTERN = re.compile(
    r"(?P<start>\d{2}:\d{2})\s+[oi]\s+"
    r"\d{2}:\d{2}\s+p\s+"
    r"\d{2}:\d{2}\s+p\s+"
    r"(?P<end>\d{2}:\d{2})\s+[oi]",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class PunchRecord:
    work_date: date
    start_time: str
    end_time: str

    @property
    def csv_row(self) -> dict[str, str]:
        day = f"{self.work_date.day:02d}"
        month = CSV_MONTHS[self.work_date.month]
        return {
            "Data": f"{day}/{month}",
            "Entrada": self.start_time,
            "Saida": self.end_time,
        }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extrai registros de ponto de um PDF e gera um CSV pronto para importacao."
    )
    parser.add_argument(
        "pdf",
        nargs="?",
        type=Path,
        help="Caminho do arquivo PDF. Se omitido, usa o primeiro PDF de data/inputs.",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="Caminho do CSV de saida. Padrao: data/outputs/<nome_do_pdf>.csv",
    )
    return parser.parse_args(argv)


def find_default_pdf() -> Path:
    pdfs = sorted(DEFAULT_INPUT_DIR.glob("*.pdf"))
    if not pdfs:
        raise FileNotFoundError(
            f"Nenhum PDF encontrado em '{DEFAULT_INPUT_DIR}'. Informe o arquivo manualmente."
        )
    return pdfs[0]


def read_pdf_text(pdf_path: Path) -> str:
    try:
        import fitz
    except ImportError as exc:  # pragma: no cover
        raise SystemExit(
            "PyMuPDF nao esta instalado. Instale com: python -m pip install -r requirements.txt"
        ) from exc

    with fitz.open(pdf_path) as document:
        return "\n".join(page.get_text() for page in document)


def extract_period_dates(text: str) -> tuple[date, date] | None:
    match = PERIOD_PATTERN.search(text)
    if not match:
        return None

    start_date = date.fromisoformat("-".join(reversed(match.group("start").split("/"))))
    end_date = date.fromisoformat("-".join(reversed(match.group("end").split("/"))))
    return start_date, end_date


def build_period_day_lookup(start_date: date, end_date: date) -> dict[int, list[date]]:
    lookup: dict[int, list[date]] = {}
    current = start_date
    while current <= end_date:
        lookup.setdefault(current.day, []).append(current)
        current += timedelta(days=1)
    return lookup


def resolve_work_date(
    day: int,
    day_lookup: dict[int, list[date]],
    last_date: date | None,
) -> date | None:
    candidates = day_lookup.get(day, [])
    if not candidates:
        return None
    if last_date is None:
        return candidates[0]
    for candidate in candidates:
        if candidate >= last_date:
            return candidate
    return candidates[-1]


def parse_records(text: str) -> list[PunchRecord]:
    records: list[PunchRecord] = []
    period = extract_period_dates(text)
    lines = [line.strip() for line in text.splitlines()]
    current_day: int | None = None
    last_date: date | None = None
    day_lookup = build_period_day_lookup(*period) if period else {}

    for line in lines:
        if not line:
            continue

        day_match = DAY_HEADER_PATTERN.match(line)
        if day_match:
            current_day = int(day_match.group("day"))
            continue

        punches_match = PUNCHES_PATTERN.search(line)
        if punches_match and current_day is not None:
            work_date: date | None = None
            if day_lookup:
                work_date = resolve_work_date(current_day, day_lookup, last_date)

            if work_date is None:
                continue

            records.append(
                PunchRecord(
                    work_date=work_date,
                    start_time=punches_match.group("start"),
                    end_time=punches_match.group("end"),
                )
            )
            last_date = work_date
            current_day = None

    unique_records = {
        (record.work_date, record.start_time, record.end_time): record for record in records
    }
    return [unique_records[key] for key in sorted(unique_records)]


def build_output_path(pdf_path: Path, output_path: Path | None) -> Path:
    if output_path is not None:
        return output_path
    return DEFAULT_OUTPUT_DIR / f"{pdf_path.stem}_extraido.csv"


def write_csv(records: list[PunchRecord], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=["Data", "Entrada", "Saida"])
        writer.writeheader()
        for record in records:
            writer.writerow(record.csv_row)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    pdf_path = args.pdf or find_default_pdf()
    pdf_path = pdf_path.resolve()
    output_path = build_output_path(pdf_path, args.output).resolve()

    if not pdf_path.exists():
        print(f"Arquivo PDF nao encontrado: {pdf_path}", file=sys.stderr)
        return 1

    text = read_pdf_text(pdf_path)
    records = parse_records(text)

    if not records:
        print(
            "Nenhum registro de ponto foi encontrado no PDF. Verifique se o layout do arquivo mudou.",
            file=sys.stderr,
        )
        return 2

    write_csv(records, output_path)
    print(f"PDF lido: {pdf_path}")
    print(f"Registros extraidos: {len(records)}")
    print(f"CSV gerado em: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
