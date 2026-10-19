CREATE SCHEMA IF NOT EXISTS meta;

CREATE TABLE IF NOT EXISTS meta.pipeline_runs (  -- this build's runs, one per month
    run_id         VARCHAR PRIMARY KEY,
    snapshot_month DATE        NOT NULL,  -- first day of the month
    git_sha        VARCHAR     NOT NULL,
    started_at     TIMESTAMPTZ NOT NULL,
    finished_at    TIMESTAMPTZ NOT NULL
);
