-- migrate:up
-- One row per model reply. Money is numeric, never a float: a token costs a
-- fraction of a cent, and numeric without a scale keeps the exact product.
CREATE TABLE llm_calls (
    id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id             uuid REFERENCES jobs (id),
    request_id         text,
    purpose            text NOT NULL CHECK (purpose IN (
                           'extract', 'generate', 'critique', 'judge')),
    model              text NOT NULL,
    prompt_tokens      integer,
    completion_tokens  integer,
    cost_usd           numeric,
    latency_ms         integer NOT NULL,
    created_at         timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX llm_calls_job_id_idx ON llm_calls (job_id);
CREATE INDEX llm_calls_created_at_idx ON llm_calls (created_at);

-- migrate:down
DROP TABLE IF EXISTS llm_calls;
