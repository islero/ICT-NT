# rules/turtle_soup_multi_tf_rule.py
from dataclasses import dataclass
from typing import List, Dict, Optional
import pandas as pd
from nautilus_trader.model import BarType, Bar
from nautilus_trader.trading import Strategy
from constants.shared_dict_key import SharedDictKey
from core import SharedState
from core.constants import SharedDictKeyBase
from core.enums import RuleSignal
from core.rules import RuleBase

@dataclass
class TurtleSoupMultiTFRuleConfig:
    """Configuration for the multi-timeframe Turtle Soup rule.

    Attributes:
        levels_sources: Ordered list of timeframes used as sources for liquidity levels
            (e.g., weekly, then daily). The rule will iterate these sources in order.
        analysis_chain: Ordered list of timeframes used for pattern analysis starting
            from a higher timeframe and going down to lower ones (e.g., daily, 4h, 1h,
            15m, 5m, 1m). Must include ``start_from``.
        turtle_bars_count: Number of most recent bars to consider when checking the
            Turtle Soup pattern.
        retries_count_on_stop_out: Number of retries on the same day only N position can be reopened if all conditions are met
        sl_shift: Shift value to add/subtract from the stop loss level for buffer
    """
    levels_sources: List[BarType]      # e.g., [weekly, daily]
    analysis_chain: List[BarType]      # e.g., [daily, 4h, 1h, 15m, 5m, 1m]
    stop_loss_bar_type: BarType        # e.g., 1h
    turtle_bars_count: int             # e.g., 4 means 4 bars are using to check the pattern
    retries_count_on_stop_out: int     # e.g., 2 - means 2 retries on the same day
    sl_shift: float                    # e.g., 0.0001 - adds buffer to stop loss

class TurtleSoupMultiTFRule(RuleBase):
    """Multi-timeframe Turtle Soup rule.

    This rule consumes liquidity pool levels discovered on higher timeframes and
    scans through an analysis chain of lower timeframes to detect a classic
    Turtle Soup setup (liquidity raid followed by a failure back through the level).

    Workflow:
    - Iterate level sources in order (e.g., Weekly, then Daily) and fetch precomputed
      upper/lower liquidity pools from the shared state (produced by SearchLiquidityPoolsRule).
    - For each level source, walk through the analysis_chain starting from
      ``start_from`` down to lower timeframes and check the most recent
      ``turtle_bars_count`` bars for a raid pattern around each level.
    - If an upper raid is detected -> set SELL signal; if a lower raid is detected -> set BUY signal.

    The rule also manages subscriptions for the required bar types on start/stop.
    """
    def __init__(self, shared_state: SharedState, strategy: Strategy, config: TurtleSoupMultiTFRuleConfig):
        super().__init__(shared_state)
        self.strategy = strategy
        self.config = config

        # Track liquidity pool usage: {pool_price: {'date': str, 'attempts': int}}
        self.pool_usage_tracker: Dict[str, Dict] = {}

    def evaluate(self, bar: Bar, current_bar: Bar = None) -> bool:
        """Process an incoming bar and evaluate the rule conditions.

        The method only reacts to bars from subscribed timeframes (from either
        ``analysis_chain`` or ``levels_sources``). It fetches precomputed
        liquidity pools and scans the analysis chain to detect a Turtle Soup setup.

        Args:
            bar: The newly received bar (from any timeframe).
            current_bar: Unused. Present for compatibility.

        Returns:
            True (the rule is non-blocking). Sets signals in a shared state when detected.
        """
        # Process only bars from subscribed TFs (any from analysis_chain or levels_sources)
        subscribed_tfs = {str(bt.standard()) for bt in self.config.analysis_chain}
        if str(bar.bar_type.standard()) not in subscribed_tfs:
            return True

        if self.shared_state is None:
            return True

        current_date = self._get_current_date(bar)

        # Fetch levels maps produced by SearchLiquidityPoolsRule
        uppers_map: Dict[str, List[tuple[float, int]]] = self.shared_state.get(SharedDictKey.UPPER_LIQUIDITY_POOLS, {})
        lowers_map: Dict[str, List[tuple[float, int]]] = self.shared_state.get(SharedDictKey.LOWER_LIQUIDITY_POOLS, {})

        # 1) For each level source in order (e.g., Weekly, then Daily)
        for levels_bt in self.config.levels_sources:
            levels_key = str(levels_bt.standard())
            upper_liquidity_pools: List[tuple[float, int]] = uppers_map.get(levels_key, [])
            lower_liquidity_pools: List[tuple[float, int]] = lowers_map.get(levels_key, [])

            # If there are no levels for this TF yet — skip and wait
            if not upper_liquidity_pools and not lower_liquidity_pools:
                continue

            bars: List[Bar] = self.strategy.cache.bars(bar.bar_type.standard())
            if not bars or len(bars) < self.config.turtle_bars_count:
                continue
            bars_slice = bars[:self.config.turtle_bars_count]

            # First, look for an upper-liquidity raid
            if upper_liquidity_pools:
                pool_used = self.__handle_upper_liquidity_raid(bars_slice, upper_liquidity_pools, current_date, bar)
                if pool_used is not None:
                    self._mark_pool_usage(pool_used, current_date)
                    self._cleanup_pool_tracker(upper_liquidity_pools, lower_liquidity_pools, current_date)
                    self.shared_state.set(SharedDictKeyBase.ENTRY_RULE_SIGNAL, RuleSignal.SELL)
                    self.shared_state.set(SharedDictKey.TURTLE_SOUP_USED_POOL, pool_used)
                    return True

            # Then, look for a lower-liquidity raid
            if lower_liquidity_pools:
                pool_used = self.__handle_lower_liquidity_raid(bars_slice, lower_liquidity_pools, current_date, bar)
                if pool_used is not None:
                    self._mark_pool_usage(pool_used, current_date)
                    self._cleanup_pool_tracker(upper_liquidity_pools, lower_liquidity_pools, current_date)
                    self.shared_state.set(SharedDictKeyBase.ENTRY_RULE_SIGNAL, RuleSignal.BUY)
                    self.shared_state.set(SharedDictKey.TURTLE_SOUP_USED_POOL, pool_used)
                    return True

        return True

    @staticmethod
    def _get_current_date(bar: Bar) -> str:
        """Get the current date from the bar timestamp."""
        bar_ts = pd.Timestamp(bar.ts_init, tz="UTC", unit="ns")
        return bar_ts.strftime("%Y-%m-%d")

    def _can_use_pool(self, pool: tuple[float, int], current_date: str) -> bool:
        """Check if a liquidity pool can be used based on tracking rules.
        Rules:
        1. Cannot use if there's an open position on this pool
        2. Cannot use if already attempted 2 times today
        3. Cannot use if it was used on a previous day
        """
        # Rule 1: Check for open position
        price, ts_init = pool
        unique_key = f"{ts_init}:{price:.8f}"

        if unique_key not in self.pool_usage_tracker:
            return True

        tracker = self.pool_usage_tracker[unique_key]

        #TODO: this check has to be checked first
        if len(self.strategy.cache.positions_open()) > 0:
            return False

        # Rule 3: Check if used on a different day (not today)
        if tracker['date'] != current_date:
            return False

        # Rule 2: Check if already attempted 2 times today
        if tracker['date'] == current_date and tracker.get('attempts', 0) >= self.config.retries_count_on_stop_out:
            return False

        return True

    def _mark_pool_usage(self, pool: tuple[float, int], current_date: str):
        """Mark a liquidity pool as used for the current date."""
        price, ts_init = pool
        unique_key = f"{ts_init}:{price:.8f}"

        if unique_key not in self.pool_usage_tracker:
            self.pool_usage_tracker[unique_key] = {
                'date': current_date,
                'attempts': 1,
            }
        else:
            tracker = self.pool_usage_tracker[unique_key]
            if tracker['date'] == current_date:
                tracker['attempts'] = tracker.get('attempts', 0) + 1
            else:
                # New day, reset attempts
                tracker['date'] = current_date
                tracker['attempts'] = 1

    def _cleanup_pool_tracker(self, upper_liquidity_pools: list[tuple[float, int]], lower_liquidity_pools: list[tuple[float, int]],
                          current_date: str):
        """Remove pools from the tracker that no longer exist in current liquidity pools or are older than 1 month."""
        from datetime import datetime, timedelta

        valid_pools = set(upper_liquidity_pools + lower_liquidity_pools)
        current_dt = datetime.strptime(current_date, '%Y-%m-%d')
        one_month_ago = current_dt - timedelta(days=30)

        pools_to_remove = []
        for pool in self.pool_usage_tracker:
            pool_date = datetime.strptime(self.pool_usage_tracker[pool]['date'], '%Y-%m-%d')
            if pool not in valid_pools and pool_date < one_month_ago:
                pools_to_remove.append(pool)

        for pool in pools_to_remove:
            del self.pool_usage_tracker[pool]

    def __handle_upper_liquidity_raid(self, bars_slice: List[Bar], upper_liquidity_pools: List[tuple[float, int]], current_date: str, bar: Bar) -> Optional[tuple[float, int]]:
        """Check if any upper liquidity pool was raided in the given bars slice.

        A valid upper raid pattern is delegated to ``__check_upper_liquidity_raid``.
        When a raid is confirmed, the latest upper pool price and a suggested
        stop-loss level (the max high in the slice) are stored in the shared state.

        Args:
            bars_slice: The most recent bars to evaluate (length ``turtle_bars_count``).
            upper_liquidity_pools: Prices of upper liquidity pools for the current level source.
            current_date: Current date string for tracking.

        Returns:
            The pool price if a raid is detected and the pool can be used; None otherwise.
        """
        for pool in upper_liquidity_pools:
            # Check if we can use this pool based on tracking rules
            if not self._can_use_pool(pool, current_date):
                continue

            if self.__check_upper_liquidity_raid(bars_slice, pool):
                # Stop Loss bars slice

                bars_slice_current_tf_highs = [float(b.high) for b in bars_slice if b is not None]
                highest_high_current_tf_in_slice = max(bars_slice_current_tf_highs)

                sl_bars = self.strategy.cache.bars(self.config.stop_loss_bar_type.standard())
                sl_bar_slice = sl_bars[:self.config.turtle_bars_count]
                sl_bar_slice_highs = [float(b.high) for b in sl_bar_slice if b is not None]
                highest_high_new_bar_in_slice = max(sl_bar_slice_highs)

                if self.shared_state:
                    stop_loss = max(highest_high_current_tf_in_slice, highest_high_new_bar_in_slice) + self.config.sl_shift
                    self.shared_state.set(SharedDictKeyBase.ENTRY_SL_PRICE, stop_loss)
                    
                return pool
        return None

    def __handle_lower_liquidity_raid(self, bars_slice: List[Bar], lower_liquidity_pools: List[tuple[float, int]], current_date: str, new_bar: Bar) -> Optional[tuple[float, int]]:
        """Check if any lower liquidity pool was raided in the given bars slice.

        A valid lower raid pattern is delegated to ``__check_lower_liquidity_raid``.
        When a raid is confirmed, the latest lower pool price and a suggested
        stop-loss level (the min low in the slice) are stored in the shared state.

        Args:
            bars_slice: The most recent bars to evaluate (length ``turtle_bars_count``).
            lower_liquidity_pools: Prices of lower liquidity pools for the current level source.
            current_date: Current date string for tracking.

        Returns:
            The pool price if a raid is detected and the pool can be used; None otherwise.
        """
        for pool in lower_liquidity_pools:
            # Check if we can use this pool based on tracking rules
            if not self._can_use_pool(pool, current_date):
                continue

            if self.__check_lower_liquidity_raid(bars_slice, pool):
                # Stop Loss bars slice
                bars_slice_current_tf_lows = [float(b.low) for b in bars_slice if b is not None]
                lowest_low_current_tf_in_slice = min(bars_slice_current_tf_lows)

                sl_bars = self.strategy.cache.bars(self.config.stop_loss_bar_type.standard())
                sl_bar_slice = sl_bars[:self.config.turtle_bars_count]
                sl_bar_slice_lows = [float(b.low) for b in sl_bar_slice if b is not None]
                lowest_low_new_bar_in_slice = min(sl_bar_slice_lows)

                if self.shared_state:
                    stop_loss = min(lowest_low_current_tf_in_slice, lowest_low_new_bar_in_slice) - self.config.sl_shift
                    self.shared_state.set(SharedDictKeyBase.ENTRY_SL_PRICE, stop_loss)

                return pool
        return None

    @staticmethod
    def __check_upper_liquidity_raid(bars_slice: List[Bar], liquidity_pool: tuple[float, int]) -> bool:
        """Detect an upper-liquidity raid pattern around the given level.

        Logic:
        1) First see a close below the level.
        2) Then see a close above the level (raid).
        3) Finally, see an open back below the level (failure back-thru) -> confirm.
        """
        price, ts_init = liquidity_pool

        most_recent_bar = bars_slice[0]
        if most_recent_bar.close > price:
            return False

        seen_close_above = False
        for bar in bars_slice:
            if not seen_close_above:
                if bar.close > price:
                    seen_close_above = True
                continue
            if bar.open < price:
                return True
        return False

    @staticmethod
    def __check_lower_liquidity_raid(bars_slice: List[Bar], liquidity_pool: tuple[float, int]) -> bool:
        """Detect a lower-liquidity raid pattern around the given level.

        Logic:
        1) First see a close above the level by the most recent bar.
        2) Then see a close below the level (raid).
        3) Finally, see an open back above the level (failure back-thru) -> confirm.
        """
        price, ts_init = liquidity_pool

        most_recent_bar = bars_slice[0]
        if most_recent_bar.close < price:
            return False

        seen_close_below = False
        for bar in bars_slice:
            if not seen_close_below:
                if bar.close < price:
                    seen_close_below = True
                continue
            if bar.open > price:
                return True
        return False

    def on_start(self) -> None:
        """Subscribe and warm up all bar types required by this rule.

        The method gathers unique bar types from both ``levels_sources`` and
        ``analysis_chain`` and ensures they are requested and subscribed. For
        backtests, aggregated bars are requested from a 30-day lookback; for
        live mode, individual requests per bar type are issued.
        """
        if self.shared_state is None:
            return

        key = SharedDictKeyBase.WARMED_UP_AND_SUBSCRIBED_BAR_TYPES
        lst = self.shared_state.get(key, [])
        if not lst:
            self.shared_state.set(key, lst)

        # Build the set of unique BarTypes to subscribe
        to_subscribe = []
        for bt in (self.config.levels_sources + self.config.analysis_chain):
            std = bt.standard()
            if std not in lst:
                lst.append(std)
                to_subscribe.append(bt)

        if to_subscribe:
            now_ts = pd.Timestamp(self.strategy.clock.timestamp_ns(), tz="UTC", unit="ns")
            start_time = (now_ts - pd.Timedelta(days=30)).normalize()

            if self.is_backtest_mode:
                self.strategy.request_aggregated_bars(to_subscribe, start=start_time, update_subscriptions=True)
            else:
                for bt in to_subscribe:
                    self.strategy.request_bars(bt, start=start_time, limit=1000)
            for bt in to_subscribe:
                self.strategy.subscribe_bars(bt)

    def on_stop(self) -> None:
        """Unsubscribe from all bar types previously subscribed in on_start.

        Ensures the subscription list in the shared state is kept in sync by removing
        each bar type after a best-effort unsubscribed.
        """
        if self.shared_state is None:
            return

        key = SharedDictKeyBase.WARMED_UP_AND_SUBSCRIBED_BAR_TYPES
        lst = self.shared_state.get(key, [])
        for bt in (self.config.levels_sources + self.config.analysis_chain):
            if bt in lst:
                try:
                    self.strategy.unsubscribe_bars(bt)
                finally:
                    if bt.standard() in lst:
                        lst.remove(bt.standard())
