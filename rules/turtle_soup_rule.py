from dataclasses import dataclass
from typing import List
import pandas as pd
from nautilus_trader.model import BarType, Bar
from nautilus_trader.trading import Strategy
from constants.shared_dict_key import SharedDictKey
from core import SharedState
from core.constants import SharedDictKeyBase
from core.enums import RuleSignal
from core.rules import RuleBase

@dataclass
class TurtleSoupRuleConfig:
    bar_type: BarType                 # target bar type to search the liquidity pools
    turtle_bars_count: int            # how many bars to consider when forming a turtle soup

class TurtleSoupRule(RuleBase):
    def __init__(self, shared_state: SharedState, strategy: Strategy, config: TurtleSoupRuleConfig):
        super().__init__(shared_state)
        self.strategy = strategy
        self.config = config
        self.first_bar_initialized = False

    def evaluate(self, bar: Bar, current_bar: Bar = None) -> bool:
        # Verify the bar type is correct
        if str(bar.bar_type) not in str(self.config.bar_type) and self.first_bar_initialized:
            return True

        if not self.first_bar_initialized:
            self.first_bar_initialized = True

        bars: List[Bar] = self.strategy.cache.bars(self.config.bar_type.standard())
        if not bars or len(bars) < self.config.turtle_bars_count:
            return True

        bars_slice: List[Bar] = bars[:self.config.turtle_bars_count]

        upper_liquidity_pools: List[float] = self.shared_state.get(SharedDictKey.UPPER_LIQUIDITY_POOLS, None)
        if upper_liquidity_pools:
            if self.__handle_upper_liquidity_raid(bars_slice, upper_liquidity_pools):
                self.shared_state.set(SharedDictKey.TURTLE_SOUP_RULE_SIGNAL, RuleSignal.SELL)
                return True

        lower_liquidity_pools: List[float] = self.shared_state.get(SharedDictKey.LOWER_LIQUIDITY_POOLS, None)
        if lower_liquidity_pools:
            if self.__handle_lower_liquidity_raid(bars_slice, lower_liquidity_pools):
                self.shared_state.set(SharedDictKey.TURTLE_SOUP_RULE_SIGNAL, RuleSignal.BUY)
                return True
        return True

    def __handle_upper_liquidity_raid(self, bars_slice: List[Bar], upper_liquidity_pools: List[float]) -> bool:
        for pool in upper_liquidity_pools:
            latest_pool = self.shared_state.get(SharedDictKey.TURTLE_SOUP_LATEST_UPPER_POOL_PRICE, None)
            if latest_pool:
                if pool == latest_pool:
                    continue

            if self.__check_upper_liquidity_raid(bars_slice, pool):
                self.shared_state.set(SharedDictKey.TURTLE_SOUP_LATEST_UPPER_POOL_PRICE, pool)
                bars_slice_highs = [float(b.high) for b in bars_slice if b is not None]
                self.shared_state.set(SharedDictKeyBase.ENTRY_SL_PRICE, max(bars_slice_highs))
                return True
        return False

    def __handle_lower_liquidity_raid(self, bars_slice: List[Bar], lower_liquidity_pools: List[float]) -> bool:
        for pool in lower_liquidity_pools:
            latest_pool = self.shared_state.get(SharedDictKey.TURTLE_SOUP_LATEST_LOWER_POOL_PRICE, None)
            if latest_pool:
                if pool == latest_pool:
                    continue

            if self.__check_lower_liquidity_raid(bars_slice, pool):
                self.shared_state.set(SharedDictKey.TURTLE_SOUP_LATEST_LOWER_POOL_PRICE, pool)
                bars_slice_lows = [float(b.low) for b in bars_slice if b is not None]
                self.shared_state.set(SharedDictKeyBase.ENTRY_SL_PRICE, min(bars_slice_lows))
                return True
        return False

    @staticmethod
    def __check_upper_liquidity_raid(bars_slice: List[Bar], liquidity_pool: float) -> bool:
        is_close_below_liquidity_pool = False
        is_close_above_liquidity_pool = False
        is_open_below_liquidity_pool = False

        for bar in bars_slice:
            if not is_close_below_liquidity_pool and bar.close < liquidity_pool:
                is_close_below_liquidity_pool = True
                continue
            if not is_close_above_liquidity_pool and bar.close > liquidity_pool:
                is_close_above_liquidity_pool = True
                continue
            if not is_open_below_liquidity_pool and bar.open < liquidity_pool:
                is_open_below_liquidity_pool = True
                continue
            if is_close_below_liquidity_pool and is_close_above_liquidity_pool and is_open_below_liquidity_pool:
                break

        return is_close_below_liquidity_pool and is_close_above_liquidity_pool and is_open_below_liquidity_pool

    @staticmethod
    def __check_lower_liquidity_raid(bars_slice: List[Bar], liquidity_pool: float) -> bool:
        is_close_above_liquidity_pool = False
        is_close_below_liquidity_pool = False
        is_open_above_liquidity_pool = False

        for bar in bars_slice:
            if not is_close_above_liquidity_pool and bar.close > liquidity_pool:
                is_close_above_liquidity_pool = True
                continue
            if not is_close_below_liquidity_pool and bar.close < liquidity_pool:
                is_close_below_liquidity_pool = True
                continue
            if not is_open_above_liquidity_pool and bar.open > liquidity_pool:
                is_open_above_liquidity_pool = True
                continue
            if is_close_above_liquidity_pool and is_close_below_liquidity_pool and is_open_above_liquidity_pool:
                break

        return is_close_above_liquidity_pool and is_close_below_liquidity_pool and is_open_above_liquidity_pool

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
            start_time = (now_ts - pd.Timedelta(days=30)).normalize()

            if self.is_backtest_mode:
                self.strategy.request_aggregated_bars([self.config.bar_type], start=start_time,
                                                      update_subscriptions=True)
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