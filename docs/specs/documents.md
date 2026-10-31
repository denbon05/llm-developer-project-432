# Documents

## Purpose

Turns an uploaded supplier document (PDF, DOCX, XLSX) into chunks: normalised
text with the metadata search filters on and citations point to. A document
that yields no chunk ends `failed` with a reason, never `indexed` and empty.

## Contracts

| Method and path | Success | Errors |
|-----------------|---------|--------|
| `POST /api/v1/documents` (multipart `file`) | `202 {"id", "status"}` | `413` · `415` · `422` · `503` |
| `GET /api/v1/documents/{id}` | `200` document view | `404 document not found` |

- **View:** `id`, `filename`, `format`, `size_bytes`, `status`, `error`,
  `chunk_count` (computed on read), timestamps; never the file.
- **Upload checks**, in order: name ≤ 255 characters (422 `file name is
  longer than 255 characters`); extension `.pdf`, `.docx` or `.xlsx`, any
  case, which sets `format` (415 `unsupported file type: accepted are pdf,
  docx and xlsx`); size ≤ `DOCUMENT_MAX_SIZE_BYTES` (413 `file is larger than
  10 MiB`); not empty (422 `file is empty`); magic bytes `%PDF-` or ZIP
  `PK\x03\x04` (415). The name is for display only, never a path.
- **Identity:** the SHA-256 of the bytes. The same bytes again, concurrently
  or under another name, return the stored document; the first name stays.
- **Storage** ([ADR 0004](../adr/0004-uploaded-files-in-postgres.md)):
  `documents` holds `filename`, `format`, `size_bytes`, `content_sha256`
  (unique), `content` (`bytea`), `status` (CHECK, indexed with `updated_at`),
  `error`; `chunks` holds `document_id` (indexed, cascade delete), `text`,
  `metadata` (`jsonb`) and the [search columns](search.md#storage).

| Metadata key | On | Value |
|--------------|----|-------|
| `position` | every chunk | 0, 1, 2… in reading order, without gaps |
| `kind` | every chunk | `text` or `table_row` |
| `page` | every chunk | PDF page, approximate DOCX page, or XLSX sheet position from 1 |
| `section` | every chunk | the heading above it, or the sheet name; null without headings |
| `row` | `table_row` | the row a person sees; the header row is 1 |
| `sku`, `brand` | `table_row` with such a column | the cell's value |

- **Workflow** `DocumentIngestionWorkflow`, ID `document-{document_id}`, on
  `TEMPORAL_DOCUMENT_TASK_QUEUE`, input the document id (never the file):

| Activity | Does | Start-to-close | Attempts |
|----------|------|----------------|----------|
| `record_document_status` | writes the status; the only code that does | 10 s | 5 |
| `chunk_document` | parses, normalises, chunks, replaces the chunks | 5 min | 3 |
| `embed_document` | computes missing vectors ([search](search.md#embedding)) | 5 min | 3 |

- Retries start at 2 s with backoff 2. Not retried: `UnreadableDocumentError`
  (the same file fails the same way), `DocumentNotFoundError`,
  `InvalidDocumentTransitionError`.
- **Failure reasons** in `error`: `the file is not a readable PDF` (`DOCX`,
  `XLSX`; encrypted PDFs too), `the PDF has no text layer; it may be a scan,
  and OCR is not supported`, `the archive unpacks to more than 100 MiB`,
  `the document contains no text`, another error of ours, or `internal error`.

## Behaviour

### Ingestion

`pending ─▶ parsing ─▶ embedding ─▶ indexed`, any non-terminal `─▶ failed`.
Writes follow the arrows; the current status again is a no-op.

1. The upload inserts the row (`ON CONFLICT (content_sha256) DO NOTHING`) and
   starts the workflow while the document is `pending`.
2. `chunk_document` reads the file in one database operation, parses in
   `asyncio.to_thread` holding no connection, and replaces the chunks in one
   transaction, so a retry leaves one set.
3. A DOCX or XLSX whose central directory lists more than 100 MiB unpacked is
   refused before anything is unpacked (a ZIP bomb).
4. A document is ingested once; ingesting it again is not supported.

### Parsing

- **PDF** (pdfplumber): words on one baseline form a line, so a table row
  stays whole. A heading is all bold, larger than the most common line size.
  No page with text means a scan.
- **DOCX** (python-docx): body paragraphs and tables in order; no headers,
  footers or blank paragraphs. Headings: styles `Title`, `Heading 1`–`9`.
  Page: 1 plus earlier page breaks, Word's rendered breaks when present. A
  table's first row is its header; a merged cell repeats in each column.
- **XLSX** (openpyxl): visible sheets; the first non-empty row is the header
  and empty leading columns are skipped; whole numbers lose `.0`, dates
  become ISO, formulas give saved values.
- **Sections** (PDF, DOCX): consecutive headings form one group named by the
  last (`PRODUCT PASSPORT`, `VentBriz 40 Fan`). Headings stay in the text, so
  a product name set as one stays searchable; headings alone make no chunk.
  Text before the first heading joins the first section.
- Not supported: OCR, `.doc`, `.xls`, multi-row headers, nested tables, text
  boxes, footnotes, comments.

### Normalisation

1. Ligatures expanded; NFC, not NFKC, which would turn `m²` into `m2`; soft
   hyphens and zero-width characters removed (cells and section names too).
2. Whitespace collapsed, lines trimmed, empty lines dropped.
3. **Running headers**, in PDFs of two or more pages: a line among a page's
   first or last three, with digits masked, found on at least two pages and
   half the pages with text, is removed at page edges. "At least two"
   protects a two-page document.
4. **Hyphenation:** a line ending in a letter or digit and `-` joins the next;
   the hyphen goes before a lowercase letter in any alphabet (`мощ-` +
   `ность`) and stays otherwise (`FAN-` + `40`).

### Chunking

- **Text:** chunks of at most 1,200 characters, cut at the last line break,
  sentence end or space past the window's first 150 characters; the next
  chunk starts 150 characters back, at a word. Sized for a 512-token
  embedding model; constants, because changing them means ingesting
  everything again. A chunk never crosses a page or section.
- **Table rows:** one chunk per row, however long:
  `<key>: <column> <value>; …`, keyed by the SKU column, else the first;
  empty cells skipped; a header `<name>, <unit>` with a one-word unit moves
  the unit after the value (`Power, W` and `40` give `Power 40 W`).
- **SKU and brand headers**, ignoring case and a trailing `.` or `:`:
  `SKU`, `Article`, `Art. No`, `Артикул`, `Арт`; `Brand`, `Trademark`,
  `Бренд`, `Марка`, `Торговая марка`.
- A chunk repeating an earlier chunk's text in the same document is dropped;
  copies in other documents stay, each citing its own.

`make ingest [dir=…]` (default `evals/datasets`) uploads a directory to the
running API, waits up to 10 minutes per document, prints status, chunks and
time, and exits 1 only if a request failed or a document didn't finish.

## Failures

- **Temporal unreachable at upload:** 503; the row stays `pending` until the
  same file is uploaded again.
- **Worker lost mid-activity:** one attempt spent; chunks are all or nothing.
- **`embed_document` fails for good:** `failed`; search ignores the document.
