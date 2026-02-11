#!/usr/bin/env python3
"""
Model Training CLI (Clean Interface)
=====================================

Simplified CLI for ML model training using the pipeline module.

Usage:
    # M01 (Regression - predicts expected return %)
    python model_runner.py m01 --start 2020-01-01 --end 2023-12-31

    # M01 Ranker (Pairwise ranking - cross-sectional ordering by date)
    python model_runner.py m01rank --start 2020-01-01 --end 2023-12-31

    # M02 (Classification - predicts ignition probability)
    python model_runner.py m02 --start 2020-01-01 --end 2023-12-31 --horizon 120

    # M03 (Market Regime - calculates risk score 0-100)
    python model_runner.py m03                         # Current regime
    python model_runner.py m03 --date 2024-01-15       # Regime as of date
    python model_runner.py m03 --history --start 2020-01-01 --end 2024-12-31

    # Run specific steps only
    python model_runner.py m01 --steps scan features  # Data prep only
    python model_runner.py m02 --steps train          # Train using existing data

    # Automated workflow (EDA + Selection + Train + Report)
    python model_runner.py workflow --start 2020-01-01 --end 2023-12-31
    python model_runner.py workflow --steps eda select  # EDA only, no training

For legacy CLI with more options, use: python model_trainer.py
"""

import argparse
import logging
import sys
from pathlib import Path

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("model.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("model")


def run_m01_pipeline(args):
    """Run M01 (regression) training pipeline."""
    from src.pipeline import DataPipeline, M01Trainer
    
    print("\n" + "=" * 70)
    print(" M01 PIPELINE (Return Regressor)")
    print("=" * 70)
    print(f"   Date Range: {args.start} to {args.end}")
    print(f"   Steps: {args.steps}")
    print(f"   Target: {args.target}")
    if args.survivor:
        print(f"   Survivor Model: ENABLED (stop mult: {getattr(args, 'stop_mult', 2.0)})")
    print("=" * 70 + "\n")
    
    pipeline = DataPipeline()
    
    # Step 1: Scan (generate D1)
    if 'scan' in args.steps:
        d1 = pipeline.scan(args.start, args.end, threshold=args.threshold)
    elif 'features' in args.steps or 'train' in args.steps:
        d1 = pipeline.load_d1()
    
    # Step 2: Features (generate D2)
    if 'features' in args.steps:
        d2 = pipeline.features(d1, n_jobs=args.jobs)
    elif 'train' in args.steps:
        d2 = pipeline.load_d2()
    
    # Step 3: Train M01
    if 'train' in args.steps:
        trainer = M01Trainer(
            feature_set=getattr(args, 'feature_set', None),
            model_name=getattr(args, 'model_name', None)
        )
        model, metrics = trainer.train(
            d2, 
            tune=args.tune,
            target=args.target,
            survivor_model=args.survivor,
            stop_multiplier=getattr(args, 'stop_mult', 2.0)
        )
        trainer.save(model, metrics)
        print(f"\n[OK] Model saved to models/{trainer.model_name.lower()}.json")

        # Calibrate if requested
        if getattr(args, 'calibrate', False):
            print("\n[CALIBRATION] Running isotonic calibration...")
            cal_results = trainer.calibrate()
            calibrator_path = trainer.save_calibrator()
            print(f"[OK] Calibrator saved to {calibrator_path}")

            # Save calibration JSON
            import json
            from datetime import datetime
            cal_data = {
                'generated_at': datetime.now().isoformat(),
                'model_name': trainer.model_name,
                'n_samples': int(cal_results['n_samples']),
                'n_bins': cal_results['n_bins'],
                'is_monotonic': cal_results['is_monotonic'],
                'calibration_error': float(cal_results['calibration_error']),
                'deciles': trainer._calibration_table.to_dict('records')
            }
            cal_json_path = trainer.get_model_dir() / 'calibration.json'
            with open(cal_json_path, 'w') as f:
                json.dump(cal_data, f, indent=2)
            print(f"[OK] Calibration data saved to {cal_json_path}")

        # Generate report if requested
        if args.report:
            report_path = trainer.generate_report(
                model, metrics,
                start_date=args.start,
                end_date=args.end
            )
            print(f"[OK] Report saved to {report_path}")


def run_m01_ranker_pipeline(args):
    """Run M01 Ranker (pairwise ranking) training pipeline."""
    from src.pipeline import DataPipeline, M01RankerTrainer

    print("\n" + "=" * 70)
    print(" M01 RANKER PIPELINE (Pairwise Cross-Sectional Ranking)")
    print("=" * 70)
    print(f"   Date Range: {args.start} to {args.end}")
    print(f"   Steps: {args.steps}")
    print(f"   Target: {args.target}")
    print(f"   Objective: rank:pairwise (groups by date)")
    print("=" * 70 + "\n")

    pipeline = DataPipeline()

    # Step 1: Scan (generate D1)
    if 'scan' in args.steps:
        d1 = pipeline.scan(args.start, args.end, threshold=args.threshold)
    elif 'features' in args.steps or 'train' in args.steps:
        d1 = pipeline.load_d1()

    # Step 2: Features (generate D2)
    if 'features' in args.steps:
        d2 = pipeline.features(d1, n_jobs=args.jobs)
    elif 'train' in args.steps:
        d2 = pipeline.load_d2()

    # Step 3: Train M01 Ranker
    if 'train' in args.steps:
        trainer = M01RankerTrainer(
            feature_set=getattr(args, 'feature_set', None),
            model_name=getattr(args, 'model_name', None)
        )
        model, metrics = trainer.train(
            d2,
            tune=args.tune,
            target=args.target,
            min_group_size=getattr(args, 'min_group_size', 5)
        )
        trainer.save(model, metrics)
        print(f"\n[OK] Ranker saved to models/{trainer.model_name.lower()}/model.json")

        # Generate report if requested
        if args.report:
            report_path = trainer.generate_report(
                model, metrics,
                start_date=args.start,
                end_date=args.end
            )
            print(f"[OK] Report saved to {report_path}")


def run_workflow(args):
    """Run automated M01 workflow (EDA + Selection + Train + Report)."""
    from src.pipeline.m01_workflow import M01Workflow, WorkflowConfig

    # Build config from args
    # Leave empty to auto-discover all numeric columns from d2_features
    # FeatureScreener.pre_filter_features() will handle the discovery
    candidate_features = args.features if args.features else []

    config = WorkflowConfig(
        start_date=args.start,
        end_date=args.end,
        candidate_features=candidate_features,
        ks_threshold=args.ks_threshold,
        correlation_threshold=getattr(args, 'correlation_threshold', 0.7),
        auto_select=not args.no_auto_select,
        fast_eda=getattr(args, 'fast_eda', False),
        exclude_m03=getattr(args, 'exclude_m03', False),
        enrich_mfe=getattr(args, 'enrich_mfe', False),
        eda_target=getattr(args, 'eda_target', 'return_pct'),
        target_type=args.target,
        tune=args.tune,
        n_jobs=args.jobs,
        generate_report=True
    )

    workflow = M01Workflow(config)
    results = workflow.run(steps=args.steps)

    # Print final summary
    if 'metrics' in results:
        m = results['metrics']
        print(f"\nWorkflow complete. IC: {m.get('avg_ic', 0):.3f}")


def run_m03_pipeline(args):
    """Run M03 (regime) calculation."""
    from src.pipeline.m03_regime import M03RegimeCalculator

    print("\n" + "=" * 70)
    print(" M03 PIPELINE (Market Regime)")
    print("=" * 70)

    calc = M03RegimeCalculator()

    if args.history:
        # Historical regime calculation
        print(f"   Date Range: {args.start} to {args.end}")
        print(f"   Frequency: {args.freq}")
        print(f"   Lag: T+1 (FRED publication delay)")
        print("=" * 70 + "\n")

        df = calc.calculate_history(args.start, args.end, freq=args.freq)

        if df.empty:
            print("❌ No regime data calculated. Check data availability.")
            return

        # Summary statistics
        print("\n[REGIME DISTRIBUTION]")
        print("-" * 40)
        cat_counts = df['category'].value_counts()
        for cat, count in cat_counts.items():
            pct = count / len(df) * 100
            print(f"   {cat:15s}: {count:4d} ({pct:5.1f}%)")

        print(f"\n   Average Score: {df['score'].mean():.1f}")
        print(f"   Score Range: {df['score'].min():.1f} - {df['score'].max():.1f}")

        # Save output
        output_path = calc.save_history(df, args.output)
        print(f"\n[OK] History saved to {output_path}")

        # Also save CSV if requested
        if args.csv and args.output.endswith('.parquet'):
            csv_path = args.output.replace('.parquet', '.csv')
            calc.save_history(df, csv_path, format='csv')
            print(f"[OK] CSV also saved to {csv_path}")

        # Show recent regimes
        print("\n[RECENT REGIMES] (last 10)")
        print("-" * 60)
        recent = df.tail(10)
        for idx, row in recent.iterrows():
            date_str = idx.strftime('%Y-%m-%d')
            print(f"   {date_str}  Score: {row['score']:5.1f}  [{row['category']:12s}]")

    else:
        # Single date calculation (current or specified)
        as_of = args.date
        print(f"   As of: {as_of or 'latest'}")
        print("=" * 70 + "\n")

        result = calc.calculate(as_of_date=as_of)

        # Display results
        print(f"\n[REGIME] Score: {result['score']} / 100")
        print(f"   Category: {result['category'].upper()}")
        print(f"   Date: {result['date']}")

        print("\n[PILLARS]")
        print("-" * 50)
        for name, pillar in result['pillars'].items():
            weight_pct = pillar['weight'] * 100
            print(f"   {name.replace('_', ' ').title():20s}: {pillar['score']:5.1f} (weight: {weight_pct:.0f}%)")

        # Trend details
        trend = result['pillars']['trend']
        if trend.get('spy_close'):
            print(f"\n   Trend: SPY ${trend['spy_close']:.2f} vs SMA ${trend['sma_200']:.2f} ({trend['pct_above_sma']:+.1f}%)")

        # Risk appetite details
        risk = result['pillars']['risk_appetite']
        if risk.get('vix'):
            print(f"   Risk: VIX {risk['vix']:.1f}, HY Spread {risk.get('hy_spread', 'N/A')}")

        # Gating recommendation
        gating = calc.should_gate_signal(result['score'])
        print("\n[SIGNAL GATING]")
        print(f"   Allow Longs: {'YES' if gating['allow_longs'] else 'NO'}")
        print(f"   Reduced Sizing: {'YES' if gating['reduced_sizing'] else 'NO'}")


def run_m03_eval_pipeline(args):
    """Run M03 (regime) evaluation against ground truth."""
    from src.evaluation.m03_evaluator import M03Evaluator

    print("\n" + "=" * 70)
    print(" M03 EVALUATION (Regime Validation)")
    print("=" * 70)
    print(f"   Date Range: {args.start} to {args.end}")
    print(f"   Config: {args.config or 'Default'}")
    print("=" * 70 + "\n")

    evaluator = M03Evaluator(config_path=args.config)
    results = evaluator.evaluate(start_date=args.start, end_date=args.end)

    # Extract results
    disc = results['discrimination']
    cal = results['calibration']
    ccr = cal['crash_capture_rate']
    far = cal['false_alarm_rate']
    lag = cal['reaction_lag']
    passed = results['passed']

    # ============================================
    # PHASE 1: DISCRIMINATION (PRIMARY)
    # ============================================
    phase1_status = '[PASS]' if passed['phase1_discrimination'] else '[FAIL]'
    print(f"[PHASE 1: DISCRIMINATION] {phase1_status}")
    print("-" * 50)
    print("   Can the model separate Bull from Bear? (Threshold-Independent)")
    print("")
    
    auc_bear_status = 'OK' if passed['auc_bear'] else 'X'
    auc_bull_status = 'OK' if passed['auc_bull'] else 'X'
    cohens_d_status = 'OK' if passed['cohens_d'] else 'X'
    
    print(f"   ROC-AUC (Bear): {disc['auc_bear']:.3f} (Target: >=0.90) [{auc_bear_status}]")
    print(f"   ROC-AUC (Bull): {disc['auc_bull']:.3f} (Target: >=0.90) [{auc_bull_status}]")
    print(f"   Cohen's D:      {disc['cohens_d']:.2f}  (Target: >=2.0)  [{cohens_d_status}]")
    print(f"   KS Statistic:   {disc['ks_statistic']:.3f}")
    print("")
    print(f"   Score Separation: STRONG_BEAR={disc['mean_strong_bear']:.1f} vs STRONG_BULL={disc['mean_strong_bull']:.1f}")
    print(f"   -> {disc['separation_points']:.1f} points apart")
    print(f"   Fitness Score: {results['fitness']:.4f}")

    # ============================================
    # PHASE 2: CALIBRATION (SECONDARY)
    # ============================================
    print("")
    phase2_status = '[PASS]' if passed['phase2_calibration'] else '[NEEDS TUNING]'
    print(f"[PHASE 2: CALIBRATION] {phase2_status}")
    print("-" * 50)
    print("   Where to set threshold lines? (Threshold-Dependent)")
    print("")
    
    ccr_status = 'OK' if passed['ccr'] else 'X'
    far_status = 'OK' if passed['far'] else 'X'
    lag_status = 'OK' if passed['lag'] else 'X'

    print(f"   Crash Capture Rate: {ccr['rate']:.1%} (Target: >=80%) [{ccr_status}]")
    print(f"        -> {ccr['captured_days']}/{ccr['total_days']} STRONG_BEAR days with Score<{ccr['threshold']}")
    print(f"   False Alarm Rate:   {far['rate']:.1%} (Target: <=5%)  [{far_status}]")
    print(f"        -> {far['false_alarm_days']}/{far['total_days']} STRONG_BULL days with Score<{far['threshold']}")
    print(f"   Avg Reaction Lag:   {lag['avg_lag']:.1f} days (Target: <=7 days) [{lag_status}]")

    # Critical crash details
    print("\n[REACTION LAG DETAILS]")
    print("-" * 50)
    for crash in lag['critical_crash_lags']:
        status = 'OK' if crash['lag_days'] <= 7 else 'X'
        print(f"   {crash['period_name'][:35]:35s} Lag: {crash['lag_days']:2d} days [{status}]")

    # Generate report
    report = evaluator.generate_report(save=True)
    print(f"\n[OK] Report saved to models/m03_evaluation_*.md")

    # Score distribution summary
    print("\n[SCORE DISTRIBUTION BY REGIME]")
    print("-" * 60)
    dist = results['regime_distribution']['score_by_ground_truth']
    print(f"   {'Regime':15s} {'Mean':>8s} {'StdDev':>8s} {'Min':>6s} {'Max':>6s}")
    for regime in ['STRONG_BEAR', 'BEAR', 'NEUTRAL', 'BULL', 'STRONG_BULL']:
        if regime in dist:
            stats = dist[regime]
            print(f"   {regime:15s} {stats['mean']:8.1f} {stats['std']:8.1f} {stats['min']:6.0f} {stats['max']:6.0f}")


def run_m03_grid_search(args):
    """Run M03 grid search across archetypes and VIX curves."""
    from src.evaluation.m03_grid_search import M03GridSearch, ARCHETYPES, VIX_CURVES

    print("\n" + "=" * 70)
    print(" M03 GRID SEARCH (Archetype Optimization)")
    print("=" * 70)
    print(f"   Date Range: {args.start} to {args.end}")
    print(f"   Archetypes: {len(ARCHETYPES)} ({', '.join(ARCHETYPES.keys())})")
    print(f"   VIX Curves: {len(VIX_CURVES)} ({', '.join(VIX_CURVES.keys())})")
    print(f"   Total Configs: {len(ARCHETYPES) * len(VIX_CURVES)}")
    print("=" * 70 + "\n")

    searcher = M03GridSearch()
    df = searcher.run_grid_search(start_date=args.start, end_date=args.end)

    # Print summary table
    print("\n" + "=" * 70)
    print(" RESULTS RANKED BY FITNESS")
    print("=" * 70)
    print(f"   {'Rank':<4} {'Config':<25} {'Fitness':>8} {'AUC_B':>7} {'AUC_L':>7} {'D':>5} {'GFC':>5} {'COV':>5}")
    print("-" * 70)
    
    for i, row in df.head(12).iterrows():
        if 'error' in row and row.get('error'):
            print(f"   {i+1:<4} {row['config_name']:<25} ERROR")
        else:
            gfc = row.get('gfc_lag', '-')
            covid = row.get('covid_lag', '-')
            print(f"   {i+1:<4} {row['config_name']:<25} {row['fitness']:8.4f} {row['auc_bear']:7.3f} {row['auc_bull']:7.3f} {row['cohens_d']:5.2f} {gfc:>5} {covid:>5}")

    # Best config summary
    if not df.empty and 'fitness' in df.columns:
        best = df.iloc[0]
        print("\n" + "=" * 70)
        print(f" BEST: {best['config_name']}")
        print("=" * 70)
        print(f"   Fitness: {best['fitness']:.4f}")
        print(f"   AUC Bear: {best['auc_bear']:.3f} (target >= 0.90)")
        print(f"   AUC Bull: {best['auc_bull']:.3f} (target >= 0.90)")
        print(f"   Cohen's D: {best['cohens_d']:.2f} (target >= 2.0)")
        
        if best.get('phase1_pass'):
            print("\n   [PHASE 1 PASSED] Ready for threshold calibration!")
        else:
            print("\n   [PHASE 1 FAILED] Try additional archetypes or features.")

    # Generate report
    report = searcher.generate_comparison_report(df)
    print(f"\n[OK] Full report saved to models/m03_configs/grid_search_results_*.md")
    
    # Return best config path
    best_config = searcher.get_best_config_path(df)
    if best_config:
        print(f"[OK] Best config: {best_config}")
        print(f"\n   To evaluate: python model_runner.py m03eval --config {best_config}")


def run_m03_calibrate(args):
    """Run M03 threshold calibration."""
    from src.evaluation.m03_evaluator import M03Evaluator

    print("\n" + "=" * 70)
    print(" M03 THRESHOLD CALIBRATION")
    print("=" * 70)
    print(f"   Date Range: {args.start} to {args.end}")
    print(f"   Target CCR: {args.ccr_target:.0%}")
    print(f"   Target FAR: {args.far_target:.0%}")
    print(f"   Save Config: {'Yes' if args.save else 'No'}")
    print("=" * 70 + "\n")

    evaluator = M03Evaluator(config_path=args.config)
    print("Running evaluation to gather score distributions...")
    evaluator.evaluate(start_date=args.start, end_date=args.end)
    
    print("\nCalculating optimal thresholds...\n")
    calibration = evaluator.calibrate_thresholds(
        ccr_target=args.ccr_target,
        far_target=args.far_target,
        save_config=args.save
    )
    
    # Display results
    current = calibration['current_thresholds']
    optimal = calibration['optimal_thresholds']
    expected = calibration['expected_metrics']
    unified = calibration['unified_threshold_analysis']
    bear = calibration['distributions']['bear']
    bull = calibration['distributions']['bull']
    
    print("[THRESHOLD RECOMMENDATIONS]")
    print("-" * 50)
    print(f"   {'Threshold':<25} {'Current':>10} {'Optimal':>10} {'Delta':>8}")
    print(f"   {'CCR (Crash Capture)':<25} {current['ccr']:>10} {optimal['ccr']:>10} {optimal['ccr'] - current['ccr']:>+8}")
    print(f"   {'FAR (False Alarm)':<25} {current['far']:>10} {optimal['far']:>10} {optimal['far'] - current['far']:>+8}")
    print(f"   {'LAG (Reaction Speed)':<25} {current['lag']:>10} {optimal['lag']:>10} {optimal['lag'] - current['lag']:>+8}")
    
    print("\n[EXPECTED METRICS WITH OPTIMAL THRESHOLDS]")
    print("-" * 50)
    print(f"   CCR: {expected['ccr_with_optimal']:.1%} (target: >={args.ccr_target:.0%})")
    print(f"   FAR: {expected['far_with_optimal']:.1%} (target: <={args.far_target:.0%})")
    
    print("\n[SCORE DISTRIBUTIONS]")
    print("-" * 50)
    print(f"   STRONG_BEAR: N={bear['count']}, Mean={bear['mean']}, Std={bear['std']}, Range=[{bear['min']}, {bear['max']}]")
    print(f"       Percentiles: P20={bear['p20']}, P50={bear['p50']}, P80={bear['p80']}")
    print(f"   STRONG_BULL: N={bull['count']}, Mean={bull['mean']}, Std={bull['std']}, Range=[{bull['min']}, {bull['max']}]")
    print(f"       Percentiles: P5={bull['p5']}, P20={bull['p20']}, P50={bull['p50']}")
    
    print("\n[UNIFIED THRESHOLD ANALYSIS]")
    print("-" * 50)
    print(f"   If using single threshold of {unified['threshold']}:")
    print(f"       CCR: {unified['ccr']:.1%}")
    print(f"       FAR: {unified['far']:.1%}")
    
    # Generate and save report
    report = evaluator.generate_calibration_report(calibration)
    report_path = Path('models') / f'm03_calibration_{args.start.replace("-", "")}_{args.end.replace("-", "")}.md'
    report_path.write_text(report, encoding='utf-8')
    print(f"\n[OK] Calibration report saved to {report_path}")
    
    if args.save:
        print(f"[OK] Config updated with calibrated thresholds")
    else:
        print("\n[TIP] Run with --save to update m03_config.json with calibrated thresholds")


def run_m02_pipeline(args):
    """Run M02 (classification) training pipeline."""
    from src.pipeline import DataPipeline, M02Trainer

    # Extract barrier params from args (use getattr for backwards compat)
    k_sl = getattr(args, 'k_sl', 1.0)
    k_tp = getattr(args, 'k_tp', 4.0)
    min_tp = getattr(args, 'min_tp', 0.20)
    max_time = getattr(args, 'max_time', 30)
    barrier_params = {'k_sl': k_sl, 'k_tp': k_tp, 'min_tp': min_tp, 'max_time': max_time}

    print("\n" + "=" * 70)
    print(" M02 PIPELINE (Ignition Classifier)")
    print("=" * 70)
    print(f"   Date Range: {args.start} to {args.end}")
    print(f"   Horizon: {'SEPA exits' if args.horizon is None else f'{args.horizon} days'}")
    print(f"   Barrier: k_sl={k_sl}, k_tp={k_tp}, min_tp={min_tp:.0%}, max_time={max_time}")
    print(f"   Steps: {args.steps}")
    print("=" * 70 + "\n")

    pipeline = DataPipeline()

    # Step 1: Scan (generate D1)
    if 'scan' in args.steps:
        d1 = pipeline.scan(args.start, args.end)  # Uses default threshold
    elif 'hydrate' in args.steps or 'label' in args.steps or 'train' in args.steps:
        d1 = pipeline.load_d1()

    # Step 2: Hydrate (generate D2R with fixed horizon)
    if 'hydrate' in args.steps:
        d2r = pipeline.hydrate(d1, horizon_days=args.horizon, n_jobs=args.jobs)
    elif 'label' in args.steps or 'train' in args.steps:
        d2r = pipeline.load_d2r(horizon_days=args.horizon)

    # Step 3: Label (generate D3 with triple barriers)
    if 'label' in args.steps:
        d3 = pipeline.label(
            d2r,
            k_sl=k_sl,
            k_tp=k_tp,
            min_tp=min_tp,
            max_time=max_time,
            horizon_days=args.horizon,
            n_jobs=args.jobs
        )
    elif 'train' in args.steps:
        d3 = pipeline.load_d3(horizon_days=args.horizon)

    # Step 4: Train M02
    if 'train' in args.steps:
        trainer = M02Trainer(
            feature_set=getattr(args, 'feature_set', None),
            model_name=getattr(args, 'model_name', None),
            barrier_params=barrier_params
        )
        model, metrics = trainer.train(d3, tune=args.tune)
        trainer.save(model, metrics)
        model_name = trainer.model_name.lower()
        print(f"\n[OK] M02 model saved to models/{model_name}.json")

        # Generate report if requested
        if hasattr(args, 'report') and args.report:
            report_path = trainer.generate_report(
                model, metrics,
                start_date=args.start,
                end_date=args.end
            )
            print(f"[OK] Report saved to {report_path}")


def run_data_pipeline(args):
    """Run data generation pipeline (D1, D2, D2R, D3)."""
    from src.pipeline import DataPipeline

    # Extract barrier params from args (use getattr for backwards compat)
    k_sl = getattr(args, 'k_sl', 1.0)
    k_tp = getattr(args, 'k_tp', 4.0)
    min_tp = getattr(args, 'min_tp', 0.20)
    max_time = getattr(args, 'max_time', 30)

    print("\n" + "=" * 70)
    print(" DATA PIPELINE")
    print("=" * 70)
    print(f"   Date Range: {args.start} to {args.end}")
    print(f"   Steps: {args.steps}")
    print(f"   Include M03: {args.include_m03}")
    if args.horizon:
        print(f"   Horizon: {args.horizon} days")
    if 'label' in args.steps:
        print(f"   Barrier: k_sl={k_sl}, k_tp={k_tp}, min_tp={min_tp:.0%}, max_time={max_time}")
    print("=" * 70 + "\n")

    pipeline = DataPipeline()

    # Step 1: Scan (generate D1)
    if 'scan' in args.steps:
        d1 = pipeline.scan(args.start, args.end, threshold=args.threshold)
    else:
        d1 = pipeline.load_d1()
        print(f"Loaded existing D1: {len(d1)} trades")

    # Step 2: Features (generate D2 with M03)
    if 'features' in args.steps:
        d2 = pipeline.features(d1, n_jobs=args.jobs, include_m03=args.include_m03)
        m03_cols = [c for c in d2.columns if c.startswith('m03_')]
        print(f"\nD2 generated with {len(m03_cols)} M03 features: {m03_cols}")

    # Step 3: Hydrate (generate D2R)
    if 'hydrate' in args.steps:
        d2r = pipeline.hydrate(d1, horizon_days=args.horizon, n_jobs=args.jobs)

    # Step 4: Label (generate D3)
    if 'label' in args.steps:
        d2r = pipeline.load_d2r(horizon_days=args.horizon)
        d3 = pipeline.label(
            d2r,
            k_sl=k_sl,
            k_tp=k_tp,
            min_tp=min_tp,
            max_time=max_time,
            horizon_days=args.horizon,
            n_jobs=args.jobs,
            include_m03=args.include_m03,
            apply_preprocessing=True
        )
        # Show summary of generated features
        log_cols = [c for c in d3.columns if c.startswith('log_')]
        m03_cols = [c for c in d3.columns if c.startswith('m03_')]
        print(f"\nD3 generated: {len(log_cols)} log_* features, {len(m03_cols)} m03_* features")

    print("\n[OK] Data pipeline complete")


def main():
    parser = argparse.ArgumentParser(
        description="Model Training CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python model.py m01 --start 2020-01-01 --end 2023-12-31
  python model.py m02 --start 2020-01-01 --end 2023-12-31 --horizon 120
  python model.py m01 --steps train --tune  # Tune existing data
        """
    )
    
    subparsers = parser.add_subparsers(dest='model', help='Model to train')
    
    # M01 subcommand
    m01_parser = subparsers.add_parser('m01', help='Train M01 (Return Regressor)')
    m01_parser.add_argument('--start', default='2018-01-01', help='Start date')
    m01_parser.add_argument('--end', default='2023-12-31', help='End date')
    m01_parser.add_argument('--threshold', type=float, default=15.0, help='Success threshold %%')
    m01_parser.add_argument('--steps', nargs='+', default=['scan', 'features', 'train'],
                           choices=['scan', 'features', 'train'],
                           help='Pipeline steps to run')
    m01_parser.add_argument('--tune', action='store_true', help='Enable Optuna tuning')
    m01_parser.add_argument('--jobs', type=int, default=-1, help='Parallel workers (-1=all)')
    m01_parser.add_argument('--survivor', action='store_true', 
                           help='Enable survivor model (filter crashed trades)')
    m01_parser.add_argument('--stop-mult', type=float, default=2.0, 
                           help='Survivor stop multiplier (default: 2.0)')
    m01_parser.add_argument('--target', default='log_hybrid',
                           choices=['return_pct', 'y_max', 'log_space', 'hybrid_floor',
                                    'risk_adjusted', 'log_hybrid'],
                           help='Target type (default: log_space)')
    m01_parser.add_argument('--feature-set', default=None,
                           help='Feature set name from feature_config.py (e.g., M01_V2_FEATURES)')
    m01_parser.add_argument('--model-name', default=None,
                           help='Custom model name for saving (e.g., m01_v2). Defaults to m01')
    m01_parser.add_argument('--report', action='store_true',
                           help='Generate markdown training report')
    m01_parser.add_argument('--calibrate', action='store_true',
                           help='Run isotonic calibration after training')

    # M01 Ranker subcommand (pairwise ranking)
    m01rank_parser = subparsers.add_parser('m01rank',
        help='Train M01 Ranker (Pairwise cross-sectional ranking)')
    m01rank_parser.add_argument('--start', default='2018-01-01', help='Start date')
    m01rank_parser.add_argument('--end', default='2023-12-31', help='End date')
    m01rank_parser.add_argument('--threshold', type=float, default=15.0, help='Success threshold %%')
    m01rank_parser.add_argument('--steps', nargs='+', default=['scan', 'features', 'train'],
                               choices=['scan', 'features', 'train'],
                               help='Pipeline steps to run')
    m01rank_parser.add_argument('--tune', action='store_true', help='Enable Optuna tuning')
    m01rank_parser.add_argument('--jobs', type=int, default=-1, help='Parallel workers (-1=all)')
    m01rank_parser.add_argument('--target', default='log_hybrid',
                               choices=['return_pct', 'y_max', 'log_space', 'log_hybrid'],
                               help='Target for ranking relevance (default: log_hybrid)')
    m01rank_parser.add_argument('--feature-set', default=None,
                               help='Feature set name from feature_config.py')
    m01rank_parser.add_argument('--model-name', default=None,
                               help='Custom model name (default: m01_rank)')
    m01rank_parser.add_argument('--min-group-size', type=int, default=5,
                               help='Minimum samples per date to include (default: 5)')
    m01rank_parser.add_argument('--report', action='store_true',
                               help='Generate markdown training report')

    # M02 subcommand
    m02_parser = subparsers.add_parser('m02', help='Train M02 (Ignition Classifier)')
    m02_parser.add_argument('--start', default='2018-01-01', help='Start date')
    m02_parser.add_argument('--end', default='2023-12-31', help='End date')
    m02_parser.add_argument('--horizon', type=int, default=None, 
                           help='Fixed horizon in days (default: None = SEPA exits)')
    m02_parser.add_argument('--steps', nargs='+', default=['scan', 'hydrate', 'label', 'train'],
                           choices=['scan', 'hydrate', 'label', 'train'],
                           help='Pipeline steps to run')
    m02_parser.add_argument('--tune', action='store_true', help='Enable Optuna tuning')
    m02_parser.add_argument('--jobs', type=int, default=-1, help='Parallel workers (-1=all)')
    m02_parser.add_argument('--report', action='store_true',
                           help='Generate markdown training report')
    m02_parser.add_argument('--feature-set', default=None,
                           help='Feature set name from feature_config.py (e.g., M01_FEATURES)')
    m02_parser.add_argument('--model-name', default=None,
                           help='Custom model name for saving (e.g., m02_exp1). Defaults to m02')
    # Triple barrier parameters
    m02_parser.add_argument('--k-sl', type=float, default=1.0,
                           help='Stop loss ATR multiplier (default: 1.0)')
    m02_parser.add_argument('--k-tp', type=float, default=4.0,
                           help='Take profit ATR multiplier (default: 4.0)')
    m02_parser.add_argument('--min-tp', type=float, default=0.20,
                           help='Minimum profit target as decimal (default: 0.20 = 20%%)')
    m02_parser.add_argument('--max-time', type=int, default=30,
                           help='Maximum time barrier in days (default: 30)')

    # DATA subcommand (data pipeline operations)
    data_parser = subparsers.add_parser('data', help='Data Pipeline (D1/D2/D2R/D3 generation)')
    data_parser.add_argument('--start', default='2018-01-01', help='Start date')
    data_parser.add_argument('--end', default='2023-12-31', help='End date')
    data_parser.add_argument('--threshold', type=float, default=15.0, help='Success threshold %%')
    data_parser.add_argument('--steps', nargs='+', default=['scan', 'features'],
                            choices=['scan', 'features', 'hydrate', 'label'],
                            help='Pipeline steps to run')
    data_parser.add_argument('--include-m03', dest='include_m03', action='store_true', default=True,
                            help='Include M03 regime features in D2 (default: True)')
    data_parser.add_argument('--no-m03', dest='include_m03', action='store_false',
                            help='Exclude M03 regime features from D2')
    data_parser.add_argument('--horizon', type=int, default=None,
                            help='Fixed horizon in days for hydration (default: SEPA exits)')
    data_parser.add_argument('--jobs', type=int, default=-1, help='Parallel workers (-1=all)')
    # Triple barrier parameters (for label step)
    data_parser.add_argument('--k-sl', type=float, default=1.0,
                            help='Stop loss ATR multiplier (default: 1.0)')
    data_parser.add_argument('--k-tp', type=float, default=4.0,
                            help='Take profit ATR multiplier (default: 4.0)')
    data_parser.add_argument('--min-tp', type=float, default=0.20,
                            help='Minimum profit target as decimal (default: 0.20 = 20%%)')
    data_parser.add_argument('--max-time', type=int, default=30,
                            help='Maximum time barrier in days (default: 30)')

    # M03 subcommand
    m03_parser = subparsers.add_parser('m03', help='Calculate M03 (Market Regime)')

    # M03 Evaluation subcommand
    m03eval_parser = subparsers.add_parser('m03eval', help='Evaluate M03 against ground truth')
    m03eval_parser.add_argument('--start', default='2003-03-01',
                               help='Evaluation start date (default: 2003-03-01)')
    m03eval_parser.add_argument('--end', default='2024-12-31',
                               help='Evaluation end date (default: 2024-12-31)')
    m03eval_parser.add_argument('--config', default=None,
                               help='Path to M03 config JSON (for grid search)')

    # M03 Grid Search subcommand
    m03grid_parser = subparsers.add_parser('m03grid', help='M03 grid search (12 archetype × VIX combinations)')
    m03grid_parser.add_argument('--start', default='2007-01-01',
                               help='Evaluation start date (default: 2007-01-01)')
    m03grid_parser.add_argument('--end', default='2024-12-31',
                               help='Evaluation end date (default: 2024-12-31)')
    
    # M03 Calibration subcommand
    m03cal_parser = subparsers.add_parser('m03calibrate', help='Calibrate M03 thresholds from score distributions')
    m03cal_parser.add_argument('--start', default='2007-01-01',
                              help='Calibration start date (default: 2007-01-01)')
    m03cal_parser.add_argument('--end', default='2024-12-31',
                              help='Calibration end date (default: 2024-12-31)')
    m03cal_parser.add_argument('--config', default=None,
                              help='Path to M03 config JSON')
    m03cal_parser.add_argument('--ccr-target', type=float, default=0.80,
                              help='Target crash capture rate (default: 0.80)')
    m03cal_parser.add_argument('--far-target', type=float, default=0.05,
                              help='Target false alarm rate (default: 0.05)')
    m03cal_parser.add_argument('--save', action='store_true',
                              help='Save calibrated thresholds to config')
    
    m03_parser.add_argument('--date', default=None,
                           help='Calculate regime as of date (default: latest)')
    m03_parser.add_argument('--history', action='store_true',
                           help='Calculate regime history over date range')
    m03_parser.add_argument('--start', default='2003-03-01',
                           help='Start date for history mode (FRED data starts ~2003)')
    m03_parser.add_argument('--end', default='2024-12-31',
                           help='End date for history mode')
    m03_parser.add_argument('--freq', default='D',
                           choices=['D', 'W-FRI', 'W-MON', 'M', 'Q'],
                           help='Frequency for history (default: D daily)')
    m03_parser.add_argument('--output', default='models/m03_history.parquet',
                           help='Output path (.parquet or .csv)')
    m03_parser.add_argument('--csv', action='store_true',
                           help='Also save as CSV (in addition to parquet)')

    # Workflow subcommand (automated M01 pipeline)
    workflow_parser = subparsers.add_parser('workflow',
        help='Automated M01 workflow (EDA + Selection + Train + Report)')
    workflow_parser.add_argument('--start', default='2018-01-01', help='Start date')
    workflow_parser.add_argument('--end', default='2023-12-31', help='End date')
    workflow_parser.add_argument('--steps', nargs='+',
                                 default=['load', 'eda', 'select', 'train', 'report'],
                                 choices=['load', 'eda', 'select', 'train', 'report'],
                                 help='Workflow steps to run')
    workflow_parser.add_argument('--ks-threshold', type=float, default=0.05,
                                 help='KS/composite threshold for feature selection (default: 0.05)')
    workflow_parser.add_argument('--correlation-threshold', type=float, default=0.7,
                                 help='Correlation threshold for clustering (default: 0.7)')
    workflow_parser.add_argument('--features', nargs='+',
                                 help='Explicit feature list (skips auto-select)')
    workflow_parser.add_argument('--no-auto-select', action='store_true',
                                 help='Disable auto feature selection (use all candidates)')
    workflow_parser.add_argument('--fast-eda', action='store_true',
                                 help='Use KS-only pipeline (skip full 4-pillar analysis)')
    workflow_parser.add_argument('--exclude-m03', action='store_true',
                                 help='Exclude M03 regime features from feature selection')
    workflow_parser.add_argument('--enrich-mfe', action='store_true',
                                 help='Enrich D2 with MFE/MAE from D2R (requires hydrate step)')
    workflow_parser.add_argument('--eda-target', default='return_pct',
                                 choices=['return_pct', 'y_max'],
                                 help='Target column for EDA screening (default: return_pct, use y_max with --enrich-mfe)')
    workflow_parser.add_argument('--target', default='log_space',
                                 choices=['return_pct', 'log_space', 'hybrid_floor',
                                          'risk_adjusted', 'log_hybrid'],
                                 help='Target type (default: log_space)')
    workflow_parser.add_argument('--tune', action='store_true',
                                 help='Enable Optuna hyperparameter tuning')
    workflow_parser.add_argument('--jobs', type=int, default=-1,
                                 help='Parallel workers (-1=all)')

    args = parser.parse_args()
    
    if args.model is None:
        parser.print_help()
        print("\n❌ Please specify a command: m01, m02, or workflow")
        sys.exit(1)

    if args.model == 'm01':
        run_m01_pipeline(args)
    elif args.model == 'm01rank':
        run_m01_ranker_pipeline(args)
    elif args.model == 'm02':
        run_m02_pipeline(args)
    elif args.model == 'm03':
        run_m03_pipeline(args)
    elif args.model == 'm03eval':
        run_m03_eval_pipeline(args)
    elif args.model == 'm03grid':
        run_m03_grid_search(args)
    elif args.model == 'm03calibrate':
        run_m03_calibrate(args)
    elif args.model == 'workflow':
        run_workflow(args)
    elif args.model == 'data':
        run_data_pipeline(args)


if __name__ == "__main__":
    main()
