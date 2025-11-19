from __future__ import annotations

from collections import deque
from typing import Deque, Optional

from nautilus_trader.indicators.base import Indicator
from nautilus_trader.model.data import Bar


class PivotPointsHighLow(Indicator):
    """
    Pivot High/Low indicator replicating TradingView ta.pivothigh/ta.pivotlow logic.

    Parameters:
        left  (int):  number of bars to the left of the pivot candidate.
        right (int):  number of bars to the right of the pivot candidate.

    Notes:
    - A pivot is confirmed only after `right` bars have passed to the right
      of the candidate bar, so the signal is delayed by `right` bars (same as TradingView).
    - Pivot High:
        high[center] is strictly higher than all high values within the window
        of `left` bars to the left and `right` bars to the right.
    - Pivot Low:
        low[center] is strictly lower than all low values within the same window.
    """

    def __init__(self, left: int, right: int) -> None:
        if left < 0 or right < 0:
            raise ValueError("left and right must be >= 0")

        self._left = int(left)
        self._right = int(right)
        self._window_size = self._left + self._right + 1

        # Sliding window of bars + high/low values
        self._bars: Deque[Bar] = deque(maxlen=self._window_size)
        self._highs: Deque = deque(maxlen=self._window_size)
        self._lows: Deque = deque(maxlen=self._window_size)

        # Current/last confirmed pivots
        self._is_pivot_high: bool = False
        self._is_pivot_low: bool = False

        self._last_pivot_high_price = None     # Price of last confirmed pivot high
        self._last_pivot_high_ts: Optional[int] = None  # ts_event of center bar

        self._last_pivot_low_price = None      # Price of last confirmed pivot low
        self._last_pivot_low_ts: Optional[int] = None   # ts_event of center bar

        super().__init__([left, right])

    # -------------------------------------------------------------------------
    # Required Indicator methods
    # -------------------------------------------------------------------------
    def handle_bar(self, bar: Bar) -> None:
        """
        Update the indicator with a new bar.

        Args:
            bar (Bar): Standard Bar from nautilus_trader.model.data.
        """
        # Reset flags on the current bar
        self._is_pivot_high = False
        self._is_pivot_low = False

        # Add bar to the sliding window
        self._bars.append(bar)
        self._highs.append(bar.high)
        self._lows.append(bar.low)

        # If we do not yet have a full window, we cannot determine a pivot
        if len(self._bars) < self._window_size:
            return

        # Center bar: left bars on the left, right bars on the right
        center_idx = self._left
        center_high = self._highs[center_idx]
        center_low = self._lows[center_idx]

        # --- Pivot High ---
        is_pivot_high = True
        for i, h in enumerate(self._highs):
            if i == center_idx:
                continue
            # Strict comparison: center high must be higher than all others
            if h >= center_high:
                is_pivot_high = False
                break

        if is_pivot_high:
            self._is_pivot_high = True
            pivot_bar = list(self._bars)[center_idx-1]
            self._last_pivot_high_price = center_high
            self._last_pivot_high_ts = pivot_bar.ts_event

        # --- Pivot Low ---
        is_pivot_low = True
        for i, l in enumerate(self._lows):
            if i == center_idx:
                continue
            # Strict comparison: center low must be lower than all others
            if l <= center_low:
                is_pivot_low = False
                break

        if is_pivot_low:
            self._is_pivot_low = True
            pivot_bar = list(self._bars)[center_idx-1]
            self._last_pivot_low_price = center_low
            self._last_pivot_low_ts = pivot_bar.ts_event

    def handle_quote_tick(self, tick) -> None:
        # Quote ticks are not used in this indicator
        return

    def handle_trade_tick(self, tick) -> None:
        # Trade ticks are not used in this indicator
        return

    def reset(self) -> None:
        """Reset the indicator state."""
        super().reset()
        self._bars.clear()
        self._highs.clear()
        self._lows.clear()
        self._is_pivot_high = False
        self._is_pivot_low = False
        self._last_pivot_high_price = None
        self._last_pivot_high_ts = None
        self._last_pivot_low_price = None
        self._last_pivot_low_ts = None

    # -------------------------------------------------------------------------
    # Properties / public API in Nautilus style
    # -------------------------------------------------------------------------
    @property
    def left(self) -> int:
        return self._left

    @property
    def right(self) -> int:
        return self._right

    @property
    def window_size(self) -> int:
        return self._window_size

    @property
    def has_inputs(self) -> bool:
        """Return True if at least one bar has been processed."""
        return len(self._bars) > 0

    @property
    def initialized(self) -> bool:
        """
        Return True when the indicator has enough data
        to start confirming pivots (full window).
        """
        return len(self._bars) >= self._window_size

    @property
    def is_pivot_high(self) -> bool:
        """
        True only on the bar where a pivot high gets CONFIRMED
        (i.e., after `right` bars have passed to the right of center).
        """
        return self._is_pivot_high

    @property
    def is_pivot_low(self) -> bool:
        """
        True only on the bar where a pivot low gets CONFIRMED
        (i.e., after `right` bars have passed to the right of center).
        """
        return self._is_pivot_low

    @property
    def last_pivot_high_price(self):
        """Price of the last confirmed Pivot High (or None)."""
        return self._last_pivot_high_price

    @property
    def last_pivot_high_ts(self) -> Optional[int]:
        """ts_event of the center bar of the last Pivot High."""
        return self._last_pivot_high_ts

    @property
    def last_pivot_low_price(self):
        """Price of the last confirmed Pivot Low (or None)."""
        return self._last_pivot_low_price

    @property
    def last_pivot_low_ts(self) -> Optional[int]:
        """ts_event of the center bar of the last Pivot Low."""
        return self._last_pivot_low_ts

    @property
    def name(self) -> str:
        return f"PivotPointsHighLow(left={self._left}, right={self._right})"