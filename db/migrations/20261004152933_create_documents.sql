-- migrate:up
CREATE TABLE documents (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    filename        text NOT NULL,
    format          text NOT NULL CHECK (format IN ('pdf', 'docx', 'xlsx')),
    size_bytes      integer NOT NULL,
    content_sha256  text NOT NULL UNIQUE,
    content         bytea NOT NULL,
    status          text NOT NULL DEFAULT 'pending' CHECK (status IN (
                        'pending', 'parsing', 'indexed', 'failed')),
    error           text,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX documents_status_updated_at_idx ON documents (status, updated_at);

-- migrate:down
DROP TABLE IF EXISTS documents;
