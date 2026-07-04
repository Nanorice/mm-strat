"""M02 signal-quality gate (prod-gap plan Phase 0.1) — go/no-go before the trade build.

Three analyses, ALL on out-of-sample scores (WF fold models score their own test
windows; the final model scores only dates after its train_end):

  (a) lead time     — for names that later enter sepa_watchlist, how many days earlier
                      did M02 first put them in the daily top decile? Plus 21d forward
                      return from the M02 signal date vs the M01 entry date.
  (b) decile gradient — daily score deciles vs 5/10/21d forward returns (from price_data,
                      never t3) + ignition-event rate per decile. The direct test that
                      the score predicts RETURNS, not just the scanner event.
  (c) top-50 turnover — day-over-day overlap of the top-50 list + unique-name precision,
                      so we know what the WF P@50 ≈ 50% actually means.

Usage:
    .venv/Scripts/python.exe scripts/analyze_m02_signal_quality.py --smoke   # path test
    .venv/Scripts/python.exe scripts/analyze_m02_signal_quality.py          # full

Output: <wf-run>/oos_score_panel.parquet (cached; delete to rebuild) and a markdown
report at docs/session_logs/sprint_13/m02_signal_quality_report.md.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import duckdb
import numpy as np
import pandas as pd
import xgboost as xgb

from config import DUCKDB_PATH
from scripts.train_breakout_model import HORIZON, _prep_cat, load_matrix

WF_RUN = Path("models/m02_breakout/20260629_203134")
FINAL_RUN = Path("models/m02_breakout/final_20260704_175544")
REPORT = Path("docs/session_logs/sprint_13/m02_signal_quality_report.md")
TOP_DECILE = 0.9
LEAD_LOOKBACK_DAYS = 60
FWD_HORIZONS = (5, 10, 21)


def build_oos_panel(wf_run: Path, final_run: Path, db: str, smoke: bool) -> pd.DataFrame:
    """Concatenate fold-model predictions on their OOS test windows + final-model
    predictions on the post-train_end tail. Every score is out-of-sample."""
    cache = wf_run / ("oos_score_panel_smoke.parquet" if smoke else "oos_score_panel.parquet")
    if cache.exists():
        print(f"OOS panel: cached -> {cache}", flush=True)
        return pd.read_parquet(cache)

    meta = json.loads((final_run / "metadata.json").read_text())
    feats: list[str] = meta["features"]
    folds = json.loads((wf_run / "summary.json").read_text())["folds"]

    df, _ = load_matrix(db, feats, smoke)
    df["date"] = pd.to_datetime(df["date"])
    X = _prep_cat(df[feats])
    print(f"matrix loaded: {len(df):,} rows", flush=True)

    parts: list[pd.DataFrame] = []
    for f in folds:
        booster = xgb.Booster()
        booster.load_model(str(wf_run / f"fold_{f['fold']:02d}_model.json"))
        # half-open [start, end): fold specs share their boundary day
        m = (df["date"] >= f["test_start"]) & (df["date"] < f["test_end"])
        if not m.any():
            continue
        pred = booster.predict(xgb.DMatrix(X[m], enable_categorical=True))
        parts.append(pd.DataFrame({
            "date": df.loc[m, "date"].values, "ticker": df.loc[m, "ticker"].values,
            "score": np.clip(pred, 0.0, 1.0), "source": f"fold_{f['fold']:02d}",
        }))
        print(f"  fold {f['fold']}: {m.sum():,} rows [{f['test_start']}..{f['test_end']}]", flush=True)

    tail = df["date"] > pd.Timestamp(meta["train_end"])
    if tail.any():
        booster = xgb.Booster()
        booster.load_model(str(final_run / "model.json"))
        pred = booster.predict(xgb.DMatrix(X[tail], enable_categorical=True))
        parts.append(pd.DataFrame({
            "date": df.loc[tail, "date"].values, "ticker": df.loc[tail, "ticker"].values,
            "score": np.clip(pred, 0.0, 1.0), "source": "final_tail",
        }))
        print(f"  final tail: {tail.sum():,} rows (> {meta['train_end']})", flush=True)

    panel = pd.concat(parts, ignore_index=True)
    assert not panel.duplicated(subset=["date", "ticker"]).any(), "fold windows overlap"
    panel.to_parquet(cache, index=False)
    print(f"OOS panel -> {cache}  rows={len(panel):,} days={panel['date'].nunique()}", flush=True)
    return panel


def _sql(con: duckdb.DuckDBPyConnection, panel_path: str) -> None:
    """Register OOS panel + per-row rank pct, forward returns, event labels as views."""
    con.execute(f"""
        CREATE OR REPLACE TEMP VIEW oos AS
        SELECT ticker, CAST(date AS DATE) AS date, score,
               PERCENT_RANK() OVER (PARTITION BY date ORDER BY score) AS rank_pct,
               NTILE(10) OVER (PARTITION BY date ORDER BY score) AS decile
        FROM read_parquet('{panel_path}')
    """)
    leads = ", ".join(
        f"LEAD(close, {h}) OVER w / NULLIF(close, 0) - 1 AS fwd_{h}d" for h in FWD_HORIZONS)
    con.execute(f"""
        CREATE OR REPLACE TEMP VIEW fwd AS
        SELECT ticker, date, {leads}
        FROM price_data
        WHERE date >= (SELECT MIN(date) FROM oos) AND close > 0
        WINDOW w AS (PARTITION BY ticker ORDER BY date)
    """)
    con.execute("""
        CREATE OR REPLACE TEMP VIEW oos_full AS
        SELECT o.*, f.fwd_5d, f.fwd_10d, f.fwd_21d,
               (t.days_to_breakout IS NOT NULL AND t.days_to_breakout <= 60) AS ignites_60d
        FROM oos o
        LEFT JOIN fwd f USING (ticker, date)
        LEFT JOIN m02_breakout_targets t USING (ticker, date)
    """)


def analyze_lead_time(con: duckdb.DuckDBPyConnection) -> dict:
    """(a) For each watchlist entry inside the OOS span: first top-decile M02 signal in
    the prior 60 calendar days, its lead time, and 21d fwd return from both dates."""
    df = con.execute(f"""
        WITH entries AS (
            SELECT w.ticker, w.entry_date, w.trend_ok AND w.breakout_ok AS quality
            FROM sepa_watchlist w
            WHERE w.entry_date BETWEEN (SELECT MIN(date) + INTERVAL {LEAD_LOOKBACK_DAYS} DAY FROM oos)
                                   AND (SELECT MAX(date) FROM oos)
              AND w.ticker IN (SELECT DISTINCT ticker FROM oos)
        ),
        first_signal AS (
            SELECT e.ticker, e.entry_date, e.quality, MIN(o.date) AS signal_date
            FROM entries e
            LEFT JOIN oos o
              ON o.ticker = e.ticker
             AND o.date >= e.entry_date - INTERVAL {LEAD_LOOKBACK_DAYS} DAY
             AND o.date < e.entry_date
             AND o.rank_pct >= {TOP_DECILE}
            GROUP BY 1, 2, 3
        )
        SELECT fs.*, DATEDIFF('day', fs.signal_date, fs.entry_date) AS lead_days,
               fsig.fwd_21d AS fwd21_from_signal, fent.fwd_21d AS fwd21_from_entry
        FROM first_signal fs
        LEFT JOIN fwd fsig ON fsig.ticker = fs.ticker AND fsig.date = fs.signal_date
        LEFT JOIN fwd fent ON fent.ticker = fs.ticker AND fent.date = fs.entry_date
    """).df()

    got = df.dropna(subset=["lead_days"])
    out = {
        "n_entries": len(df),
        "n_with_signal": len(got),
        "coverage": len(got) / len(df) if len(df) else float("nan"),
        "lead_median": got["lead_days"].median(),
        "lead_q25": got["lead_days"].quantile(0.25),
        "lead_q75": got["lead_days"].quantile(0.75),
        "fwd21_from_signal_mean": got["fwd21_from_signal"].mean(),
        "fwd21_from_entry_mean": got["fwd21_from_entry"].mean(),
        "quality_coverage": (
            got["quality"].fillna(False).sum() / max(1, int(df["quality"].fillna(False).sum()))),
    }
    return out


def analyze_deciles(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """(b) Mean forward return + ignition rate per daily score decile."""
    return con.execute("""
        SELECT decile,
               COUNT(*) AS n,
               AVG(fwd_5d)  AS fwd_5d,
               AVG(fwd_10d) AS fwd_10d,
               AVG(fwd_21d) AS fwd_21d,
               AVG(CASE WHEN ignites_60d THEN 1.0 ELSE 0.0 END) AS ignition_rate
        FROM oos_full
        GROUP BY decile ORDER BY decile
    """).df()


def analyze_turnover(con: duckdb.DuckDBPyConnection) -> dict:
    """(c) Day-over-day overlap of the daily top-50 + unique-name precision at the
    FIRST top-50 appearance (deduplicated view of what P@50 counts daily)."""
    top = con.execute("""
        SELECT date, ticker, ignites_60d FROM (
            SELECT date, ticker, ignites_60d,
                   ROW_NUMBER() OVER (PARTITION BY date ORDER BY score DESC) AS rn
            FROM oos_full)
        WHERE rn <= 50 ORDER BY date
    """).df()

    sets = top.groupby("date")["ticker"].agg(set).sort_index()
    overlaps = [len(a & b) / 50 for a, b in zip(sets.iloc[:-1], sets.iloc[1:])]
    first = top.drop_duplicates(subset="ticker", keep="first")
    return {
        "n_days": len(sets),
        "overlap_mean": float(np.mean(overlaps)) if overlaps else float("nan"),
        "unique_names": len(first),
        "unique_precision": float(first["ignites_60d"].fillna(False).mean()),
    }


def write_report(lead: dict, dec: pd.DataFrame, turn: dict, n_panel: int, smoke: bool) -> None:
    spread = dec["fwd_21d"].iloc[-1] - dec["fwd_21d"].iloc[0]
    monotone_frac = float((dec["fwd_21d"].diff().dropna() > 0).mean())
    dec_fmt = dec.copy()
    for c in ["fwd_5d", "fwd_10d", "fwd_21d", "ignition_rate"]:
        dec_fmt[c] = (dec_fmt[c] * 100).map("{:+.2f}%".format if c != "ignition_rate" else "{:.1f}%".format)

    md = f"""# M02 signal-quality gate — report{' (SMOKE)' if smoke else ''}

> Generated {datetime.now().isoformat(timespec='seconds')} by `scripts/analyze_m02_signal_quality.py`.
> All scores OUT-OF-SAMPLE (WF fold models on their test windows + final model on the
> post-train tail). Panel rows: {n_panel:,}. Gate criteria: prod-gap plan Phase 0.1.

## (a) Lead time vs M01 watchlist entry (lookback {LEAD_LOOKBACK_DAYS}d, signal = daily top decile)

- Watchlist entries in span: **{lead['n_entries']:,}**, with a prior M02 signal: **{lead['n_with_signal']:,}**
  (coverage **{lead['coverage']:.1%}**)
- Lead time days: median **{lead['lead_median']:.0f}**, IQR [{lead['lead_q25']:.0f}, {lead['lead_q75']:.0f}]
- Mean 21d fwd return from M02 signal date: **{lead['fwd21_from_signal_mean']:+.2%}**
  vs from M01 entry date: **{lead['fwd21_from_entry_mean']:+.2%}**

## (b) Score decile vs forward returns (the anti-circularity test)

{dec_fmt.to_markdown(index=False)}

- Top-minus-bottom decile 21d spread: **{spread:+.2%}**
- Monotone step fraction (21d): **{monotone_frac:.0%}** of decile steps increase

## (c) Top-50 stability

- Mean day-over-day top-50 overlap: **{turn['overlap_mean']:.1%}** over {turn['n_days']:,} days
- Unique names ever in top-50: **{turn['unique_names']:,}**; precision at FIRST appearance:
  **{turn['unique_precision']:.1%}** (vs daily-P@50 ≈ 50% from the WF run)

## Gate read (Phase 0.1 go/no-go)

- **Go requires:** (a) coverage well above 0 with median lead > 0, AND (b) a real,
  roughly monotone top-vs-bottom forward-return spread.
- Verdict: _fill after review — this section is the human call, not auto-generated._
"""
    REPORT.write_text(md, encoding="utf-8")
    print(f"report -> {REPORT}", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default=str(DUCKDB_PATH))
    ap.add_argument("--wf-run", default=str(WF_RUN))
    ap.add_argument("--final-run", default=str(FINAL_RUN))
    ap.add_argument("--smoke", action="store_true")
    args = ap.parse_args()

    panel = build_oos_panel(Path(args.wf_run), Path(args.final_run), args.db, args.smoke)
    cache = Path(args.wf_run) / ("oos_score_panel_smoke.parquet" if args.smoke else "oos_score_panel.parquet")

    con = duckdb.connect(args.db, read_only=True)
    try:
        _sql(con, str(cache).replace("\\", "/"))
        print("views ready; running analyses...", flush=True)
        lead = analyze_lead_time(con)
        print(f"(a) lead-time: {lead}", flush=True)
        dec = analyze_deciles(con)
        print(f"(b) deciles:\n{dec.to_string()}", flush=True)
        turn = analyze_turnover(con)
        print(f"(c) turnover: {turn}", flush=True)
    finally:
        con.close()

    write_report(lead, dec, turn, len(panel), args.smoke)


if __name__ == "__main__":
    main()
