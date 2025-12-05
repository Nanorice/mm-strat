"""
Trading Configuration - Strategy Parameters
Defines configurable parameters for trade simulation and execution.
"""

from dataclasses import dataclass, field
from typing import Optional, Callable, TYPE_CHECKING

if TYPE_CHECKING:
    from src.trade_simulator import Trade


@dataclass
class TradingConfig:
    """
    Configurable trading strategy parameters.
    
    This class can be reused across:
    - TradeSimulator (for historical simulation and Dataset B construction)
    - Portfolio Manager (for live execution)
    - Backtesting Engine (for strategy testing)
    
    Attributes:
        success_threshold_pct: Return threshold for labeling success (default: 15%)
        exit_on_trend_break: Exit when SEPA trend breaks (default: True)
        exit_on_stop_loss: Exit on stop loss (default: False)
        stop_loss_pct: Stop loss percentage if enabled (default: 8%)
        max_positions: Maximum concurrent positions (default: 8)
        position_size_pct: Position size as % of portfolio (default: 12.5%)
        allow_reentry: Allow same ticker to re-trigger (default: True)
        reentry_cooldown_days: Days to wait before re-entry (default: 0)
    """
    
    # Labeling Parameters
    success_threshold_pct: float = 15.0
    
    # Exit Rules
    exit_on_trend_break: bool = True
    exit_on_stop_loss: bool = False
    stop_loss_pct: float = 8.0
    
    # Position Management
    max_positions: int = 8
    position_size_pct: float = 12.5  # 100% / 8 positions
    
    # Re-Entry Rules
    allow_reentry: bool = True
    reentry_cooldown_days: int = 0
    
    # Labeling Function (custom or default)
    labeling_function: Optional[Callable[['Trade'], int]] = None
    
    def __post_init__(self):
        """Validate configuration and set default labeling function."""
        if self.success_threshold_pct <= 0:
            raise ValueError("success_threshold_pct must be positive")
        if self.max_positions <= 0:
            raise ValueError("max_positions must be positive")
        if self.position_size_pct <= 0 or self.position_size_pct > 100:
            raise ValueError("position_size_pct must be between 0 and 100")
        if self.reentry_cooldown_days < 0:
           raise ValueError("reentry_cooldown_days cannot be negative")

        # Set default labeling function if not provided
        if self.labeling_function is None:
            self.labeling_function = self._default_labeling_function

    def _default_labeling_function(self, trade: 'Trade') -> int:
        """
        Default labeling function based on return threshold.
        This is a proper method (not lambda) so it can be pickled for multiprocessing.
        """
        return 1 if trade.return_pct >= self.success_threshold_pct else 0
    
    @classmethod
    def conservative(cls) -> 'TradingConfig':
        """
        Conservative configuration with tighter stops and lower success threshold.
        """
        return cls(
            success_threshold_pct=10.0,
            exit_on_trend_break=True,
            exit_on_stop_loss=True,
            stop_loss_pct=5.0,
            max_positions=5,
            position_size_pct=20.0
        )
    
    @classmethod
    def aggressive(cls) -> 'TradingConfig':
        """
        Aggressive configuration for superperformers.
        """
        return cls(
            success_threshold_pct=20.0,
            exit_on_trend_break=True,
            exit_on_stop_loss=False,
            max_positions=10,
            position_size_pct=10.0
        )
    
    @classmethod
    def default(cls) -> 'TradingConfig':
        """
        Default SEPA configuration per user specifications.
        - 15% return threshold
        - Trend break exit only
        - No stop loss
        - No re-entry cooldown
        """
        return cls(
            success_threshold_pct=15.0,
            exit_on_trend_break=True,
            exit_on_stop_loss=False,
            max_positions=8,
            allow_reentry=True,
            reentry_cooldown_days=0
        )
    
    def to_dict(self) -> dict:
        """Convert config to dictionary for serialization."""
        return {
            'success_threshold_pct': self.success_threshold_pct,
            'exit_on_trend_break': self.exit_on_trend_break,
            'exit_on_stop_loss': self.exit_on_stop_loss,
            'stop_loss_pct': self.stop_loss_pct,
            'max_positions': self.max_positions,
            'position_size_pct': self.position_size_pct,
            'allow_reentry': self.allow_reentry,
            'reentry_cooldown_days': self.reentry_cooldown_days
        }
    
    @classmethod
    def from_dict(cls, config_dict: dict) -> 'TradingConfig':
        """Create config from dictionary."""
        return cls(**config_dict)
    
    def __str__(self) -> str:
        """Human-readable configuration summary."""
        return (
            f"TradingConfig(\n"
            f"  Success Threshold: {self.success_threshold_pct}%\n"
            f"  Exit on Trend Break: {self.exit_on_trend_break}\n"
            f"  Exit on Stop Loss: {self.exit_on_stop_loss}\n"
            f"  Max Positions: {self.max_positions}\n"
            f"  Position Size: {self.position_size_pct}%\n"
            f"  Allow Re-entry: {self.allow_reentry}\n"
            f")"
        )
