from abc import ABC, abstractmethod
from typing import Optional, ClassVar, List
from nautilus_trader.core import Data
from nautilus_trader.model import Bar, BarType, Quantity
from nautilus_trader.model.enums import AggregationSource
from nautilus_trader.trading import Strategy
from core import SharedState
from core.constants import SharedDictKeyBase

class RuleBase(ABC):
    """
    Abstract base for all trading rules.
    Child classes must implement the `evaluate` method.
    """
    # Shared, process-wide backtest flag accessible by all subclasses
    is_backtest: ClassVar[bool] = False

    @classmethod
    def configure_environment(cls, is_backtest: bool) -> None:
        """Configure a shared backtest flag for all rules.

        Calling this once (e.g., from your Strategy on startup) sets a
        process-wide flag accessible by all subclasses via `RuleBase.is_backtest`
        or `self.is_backtest_mode`.

        Parameters
        ----------
        is_backtest : bool
            True if running in a backtest/simulation environment; False for live/paper.
        """
        cls.is_backtest = bool(is_backtest)

    @property
    def is_backtest_mode(self) -> bool:
        """Return whether the shared environment is configured as a backtest.

        This simply returns the class-level `RuleBase.is_backtest` to make
        instance code more readable (e.g., `if self.is_backtest_mode:`).
        """
        return type(self).is_backtest
    def __init__(self, shared_state: Optional[SharedState] = None):
        self.shared_state = shared_state

    @abstractmethod
    def evaluate(self, bar: Bar, current_bar: Bar = None) -> bool:
        """Check if the rule is satisfied."""
        pass

    def on_register_indicator_for_bars(self) -> None:
        """Register the indicator for the bars before the warmup period."""
        pass

    def on_start(self) -> None:
        """Actions to be performed on strategy start."""
        pass

    def on_stop(self) -> None:
        """Actions to be performed on strategy stop."""
        pass

    def on_historical_data(self, data: Data):
        """This method is called by the framework (see actor.py docstring for on_historical_data)
        Forward the payload to the rule:"""
        pass

    def on_bar(self, bar: Bar):
        """This method is called by the framework (see actor.py docstring for on_bar)
        Forward the payload to the rule:"""
        pass

    @staticmethod
    def _calculate_not_full_bar(strategy: Strategy, bar_type: BarType, base_bar_type: BarType) -> tuple[Bar | None, Bar | None]:
        """Build the current *not full* bar from base bars.

        Semantics (as requested): use **all** base bars with `ts_init >= bar_close_ts`,
        where `bar_close_ts = bar.ts_init + (bar.ts_init - prior_bar.ts_init)`.

        Assumptions:
        - `strategy.cache.bar(..., index=0)` returns the most recent (DESC order by `ts_init`).
        - `strategy.cache.bars(base_bar_type.standard())` returns a list **sorted DESC** by `ts_init`.

        Performance notes:
        - No list comprehensions over the full array; we take a slice prefix by index.
        - Custom binary search on a DESC array to find the split point in O(log n).
        - Single-pass OHLCV aggregation over the selected prefix [0: split_idx].
        """
        bar = strategy.cache.bar(bar_type.standard(), index=0)
        if bar is None:
            return None, None

        base_bars_all: List[Bar] = strategy.cache.bars(base_bar_type.standard())
        if not base_bars_all:
            return None, None

        # --- Binary search on DESC-ordered ts_init to find the first index where ts < bar_close_ts ---
        lo = 0
        hi = len(base_bars_all)
        while lo < hi:
            mid = (lo + hi) // 2
            if base_bars_all[mid].ts_init >= bar.ts_init:
                lo = mid + 1
            else:
                hi = mid
        split_idx = lo  # number of elements satisfying ts_init >= bar_close_ts

        if split_idx <= 1:
            # zero or one base bars are not enough to aggregate a meaningful not-full bar
            return None, None

        # Aggregate OHLCV over base_bars_all[0: split_idx]
        first = base_bars_all[0]  # newest in the selected prefix
        last = base_bars_all[split_idx - 1]  # oldest in the selected prefix

        open_price = last.open
        close_price = first.close

        # Initialize with the first element to avoid branching in the loop
        high_price = first.high
        low_price = first.low
        volume_acc = first.volume

        for i in range(1, split_idx):
            b = base_bars_all[i]
            h = b.high
            if h > high_price:
                high_price = h
            l = b.low
            if l < low_price:
                low_price = l
            volume_acc += b.volume

        # `Quantity` construction kept consistent with existing code
        volume_q = Quantity.from_str(f"{volume_acc}")

        bar_for_consolidation: Bar = Bar(bar_type, open_price, high_price, low_price, first.close, volume_q, bar.ts_event, bar.ts_init)
        bar_for_indicator: Bar = Bar(bar_type, open_price, high_price, low_price, first.open, volume_q, bar.ts_event, bar.ts_init)

        return bar_for_consolidation, bar_for_indicator

    @staticmethod
    def _to_external(bar_type: BarType) -> BarType:
        """
        Converts a BarType instance to an external representation.
        This method standardizes
        the BarType object and updates its aggregation source to EXTERNAL.

        :param bar_type: The BarType object to be converted.
        :type bar_type: BarType
        :return: A new BarType instance with an updated aggregation source set to EXTERNAL.
        :rtype: BarType
        """
        standard_bar_type = bar_type.standard()
        return BarType(standard_bar_type.instrument_id, standard_bar_type.spec, AggregationSource.EXTERNAL)

    @staticmethod
    def _is_wait_for_most_recent_bar(strategy: Strategy, bar_type: BarType, current_ts_ns: int) -> bool:
        """
        Determines if the system should wait for the most recent bar and doesn't allow to trade.

        :param strategy: Strategy instance containing the cache for accessing bars.
        :param bar_type: Type of bar (BarType) used for identifying the bar data.
        :param current_ts_ns: Current timestamp in nanoseconds to be compared with the
            most recent bar's timing.
        :return: Boolean is indicating whether to wait for the most recent bar or not.
        """
        current_bar = strategy.cache.bar(bar_type.standard(), index=0)
        if current_bar is None:
            return False

        prior_bar = strategy.cache.bar(bar_type.standard(), index=1)
        if prior_bar is None:
            return False

        # calculate nanosecond difference between bar and prior bar
        bars_diff = current_bar.ts_init - prior_bar.ts_init

        # expected close timestamp for the current bar based on bar spacing
        expected_close_ts = current_bar.ts_init + bars_diff

        # How many full days has `current_ts_ns` exceeded the expected close?
        # This accounts for weekends/holidays (non-business days) by measuring wall-clock days.
        DAY_NS = 86_400_000_000_000  # 24 * 60 * 60 * 1e9
        days_overdue = 0
        if current_ts_ns > expected_close_ts:
            days_overdue = (current_ts_ns - expected_close_ts) / DAY_NS

        # If we're overdue by at least one full day, don't keep waiting for a "most recent" bar
        # (market may have been closed due to non-business days). Otherwise, use the original check.
        if days_overdue >= 1:
            return False

        return current_ts_ns >= expected_close_ts

    @staticmethod
    def _timeframes_sync(current_bar: Bar, strategy: Strategy, bar_type: BarType, shared_state: SharedState) -> bool:
        if not current_bar:
            return True

        # Safely track the sync state for the bar type
        timeframes = shared_state.get(SharedDictKeyBase.TIMEFRAMES_SYNC, {})

        # Ensure dict, not a list or something else
        if not isinstance(timeframes, dict):
            timeframes = {}

        if RuleBase._is_wait_for_most_recent_bar(strategy, bar_type, current_bar.ts_init):
            # Update or insert the flag for this bar type
            timeframes[str(bar_type.standard())] = False
            shared_state.set(SharedDictKeyBase.TIMEFRAMES_SYNC, timeframes)
            return False
        else:
            # When we are NOT waiting for the most recent bar, mark the timeframe as in-sync
            timeframes[str(bar_type.standard())] = True
            shared_state.set(SharedDictKeyBase.TIMEFRAMES_SYNC, timeframes)
            return True

    def _are_all_timeframes_in_sync(self) -> bool:
        """Return True if all tracked timeframes are marked as in-sync (True)."""
        timeframes = self.shared_state.get(SharedDictKeyBase.TIMEFRAMES_SYNC, {})
        if not isinstance(timeframes, dict):
            return False  # no timeframes tracked or invalid structure

        if not timeframes:
            return True

        return all(timeframes.values())

    @staticmethod
    def _is_future_bar(strategy: Strategy, bar_type: BarType, base_bar_type: BarType) -> bool:
        bar = strategy.cache.bar(bar_type.standard(), index=0)
        if bar is None:
            return False

        prior_bar = strategy.cache.bar(bar_type.standard(), index=1)
        if prior_bar is None:
            return False

        # calculate nanosecond difference between bar and prior bar
        bars_diff = bar.ts_init - prior_bar.ts_init

        base_bar = strategy.cache.bar(base_bar_type.standard(), index=0)

        if base_bar is None:
            return False

        return bar.ts_init + bars_diff > base_bar.ts_init