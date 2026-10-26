from collections import Counter
from typing import NamedTuple
from uuid import UUID

from app.agents.prompts import (
    CITATION_CHUNK_MISSING_ISSUE,
    CITATION_NOT_IN_CONTEXT_ISSUE,
    build_grounded_critic_messages,
    build_grounded_generator_messages,
)
from app.core.config import get_settings
from app.core.errors import ConflictError, NotFoundError, ServiceError
from app.core.logging import get_logger
from app.guardrails.injection import detect_injection, find_injection_patterns
from app.guardrails.pii import mask_texts
from app.rag import retrieval
from app.rag.context import (
    ContextChunk,
    assemble_context,
    choose_title,
    filter_chunks,
    find_naming_documents,
)
from app.repositories import chunks as chunks_repository
from app.repositories import documents as documents_repository
from app.repositories import jobs as jobs_repository
from app.schemas.cards import (
    SOURCE_LABEL_PREFIX,
    Critique,
    ExcludedDocument,
    FlaggedChunk,
    GroundedCardDraft,
    InjectionVerdict,
)
from app.schemas.documents import (
    DocumentStatus,
    DocumentView,
    SearchMode,
    SearchRequest,
)
from app.schemas.jobs import Source
from app.services import jobs as jobs_service
from app.services.pipeline import build_critique_params, build_generate_params
from app.services.structured import complete_structured

# Hybrid search candidates the context is assembled from
CANDIDATE_COUNT = 20
# -1 turns the similarity threshold off: the user chose the documents, and a
# section like "Package contents" looks nothing like the hint.
NO_SIMILARITY_THRESHOLD = -1.0
LIST_SEPARATOR = ", "
NOT_IN_CONTEXT = "not_in_context"
CHUNK_MISSING = "chunk_missing"

logger = get_logger(__name__)


class DocumentsNotFoundError(NotFoundError):
    """Raised when some of the requested documents don't exist"""

    def __init__(self, document_ids: list[UUID]) -> None:
        listed = LIST_SEPARATOR.join(
            str(document_id) for document_id in document_ids
        )
        super().__init__(f"documents not found: {listed}")


class DocumentsNotIndexedError(ConflictError):
    """Raised when some of the requested documents aren't indexed"""

    def __init__(self, documents: list[DocumentView]) -> None:
        listed = LIST_SEPARATOR.join(
            f"{document.id} ({document.status})" for document in documents
        )
        super().__init__(f"documents not indexed: {listed}")


# Maps to no HTTP status: it fails a job, never a request.
class EmptyContextError(ServiceError):
    """Raised when no chunk of the job's documents can enter its context"""

    message = (
        "no chunks to build the context from; "
        "run make reindex if the embedding model changed"
    )


# Maps to no HTTP status: it fails a job, never a request.
class ContextExcludedError(ServiceError):
    """Raised when the injection check excludes every chunk of a job"""

    def __init__(self, filenames: list[str]) -> None:
        super().__init__(
            "the injection check excluded every chunk of the documents "
            f"{LIST_SEPARATOR.join(filenames)}; see the job's guard report"
        )


class InjectionCheck(NamedTuple):
    """The chunks the injection check kept, and what it found"""

    chunks: list[ContextChunk]
    flagged_chunks: list[FlaggedChunk]
    excluded_documents: list[ExcludedDocument]


class RetrievedContext(NamedTuple):
    """A job's product line and the chunk ids of its sources, in label order"""

    product_line: str
    chunk_ids: list[UUID]
    has_excluded_chunks: bool


async def check_documents(document_ids: list[UUID]) -> None:
    """Raise unless every document exists and is indexed"""
    documents = await documents_repository.find_documents_by_id(document_ids)
    missing_ids = [
        document_id
        for document_id in document_ids
        if document_id not in documents
    ]
    if missing_ids:
        raise DocumentsNotFoundError(missing_ids)
    not_indexed = [
        documents[document_id]
        for document_id in document_ids
        if documents[document_id].status != DocumentStatus.INDEXED
    ]
    if not_indexed:
        raise DocumentsNotIndexedError(not_indexed)


async def read_title(document_id: UUID) -> str:
    """Return the document's title"""
    document = await documents_repository.get_document(document_id)
    # An indexed document always has a chunk.
    chunks = await chunks_repository.find_document_chunks([document_id])
    return choose_title(chunks[0].metadata["section"], document.filename)


async def check_injection(
    chunks: list[ContextChunk], filenames: dict[UUID, str]
) -> InjectionCheck:
    """Return the chunks the injection check keeps, in their order"""
    threshold = get_settings().injection_check_document_threshold
    excluded_counts: Counter[UUID] = Counter()
    kept_chunks: list[ContextChunk] = []
    flagged_chunks: list[FlaggedChunk] = []
    checked_chunk_count = 0

    for chunk in chunks:
        # One excluded chunk can be a detector mistake, several in one
        # document rarely are, so such a document is excluded whole. Its
        # other chunks can't change that, so they cost no detector call.
        if excluded_counts[chunk.document_id] >= threshold:
            continue
        checked_chunk_count += 1
        # Searched in what the detector receives: the masked text.
        [text] = mask_texts([chunk.text]).texts
        found_injection_patterns = find_injection_patterns(text)
        if not found_injection_patterns:
            kept_chunks.append(chunk)
            continue
        flagged_chunk = await detect_injection(
            chunk, text, found_injection_patterns, filenames[chunk.document_id]
        )
        flagged_chunks.append(flagged_chunk)
        if flagged_chunk.verdict == InjectionVerdict.CLEAN:
            kept_chunks.append(chunk)
        else:
            excluded_counts[chunk.document_id] += 1

    excluded_documents = [
        ExcludedDocument(
            document_id=document_id,
            filename=filenames[document_id],
            excluded_chunk_count=count,
        )
        for document_id, count in excluded_counts.items()
        if count >= threshold
    ]
    excluded_ids = {document.document_id for document in excluded_documents}
    kept_chunks = [
        chunk for chunk in kept_chunks if chunk.document_id not in excluded_ids
    ]
    # Patterns and verdicts, never the detector's reasons: a reason can restate
    # the injection, and names aren't masked.
    logger.info(
        "injection_check_completed",
        checked_chunk_count=checked_chunk_count,
        flagged_chunk_count=len(flagged_chunks),
        excluded_chunk_count=len(chunks) - len(kept_chunks),
        excluded_document_count=len(excluded_documents),
        flagged_chunks=[
            {
                "chunk_id": str(flagged_chunk.chunk_id),
                "patterns": flagged_chunk.patterns,
                "verdict": flagged_chunk.verdict,
            }
            for flagged_chunk in flagged_chunks
        ],
    )
    return InjectionCheck(kept_chunks, flagged_chunks, excluded_documents)


async def retrieve_context(
    job_id: UUID, document_ids: list[UUID], hint: str | None
) -> RetrievedContext:
    """Return the job's product line and sources, and whether the injection
    check excluded a chunk

    Stores the injection check's part of the job's guard report.
    """
    # Names the product for the generator and the critic; also the query.
    product_line = hint or await read_title(document_ids[0])
    candidates = await retrieval.search(
        SearchRequest(
            query=product_line,
            mode=SearchMode.HYBRID,
            top_k=CANDIDATE_COUNT,
            document_ids=document_ids,
            min_similarity=NO_SIMILARITY_THRESHOLD,
        )
    )
    document_chunks = await chunks_repository.find_document_chunks(
        find_naming_documents(candidates)
    )
    chunks, dropped = filter_chunks(candidates, document_chunks, hint)
    # Possible only when no chunk has a current vector and keyword search
    # finds nothing.
    if not chunks:
        raise EmptyContextError()
    documents = await documents_repository.find_documents_by_id(document_ids)
    filenames = {
        document_id: document.filename
        for document_id, document in documents.items()
    }
    # Before the limits: the patterns cost nothing, an excluded chunk frees its
    # place for the next one, and a document's count of excluded chunks sees
    # all its candidates, not only those that fit.
    check = await check_injection(chunks, filenames)
    # Stored before the check can fail the job, so the job says why.
    await jobs_repository.store_injection_check(
        job_id, check.flagged_chunks, check.excluded_documents
    )
    if not check.chunks:
        raise ContextExcludedError(
            list(
                dict.fromkeys(filenames[chunk.document_id] for chunk in chunks)
            )
        )
    context = assemble_context(check.chunks)
    # Ids and counts only: neither chunk text nor the query reaches the logs.
    logger.info(
        "context_assembled",
        job_id=str(job_id),
        documents=len(document_ids),
        candidates=len(candidates),
        sources=len(context.chunk_ids),
        tokens=context.tokens,
        dropped_mismatched_sku_chunk_count=dropped.mismatched_sku_chunk_count,
        dropped_duplicate_chunk_count=dropped.duplicate_chunk_count,
        excluded_chunk_count=len(chunks) - len(check.chunks),
        over_limit_chunk_count=context.over_limit_chunk_count,
        chunk_ids=[str(chunk_id) for chunk_id in context.chunk_ids],
    )
    return RetrievedContext(
        product_line=product_line,
        chunk_ids=context.chunk_ids,
        has_excluded_chunks=len(check.chunks) < len(chunks),
    )


async def read_sources(job_id: UUID) -> list[Source]:
    """Return the job's sources, masked, in label order"""
    # Read in a database operation of its own, so no connection is held
    # during the model call.
    return (await jobs_service.read_masked_job(job_id)).sources


async def generate(
    job_id: UUID,
    product_line: str,
    feedback: list[str] | None = None,
    previous_draft: GroundedCardDraft | None = None,
) -> GroundedCardDraft:
    """Return a card draft written from the job's sources and any issues"""
    sources = await read_sources(job_id)
    return await complete_structured(
        build_grounded_generator_messages(
            product_line, sources, feedback, previous_draft
        ),
        params=build_generate_params(),
        response_schema=GroundedCardDraft,
    )


async def verify_citations(job_id: UUID, draft: GroundedCardDraft) -> list[str]:
    """Return an issue for each citation of a source the job doesn't have"""
    # Citing a chunk the model never saw is invention. Whether a real source
    # supports the value is for the critic.
    context_chunk_ids = await jobs_repository.get_context_chunk_ids(job_id)
    existing_ids = await chunks_repository.find_existing_chunk_ids(
        context_chunk_ids
    )
    chunk_ids_by_label = {
        f"{SOURCE_LABEL_PREFIX}{position}": chunk_id
        for position, chunk_id in enumerate(context_chunk_ids, start=1)
    }
    issues: list[str] = []
    invalid_citations: list[dict[str, str]] = []
    for name, cited in draft.characteristics.items():
        for label in cited.sources:
            if label not in chunk_ids_by_label:
                reason, issue = NOT_IN_CONTEXT, CITATION_NOT_IN_CONTEXT_ISSUE
            # Only if a document is re-chunked after retrieval: nothing does
            # that today, but the check is cheap.
            elif chunk_ids_by_label[label] not in existing_ids:
                reason, issue = CHUNK_MISSING, CITATION_CHUNK_MISSING_ISSUE
            else:
                continue
            issues.append(issue.format(name=name, label=label))
            invalid_citations.append(
                {"characteristic": name, "label": label, "reason": reason}
            )
    if invalid_citations:
        logger.warning(
            "citations_invalid", job_id=str(job_id), citations=invalid_citations
        )
    return issues


async def critique(
    job_id: UUID, product_line: str, draft: GroundedCardDraft
) -> Critique:
    """Return the critic's verdict on the draft against the job's sources"""
    sources = await read_sources(job_id)
    reply = await complete_structured(
        build_grounded_critic_messages(product_line, sources, draft),
        params=build_critique_params(),
        response_schema=Critique,
    )
    # The job keeps only the last round's issues; the log keeps every round's.
    logger.info(
        "critique_completed", verdict=reply.verdict, issues=reply.issues
    )
    return reply
