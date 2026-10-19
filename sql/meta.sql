CREATE SCHEMA IF NOT EXISTS meta;

CREATE TABLE IF NOT EXISTS meta.pipeline_runs (  -- this build's runs, one per month
    run_id         VARCHAR PRIMARY KEY,
    snapshot_month DATE        NOT NULL,  -- first day of the month
    git_sha        VARCHAR     NOT NULL,
    started_at     TIMESTAMPTZ NOT NULL,
    finished_at    TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS meta.dq_results (
    run_id       VARCHAR     NOT NULL,
    check_name   VARCHAR     NOT NULL,
    layer        VARCHAR     NOT NULL,
    severity     VARCHAR     NOT NULL,  -- error blocks publishing, warn is reported only
    failing_rows BIGINT      NOT NULL,
    sample       VARCHAR,               -- JSON array of the first failing rows
    PRIMARY KEY (run_id, check_name)
);
