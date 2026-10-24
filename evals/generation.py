"""Measure card drafts against the reference set and write the report"""

import argparse
import asyncio
import logging
import re
import statistics
import sys
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, NamedTuple
from uuid import UUID

import httpx
from evals.costs import build_ledger_table, format_cost
from evals.dataset_files import DATASETS_DIR
from evals.expected_chunks import ExpectedChunk, is_expected_chunk
from evals.ingest import (
    DEFAULT_API_URL,
    REQUEST_TIMEOUT_S,
    upload_documents,
    wait_for_documents,
)
from evals.judge import Claim, ClaimVerdict, judge_claims, split_into_claims
from evals.tables import format_table
from pydantic import BaseModel

from app.core import db
from app.core.bootstrap import bootstrap
from app.core.config import Settings, get_settings
from app.llm.client import LlmUnavailableError
from app.llm.cost import PRICES
from app.main import API_PREFIX
from app.repositories import chunks as chunks_repository
from app.repositories import llm_calls as llm_calls_repository
from app.repositories.llm_calls import ModelCalls
from app.routers.generate import GENERATE_PATH
from app.routers.health import LIVENESS_PATH
from app.routers.jobs import JOB_PATH, REJECT_PATH
from app.schemas.cards import CitedValue, GroundedCardDraft
from app.schemas.documents import ChunkMetadata, DocumentStatus
from app.schemas.jobs import DECISION_STATUSES, JobStatus, JobView
from app.services.structured import InvalidModelOutputError
from app.temporal import client as temporal_client

EVALS_DIR = Path(__file__).resolve().parent
REFERENCE_SET_PATH = EVALS_DIR / "goldens" / "cards.json"
REPORTS_DIR = EVALS_DIR / "reports"
SUBSET = "subset"
FULL = "full"
GENERATE_URL = f"{API_PREFIX}{GENERATE_PATH}"
JOB_URL = f"{API_PREFIX}{JOB_PATH}"
REJECT_URL = f"{API_PREFIX}{REJECT_PATH}"
REJECT_REASON = "evaluation run"
# The statuses a job's draft is measured in
RESULT_STATUSES = DECISION_STATUSES | {JobStatus.FAILED}
POLL_INTERVAL_S = 2.0
# A running worker picks a job up within seconds.
PENDING_LIMIT_S = 60
# A job's rounds take minutes on a local model; longer means it is stuck.
JOB_TIME_LIMIT_MIN = 30
SECONDS_PER_MINUTE = 60
RATIO_DIGITS = 2
ROUNDS_DIGITS = 1
NO_VALUE = "-"
CASE_COLUMNS = [
    "Case",
    "Status",
    "Rounds",
    "Confidence",
    "Matched",
    "Citations",
    "Supported",
    "Missing but present",
    "Truly missing",
    "Cost",
    "Time",
]
# Normalisation, for names and values alike
DECIMAL_COMMA = re.compile(r"(?<=\d),(?=\d)")
SPACE_BEFORE_UNIT = re.compile(r"(?<=\d) (?=[^\W\d_])")


class ReferenceCharacteristic(BaseModel):
    """A characteristic a card draft must hold, and where it is stated"""

    # Names in the documents' language
    names: list[str]
    # Acceptable values; with none, only the characteristic's presence counts
    values: list[str] = []
    where: list[ExpectedChunk]


class ReferenceMissingField(BaseModel):
    """A field the case's documents lack, under the names it may carry"""

    names: list[str]


class ReferenceCase(BaseModel):
    """Documents, an optional hint, and what their card draft must hold"""

    id: str
    documents: list[str]
    hint: str | None
    characteristics: list[ReferenceCharacteristic]
    missing_fields: list[ReferenceMissingField]


class ReferenceSet(BaseModel):
    """The reference cases and the ids of the subset"""

    subset: list[str]
    cases: list[ReferenceCase]


class SourcePlace(NamedTuple):
    """Where a source's chunk sits: its reference file and its metadata"""

    file: str
    metadata: ChunkMetadata


@dataclass
class DraftScore:
    """One card draft's metric counts, and the errors behind them"""

    expected_count: int
    truly_missing_count: int
    matched_count: int = 0
    wrong_value_count: int = 0
    correct_citation_count: int = 0
    missing_but_present_count: int = 0
    truly_missing_listed_count: int = 0
    # None when the draft was not judged
    claim_count: int | None = None
    supported_count: int | None = None
    errors: list[str] = field(default_factory=list)


@dataclass
class CaseOutcome:
    """How one reference case's job ended, and its score"""

    case_id: str
    status: JobStatus
    rounds: int
    confidence: float | None
    score: DraftScore
    time_s: float
    # The job's id, which the ledger's rows carry
    job_id: UUID
    # Read from the ledger after the last case; None when a call of the job
    # has an unknown cost
    cost_usd: Decimal | None = None


@dataclass
class RunTotals:
    """The counts of every draft added up"""

    draft_count: int = 0
    expected_count: int = 0
    matched_count: int = 0
    wrong_value_count: int = 0
    correct_citation_count: int = 0
    citing_draft_count: int = 0
    correct_citing_draft_count: int = 0
    claim_count: int = 0
    supported_count: int = 0
    judged_draft_count: int = 0
    missing_but_present_count: int = 0
    truly_missing_count: int = 0
    truly_missing_listed_count: int = 0


class RunStoppedError(Exception):
    """Raised when broken infrastructure stops the run"""


def parse_arguments() -> argparse.Namespace:
    """Return the command-line arguments"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--full", action="store_true", help="run every case, not the subset"
    )
    parser.add_argument(
        "--api-url",
        default=DEFAULT_API_URL,
        help=f"address of the running API (default: {DEFAULT_API_URL})",
    )
    return parser.parse_args()


def normalize(text: str) -> str:
    """Return a name or value in the form they compare in"""
    # «800 Вт», «800 вт», «800Вт.» and «800 Вт » compare equal.
    text = " ".join(text.casefold().replace("ё", "е").split())
    text = text.removesuffix(".").rstrip()
    text = DECIMAL_COMMA.sub(".", text)
    return SPACE_BEFORE_UNIT.sub("", text)


def find_named(
    draft: GroundedCardDraft, names: list[str]
) -> list[tuple[str, CitedValue]]:
    """Return the draft's characteristics that carry one of the names"""
    wanted = {normalize(name) for name in names}
    return [
        (name, cited)
        for name, cited in draft.characteristics.items()
        if normalize(name) in wanted
    ]


def has_expected_citation(
    labels: list[str],
    expected_chunks: list[ExpectedChunk],
    source_places: dict[str, SourcePlace],
) -> bool:
    """Return whether any of the labels points to an expected chunk"""
    return any(
        label in source_places
        and is_expected_chunk(
            source_places[label].file,
            source_places[label].metadata,
            expected_chunks,
        )
        for label in labels
    )


def describe_citation(label: str, source_places: dict[str, SourcePlace]) -> str:
    """Return the label with the place of its chunk"""
    place = source_places.get(label)
    if place is None:
        return f"{label} (not a source of the job)"
    metadata = place.metadata
    details = [
        place.file,
        f"p. {metadata['page']}",
        *(
            value
            for value in (metadata["section"], metadata.get("sku"))
            if value
        ),
    ]
    return f"{label} ({', '.join(details)})"


def score_characteristic(
    score: DraftScore,
    draft: GroundedCardDraft,
    expected: ReferenceCharacteristic,
    source_places: dict[str, SourcePlace],
) -> None:
    """Add to the score whether the draft holds the characteristic, with the
    expected value and citation
    """
    # The draft may use any of the reference's names, such as Power or Rated
    # power.
    found = find_named(draft, expected.names)
    if not found:
        score.errors.append(f"Absent: {expected.names[0]}")
        return
    first_name, first_cited = found[0]
    # A reference without values, such as package contents, counts by
    # presence; otherwise a found value must equal an expected one.
    acceptable = {normalize(value) for value in expected.values}
    if not acceptable or any(
        normalize(cited.value) in acceptable for _, cited in found
    ):
        score.matched_count += 1
    else:
        score.wrong_value_count += 1
        score.errors.append(
            f"Wrong value: {first_name} «{first_cited.value}», "
            f"expected «{expected.values[0]}»"
        )
    # A citation is correct when a cited chunk sits where the reference says
    # the value is. A source in another place catches a value taken from
    # another model.
    labels = [label for _, cited in found for label in cited.sources]
    if has_expected_citation(labels, expected.where, source_places):
        score.correct_citation_count += 1
    else:
        described = ", ".join(
            describe_citation(label, source_places) for label in labels
        )
        score.errors.append(f"Wrong citation: {first_name} → {described}")


def score_missing_fields(
    score: DraftScore, draft: GroundedCardDraft, reference_case: ReferenceCase
) -> None:
    """Add to the score the draft's missing fields, checked both ways against
    the reference case
    """
    # The reference's characteristics are in the documents, so listing one
    # as missing is an error.
    reference_names = {
        normalize(name)
        for expected in reference_case.characteristics
        for name in expected.names
    }
    for name in draft.missing_fields:
        if normalize(name) in reference_names:
            score.missing_but_present_count += 1
            score.errors.append(
                f"Listed as missing but in the documents: {name}"
            )
    # The fields the documents lack should be listed as missing.
    listed = {normalize(name) for name in draft.missing_fields}
    for missing in reference_case.missing_fields:
        if any(normalize(name) in listed for name in missing.names):
            score.truly_missing_listed_count += 1
        else:
            score.errors.append(f"Truly missing not listed: {missing.names[0]}")


def score_draft(
    draft: GroundedCardDraft,
    reference_case: ReferenceCase,
    source_places: dict[str, SourcePlace],
) -> DraftScore:
    """Return how the draft compares with its reference case: the counts and
    the errors behind them
    """
    score = DraftScore(
        expected_count=len(reference_case.characteristics),
        truly_missing_count=len(reference_case.missing_fields),
    )
    for expected in reference_case.characteristics:
        score_characteristic(score, draft, expected, source_places)
    score_missing_fields(score, draft, reference_case)
    return score


def score_claims(
    score: DraftScore, claims: list[Claim], verdicts: list[ClaimVerdict]
) -> None:
    """Add the judge's verdicts on the claims to the draft's score"""
    score.claim_count = len(claims)
    score.supported_count = sum(verdict.supported for verdict in verdicts)
    score.errors += [
        f"Unsupported: {claim.kind} «{claim.text}» ({verdict.reason})"
        for claim, verdict in zip(claims, verdicts, strict=True)
        if not verdict.supported
    ]


def add_up(scores: list[DraftScore]) -> RunTotals:
    """Return the sum of the drafts' counts"""
    # Sums, not means of ratios: each characteristic weighs the same.
    totals = RunTotals(draft_count=len(scores))
    for score in scores:
        found = score.matched_count + score.wrong_value_count
        totals.expected_count += score.expected_count
        totals.matched_count += score.matched_count
        totals.wrong_value_count += score.wrong_value_count
        totals.correct_citation_count += score.correct_citation_count
        # A draft with nothing found has no citations to check.
        if found:
            totals.citing_draft_count += 1
            if score.correct_citation_count == found:
                totals.correct_citing_draft_count += 1
        totals.missing_but_present_count += score.missing_but_present_count
        totals.truly_missing_count += score.truly_missing_count
        totals.truly_missing_listed_count += score.truly_missing_listed_count
        if score.claim_count is not None and score.supported_count is not None:
            totals.judged_draft_count += 1
            totals.claim_count += score.claim_count
            totals.supported_count += score.supported_count
    return totals


def format_fraction(part: int, whole: int) -> str:
    """Return part/whole, or a dash when there is no whole"""
    return f"{part}/{whole}" if whole else NO_VALUE


def format_ratio(part: int, whole: int) -> str:
    """Return part/whole with its ratio, or a dash when there is no whole"""
    if not whole:
        return NO_VALUE
    return f"{part}/{whole} ({part / whole:.{RATIO_DIGITS}f})"


def format_duration(seconds: float) -> str:
    """Return the duration in minutes and seconds"""
    minutes, rest = divmod(round(seconds), SECONDS_PER_MINUTE)
    return f"{minutes}m {rest}s"


def format_averages(outcomes: list[CaseOutcome]) -> str:
    """Return the mean cost, time and rounds per card"""
    costs = [outcome.cost_usd for outcome in outcomes]
    known_costs = [cost for cost in costs if cost is not None]
    # Unknown if any card's cost is unknown
    average_cost = (
        sum(known_costs, Decimal(0)) / len(known_costs)
        if len(known_costs) == len(costs)
        else None
    )
    average_time_s = statistics.mean(outcome.time_s for outcome in outcomes)
    average_rounds = statistics.mean(outcome.rounds for outcome in outcomes)
    return (
        f"{format_cost(average_cost)} · {format_duration(average_time_s)} · "
        f"{average_rounds:.{ROUNDS_DIGITS}f} rounds"
    )


def build_summary_table(
    totals: RunTotals, outcomes: list[CaseOutcome]
) -> list[str]:
    """Return the table of totals"""
    found = totals.matched_count + totals.wrong_value_count
    rows = [
        (
            "Characteristics matched",
            format_ratio(totals.matched_count, totals.expected_count),
        ),
        ("Wrong values", str(totals.wrong_value_count)),
        (
            "Correct citations",
            format_ratio(totals.correct_citation_count, found),
        ),
        (
            "Cards with all citations correct",
            format_fraction(
                totals.correct_citing_draft_count, totals.citing_draft_count
            ),
        ),
        (
            "Claims supported (judge)",
            format_ratio(totals.supported_count, totals.claim_count),
        ),
        (
            "Cards judged",
            format_fraction(totals.judged_draft_count, totals.draft_count),
        ),
        (
            "Listed as missing but in the documents",
            str(totals.missing_but_present_count),
        ),
        (
            "Truly missing listed",
            format_fraction(
                totals.truly_missing_listed_count, totals.truly_missing_count
            ),
        ),
        ("Per card, average", format_averages(outcomes)),
    ]
    return format_table(["Metric", "Value"], rows)


def build_cases_table(outcomes: list[CaseOutcome]) -> list[str]:
    """Return the table with one row per case"""
    rows: list[list[str]] = []
    for outcome in outcomes:
        score = outcome.score
        found = score.matched_count + score.wrong_value_count
        supported = (
            NO_VALUE
            if score.claim_count is None or score.supported_count is None
            else format_fraction(score.supported_count, score.claim_count)
        )
        row = [
            outcome.case_id,
            outcome.status,
            str(outcome.rounds),
            NO_VALUE if outcome.confidence is None else str(outcome.confidence),
            format_fraction(score.matched_count, score.expected_count),
            format_fraction(score.correct_citation_count, found),
            supported,
            str(score.missing_but_present_count),
            format_fraction(
                score.truly_missing_listed_count, score.truly_missing_count
            ),
            format_cost(outcome.cost_usd),
            format_duration(outcome.time_s),
        ]
        rows.append(row)
    return format_table(CASE_COLUMNS, rows)


def build_errors(outcomes: list[CaseOutcome]) -> list[str]:
    """Return the section listing each case's problems"""
    lines = ["## Errors"]
    for outcome in outcomes:
        if outcome.score.errors:
            lines += ["", f"### {outcome.case_id}", ""]
            lines += [f"- {error}" for error in outcome.score.errors]
    if len(lines) == 1:
        lines += ["", "None."]
    return lines


def build_report(
    scope: str,
    case_count: int,
    outcomes: list[CaseOutcome],
    model_calls: list[ModelCalls],
    settings: Settings,
) -> str:
    """Return the evaluation report as Markdown"""
    models = dict.fromkeys(
        [settings.llm_model, settings.llm_cheap_model, settings.llm_judge_model]
    )
    prices = ", ".join(
        f"{model} {price.input} / {price.output}"
        for model in models
        if (price := PRICES.get(model))
    )
    command = "make eval-generation" + (" full=1" if scope == FULL else "")
    totals = add_up([outcome.score for outcome in outcomes])
    lines = [
        f"# Generation evaluation: {scope}",
        "",
        (
            f"- Date: {datetime.now(UTC).date()} · "
            f"Cases: {len(outcomes)} of {case_count}"
        ),
        (
            f"- Main model: {settings.llm_model} · "
            f"Cheap model: {settings.llm_cheap_model} · "
            f"Judge model: {settings.llm_judge_model}"
        ),
        f"- Prices, USD per 1M tokens (input / output): {prices or 'none set'}",
        "",
        (
            f"Written by `{command}`. One run per case: a case can change by "
            "several values between runs with no change in code, so compare "
            "the totals, not single cases."
        ),
        "",
        "## Summary",
        "",
        *build_summary_table(totals, outcomes),
        "",
        "## Cases",
        "",
        *build_cases_table(outcomes),
        "",
        *build_errors(outcomes),
        "",
        "## Cost by model",
        "",
        *build_ledger_table(model_calls),
    ]
    return "\n".join(lines) + "\n"


def call_api(
    client: httpx.Client, method: str, url: str, body: Any = None
) -> Any:
    """Return the API's JSON answer, or stop the run if the request fails"""
    try:
        response = client.request(method, url, json=body)
        response.raise_for_status()
    except httpx.HTTPError as error:
        raise RunStoppedError(f"{method} {url} failed: {error}") from error
    return response.json()


def check_api(client: httpx.Client) -> None:
    """Stop the run unless the API answers"""
    try:
        client.get(LIVENESS_PATH).raise_for_status()
    except httpx.HTTPError as error:
        raise RunStoppedError(
            f"the API at {client.base_url} is unreachable ({error})"
        ) from error


async def check_workers() -> None:
    """Stop the run unless workers poll both task queues"""
    settings = get_settings()
    for task_queue in (
        settings.temporal_task_queue,
        settings.temporal_document_task_queue,
    ):
        try:
            is_polled = await temporal_client.has_workers(task_queue)
        except temporal_client.TemporalUnavailableError as error:
            raise RunStoppedError("Temporal is unreachable") from error
        # Checked before any job exists: a job started without a worker
        # would run later, when nothing waits to measure or reject it.
        if not is_polled:
            raise RunStoppedError(
                f"no worker polls the {task_queue} task queue"
            )


def index_documents(
    client: httpx.Client, cases: list[ReferenceCase]
) -> dict[str, UUID]:
    """Upload the cases' documents, wait until each is indexed, and return
    their ids by file name
    """
    paths = [
        DATASETS_DIR / name
        for name in sorted({name for case in cases for name in case.documents})
    ]
    document_ids, failures = upload_documents(client, paths)
    documents, status_failures = wait_for_documents(client, document_ids)
    failures |= status_failures
    if failures:
        raise RunStoppedError(
            "; ".join(
                f"{path.name}: {error}" for path, error in failures.items()
            )
        )
    not_indexed = [
        f"{path.name} ({documents[path].status})"
        for path in paths
        if documents[path].status != DocumentStatus.INDEXED
    ]
    if not_indexed:
        raise RunStoppedError(
            f"documents not indexed: {', '.join(not_indexed)}"
        )
    return {path.name: documents[path].id for path in paths}


async def wait_for_job(client: httpx.Client, job_id: UUID) -> dict[str, Any]:
    """Return the job once it waits for a decision or has failed"""
    started_at = time.monotonic()
    while True:
        job = call_api(client, "GET", JOB_URL.format(job_id=job_id))
        if job["status"] in RESULT_STATUSES:
            return job
        waited_s = time.monotonic() - started_at
        if job["status"] == JobStatus.PENDING and waited_s > PENDING_LIMIT_S:
            raise RunStoppedError(
                f"job {job_id} stayed pending: no worker picked it up"
            )
        if waited_s > JOB_TIME_LIMIT_MIN * SECONDS_PER_MINUTE:
            raise RunStoppedError(
                f"job {job_id} ran longer than {JOB_TIME_LIMIT_MIN} minutes"
            )
        await asyncio.sleep(POLL_INTERVAL_S)


async def read_source_places(
    job: JobView, filenames: dict[UUID, str]
) -> dict[str, SourcePlace]:
    """Return where each of the job's sources sits, by label"""
    chunks = await chunks_repository.find_document_chunks(
        list({source.document_id for source in job.sources})
    )
    metadata = {chunk.chunk_id: chunk.metadata for chunk in chunks}
    return {
        source.label: SourcePlace(
            filenames[source.document_id], metadata[source.chunk_id]
        )
        for source in job.sources
    }


async def score_job(
    case: ReferenceCase,
    job: JobView,
    draft: GroundedCardDraft | None,
    filenames: dict[UUID, str],
) -> DraftScore:
    """Return the score of the job's draft, judge included"""
    if draft is None:
        # A failed job's characteristics count as absent and its missing
        # fields as not listed; it has no citations and no claims.
        return DraftScore(
            expected_count=len(case.characteristics),
            truly_missing_count=len(case.missing_fields),
            errors=[f"Job failed: {job.error}"],
        )
    source_places = await read_source_places(job, filenames)
    score = score_draft(draft, case, source_places)
    claims = split_into_claims(draft)
    try:
        verdicts = await judge_claims(job.sources, claims)
    except LlmUnavailableError as error:
        raise RunStoppedError(
            "the judge's model server is unreachable"
        ) from error
    except InvalidModelOutputError:
        score.errors.append("Not judged: the judge's reply stayed invalid")
        return score
    score_claims(score, claims, verdicts)
    return score


async def evaluate_case(
    client: httpx.Client,
    case: ReferenceCase,
    document_ids: dict[str, UUID],
    filenames: dict[UUID, str],
) -> CaseOutcome:
    """Generate the case's card draft and measure it"""
    created = call_api(
        client,
        "POST",
        GENERATE_URL,
        {
            "document_ids": [
                str(document_ids[name]) for name in case.documents
            ],
            "hint": case.hint,
        },
    )
    raw_job = await wait_for_job(client, UUID(created["id"]))
    job = JobView.model_validate(raw_job)
    # Relies on the "<error type>: <message>" form the workflow stores; if
    # that form changes, an outage would be scored as a failed draft.
    if job.error and job.error.startswith(LlmUnavailableError.__name__):
        raise RunStoppedError(
            f"the model server is unreachable: job {job.id} failed "
            f"({job.error})"
        )
    # Read as a grounded draft: the view's union can't tell one without
    # characteristics from a supplier-text draft.
    draft = (
        None
        if job.status == JobStatus.FAILED
        else GroundedCardDraft.model_validate(raw_job["result"])
    )
    try:
        score = await score_job(case, job, draft, filenames)
    finally:
        # Otherwise the job's workflow waits for a decision forever.
        if job.status in DECISION_STATUSES:
            call_api(
                client,
                "POST",
                REJECT_URL.format(job_id=job.id),
                {"reason": REJECT_REASON},
            )
    return CaseOutcome(
        case_id=case.id,
        status=job.status,
        rounds=job.attempts,
        confidence=draft.confidence if draft else None,
        score=score,
        time_s=(job.updated_at - job.created_at).total_seconds(),
        job_id=job.id,
    )


async def evaluate_cases(
    client: httpx.Client, cases: list[ReferenceCase]
) -> list[CaseOutcome]:
    """Run each case through the API, one after another, and measure it"""
    check_api(client)
    await check_workers()
    document_ids = index_documents(client, cases)
    filenames = {
        document_id: name for name, document_id in document_ids.items()
    }
    outcomes: list[CaseOutcome] = []
    # One at a time: a local model serves one request at a time, and the
    # time per card stays honest.
    for case in cases:
        outcome = await evaluate_case(client, case, document_ids, filenames)
        print(f"{case.id}: {outcome.status}")
        outcomes.append(outcome)
    costs = await llm_calls_repository.find_job_costs(
        [outcome.job_id for outcome in outcomes]
    )
    for outcome in outcomes:
        # A job without ledger rows made no calls.
        outcome.cost_usd = costs.get(outcome.job_id, Decimal(0))
    return outcomes


async def run_evaluation() -> int:
    """Evaluate the chosen cases, write the report and return the exit code"""
    # Importing the app sets logging to INFO, where httpx logs every request.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    arguments = parse_arguments()
    scope = FULL if arguments.full else SUBSET
    reference_set = ReferenceSet.model_validate_json(
        REFERENCE_SET_PATH.read_bytes()
    )
    cases = [
        case
        for case in reference_set.cases
        if arguments.full or case.id in reference_set.subset
    ]
    settings = bootstrap()
    await db.open_pool(settings)
    try:
        with httpx.Client(
            base_url=arguments.api_url, timeout=REQUEST_TIMEOUT_S
        ) as client:
            outcomes = await evaluate_cases(client, cases)
        model_calls = await llm_calls_repository.count_calls_by_model(
            [outcome.job_id for outcome in outcomes]
        )
    # A broken run writes no report, so it never overwrites a committed one.
    except RunStoppedError as error:
        print(f"run stopped: {error}", file=sys.stderr)
        return 1
    finally:
        await db.close_pool()
    report = build_report(
        scope, len(reference_set.cases), outcomes, model_calls, settings
    )
    REPORTS_DIR.mkdir(exist_ok=True)
    report_path = REPORTS_DIR / f"generation_{scope}.md"
    report_path.write_text(report)
    totals = add_up([outcome.score for outcome in outcomes])
    print()
    print("\n".join(build_summary_table(totals, outcomes)))
    print()
    print("\n".join(build_cases_table(outcomes)))
    print(f"\nwritten to {report_path.relative_to(EVALS_DIR.parent)}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(run_evaluation()))
