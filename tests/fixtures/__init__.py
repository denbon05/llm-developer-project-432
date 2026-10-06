from pathlib import Path

# Copies of supplier documents from the evaluation set. Tests read only these,
# so the evaluation set can change without changing what the tests check.
DOCUMENTS_DIR = Path(__file__).parent / "documents"
