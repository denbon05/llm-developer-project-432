-- migrate:up
-- An HNSW index needs a fixed vector length: another dimension needs a
-- migration. The model and passage prefix that made a vector are written with
-- it, so search and reindex can tell old vectors from current ones.
ALTER TABLE chunks
    ADD COLUMN embedding vector(768),
    ADD COLUMN embedding_model text,
    ADD COLUMN embedding_prefix text,
    -- 'russian' stems Cyrillic words by Russian rules and Latin words by
    -- English ones, so one column serves both languages.
    ADD COLUMN tsv tsvector
        GENERATED ALWAYS AS (to_tsvector('russian', text)) STORED;
-- An index serves one distance: queries must use <=>, cosine distance.
CREATE INDEX chunks_embedding_idx ON chunks
    USING hnsw (embedding vector_cosine_ops);
CREATE INDEX chunks_tsv_idx ON chunks USING gin (tsv);

-- migrate:down
DROP INDEX IF EXISTS chunks_tsv_idx;
DROP INDEX IF EXISTS chunks_embedding_idx;
ALTER TABLE chunks
    DROP COLUMN IF EXISTS tsv,
    DROP COLUMN IF EXISTS embedding_prefix,
    DROP COLUMN IF EXISTS embedding_model,
    DROP COLUMN IF EXISTS embedding;
