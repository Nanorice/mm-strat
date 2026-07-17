"""PortfolioManager — fill-log derivation and input validation."""
import os
import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import pytest

# dashboard_utils runs _ensure_local_db() at MODULE SCOPE, which starts a ~751MB
# R2 pull unless DASHBOARD_DB_PATH is set (project_on_cloud_creds_false_positive).
# Pin it before the import below; don't inherit the ambient value.
os.environ.setdefault("DASHBOARD_DB_PATH", "data/dashboard.duckdb")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from src.managers.portfolio_manager import PortfolioManager


@pytest.fixture
def pm(tmp_path):
    m = PortfolioManager(str(tmp_path / "t.duckdb"))
    m.ensure_schema()
    # positions() marks to price_data.close; seed the same shape the real DB has.
    import duckdb
    with duckdb.connect(m.db_path) as c:
        # Mirror the real price_data shape: load_portfolio_risk reads high/low.
        c.execute("CREATE TABLE price_data (ticker VARCHAR, date DATE, close DOUBLE,"
                  " high DOUBLE, low DOUBLE)")
        c.execute("""INSERT INTO price_data (ticker,date,close,high,low) VALUES
            ('NVDA','2026-07-01',150.0,151.0,149.0), ('NVDA','2026-07-15',300.0,301.0,299.0),
            ('AAPL','2026-07-15',110.0,111.0,109.0), ('MSFT','2026-07-15',120.0,121.0,119.0),
            ('TSLA','2026-07-15', 20.0, 21.0, 19.0), ('AMD', '2026-07-15',100.0,101.0,99.0),
            ('ORCL','2026-07-15', 50.0, 51.0, 49.0)""")
        c.execute("""CREATE TABLE t3_sepa_features
                     (ticker VARCHAR, date DATE, high_52w DOUBLE, low_52w DOUBLE)""")
        c.execute("INSERT INTO t3_sepa_features VALUES ('NVDA','2026-07-15',310.0,140.0)")
        # load_portfolio joins these; AAPL is deliberately UNSCORED so the
        # NULL-score path (the ~81% of the universe the model ignores) is covered.
        c.execute("""CREATE TABLE daily_predictions (
            prediction_date DATE, ticker VARCHAR, model_version_id VARCHAR, cohort VARCHAR,
            prob_class_1 DOUBLE, prob_class_3 DOUBLE, rank_within_day INTEGER,
            ingested_at TIMESTAMP)""")
        c.execute("""INSERT INTO daily_predictions VALUES
            ('2026-07-15','NVDA','m01_binary_x','active', 0.61, NULL, 3, now()),
            ('2026-07-01','NVDA','m01_binary_x','active', 0.40, NULL, 9, now())""")
        c.execute("CREATE TABLE company_profiles (ticker VARCHAR, sector VARCHAR,"
                  " industry VARCHAR, beta DOUBLE)")
        c.execute("""INSERT INTO company_profiles VALUES
            ('NVDA','Technology','Semiconductors',2.37), ('AAPL','Technology','Hardware',1.20),
            ('MSFT','Technology','Software',0.90), ('TSLA','Consumer Cyclical','Autos',2.10),
            ('AMD','Technology','Semiconductors',1.80), ('ORCL','Technology','Software',1.05)""")
    return m


def test_scale_in_averages_cost(pm):
    """Two BUYs at different prices -> qty sums, avg_cost is cost-weighted."""
    pm.add_trade("NVDA", date(2026, 1, 5), "BUY", 100, 100.0)
    pm.add_trade("NVDA", date(2026, 2, 5), "BUY", 100, 200.0)
    row = pm.positions().set_index("ticker").loc["NVDA"]
    assert row["qty"] == 200
    assert row["avg_cost"] == pytest.approx(150.0)


def test_partial_sell_keeps_buy_weighted_cost(pm):
    """A partial SELL reduces qty but must NOT distort the remaining cost basis."""
    pm.add_trade("AAPL", date(2026, 1, 5), "BUY", 100, 100.0)
    pm.add_trade("AAPL", date(2026, 3, 5), "SELL", 40, 500.0)
    row = pm.positions().set_index("ticker").loc["AAPL"]
    assert row["qty"] == 60
    assert row["avg_cost"] == pytest.approx(100.0)  # not dragged toward the 500 exit


def test_fees_fold_into_cost_basis(pm):
    pm.add_trade("MSFT", date(2026, 1, 5), "BUY", 10, 100.0, fees=50.0)
    row = pm.positions().set_index("ticker").loc["MSFT"]
    assert row["avg_cost"] == pytest.approx(105.0)  # (10*100 + 50) / 10


def test_full_exit_closes_position(pm):
    pm.add_trade("TSLA", date(2026, 1, 5), "BUY", 50, 10.0)
    pm.add_trade("TSLA", date(2026, 6, 5), "SELL", 50, 20.0)
    assert pm.position_qty("TSLA") == 0
    assert pm.positions(open_only=True).empty
    assert "TSLA" in set(pm.positions(open_only=False)["ticker"])


def test_oversell_is_rejected(pm):
    """The trust boundary: hand-typed input must not book a phantom sale."""
    pm.add_trade("AMD", date(2026, 1, 5), "BUY", 10, 100.0)
    with pytest.raises(ValueError, match="only 10.0 held"):
        pm.add_trade("AMD", date(2026, 1, 6), "SELL", 25, 110.0)
    assert pm.position_qty("AMD") == 10  # rejected fill left no trace


def test_sell_with_no_position_rejected(pm):
    with pytest.raises(ValueError, match="cannot SELL"):
        pm.add_trade("GME", date(2026, 1, 5), "SELL", 1, 100.0)


@pytest.mark.parametrize("kw", [
    {"quantity": 0}, {"quantity": -5}, {"price": 0}, {"price": -1}, {"fees": -1},
])
def test_invalid_numbers_rejected(pm, kw):
    args = {"quantity": 10, "price": 100.0, **kw}
    with pytest.raises(ValueError):
        pm.add_trade("X", date(2026, 1, 5), "BUY", **args)


def test_bad_side_rejected(pm):
    with pytest.raises(ValueError, match="side must be"):
        pm.add_trade("X", date(2026, 1, 5), "HOLD", 1, 1.0)


def test_ticker_normalized(pm):
    pm.add_trade("nvda", date(2026, 1, 5), "BUY", 1, 1.0)
    assert pm.position_qty("NVDA") == 1
    assert pm.position_qty("nvda") == 1


def test_append_only_correction(pm):
    """A wrong fill is corrected by an offsetting fill; both rows survive."""
    pm.add_trade("ORCL", date(2026, 1, 5), "BUY", 100, 50.0)
    pm.add_trade("ORCL", date(2026, 1, 5), "SELL", 100, 50.0)  # undo
    pm.add_trade("ORCL", date(2026, 1, 5), "BUY", 10, 50.0)    # what was meant
    assert pm.position_qty("ORCL") == 10
    assert len(pm.trades(ticker="ORCL")) == 3


def test_marks_to_latest_close(pm):
    """NVDA has two prices; the mark must take the most recent, not the first."""
    pm.add_trade("NVDA", date(2026, 1, 5), "BUY", 10, 100.0)
    row = pm.positions().set_index("ticker").loc["NVDA"]
    assert row["close"] == 300.0
    assert row["market_value"] == pytest.approx(3000.0)
    assert row["unrealized_pnl"] == pytest.approx(2000.0)


def test_unpriced_ticker_does_not_crash(pm):
    """A ticker with no price_data rows marks NULL rather than raising."""
    pm.add_trade("NOPRICE", date(2026, 1, 5), "BUY", 10, 100.0)
    row = pm.positions().set_index("ticker").loc["NOPRICE"]
    assert row["qty"] == 10
    assert pd.isna(row["close"])


def test_nav_snapshot_is_idempotent(pm):
    """Re-running the same day overwrites, never duplicates (PK on date)."""
    pm.add_trade("NVDA", date(2026, 1, 5), "BUY", 10, 100.0)
    pm.snapshot_nav(as_of=date(2026, 1, 6))
    pm.snapshot_nav(as_of=date(2026, 1, 6))
    with __import__("duckdb").connect(pm.db_path, read_only=True) as c:
        assert c.execute("SELECT COUNT(*) FROM nav_history").fetchone()[0] == 1


def test_nav_empty_book_is_zero_not_error(pm):
    assert pm.snapshot_nav(as_of=date(2026, 1, 6)) == 0.0


def test_cash_derives_from_flows_and_fills(pm):
    pm.add_cash_flow(date(2026, 1, 2), "DEPOSIT", 100_000)
    pm.add_trade("NVDA", date(2026, 1, 5), "BUY", 100, 150.0, fees=5.0)   # -15,005
    pm.add_trade("NVDA", date(2026, 3, 5), "SELL", 40, 200.0, fees=3.0)   # + 7,997
    pm.add_cash_flow(date(2026, 4, 1), "WITHDRAW", 10_000)
    assert pm.cash() == pytest.approx(100_000 - 15_005 + 7_997 - 10_000)


def test_cash_is_point_in_time(pm):
    pm.add_cash_flow(date(2026, 1, 2), "DEPOSIT", 50_000)
    pm.add_cash_flow(date(2026, 6, 1), "DEPOSIT", 20_000)
    assert pm.cash(as_of=date(2026, 3, 1)) == pytest.approx(50_000)
    assert pm.cash() == pytest.approx(70_000)


def test_deposit_is_not_a_gain(pm):
    """THE property the cash leg exists for. A 500k deposit must produce a ~0%
    return, not a +500k 'profit'. This is what a positions-only NAV got wrong."""
    pm.add_cash_flow(date(2026, 1, 2), "DEPOSIT", 100_000)
    pm.snapshot_nav(as_of=date(2026, 1, 2))          # nav 100k, all cash
    pm.add_cash_flow(date(2026, 1, 3), "DEPOSIT", 500_000)
    pm.snapshot_nav(as_of=date(2026, 1, 3))          # nav 600k — but 0 earned

    r = pm.returns().set_index("date")
    assert r.loc[date(2026, 1, 3), "ret"] == pytest.approx(0.0, abs=1e-9)
    # the naive version this guards against:
    nav = pm.nav_history().set_index("date")["nav"]
    assert nav.pct_change().loc[date(2026, 1, 3)] == pytest.approx(5.0)  # +500% lie


def test_withdrawal_is_not_a_loss(pm):
    pm.add_cash_flow(date(2026, 1, 2), "DEPOSIT", 100_000)
    pm.snapshot_nav(as_of=date(2026, 1, 2))
    pm.add_cash_flow(date(2026, 1, 3), "WITHDRAW", 40_000)
    pm.snapshot_nav(as_of=date(2026, 1, 3))
    r = pm.returns().set_index("date")
    assert r.loc[date(2026, 1, 3), "ret"] == pytest.approx(0.0, abs=1e-9)


def test_real_gain_is_measured(pm):
    """Sanity counterpart: a genuine mark-up MUST show as a gain."""
    pm.add_cash_flow(date(2026, 1, 2), "DEPOSIT", 100_000)
    pm.add_trade("NVDA", date(2026, 1, 2), "BUY", 100, 150.0)  # cash 85k + 100sh
    pm.snapshot_nav(as_of=date(2026, 7, 1))   # NVDA marks at 300 -> 85k + 30k = 115k
    prev = pm.nav_history().set_index("date").loc[date(2026, 7, 1), "nav"]
    assert prev == pytest.approx(85_000 + 100 * 300.0)


def test_nav_equals_cash_plus_positions(pm):
    pm.add_cash_flow(date(2026, 1, 2), "DEPOSIT", 100_000)
    pm.add_trade("NVDA", date(2026, 1, 5), "BUY", 100, 150.0)
    nav = pm.snapshot_nav(as_of=date(2026, 7, 1))
    row = pm.nav_history().set_index("date").loc[date(2026, 7, 1)]
    assert nav == pytest.approx(row["cash"] + row["positions_value"])
    assert row["cash"] == pytest.approx(85_000)


def test_drawdown_is_negative_after_a_fall(pm):
    pm.add_cash_flow(date(2026, 1, 2), "DEPOSIT", 100_000)
    pm.snapshot_nav(as_of=date(2026, 1, 2))
    pm.add_trade("TSLA", date(2026, 1, 3), "BUY", 1000, 80.0)  # cash 20k + 1000sh
    pm.snapshot_nav(as_of=date(2026, 1, 3))   # TSLA marks 20 -> 20k + 20k = 40k
    r = pm.returns()
    assert r["ret"].iloc[-1] < 0
    assert r["drawdown"].iloc[-1] < 0


def test_bad_cash_flow_rejected(pm):
    with pytest.raises(ValueError, match="kind must be"):
        pm.add_cash_flow(date(2026, 1, 2), "TRANSFER", 100)
    with pytest.raises(ValueError, match="amount must be"):
        pm.add_cash_flow(date(2026, 1, 2), "DEPOSIT", -100)


def test_loader_matches_manager(pm, monkeypatch):
    """dashboard_utils.load_portfolio duplicates the manager's SQL (it must stay
    read-only). Pin them to identical numbers so the copies can't drift apart."""
    pm.add_trade("NVDA", date(2026, 1, 5), "BUY", 100, 100.0)
    pm.add_trade("NVDA", date(2026, 2, 5), "BUY", 100, 200.0, fees=10.0)
    pm.add_trade("NVDA", date(2026, 3, 5), "SELL", 50, 250.0)
    pm.add_trade("AAPL", date(2026, 1, 5), "BUY", 10, 50.0)

    import duckdb
    import dashboard_utils as du
    monkeypatch.setattr(du, "_connect",
                        lambda read_only=True: duckdb.connect(pm.db_path, read_only=True))
    du.load_portfolio.clear()

    mgr = pm.positions(open_only=True).set_index("ticker")
    ldr = du.load_portfolio().set_index("ticker")

    assert list(mgr.index) == list(ldr.index)
    for col in ("qty", "avg_cost", "market_value", "unrealized_pnl", "pct_return"):
        for tkr in mgr.index:
            assert mgr.loc[tkr, col] == pytest.approx(ldr.loc[tkr, col]), f"{col}/{tkr} drifted"


def test_score_join_is_latest_and_null_when_unscored(pm, monkeypatch):
    """The model scores only the SEPA universe. A held name outside it must show
    NULL — never a stale score, never a zero (which would read as 'model hates it')."""
    pm.add_trade("NVDA", date(2026, 1, 5), "BUY", 10, 100.0)   # scored
    pm.add_trade("AAPL", date(2026, 1, 5), "BUY", 10, 100.0)   # NOT in daily_predictions

    import duckdb
    import dashboard_utils as du
    monkeypatch.setattr(du, "_connect",
                        lambda read_only=True: duckdb.connect(pm.db_path, read_only=True))
    du.load_portfolio.clear()
    p = du.load_portfolio().set_index("ticker")

    assert p.loc["NVDA", "score_raw"] == pytest.approx(0.61)   # latest, not the 0.40
    assert p.loc["NVDA", "cohort"] == "active"
    assert pd.isna(p.loc["AAPL", "score_raw"])                 # honest gap
    assert pd.isna(p.loc["AAPL", "cohort"])
    assert p.loc["NVDA", "sector"] == "Technology"             # profile join


def test_risk_atr_matches_hand_computed(pm, monkeypatch):
    """ATR is the unit every distance on the Risk panel is quoted in — a wrong ATR
    silently mis-scales all of them. Pin it to a hand-computed true range."""
    import duckdb
    import dashboard_utils as du

    # True range VARIES per bar so the window size is observable: a constant TR
    # would make every window average the same and the test would pass with a
    # wrong window (mutation-verified — the first version did exactly that).
    # Newest 14 bars have TR = 1..14 -> ATR(14) = mean(1..14) = 7.5.
    # A 5-bar window would give mean(1..5) = 3.0, so 7.5 pins the window.
    with duckdb.connect(pm.db_path) as c:
        for i in range(20):
            d = date(2026, 6, 1) + timedelta(days=i)
            tr = 20.0 - i          # newest bar (i=19) has TR=1, oldest TR=20
            c.execute("INSERT INTO price_data (ticker,date,close,high,low) VALUES (?,?,?,?,?)",
                      ["ATRT", d, 100.0, 100.0 + tr / 2, 100.0 - tr / 2])
    pm.add_trade("ATRT", date(2026, 6, 1), "BUY", 10, 100.0)

    monkeypatch.setattr(du, "_connect",
                        lambda read_only=True: duckdb.connect(pm.db_path, read_only=True))
    du.load_portfolio_risk.clear()
    r = du.load_portfolio_risk().set_index("ticker")

    assert r.loc["ATRT", "atr_14"] == pytest.approx(7.5)           # mean(1..14), NOT mean(1..5)=3.0
    assert r.loc["ATRT", "atr_pct"] == pytest.approx(7.5)          # 7.5/100.0*100
    assert r.loc["ATRT", "atr_move_value"] == pytest.approx(75.0)  # 10 shares x 7.5


def test_risk_covers_names_outside_the_screen(pm, monkeypatch):
    """Entries are discretionary, so holdings often sit outside the SEPA screen.
    ATR/vol/S-R must still resolve from price_data; only 52w may be NULL."""
    import duckdb
    import dashboard_utils as du
    with duckdb.connect(pm.db_path) as c:
        for i in range(20):
            d = date(2026, 6, 1) + timedelta(days=i)
            c.execute("INSERT INTO price_data (ticker,date,close,high,low) VALUES (?,?,?,?,?)",
                      ["OFFSCR", d, 50.0 + i, 51.0 + i, 49.0 + i])
    pm.add_trade("OFFSCR", date(2026, 6, 1), "BUY", 10, 50.0)

    monkeypatch.setattr(du, "_connect",
                        lambda read_only=True: duckdb.connect(pm.db_path, read_only=True))
    du.load_portfolio_risk.clear()
    r = du.load_portfolio_risk().set_index("ticker")

    assert r.loc["OFFSCR", "atr_14"] > 0          # from price_data -> covered
    assert pd.notna(r.loc["OFFSCR", "sup_50d"])
    assert pd.isna(r.loc["OFFSCR", "high_52w"])   # off-screen -> honest gap, no crash


def test_loader_returns_match_manager(pm, monkeypatch):
    """load_returns() duplicates the manager's TWR math — pin them together."""
    pm.add_cash_flow(date(2026, 1, 2), "DEPOSIT", 100_000)
    pm.snapshot_nav(as_of=date(2026, 1, 2))
    pm.add_trade("NVDA", date(2026, 1, 3), "BUY", 100, 150.0)
    pm.snapshot_nav(as_of=date(2026, 1, 3))
    pm.add_cash_flow(date(2026, 1, 4), "DEPOSIT", 50_000)   # flow day
    pm.snapshot_nav(as_of=date(2026, 1, 4))

    import duckdb
    import dashboard_utils as du
    monkeypatch.setattr(du, "_connect",
                        lambda read_only=True: duckdb.connect(pm.db_path, read_only=True))
    du.load_nav_history.clear(); du.load_returns.clear(); du.load_cash.clear()

    mgr, ldr = pm.returns(), du.load_returns()
    assert len(mgr) == len(ldr) > 0
    for col in ("ret", "cum_ret", "drawdown"):
        assert list(mgr[col].round(10)) == list(ldr[col].round(10)), f"{col} drifted"
    assert du.load_cash() == pytest.approx(pm.cash())
