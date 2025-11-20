from dataclasses import dataclass
from typing import Optional

import pandas as pd
from nautilus_trader.model import Bar
from nautilus_trader.model.data import BarType
from nautilus_trader.trading import Strategy

from constants.shared_dict_key import SharedDictKey
from core import SharedState
from core.constants import SharedDictKeyBase
from core.rules import RuleBase
from indicators.pivot_points_high_low import PivotPointsHighLow


@dataclass
class MarketStructureShiftRuleConfig:
    """
    Configuration for Market Structure Shift Rule.

    Parameters:
        target_bar_type: Optional BarType for detecting market structure.
                        If None, uses bar.bar_type instead.
        left: Number of bars to the left of pivot candidate (default: 10)
        right: Number of bars to the right of pivot candidate (default: 10)
    """
    target_bar_type: Optional[BarType] = None
    left: int = 10
    right: int = 10


class MarketStructureShiftRule(RuleBase):
    """
    Market Structure Shift Rule using Pivot Points High/Low indicator.

    Market Structure:
    - Uptrend: Higher highs and higher lows (pivot points forming upward)
    - Downtrend: Lower highs and lower lows (pivot points forming downward)

    Market Structure Shift:
    - In uptrend: Current bar pierces the latest low pivot point
    - In downtrend: Current bar pierces the latest high pivot point

    Shared State:
    - Trend direction is saved to shared_state
    - Market structure shift (True/False) is saved to shared_state
    """

    def __init__(
        self,
        shared_state: SharedState,
        strategy: Strategy,
        config: MarketStructureShiftRuleConfig
    ):
        super().__init__(shared_state)
        self.strategy = strategy
        self.config = config

        # Initialize the Pivot Points indicator
        self.pivot_indicator = PivotPointsHighLow(
            left=config.left,
            right=config.right
        )

        self.first_bar_initialized = False

        # Track previous pivot highs and lows to determine trend
        self.previous_pivot_high = None
        self.previous_pivot_low = None

    def evaluate(self, bar: Bar, current_bar: Bar = None) -> bool:
        """
        Evaluate the rule and detect market structure shifts.

        Args:
            bar: The bar being processed
            current_bar: The current bar (optional)

        Returns:
            bool: Always returns True to continue processing
        """
        # Determine which bar type to use
        target_bar_type = self.config.target_bar_type if self.config.target_bar_type else bar.bar_type

        # Verify the bar type is correct
        if str(bar.bar_type) not in str(target_bar_type) and self.first_bar_initialized:
            return True

        if not self.first_bar_initialized:
            self.first_bar_initialized = True

        # Check if the indicator is initialized
        if not self.pivot_indicator.initialized:
            return True

        # Get current pivot points
        current_pivot_high = self.pivot_indicator.last_pivot_high_price
        current_pivot_low = self.pivot_indicator.last_pivot_low_price

        # Detect trend direction based on market structure
        trend_direction = self._detect_trend_direction(current_pivot_high, current_pivot_low)

        # Save trend direction to shared state
        if trend_direction:
            self.shared_state.set(SharedDictKey.MARKET_STRUCTURE_TREND_DIRECTION, trend_direction)

        # Detect market structure shift
        market_structure_shift = self._detect_market_structure_shift(
            bar,
            trend_direction,
            current_pivot_high,
            current_pivot_low
        )

        # Save market structure shift to shared state
        self.shared_state.set(SharedDictKey.MARKET_STRUCTURE_SHIFT, market_structure_shift)

        return True

    def _detect_trend_direction(
        self,
        current_pivot_high: Optional[float],
        current_pivot_low: Optional[float]
    ) -> Optional[str]:
        """
        Detect trend direction based on pivot points.

        Returns:
            "uptrend" if higher highs and higher lows
            "downtrend" if lower highs and lower lows
            None if trend cannot be determined yet
        """
        if current_pivot_high is None or current_pivot_low is None:
            return None

        # Need at least one previous pivot to compare
        if self.previous_pivot_high is None or self.previous_pivot_low is None:
            # Store current pivots for next comparison
            if current_pivot_high is not None:
                self.previous_pivot_high = float(current_pivot_high)
            if current_pivot_low is not None:
                self.previous_pivot_low = float(current_pivot_low)
            return None

        # Check for uptrend: higher highs AND higher lows
        if (float(current_pivot_high) > self.previous_pivot_high and
            float(current_pivot_low) > self.previous_pivot_low):
            trend = "uptrend"
        # Check for downtrend: lower highs AND lower lows
        elif (float(current_pivot_high) < self.previous_pivot_high and
              float(current_pivot_low) < self.previous_pivot_low):
            trend = "downtrend"
        else:
            # Mixed signals, maintain previous trend if exists
            trend = self.shared_state.get(SharedDictKey.MARKET_STRUCTURE_TREND_DIRECTION, None)

        # Update previous pivots
        self.previous_pivot_high = float(current_pivot_high)
        self.previous_pivot_low = float(current_pivot_low)

        return trend

    def _detect_market_structure_shift(
        self,
        bar: Bar,
        trend_direction: Optional[str],
        current_pivot_high: Optional[float],
        current_pivot_low: Optional[float]
    ) -> bool:
        """
        Detect if there's a market structure shift.

        Args:
            bar: Current bar being processed
            trend_direction: Current trend direction ("uptrend" or "downtrend")
            current_pivot_high: Latest pivot high price
            current_pivot_low: Latest pivot low price

        Returns:
            True if market structure shift detected, False otherwise
        """
        if trend_direction is None:
            return False

        # Uptrend shift: current bar pierces the latest low pivot point
        if trend_direction == "uptrend" and current_pivot_low is not None:
            if float(bar.low) < float(current_pivot_low):
                return True

        # Downtrend shift: current bar pierces the latest high pivot point
        if trend_direction == "downtrend" and current_pivot_high is not None:
            if float(bar.high) > float(current_pivot_high):
                return True

        return False

    def on_register_indicator_for_bars(self) -> None:
        """Register the pivot indicator for bars before the warmup period."""
        bar_type = self.config.target_bar_type if self.config.target_bar_type else None
        if bar_type:
            self.strategy.register_indicator_for_bars(bar_type, self.pivot_indicator)

    def on_start(self) -> None:
        """Actions to be performed on strategy start."""
        # Only subscribe if target_bar_type is specified
        if self.config.target_bar_type is None:
            return

        # Setting the warmed-up and subscribed bar type
        key = SharedDictKeyBase.WARMED_UP_AND_SUBSCRIBED_BAR_TYPES
        lst = self.shared_state.get(key, [])
        if not lst:
            self.shared_state.set(key, lst)

        # Add if not already there (avoid duplicates)
        if self.config.target_bar_type.standard() not in lst:
            lst.append(self.config.target_bar_type.standard())

            now_ts = pd.Timestamp(self.strategy.clock.timestamp_ns(), tz="UTC", unit="ns")
            start_time = (now_ts - pd.Timedelta(days=3)).normalize()

            if self.is_backtest_mode:
                self.strategy.request_aggregated_bars([self.config.target_bar_type], start=start_time, update_subscriptions=True)
            else:  # live trading mode
                self.strategy.request_bars(self.config.target_bar_type, start=start_time, limit=1000)

            self.strategy.subscribe_bars(self.config.target_bar_type)

    def on_stop(self) -> None:
        """Actions to be performed on strategy stop."""
        if self.config.target_bar_type is None:
            return

        self.strategy.unsubscribe_bars(self.config.target_bar_type)

        # Remove the bar type from the list
        key = SharedDictKeyBase.WARMED_UP_AND_SUBSCRIBED_BAR_TYPES
        lst = self.shared_state.get(key, [])
        if lst and self.config.target_bar_type.standard() in lst:
            lst.remove(self.config.target_bar_type.standard())
