-- Migration: create daily_predictions table for paper-trade prediction logging.
--
-- One row per (prediction_date, ticker, model_version_id). The dashboard
-- "Today" page (Phase D §5.1) will later flip decision_taken to 'taken' or
-- 'skipped' — until that lands the column stays NULL, which is expected.
--
-- Idempotent: safe to re-run.

CREATE TABLE IF NOT EXISTS daily_predictions (
    prediction_date  DATE        NOT NULL,
    ticker           VARCHAR     NOT NULL,
    model_version_id VARCHAR     NOT NULL,
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
    PRIMARY KEY (prediction_date, ticker, model_version_id)
);

CREATE INDEX IF NOT EXISTS idx_daily_predictions_date
    ON daily_predictions(prediction_date);

CREATE INDEX IF NOT EXISTS idx_daily_predictions_model
    ON daily_predictions(model_version_id);
