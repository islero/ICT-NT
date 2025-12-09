from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from nautilus_trader.indicators.base import Indicator
from nautilus_trader.model.data import Bar


class FvgDirection(Enum):
    """Direction of a Fair Value Gap."""
    BULLISH = "bullish"
    BEARISH = "bearish"


@dataclass
class FvgRecord:
    """
    Record of a detected Fair Value Gap.

    Attributes:
        c1: First bar of the 3-bar pattern.
        c2: Middle bar of the 3-bar pattern.
        c3: Third bar of the 3-bar pattern.
        fvg_low: Lower boundary of the gap.
        fvg_high: Upper boundary of the gap.
        distance_percent: Gap size as percentage of midpoint.
        middle_candle_time: Timestamp of the middle candle (c2.ts_event).
        direction: Bullish or bearish FVG.
    """
    c1: Bar
    c2: Bar
    c3: Bar
    fvg_low: float
    fvg_high: float
    distance_percent: float
    middle_candle_time: int
    direction: FvgDirection


class FairValueGap(Indicator):
    """
    Fair Value Gap (FVG) indicator that detects imbalances in price action
    using a rolling 3-bar window.

    A Fair Value Gap represents an imbalance in price where the market moved
    so quickly that it left a gap between the wicks of consecutive candles.

    Logic:
    - Bullish FVG: c1.high < c3.low (gap up)
      - fvg_low = c1.high, fvg_high = c3.low
    - Bearish FVG: c1.low > c3.high (gap down)
      - fvg_low = c3.high, fvg_high = c1.low

    Attributes:
        min_distance_percent: Minimum gap size (%) to qualify as valid FVG.
        fvgs: List of all detected FVG records.
        last_fvg: Most recently detected FVG, or None if no FVGs detected.
        has_new_fvg: True if a new FVG was detected on the current bar.
    """

    def __init__(self, min_distance_percent: float = 0.0) -> None:
        """
        Initialize the Fair Value Gap indicator.

        Args:
            min_distance_percent: Minimum distance percentage to filter small gaps.
                                  Defaults to 0.0 (no filtering).
        """
        super().__init__([min_distance_percent])

        self._min_distance_percent = min_distance_percent

        # Rolling window of last 3 bars
        self._bar_window: list[Bar] = []

        # Detected FVGs
        self._fvgs: list[FvgRecord] = []

        # Signal flag (True for one bar when new FVG detected)
        self._has_new_fvg: bool = False

    def handle_bar(self, bar: Bar) -> None:
        """
        Process a new bar and check for Fair Value Gap formation.

        Args:
            bar: The new bar to process.
        """
        # Reset signal flag each bar
        self._has_new_fvg = False

        # Add bar to window
        self._bar_window.append(bar)

        # Keep only last 3 bars
        if len(self._bar_window) > 3:
            self._bar_window.pop(0)

        # Need at least 3 bars to detect FVG
        if len(self._bar_window) < 3:
            return

        c1, c2, c3 = self._bar_window

        # Check for Bullish FVG: c1.high < c3.low (gap up)
        if c1.high < c3.low:
            fvg_low = float(c1.high)
            fvg_high = float(c3.low)
            self._try_record_fvg(c1, c2, c3, fvg_low, fvg_high, FvgDirection.BULLISH)

        # Check for Bearish FVG: c1.low > c3.high (gap down)
        elif c1.low > c3.high:
            fvg_low = float(c3.high)
            fvg_high = float(c1.low)
            self._try_record_fvg(c1, c2, c3, fvg_low, fvg_high, FvgDirection.BEARISH)

    def _try_record_fvg(
        self,
        c1: Bar,
        c2: Bar,
        c3: Bar,
        fvg_low: float,
        fvg_high: float,
        direction: FvgDirection,
    ) -> None:
        """
        Attempt to record an FVG if it meets the minimum distance threshold.

        Args:
            c1: First bar.
            c2: Middle bar.
            c3: Third bar.
            fvg_low: Lower boundary of gap.
            fvg_high: Upper boundary of gap.
            direction: Bullish or bearish.
        """
        gap = fvg_high - fvg_low
        mid = (fvg_high + fvg_low) / 2
        distance_percent = (gap / mid) * 100 if mid != 0 else 0.0

        # Apply minimum distance filter
        if distance_percent < self._min_distance_percent:
            return

        record = FvgRecord(
            c1=c1,
            c2=c2,
            c3=c3,
            fvg_low=fvg_low,
            fvg_high=fvg_high,
            distance_percent=distance_percent,
            middle_candle_time=c2.ts_event,
            direction=direction,
        )

        self._fvgs.append(record)
        self._has_new_fvg = True

    def handle_trade_tick(self, tick) -> None:
        """Handle trade tick (not used by this indicator)."""
        pass

    def handle_quote_tick(self, tick) -> None:
        """Handle quote tick (not used by this indicator)."""
        pass

    def reset(self) -> None:
        """Reset all indicator state."""
        super().reset()
        self._bar_window.clear()
        self._fvgs.clear()
        self._has_new_fvg = False

    @property
    def min_distance_percent(self) -> float:
        """Minimum distance percentage threshold for FVG detection."""
        return self._min_distance_percent

    @property
    def fvgs(self) -> list[FvgRecord]:
        """List of all detected Fair Value Gaps."""
        return self._fvgs

    @property
    def last_fvg(self) -> Optional[FvgRecord]:
        """Most recently detected FVG, or None if no FVGs detected."""
        return self._fvgs[-1] if self._fvgs else None

    @property
    def has_new_fvg(self) -> bool:
        """True if a new FVG was detected on the current bar."""
        return self._has_new_fvg
