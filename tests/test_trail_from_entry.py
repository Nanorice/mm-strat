"""R3b — rising-trail-from-entry stop logic (position_tracker.update_stops).

The tail-harvesting exit relies on a stop that ratchets up from the first bar when
trail_from_entry_atr > 0 (no tranche take-profit engages the legacy trail). Guards:
off by default (legacy behavior), ratchets up, never below the initial stop.
"""
from src.backtest.position_tracker import PositionTracker


def _pos(tracker, entry=100.0, stop=90.0):
    tracker.positions.clear()
    tracker.register_entry_intent(order_ref=1, intent={
        "ticker": "T", "entry_date": None, "entry_atr": 2.0, "initial_size": 100,
        "full_target_size": 100, "add_trigger_price": 0.0, "initial_stop": stop,
        "target1": 130.0, "target2": 150.0, "score": 1.0, "trailing_pct": 1.0, "regime": 2,
    })
    tracker.confirm_entry(order_ref=1, executed_price=entry, executed_size=100)
    return tracker.positions["T"]


def test_off_by_default_keeps_initial_stop():
    t = PositionTracker()
    _pos(t, entry=100.0, stop=90.0)
    # Big favorable move, but trail off (legacy) and no tranche sold -> stop unchanged.
    assert t.update_stops("T", current_atr=2.0, current_high=120.0) is None
    assert t.positions["T"].current_stop == 90.0


def test_from_entry_ratchets_up():
    t = PositionTracker()
    _pos(t, entry=100.0, stop=90.0)
    # high 120, 1.5*ATR(2)=3 -> new stop 117 > initial 90 -> engages.
    t.update_stops("T", current_atr=2.0, current_high=120.0, trail_from_entry_atr=1.5)
    assert t.positions["T"].current_stop == 117.0
    # A lower high must NOT move the stop down (high-water mark).
    t.update_stops("T", current_atr=2.0, current_high=110.0, trail_from_entry_atr=1.5)
    assert t.positions["T"].current_stop == 117.0


def test_from_entry_never_below_initial():
    t = PositionTracker()
    _pos(t, entry=100.0, stop=90.0)
    # Early bar barely above entry: high 101, trail 1.5*2=3 -> 98 < initial 90? no, 98>90
    # so pick a case where high-trail < initial: high 92, trail -> 89 < 90 -> ignored.
    assert t.update_stops("T", current_atr=2.0, current_high=92.0, trail_from_entry_atr=1.5) is None
    assert t.positions["T"].current_stop == 90.0


if __name__ == "__main__":
    test_off_by_default_keeps_initial_stop()
    test_from_entry_ratchets_up()
    test_from_entry_never_below_initial()
    print("OK — trail-from-entry stop logic")
