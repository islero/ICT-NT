from dataclasses import dataclass
from typing import Dict, List

import pandas as pd
from nautilus_trader.core import Data
from nautilus_trader.model import Bar, BarType
from nautilus_trader.trading import Strategy
from pandas import Timedelta

from constants.shared_dict_key import SharedDictKey
from core import SharedState
from core.constants import SharedDictKeyBase
from core.rules import RuleBase


@dataclass
class SearchLiquidityPoolsRuleConfig:
    """Configuration for searching liquidity pools rule."""

    bar_type: BarType  # target bar type to search the liquidity pools
    upper_period_window: int  # the upper period window | 3 on 1D TF means the last 3 daily bars highs inclusive
    lower_period_window: int  # the lower period window | 3 on 1D TF means the last 3 daily bars lows inclusive
    lower_bar_type: BarType  # lower timeframe bar type for data sufficiency check (e.g., 1h for daily, 1d for weekly)
    time_delta: Timedelta
    min_data_count: int = 3  # minimum number of lower timeframe bars required
    extremums_count: int = 1  # how many extremums to consider for the pool


class SearchLiquidityPoolsRule(RuleBase):
    """
    Search for liquidity pools for a certain bar type
    and saves the results in the shared state:
    - "upper_liquidity_pools" for upper liquidity pools
    - "lower_liquidity_pools" for lower liquidity pools
    """

    def __init__(self, shared_state: SharedState, strategy: Strategy, config: SearchLiquidityPoolsRuleConfig):
        super().__init__(shared_state)
        self.strategy = strategy
        self.config = config
        self.first_bar_initialized = False

    def _has_sufficient_data(self, bar: Bar) -> bool:
        """Check if the bar has minimum required data points from a lower timeframe."""
        if self.config.lower_bar_type is None:
            return True  # No validation if lower_bar_type not configured

        lower_bars = self.strategy.cache.bars(self.config.lower_bar_type.standard())
        if not lower_bars:
            return False

        count = sum(1 for b in lower_bars if bar.ts_init <= b.ts_init < bar.ts_init + self.config.time_delta.value)

        return count >= self.config.min_data_count

    def evaluate(self, bar: Bar, current_bar: Bar = None) -> bool:
        # Verify the bar type is correct
        if str(bar.bar_type) not in str(self.config.bar_type) and self.first_bar_initialized:
            return True

        if not self.first_bar_initialized:
            self.first_bar_initialized = True

        bars: List[Bar] = self.strategy.cache.bars(self.config.bar_type.standard())
        if not bars or len(bars) < min(self.config.upper_period_window, self.config.lower_period_window):
            return True

        if self.config.upper_period_window == self.config.lower_period_window:
            bars_slice = bars[: self.config.upper_period_window]
            upper_period_bars = bars_slice
            lower_period_bars = bars_slice
        else:
            upper_period_bars = bars[: self.config.upper_period_window]
            lower_period_bars = bars[: self.config.lower_period_window]

        # Filter bars that have sufficient data from a lower timeframe
        upper_period_bars = [
            bars[i] for i in range(len(upper_period_bars)) if i == 0 or self._has_sufficient_data(bars[i])
        ]
        lower_period_bars = [
            bars[i] for i in range(len(lower_period_bars)) if i == 0 or self._has_sufficient_data(bars[i])
        ]

        # Creating maps for upper and lower liquidity pools or getting them from the shared state
        uppers_map: Dict[str, List[tuple[float, int]]] = self.shared_state.get(SharedDictKey.UPPER_LIQUIDITY_POOLS, {})
        lowers_map: Dict[str, List[tuple[float, int]]] = self.shared_state.get(SharedDictKey.LOWER_LIQUIDITY_POOLS, {})

        # Extract highs for an upper window and lows for a lower window. Convert to float for consistency.
        upper_highs = [(float(b.high), b.ts_init) for b in upper_period_bars if b is not None]
        lower_lows = [(float(b.low), b.ts_init) for b in lower_period_bars if b is not None]

        # Keep only the top extremums_count maximums in upper_highs and minimums in lower_lows
        upper_highs = sorted(upper_highs, key=lambda x: x[0], reverse=True)[: self.config.extremums_count]
        lower_lows = sorted(lower_lows, key=lambda x: x[0])[: self.config.extremums_count]

        # Saving the highs/lows for the selected bar type
        tf_key = str(self.config.bar_type.standard())
        uppers_map[tf_key] = upper_highs
        lowers_map[tf_key] = lower_lows

        # Set the upper and lower liquidity pools based on highs/lows in the selected windows
        self.shared_state.set(SharedDictKey.UPPER_LIQUIDITY_POOLS, uppers_map)
        self.shared_state.set(SharedDictKey.LOWER_LIQUIDITY_POOLS, lowers_map)

        return True

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
            start_time = (now_ts - pd.Timedelta(days=89)).normalize()

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

    def on_historical_data(self, data: Data):
        """This method is called by the framework (see actor.py docstring for on_historical_data)
        Forward the payload to the rule:"""
        pass
