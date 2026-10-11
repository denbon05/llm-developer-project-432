-- migrate:up
ALTER TABLE documents DROP CONSTRAINT documents_status_check;
ALTER TABLE documents ADD CONSTRAINT documents_status_check CHECK (status IN (
    'pending', 'parsing', 'embedding', 'indexed', 'failed'));

-- migrate:down
-- Fails while a document is in embedding: that status has no older meaning.
ALTER TABLE documents DROP CONSTRAINT documents_status_check;
ALTER TABLE documents ADD CONSTRAINT documents_status_check CHECK (status IN (
    'pending', 'parsing', 'indexed', 'failed'));
