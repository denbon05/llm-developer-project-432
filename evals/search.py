"""Search the ingested documents, or evaluate search on reference queries"""

import argparse
import asyncio
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from uuid import UUID

from evals.dataset_files import DATASETS_DIR, find_document_files
from evals.expected_chunks import ExpectedChunk, is_expected_chunk
from pydantic import BaseModel, TypeAdapter

from app.core import db
from app.core.bootstrap import bootstrap
from app.core.config import Settings
from app.rag import embedder
from app.rag.retrieval import search
from app.repositories import documents as documents_repository
from app.schemas.documents import (
    SEARCH_DEFAULT_MODE,
    SEARCH_DEFAULT_TOP_K,
    DocumentStatus,
    DocumentView,
    SearchMode,
    SearchRequest,
    SearchResult,
)

EVALS_DIR = Path(__file__).resolve().parent
GOLDENS_DIR = EVALS_DIR / "goldens" / "search"
REPORTS_DIR = EVALS_DIR / "reports"
LANGUAGES = ("en", "ru")
DEFAULT_LANGUAGE = "en"
# Ranks are looked for within the top 20, as many candidates as hybrid
# search fuses by default.
EVALUATION_DEPTH = 20
RECALL_DEPTH = 5
# Cosine similarity never falls below -1, so this threshold keeps every chunk.
NO_THRESHOLD = -1.0
# Shown rounded, so a rerun on unchanged data writes an unchanged report
SIMILARITY_DIGITS = 3
PREVIEW_LENGTH = 100
NO_VALUE = "-"
ANSWERED_KINDS = ("characteristic", "sku")
NOISE_KIND = "noise"
# The subcommands: python -m evals.search query "FAN-50" | eval --lang ru
QUERY_COMMAND = "query"
EVAL_COMMAND = "eval"

QueryKind = Literal["characteristic", "sku", "noise"]


class ReferenceQuery(BaseModel):
    """A query and the chunks that answer it; a noise query expects none"""

    query: str
    kind: QueryKind
    expected: list[ExpectedChunk] = []


@dataclass
class QueryOutcome:
    """How each mode did on one reference query"""

    query: ReferenceQuery
    # Per mode, with the threshold on: the best rank of an expected chunk
    # within the top 20, or None
    ranks: dict[SearchMode, int | None]
    # Per mode, with the threshold on: how many chunks it returned
    result_counts: dict[SearchMode, int]
    # With the threshold off: an answered query's best expected chunk, or a
    # noise query's top chunk; None when there is none in the top 20
    similarity: float | None


def parse_arguments() -> argparse.Namespace:
    """Return the command-line arguments"""
    parser = argparse.ArgumentParser(description=__doc__)
    # Each subcommand has its own arguments. The chosen one's name lands in
    # arguments.command, and running without one is an error.
    commands = parser.add_subparsers(dest="command", required=True)
    query_parser = commands.add_parser(QUERY_COMMAND, help="run one search")
    query_parser.add_argument("query", help="the search query")
    query_parser.add_argument(
        "--mode",
        type=SearchMode,
        choices=list(SearchMode),
        default=SEARCH_DEFAULT_MODE,
    )
    query_parser.add_argument("--top-k", type=int, default=SEARCH_DEFAULT_TOP_K)
    eval_parser = commands.add_parser(
        EVAL_COMMAND, help="run the reference queries and write the report"
    )
    eval_parser.add_argument(
        "--lang", choices=LANGUAGES, default=DEFAULT_LANGUAGE
    )
    return parser.parse_args()


async def find_indexed_documents() -> list[DocumentView]:
    """Return the indexed documents, the ones search covers"""
    return await documents_repository.find_documents(DocumentStatus.INDEXED)


def hash_reference_files() -> dict[str, str]:
    """Return the name of each file of evals/datasets/, by content hash"""
    # The content hash is a document's identity, so a file renamed since its
    # upload still counts, and another file under the same name doesn't.
    return {
        documents_repository.hash_content(path.read_bytes()): path.name
        for path in find_document_files(DATASETS_DIR)
    }


def map_filenames(documents: list[DocumentView]) -> dict[UUID, str]:
    """Return each document's file name by its id"""
    return {document.id: document.filename for document in documents}


def print_results(
    results: list[SearchResult], filenames: dict[UUID, str]
) -> None:
    """Print one line per result, best first"""
    if not results:
        print("no results")
    for position, result in enumerate(results, start=1):
        metadata = result.metadata
        preview = " / ".join(result.text.splitlines())[:PREVIEW_LENGTH]
        print(
            f"{position}. score={result.score:.3f} "
            f"vector={result.vector_rank or NO_VALUE} "
            f"keyword={result.keyword_rank or NO_VALUE}  "
            f"{filenames[result.document_id]}  page {metadata['page']}  "
            f"{metadata['section'] or NO_VALUE}  "
            f"{metadata.get('sku', NO_VALUE)}\n"
            f"   {preview}"
        )


def is_expected(
    result: SearchResult, filenames: dict[UUID, str], query: ReferenceQuery
) -> bool:
    """Return whether the result is one of the chunks the query expects"""
    return is_expected_chunk(
        filenames[result.document_id], result.metadata, query.expected
    )


async def evaluate_query(
    query: ReferenceQuery, filenames: dict[UUID, str]
) -> QueryOutcome:
    """Run the query in every mode and measure how each did"""
    ranks: dict[SearchMode, int | None] = {}
    result_counts: dict[SearchMode, int] = {}
    # Only the reference documents: whatever else the database holds must
    # not change the report.
    document_ids = list(filenames)
    for mode in SearchMode:
        results = await search(
            SearchRequest(
                query=query.query,
                mode=mode,
                top_k=EVALUATION_DEPTH,
                document_ids=document_ids,
            )
        )
        result_counts[mode] = len(results)
        ranks[mode] = next(
            (
                position
                for position, result in enumerate(results, start=1)
                if is_expected(result, filenames, query)
            ),
            None,
        )
    # With the threshold off, to see where answers and noise really lie
    unfiltered = await search(
        SearchRequest(
            query=query.query,
            mode=SearchMode.VECTOR,
            top_k=EVALUATION_DEPTH,
            document_ids=document_ids,
            min_similarity=NO_THRESHOLD,
        )
    )
    # A noise query has no answer, so its top chunk is measured: [:1] keeps
    # at most the first result. An answered query measures its best answer.
    measured = (
        unfiltered[:1]
        if query.kind == NOISE_KIND
        else [
            result
            for result in unfiltered
            if is_expected(result, filenames, query)
        ]
    )
    similarity = measured[0].score if measured else None
    return QueryOutcome(query, ranks, result_counts, similarity)


def format_similarity(similarity: float | None) -> str:
    """Return the similarity with three decimals, or a dash"""
    if similarity is None:
        return NO_VALUE
    return f"{similarity:.{SIMILARITY_DIGITS}f}"


def format_passes(similarity: float | None, threshold: float) -> str:
    """Return whether the similarity passes the threshold, in words"""
    if similarity is None:
        return NO_VALUE
    return "yes" if similarity >= threshold else "no"


def build_report(
    language: str,
    outcomes: list[QueryOutcome],
    settings: Settings,
    documents: list[DocumentView],
) -> str:
    """Return the evaluation report as Markdown"""
    threshold = settings.search_min_similarity
    command = "make eval-search" + (
        "" if language == DEFAULT_LANGUAGE else f" lang={language}"
    )
    lines = [
        f"# Search evaluation: {language}",
        "",
        f"- Model: `{settings.embedding_model}`",
        f"- Query prefix: `{settings.embedding_query_prefix}`",
        f"- Chunk prefix: `{settings.embedding_chunk_prefix}`",
        f"- Similarity threshold: {threshold}",
        # What the run searched, so reports compare only on the same data.
        # No run time: a rerun on unchanged data leaves the file unchanged.
        (
            f"- Data: {len(documents)} indexed documents of evals/datasets/, "
            f"{sum(document.chunk_count for document in documents)} chunks"
        ),
        "",
        (
            f"Written by `{command}`. Ranks are positions within the top "
            f"{EVALUATION_DEPTH}, with the threshold on; `{NO_VALUE}` means "
            "not found. Similarities are measured with the threshold off."
        ),
        "",
        *build_recall_table(outcomes),
        "",
        *build_window_table(outcomes),
        "",
        *build_answer_table(outcomes, threshold),
        "",
        *build_noise_table(outcomes, threshold),
    ]
    return "\n".join(lines) + "\n"


def select_kind(
    outcomes: list[QueryOutcome], kinds: tuple[str, ...]
) -> list[QueryOutcome]:
    """Return the outcomes of queries of these kinds"""
    return [outcome for outcome in outcomes if outcome.query.kind in kinds]


def build_recall_table(outcomes: list[QueryOutcome]) -> list[str]:
    """Return the recall@5 section: per mode and kind of query"""
    groups = [
        *(select_kind(outcomes, (kind,)) for kind in ANSWERED_KINDS),
        select_kind(outcomes, ANSWERED_KINDS),
    ]
    lines = [
        f"## Recall@{RECALL_DEPTH}",
        "",
        (
            "Characteristic and SKU queries with an expected chunk in the "
            f"top {RECALL_DEPTH}, with the threshold on."
        ),
        "",
        "| Mode | Characteristic | SKU | All |",
        "|------|----------------|-----|-----|",
    ]
    for mode in SearchMode:
        cells = [count_recalled(group, mode) for group in groups]
        lines.append(f"| {mode} | {' | '.join(cells)} |")
    return lines


def build_window_table(outcomes: list[QueryOutcome]) -> list[str]:
    """Return the threshold window section: noise ceiling, relevant floors"""
    noise = measure(select_kind(outcomes, (NOISE_KIND,)))
    lines = [
        "## Threshold window",
        "",
        (
            "A threshold above the noise ceiling, and no higher than a "
            "relevant floor, keeps those answers and drops all noise."
        ),
        "",
        "| Measure | Similarity | Query |",
        "|---------|------------|-------|",
        format_window_row(
            "Noise ceiling: highest top-1 of a noise query",
            max(noise, key=read_similarity, default=None),
        ),
    ]
    for kind in ANSWERED_KINDS:
        answers = measure(select_kind(outcomes, (kind,)))
        lines.append(
            format_window_row(
                f"Relevant floor: lowest answer to a {kind} query",
                min(answers, key=read_similarity, default=None),
            )
        )
    return lines


def build_answer_table(
    outcomes: list[QueryOutcome], threshold: float
) -> list[str]:
    """Return the section of characteristic and SKU queries"""
    lines = [
        "## Characteristic and SKU queries",
        "",
        (
            "| Query | Kind | Vector | Keyword | Hybrid | Vector similarity "
            "| Above threshold |"
        ),
        (
            "|-------|------|--------|---------|--------|-------------------"
            "|-----------------|"
        ),
    ]
    for outcome in select_kind(outcomes, ANSWERED_KINDS):
        ranks = [str(outcome.ranks[mode] or NO_VALUE) for mode in SearchMode]
        lines.append(
            f"| {outcome.query.query} | {outcome.query.kind} | "
            f"{' | '.join(ranks)} | {format_similarity(outcome.similarity)} | "
            f"{format_passes(outcome.similarity, threshold)} |"
        )
    return lines


def build_noise_table(
    outcomes: list[QueryOutcome], threshold: float
) -> list[str]:
    """Return the section of noise queries"""
    lines = [
        "## Noise queries",
        "",
        (
            "How many chunks each mode returns with the threshold on, and "
            "the top chunk's similarity with it off."
        ),
        "",
        (
            "| Query | Vector | Keyword | Hybrid | Top-1 vector similarity "
            "| Above threshold |"
        ),
        (
            "|-------|--------|---------|--------|-------------------------"
            "|-----------------|"
        ),
    ]
    for outcome in select_kind(outcomes, (NOISE_KIND,)):
        counts = [str(outcome.result_counts[mode]) for mode in SearchMode]
        lines.append(
            f"| {outcome.query.query} | {' | '.join(counts)} | "
            f"{format_similarity(outcome.similarity)} | "
            f"{format_passes(outcome.similarity, threshold)} |"
        )
    return lines


def count_recalled(outcomes: list[QueryOutcome], mode: SearchMode) -> str:
    """Return how many outcomes have an expected chunk in the top 5"""
    recalled = [
        outcome
        for outcome in outcomes
        if (rank := outcome.ranks[mode]) is not None and rank <= RECALL_DEPTH
    ]
    return f"{len(recalled)}/{len(outcomes)}"


def measure(outcomes: list[QueryOutcome]) -> list[QueryOutcome]:
    """Return the outcomes with a measured similarity"""
    return [outcome for outcome in outcomes if outcome.similarity is not None]


def read_similarity(outcome: QueryOutcome) -> float:
    """Return the outcome's measured similarity"""
    assert outcome.similarity is not None  # only measured outcomes come here
    return outcome.similarity


def format_window_row(label: str, outcome: QueryOutcome | None) -> str:
    """Return a threshold window row for the outcome, if there is one"""
    if outcome is None:
        return f"| {label} | {NO_VALUE} | {NO_VALUE} |"
    return (
        f"| {label} | {format_similarity(outcome.similarity)} | "
        f"{outcome.query.query} |"
    )


async def run_query(arguments: argparse.Namespace) -> int:
    """Run one search, print its results and return the exit code"""
    results = await search(
        SearchRequest(
            query=arguments.query, mode=arguments.mode, top_k=arguments.top_k
        )
    )
    print_results(results, map_filenames(await find_indexed_documents()))
    return 0


async def run_evaluation(language: str, settings: Settings) -> int:
    """Evaluate the language's reference queries and return the exit code"""
    queries = TypeAdapter(list[ReferenceQuery]).validate_json(
        (GOLDENS_DIR / f"{language}.json").read_bytes()
    )
    files_by_hash = hash_reference_files()
    documents = await documents_repository.find_documents_by_content(
        list(files_by_hash), DocumentStatus.INDEXED
    )
    filenames = {
        document.id: files_by_hash[content_sha256]
        for content_sha256, document in documents.items()
    }
    # A missing ingest must not show up as a search miss.
    missing = sorted(
        {expected.file for query in queries for expected in query.expected}
        - set(filenames.values())
    )
    if missing:
        print(
            f"no indexed document for: {', '.join(missing)}; "
            "run make ingest first",
            file=sys.stderr,
        )
        return 1
    # One query at a time: the model computes one call at a time anyway, and
    # the outcomes keep the order of the reference file.
    outcomes = [await evaluate_query(query, filenames) for query in queries]
    report = build_report(
        language, outcomes, settings, list(documents.values())
    )
    REPORTS_DIR.mkdir(exist_ok=True)
    report_path = REPORTS_DIR / f"search_{language}.md"
    report_path.write_text(report)
    print(report)
    print(f"written to {report_path.relative_to(EVALS_DIR.parent)}")
    return 0


async def run_command() -> int:
    """Run the chosen command against the database and return its exit code"""
    arguments = parse_arguments()
    settings = bootstrap()
    embedder.load_model()
    await db.open_pool(settings)
    try:
        if arguments.command == QUERY_COMMAND:
            return await run_query(arguments)
        return await run_evaluation(arguments.lang, settings)
    finally:
        await db.close_pool()


if __name__ == "__main__":
    sys.exit(asyncio.run(run_command()))
