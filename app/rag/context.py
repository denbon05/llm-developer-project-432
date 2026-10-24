from pathlib import PurePath
from typing import NamedTuple
from uuid import UUID

from tokenizers import Tokenizer

from app.schemas.cards import normalize_name
from app.schemas.documents import SearchResult, StoredChunk

# Without a count limit, short table rows of other models could fill the
# token budget.
MAX_SOURCES = 12
# Leaves room in an 8k-token window for the instructions, a previous draft
# and a reply of up to 4,096 tokens.
CONTEXT_BUDGET_TOKENS = 3000
# One fixed tokenizer whatever model serves the call: the critic may run on
# another model than the generator, and both read the same sources
# (docs/adr/0006-context-budget-tokenizer.md).
TOKENIZER_REPOSITORY = "google/gemma-4-E4B-it"

ContextChunk = SearchResult | StoredChunk

_tokenizer: Tokenizer | None = None


class TokenizerNotLoadedError(RuntimeError):
    """Raised when tokens are counted before the tokenizer is loaded"""


class AssembledContext(NamedTuple):
    """A context's chunk ids in label order, and what assembly left out"""

    chunk_ids: list[UUID]
    tokens: int
    other_sku_rows_dropped: int
    duplicates_dropped: int
    cut_by_limit: int


def load_tokenizer() -> None:
    """Load the tokenizer, downloading it on first use"""
    global _tokenizer
    # The first load downloads tokenizer.json into the Hugging Face cache;
    # later loads read it from disk.
    _tokenizer = Tokenizer.from_pretrained(TOKENIZER_REPOSITORY)


def count_tokens(text: str) -> int:
    """Return how many tokens the text takes"""
    if _tokenizer is None:
        raise TokenizerNotLoadedError("the tokenizer is not loaded")
    # Counts the text alone, without the start and end markers a tokenizer
    # adds around a whole prompt.
    return len(_tokenizer.encode(text, add_special_tokens=False).ids)


def choose_title(section: str | None, filename: str) -> str:
    """Return a document's title from its first chunk's section or its file"""
    # A document usually opens with its title as its first section.
    return section or PurePath(filename).stem


def find_naming_documents(candidates: list[SearchResult]) -> list[UUID]:
    """Return the documents that name the product, by their best candidate"""
    # Found by keyword search: the hint's words are in the text. dict.fromkeys
    # drops repeats and keeps the best-first order.
    return list(
        dict.fromkeys(
            candidate.document_id
            for candidate in candidates
            if candidate.keyword_rank is not None
        )
    )


def order_chunks(
    candidates: list[SearchResult], document_chunks: list[StoredChunk]
) -> list[ContextChunk]:
    """Return the chunks of documents naming the product, then the others"""
    # A document that names the product enters whole: sections such as
    # "Warranty" don't mention the product and would lose on rank alone.
    naming_document_ids = find_naming_documents(candidates)
    ordered: list[ContextChunk] = []
    for document_id in naming_document_ids:
        own_candidates = [
            candidate
            for candidate in candidates
            if candidate.document_id == document_id
        ]
        candidate_ids = {candidate.chunk_id for candidate in own_candidates}
        ordered += own_candidates
        ordered += [
            chunk
            for chunk in document_chunks
            if chunk.document_id == document_id
            and chunk.chunk_id not in candidate_ids
        ]
    ordered += [
        candidate
        for candidate in candidates
        if candidate.document_id not in naming_document_ids
    ]
    return ordered


def read_sku(chunk: ContextChunk) -> str | None:
    """Return a table row's SKU in compared form, or None for text"""
    # Only table rows carry a SKU.
    sku = chunk.metadata.get("sku")
    return None if sku is None else normalize_name(sku)


def drop_other_sku_rows(
    chunks: list[ContextChunk], hint: str | None
) -> list[ContextChunk]:
    """Return the chunks without the table rows of SKUs other than the hint"""
    # Other models' rows are the likeliest source of wrong values. Applies
    # only when the hint is a row's SKU.
    if hint is None:
        return chunks
    sku = normalize_name(hint)
    if sku not in {read_sku(chunk) for chunk in chunks}:
        return chunks
    return [chunk for chunk in chunks if read_sku(chunk) in (None, sku)]


def drop_duplicates(chunks: list[ContextChunk]) -> list[ContextChunk]:
    """Return the chunks without those whose text an earlier chunk has"""
    # The first copy comes from the document most about the product. Exact
    # text only: two models' rows are alike in meaning, not in values.
    seen_texts: set[str] = set()
    kept: list[ContextChunk] = []
    for chunk in chunks:
        if chunk.text not in seen_texts:
            seen_texts.add(chunk.text)
            kept.append(chunk)
    return kept


def take_within_limits(
    chunks: list[ContextChunk],
) -> tuple[list[ContextChunk], int]:
    """Return the chunks taken within both limits, and their token count"""
    # A chunk over the remaining budget is skipped, never cut: half a row or
    # section can mislead.
    taken: list[ContextChunk] = []
    tokens = 0
    for chunk in chunks:
        if len(taken) == MAX_SOURCES:
            break
        chunk_tokens = count_tokens(chunk.text)
        if tokens + chunk_tokens <= CONTEXT_BUDGET_TOKENS:
            taken.append(chunk)
            tokens += chunk_tokens
    return taken, tokens


def assemble_context(
    candidates: list[SearchResult],
    document_chunks: list[StoredChunk],
    hint: str | None,
) -> AssembledContext:
    """Return the context of the search candidates, within its limits"""
    # document_chunks: every chunk of the documents that name the product.
    # The first chunk id returned becomes S1.
    ordered = order_chunks(candidates, document_chunks)
    without_other_skus = drop_other_sku_rows(ordered, hint)
    unique = drop_duplicates(without_other_skus)
    taken, tokens = take_within_limits(unique)
    return AssembledContext(
        chunk_ids=[chunk.chunk_id for chunk in taken],
        tokens=tokens,
        other_sku_rows_dropped=len(ordered) - len(without_other_skus),
        duplicates_dropped=len(without_other_skus) - len(unique),
        cut_by_limit=len(unique) - len(taken),
    )
