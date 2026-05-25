"""One-shot verification for model card prerequisites (§5.1) — round 2."""

import duckdb
from pathlib import Path

DB = Path(__file__).resolve().parent.parent / "data" / "market_data.duckdb"

def run_check(con, title: str, sql: str):
    print(f"\n{'='*70}\n{title}\n{'='*70}", flush=True)
    print(sql.strip(), flush=True)
    try:
        df = con.execute(sql).fetchdf()
        print("\nResult:", flush=True)
        print(df.to_string(index=False), flush=True)
        return df
    except Exception as e:
        print(f"\nFAIL: {e}", flush=True)
        return None


def main():
    con = duckdb.connect(str(DB), read_only=True)

    # A. Find actual "trend" / C-criteria columns in t3_sepa_features
    run_check(
        con,
        "A. t3_sepa_features columns matching trend/c1/c2/c6/sepa criteria",
        """
        SELECT column_name, data_type
        FROM information_schema.columns
        WHERE table_name = 't3_sepa_features'
          AND (
            column_name ILIKE '%trend%'
            OR column_name ILIKE 'c1%'
            OR column_name ILIKE 'c2%'
            OR column_name ILIKE 'c3%'
            OR column_name ILIKE 'c6%'
            OR column_name ILIKE 'c8%'
            OR column_name ILIKE 'c9%'
            OR column_name ILIKE 'c11%'
            OR column_name ILIKE '%_ok'
            OR column_name ILIKE 'breakout%'
            OR column_name ILIKE 'sepa%'
          )
        ORDER BY column_name
        """,
    )

    # B. Same scan against daily_features
    run_check(
        con,
        "B. daily_features columns matching trend/c1/c2/c6 criteria",
        """
        SELECT column_name, data_type
        FROM information_schema.columns
        WHERE table_name = 'daily_features'
          AND (
            column_name ILIKE '%trend%'
            OR column_name ILIKE 'c1%'
            OR column_name ILIKE 'c2%'
            OR column_name ILIKE 'c6%'
            OR column_name ILIKE '%_ok'
            OR column_name ILIKE 'sma%'
          )
        ORDER BY column_name
        LIMIT 50
        """,
    )

    # C. Use trend_ok (the candidate from previous error) to size the active pool
    run_check(
        con,
        "C. Active pool size using trend_ok on most recent date",
        """
        WITH last_date AS (
          SELECT MAX(date) AS d FROM t3_sepa_features WHERE feature_version='v3.1'
        )
        SELECT
          (SELECT d FROM last_date) AS date,
          COUNT(*) AS rows_on_date,
          SUM(CASE WHEN trend_ok = TRUE THEN 1 ELSE 0 END) AS trend_ok_rows
        FROM t3_sepa_features
        WHERE feature_version='v3.1'
          AND date = (SELECT d FROM last_date)
        """,
    )

    # D. Home-run prevalence on the SEPA universe (d2 cache, mfe_pct > 30)
    run_check(
        con,
        "D. Home-run prevalence in d2_training_cache (mfe_pct > 30)",
        """
        SELECT
          COUNT(*) AS total_rows,
          SUM(CASE WHEN mfe_pct > 30 THEN 1 ELSE 0 END) AS homerun_rows,
          ROUND(100.0 * SUM(CASE WHEN mfe_pct > 30 THEN 1 ELSE 0 END) / COUNT(*), 2) AS homerun_pct,
          ROUND(MIN(date)::VARCHAR, 0) AS min_date,
          ROUND(MAX(date)::VARCHAR, 0) AS max_date
        FROM d2_training_cache
        """,
    )

    # E. v_d2_training row counts to investigate 38122 (mfe_pct populated 100%, but only 38k rows total — seems low for 25yr SEPA universe)
    run_check(
        con,
        "E. v_d2_training row distribution by year",
        """
        SELECT EXTRACT(YEAR FROM date) AS year, COUNT(*) AS rows
        FROM v_d2_training
        WHERE feature_version='v3.1'
        GROUP BY year ORDER BY year
        """,
    )

    # F. t2_regime_scores schema
    run_check(
        con,
        "F. t2_regime_scores schema",
        """
        SELECT column_name, data_type
        FROM information_schema.columns
        WHERE table_name = 't2_regime_scores'
        ORDER BY ordinal_position
        """,
    )

    # G. t2_risk_scores schema (the 5-factor model)
    run_check(
        con,
        "G. t2_risk_scores schema",
        """
        SELECT column_name, data_type
        FROM information_schema.columns
        WHERE table_name = 't2_risk_scores'
        ORDER BY ordinal_position
        """,
    )

    # H. M03 / regime columns in any view (not just daily_features)
    run_check(
        con,
        "H. m03 / regime columns across ALL tables and views",
        """
        SELECT table_name, column_name
        FROM information_schema.columns
        WHERE column_name ILIKE 'm03%'
           OR column_name ILIKE '%regime%'
        ORDER BY table_name, column_name
        """,
    )

    # I. Sample t2_risk_scores values to see if it's a continuous score or discrete buckets
    run_check(
        con,
        "I. t2_risk_scores sample values (5 most recent rows)",
        """
        SELECT * FROM t2_risk_scores ORDER BY date DESC LIMIT 5
        """,
    )

    # J. v_d2_training schema — ALL columns (we only filtered to 7 earlier)
    run_check(
        con,
        "J. v_d2_training all columns",
        """
        SELECT column_name, data_type
        FROM information_schema.columns
        WHERE table_name = 'v_d2_training'
        ORDER BY ordinal_position
        """,
    )

    con.close()


if __name__ == "__main__":
    main()
