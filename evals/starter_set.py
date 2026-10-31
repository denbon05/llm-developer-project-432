"""The starter supplier documents and their reference, as a reference set"""

# TODO(acceptance): the starter set in data/ is what the acceptance review
# evaluates; delete this module once the project is accepted.

import json
from pathlib import Path
from typing import Any

STARTER_DIR = Path(__file__).resolve().parents[1] / "data"
STARTER_REFERENCE_PATH = STARTER_DIR / "golden_cards.json"
# The reference's missing fields of a document without text: nothing can be
# read from it, so its ingestion must fail.
UNREADABLE_MARK = ["*"]


def read_starter_set() -> dict[str, Any]:
    """Return the starter reference in the fields of a reference set"""
    reference = json.loads(STARTER_REFERENCE_PATH.read_text())
    cases: list[dict[str, Any]] = []
    rejected_documents: list[str] = []
    for filename, card in reference["documents"].items():
        if card["missing_fields"] == UNREADABLE_MARK:
            rejected_documents.append(filename)
            continue
        probes = card.get("source_probes", {})
        blocked = card.get("injection_must_be_blocked", {})
        cases.append(
            {
                "id": Path(filename).stem,
                "documents": [filename],
                # Uploaded as is: a hint that names one SKU would leave the
                # other rows of a spreadsheet out.
                "hint": None,
                "characteristics": [
                    {
                        "names": [name],
                        "values": [value],
                        "quote": probes.get(name, {}).get("text_contains"),
                    }
                    for name, value in card["characteristics"].items()
                ],
                "missing_fields": [
                    {"names": [name]} for name in card["missing_fields"]
                ],
                "forbidden_texts": [
                    *card.get("pii_must_be_masked", []),
                    *blocked.get("card_must_not_contain", []),
                ],
            }
        )
    return {
        "subset": [Path(name).stem for name in reference["eval_defaults"]],
        "cases": cases,
        "rejected_documents": rejected_documents,
    }
