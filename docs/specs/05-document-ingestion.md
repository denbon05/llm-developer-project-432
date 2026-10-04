# 05 · Document ingestion

**Status:** accepted

## Context

Until now a card draft has started from plain supplier text. Suppliers send
files instead. Product passports and commercial offers come as PDF or DOCX,
specifications as XLSX. A file is not text: it mixes paragraphs, tables,
repeated page lines and layout, and each format causes its own problems.

This spec turns an uploaded supplier document into **chunks**. A chunk is a
normalised piece of text with the metadata that later search filters on and
citations point to: document, page and section. Retrieval (06) and grounded
generation (07) build on these chunks.

A document that can't be turned into chunks ends `failed`, with a reason. It
never ends `indexed` with nothing in it: an empty card draft with no
explanation would look like a broken service.

## Requirements

- **ING-1 — Upload:** the API accepts a PDF, DOCX or XLSX file of at most
  10 MiB and answers `202` with the document's id. It refuses any other file
  with a status that says why.
- **ING-2 — No duplicates:** uploading the same bytes again, even
  concurrently, returns the existing document and creates no new chunks.
- **ING-3 — Durable ingestion:** ingestion runs as a Temporal workflow, off
  the request path, and survives worker restarts. PostgreSQL holds the
  document status of record.
- **ING-4 — Structure:** PDF text is read page by page. DOCX headings mark
  section boundaries. XLSX rows keep their column headers. Every structural
  unit knows its page.
- **ING-5 — Normalisation:** running headers are removed, words hyphenated
  across lines are joined again, ligatures are expanded and whitespace is
  collapsed.
- **ING-6 — Chunking:** text is cut into overlapping windows of a fixed
  size. A table row is never split, and it carries its column headers.
- **ING-7 — Metadata:** every chunk records its document, position, page and
  section. A table row also records its row number, plus its SKU and brand
  when the table has those columns.
- **ING-8 — Explicit failure:** a document that can't be read, or that yields
  no text, ends `failed` with a reason. A scan without a text layer is one
  example.
- **ING-9 — Untrusted input:** an upload is checked before it is stored, an
  archive's unpacked size is checked before it is opened, and chunk text
  never reaches the logs.
- **ING-10 — Testability:** parsing is verified on the committed document
  set. Tests need neither a model server nor the developer's Compose
  database.

## Non-goals

- OCR. A scan without a text layer fails (ING-8).
- Table extraction from PDFs. A PDF table row reaches its chunk as one text
  line, with its cells in order.
- Embeddings, the full-text column and search (06). Context assembly and
  removing duplicates across documents (07).
- Masking personal data and detecting prompt injection (09). Chunks store the
  text as extracted, small print included, so 09 sees what a model would.
- Object storage for uploaded files
  ([ADR 0004](../adr/0004-uploaded-files-in-postgres.md)).
- Ingesting a document again: retrying a `failed` one, deleting one, or
  keeping versions after the chunking rules change.
- Legacy `.doc` and `.xls`, and every other format.
- Multi-row spreadsheet headers, and nested DOCX tables, text boxes,
  footnotes and comments.
- Limiting a request body before the server has received all of it. A
  reverse proxy does that in production.
- An endpoint that lists chunks, and an operator view of the ingestion
  workflow.

## Design

Parsing, normalisation and chunking rest on heuristics. The code states the
reason for each rule in a short comment.

### Component flow

```text
POST /documents ─▶ upload checks ─▶ documents repository
                                       └─▶ DocumentIngestionWorkflow
                                             ├─▶ record_document_status ─▶ documents repository
                                             └─▶ parse_document ─▶ documents service
                                                                     ├─▶ documents repository   load the file
                                                                     ├─▶ parsers, in a thread   parse, normalise, chunk
                                                                     └─▶ chunks repository      replace the chunks

GET /documents/{id} ─▶ documents repository
```

The modules come from the
[platform layout](02-platform-foundation.md#module-layout):

- `routers/documents.py` and `services/documents.py`;
- `parsers/`: `pdf.py`, `docx.py`, `xlsx.py`, `normalizer.py`, `chunker.py`;
- `repositories/documents.py` and `repositories/chunks.py`;
- `schemas/documents.py`: the API models, the document status, the workflow
  input, and the parsed block that parsers pass to the normaliser and the
  chunker;
- the Temporal modules.

### Upload checks

The router reads at most the size limit plus one byte. The service then
checks, in this order:

1. The file name is at most 255 characters. Otherwise `422`.
2. The extension, ignoring case, is `.pdf`, `.docx` or `.xlsx`. It sets the
   document's `format`. Otherwise `415`.
3. The file is at most `DOCUMENT_MAX_SIZE_BYTES`. Otherwise `413`.
4. The file is not empty. Otherwise `422`.
5. The file starts with its format's signature. That is `%PDF-` for PDF, and
   a ZIP header (`PK\x03\x04`) for DOCX and XLSX, which are ZIP archives of
   XML files. Otherwise `415`. A file that passes this check but can't be
   parsed ends `failed` later.

The file name is kept for display only. It is never used as a path.

A document's identity is the SHA-256 of its bytes. Creating a document is one
`INSERT … ON CONFLICT (content_sha256) DO NOTHING`, as for jobs, so
concurrent uploads of one file create one document. A repeated upload keeps
the first file name.

Once the row exists, the router starts the workflow if the document is still
`pending`. This is the same recovery as job creation: if Temporal is down,
the answer is `503` and the row stays `pending`, and uploading the same file
again starts the workflow.

### Storage

The `create_documents` and `create_chunks` migrations are the source of
truth.

**Document:**

- `id`, `filename`, `format` (`pdf`, `docx` or `xlsx`), `size_bytes`;
- `content_sha256`, unique;
- `content`, the file itself, as `bytea`
  ([ADR 0004](../adr/0004-uploaded-files-in-postgres.md));
- `status` and `error`, then the timestamps.

`status` is `text` with a `CHECK`, and `(status, updated_at)` is indexed, as
for jobs. Repositories read `content` only to parse it.

**Chunk:**

- `id`;
- `document_id`, a foreign key that deletes the chunks along with their
  document. It is indexed, because nearly every search filters on it.
- `text`;
- `metadata`, as `jsonb`.

Metadata is `jsonb` because its keys differ between kinds of chunk, and a new
key needs no migration. 06 adds the vector and full-text columns.

| Key | Present on | Value |
|-----|-----------|-------|
| `position` | every chunk | 0, 1, 2… in the document's reading order |
| `kind` | every chunk | `text` or `table_row` |
| `page` | every chunk | PDF: the page; DOCX: the approximate page ([DOCX](#docx)); XLSX: the sheet's position in the workbook, from 1 |
| `section` | every chunk | the heading the chunk sits under, or the sheet name; `null` when the document has no heading |
| `row` | `table_row` | the row number a person sees: the sheet row in XLSX, or the row within its table in DOCX. The header row counts as row 1. |
| `sku` | `table_row` in a table with a SKU column | the cell's value |
| `brand` | `table_row` in a table with a brand column | the cell's value |

A chunk's keys depend on its kind, not on the file format, so search and
citations never need to know where a chunk came from. For example, the
`position` 0–4 chunks of `fan_passport_fan_40.pdf` sit under
`VentBriz 40 Fan` and `Technical specifications` on page 1, then under
`Package contents`, `Operating rules` and `Warranty obligations` on page 2.

A document's chunk count is computed when the document is read; there is no
counter column. Replacing a document's chunks is one transaction that deletes
the old chunks and inserts the new ones. A retried `parse_document`
therefore leaves exactly one set.

### Parsing

Each parser takes the file's bytes and returns blocks in reading order. A
block has a page and a section. It is either text (a list of lines) or a
table (column headers, and rows with their row numbers).

#### PDF

- pdfplumber reads each page's text lines. Words on one baseline form one
  line, so a table row such as `Power 40 W` stays together.
- A **heading** is a line in which every character is in a bold font and the
  font size is larger than the document's most common line size. In the
  committed passports, headings are bold 12 or 16 pt, body text is 10 pt and
  table rows are 9 pt. The bold 9 pt table header (`Parameter Value`) is
  therefore not a heading.
- A page without text is skipped and counted in the log. If no page has
  text, the document is unreadable: "the PDF has no text layer; it may be a
  scan, and OCR is not supported".
- A file pdfplumber can't open, including an encrypted one, is unreadable:
  "the file is not a readable PDF".

#### DOCX

- python-docx reads the paragraphs and tables of the body in document order.
  Page headers and footers are stored as separate parts of the file and are
  not read.
- A **heading** is a paragraph styled `Title` or `Heading 1`–`Heading 9`.
  python-docx reports built-in style names in English, whatever the language
  of the Word installation that saved the file.
- **Page:** DOCX stores no page numbers. The page is 1 plus the number of
  page breaks before the paragraph or table. When Word last laid out the
  file, it recorded where each page began (`lastRenderedPageBreak`). If the
  file has these marks, only they count; otherwise explicit page breaks
  count. The result is approximate, and a generated file without breaks is
  page 1 throughout.
- A table's first row holds its column headers. A cell's text is its
  paragraphs joined with spaces. A merged cell's text appears under every
  column it spans.
- A file python-docx can't open is unreadable: "the file is not a readable
  DOCX".

#### XLSX

- openpyxl reads the cell values of each visible sheet in read-only mode; a
  formula yields its last saved value. Hidden sheets are skipped.
- On each sheet, the first row with a non-empty cell holds the column
  headers, and every later non-empty row is a table row.
- Values become text: whole numbers without `.0` (`35`, not `35.0`), other
  numbers in their shortest form (`2.4`), dates as ISO dates, and text
  trimmed. A formula without a saved value counts as an empty cell.
- The section is the sheet name, and the page is the sheet's position in the
  workbook.
- A file openpyxl can't open is unreadable: "the file is not a readable
  XLSX".

#### Archive limit

DOCX and XLSX files are ZIP archives. Text XML compresses about tenfold, and
a crafted archive (a "ZIP bomb") a few kilobytes long can unpack to
gigabytes and exhaust the worker's memory.

Before opening an archive, the parser reads its central directory: the list
of its files with each file's unpacked size, read without unpacking
anything. If the sizes add up to more than 100 MiB, the document is
unreadable: "the archive unpacks to more than 100 MiB". A PDF is not an
archive; the upload limit and the activity timeout bound it.

#### Sections

For PDF and DOCX:

- A heading starts a new section. Consecutive headings form one group, and
  the last heading names the section: `PRODUCT PASSPORT` followed by
  `VentBriz 40 Fan` gives the section `VentBriz 40 Fan`.
- Headings stay in the text, at the start of the block they open. Otherwise a
  product name set as a heading would vanish from search.
- Text before the first heading belongs to the first section.
- A section continues across a page break. The new page starts a new block
  with the same section.
- A document without any heading has a `null` section.

### Normalisation (`normalizer.py`)

These steps run in order on every text block. Steps 1 and 2 also run on
every table cell.

1. **Characters:** the ligatures `ﬀ ﬁ ﬂ ﬃ ﬄ ﬅ ﬆ` are expanded, and the text
   is converted to NFC form. NFKC is not used: it would also rewrite `m²` as
   `m2` and `½` as `1⁄2`. Soft hyphens (U+00AD) and zero-width characters
   are removed.
2. **Whitespace:** no-break spaces, tabs and other space characters become a
   plain space, and runs of spaces collapse to one. Lines are trimmed and
   empty lines are dropped. A line break inside a table cell becomes a
   space.
3. **Running headers**, only in PDFs of two or more pages:
   - A running header is a line repeated at the top or bottom of each page,
     for example `DomTekh LLC · opt@domteh.example · www.domteh.example —
     p. 1`.
   - Only the first three and last three lines of a page are candidates.
   - Digits are masked when lines are compared, so `p. 1` and `p. 2` match.
   - A line found on at least two pages, and on at least half of all pages,
     is removed wherever it appears at a page edge. The same text inside a
     page's body stays.
   - The "at least two pages" condition protects a two-page document. Under
     a "most pages" rule, one page out of two would count as a majority, and
     every line would be removed.
   - A one-page document keeps all its lines, because nothing can repeat.
4. **Hyphenation:** a line that ends in a letter or digit followed by `-` is
   joined with the next line.
   - If the next line starts with a lowercase letter, in any alphabet, the
     hyphen only marked a line break and is dropped: `мощ-` + `ность` →
     `мощность`.
   - Otherwise the hyphen belongs to the word and stays: `FAN-` + `40` →
     `FAN-40`, `Wi-` + `Fi` → `Wi-Fi`.
   - A lowercase compound broken at its own hyphen (`black-` + `and-white`)
     loses that hyphen. This is rare and accepted.

A block left empty after normalisation is dropped.

### Chunking (`chunker.py`)

**Text blocks:**

- A block's lines are joined with line breaks. A block of at most 1,200
  characters becomes one chunk.
- A longer block is cut into chunks of at most 1,200 characters. A chunk ends
  at the last line break in its window, otherwise at the last sentence end,
  otherwise at the last space. A chunk ends inside a word only when a single
  word is longer than the window.
- The next chunk starts 150 characters before the previous one ended, moved
  forward to the start of a word. A statement cut at a boundary therefore
  keeps its context in the next chunk.
- The sizes suit a 512-token embedding model such as multilingual-e5-base,
  which 06 is expected to use. 1,200 characters of English or Russian text
  is roughly 300–400 tokens, which leaves room for the model's prefix. The
  overlap is one eighth of the size.
- Both sizes are constants, not settings: changing them means ingesting
  every document again.
- Each block has one page and one section, so a chunk never crosses a page
  or section boundary. The overlap works only within a block.

**Table rows:**

- Each row becomes one chunk, however long it is, so a row is never split.
- The row text names every column, so each chunk of a large table carries
  the column headers. It reads `<key>: <column> <value>; <column> <value>; …`:
  - The key is the value in the SKU column if the table has one, otherwise
    the value in the first column.
  - Empty cells are skipped. A value under an empty header appears on its
    own.
  - For a header `<name>, <unit>` whose unit is one word without digits, the
    unit moves after the value: `Power, W` and `40` give `Power 40 W`. A value
    that already ends with the unit doesn't repeat it. Every other header is
    used as it is: `Price, pcs from 100 2,490 RUB`.
  - Example, `fan_spec_1.xlsx`, sheet row 3: `FAN-40: Brand VentBriz;
    Model 40; Power 40 W; Blade diameter 27 cm; Weight 2.5 kg; Wholesale
    price 2,490 RUB`.
- **SKU and brand columns** are recognised by their header. Headers are
  compared ignoring case and any trailing `.` or `:`:
  - SKU: `SKU`, `Article`, `Art. No`, `Артикул`, `Арт`;
  - brand: `Brand`, `Trademark`, `Бренд`, `Марка`, `Торговая марка`.
- Text chunks carry neither key. Finding codes in free text waits until
  evaluation (08) shows it is needed.

**Whole document:**

- A chunk whose text equals an earlier chunk of the same document is
  dropped, so a repeated block doesn't count twice in search.
- Duplicates across documents stay: each one is a citation of its own
  document, and 07 removes duplicates when it assembles the context.
- Positions are numbered after duplicates are dropped, so they have no gaps.
- A document left without chunks is unreadable: "the document contains no
  text".

### Workflow

There is one workflow per document: `DocumentIngestionWorkflow`, with ID
`document-{document_id}`, on the task queue `document-ingestion`. Its input
is the document id only: the file never passes through Temporal
([ADR 0004](../adr/0004-uploaded-files-in-postgres.md)).

| Activity | Does | Start-to-close | Max attempts |
|----------|------|----------------|--------------|
| `record_document_status` | writes the status | 10 s | 5 |
| `parse_document` | loads the file, parses, normalises, chunks and replaces the chunks; returns the chunk count | 5 min | 3 |

- **Algorithm:** record `parsing`, run `parse_document`, record `indexed`.
  When an activity fails for good, the workflow records `failed` with the
  cause's type and message (best effort), then fails, as a job's workflow
  does.
- **Retries** start after 2 s, with backoff coefficient 2. These errors are
  not retried:
  - `UnreadableDocumentError`, because the same file fails the same way;
  - a missing document;
  - a disallowed status transition.
- **`parse_document`** is an `async def` activity:
  - It loads the file in one database operation.
  - It runs parsing, normalisation and chunking through `asyncio.to_thread`.
    That work blocks and is CPU-bound; in a thread it leaves the worker's
    event loop free for other activities.
  - It replaces the chunks in one transaction.
  - It holds no database connection while it parses.
- **Setting:** `TEMPORAL_DOCUMENT_TASK_QUEUE`, default `document-ingestion`.

### Worker

- One process, `make worker`, runs two Temporal workers on one client:
  - `card-generation`: the card workflow and its four activities
    ([03](03-generation-pipeline.md#workflow));
  - `document-ingestion`: this workflow and its two activities.
- **Why two queues:** parsing loads the CPU, while generation waits on the
  model server.
  - With separate queues, a burst of uploads can't take card generation's
    activity slots.
  - Each kind of work gets its own concurrency limit.
  - Ingestion can later move to a process of its own without code changes.
- **No thread pool:** the worker's activity thread pool is removed.
  - Temporal runs only activities declared with plain `def` in an
    `activity_executor`.
  - Every activity here is `async def`.
  - Blocking work goes through `asyncio.to_thread`, which uses Python's
    default thread pool.
- Each worker keeps Temporal's default `max_concurrent_activities` until a
  bulk run shows a reason to change it.
- SIGINT or SIGTERM stops both workers.

### HTTP API

| Method and path | Router | Success | Errors |
|-----------------|--------|---------|--------|
| `POST /documents` (multipart field `file`) | `documents.py` | `202 {"id", "status"}` | `413` · `415` · `422` · `503` |
| `GET /documents/{id}` | `documents.py` | `200` document | `404` |

- **Document view:** `id`, `filename`, `format`, `size_bytes`, `status`,
  `error`, `chunk_count`, `created_at`, `updated_at`. Never the content.
- A repeated upload answers `202` with the existing document's id and its
  current status (ING-2).
- **Error kinds:** two kinds join `core/errors.py`. An exceeded size limit
  answers `413`, and an unsupported format answers `415`.
- **Details:**
  - `413 {"detail": "file is larger than 10 MiB"}`, with the configured limit
    in the message;
  - `415 {"detail": "unsupported file type: accepted are pdf, docx and xlsx"}`;
  - `422 {"detail": "file is empty"}` or
    `422 {"detail": "file name is longer than 255 characters"}`;
  - `404 {"detail": "document not found"}`.
- `python-multipart` becomes a dependency, because FastAPI needs it to read
  uploads.
- **Setting:** `DOCUMENT_MAX_SIZE_BYTES`, default 10 MiB (10,485,760).

Like `TEMPORAL_DOCUMENT_TASK_QUEUE`, this is a tuning setting with a default
in code, so it is not in `.env.example`.

### Ingest command

`make ingest dir=<path>` runs `evals/ingest.py` against the running API and
worker. The default directory is `evals/datasets`. The command:

- uploads every PDF, DOCX and XLSX file directly inside the directory, then
  polls each document until it is `indexed` or `failed`. It gives up after
  10 minutes.
- prints one line per file: name, status, chunk count, ingestion time and
  error. Then it prints totals: documents per status, chunks, and the median
  and 95th-percentile ingestion time.
- takes ingestion time as the document's `updated_at` minus `created_at`, so
  polling doesn't distort it. A file ingested earlier keeps its first time.
- exits with 1 if a request failed or a document didn't finish in time.
  Otherwise it exits with 0, even when some documents failed.
- takes the API address as an option, default `http://localhost:8000`.

The command serves two runs:

- the committed set in `evals/datasets/`, as the reference run;
- an optional bulk set in `data/bulk/`, which is not committed. It provides
  load and checks the rules on documents they were not tuned on.

### Logs

- `document_uploaded` (info): `document_id`, `format`, `size_bytes`,
  `was_created`.
- `document_parsed` (info): `document_id`, `pages` (sheets for XLSX),
  `pages_without_text`, `chunk_count`, `duration_ms`.
- `document_unreadable` (warning): `document_id`, `reason`.

No log line carries chunk text, file content or the file name, because
supplier files hold personal data
([01](01-product-overview.md#principles), principle 4).

## Behaviour

### Document status

```text
pending ─▶ parsing ─▶ indexed
any non-terminal status ─▶ failed
```

| Status | Meaning | Terminal |
|--------|---------|----------|
| `pending` | file stored; workflow not yet picked up | no |
| `parsing` | parsing, normalisation and chunking in progress | no |
| `indexed` | chunks stored | yes |
| `failed` | the document is unreadable, or an activity failed after its retries; `error` says why | yes |

- 06 adds `embedding` between `parsing` and `indexed`. From then on,
  `indexed` means ready for search.
- Only `record_document_status` writes the status. A write applies only when
  the transition is allowed. Writing the status a document already has is a
  no-op, as for jobs.
- An `indexed` document always has at least one chunk.

### Failure reasons

```text
UnreadableDocumentError: the PDF has no text layer; it may be a scan, and OCR is not supported
UnreadableDocumentError: the archive unpacks to more than 100 MiB
UnreadableDocumentError: the document contains no text
```

### Durability

- A worker lost during `parse_document` costs one attempt.
- The chunks are replaced in one transaction, so a lost attempt has written
  either nothing or a complete set, and the retry replaces it.
- A document whose workflow never started stays `pending` until the same file
  is uploaded again.

## Verification

- **ING-1:**
  - Unit tests of the upload checks: every accepted extension in any case; a
    wrong extension or signature answers `415`, an oversized file `413`, an
    empty file or a long name `422`.
  - API integration tests, with the workflow start substituted: `202`, `GET`
    with `chunk_count`, `404`, and `503` when Temporal is down.
- **ING-2:**
  - Repository test: two concurrent creations with the same bytes give one
    document.
  - API test: a repeated upload answers the same id, and starts the workflow
    again only while the document is `pending`.
  - Replacing a document's chunks twice leaves one set.
- **ING-3:**
  - Workflow tests in Temporal's test environment with stub activities: the
    statuses go `parsing`, then `indexed`; `UnreadableDocumentError` is not
    retried and ends `failed` with its type and message; a transient error is
    retried.
  - Repository tests of the allowed status transitions.
- **ING-4, ING-5, ING-7:** parser tests on the committed set:
  - `fan_passport_fan_40.pdf`: two pages. `Power 40 W` is in a page-1 chunk
    under `Technical specifications`. Page 2 holds `Package contents`,
    `Operating rules` and `Warranty obligations`. No chunk contains the
    running header.
  - `coffee_passport_cfe_1000.pdf`: the footer `… — стр. 1` / `стр. 2` is
    removed, and `Технические характеристики` is a page-1 section.
  - `fan_kp_2.pdf`: a single page, so its company line stays.
  - `fan_spec_1.xlsx`: three `table_row` chunks. The FAN-40 chunk reads
    exactly as in the [example](#chunking-chunkerpy), with page 1, section
    `Specification`, row 3, sku `FAN-40` and brand `VentBriz`.
  - `vacuum_spec_1.xlsx`: the VCS-180 row says `Power 500 W`.
  - `blender_kp.docx` and `blender_kp_ru.docx`: the price-list rows carry the
    skus `BLD-500`, `BLD-800` and `BLD-1200`, under `Price list (wholesale)`
    and `Прайс-лист (опт)` respectively.
- **ING-5:** normaliser unit tests on short texts written in the test:
  - the two-page trap: every body line survives and the repeated edge line is
    removed;
  - masked page numbers;
  - a repeated line inside a page's body that stays;
  - every hyphenation case, including a Cyrillic one;
  - ligatures, no-break spaces and soft hyphens.
- **ING-6:** chunker unit tests:
  - chunk size and overlap;
  - no cut inside a word;
  - no chunk across a page or section;
  - a table row longer than 1,200 characters stays one chunk;
  - duplicates within a document are dropped;
  - positions have no gaps;
  - units move after values in row text.
- **ING-8:** `fan_passport_fan_45_scan.pdf` is unreadable with the
  no-text-layer reason, and a document without text is unreadable.
- **ING-9:** an archive whose files add up to more than 100 MiB is refused
  before anything is unpacked. Captured logs of a parse hold no chunk text.
- **ING-10:** parser tests read files from `evals/datasets/`, database tests
  use testcontainers, and no test calls a model.

## Acceptance criteria

1. The automated verification above passes in CI. *(test)*
2. `make ingest` over `evals/datasets/` ends with nine documents `indexed`,
   and `fan_passport_fan_45_scan.pdf` `failed` with the no-text-layer reason.
   *(manual)*
3. In the database, every chunk has a document, position and page, and every
   chunk of the nine indexed documents has a section. Each table-row chunk
   reads `<SKU>: <column> <value>; …` and holds one whole row. *(manual +
   test)*
4. Running `make ingest` again creates no new documents or chunks. *(manual +
   test)*
5. Stopping the worker while a document is `parsing`, then starting it
   again, ends the document `indexed` with one set of chunks. *(manual)*
6. Optional: `make ingest dir=data/bulk` finishes. Its results are reviewed
   by hand and don't gate the step. *(manual)*

The README's Usage section shows an upload, `make ingest` and the bulk
directory.

## Open questions

None.
