"""Tables in the shape the external acceptance tests write and read"""

# TODO(acceptance): delete this module once the project is accepted, and
# drop the schema from a development database:
#   DROP SCHEMA acceptance CASCADE;
# The external tests write documents and chunks straight into tables of
# their own shape (text ids, no file). Those live in a schema of their own,
# so the product's tables never see them: a direct synchronous connection
# puts this schema first on its search_path.
from typing import Any

from app.core.config import get_settings

ACCEPTANCE_SCHEMA = "acceptance"
# Columns by table, each added if missing
DOCUMENT_COLUMNS = {
    "filename": "text",
    "title": "text",
    "content_hash": "text",
    "kind": "text",
    "format": "text",
    "status": "text",
    "error": "text",
    "content": "bytea",
    "metadata": "jsonb NOT NULL DEFAULT '{}'",
    "created_at": "timestamptz NOT NULL DEFAULT now()",
}
CHUNK_COLUMNS = {
    "chunk_id": "text",
    "doc_id": "text",
    "content": "text",
    "text": "text",
    "section": "text",
    "page": "integer",
    "chunk_index": "integer",
    "metadata": "jsonb NOT NULL DEFAULT '{}'",
}


def add_columns(conn: Any, table: str, columns: dict[str, str]) -> None:
    """Add each column the table lacks"""
    for name, definition in columns.items():
        conn.execute(
            f"ALTER TABLE {ACCEPTANCE_SCHEMA}.{table} "
            f"ADD COLUMN IF NOT EXISTS {name} {definition}"
        )


def create_acceptance_schema(conn: Any) -> None:
    """Create the acceptance tables if missing and search them first"""
    dimensions = get_settings().embedding_dimensions
    conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
    conn.execute(f"CREATE SCHEMA IF NOT EXISTS {ACCEPTANCE_SCHEMA}")
    conn.execute(
        f"CREATE TABLE IF NOT EXISTS {ACCEPTANCE_SCHEMA}.documents "
        "(id text PRIMARY KEY)"
    )
    add_columns(conn, "documents", DOCUMENT_COLUMNS)
    conn.execute(
        f"CREATE TABLE IF NOT EXISTS {ACCEPTANCE_SCHEMA}.chunks "
        "(id bigserial PRIMARY KEY)"
    )
    add_columns(
        conn,
        "chunks",
        CHUNK_COLUMNS | {"embedding": f"vector({dimensions})"},
    )
    conn.execute(
        f"ALTER TABLE {ACCEPTANCE_SCHEMA}.chunks ADD COLUMN IF NOT EXISTS tsv "
        "tsvector GENERATED ALWAYS AS "
        "(to_tsvector('russian', coalesce(content, text, ''))) STORED"
    )
    conn.execute(f"SET search_path TO {ACCEPTANCE_SCHEMA}, public")
