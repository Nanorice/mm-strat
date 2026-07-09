"""Progressive-fill scale-in state math (PositionTracker level).

The BackTrader money path: starter fill on entry, add grows remaining_shares and
blends the cost basis, tranche_size keys off the FINAL target. Default off must be
byte-identical to the pre-change behaviour.
"""
from datetime import date

from src.backtest.position_tracker import PositionTracker


def _intent(full_target, starter, add_trigger_price):
    return {
        'ticker': 'T', 'entry_date': date(2024, 1, 2), 'entry_atr': 1.0,
        'initial_size': starter, 'full_target_size': full_target,
        'add_trigger_price': add_trigger_price, 'initial_stop': 92.0,
        'target1': 115.0, 'target2': 120.0, 'score': 50.0, 'regime': 3,
    }


def test_default_off_is_unchanged():
    # No prog-fills fields => remaining_shares == executed_size, added True, tranche off final.
    pt = PositionTracker()
    pt.register_entry_intent(1, {
        'ticker': 'T', 'entry_date': date(2024, 1, 2), 'entry_atr': 1.0,
        'initial_size': 99, 'initial_stop': 92.0, 'target1': 115.0,
        'target2': 120.0, 'score': 50.0, 'regime': 3,
    })
    pos = pt.confirm_entry(1, executed_price=100.0, executed_size=99)
    assert pos.remaining_shares == 99
    assert pos.initial_size == 99
    assert pos.added is True and pos.add_target_shares == 0
    assert pos.tranche_size == 33  # 99 // 3


def test_starter_then_add_blends_and_keeps_tranche_on_final():
    pt = PositionTracker()
    # full target 100, starter 50, add trigger at 105.
    pt.register_entry_intent(1, _intent(full_target=100, starter=50, add_trigger_price=105.0))
    pos = pt.confirm_entry(1, executed_price=100.0, executed_size=50)
    # Starts at the starter size; remainder pending; tranche keyed off FINAL 100.
    assert pos.remaining_shares == 50
    assert pos.initial_size == 100 and pos.tranche_size == 33  # 100 // 3, NOT 50//3
    assert pos.added is False and pos.add_target_shares == 50

    # Add fills 50 @ 110 -> total 100, blended entry (100*50 + 110*50)/100 = 105.
    ok = pt.confirm_add('T', executed_price=110.0, executed_size=50)
    assert ok
    assert pos.remaining_shares == 100
    assert abs(pos.entry_price - 105.0) < 1e-9
    assert pos.added is True and pos.add_target_shares == 0


def test_loser_never_adds_stays_small():
    # A position whose add never fires keeps only the starter — the starve-losers half.
    pt = PositionTracker()
    pt.register_entry_intent(1, _intent(full_target=100, starter=50, add_trigger_price=105.0))
    pos = pt.confirm_entry(1, executed_price=100.0, executed_size=50)
    # Exit the starter at a loss BEFORE any add. Loss is on 50 shares, not 100.
    pt.record_partial_exit('T', shares_sold=50, exit_price=92.0, exit_reason='stop',
                           exit_date=date(2024, 1, 10))
    assert pos.is_closed
    assert pos.remaining_shares == 0
    # Never scaled up: the add target was still pending at exit.
    assert pos.added is False


if __name__ == '__main__':
    test_default_off_is_unchanged()
    test_starter_then_add_blends_and_keeps_tranche_on_final()
    test_loser_never_adds_stays_small()
    print('[OK] progressive-fill state math')
