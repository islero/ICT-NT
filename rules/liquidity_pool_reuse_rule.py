from dataclasses import dataclass
from typing import List, Optional

from nautilus_trader.model import Bar
from nautilus_trader.model.data import BarType
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.trading import Strategy

from constants.shared_dict_key import SharedDictKey
from core import SharedState
from core.enums import RuleSignal
from core.rules import RuleBase


@dataclass
class LiquidityPoolReuseRuleConfig:
    """
    Configuration for the liquidity pool reuse rules.

    This class holds configuration attributes related to liquidity pool reuse. It is used
    to define the limits and rules on how often a liquidity pool can be reused for given
    financial instruments and bar types.

    :ivar bar_type: Specifies the type of bar data for the liquidity pool.
    :type bar_type: BarType
    :ivar instrument_id: Identifies the financial instrument associated with the pool.
    :type instrument_id: InstrumentId
    :ivar turtle_bars_count: Number of turtle bars to be considered for the pool.
    :type turtle_bars_count: int
    :ivar liquidity_pool_uses_count: The maximum number of times a pool can be reused
        before it becomes outdated.
    :type liquidity_pool_uses_count: int
    """

    bar_type: BarType
    instrument_id: InstrumentId
    turtle_bars_count: int
    liquidity_pool_uses_count: int  # the max number of times a pool can be used before its being outdated


class LiquidityPoolReuseRule(RuleBase):
    """
    Liquidity Pool Reuse Filter Rule.

    This rule does NOT generate signals. It filters pre-existing Turtle Soup signals
    based on whether the liquidity pool has already been "used" (has a confirmed pivot
    point formed above it for LOWER pools, or below it for UPPER pools).

    Logic:
        - For BUY signals (based on LOWER liquidity pools):
          * Get the latest lower pool price from TURTLE_SOUP_LATEST_LOWER_POOL_PRICE
          * Check if any pivot HIGH has formed ABOVE this pool level
          * If yes → pool is used → REJECT signal
          * If no → pool is fresh → ALLOW signal

        - For SELL signals (based on UPPER liquidity pools):
          * Get the latest upper pool price from TURTLE_SOUP_LATEST_UPPER_POOL_PRICE
          * Check if any pivot LOW has formed BELOW this pool level
          * If yes → pool is used → REJECT signal
          * If no → pool is fresh → ALLOW signal
    """

    def __init__(
        self,
        shared_state: SharedState,
        strategy: Strategy,
        config: LiquidityPoolReuseRuleConfig,
    ):
        super().__init__(shared_state)
        self.strategy = strategy
        self.config = config

    def evaluate(self, bar: Bar, current_bar: Bar = None) -> bool:
        """
        Evaluate if the Turtle Soup signal should be allowed based on liquidity pool reuse.

        Args:
            bar: The bar being processed
            current_bar: The current bar (optional)

        Returns:
            bool: True if the signal passes filter (allow trade), False if the signal is rejected
        """
        # Validate current bar
        if current_bar is None:
            return False

        # Verify the bar type is correct
        if str(bar.bar_type) not in str(self.config.bar_type):
            return True

        # Get the turtle soup signal direction
        turtle_soup_signal: Optional[RuleSignal] = self.shared_state.get(SharedDictKey.TURTLE_SOUP_RULE_SIGNAL)

        # If no signal, allow (nothing to filter)
        if turtle_soup_signal is None:
            return True

        # Filter based on a signal direction
        if turtle_soup_signal == RuleSignal.BUY:
            return self._check_lower_pool_not_reused()
        elif turtle_soup_signal == RuleSignal.SELL:
            return self._check_upper_pool_not_reused()

        # Unknown signal, allow by default
        return True

    def _check_lower_pool_not_reused(self) -> bool:
        """
        Check if the lower liquidity pool (for BUY signal) has NOT been reused.

        A lower pool is considered "used" if a pivot HIGH has formed ABOVE it.

        Returns:
            bool: True if pool is fresh (not reused), False if pool is already used
        """
        # Get the lower pool price that triggered the Turtle Soup BUY signal
        lower_pool: Optional[tuple[float, int]] = self.shared_state.get(SharedDictKey.TURTLE_SOUP_USED_POOL)

        if lower_pool is None:
            self.strategy.log.warning("BUY signal: Cannot verify pool reuse - no lower pool price available")
            return False

        price, ts_init = lower_pool

        bars: List[Bar] = self.strategy.cache.bars(self.config.bar_type.standard())
        if not bars or len(bars) < self.config.turtle_bars_count:
            return False

        # bars are sorted in descending order, so first element is the latest, take bars where bar.ts_init are > ts_init
        bars_slice = [bar for bar in bars if bar.ts_init > ts_init]

        # Find the maximum number of consecutive bars closed below the price
        max_consecutive_bars_below = 0
        current_consecutive = 0
        for bar in reversed(bars_slice):
            if bar.close < price:
                current_consecutive += 1
                max_consecutive_bars_below = max(max_consecutive_bars_below, current_consecutive)
            else:
                current_consecutive = 0

        # If more than turtle_bars_count consecutive bars closed below the price, pool is considered outdated
        if max_consecutive_bars_below > self.config.turtle_bars_count:
            return False

        # Count how many times bars transitioned from below to above the price
        reuse_count = 0
        was_below = False

        # Iterate in reverse order (oldest to newest) to track transitions
        for bar in reversed(bars_slice):
            if bar.close < price:
                was_below = True
            elif was_below and bar.close >= price:
                reuse_count += 1
                was_below = False

        # If the pool has been reused more than allowed, reject the signal
        if reuse_count >= self.config.liquidity_pool_uses_count:
            return False

        return True

    def _check_upper_pool_not_reused(self) -> bool:
        """
        Check if the upper liquidity pool (for SELL signal) has NOT been reused.

        An upper pool is considered "used" if a pivot LOW has formed BELOW it.

        Returns:
            bool: True if pool is fresh (not reused), False if pool is already used
        """
        # Get the upper pool price that triggered the Turtle Soup SELL signal
        upper_pool: Optional[tuple[float, int]] = self.shared_state.get(SharedDictKey.TURTLE_SOUP_USED_POOL)

        if upper_pool is None:
            self.strategy.log.warning("SELL signal: Cannot verify pool reuse - no upper pool price available")
            return False

        price, ts_init = upper_pool

        bars: List[Bar] = self.strategy.cache.bars(self.config.bar_type.standard())
        if not bars or len(bars) < self.config.turtle_bars_count:
            return False

        # bars are sorted in descending order, so first element is the latest, take bars where bar.ts_init are > ts_init
        bars_slice = [bar for bar in bars if bar.ts_init > ts_init]

        # Find the maximum number of consecutive bars closed above the price
        max_consecutive_bars_above = 0
        current_consecutive = 0
        for bar in reversed(bars_slice):
            if bar.close > price:
                current_consecutive += 1
                max_consecutive_bars_above = max(max_consecutive_bars_above, current_consecutive)
            else:
                current_consecutive = 0

        # If more than turtle_bars_count consecutive bars closed above the price, pool is considered outdated
        if max_consecutive_bars_above > self.config.turtle_bars_count:
            return False

        # Count how many times bars transitioned from above to below the price
        reuse_count = 0
        was_above = False

        # Iterate in reverse order (oldest to newest) to track transitions
        for bar in reversed(bars_slice):
            if bar.close > price:
                was_above = True
            elif was_above and bar.close <= price:
                reuse_count += 1
                was_above = False

        # If the pool has been reused more than allowed, reject the signal
        if reuse_count >= self.config.liquidity_pool_uses_count:
            return False

        return True
