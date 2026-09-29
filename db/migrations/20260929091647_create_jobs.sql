-- migrate:up
CREATE TABLE jobs (
    id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    idempotency_key  text UNIQUE,
    request_hash     text NOT NULL,
    status           text NOT NULL DEFAULT 'pending' CHECK (status IN (
                        'pending', 'extracting', 'generating', 'critiquing',
                        'awaiting_approval', 'needs_review',
                        'approved', 'rejected', 'failed')),
    payload          jsonb NOT NULL,
    result           jsonb,
    critique_issues  jsonb NOT NULL DEFAULT '[]',
    attempts         integer NOT NULL DEFAULT 0,
    error            text,
    decision_reason  text,
    created_at       timestamptz NOT NULL DEFAULT now(),
    updated_at       timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX jobs_status_updated_at_idx ON jobs (status, updated_at);

-- migrate:down
DROP TABLE IF EXISTS jobs;
