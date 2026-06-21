-- Migration: add `cohort` to daily_predictions and fold it into the PK.
--
-- A ticker can now be scored under two cohorts on the same day:
--   'breakout'      — SEPA breakout entries  (v_d3_deployment, breakout_ok=TRUE)
--   'pre_breakout'  — in-setup names         (trend_ok=TRUE AND breakout_ok=FALSE)
-- Both are written under the prod model_version_id. To keep one row per
-- (date, ticker, model, cohort) and let INSERT OR REPLACE overwrite on rerun,
-- `cohort` must be part of the primary key.
--
-- DuckDB cannot ALTER a primary key in place, so we rebuild the table when the
-- column is absent. Existing rows are pre-cohort breakout scores → backfilled
-- to 'breakout'. Idempotent: the rebuild only runs when `cohort` is missing.

CREATE TABLE IF NOT EXISTS daily_predictions (
    prediction_date  DATE        NOT NULL,
    ticker           VARCHAR     NOT NULL,
    model_version_id VARCHAR     NOT NULL,
    cohort           VARCHAR     NOT NULL DEFAULT 'breakout',
    prob_class_0     DOUBLE,
    prob_class_1     DOUBLE,
    prob_class_2     DOUBLE,
    prob_class_3     DOUBLE,
    predicted_class  INTEGER,
    rank_within_day  INTEGER,
    decision_taken   VARCHAR DEFAULT NULL,
    taken_at         TIMESTAMP DEFAULT NULL,
    notes            VARCHAR DEFAULT NULL,
    ingested_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (prediction_date, ticker, model_version_id, cohort)
);

CREATE INDEX IF NOT EXISTS idx_daily_predictions_date
    ON daily_predictions(prediction_date);

CREATE INDEX IF NOT EXISTS idx_daily_predictions_model
    ON daily_predictions(model_version_id);

CREATE INDEX IF NOT EXISTS idx_daily_predictions_cohort
    ON daily_predictions(cohort);
