# rules/turtle_soup_multi_tf_rule.py
from dataclasses import dataclass
from typing import List, Dict
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
        start_from: Timeframe in ``analysis_chain`` where analysis begins.
        turtle_bars_count: Number of most recent bars to consider when checking the
            Turtle Soup pattern.
    """
    levels_sources: List[BarType]      # e.g., [weekly, daily]
    analysis_chain: List[BarType]      # e.g., [daily, 4h, 1h, 15m, 5m, 1m]
    start_from: BarType                # e.g., daily (must be present in analysis_chain)
    turtle_bars_count: int

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
        self.first_bar_initialized = False

        # Validate configuration
        chain_str = [str(bt.standard()) for bt in self.config.analysis_chain]
        start_str = str(self.config.start_from.standard())
        if start_str not in chain_str:
            raise ValueError("start_from must be an element of analysis_chain")

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
        subscribed_tfs = {str(bt.standard()) for bt in (self.config.analysis_chain + self.config.levels_sources)}
        if str(bar.bar_type.standard()) not in subscribed_tfs and self.first_bar_initialized:
            return True
        if not self.first_bar_initialized:
            self.first_bar_initialized = True

        # Fetch levels maps produced by SearchLiquidityPoolsRule
        uppers_map: Dict[str, List[float]] = self.shared_state.get(SharedDictKey.UPPER_LIQUIDITY_POOLS, {})
        lowers_map: Dict[str, List[float]] = self.shared_state.get(SharedDictKey.LOWER_LIQUIDITY_POOLS, {})

        # 1) For each level source in order (e.g., Weekly, then Daily)
        for levels_bt in self.config.levels_sources:
            levels_key = str(levels_bt.standard())
            upper_liquidity_pools = uppers_map.get(levels_key)
            lower_liquidity_pools = lowers_map.get(levels_key)

            # If there are no levels for this TF yet — skip and wait
            if not upper_liquidity_pools and not lower_liquidity_pools:
                continue

            # 2) Determine the starting point within analysis_chain
            chain = self.config.analysis_chain
            start_idx = [str(bt.standard()) for bt in chain].index(str(self.config.start_from.standard()))

            # 3) Iterate analysis TFs from start_idx down to lower TFs
            for bt in chain[start_idx:]:
                bars: List[Bar] = self.strategy.cache.bars(bt.standard())
                if not bars or len(bars) < self.config.turtle_bars_count:
                    continue
                bars_slice = bars[:self.config.turtle_bars_count]

                # First, look for an upper-liquidity raid
                if upper_liquidity_pools:
                    if self.__handle_upper_liquidity_raid(bars_slice, upper_liquidity_pools):
                        self.shared_state.set(SharedDictKey.TURTLE_SOUP_RULE_SIGNAL, RuleSignal.SELL)
                        return True

                # Then, look for a lower-liquidity raid
                if lower_liquidity_pools:
                    if self.__handle_lower_liquidity_raid(bars_slice, lower_liquidity_pools):
                        self.shared_state.set(SharedDictKey.TURTLE_SOUP_RULE_SIGNAL, RuleSignal.BUY)
                        return True

            # If nothing is found for the current level source (e.g., Weekly),
            # move on to the next source (e.g., Daily) and repeat.

        return True

    def __handle_upper_liquidity_raid(self, bars_slice: List[Bar], upper_liquidity_pools: List[float]) -> bool:
        """Check if any upper liquidity pool was raided in the given bars slice.

        A valid upper raid pattern is delegated to ``__check_upper_liquidity_raid``.
        When a raid is confirmed, the latest upper pool price and a suggested
        stop-loss level (the max high in the slice) are stored in shared state.

        Args:
            bars_slice: The most recent bars to evaluate (length ``turtle_bars_count``).
            upper_liquidity_pools: Prices of upper liquidity pools for the current level source.

        Returns:
            True if a raid is detected for any pool; False otherwise.
        """
        for pool in upper_liquidity_pools:
            latest_pool = self.shared_state.get(SharedDictKey.TURTLE_SOUP_LATEST_UPPER_POOL_PRICE, None)
            if latest_pool and pool == latest_pool:
                continue
            if self.__check_upper_liquidity_raid(bars_slice, pool):
                self.shared_state.set(SharedDictKey.TURTLE_SOUP_LATEST_UPPER_POOL_PRICE, pool)
                bars_slice_highs = [float(b.high) for b in bars_slice if b is not None]
                self.shared_state.set(SharedDictKeyBase.ENTRY_SL_PRICE, max(bars_slice_highs))
                return True
        return False

    def __handle_lower_liquidity_raid(self, bars_slice: List[Bar], lower_liquidity_pools: List[float]) -> bool:
        """Check if any lower liquidity pool was raided in the given bars slice.

        A valid lower raid pattern is delegated to ``__check_lower_liquidity_raid``.
        When a raid is confirmed, the latest lower pool price and a suggested
        stop-loss level (the min low in the slice) are stored in shared state.

        Args:
            bars_slice: The most recent bars to evaluate (length ``turtle_bars_count``).
            lower_liquidity_pools: Prices of lower liquidity pools for the current level source.

        Returns:
            True if a raid is detected for any pool; False otherwise.
        """
        for pool in lower_liquidity_pools:
            latest_pool = self.shared_state.get(SharedDictKey.TURTLE_SOUP_LATEST_LOWER_POOL_PRICE, None)
            if latest_pool and pool == latest_pool:
                continue
            if self.__check_lower_liquidity_raid(bars_slice, pool):
                self.shared_state.set(SharedDictKey.TURTLE_SOUP_LATEST_LOWER_POOL_PRICE, pool)
                bars_slice_lows = [float(b.low) for b in bars_slice if b is not None]
                self.shared_state.set(SharedDictKeyBase.ENTRY_SL_PRICE, min(bars_slice_lows))
                return True
        return False

    @staticmethod
    def __check_upper_liquidity_raid(bars_slice: List[Bar], liquidity_pool: float) -> bool:
        """Detect an upper-liquidity raid pattern around the given level.

        Logic:
        1) First see a close below the level.
        2) Then see a close above the level (raid).
        3) Finally, see an open back below the level (failure back-thru) -> confirm.
        """
        seen_close_below = False
        seen_close_above = False
        for bar in bars_slice:
            if not seen_close_below:
                if bar.close < liquidity_pool:
                    seen_close_below = True
                continue
            if not seen_close_above:
                if bar.close > liquidity_pool:
                    seen_close_above = True
                continue
            if bar.open < liquidity_pool:
                return True
        return False

    @staticmethod
    def __check_lower_liquidity_raid(bars_slice: List[Bar], liquidity_pool: float) -> bool:
        """Detect a lower-liquidity raid pattern around the given level.

        Logic:
        1) First see a close above the level.
        2) Then see a close below the level (raid).
        3) Finally, see an open back above the level (failure back-thru) -> confirm.
        """
        seen_close_above = False
        seen_close_below = False
        for bar in bars_slice:
            if not seen_close_above:
                if bar.close > liquidity_pool:
                    seen_close_above = True
                continue
            if not seen_close_below:
                if bar.close < liquidity_pool:
                    seen_close_below = True
                continue
            if bar.open > liquidity_pool:
                return True
        return False

    def on_start(self) -> None:
        """Subscribe and warm up all bar types required by this rule.

        The method gathers unique bar types from both ``levels_sources`` and
        ``analysis_chain`` and ensures they are requested and subscribed. For
        backtests, aggregated bars are requested from a 30-day lookback; for
        live mode, individual requests per bar type are issued.
        """
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
        key = SharedDictKeyBase.WARMED_UP_AND_SUBSCRIBED_BAR_TYPES
        lst = self.shared_state.get(key, [])
        for bt in (self.config.levels_sources + self.config.analysis_chain):
            if bt in lst:
                try:
                    self.strategy.unsubscribe_bars(bt)
                finally:
                    if bt.standard() in lst:
                        lst.remove(bt.standard())