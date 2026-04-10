from __future__ import annotations

import argparse
import sys
from pathlib import Path

from conferir_ponto.timecard import parse_timecard_pdf, write_analysis_csv


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extrai registros do cartao ponto PDF e gera um CSV consolidado."
    )
    parser.add_argument(
        "pdf",
        nargs="?",
        type=Path,
        help="Caminho do arquivo PDF. Se omitido, usa o primeiro PDF em data/inputs.",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="Caminho do CSV de saida. Padrao: data/outputs/<nome_do_pdf>_extraido.csv",
    )
    return parser.parse_args(argv)


def find_default_pdf() -> Path:
    pdfs = sorted(DEFAULT_INPUT_DIR.glob("*.pdf"))
    if not pdfs:
        raise FileNotFoundError(
            f"Nenhum PDF encontrado em '{DEFAULT_INPUT_DIR}'. Informe o arquivo manualmente."
        )
    return pdfs[0]


def build_output_path(pdf_path: Path, output_path: Path | None) -> Path:
    if output_path is not None:
        return output_path
    return DEFAULT_OUTPUT_DIR / f"{pdf_path.stem}_extraido.csv"


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    pdf_path = args.pdf or find_default_pdf()
    pdf_path = pdf_path.resolve()
    output_path = build_output_path(pdf_path, args.output).resolve()

    if not pdf_path.exists():
        print(f"Arquivo PDF nao encontrado: {pdf_path}", file=sys.stderr)
        return 1

    analysis = parse_timecard_pdf(pdf_path)
    write_analysis_csv(analysis, output_path)

    print(f"PDF lido: {pdf_path}")
    print(f"Periodo detectado: {analysis.period_start} ate {analysis.period_end}")
    print(f"Registros exportados em: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
