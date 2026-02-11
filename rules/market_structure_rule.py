from dataclasses import dataclass
from typing import Optional

from nautilus_trader.model import Bar, BarType
from nautilus_trader.trading import Strategy

from constants.shared_dict_key import SharedDictKey
from core import SharedState
from core.enums import RuleSignal
from core.rules.rule_base import RuleBase
from indicators.smart_pivot_points import SmartPivotPoints, Trend


@dataclass
class MarketStructureRuleConfig:
    """
    Configuration for Market Structure Rule.

    Parameters:
        bar_type: Optional BarType for detecting market structure.
                  If None, uses bar.bar_type from the incoming bar.
    """

    bar_type: Optional[BarType] = None


class MarketStructureRule(RuleBase):
    """
    Market Structure Rule using SmartPivotPoints indicator.

    This rule evaluates the current market structure trend using the
    SmartPivotPoints indicator and generates appropriate trading signals.

    Trend Detection:
    - trend == 1 (Uptrend): HH -> HL -> HH structure -> RuleSignal.BUY
    - trend == -1 (Downtrend): LL -> LH -> LL structure -> RuleSignal.SELL
    - trend == 0 (Undefined): No clear structure -> RuleSignal.NONE

    The rule saves:
    - MARKET_STRUCTURE_RULE_SIGNAL: The RuleSignal (BUY, SELL, or NONE)
    """

    def __init__(self, shared_state: SharedState, strategy: Strategy, config: MarketStructureRuleConfig):
        super().__init__(shared_state)
        self.strategy = strategy
        self.config = config

        # Initialize the SmartPivotPoints indicator
        self.smart_pivot_points = SmartPivotPoints()

        self.first_bar_initialized = False

    @property
    def trend(self) -> Trend:
        """Returns the current trend from the SmartPivotPoints indicator."""
        return self.smart_pivot_points.trend

    def evaluate(self, bar: Bar, current_bar: Bar = None) -> bool:
        """
        Evaluate the rule and detect market structure trend direction.

        Args:
            bar: The bar being processed
            current_bar: The current bar (optional)

        Returns:
            bool: Always returns True to continue processing
        """
        # Determine which bar type to use
        target_bar_type = self.config.bar_type if self.config.bar_type else bar.bar_type

        # Verify the bar type is correct
        if str(bar.bar_type) not in str(target_bar_type) and self.first_bar_initialized:
            return True

        if not self.first_bar_initialized:
            self.first_bar_initialized = True

        # Update the SmartPivotPoints indicator with the new bar
        self.smart_pivot_points.handle_bar(bar)

        # Determine the signal based on trend direction
        trend = self.smart_pivot_points.trend

        if trend == Trend.UP:
            # Uptrend: HH -> HL -> HH structure
            signal = RuleSignal.BUY
        elif trend == Trend.DOWN:
            # Downtrend: LL -> LH -> LL structure
            signal = RuleSignal.SELL
        else:
            # Undefined trend
            signal = RuleSignal.NONE

        # Save signal to shared state
        self.shared_state.set(SharedDictKey.MARKET_STRUCTURE_RULE_SIGNAL, signal)

        return True

    def on_register_indicator_for_bars(self) -> None:
        """Register the SmartPivotPoints indicator for bars before the warmup period."""
        bar_type = self.config.bar_type if self.config.bar_type else None
        if bar_type:
            self.strategy.register_indicator_for_bars(bar_type, self.smart_pivot_points)

    def on_start(self) -> None:
        """Actions to be performed on strategy start."""
        pass

    def on_stop(self) -> None:
        """Actions to be performed on strategy stop."""
        pass
