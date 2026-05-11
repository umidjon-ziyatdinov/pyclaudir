CREATE TABLE IF NOT EXISTS kb_ingestions (
    id           INTEGER PRIMARY KEY,
    source_url   TEXT    NOT NULL,
    content_hash TEXT    NOT NULL,
    ingested_at  DATETIME NOT NULL,
    source_type  TEXT    NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_kb_ingestions_url
    ON kb_ingestions (source_url);
