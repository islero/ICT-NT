from nautilus_trader.model import BarType
from nautilus_trader.trading.config import StrategyConfig

from core.strategies import RuleBasedStrategy


class EmptyStrategyConfig(StrategyConfig, frozen=True):
    """Minimal configuration for an empty strategy."""
    base_bar_type: BarType


class EmptyStrategy(RuleBasedStrategy):
    """A no-op strategy that subscribes to the base bar type and does nothing."""

    def __init__(self, config: EmptyStrategyConfig):
        super().__init__(config, config.base_bar_type)
        # No rules to initialize

    def on_start(self) -> None:
        # Subscribe base bars (required by RuleBasedStrategy execution flow)
        self.subscribe_bars(self.config.base_bar_type)

    def on_stop(self) -> None:
        # Unsubscribe base bars on stop
        self.unsubscribe_bars(self.config.base_bar_type)
