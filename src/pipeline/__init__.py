"""
Pipeline Module - ML Model Training Infrastructure
==================================================

This module provides the core infrastructure for SEPA ML model training:

Classes:
    - DataPipeline: Orchestrates data generation (scan → features → hydrate → label)
    - BaseTrainer: Abstract base class for model trainers
    - M01Trainer: SEPA Return Regressor (predicts expected return %)
    - M01RankerTrainer: SEPA Pairwise Ranker (cross-sectional ranking by date)
    - M02Trainer: Ignition Classifier (predicts barrier hit probability)

Example Usage:
    # M01 Regressor (absolute return prediction)
    from src.pipeline import DataPipeline, M01Trainer

    pipeline = DataPipeline()
    d2 = pipeline.features(pipeline.scan('2020-01-01', '2023-12-31'))

    trainer = M01Trainer()
    model, metrics = trainer.train(d2)
    trainer.save(model, metrics)

    # M01 Ranker (cross-sectional ranking)
    from src.pipeline import DataPipeline, M01RankerTrainer

    pipeline = DataPipeline()
    d2 = pipeline.features(pipeline.scan('2020-01-01', '2023-12-31'))

    ranker = M01RankerTrainer()
    model, metrics = ranker.train(d2)  # Groups by date for pairwise ranking
    ranker.save(model, metrics)

    # M02 Classifier
    from src.pipeline import DataPipeline, M02Trainer

    pipeline = DataPipeline()
    d3 = pipeline.label(pipeline.hydrate(pipeline.scan('2020-01-01', '2023-12-31')))

    trainer = M02Trainer()
    model, metrics = trainer.train(d3)
    trainer.save(model, metrics)
"""

from .data_pipeline import DataPipeline
from .base_trainer import BaseTrainer
from .m01_trainer import M01Trainer
from .m01_ranker_trainer import M01RankerTrainer
from .m02_trainer import M02Trainer
from .m03_regime import M03RegimeCalculator
from .production_scorer import ProductionScorer
from .m01_workflow import M01Workflow, WorkflowConfig

__all__ = [
    'DataPipeline',
    'BaseTrainer',
    'M01Trainer',
    'M01RankerTrainer',
    'M02Trainer',
    'M03RegimeCalculator',
    'ProductionScorer',
    'M01Workflow',
    'WorkflowConfig'
]
