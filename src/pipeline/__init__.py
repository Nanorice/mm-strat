"""
Pipeline Module - ML Model Training Infrastructure
==================================================

This module provides the core infrastructure for SEPA ML model training:

Classes:
    - DataPipeline: Orchestrates data generation (scan → features → hydrate → label)
    - BaseTrainer: Abstract base class for model trainers
    - M01Trainer: SEPA Return Regressor (predicts expected return %)
    - M02Trainer: Ignition Classifier (predicts barrier hit probability)

Example Usage:
    # Full M01 pipeline
    from src.pipeline import DataPipeline, M01Trainer
    
    pipeline = DataPipeline()
    d1 = pipeline.scan('2020-01-01', '2023-12-31')
    d2 = pipeline.features(d1)
    
    trainer = M01Trainer()
    model, metrics = trainer.train(d2)
    trainer.save(model, metrics)

    # Full M02 pipeline
    from src.pipeline import DataPipeline, M02Trainer
    
    pipeline = DataPipeline()
    d1 = pipeline.scan('2020-01-01', '2023-12-31')
    d2r = pipeline.hydrate(d1, horizon_days=120)
    d3 = pipeline.label(d2r)
    
    trainer = M02Trainer()
    model, metrics = trainer.train(d3)
    trainer.save(model, metrics)
"""

from .data_pipeline import DataPipeline
from .base_trainer import BaseTrainer
from .m01_trainer import M01Trainer
from .m02_trainer import M02Trainer

__all__ = ['DataPipeline', 'BaseTrainer', 'M01Trainer', 'M02Trainer']
