from pathlib import Path

# Supplier documents for tests: copies of evaluation set files, so the set
# can change without changing what the tests check, and documents that only
# tests need, such as manuals carrying a prompt injection.
DOCUMENTS_DIR = Path(__file__).parent / "documents"
