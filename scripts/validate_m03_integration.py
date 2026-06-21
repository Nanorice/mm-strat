"""
Validate M03 Integration in FeaturePipeline

This script validates that the FeaturePipeline correctly reads M03 scores
from t2_regime_scores table (DuckDB v2 architecture).
"""

import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))

import duckdb
import pandas as pd
from src.feature_pipeline import FeaturePipeline

DB_PATH = 'data/market_data.duckdb'


def validate_m03_integration():
    """
    Validate that M03 features are correctly joined from t2_regime_scores table.
    """
    print("=" * 60)
    print("VALIDATING M03 INTEGRATION IN FEATURE PIPELINE")
    print("=" * 60)

    # Step 1: Check t2_regime_scores table
    print("\n[1] Checking t2_regime_scores table...")
    con = duckdb.connect(DB_PATH)

    try:
        regime_count = con.execute("SELECT COUNT(*) FROM t2_regime_scores").fetchone()[0]
        print(f"   [OK] t2_regime_scores: {regime_count:,} rows")

        regime_sample = con.execute("""
            SELECT date, m03_score, m03_pillar_trend, m03_delta_5d
            FROM t2_regime_scores
            ORDER BY date DESC
            LIMIT 5
        """).df()
        print(f"   Sample (latest 5 dates):")
        print(regime_sample.to_string(index=False))

    finally:
        con.close()

    # Step 2: Check daily_features before M03 update
    print("\n[2] Checking daily_features M03 columns before update...")
    con = duckdb.connect(DB_PATH)

    try:
        # Check if M03 columns exist
        cols = {r[0] for r in con.execute("DESCRIBE daily_features").fetchall()}
        m03_cols = ['m03_score', 'm03_pillar_trend', 'm03_pillar_liq',
                    'm03_pillar_risk', 'm03_delta_5d', 'm03_delta_20d', 'm03_regime_vol']

        existing_m03 = [c for c in m03_cols if c in cols]
        print(f"   M03 columns in daily_features: {len(existing_m03)}/{len(m03_cols)}")

        if existing_m03:
            null_counts = con.execute(f"""
                SELECT
                    COUNT(*) as total_rows,
                    COUNT(m03_score) as non_null_m03
                FROM daily_features
            """).fetchone()
            print(f"   Rows with M03 data: {null_counts[1]:,} / {null_counts[0]:,}")

    finally:
        con.close()

    # Step 3: Run FeaturePipeline M03 phases
    print("\n[3] Running FeaturePipeline M03 phases...")
    pipeline = FeaturePipeline(db_path=DB_PATH)

    try:
        # Run Phase D: M03 base features
        pipeline.compute_m03_features()

        # Run Phase E: M03 derived features
        pipeline.compute_m03_derived()

        print("   [OK] M03 phases completed")

    except Exception as e:
        print(f"   [FAIL] M03 phases failed: {e}")
        raise

    # Step 4: Validate results in daily_features
    print("\n[4] Validating daily_features M03 values...")
    con = duckdb.connect(DB_PATH)

    try:
        # Check row counts
        validation = con.execute("""
            SELECT
                COUNT(*) as total_rows,
                COUNT(m03_score) as non_null_base,
                COUNT(m03_delta_5d) as non_null_derived,
                MIN(m03_score) as min_score,
                MAX(m03_score) as max_score,
                AVG(m03_score) as avg_score
            FROM daily_features
        """).fetchone()

        print(f"   Total rows: {validation[0]:,}")
        print(f"   Rows with M03 base: {validation[1]:,}")
        print(f"   Rows with M03 derived: {validation[2]:,}")
        print(f"   Score range: {validation[3]:.4f} to {validation[4]:.4f} (avg: {validation[5]:.4f})")

        # Sample comparison
        print("\n   Sample comparison (10 random dates):")
        comparison = con.execute("""
            SELECT
                df.date,
                df.ticker,
                df.m03_score as df_score,
                r.m03_score / 100.0 as regime_score,
                ABS(df.m03_score - r.m03_score / 100.0) as variance
            FROM daily_features df
            JOIN t2_regime_scores r ON df.date = r.date
            WHERE df.m03_score IS NOT NULL
            ORDER BY RANDOM()
            LIMIT 10
        """).df()

        print(comparison.to_string(index=False))

        max_variance = comparison['variance'].max()
        if max_variance < 0.001:
            print(f"\n   [OK] VALIDATION PASSED: max variance = {max_variance:.6f}")
        else:
            print(f"\n   [FAIL] VALIDATION FAILED: max variance = {max_variance:.6f}")

    finally:
        con.close()

    print("\n" + "=" * 60)
    print("VALIDATION COMPLETE")
    print("=" * 60)


if __name__ == '__main__':
    validate_m03_integration()
