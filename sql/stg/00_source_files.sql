-- Lineage of the month's snapshot: one row per raw file a source was built from.
CREATE TABLE IF NOT EXISTS stg.source_files (
    snapshot_month DATE        NOT NULL,
    source         VARCHAR     NOT NULL,
    file           VARCHAR     NOT NULL,
    url            VARCHAR     NOT NULL,
    sha256         VARCHAR     NOT NULL,
    fetched_at     TIMESTAMPTZ NOT NULL,
    snapshot_rows  BIGINT      NOT NULL,  -- rows the source contributed to the snapshot
    period         VARCHAR               -- the latest period in the data, in the source's format;
                                         -- none when the source has no rows
);

DELETE FROM stg.source_files WHERE snapshot_month = getvariable('snapshot_month');

INSERT INTO stg.source_files
SELECT
    getvariable('snapshot_month'),
    manifest.source::VARCHAR,
    raw.file::VARCHAR,
    raw.url::VARCHAR,
    raw.sha256::VARCHAR,
    raw.fetched_at::TIMESTAMPTZ,
    manifest.rows::BIGINT,
    manifest.period::VARCHAR
FROM read_json('*.json') AS manifest, unnest(manifest.files) AS t(raw);
