from dataclasses import dataclass

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
class ExpectedTargetRuleConfig:
    """
    Configuration for Expected Target Rule.

    Parameters:
        bar_type: BarType for the pivot points calculation (1 hour timeframe)
        left: Number of bars to the left of pivot candidate (default: 10)
        right: Number of bars to the right of pivot candidate (default: 10)
    """

    bar_type: BarType
    left: int = 10
    right: int = 10


class ExpectedTargetRule(RuleBase):
    """
    Expected Target Rule using Pivot Points High/Low indicator.

    - Timeframe: 1 hour
    - Warmup period: 3 days (72 hours = 72 bars on 1H timeframe)
    - Tracks the latest high pivot point and stores it in shared state
    """

    def __init__(self, shared_state: SharedState, strategy: Strategy, config: ExpectedTargetRuleConfig):
        super().__init__(shared_state)
        self.strategy = strategy
        self.config = config

        # Initialize the Pivot Points indicator
        self.pivot_indicator = PivotPointsHighLow(left=config.left, right=config.right)

        self.first_bar_initialized = False

    def evaluate(self, bar: Bar, current_bar: Bar = None) -> bool:
        """
        Evaluate the rule and update shared state with latest pivot high.

        Args:
            bar: The bar being processed
            current_bar: The current bar (optional)

        Returns:
            bool: Always returns True to continue processing
        """
        # Verify the bar type is correct
        if str(bar.bar_type) not in str(self.config.bar_type) and self.first_bar_initialized:
            return True

        if not self.first_bar_initialized:
            self.first_bar_initialized = True

        # Check if the indicator is initialized
        if not self.pivot_indicator.initialized:
            return True

        # Update the shared state with the latest pivot high if available
        if self.pivot_indicator.last_pivot_high_price is not None:
            self.shared_state.set(
                SharedDictKey.EXPECTED_TARGET_LATEST_PIVOT_HIGH_PRICE, float(self.pivot_indicator.last_pivot_high_price)
            )
            self.shared_state.set(
                SharedDictKey.EXPECTED_TARGET_LATEST_PIVOT_HIGH_TS, self.pivot_indicator.last_pivot_high_ts
            )

        # Update the shared state with the latest pivot low if available
        if self.pivot_indicator.last_pivot_low_price is not None:
            self.shared_state.set(
                SharedDictKey.EXPECTED_TARGET_LATEST_PIVOT_LOW_PRICE, float(self.pivot_indicator.last_pivot_low_price)
            )
            self.shared_state.set(
                SharedDictKey.EXPECTED_TARGET_LATEST_PIVOT_LOW_TS, self.pivot_indicator.last_pivot_low_ts
            )

        return True

    def on_register_indicator_for_bars(self) -> None:
        """Register the pivot indicator for bars before the warmup period."""
        self.strategy.register_indicator_for_bars(self.config.bar_type, self.pivot_indicator)

    def on_start(self) -> None:
        """Actions to be performed on strategy start."""
        # Setting the warmed-up and subscribed bar type
        key = SharedDictKeyBase.WARMED_UP_AND_SUBSCRIBED_BAR_TYPES
        lst = self.shared_state.get(key, [])
        if not lst:  # if the key was missing, we got the default []
            self.shared_state.set(key, lst)

        # add if not already there (avoid duplicates)
        if self.config.bar_type.standard() not in lst:
            lst.append(self.config.bar_type.standard())

            now_ts = pd.Timestamp(self.strategy.clock.timestamp_ns(), tz="UTC", unit="ns")
            # Warmup period: 3 days = 72 hours on 1H timeframe
            start_time = (now_ts - pd.Timedelta(days=3)).normalize()

            if self.is_backtest_mode:
                self.strategy.request_aggregated_bars(
                    [self.config.bar_type], start=start_time, update_subscriptions=True
                )
            else:  # live trading mode
                self.strategy.request_bars(self.config.bar_type, start=start_time, limit=1000)

            self.strategy.subscribe_bars(self.config.bar_type)

    def on_stop(self) -> None:
        """Actions to be performed on strategy stop."""
        self.strategy.unsubscribe_bars(self.config.bar_type)

        # remove the bar type from a list
        key = SharedDictKeyBase.WARMED_UP_AND_SUBSCRIBED_BAR_TYPES
        lst = self.shared_state.get(key, [])
        if lst and self.config.bar_type.standard() in lst:
            lst.remove(self.config.bar_type.standard())
