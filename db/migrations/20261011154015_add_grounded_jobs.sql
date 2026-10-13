-- migrate:up
ALTER TABLE jobs DROP CONSTRAINT jobs_status_check;
ALTER TABLE jobs ADD CONSTRAINT jobs_status_check CHECK (status IN (
    'pending', 'extracting', 'retrieving', 'generating', 'critiquing',
    'awaiting_approval', 'needs_review', 'approved', 'rejected', 'failed'));
-- A document job's context as chunk ids in label order (S1 first). Text and
-- metadata are read through a join: indexed chunks never change.
ALTER TABLE jobs ADD COLUMN context_chunk_ids uuid[] NOT NULL DEFAULT '{}';

-- migrate:down
-- Fails while a job is in retrieving: that status has no older meaning.
ALTER TABLE jobs DROP COLUMN IF EXISTS context_chunk_ids;
ALTER TABLE jobs DROP CONSTRAINT jobs_status_check;
ALTER TABLE jobs ADD CONSTRAINT jobs_status_check CHECK (status IN (
    'pending', 'extracting', 'generating', 'critiquing',
    'awaiting_approval', 'needs_review', 'approved', 'rejected', 'failed'));
