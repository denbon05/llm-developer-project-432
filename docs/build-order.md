# Build order

How this service was built, in order, and what each stage teaches for similar
business systems: documents in, a model-written draft out, a human deciding.
The specs in [`docs/specs/`](specs/README.md) describe the system as it is.

## The order

1. **Skeleton and design documents:** an app with typed settings and
   structured logs, plus specs, decision records and a glossary. Names and
   decisions are cheapest to fix before code depends on them.
2. **Platform:** Postgres with pgvector, Temporal, migrations, a connection
   pool, health probes, disposable test databases, CI. Every later stage
   needs storage, background execution and tests.
3. **Generation pipeline:** an LLM client with its own retries, three model
   roles, jobs, a durable workflow and a human decision. The core value path
   comes first, on the simplest input: plain text.
4. **Structured output:** a contract for card drafts checked in code,
   tolerant JSON reading, repairs, confidence routing. Once the path runs end
   to end, its weakest point is the model's reply format.
5. **Document ingestion:** upload, parsing of PDF, DOCX and XLSX,
   normalisation, chunking. Real inputs are files, and search needs chunks
   that know their page and section.
6. **Embeddings and search:** local embeddings, vector, keyword and hybrid
   search, a calibrated threshold, a search evaluation. Retrieval bounds the
   quality of everything generated from it, so it is measured on its own.
7. **Grounded generation:** context from the chosen documents, labelled
   sources, citations verified in code. It joins search and the pipeline.
8. **Cost, tracing and evaluation:** a call ledger, a cheap model for the
   checking roles, ids that tie log lines together, a reference set and a
   judge. With the whole flow working, changes need numbers before and after.
9. **Guardrails:** masking, an injection check, a leak check. They wrap a
   finished flow at its boundaries, and the evaluation shows what they cost
   in quality.
10. **Delivery:** a clean-slate run, the README, committed reports, error
    messages safe for clients, specs rewritten by area.

## The stages

### 1. Skeleton and design documents

An AI-assisted project drifts quickly: each change renames something or
moves a responsibility. Write the problem, the promises and the principles
first. Keep a glossary that also lists the words to avoid, decision records
for choices that had real alternatives, and short layering rules (SQL only in
repositories, one module talks to the model, services know no framework).
Watch out: keep one source of truth per fact. Code holds values, specs hold
behaviour, decision records hold the why.

### 2. Platform

Every later stage relies on storage, background work and tests.
Plain SQL migrations and a driver, no ORM, because the queries that matter
(vector search, text ranking) are database-specific. One connection per
operation from a lazy pool; separate liveness from readiness; run tests
against throwaway containers, never a developer's database.
Watch out: retries stacked at several levels multiply. Fail at startup when a
hard dependency is missing, not on the first request.

### 3. Generation pipeline

Generation takes minutes, and a draft may wait days for a human, so it can't
live in a request handler. One LLM client owns timeouts, retries and error
mapping; nothing else sees the provider's SDK. Roles split the work: an
extractor runs once, then a generator and a critic take turns within a fixed
number of rounds. The database holds the status of record; a durable
workflow runs each stage as a retryable activity and waits for an approval
signal at no cost. Idempotency keys and guarded status transitions make
repeats safe.
Watch out: the client retries a call and the workflow retries a stage; never
let the second repeat what the first gave up on. Workflow code must stay
deterministic: no I/O, no settings, no clock.

### 4. Structured output

Models return almost-JSON, titles that are too long, empty values and
invented data. Check every reply against a schema in code. Read JSON
tolerantly (fences, text around it). On errors, send them back: ask only for
the broken fields when you can, the whole object otherwise, within a small
budget. Compute confidence in code from what is present and what is missing,
and send a draft with low confidence to a human.
Watch out: a length limit in the schema sent to the model makes constrained
decoding cut text mid-word and hides the error. A missing value is listed,
never filled.

### 5. Document ingestion

Supplier files mix paragraphs, tables, page headers and layout, each format
differently. Parse each into blocks with a page and a section; normalise
ligatures, whitespace, running headers and hyphenation; cut text into
overlapping chunks and keep each table row whole, naming its columns. Store
the file by its content hash, so the same upload is the same document, and
check size, format and archive size before parsing.
Watch out: heuristics tuned on a few files break on others, so keep a bulk
set to try them on. A file that yields no text must fail loudly, not end
indexed and empty.

### 6. Embeddings and search

A question in other words needs search by meaning; an exact product code
needs search by words. Each fails where the other works, so merge both by
rank (reciprocal rank fusion), not by their raw values. Store each vector
with the model and prefix that made it, so a model change can find stale
ones. Calibrate a similarity threshold on reference queries in each
language.
Watch out: embedding models expect their prefixes; a vector index with
filters needs an iterative scan or filtered searches come back empty; a
threshold belongs to one model and one document set.

### 7. Grounded generation

The promise is that every value points to its source. The application, not
the model, retrieves: documents that name the product enter whole, other
models' rows and exact duplicates are dropped, and the context is capped by
count and by tokens. Sources get short labels in tags, the job stores only
chunk ids, code verifies every citation before the critic, and the critic
checks values against their sources.
Watch out: a threshold that suits global search hurts here, where the user
already chose the documents. Keep source text out of workflow history and
pass ids instead.

### 8. Cost, tracing and evaluation

Without numbers, each prompt change is judged by eye, and cost appears only
on the invoice. Record every model reply in a ledger with its purpose, model,
tokens and exact cost; run the checking roles on a cheaper model; tie log
lines together with a request id and a job id. Write the reference set from
the documents before any run, compute metrics in code, let a judge model
check claims that code has numbered, and commit the reports.
Watch out: a failed ledger write must never fail the call, which is already
paid for. Output varies between runs, so compare totals. A broken run writes
no report.

### 9. Guardrails

Supplier files carry real contacts and can carry instructions aimed at the
model. Mask personal data before every model call, with stable placeholders
and checksums so SKUs and prices stay intact; mask on read and keep stored
text as it is. Let cheap patterns flag chunks and a cheap model decide, and
fail closed. Escape tags inside sources. Check the finished draft for leaks,
and send anything a guard touched to a human with a report.
Watch out: patterns alone flag too much, and a model call on every chunk
costs too much; combine them. Keep found values and detector reasons out of
logs.

### 10. Delivery

Someone else has to install, run, trust and change the system. Make a
clean-slate run work from the README, commit evaluation reports as the
baseline, show clients our own error messages and "internal error" for
anything else, and close gaps the model keeps leaving with code (standard
missing fields). Rewrite the stage-by-stage specs by area, for whoever
changes the code next.
Watch out: documents written while building carry history; the reader needs
the system as it is now.
