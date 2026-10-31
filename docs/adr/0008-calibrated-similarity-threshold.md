# Vector search keeps chunks above a calibrated similarity threshold

**Status:** accepted

Vector search always returns the nearest chunks, even for a question the
documents don't answer: "How do I renew my car insurance?" finds a warranty
section at a similarity of 0.794. So search
([06](../specs/06-embeddings-and-search.md)) drops vector results whose cosine
similarity is below `SEARCH_MIN_SIMILARITY`, 0.795. The value is calibrated on
the evaluation set with `intfloat/multilingual-e5-base`: above the highest
unrelated query (0.794, English) and below the lowest answer to a question
about a characteristic (0.798, Russian). Keyword search has no threshold, and
neither does a job's context.

## Considered options

- **No threshold, top-k only.** Every query returns k chunks, so a caller
  can't tell "nothing found" from "found".
- **A round value such as 0.8.** Not anchored to anything: e5 scores
  unrelated text 0.74–0.79, so the right value depends on the documents and
  differs by hundredths.
- **A threshold on the hybrid score.** Reciprocal rank fusion adds up ranks,
  not similarities; a cut on it says nothing about relevance.
- **A threshold for keyword search too.** `ts_rank` values don't compare
  between queries, and requiring every query word already filters.
- **Calibrated on a reference set.** The evaluation measures, per language,
  the highest similarity of an unrelated query and the lowest of an answer;
  the threshold goes in the window both languages share.

## Consequences

- The window is 0.004 wide. A new document set, language or embedding model
  needs a new calibration: `make eval-search` reports the window.
- A SKU inside a multi-row chunk can score below the threshold (`FAN-50` at
  0.790). Hybrid search still finds it through keyword search, which is why
  hybrid is the default mode.
- A job's context turns the threshold off: the user chose the documents, and
  a section such as "Package contents" looks nothing like the product name
  the query is built from.
- The evaluation measures similarities with the threshold off, so its report
  shows where answers and noise really lie.
