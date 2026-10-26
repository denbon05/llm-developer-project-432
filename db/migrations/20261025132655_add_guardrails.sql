-- migrate:up
-- What masking, the injection check and the leak check did for the job.
-- NULL until the job writes it; each activity merges its own keys in.
ALTER TABLE jobs ADD COLUMN guard_report jsonb;
ALTER TABLE llm_calls DROP CONSTRAINT llm_calls_purpose_check;
ALTER TABLE llm_calls ADD CONSTRAINT llm_calls_purpose_check CHECK (purpose IN (
    'extract', 'generate', 'critique', 'detect_injection', 'judge'));

-- migrate:down
-- Fails while the ledger has detect_injection calls: that purpose has no
-- older meaning.
ALTER TABLE llm_calls DROP CONSTRAINT llm_calls_purpose_check;
ALTER TABLE llm_calls ADD CONSTRAINT llm_calls_purpose_check CHECK (purpose IN (
    'extract', 'generate', 'critique', 'judge'));
ALTER TABLE jobs DROP COLUMN IF EXISTS guard_report;
