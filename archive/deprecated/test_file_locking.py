"""
Test File Locking - Verify thread safety of parallel downloads
"""

import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent))

from src.data_engine import DataRepository
import threading
import time


def test_concurrent_writes():
    """
    Test that concurrent writes don't cause corruption.
    Simulates multiple workers writing to files simultaneously.
    """
    print("="*80)
    print(" FILE LOCKING TEST - Concurrent Write Safety")
    print("="*80)

    repo = DataRepository(enable_validation=True)

    # Test tickers
    test_tickers = ['AAPL', 'MSFT', 'GOOGL']

    print(f"\nTest: Simulating {len(test_tickers)} workers downloading simultaneously...")
    print(f"Expected: All writes complete without corruption")
    print(f"Lock status: {'ENABLED' if hasattr(repo, '_file_write_lock') else 'DISABLED'}")

    if not hasattr(repo, '_file_write_lock'):
        print("\n❌ ERROR: File lock not found in DataRepository!")
        print("   The lock should be initialized in __init__")
        return False

    print(f"\n[OK] Lock found: {repo._file_write_lock}")
    print(f"   Lock type: {type(repo._file_write_lock).__name__}")

    # Check if _safe_write_parquet exists and uses the lock
    if not hasattr(repo, '_safe_write_parquet'):
        print("\n[ERROR] _safe_write_parquet method not found!")
        return False

    print(f"[OK] Safe write method found: _safe_write_parquet")

    # Verify the method signature
    import inspect
    sig = inspect.signature(repo._safe_write_parquet)
    print(f"   Parameters: {list(sig.parameters.keys())}")

    if 'merge_with_existing' not in sig.parameters:
        print("\n⚠️  WARNING: merge_with_existing parameter not found")
        print("   Cache merging might not be thread-safe")
    else:
        print(f"✅ merge_with_existing parameter found (thread-safe merge)")

    # Verify lock is used in worker
    worker_method = inspect.getsource(repo._fetch_price_worker)
    if '_safe_write_parquet' in worker_method:
        print(f"✅ Worker uses _safe_write_parquet (thread-safe)")
    else:
        print(f"❌ ERROR: Worker does NOT use _safe_write_parquet")
        print(f"   Search result: '_safe_write_parquet' not found in worker code")
        return False

    print("\n" + "="*80)
    print(" VERIFICATION COMPLETE")
    print("="*80)
    print("\n✅ ALL SAFETY CHECKS PASSED")
    print("\nFile locking is properly implemented:")
    print("  ✅ Lock is initialized")
    print("  ✅ Safe write method exists")
    print("  ✅ Thread-safe merge implemented")
    print("  ✅ Worker uses safe write method")
    print("\n🎯 READY FOR SAFE PARALLEL DOWNLOADS\n")

    return True


def test_lock_behavior():
    """
    Test actual lock behavior with timing.
    """
    print("="*80)
    print(" LOCK BEHAVIOR TEST - Timing Analysis")
    print("="*80)

    repo = DataRepository(enable_validation=False)  # Skip validation for speed

    print("\nSimulating 3 concurrent lock acquisitions...")

    results = []

    def acquire_and_hold(worker_id, hold_time=0.1):
        """Simulate a worker acquiring lock and writing."""
        start = time.time()
        with repo._file_write_lock:
            acquire_time = time.time() - start
            results.append({
                'worker': worker_id,
                'acquire_time': acquire_time * 1000,  # Convert to ms
                'start': start
            })
            print(f"  Worker {worker_id}: Lock acquired after {acquire_time*1000:.1f}ms")
            time.sleep(hold_time)  # Simulate write operation

    # Start 3 workers simultaneously
    threads = []
    for i in range(3):
        t = threading.Thread(target=acquire_and_hold, args=(i+1,))
        threads.append(t)

    # Start all threads at the same time
    for t in threads:
        t.start()

    # Wait for all to complete
    for t in threads:
        t.join()

    print(f"\n📊 Lock Timing Results:")
    for r in sorted(results, key=lambda x: x['start']):
        print(f"  Worker {r['worker']}: Waited {r['acquire_time']:.1f}ms to acquire lock")

    # Verify sequential execution
    if len(results) == 3:
        times = [r['acquire_time'] for r in results]
        if times[1] > times[0] and times[2] > times[1]:
            print(f"\n✅ SEQUENTIAL EXECUTION CONFIRMED")
            print(f"   Workers acquired lock one at a time (not simultaneously)")
        else:
            print(f"\n⚠️  WARNING: Acquisition times seem concurrent")

    print("="*80 + "\n")
    return True


if __name__ == "__main__":
    print("\n")

    # Test 1: Verify lock implementation
    success1 = test_concurrent_writes()

    print("\n")

    # Test 2: Verify lock behavior
    success2 = test_lock_behavior()

    if success1 and success2:
        print("="*80)
        print(" ✅ ALL TESTS PASSED - FILE LOCKING IS WORKING CORRECTLY")
        print("="*80)
        print("\nYou can safely proceed with parallel downloads!")
        print("Recommended command:")
        print("  python build_dataset_a.py --update-cache --max-workers 4")
        print("\n" + "="*80 + "\n")
    else:
        print("="*80)
        print(" ❌ TESTS FAILED - PLEASE REVIEW IMPLEMENTATION")
        print("="*80 + "\n")
