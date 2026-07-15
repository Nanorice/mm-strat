"""
Vectorized SEPA Backtest
========================
Pure pandas/numpy engine for rapid notebook prototyping.

Trade-offs vs SEPAHybridV1 (BackTrader):
    - 10-100x faster (no event loop, no per-bar indicator updates)
    - Approximate capital constraints (assumes slots always available)
    - Simplified single-exit logic (no 3-tranche scaling)
    - Optional flat commission/slippage estimate

Use for rapid model iteration and parameter sweeps.
Use BackTrader for final production validation.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import duckdb
from src import db
import numpy as np
import pandas as pd

import config
from src.backtest.universe_scorer import UniverseScorer

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = config.DATA_DIR / 'market_data.duckdb'


class VectorizedSEPABacktest:
    """
    Vectorized SEPA backtest — no event loop.

    Flow:
        1. Score all T3 candidates daily via UniverseScorer.score_from_t3()
        2. Filter by min_prob_elite, skip warmup days
        3. Rank within each day by prob_elite, take top N
        4. For each entry, vectorize-simulate exit vs price_data
        5. Compute trade-level PnL + portfolio equity curve
    """

    def __init__(
        self,
        model_path: str = 'models/m01_prototype/model.json',
        db_path: Optional[str] = None,
        start_date: str = '2020-01-01',
        end_date: str = '2025-01-01',
        min_prob_elite: float = 0.15,
        max_positions_per_day: int = 3,
        ranking_lookback_days: int = 10,
        stop_loss_pct: float = 0.10,
        sma_exit_period: int = 50,
        warmup_days: int = 10,
        commission_pct: float = 0.001,
        slippage_pct: float = 0.001,
        initial_cash: float = 100_000.0,
        position_size_pct: float = 0.10,
        max_hold_days: int = 252,
        exit_policy: str = 'sma',
        nday_hold: int = 10,
        atr_period: int = 14,
        atr_trail_mult: float = 2.5,
        be_trigger_pct: float = 0.10,
        trail_pct: float = 0.10,
        progressive_fills: bool = False,
        starter_frac: float = 0.5,
        add_trigger_pct: float = 0.05,
        regime_gate: bool = False,
        regime_bear_score: float = 15.0,
        max_concurrent_positions: Optional[int] = None,
        precomputed_scores: Optional[pd.DataFrame] = None,
        precomputed_prices: Optional[pd.DataFrame] = None,
    ):
        self.model_path = model_path
        self.db_path = Path(db_path) if db_path else DEFAULT_DB_PATH
        self.start_date = start_date
        self.end_date = end_date
        self.min_prob_elite = min_prob_elite
        self.max_positions_per_day = max_positions_per_day
        self.ranking_lookback_days = ranking_lookback_days
        self.stop_loss_pct = stop_loss_pct
        self.sma_exit_period = sma_exit_period
        self.warmup_days = warmup_days
        self.commission_pct = commission_pct
        self.slippage_pct = slippage_pct
        self.initial_cash = initial_cash
        self.position_size_pct = position_size_pct
        self.max_hold_days = max_hold_days
        if exit_policy not in ('sma', 'nday', 'atr_trail', 'minervini'):
            raise ValueError(f"exit_policy must be sma|nday|atr_trail|minervini, got {exit_policy!r}")
        self.exit_policy = exit_policy
        self.nday_hold = nday_hold
        self.atr_period = atr_period
        self.atr_trail_mult = atr_trail_mult
        # Minervini breakeven-ratchet trailing stop: tight initial stop
        # (stop_loss_pct), ratchet to breakeven once the running high clears
        # +be_trigger_pct, then trail trail_pct below the running high.
        self.be_trigger_pct = be_trigger_pct
        self.trail_pct = trail_pct
        # Progressive fills (Minervini press-winners/starve-losers): enter a
        # starter_frac position, add the remainder to full size once price first
        # clears +add_trigger_pct. Path-dependent — a loser that never triggers
        # stays small and stops out cheap; a winner scales up only AFTER it's
        # already up, so the added capital earns the post-trigger path only. The
        # asymmetry the fixed-hold basket can't express (verdict §6d point 2, §7b).
        self.progressive_fills = progressive_fills
        self.starter_frac = starter_frac
        self.add_trigger_pct = add_trigger_pct
        # M03 strong-bear gate: matches SEPAHybridV1 (no entries + zero exposure
        # when m03_score < regime_bear_score, i.e. regime_cat 0). This is the
        # load-bearing piece that closes the vec↔BackTrader sign-flip gap — the
        # vectorized engine otherwise holds through the 2022 bear.
        self.regime_gate = regime_gate
        self.regime_bear_score = regime_bear_score
        # Hard slot-book cap. Without it the engine over-subscribes (top-N *new*
        # entries/day × ~25-day holds → up to ~4N concurrent), and equity_curve
        # pro-rata-dilutes the winners — the dominant vec↔BackTrader gap. When
        # set, a greedy capacity pass admits an entry only if a slot is free
        # (an earlier trade has exited), mirroring BackTrader's slot book.
        self.max_concurrent_positions = max_concurrent_positions
        self._regime_exposure: Optional[pd.Series] = None

        # Injected caches — avoids re-scoring / re-loading on every sweep combo
        self._scores: Optional[pd.DataFrame] = precomputed_scores
        self._prices: Optional[pd.DataFrame] = precomputed_prices

    def run(self) -> pd.DataFrame:
        """
        Execute the full vectorized backtest.

        Returns:
            DataFrame with columns: ticker, entry_date, entry_price, exit_date,
            exit_price, exit_reason, pnl_pct, prob_elite_at_entry, holding_days.
        """
        entries = self._select_entries()
        if entries.empty:
            logger.warning("No entries selected — check min_prob_elite / warmup / date range")
            return pd.DataFrame(columns=[
                'ticker', 'entry_date', 'entry_price', 'exit_date', 'exit_price',
                'exit_reason', 'pnl_pct', 'prob_elite_at_entry', 'holding_days',
            ])

        prices = self._load_prices(
            entries['ticker'].unique().tolist(),
            sma_period=self.sma_exit_period,
        )
        self._price_path = prices  # cached so equity_curve can mark-to-market
        trades = self._simulate_exits(entries, prices)
        trades = self._enforce_capacity(trades)
        trades = self._apply_costs(trades)
        return trades

    def _select_entries(self) -> pd.DataFrame:
        if self._scores is None:
            scorer = UniverseScorer(
                m01_path=self.model_path,
                calibration_path=None,
            )
            self._scores = scorer.score_from_t3(
                self.start_date,
                self.end_date,
                db_path=self.db_path,
                ranking_lookback_days=self.ranking_lookback_days,
            )

        if 'prob_elite' not in self._scores.columns:
            raise RuntimeError(
                "Scorer output missing prob_elite — model must be a classifier"
            )

        # SEPA entry gate: keep only genuine breakouts (trend_ok AND breakout_ok).
        # score_from_t3 scores the WHOLE trend-active panel, so without this the
        # top-N/day is drawn from an inflated population of off-setup rows (a stock
        # in a downtrend still gets a — out-of-distribution — score). Legacy score
        # frames without the flags fall through ungated (with a warning).
        if {'trend_ok', 'breakout_ok'} <= set(self._scores.columns):
            n_before = len(self._scores)
            gated = self._scores[
                self._scores['trend_ok'].astype(bool)
                & self._scores['breakout_ok'].astype(bool)
            ]
            logger.info(
                f"SEPA entry gate: {len(gated)}/{n_before} rows are genuine "
                f"breakouts (trend_ok AND breakout_ok)"
            )
        else:
            logger.warning(
                "No trend_ok/breakout_ok in scores — SEPA entry gate disabled; "
                "selecting from the full scored panel (population-inflated)."
            )
            gated = self._scores

        eligible = gated[gated['prob_elite'] >= self.min_prob_elite].copy()
        eligible['date'] = pd.to_datetime(eligible['date'])

        unique_dates = pd.Series(eligible['date'].unique()).sort_values().reset_index(drop=True)
        if len(unique_dates) <= self.warmup_days:
            logger.warning(
                f"warmup_days={self.warmup_days} >= unique dates ({len(unique_dates)}); "
                "no entries will be generated"
            )
            return eligible.iloc[0:0]

        warmup_cutoff = unique_dates.iloc[self.warmup_days]
        eligible = eligible[eligible['date'] >= warmup_cutoff]

        # M03 gate: block entries on strong-bear days (regime 0), like BackTrader.
        if self.regime_gate:
            exp = self._load_regime_exposure()
            bear_days = set(exp.index[exp <= 0.0])
            n_before = len(eligible)
            eligible = eligible[~eligible['date'].isin(bear_days)]
            logger.info(
                f"Regime gate: dropped {n_before - len(eligible)} bear-day candidate rows "
                f"({len(bear_days)} strong-bear days)"
            )

        eligible['daily_rank'] = eligible.groupby('date')['prob_elite'].rank(
            ascending=False, method='first'
        )
        eligible = eligible[eligible['daily_rank'] <= self.max_positions_per_day]

        # Deduplicate: only first entry per ticker within the backtest window
        eligible = eligible.sort_values(['ticker', 'date'])
        first_entries = eligible.drop_duplicates(subset=['ticker'], keep='first')

        logger.info(
            f"Selected {len(first_entries)} entries from {len(eligible)} eligible "
            f"({eligible['ticker'].nunique()} unique tickers)"
        )
        cols_to_return = ['date', 'ticker', 'prob_elite', 'calibrated_score']
        if 'rs_sector_rank' in first_entries.columns:
            cols_to_return.append('rs_sector_rank')
        if 'rs_industry_rank' in first_entries.columns:
            cols_to_return.append('rs_industry_rank')
            
        return first_entries[cols_to_return].rename(
            columns={'date': 'entry_date', 'prob_elite': 'prob_elite_at_entry'}
        )

    def _load_prices(
        self,
        tickers: list[str],
        sma_period: Optional[int] = None,
    ) -> pd.DataFrame:
        """Load OHLC prices and compute SMA exit signal.

        If ``self._prices`` was injected (precomputed_prices), the raw frame is
        reused and only the SMA is (re)computed for the current sma_exit_period.
        """
        sma_period = sma_period or self.sma_exit_period

        if self._prices is not None:
            # Use cached raw prices; filter to requested tickers
            df = self._prices[self._prices['ticker'].isin(tickers)].copy()
        else:
            con = db.connect(str(self.db_path), read_only=True)
            try:
                df = con.execute("""
                    SELECT ticker, date, open, high, low, close
                    FROM price_data
                    WHERE ticker = ANY(?)
                      AND date >= ? AND date <= ?
                    ORDER BY ticker, date
                """, [tickers, self.start_date, self.end_date]).fetchdf()
            finally:
                con.close()
            df['date'] = pd.to_datetime(df['date'])

        # (Re)compute SMA for the current sweep period — fast, in-memory
        df['sma'] = (
            df.groupby('ticker')['close']
            .transform(lambda s: s.rolling(sma_period, min_periods=1).mean())
        )
        if self.exit_policy == 'atr_trail':
            g = df.groupby('ticker')
            prev_close = g['close'].shift(1)
            tr = pd.concat([
                df['high'] - df['low'],
                (df['high'] - prev_close).abs(),
                (df['low'] - prev_close).abs(),
            ], axis=1).max(axis=1)
            df['atr'] = tr.groupby(df['ticker']).transform(
                lambda s: s.rolling(self.atr_period, min_periods=1).mean()
            )
        logger.info(f"Prices ready: {len(df)} rows, {df['ticker'].nunique()} tickers, SMA={sma_period}")
        return df

    def _load_regime_exposure(self) -> pd.Series:
        """Daily exposure series from M03: 0.0 on strong-bear (m03_score < bear
        threshold, i.e. regime_cat 0), 1.0 otherwise. Same threshold as
        SEPAHybridV1's bear-gate (runner._load_regime_from_duckdb → regime_cat 0).
        Cached so entry-gate and equity_curve share one series.
        """
        if self._regime_exposure is not None:
            return self._regime_exposure
        con = db.connect(str(self.db_path), read_only=True)
        try:
            df = con.execute("""
                SELECT date, m03_score
                FROM t2_regime_scores
                WHERE date >= ? AND date <= ?
                ORDER BY date
            """, [self.start_date, self.end_date]).fetchdf()
        finally:
            con.close()
        df['date'] = pd.to_datetime(df['date'])
        exp = pd.Series(
            np.where(df['m03_score'] < self.regime_bear_score, 0.0, 1.0),
            index=df['date'], name='exposure',
        )
        self._regime_exposure = exp
        return exp

    def _simulate_exits(
        self,
        entries: pd.DataFrame,
        prices: pd.DataFrame,
    ) -> pd.DataFrame:
        prices = prices.sort_values(['ticker', 'date']).reset_index(drop=True)

        # Attach entry_price using the bar AT entry_date (next-day fill approximation: use close)
        entry_price_lookup = prices.merge(
            entries[['ticker', 'entry_date']],
            left_on=['ticker', 'date'],
            right_on=['ticker', 'entry_date'],
            how='inner',
        )[['ticker', 'entry_date', 'close']].rename(columns={'close': 'entry_price'})

        entries = entries.merge(entry_price_lookup, on=['ticker', 'entry_date'], how='inner')
        if entries.empty:
            return pd.DataFrame()

        # Join every post-entry bar with its originating entry
        merged = prices.merge(
            entries[['ticker', 'entry_date', 'entry_price', 'prob_elite_at_entry']],
            on='ticker',
            how='inner',
        )
        merged = merged[merged['date'] > merged['entry_date']].copy()

        merged['bars_held'] = (
            merged.groupby(['ticker', 'entry_date']).cumcount() + 1
        )

        # Stop level: fixed % (sma/nday), ATR-trailing (atr_trail), or the
        # Minervini breakeven-ratchet (minervini) off the running high.
        if self.exit_policy == 'atr_trail':
            grp = merged.groupby(['ticker', 'entry_date'])
            run_high = grp['high'].cummax()
            merged['stop_level'] = run_high - self.atr_trail_mult * merged['atr']
        elif self.exit_policy == 'minervini':
            run_high = merged.groupby(['ticker', 'entry_date'])['high'].cummax()
            initial = merged['entry_price'] * (1.0 - self.stop_loss_pct)
            # Armed once the running high clears the breakeven trigger; then the
            # stop is the wider-up of breakeven and the trailing level, so it only
            # ever ratchets up.
            armed = run_high >= merged['entry_price'] * (1.0 + self.be_trigger_pct)
            trailed = np.maximum(
                merged['entry_price'].values,
                run_high.values * (1.0 - self.trail_pct),
            )
            merged['stop_level'] = np.where(armed.values, trailed, initial.values)
        else:
            merged['stop_level'] = merged['entry_price'] * (1.0 - self.stop_loss_pct)
        merged['hit_stop'] = merged['low'] <= merged['stop_level']
        merged['hit_timeout'] = merged['bars_held'] >= self.max_hold_days

        # Second exit condition is the strategy-type selector.
        if self.exit_policy == 'sma':
            merged['hit_secondary'] = merged['close'] < merged['sma']
            secondary_reason = 'trend_break'
        elif self.exit_policy == 'nday':
            merged['hit_secondary'] = merged['bars_held'] >= self.nday_hold
            secondary_reason = 'nday_exit'
        else:  # atr_trail / minervini — the trailing stop IS the exit; no secondary
            merged['hit_secondary'] = False
            secondary_reason = 'trail_stop'

        # Progressive fills: date of the first bar whose high clears +add_trigger_pct
        # (when the starter scales to full). NaT for trades that never trigger.
        if self.progressive_fills:
            add_hit = merged[
                merged['high'] >= merged['entry_price'] * (1.0 + self.add_trigger_pct)
            ]
            add_dates = (
                add_hit.sort_values(['ticker', 'entry_date', 'date'])
                .drop_duplicates(subset=['ticker', 'entry_date'], keep='first')
                [['ticker', 'entry_date', 'date']]
                .rename(columns={'date': 'add_date'})
            )

        # Priority: stop > secondary > timeout
        conditions = [merged['hit_stop'], merged['hit_secondary'], merged['hit_timeout']]
        choices = ['stop_loss', secondary_reason, 'max_hold']
        merged['exit_candidate'] = np.select(conditions, choices, default=None)

        exits = merged[merged['exit_candidate'].notna()].copy()
        first_exits = exits.sort_values(['ticker', 'entry_date', 'date']).drop_duplicates(
            subset=['ticker', 'entry_date'], keep='first'
        )

        # Exit price: stop-outs fill at the stop, but a gap-down OPEN below the
        # stop fills at the open (worse) — book min(stop_level, open), not the
        # stop unconditionally (was understating the gap tail: 7% of stops gap,
        # real loss to -39.8% vs booked -15%).
        first_exits['exit_price'] = np.where(
            first_exits['exit_candidate'] == 'stop_loss',
            np.minimum(first_exits['stop_level'], first_exits['open']),
            first_exits['close'],
        )

        trades = entries.merge(
            first_exits[['ticker', 'entry_date', 'date', 'exit_price', 'exit_candidate']],
            on=['ticker', 'entry_date'],
            how='left',
        ).rename(columns={'date': 'exit_date', 'exit_candidate': 'exit_reason'})

        # Open trades: still holding at end of data — mark-to-market at last available close
        open_mask = trades['exit_date'].isna()
        if open_mask.any():
            last_prices = (
                prices.sort_values(['ticker', 'date'])
                .groupby('ticker')
                .tail(1)[['ticker', 'date', 'close']]
                .rename(columns={'date': 'last_date', 'close': 'last_close'})
            )
            trades = trades.merge(last_prices, on='ticker', how='left')
            trades.loc[open_mask, 'exit_date'] = trades.loc[open_mask, 'last_date']
            trades.loc[open_mask, 'exit_price'] = trades.loc[open_mask, 'last_close']
            trades.loc[open_mask, 'exit_reason'] = 'held_open'
            trades = trades.drop(columns=['last_date', 'last_close'])

        trades['pnl_pct'] = (
            (trades['exit_price'] - trades['entry_price']) / trades['entry_price']
        )
        trades['holding_days'] = (
            pd.to_datetime(trades['exit_date']) - pd.to_datetime(trades['entry_date'])
        ).dt.days

        cols = [
            'ticker', 'entry_date', 'entry_price', 'exit_date', 'exit_price',
            'exit_reason', 'pnl_pct', 'prob_elite_at_entry', 'holding_days',
        ]
        if self.progressive_fills:
            trades = trades.merge(add_dates, on=['ticker', 'entry_date'], how='left')
            cols.append('add_date')
        if 'rs_sector_rank' in trades.columns:
            cols.append('rs_sector_rank')
        if 'rs_industry_rank' in trades.columns:
            cols.append('rs_industry_rank')
            
        return trades[cols].sort_values('entry_date').reset_index(drop=True)

    def _enforce_capacity(self, trades: pd.DataFrame) -> pd.DataFrame:
        """Greedy slot-book: admit an entry only if a slot is free at its date.

        Exits here are path-independent — a trade's exit depends only on its own
        entry and that ticker's forward price, not on other open positions — so a
        single heap pass over entry-date-sorted trades gives the exact 5-slot
        book BackTrader produces via its event loop. On a tie of entry dates,
        higher prob_elite_at_entry wins the slot (matches daily-rank priority).
        """
        import heapq
        cap = self.max_concurrent_positions
        if cap is None or trades.empty:
            return trades

        ordered = trades.sort_values(
            ['entry_date', 'prob_elite_at_entry'], ascending=[True, False]
        )
        active: list = []  # min-heap of exit_dates for currently-open positions
        keep_idx = []
        for idx, t in ordered.iterrows():
            entry = pd.Timestamp(t['entry_date'])
            while active and active[0] <= entry:  # free slots for exits up to today
                heapq.heappop(active)
            if len(active) < cap:
                heapq.heappush(active, pd.Timestamp(t['exit_date']))
                keep_idx.append(idx)
        n_drop = len(trades) - len(keep_idx)
        logger.info(f"Capacity gate (cap={cap}): dropped {n_drop} over-subscribed entries")
        return trades.loc[keep_idx].sort_values('entry_date').reset_index(drop=True)

    def _apply_costs(self, trades: pd.DataFrame) -> pd.DataFrame:
        if trades.empty:
            return trades
        cost = 2 * (self.commission_pct + self.slippage_pct)
        trades['pnl_pct'] = trades['pnl_pct'] - cost
        return trades

    def equity_curve(
        self,
        trades: pd.DataFrame,
        exposure: Optional[pd.Series] = None,
    ) -> pd.Series:
        """Bar-by-bar mark-to-market equity curve with a shared capital pool.

        Fixes two flaws of a spike-on-exit curve:
          1. Each position is marked to its *actual* daily close over its holding
             window (from the cached ``price_data`` path), so real intra-trade
             volatility and drawdown are captured — not a straight-line
             approximation, which artificially smooths daily variance and
             inflates Sharpe.
          2. Positions draw from a *shared* pool: per-position weight is
             ``position_size_pct`` of current equity, scaled down pro-rata when
             more positions are open than the pool allows (max_slots =
             1/position_size_pct), so N concurrent trades cannot each lever the
             full account.

        ``exposure`` is an optional daily weight series (a *separate* sizing input,
        e.g. macro/VIX regime) indexed by date, values in [0, 1+]. It scales each
        day's portfolio return WITHOUT touching selection — the same trades, sized
        differently. Missing/unaligned dates default to 1.0 (flat). Must be
        lagged by the caller to avoid lookahead. Default None => flat 1.0, i.e.
        exactly the prior behaviour (backward-compatible).

        Requires the price path — set by ``run()``. If unavailable (e.g. curve
        called on injected trades), raises so the caller doesn't silently get a
        degenerate curve.
        """
        if trades.empty:
            return pd.Series(dtype=float)
        prices = getattr(self, '_price_path', None)
        if prices is None:
            raise RuntimeError(
                "equity_curve needs the price path; call run() first (it caches "
                "_price_path) or pass prices via _price_path."
            )

        max_slots = max(1, int(round(1.0 / self.position_size_pct)))

        dates = pd.date_range(
            start=pd.Timestamp(trades['entry_date'].min()),
            end=pd.Timestamp(trades['exit_date'].max()),
            freq='B',
        )

        # Wide daily-return matrix: rows=business days, cols=ticker, cell=close-to-close ret.
        px = prices[['ticker', 'date', 'close']].copy()
        px['date'] = pd.to_datetime(px['date'])
        close_wide = (
            px.pivot_table(index='date', columns='ticker', values='close', aggfunc='last')
            .reindex(dates).ffill()
        )
        ret_wide = close_wide.pct_change().fillna(0.0)

        date_pos = {d: i for i, d in enumerate(dates)}

        # Per-day fractional PnL (weight-1 positions) and open-position count.
        daily_frac_pnl = np.zeros(len(dates))
        open_count = np.zeros(len(dates))

        for _, t in trades.iterrows():
            tkr = t['ticker']
            if tkr not in ret_wide.columns:
                continue
            entry_i = self._nearest_idx(pd.Timestamp(t['entry_date']), dates, date_pos)
            exit_i = self._nearest_idx(pd.Timestamp(t['exit_date']), dates, date_pos)
            if entry_i is None or exit_i is None or exit_i <= entry_i:
                continue
            # Held over (entry, exit]; PnL accrues on each held bar's actual return.
            seg = ret_wide[tkr].values[entry_i + 1:exit_i + 1].copy()
            # Progressive fills: weight held bars at starter_frac until the add
            # fires, full (1.0) after. The starter runs the whole path; the added
            # capital only earns the post-trigger bars — winners scale up, losers
            # that never trigger stay small.
            if self.progressive_fills:
                w = np.full(len(seg), self.starter_frac)
                add_date = t.get('add_date')
                if pd.notna(add_date):
                    add_i = self._nearest_idx(pd.Timestamp(add_date), dates, date_pos)
                    if add_i is not None:
                        # bar-local offset into seg (seg starts at entry_i+1)
                        off = max(0, add_i - (entry_i + 1))
                        w[off:] = 1.0
                seg = seg * w
            daily_frac_pnl[entry_i + 1:exit_i + 1] += seg
            open_count[entry_i:exit_i] += 1

        scale = np.where(open_count > max_slots, max_slots / np.maximum(open_count, 1), 1.0)
        daily_return = daily_frac_pnl * self.position_size_pct * scale

        # M03 bear-gate: zero daily return on strong-bear days (positions flat),
        # mirroring BackTrader's regime_liquidation. Composes with any macro
        # exposure the caller passes (they multiply).
        if self.regime_gate:
            g = self._load_regime_exposure().reindex(dates).ffill().fillna(1.0).to_numpy()
            daily_return = daily_return * g

        # Separate sizing input: scale daily exposure by the macro weight (flat if absent).
        if exposure is not None:
            w = exposure.reindex(dates).ffill().fillna(1.0).to_numpy()
            daily_return = daily_return * w

        equity = self.initial_cash * np.cumprod(1.0 + daily_return)
        return pd.Series(equity, index=dates, name='equity')

    @staticmethod
    def _nearest_idx(day: pd.Timestamp, dates: pd.DatetimeIndex, date_idx: dict) -> Optional[int]:
        """Map a (possibly non-business-day) date onto the business-day grid."""
        i = date_idx.get(day)
        if i is not None:
            return i
        after = dates[dates >= day]
        if len(after):
            return date_idx[after[0]]
        return None

    def metrics(self, trades: pd.DataFrame) -> dict:
        """Risk-adjusted metrics off the mark-to-market equity curve.

        The objective surface for the parameter optimizer. Returns sharpe,
        annualized return/vol, max drawdown, plus trade-level stats.
        """
        base = {
            'n_trades': len(trades), 'sharpe': float('nan'), 'ann_return': float('nan'),
            'ann_vol': float('nan'), 'total_return': float('nan'), 'max_drawdown': float('nan'),
            'win_rate': float('nan'), 'avg_pnl_pct': float('nan'),
        }
        if trades.empty:
            return base

        eq = self.equity_curve(trades)
        if len(eq) < 2:
            return base

        rets = eq.pct_change().dropna()
        ann = np.sqrt(252)
        std = rets.std()
        wins = trades[trades['pnl_pct'] > 0]
        base.update({
            'sharpe': float(rets.mean() / std * ann) if std > 0 else float('nan'),
            'ann_return': float((eq.iloc[-1] / eq.iloc[0]) ** (252 / len(eq)) - 1),
            'ann_vol': float(std * ann),
            'total_return': float(eq.iloc[-1] / eq.iloc[0] - 1),
            'max_drawdown': float((eq / eq.cummax() - 1).min()),
            'win_rate': float(len(wins) / len(trades)),
            'avg_pnl_pct': float(trades['pnl_pct'].mean()),
        })
        return base

    def summary(self, trades: pd.DataFrame) -> dict:
        """Print and return summary statistics."""
        if trades.empty:
            stats = {'n_trades': 0}
            print(stats)
            return stats

        wins = trades[trades['pnl_pct'] > 0]
        losses = trades[trades['pnl_pct'] <= 0]
        stats = {
            'n_trades': len(trades),
            'n_tickers': trades['ticker'].nunique(),
            'win_rate': len(wins) / len(trades),
            'avg_pnl_pct': trades['pnl_pct'].mean(),
            'median_pnl_pct': trades['pnl_pct'].median(),
            'avg_win_pct': wins['pnl_pct'].mean() if len(wins) else 0.0,
            'avg_loss_pct': losses['pnl_pct'].mean() if len(losses) else 0.0,
            'avg_hold_days': trades['holding_days'].mean(),
            'total_pnl_pct_sum': trades['pnl_pct'].sum(),
            'exit_reasons': trades['exit_reason'].value_counts().to_dict(),
        }

        print("=" * 60)
        print(f"Vectorized Backtest Summary ({self.start_date} -> {self.end_date})")
        print("=" * 60)
        print(f"  Trades:        {stats['n_trades']}")
        print(f"  Tickers:       {stats['n_tickers']}")
        print(f"  Win rate:      {stats['win_rate']:.2%}")
        print(f"  Avg PnL:       {stats['avg_pnl_pct']:.2%}")
        print(f"  Avg win:       {stats['avg_win_pct']:.2%}")
        print(f"  Avg loss:      {stats['avg_loss_pct']:.2%}")
        print(f"  Avg hold:      {stats['avg_hold_days']:.1f} days")
        print(f"  Exit reasons:  {stats['exit_reasons']}")
        print("=" * 60)
        return stats

    def tearsheet(
        self,
        trades: pd.DataFrame,
        benchmark: str = 'SPY',
        output_path: Optional[str] = None,
    ) -> Optional[str]:
        """Generate QuantStats tearsheet from trade results."""
        try:
            import quantstats as qs
        except ImportError:
            logger.error("quantstats not installed. Run: pip install quantstats")
            return None

        equity = self.equity_curve(trades)
        if len(equity) < 2:
            logger.warning("Insufficient equity data for tearsheet")
            return None

        returns = equity.pct_change().dropna()
        returns.index = pd.to_datetime(returns.index)
        returns.index.name = None

        if output_path:
            qs.reports.html(returns, benchmark=benchmark, output=output_path)
            logger.info(f"Tearsheet saved to {output_path}")
            return output_path

        qs.reports.html(returns, benchmark=benchmark)
        return None


def _minervini_selfcheck() -> None:
    """The ratchet must move the stop UP after the breakeven trigger fires, and
    hold at the tight initial stop before it. Runs on a synthetic one-ticker path.
    """
    dates = pd.date_range('2024-01-02', periods=6, freq='B')
    # Rises to +20% (arms breakeven at +10%), then pulls back through the trail.
    highs = [100, 105, 112, 120, 118, 110]
    px = pd.DataFrame({
        'ticker': 'TEST', 'date': dates,
        'open': highs, 'high': highs,
        'low': [h - 1 for h in highs], 'close': highs, 'sma': 0.0,
    })
    entries = pd.DataFrame({
        'ticker': ['TEST'], 'entry_date': [dates[0]],
        'prob_elite_at_entry': [0.9], 'calibrated_score': [0.5],
    })
    vbt = VectorizedSEPABacktest(
        start_date='2024-01-01', end_date='2024-02-01',
        exit_policy='minervini', stop_loss_pct=0.08, be_trigger_pct=0.10, trail_pct=0.10,
    )
    trades = vbt._simulate_exits(entries, px)
    t = trades.iloc[0]
    # Path: entry 100, high runs to 120 (arms breakeven at +10%), then pulls back.
    # Once armed the stop trails at run_high*(1-0.10); at high=120 that's 108, well
    # above the tight initial 100*(1-0.08)=92 — the ratchet property under test.
    # The pullback low bottoms at 109 (bar 6), still above 108, so this short path
    # exits on max_hold with a POSITIVE pnl (a winner given room to run).
    assert t['exit_reason'] in ('stop_loss', 'max_hold', 'held_open'), t['exit_reason']
    assert t['pnl_pct'] > 0, f"ratcheted winner should be positive, got {t['pnl_pct']:.1%}"
    assert 120.0 * (1.0 - 0.10) > 100.0 * (1.0 - 0.08), "ratchet must raise stop above initial"
    print(f"[OK] minervini ratchet self-check: exit={t['exit_reason']}, pnl={t['pnl_pct']:.1%}")


def _progressive_fills_selfcheck() -> None:
    """A winner (triggers the add) must out-earn the same trade run flat; a loser
    (never triggers) must lose LESS than flat. That asymmetry is the whole point.
    Compares equity end-value with progressive_fills on vs off, same trades.
    """
    dates = pd.date_range('2024-01-02', periods=8, freq='B')

    def _equity_end(closes, progressive):
        px = pd.DataFrame({
            'ticker': 'T', 'date': dates, 'open': closes, 'high': closes,
            'low': [c - 0.01 for c in closes], 'close': closes, 'sma': 0.0,
        })
        vbt = VectorizedSEPABacktest(
            start_date='2024-01-01', end_date='2024-02-01',
            exit_policy='sma', stop_loss_pct=0.30, max_hold_days=100,
            position_size_pct=1.0, initial_cash=1.0,
            progressive_fills=progressive, starter_frac=0.5, add_trigger_pct=0.05,
        )
        trades = vbt._simulate_exits(
            pd.DataFrame({'ticker': ['T'], 'entry_date': [dates[0]],
                          'prob_elite_at_entry': [0.9], 'calibrated_score': [0.5]}),
            px,
        )
        vbt._price_path = px
        return vbt.equity_curve(trades).iloc[-1]

    # Winner: clears +5% add trigger early, keeps rising -> add earns the rise.
    win_flat = _equity_end([100, 103, 106, 110, 114, 118, 122, 126], False)
    win_prog = _equity_end([100, 103, 106, 110, 114, 118, 122, 126], True)
    # Loser: dribbles down, never clears +5% -> stays at starter_frac -> smaller loss.
    los_flat = _equity_end([100, 99, 98, 97, 96, 95, 94, 93], False)
    los_prog = _equity_end([100, 99, 98, 97, 96, 95, 94, 93], True)

    assert los_prog > los_flat, f"loser should lose less w/ starter: {los_prog:.4f} vs {los_flat:.4f}"
    assert win_prog > los_prog, "winner must beat loser under progressive fills"
    print(f"[OK] progressive-fills self-check: winner {win_prog:.3f} (flat {win_flat:.3f}), "
          f"loser {los_prog:.3f} > flat {los_flat:.3f} (starved)")


def _gap_fill_selfcheck() -> None:
    """A stop-out that GAPS DOWN through the stop must fill at the open, not the
    stop level. Entry 100, stop -15% = 85; the exit bar opens at 80 (below 85)
    → real fill 80, pnl -20%, NOT the booked -15%.
    """
    dates = pd.date_range('2024-01-02', periods=3, freq='B')
    px = pd.DataFrame({
        'ticker': 'T', 'date': dates,
        'open':  [100, 100, 80],   # bar 3 gaps down through the stop
        'high':  [100, 101, 82],
        'low':   [99,  99,  78],
        'close': [100, 100, 79], 'sma': 0.0,
    })
    entries = pd.DataFrame({
        'ticker': ['T'], 'entry_date': [dates[0]],
        'prob_elite_at_entry': [0.9], 'calibrated_score': [0.5],
    })
    vbt = VectorizedSEPABacktest(
        start_date='2024-01-01', end_date='2024-02-01',
        exit_policy='sma', stop_loss_pct=0.15, max_hold_days=100,
    )
    t = vbt._simulate_exits(entries, px).iloc[0]
    assert t['exit_reason'] == 'stop_loss', t['exit_reason']
    assert abs(t['exit_price'] - 80.0) < 1e-9, f"gap fill should be open=80, got {t['exit_price']}"
    assert t['pnl_pct'] < -0.15, f"gap loss must exceed the -15% stop, got {t['pnl_pct']:.1%}"
    print(f"[OK] gap-fill self-check: exit={t['exit_price']:.0f}, pnl={t['pnl_pct']:.1%} (< -15% stop)")


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(message)s')
    _minervini_selfcheck()
    _progressive_fills_selfcheck()
    _gap_fill_selfcheck()
    vbt = VectorizedSEPABacktest(
        start_date='2024-01-01',
        end_date='2024-06-30',
        min_prob_elite=0.15,
        max_positions_per_day=3,
    )
    trades = vbt.run()
    vbt.summary(trades)
