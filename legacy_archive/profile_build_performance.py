"""
Performance profiling and optimization analysis for build_dataset_a.py

Analyzes:
1. Time bottlenecks in the pipeline
2. Memory usage patterns
3. I/O efficiency (disk, network)
4. Parallelization effectiveness
5. Data serialization overhead
"""

import time
import psutil
import pandas as pd
import numpy as np
from pathlib import Path
from typing import Dict, List, Tuple
import logging
import sys

sys.path.append(str(Path(__file__).parent))
import config
from src.data_engine import DataRepository
from src.features import FeatureEngineer
from src.fundamental_merger import FundamentalMerger

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class BuildProfiler:
    """Profile the dataset build process to identify optimization opportunities."""

    def __init__(self):
        self.process = psutil.Process()
        self.timings = {}
        self.memory_snapshots = {}

    def measure_time(self, label: str):
        """Context manager for timing code blocks."""
        class Timer:
            def __init__(self, profiler, label):
                self.profiler = profiler
                self.label = label
                self.start = None

            def __enter__(self):
                self.start = time.time()
                return self

            def __exit__(self, *args):
                elapsed = time.time() - self.start
                self.profiler.timings[self.label] = elapsed
                logger.info(f"⏱️  {self.label}: {elapsed:.2f}s")

        return Timer(self, label)

    def snapshot_memory(self, label: str):
        """Record current memory usage."""
        mem_info = self.process.memory_info()
        rss_mb = mem_info.rss / (1024 * 1024)
        vms_mb = mem_info.vms / (1024 * 1024)

        self.memory_snapshots[label] = {
            'rss_mb': rss_mb,
            'vms_mb': vms_mb,
            'available_mb': psutil.virtual_memory().available / (1024 * 1024)
        }
        logger.info(f"💾 {label}: RSS={rss_mb:.1f}MB, Available={self.memory_snapshots[label]['available_mb']:.1f}MB")

    def profile_data_loading(self, sample_tickers: List[str]) -> Dict:
        """Profile the data loading phase."""
        logger.info("\n" + "="*80)
        logger.info("PHASE 1: DATA LOADING ANALYSIS")
        logger.info("="*80)

        results = {}
        data_repo = DataRepository()

        # Test 1: Single ticker load time
        with self.measure_time("Load single ticker (cache)"):
            df = data_repo.get_ticker_data(sample_tickers[0], use_cache=True)
        results['single_ticker_load_time'] = self.timings["Load single ticker (cache)"]
        results['single_ticker_rows'] = len(df) if df is not None else 0

        # Test 2: Batch loading (sequential vs parallel)
        batch_size = min(50, len(sample_tickers))
        batch = sample_tickers[:batch_size]

        with self.measure_time(f"Batch load {batch_size} tickers (parallel, max_workers=8)"):
            batch_data = data_repo.get_batch_data(batch, max_workers=8, show_progress=False)
        results['batch_parallel_time'] = self.timings[f"Batch load {batch_size} tickers (parallel, max_workers=8)"]
        results['batch_size'] = batch_size
        results['throughput_tickers_per_sec'] = batch_size / results['batch_parallel_time']

        # Test 3: Parquet read performance
        cache_file = config.PRICE_DATA_DIR / f"{sample_tickers[0]}.parquet"
        if cache_file.exists():
            file_size_mb = cache_file.stat().st_size / (1024 * 1024)

            with self.measure_time("Parquet read (single file)"):
                df = pd.read_parquet(cache_file)

            results['parquet_read_time'] = self.timings["Parquet read (single file)"]
            results['parquet_file_size_mb'] = file_size_mb
            results['parquet_throughput_mb_per_sec'] = file_size_mb / results['parquet_read_time']

        logger.info(f"\n📊 Data Loading Results:")
        logger.info(f"  Single ticker: {results['single_ticker_load_time']*1000:.1f}ms ({results['single_ticker_rows']} rows)")
        logger.info(f"  Batch ({batch_size} tickers): {results['batch_parallel_time']:.2f}s")
        logger.info(f"  Throughput: {results['throughput_tickers_per_sec']:.1f} tickers/sec")
        if 'parquet_throughput_mb_per_sec' in results:
            logger.info(f"  Parquet I/O: {results['parquet_throughput_mb_per_sec']:.1f} MB/sec")

        return results

    def profile_feature_calculation(self, sample_df: pd.DataFrame, ticker: str) -> Dict:
        """Profile feature engineering performance."""
        logger.info("\n" + "="*80)
        logger.info("PHASE 2: FEATURE CALCULATION ANALYSIS")
        logger.info("="*80)

        results = {}
        data_repo = DataRepository()
        benchmark_data = data_repo.get_benchmark_data()
        feature_engine = FeatureEngineer(benchmark_data=benchmark_data)

        # Test 1: Lightweight features
        self.snapshot_memory("Before lightweight features")
        with self.measure_time("Lightweight features"):
            df_light = feature_engine.calculate_lightweight_features(sample_df.copy())
        self.snapshot_memory("After lightweight features")

        results['lightweight_time'] = self.timings["Lightweight features"]
        results['lightweight_time_per_row'] = results['lightweight_time'] / len(sample_df) * 1000
        results['num_lightweight_features'] = len(df_light.columns) - len(sample_df.columns)

        # Test 2: Heavyweight features
        self.snapshot_memory("Before heavyweight features")
        with self.measure_time("Heavyweight features"):
            df_heavy = feature_engine.calculate_heavyweight_features(df_light.copy(), ticker)
        self.snapshot_memory("After heavyweight features")

        results['heavyweight_time'] = self.timings["Heavyweight features"]
        results['heavyweight_time_per_row'] = results['heavyweight_time'] / len(sample_df) * 1000
        results['num_heavyweight_features'] = len(df_heavy.columns) - len(df_light.columns)

        # Calculate overhead
        total_feature_time = results['lightweight_time'] + results['heavyweight_time']
        results['total_feature_time'] = total_feature_time
        results['feature_overhead_pct'] = (total_feature_time / results['lightweight_time'] - 1) * 100

        logger.info(f"\n📊 Feature Calculation Results:")
        logger.info(f"  Lightweight: {results['lightweight_time']*1000:.1f}ms ({results['num_lightweight_features']} features)")
        logger.info(f"  Heavyweight: {results['heavyweight_time']*1000:.1f}ms ({results['num_heavyweight_features']} features)")
        logger.info(f"  Per-row cost: Lightweight={results['lightweight_time_per_row']:.3f}ms, Heavyweight={results['heavyweight_time_per_row']:.3f}ms")
        logger.info(f"  Heavyweight overhead: +{results['feature_overhead_pct']:.1f}%")

        return results

    def profile_fundamental_merge(self, sample_df: pd.DataFrame, ticker: str) -> Dict:
        """Profile fundamental data merge performance."""
        logger.info("\n" + "="*80)
        logger.info("PHASE 3: FUNDAMENTAL MERGE ANALYSIS")
        logger.info("="*80)

        results = {}
        fundamental_merger = FundamentalMerger(force_cache_only=True)

        self.snapshot_memory("Before fundamental merge")
        with self.measure_time("Fundamental merge"):
            df_merged = fundamental_merger.merge_ticker_data(ticker, sample_df.copy())
        self.snapshot_memory("After fundamental merge")

        results['merge_time'] = self.timings["Fundamental merge"]
        results['merge_time_per_row'] = results['merge_time'] / len(sample_df) * 1000
        results['num_fundamental_cols'] = len(df_merged.columns) - len(sample_df.columns)

        logger.info(f"\n📊 Fundamental Merge Results:")
        logger.info(f"  Merge time: {results['merge_time']*1000:.1f}ms")
        logger.info(f"  Per-row cost: {results['merge_time_per_row']:.3f}ms")
        logger.info(f"  Fundamental columns added: {results['num_fundamental_cols']}")

        return results

    def profile_concatenation(self, sample_dfs: List[pd.DataFrame]) -> Dict:
        """Profile DataFrame concatenation performance."""
        logger.info("\n" + "="*80)
        logger.info("PHASE 4: CONCATENATION ANALYSIS")
        logger.info("="*80)

        results = {}

        # Test different concatenation strategies
        total_rows = sum(len(df) for df in sample_dfs)

        # Strategy 1: Simple concat
        self.snapshot_memory("Before concat (simple)")
        with self.measure_time("Concat (simple)"):
            df_concat = pd.concat(sample_dfs, ignore_index=True)
        self.snapshot_memory("After concat (simple)")

        results['simple_concat_time'] = self.timings["Concat (simple)"]
        results['simple_concat_mb_per_sec'] = (df_concat.memory_usage(deep=True).sum() / (1024*1024)) / results['simple_concat_time']

        # Strategy 2: Concat with copy=False
        with self.measure_time("Concat (copy=False)"):
            df_concat_nocopy = pd.concat(sample_dfs, ignore_index=True, copy=False)

        results['nocopy_concat_time'] = self.timings["Concat (copy=False)"]
        results['nocopy_speedup'] = results['simple_concat_time'] / results['nocopy_concat_time']

        logger.info(f"\n📊 Concatenation Results:")
        logger.info(f"  Simple concat: {results['simple_concat_time']:.2f}s ({total_rows:,} rows)")
        logger.info(f"  Throughput: {results['simple_concat_mb_per_sec']:.1f} MB/sec")
        logger.info(f"  copy=False speedup: {results['nocopy_speedup']:.2f}x")

        return results

    def profile_serialization(self, sample_df: pd.DataFrame) -> Dict:
        """Profile different serialization formats."""
        logger.info("\n" + "="*80)
        logger.info("PHASE 5: SERIALIZATION ANALYSIS")
        logger.info("="*80)

        results = {}
        temp_dir = Path("temp_profile")
        temp_dir.mkdir(exist_ok=True)

        # Test 1: Parquet (default)
        with self.measure_time("Write parquet (default)"):
            sample_df.to_parquet(temp_dir / "test_default.parquet")
        results['parquet_default_time'] = self.timings["Write parquet (default)"]
        results['parquet_default_size_mb'] = (temp_dir / "test_default.parquet").stat().st_size / (1024*1024)

        # Test 2: Parquet (snappy compression)
        with self.measure_time("Write parquet (snappy)"):
            sample_df.to_parquet(temp_dir / "test_snappy.parquet", compression='snappy')
        results['parquet_snappy_time'] = self.timings["Write parquet (snappy)"]
        results['parquet_snappy_size_mb'] = (temp_dir / "test_snappy.parquet").stat().st_size / (1024*1024)

        # Test 3: Parquet (gzip compression)
        with self.measure_time("Write parquet (gzip)"):
            sample_df.to_parquet(temp_dir / "test_gzip.parquet", compression='gzip')
        results['parquet_gzip_time'] = self.timings["Write parquet (gzip)"]
        results['parquet_gzip_size_mb'] = (temp_dir / "test_gzip.parquet").stat().st_size / (1024*1024)

        # Test 4: Read performance
        with self.measure_time("Read parquet (snappy)"):
            df_read = pd.read_parquet(temp_dir / "test_snappy.parquet")
        results['parquet_snappy_read_time'] = self.timings["Read parquet (snappy)"]

        # Cleanup
        import shutil
        shutil.rmtree(temp_dir)

        logger.info(f"\n📊 Serialization Results:")
        logger.info(f"  Parquet default: {results['parquet_default_time']:.2f}s, {results['parquet_default_size_mb']:.1f}MB")
        logger.info(f"  Parquet snappy: {results['parquet_snappy_time']:.2f}s, {results['parquet_snappy_size_mb']:.1f}MB")
        logger.info(f"  Parquet gzip: {results['parquet_gzip_time']:.2f}s, {results['parquet_gzip_size_mb']:.1f}MB")
        logger.info(f"  Read (snappy): {results['parquet_snappy_read_time']:.2f}s")
        logger.info(f"  Compression ratio (snappy): {results['parquet_default_size_mb']/results['parquet_snappy_size_mb']:.2f}x")

        return results

    def generate_report(self) -> str:
        """Generate comprehensive optimization report."""
        report = []
        report.append("\n" + "="*80)
        report.append("OPTIMIZATION RECOMMENDATIONS")
        report.append("="*80)

        report.append("\n## Memory Optimization:")
        mem_deltas = []
        labels = list(self.memory_snapshots.keys())
        for i in range(1, len(labels)):
            prev = self.memory_snapshots[labels[i-1]]['rss_mb']
            curr = self.memory_snapshots[labels[i]]['rss_mb']
            delta = curr - prev
            mem_deltas.append((labels[i], delta))

        mem_deltas.sort(key=lambda x: x[1], reverse=True)
        for label, delta in mem_deltas[:5]:
            report.append(f"  • {label}: +{delta:.1f}MB")

        report.append("\n## Time Optimization:")
        time_sorted = sorted(self.timings.items(), key=lambda x: x[1], reverse=True)
        for label, time_val in time_sorted[:5]:
            report.append(f"  • {label}: {time_val:.2f}s")

        return "\n".join(report)


def main():
    """Run comprehensive profiling."""
    print("="*80)
    print(" BUILD PERFORMANCE PROFILER")
    print("="*80)

    profiler = BuildProfiler()
    data_repo = DataRepository()

    # Get sample tickers
    print("\nLoading ticker universe...")
    from src.utils import filter_etfs
    tickers = data_repo.update_universe()
    tickers = filter_etfs(tickers)

    # Use a representative sample
    sample_size = min(100, len(tickers))
    sample_tickers = tickers[:sample_size]
    print(f"Using {sample_size} sample tickers for profiling\n")

    profiler.snapshot_memory("Initial")

    # Phase 1: Data Loading
    load_results = profiler.profile_data_loading(sample_tickers)

    # Phase 2: Feature Calculation (use first ticker)
    sample_df = data_repo.get_ticker_data(sample_tickers[0], use_cache=True)
    if sample_df is not None and not sample_df.empty:
        feature_results = profiler.profile_feature_calculation(sample_df, sample_tickers[0])

        # Phase 3: Fundamental Merge
        fund_results = profiler.profile_fundamental_merge(sample_df, sample_tickers[0])

        # Phase 4: Concatenation (create sample)
        sample_dfs = []
        for ticker in sample_tickers[:20]:
            df = data_repo.get_ticker_data(ticker, use_cache=True)
            if df is not None and not df.empty:
                sample_dfs.append(df)

        if sample_dfs:
            concat_results = profiler.profile_concatenation(sample_dfs)

        # Phase 5: Serialization
        serialization_results = profiler.profile_serialization(sample_df)

    profiler.snapshot_memory("Final")

    # Generate report
    report = profiler.generate_report()
    print(report)

    # Calculate projected full build time
    print("\n" + "="*80)
    print("PROJECTED FULL BUILD PERFORMANCE (2350 tickers)")
    print("="*80)

    total_tickers = 2350
    if 'throughput_tickers_per_sec' in load_results:
        load_time = total_tickers / load_results['throughput_tickers_per_sec']
        print(f"\nData Loading: ~{load_time:.1f}s ({load_time/60:.1f} min)")

    if 'total_feature_time' in feature_results:
        feature_time_per_ticker = feature_results['total_feature_time']
        # With 10 workers, approximate parallelization
        feature_time_total = (total_tickers * feature_time_per_ticker) / 10
        print(f"Feature Engineering (10 workers): ~{feature_time_total:.1f}s ({feature_time_total/60:.1f} min)")

    if 'merge_time' in fund_results:
        merge_time_per_ticker = fund_results['merge_time']
        merge_time_total = (total_tickers * merge_time_per_ticker) / 10
        print(f"Fundamental Merge (10 workers): ~{merge_time_total:.1f}s ({merge_time_total/60:.1f} min)")

    if 'simple_concat_time' in concat_results:
        # Estimate based on sample
        concat_scale = total_tickers / len(sample_dfs)
        concat_time = concat_results['simple_concat_time'] * concat_scale
        print(f"Concatenation: ~{concat_time:.1f}s ({concat_time/60:.1f} min)")

    total_time = load_time + feature_time_total + merge_time_total + concat_time
    print(f"\n🎯 ESTIMATED TOTAL TIME: ~{total_time:.1f}s ({total_time/60:.1f} min)")

    print("\n✅ Profiling complete!")


if __name__ == "__main__":
    main()
