# 07 · Grounded generation

**Status:** implemented

## Context

So far, a card draft is written from supplier text pasted into the request.
The product promise ([01](01-product-overview.md#goal)) says more: every
characteristic points to the chunk it came from, and anything the documents
lack is listed as missing. For that, a draft must be written from the stored
chunks of supplier documents, with references the application can check.

A content manager uploads a supplier's files once
([05](05-document-ingestion.md)). One file often covers several products
(`fan_spec_1.xlsx` has a row for each of FAN-35, FAN-40 and FAN-45), and one
product's facts are spread over several files (FAN-40's power is in the
spreadsheet, its package contents in the passport). To get a card, the
manager names the documents and, optionally, the product:

```text
POST /api/v1/generate {"document_ids": ["d1", "d2"], "hint": "FAN-40"}
```

The job finds the chunks of those documents that describe the product and
gives them to the model as labelled **sources**. The model writes a draft
whose every characteristic cites a source label. The manager then checks each
value against the quoted source instead of rereading the files.

Three defences keep invented data out of an approved card:

1. **Retrieval:** the model sees only sources from the chosen documents.
2. **Citation verification:** code checks that every cited label was in this
   job's context and that its chunk exists. If the model cites a chunk it was
   never shown, it has invented the reference, even though the reference
   looks plausible.
3. **The critic** checks each characteristic against the sources it cites,
   and the rest of the draft against the whole context. Code can't judge
   whether a real source supports a value.

A human decision ends the job, as in [03](03-generation-pipeline.md).

## Requirements

- **GND-1 — Generation request:** a client asks for a card draft from 1–10
  indexed documents and an optional hint naming the product. The answer is
  `202` with the job's id. Documents that are unknown or not indexed are
  refused.
- **GND-2 — Retrieval scope:** retrieval covers only the chosen documents,
  with hybrid search and no similarity threshold. Documents that name the
  product enter the context first, whole.
- **GND-3 — Context:** each source has a label unique within the job.
  Duplicate texts across documents appear once. The context holds at most
  12 sources and 3,000 tokens, counted with the configured model's tokenizer.
- **GND-4 — Citations:** every characteristic of the draft cites at least one
  source label.
- **GND-5 — Citation verification:** a cited label must be in the job's
  context, and its chunk must still exist. A violation sends the draft back
  for revision with an explanation. A second draft with a violation ends the
  job in `needs_review`.
- **GND-6 — Critic against sources:** the critic checks the draft against the
  sources and the target product. Every issue names the source or the draft
  field it concerns.
- **GND-7 — Status of record:** a document job passes `retrieving`,
  `generating` and `critiquing`, and each status is written to the database
  when its stage starts.
- **GND-8 — Readable result:** `GET /jobs/{id}` returns the draft together
  with the sources its labels refer to. Approval and rejection work as for
  any job.
- **GND-9 — Testability:** no test needs a model server, the embedding model
  or the tokenizer download. An end-to-end test runs the whole flow on seeded
  chunks.

## Non-goals

- **Changing the supplier-text paths.** `POST /cards` and `POST /jobs` keep
  the extractor and produce drafts without citations. The citation promise
  holds for document jobs only. The one change the text path gets is the
  issue format ([Prompts](#prompts)).
- **A synchronous preview from documents.** Retrieval needs the embedding
  model, and the API never loads it
  ([ADR 0005](../adr/0005-local-embeddings-in-process.md)).
- **Waiting for documents still being ingested.** Such a request is refused
  with `409`. A document's ingestion progress is visible on the document
  itself.
- **Citations for description, benefits and SEO text.** The critic checks
  these against the whole context.
- **Duplicates by meaning, and overlap between neighbouring chunks.** Rows of
  different models are as similar as 0.984 (FAN-40 and FAN-45), more than the
  English and Russian versions of one row (0.920), so treating similar
  meaning as a duplicate would merge different products. In our chunks,
  overlap appears only in sections over 1,200 characters.
- **A reranker, query rewriting, and retrieval as a tool the model calls.**
  Retrieval is a fixed step the application runs, because grounding is a
  product rule, not the model's choice.
- **Checking a value against its source in code.** Values are reworded and
  translated, so the critic judges whether a source supports a value. 08
  measures citation accuracy.
- **Masking personal data in prompts (09).** In this step, chunks with
  contact details still reach the local model.
- **Workflows started before this spec.** The workflow input changes, so
  development Temporal state is reset, as in
  [04](04-structured-output.md#non-goals).

## Design

The code states the reason for each non-obvious rule in a short, plain
comment. These are:

- the missing similarity threshold;
- documents that name the product coming first;
- the filter for rows of other SKUs;
- the first copy of a duplicate being kept;
- the limits and their arithmetic;
- labels instead of chunk ids;
- the `<source>` tags;
- the context being kept in the database instead of Temporal history;
- the citation check running before the critic;
- the second violation ending the loop;
- the tokenizer standing in for the model server's count;
- where personal-data masking will go (09).

### Component flow

```text
POST /generate ─▶ routers/generate.py
                    ├─▶ rag_pipeline: documents exist and are indexed ─▶ documents repository
                    ├─▶ jobs repository: create the job (pending, idempotent)
                    └─▶ temporal/client.py: start CardGenerationWorkflow

CardGenerationWorkflow, document job
  ├─▶ record retrieving
  ├─▶ build_context ────▶ rag_pipeline ─▶ rag/retrieval.py   hybrid search in the documents
  │                                     ├─▶ chunks repository  chunks of the documents naming the product
  │                                     ├─▶ rag/context.py     assemble the context, count tokens
  │                                     └─▶ jobs repository    store context_chunk_ids
  ├─▶ record generating ─▶ generate_grounded_draft ─▶ rag_pipeline ─▶ structured.py ─▶ LLM client
  ├─▶ record critiquing ─▶ verify_citations ─────────▶ rag_pipeline ─▶ chunks repository
  │                     └▶ critique_grounded_draft ──▶ rag_pipeline ─▶ structured.py ─▶ LLM client
  └─▶ record awaiting_approval | needs_review ─▶ wait for a decision (03)

GET /jobs/{id} ─▶ jobs repository: the job, and its sources joined from chunks and documents
```

- **`services/rag_pipeline.py`** holds the document job's steps:
  - checking the requested documents;
  - retrieval and assembly;
  - generation, verification and critique.

  Like `pipeline.py`, it imports neither FastAPI nor Temporal.
- **`rag/context.py`** assembles the context. It turns search results and
  document chunks into an ordered list of sources and counts their tokens.
  Its assembly function is pure, so tests run it without a database.
- **Prompts** for sources live in `agents/prompts.py`, like every other
  prompt.
- **Repositories** are the only place with SQL: `chunks.py` reads the chunks
  of documents and checks which chunks exist; `jobs.py` stores and reads a
  job's context.

### HTTP API

| Method and path | Router | Success | Errors |
|-----------------|--------|---------|--------|
| `POST /generate` | `generate.py` | `202 {"id", "status"}` | `404` · `409` · `422` · `503` |
| `GET /jobs/{id}` | `jobs.py` | `200` job, now with `sources` | `404` |

- **Body:**
  - `document_ids`: 1 to 10 ids, without repeats;
  - `hint`: optional, 1 to 200 characters, not blank.

  A repeated id, or a list that is empty or too long, answers `422`.
- **Why 10:** every chosen document shares one context. Our documents hold
  about 250 tokens each, so ten fit the 3,000-token budget. With more, the
  budget cuts most of them anyway.
- **Checks, in order:**
  1. the body (`422`);
  2. every document exists: `404 {"detail": "documents not found: <id>, …"}`;
  3. every document is `indexed`:
     `409 {"detail": "documents not indexed: <id> (parsing), …"}`;
  4. the job is created;
  5. its workflow is started while the job is `pending`, as `POST /jobs`
     does.
- **Idempotency:** the `Idempotency-Key` header works as in
  [03](03-generation-pipeline.md#http-api). The request hash covers
  `document_ids` and `hint`.
- **Job view:** `GET /jobs/{id}` gains `sources`, ordered by label. Each
  source has `label`, `chunk_id`, `document_id`, `filename`, `page`,
  `section` and `text`. A supplier-text job has no sources. For a document
  job, `result` is a grounded draft ([Grounded draft](#grounded-draft)).
- Decisions (`/approve`, `/reject`) and the workflow view are unchanged.

### Storage

One migration, `add_grounded_jobs`:

- the `jobs.status` check allows `retrieving`;
- `jobs.context_chunk_ids uuid[] NOT NULL DEFAULT '{}'`: the chunk ids of the
  job's context, in label order. The first id is S1.

Why only ids:

- **The job must remember which chunks it showed and in what order.** S1 in
  one job is a different chunk from S1 in another. Without this record, code
  can't check that a cited chunk was in the context, nor resolve a label for
  the reader.
- **Text, page, section and file name are not copied.** They are read through
  a join with `chunks` and `documents`, because the chunks of an indexed
  document never change.
- **A label whose chunk no longer exists** is left out of `sources`. The
  other labels keep their numbers.

A document job's `payload` is its request: `{"document_ids": […], "hint": …}`.
`build_context` writes `context_chunk_ids` once. A retry of that activity
writes the same list again.

### Workflow

- **Input:** `CardWorkflowInput` gains `document_ids` and `hint`, and
  `supplier_text` becomes optional. Exactly one of `supplier_text` and
  `document_ids` is set. The workflow id (`card-job-{id}`), the signals, the
  query and the decision code are unchanged, so both kinds of job are
  approved the same way.
- **Activities** for document jobs, on the `card-generation` queue:

| Activity | Does | Start-to-close | Max attempts |
|----------|------|----------------|--------------|
| `build_context` | finds the job's sources (`rag_pipeline.retrieve_context`, which writes nothing), then stores their chunk ids; returns the product line | 2 min | 3 |
| `generate_grounded_draft` | reads the context, writes a draft | 8 min (25 min schedule-to-close) | 3 |
| `verify_citations` | returns the draft's citation issues | 10 s | 5 |
| `critique_grounded_draft` | reads the context, checks the draft | 2 min | 2 |

- **Arguments:** activities pass the job id, the product line, issues and
  drafts. They never pass source text. Whatever an activity receives or
  returns, Temporal keeps in workflow history. Chunks hold the supplier's
  contact details, so they stay in Postgres, the one store whose personal
  data 09 will handle. This follows the approach of
  [ADR 0004](../adr/0004-uploaded-files-in-postgres.md).
- **Product line:** the text that tells the generator and the critic which
  product the card is for. It is the hint, or, without a hint, the first
  document's title ([Retrieval](#retrieval)).

**Algorithm (document job):**

```text
record retrieving
product = build_context(job, document_ids, hint)
issues = [], draft = none, citation violations = 0
for each round, at most 3:
    record generating (new attempt)
    draft = generate_grounded_draft(job, product, issues, previous draft)
    record critiquing
    citation issues = verify_citations(job, draft)
    if citation issues:
        verdict = revise, issues = citation issues
        citation violations += 1
        if citation violations == 2: stop the loop
        next round                       # the critic isn't called
    verdict, issues = critique_grounded_draft(job, product, draft)
    if verdict == pass: stop the loop
record awaiting_approval | needs_review, with the draft and the issues
wait for a decision (03)
```

- **Citations are checked before the critic.** An invented reference is
  certain from code alone, so the critic call is saved.
- **The second violating draft ends the loop.** A model that cites a source
  it wasn't given, after being told which sources it has, is unlikely to stop
  on a third try. A human sees the draft with the issues instead.
- **A violation still uses one of the three rounds.**
- **Routing** is `choose_draft_status`, as in
  [04](04-structured-output.md#routing). A loop stopped by citations ends with
  `revise`, and so in `needs_review`.
- **Non-retryable errors:** the card ones, plus `EmptyContextError`
  ([Edge cases](#edge-cases)).

### Retrieval

`rag_pipeline.retrieve_context` runs these steps and writes nothing; the
`build_context` activity then stores the chunk ids:

1. **Product line and query.** Use the hint. Without one, use the title of
   the first document in the request: the section of its first chunk, or,
   if that chunk has no section, its file name without the extension. In our
   documents the first section is the title, for example `VentBriz 40 Fan`
   or `Кофеварка капельная «КофеАрт 1000»`.
2. **Search.** Hybrid search ([06](06-embeddings-and-search.md#hybrid-search))
   for the query, limited to the requested documents. It returns 20
   candidates, and the similarity threshold is off (`min_similarity` -1).
   - **Why no threshold:** `SEARCH_MIN_SIMILARITY` decides whether a chunk
     relates to a query at all when the whole database is searched. Here the
     human has already chosen the documents. Similarity to a code says how
     much a text looks like the code, not whether it describes that product.
   - **Example, query `FAN-40`:**
     - the passport's `Package contents` scores 0.731 and the
       `DomTekh LLC · opt@…` line scores 0.731 too, both below 0.795;
     - no threshold separates the needed chunk from the noise.
3. **Documents that name the product.** A document with a candidate found by
   keyword search (`keyword_rank` not null) names the product word for word.
   Such documents come first, ordered by their best candidate. Each of them
   enters whole:
   - first its candidates, by rank;
   - then its other chunks, in reading order (one repository read).
   - **Why:** with all eight fan files of `data/bulk` and the hint `FAN-40`,
     the 20 candidates fill up with the `Технические характеристики` of other
     fans' passports. FAN-40's own `Комплект поставки` and
     `Гарантийные обязательства` don't reach the candidates at all.
4. **Other documents** follow with their candidates, by rank.
5. **Rows of other SKUs.** Suppose the hint equals a table-row chunk's `sku`
   in the assembled list, ignoring case and surrounding spaces. Then table
   rows with a different `sku` are dropped. For `FAN-40`, this drops the
   FAN-35 and FAN-45 rows of `fan_spec_1.xlsx`, the noise most likely to lend
   the card another model's values. Text chunks have no `sku` and stay.
6. **Duplicates.** A chunk whose text equals an earlier chunk's text is
   dropped. The first copy wins, which, by the order above, is the copy from
   the document most about the product. Ingestion normalised the text
   already, so plain string equality is enough. Example: the `Operating rules`
   section of the FAN-40 and FAN-45 passports.
7. **Limits.** Sources are taken in this order until 12 sources are taken.
   A source that doesn't fit the remaining budget of 3,000 tokens is skipped,
   and the next one is tried. A chunk is never cut: a cut table row or
   section loses what makes it understandable.
   - **Why both limits:** without a count limit, short table rows (about 44
     tokens each) would fill the token budget with dozens of other models.
   - **The budget:** 3,000 tokens leaves room in an 8k-token window for the
     instructions, a previous draft and a reply of up to 4,096 tokens.
   - **On our sets:** three fan files make 11 sources and about 550 tokens.
     All eight fan files of `data/bulk` make 12 sources and about 1,000
     tokens.
8. **Labels** go in context order: `S1`, `S2`, … The ids are stored in
   `context_chunk_ids`.

The limits are constants, not settings: changing them changes what every job
sees. Evaluation (08) may tune them. Steps 3–8 are one pure function in
`rag/context.py`.

**Empty context:** possible only when no chunk of the documents has a current
vector and keyword search finds nothing. `rag_pipeline.retrieve_context` then raises
`EmptyContextError` with the message `no chunks to build the context from;
run make reindex if the embedding model changed`, and the job fails.

### Token counting

- The budget is counted with the tokenizer of the model behind the LLM
  client ([ADR 0006](../adr/0006-context-budget-tokenizer.md)).
- **`LLM_TOKENIZER`** is the model's Hugging Face repository. The default is
  `google/gemma-4-E4B-it`, the tokenizer of the default `LLM_MODEL`; GGUF and
  MLX builds of the model share it. The setting is in `.env.example` next to
  `LLM_MODEL`, because changing the model means changing its tokenizer.
- **Model change guard:** when `LLM_MODEL` differs from its default,
  `LLM_TOKENIZER` must be set explicitly, as the embedding model guard
  requires ([06](06-embeddings-and-search.md#settings)). Otherwise settings
  fail with `LLM_MODEL is changed: also set LLM_TOKENIZER to the model's
  Hugging Face repository`.
- **Loading:**
  - the tokenizer is loaded through the `tokenizers` library, which is
    already installed with fastembed;
  - the first load downloads `tokenizer.json` (about 30 MB) into the Hugging
    Face cache, and later loads read it from disk;
  - the worker loads it at startup, next to the embedding model, so a
    missing file stops the worker instead of failing a job;
  - the API never loads it.
- Tokens are counted without special tokens. The source tags add a few tokens
  per source, which the margin of the window covers.

### Context format

The sources go into the prompt in tags:

```text
<source id="S1" file="fan_spec_1.xlsx" page="1" section="Specification">
FAN-40: Brand VentBriz; Model 40; Power 40 W; Blade diameter 27 cm; …
</source>
<source id="S2" file="fan_passport_fan_40.pdf" page="2" section="Package contents">
Package contents
No. Item Qty
1 Fan 1 pc. …
</source>
```

- **Tags mark explicit boundaries.** A chunk's text can't be mistaken for the
  start of another source.
- **Metadata are named attributes**, so the model reads them as fields.
- **09 can build on the tags:** text inside `<source>` is data, not
  instructions.
- An attribute that a chunk lacks is left out.

### Grounded draft

`GroundedCardDraft` in `schemas/cards.py` is `CardDraft` with characteristics
that cite their sources:

```json
"characteristics": {
  "Power": {"value": "40 W", "sources": ["S1"]},
  "Package contents": {"value": "fan, support stand, cross base, passport", "sources": ["S2"]}
}
```

- `value`: the same rules as a `CardDraft` value. A blank or
  punctuation-only value moves the characteristic to `missing_fields`.
- `sources`: at least one label, each matching `S<number>`. An empty list or a
  malformed label is a validation error. It goes through a field fix
  ([04](04-structured-output.md#output-repair-and-field-fix-structuredpy)),
  not through citation verification: it is a broken format, not a citation
  to an unknown source.
- Every other field, rule and the confidence formula are those of
  `CardDraft`. Drafts sent back to the generator or to the critic still leave
  out `confidence`.
- A job's stored `result` is a `CardDraft` for a supplier-text job and a
  `GroundedCardDraft` for a document job.

### Citation verification

`verify_citations` takes the job id and the draft. It reads
`context_chunk_ids` and asks the chunks repository which of them still
exist. It returns one issue per bad citation, in the order of the draft's
characteristics:

```text
# The label isn't in the context
Characteristic "Power" cites S9, but no source S9 was given. Cite only ids of the <source> tags above, or move "Power" to missing_fields if no source states it.

# The label was in the context, but its chunk no longer exists
Characteristic "Power" cites S3, but that source is no longer available. Cite another source that states it, or move "Power" to missing_fields.
```

- The issues go to the generator as the next round's feedback. If the loop
  ends, they are saved in `critique_issues`, so the human reads the same text.
- **A chunk that no longer exists** can happen only if a document is
  re-chunked between retrieval and verification. Nothing re-chunks an indexed
  document today, but the check is cheap and keeps the second condition
  honest.

### Prompts

**Generator (document jobs):**

- The user message holds `Product: <product line>`, the sources, and, in a
  revision, the previous draft and the issues.
- The rules:
  - use only the sources;
  - every characteristic cites the labels of the sources that state its
    value;
  - describe only the product of the product line. Sources about other
    models are context, never values;
  - the card is for a retail buyer: no wholesale prices, order or delivery
    terms, and no supplier company or contacts;
  - each benefit turns a fact from the sources into a benefit for the buyer,
    without praise the sources don't state;
  - a value saying the product lacks a feature ("no") is a value, not a
    missing field;
  - a characteristic a buyer of this product type expects that no source
    states goes to `missing_fields`, never gets a value and never gets a
    placeholder. This is the extractor's rule, now the generator's;
  - write in the main language of the sources.
- Title, description, benefits, SEO and their limits are as in
  [04](04-structured-output.md#prompts).
- Temperature, `max_tokens`, timeouts and retries are the generator's
  existing settings.

**Critic (document jobs):** receives the product line, all the sources and
the draft. Its checklist:

1. Each characteristic's value is stated in the sources it cites.
2. Each missing field is absent from every source; a feature stated as
   "no" is not missing.
3. The description, benefits and SEO text state nothing that the sources
   don't, praise included.
4. All text is in the main language of the sources.
5. Each characteristic's sources describe the product of the product line,
   not another model.
6. The card leaves out wholesale prices, order and delivery terms, and the
   supplier's company and contacts.

**Issue format, both paths:**

- The rules stay a numbered checklist in the critic's prompt, but an issue
  doesn't cite a rule number: the generator reads the issues and doesn't
  know the numbers.
- An issue starts with the source label or the draft field it concerns:
  - `S1: Power is 40 W in S1, the draft says 45 W`
  - `S3: Blade diameter 30 cm is from FAN-45, not FAN-40`
  - `missing_fields: Package contents is listed as missing, but S2 lists it`
  - `description: "quiet operation" is stated in no source`
- The supplier-text critic follows the same format, starting with a field
  name ([04](04-structured-output.md#prompts)).

### Logs

- `context_assembled` (info): `job_id`, `documents`, `candidates`, `sources`,
  `tokens`, `duplicates_dropped`, `other_sku_rows_dropped`,
  `cut_by_limit`, `chunk_ids`.
- `citations_invalid` (warning): `job_id`, `citations`: a list of
  `{"characteristic", "label", "reason"}`, where `reason` is `not_in_context`
  or `chunk_missing`.

No log line carries chunk text or query text
([06](06-embeddings-and-search.md#logs)). Ids, labels and characteristic
names are enough to find the text in the database.

### Worker

- The `card-generation` worker registers the four new activities.
- At startup the process loads the tokenizer after the embedding model, and
  before either worker polls. `build_context` embeds the query with the
  model the process already holds.

## Behaviour

### Job status

```text
pending ─┬─▶ extracting ─┬─▶ generating ⇄ critiquing ─┬─▶ awaiting_approval ─┬─▶ approved
         └─▶ retrieving ─┘                            └─▶ needs_review ──────┴─▶ rejected
any non-terminal status ─────────────────────────────────────────────────────────▶ failed
```

| Status | Meaning | Terminal |
|--------|---------|----------|
| `retrieving` | a document job is searching its documents and assembling the context | no |

- Supplier-text jobs pass `extracting`, and document jobs pass `retrieving`.
- `generating` may follow `extracting`, `retrieving` or `critiquing`.
- For a document job, `critiquing` covers both the citation check and the
  critic.
- Other statuses keep their meaning from [03](03-generation-pipeline.md#job-status)
  and [04](04-structured-output.md#job-status).

### Edge cases

| Situation | Behaviour |
|-----------|-----------|
| The model cites S9, which isn't in the context | Code catches it, and the draft is revised with the explanation. A second time, the job goes to `needs_review` with the issues. |
| A value from another model (FAN-45's 30 cm in a FAN-40 card) | The SKU filter drops other models' table rows. Other models' passports reach the critic (checklist item 5). If the critic misses it, the human sees the source next to the value. |
| The hint names a product the documents lack (`FAN-99`) | No document names it, so the context is the best candidates. The expected draft has every characteristic missing, confidence 0, and goes to `needs_review`. The risk is values taken from FAN-40; the critic and then the human catch them. |
| Many documents chosen | Documents that name the product enter whole. A useful chunk of a document that doesn't name it may not fit in 12 sources. |
| One section repeated in two passports | One copy, from the document that comes first. |
| English and Russian versions of one offer chosen together | The model picks the main language. The critic's language check catches mixed text, which leads to a revision or `needs_review`. |
| `LLM_TOKENIZER` not changed with the model | Settings refuse to load (the guard). If it is set wrong on purpose, the budget is off by 10–20%, which an 8k window absorbs. |
| No hint, and the first document is a spreadsheet | The title is the sheet name, which names no product. A table of several models needs a hint; the README says so. |
| A document is `parsing`, `embedding` or `failed` | `409`, listing each such document with its status. |
| No chunk can be retrieved | `EmptyContextError`; the job is `failed` with the message above. |
| The worker restarts during a document job | Completed activities aren't repeated. A repeated `build_context` stores the same list. |

## Verification

Each behaviour is tested once, at the cheapest level that shows it.

- **GND-1:** API tests with the workflow start substituted:
  - `202` and a `pending` job;
  - `404` and `409` with the listed ids;
  - `422` for an empty list, 11 ids, a repeated id and a blank hint;
  - a repeated key returns the same job.
- **GND-2, GND-3:** unit tests of the pure assembly function on hand-built
  search results and chunks:
  - documents that name the product come first and enter whole, candidates
    before their other chunks;
  - other documents follow by rank;
  - rows of other SKUs are dropped only when the hint is one of the rows'
    SKUs;
  - the first copy of a duplicate wins;
  - the 12-source limit;
  - a source over the remaining budget is skipped and a smaller one is taken;
  - labels follow the order;
  - the title fallback when there is no hint.

  Token counting is substituted.
- **GND-4:** schema tests for `GroundedCardDraft`: an empty `sources` list or
  a malformed label is a field error, and a blank value moves the
  characteristic to `missing_fields`.
- **GND-5, GND-7, GND-8, GND-9:** two end-to-end tests. Each one:
  - goes from the API through Temporal's time-skipping environment with the
    real activities to a testcontainers database;
  - starts from documents and chunks stored by `tests/integration/seeds.py`,
    with hand-made vectors;
  - substitutes the query embedding, token counting and the LLM client, which
    answers from a script.
  1. **Happy path:**
     - the generator cites S1 and S2, and the critic passes;
     - the job goes `retrieving`, `generating`, `critiquing`,
       `awaiting_approval`, and approval makes it `approved`;
     - `GET /jobs/{id}` returns the draft and its two sources;
     - the workflow history shows the activities in that order, then the
       signal.
  2. **Invented citation:**
     - the generator cites S9 twice;
     - the second generation request carries the issue text;
     - the critic is never called;
     - the job ends in `needs_review` with the issue in `critique_issues`.
- **GND-6:** prompt builder tests: the product line, the source tags and the
  checklist are present, and no issue example cites a rule number.
- **Repositories:** the chunks of given documents come in reading order; the
  existence check returns the ids that exist; a job's sources come back in
  label order with file, page and section; `retrieving` follows `pending`
  and precedes `generating`.
- **Settings:** a changed `LLM_MODEL` without `LLM_TOKENIZER` fails, and with
  it passes.
- **No downloads:** an autouse fixture makes loading the tokenizer fail in
  every test, as one already does for the embedding model. Captured logs of
  assembly and verification hold no chunk text.

## Acceptance criteria

1. The automated verification above passes in CI. *(test)*
2. On the documents of `evals/datasets`, each scenario of the
   [manual run](#manual-run) ends as expected. *(manual)*
3. A draft with an invented citation is revised, then ends in `needs_review`.
   *(test)*
4. The workflow history of an approved job shows retrieval, generation,
   citation check, critique, the wait, the signal and completion.
   *(manual + test)*

The README's Installation section covers the tokenizer download and the model
window of at least 8k tokens. Its Usage section shows a generation request,
reading the job with its sources, and a decision.

## Manual run

Run on 2026-10-13 against LM Studio (`gemma-4-e4b-it-mlx`) with the
documents of `evals/datasets` ingested:

| # | Documents | Hint | Expected | Result |
|---|-----------|------|----------|--------|
| 1 | `fan_passport_fan_40.pdf`, `fan_spec_1.xlsx` | `FAN-40` | `awaiting_approval`; every characteristic cites a source; no FAN-35 or FAN-45 values | as expected: two rounds, confidence 1.0, package contents from the passport |
| 2 | `fan_passport_fan_45.pdf` | `FAN-45` | package contents in `missing_fields` (the passport has no such section); confidence below 1 | as expected: package contents the only missing field, confidence 0.92 |
| 3 | `blender_kp_ru.docx` | `BLD-800` | a draft in Russian; no BLD-500 or BLD-1200 values | as expected: three rounds, confidence 0.8; the SKU filter left only the BLD-800 row, no wholesale price |
| 4 | `coffee_passport_cfe_1000.pdf` | none | the query is the title; a draft in Russian | as expected; "Таймер: нет" kept as a value, but package contents listed as missing although S3 holds it |
| 5 | `fan_passport_fan_40.pdf`, `fan_spec_1.xlsx` | `FAN-99` | `needs_review`; nothing taken from FAN-40 | as expected: no characteristics, confidence 0 |

Observations:

- **Earlier runs found missing rules.** Before the retail, benefit and "no"
  rules were added to the prompts, drafts listed values of "no" as missing
  ("Sleep timer", "Таймер"), carried wholesale prices and supply terms, and
  padded benefits with praise the sources don't state.
- **Package contents of coffee passports.** It is listed as missing although
  a source holds it, here and in a run on `data/bulk` (CFE-600 passport, hint
  `КофеАрт 600`). The critic passes the draft both times.
- **Benefits of a commercial offer** still address retailers ("подходит для
  маркетплейсов"), because an offer says little about the product itself.
- **Evaluation (08) measures these.** It checks missing-field accuracy and
  claims supported by sources; the coffee passports belong in its reference
  set.

## Open questions

None.
