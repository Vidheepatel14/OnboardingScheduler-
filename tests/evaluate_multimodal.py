import csv
from pathlib import Path
from typing import Iterable

import sys

sys.path.append(str(Path(__file__).resolve().parents[1]))

from src.core.document_qa import answer_question_about_file

OUT_CSV = Path(__file__).resolve().parent / "multimodal_evaluation.csv"

EVAL_SET = [
    {
        "query": "Are occasional and seasonal employees eligible for PTO?",
        "pdf_file": "PTO_Policy.pdf",
        "image_file": "PTO_Policy.png",
    },
    {
        "query": "How many total annual hours of PTO does a full-time 40-hour employee with 5 years of service get?",
        "pdf_file": "PTO_Policy.pdf",
        "image_file": "PTO_Policy.png",
    },
]


def run_cross_modal_eval(eval_set: Iterable[dict], out_csv: Path) -> None:
    results = []
    out_csv.parent.mkdir(parents=True, exist_ok=True)

    for item in eval_set:
        query = item["query"]
        pdf_path = item["pdf_file"]
        image_path = item["image_file"]

        pdf_answer = answer_question_about_file(pdf_path, query) if Path(pdf_path).exists() else f"[File Not Found: {pdf_path}]"
        image_answer = (
            answer_question_about_file(image_path, query) if Path(image_path).exists() else f"[File Not Found: {image_path}]"
        )

        results.append(
            {
                "query": query,
                "pdf_file": pdf_path,
                "pdf_answer": pdf_answer,
                "image_file": image_path,
                "image_answer": image_answer,
            }
        )

    with out_csv.open(mode="w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["query", "pdf_file", "pdf_answer", "image_file", "image_answer"],
        )
        writer.writeheader()
        writer.writerows(results)


if __name__ == "__main__":
    run_cross_modal_eval(EVAL_SET, OUT_CSV)
