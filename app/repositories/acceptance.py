"""Tables in the shape the external acceptance tests write and read"""

# TODO(acceptance): delete this module once the project is accepted. The
# external tests write chunks straight into a table of their own shape
# (doc_id text, no documents row). It lives in a schema of its own, so the
# product's tables never see it: a direct synchronous connection puts this
# schema first on its search_path.
from typing import Any

from app.core.config import get_settings

ACCEPTANCE_SCHEMA = "acceptance"


def create_acceptance_schema(conn: Any) -> None:
    """Create the acceptance tables if missing and search them first"""
    dimensions = get_settings().embedding_dimensions
    conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
    conn.execute(f"CREATE SCHEMA IF NOT EXISTS {ACCEPTANCE_SCHEMA}")
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {ACCEPTANCE_SCHEMA}.chunks (
            id bigserial PRIMARY KEY,
            chunk_id text,
            doc_id text,
            content text,
            text text,
            section text,
            page integer,
            chunk_index integer,
            metadata jsonb NOT NULL DEFAULT '{{}}',
            embedding vector({dimensions}),
            tsv tsvector GENERATED ALWAYS AS (
                to_tsvector('russian', coalesce(content, text, ''))
            ) STORED
        )
        """
    )
    conn.execute(f"SET search_path TO {ACCEPTANCE_SCHEMA}, public")
