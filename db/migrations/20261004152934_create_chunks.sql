-- migrate:up
CREATE TABLE chunks (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id  uuid NOT NULL REFERENCES documents (id) ON DELETE CASCADE,
    text         text NOT NULL,
    metadata     jsonb NOT NULL
);
CREATE INDEX chunks_document_id_idx ON chunks (document_id);

-- migrate:down
DROP TABLE IF EXISTS chunks;
