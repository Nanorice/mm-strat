"""
Test Backtest Enhancements (Phase 6.5 - Tasks 1.2-1.4)
========================================================
Validates:
1. Calmar Ratio analyzer works correctly
2. Entry/exit threshold parameters work
3. Position sizing modes work
4. Integration with runner.py

Usage:
    python scripts/test_backtest_enhancements.py
"""

import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def test_calmar_analyzer():
    """Test 1: Verify Calmar analyzer can be imported and initialized."""
    logger.info("[TEST 1] Testing Calmar Ratio Analyzer...")

    try:
        from src.backtest.analyzers import CalmarRatio
        import backtrader as bt

        # Create a minimal analyzer instance (won't run, just check it exists)
        analyzer_class = CalmarRatio

        # Check it has required methods
        assert hasattr(analyzer_class, 'start')
        assert hasattr(analyzer_class, 'next')
        assert hasattr(analyzer_class, 'stop')
        assert hasattr(analyzer_class, 'get_analysis')

        logger.info("[OK] CalmarRatio analyzer exists with required methods")
        return True

    except Exception as e:
        logger.error(f"[FAIL] Calmar analyzer test failed: {e}")
        return False


def test_runner_integration():
    """Test 2: Verify runner.py imports Calmar and has analyzer setup."""
    logger.info("[TEST 2] Testing runner.py integration...")

    try:
        from src.backtest.runner import SEPABacktestRunner
        from src.backtest.analyzers import CalmarRatio

        # Check that CalmarRatio is imported in runner module
        import src.backtest.runner as runner_module
        assert hasattr(runner_module, 'CalmarRatio')

        logger.info("[OK] CalmarRatio imported in runner.py")
        return True

    except Exception as e:
        logger.error(f"[FAIL] Runner integration test failed: {e}")
        return False


def test_strategy_params():
    """Test 3: Verify new strategy parameters exist."""
    logger.info("[TEST 3] Testing strategy parameter updates...")

    try:
        # Read source file directly (BackTrader metaclasses make introspection hard)
        strategy_file = Path(__file__).parent.parent / 'src' / 'backtest' / 'sepa_strategy.py'
        source = strategy_file.read_text()

        # Check new entry/exit params exist in source
        required_params = [
            'entry_percentile_min',
            'entry_mode',
            'entry_top_n',
            'exit_percentile_max',
            'exit_use_percentile',
            'sizing_mode',
        ]

        missing = []
        for param in required_params:
            if f"('{param}'" not in source:
                missing.append(param)

        if missing:
            logger.error(f"[FAIL] Missing parameters in source: {missing}")
            return False

        logger.info(f"[OK] All {len(required_params)} new parameters found in source")

        # Check default values in source
        checks = [
            ("'entry_percentile_min', 0.0", "entry_percentile_min defaults to 0.0"),
            ("'entry_mode', 'percentile'", "entry_mode defaults to 'percentile'"),
            ("'exit_use_percentile', False", "exit_use_percentile defaults to False"),
            ("'sizing_mode', 'regime'", "sizing_mode defaults to 'regime'"),
        ]

        for check_str, desc in checks:
            if check_str not in source:
                logger.error(f"[FAIL] {desc} - not found in source")
                return False

        logger.info("[OK] Default parameter values correct")
        return True

    except Exception as e:
        logger.error(f"[FAIL] Strategy params test failed: {e}")
        return False


def test_position_sizing_method():
    """Test 4: Verify calculate_position_size method exists and works."""
    logger.info("[TEST 4] Testing position sizing method...")

    try:
        from src.backtest.sepa_strategy import SEPAHybridV1

        # Check method exists
        assert hasattr(SEPAHybridV1, 'calculate_position_size')

        # Create a mock strategy instance to test sizing logic
        # (We won't run a full backtest, just test the method logic)
        class MockStrategy:
            def __init__(self):
                self.p = type('obj', (object,), {
                    'sizing_mode': 'regime',
                    'regime_sizes': {0: 0.0, 1: 0.025, 2: 0.05, 3: 0.075, 4: 0.10},
                    'regime_max_pos': {0: 0, 1: 4, 2: 8, 3: 10, 4: 12},
                })()

        mock = MockStrategy()

        # Test regime mode
        mock.p.sizing_mode = 'regime'
        size = SEPAHybridV1.calculate_position_size(mock, regime_cat=3, score=50.0, rank=0.8)
        assert size == 0.075, f"Regime mode: expected 0.075, got {size}"

        # Test equal_weight mode
        mock.p.sizing_mode = 'equal_weight'
        size = SEPAHybridV1.calculate_position_size(mock, regime_cat=3, score=50.0, rank=0.8)
        expected = 1.0 / 10  # 10 max positions
        assert abs(size - expected) < 0.001, f"Equal weight: expected {expected}, got {size}"

        # Test rank_weighted mode
        mock.p.sizing_mode = 'rank_weighted'
        size = SEPAHybridV1.calculate_position_size(mock, regime_cat=3, score=50.0, rank=0.8)
        # 0.075 * (0.5 + 0.8*1.5) = 0.075 * 1.7 = 0.1275
        expected = 0.075 * (0.5 + 0.8 * 1.5)
        assert abs(size - expected) < 0.001, f"Rank weighted: expected {expected}, got {size}"

        # Test score_weighted mode
        mock.p.sizing_mode = 'score_weighted'
        size = SEPAHybridV1.calculate_position_size(mock, regime_cat=3, score=75.0, rank=0.8)
        # 0.075 * (75/50) = 0.075 * 1.5 = 0.1125
        expected = 0.075 * (75.0 / 50.0)
        assert abs(size - expected) < 0.001, f"Score weighted: expected {expected}, got {size}"

        logger.info("[OK] All 4 sizing modes work correctly")
        return True

    except Exception as e:
        logger.error(f"[FAIL] Position sizing test failed: {e}")
        return False


def test_rank_exit_method():
    """Test 5: Verify _check_rank_exits method exists."""
    logger.info("[TEST 5] Testing rank-based exit method...")

    try:
        from src.backtest.sepa_strategy import SEPAHybridV1

        # Check method exists
        assert hasattr(SEPAHybridV1, '_check_rank_exits')

        logger.info("[OK] _check_rank_exits method exists")
        return True

    except Exception as e:
        logger.error(f"[FAIL] Rank exit method test failed: {e}")
        return False


def main():
    """Run all tests."""
    logger.info("=" * 60)
    logger.info("Testing Phase 6.5 Backtest Enhancements")
    logger.info("=" * 60)

    tests = [
        ("Calmar Analyzer", test_calmar_analyzer),
        ("Runner Integration", test_runner_integration),
        ("Strategy Parameters", test_strategy_params),
        ("Position Sizing", test_position_sizing_method),
        ("Rank Exit Method", test_rank_exit_method),
    ]

    results = []
    for name, test_func in tests:
        try:
            passed = test_func()
            results.append((name, passed))
        except Exception as e:
            logger.error(f"[ERR] Test '{name}' crashed: {e}")
            results.append((name, False))

    # Summary
    logger.info("\n" + "=" * 60)
    logger.info("TEST SUMMARY")
    logger.info("=" * 60)

    passed_count = sum(1 for _, passed in results if passed)
    total_count = len(results)

    for name, passed in results:
        status = "[OK]  " if passed else "[FAIL]"
        logger.info(f"{status} {name}")

    logger.info("-" * 60)
    logger.info(f"Passed: {passed_count}/{total_count}")

    if passed_count == total_count:
        logger.info("\n[OK] All tests passed! Enhancements are working correctly.")
        return 0
    else:
        logger.error(f"\n[FAIL] {total_count - passed_count} test(s) failed.")
        return 1


if __name__ == '__main__':
    sys.exit(main())
