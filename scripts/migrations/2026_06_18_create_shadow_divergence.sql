-- Migration: shadow_divergence — one verdict row per (date, prod, shadow, cohort).
--
-- Module B (nightly) materializes the cheap ranking-divergence verdict computed
-- by src/evaluation/shadow_compare on already-stored daily_predictions scores.
-- This is NOT a scores table — the scores live in daily_predictions, keyed by
-- model_version_id. This caches the comparison so divergence-over-time is a
-- plain SELECT (feeds a future dashboard sparkline) without re-running the
-- self-join over history.
--
-- Idempotent: INSERT OR REPLACE on rerun of the same day.

CREATE TABLE IF NOT EXISTS shadow_divergence (
    prediction_date   DATE        NOT NULL,
    prod_version_id   VARCHAR     NOT NULL,
    shadow_version_id VARCHAR     NOT NULL,
    cohort            VARCHAR     NOT NULL DEFAULT 'breakout',
    n_common          INTEGER,
    spearman          DOUBLE,
    jaccard_at_10     DOUBLE,
    n_disagreements   INTEGER,
    computed_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (prediction_date, prod_version_id, shadow_version_id, cohort)
);

CREATE INDEX IF NOT EXISTS idx_shadow_divergence_date
    ON shadow_divergence(prediction_date);
