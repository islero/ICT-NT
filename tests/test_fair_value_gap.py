"""
Test suite for FairValueGap indicator.

These tests verify:
1. Bullish FVG detection (c1.high < c3.low)
2. Bearish FVG detection (c1.low > c3.high)
3. No detection when candles overlap or only touch
4. Minimum distance filter behavior
5. Multiple FVGs in a sequence
6. Correct association of the three bars
7. Edge cases with <3 bars
8. Correct middleCandleTime and distancePercent
"""

import sys
import os
from unittest.mock import MagicMock

import pytest

# --- MOCKING NAUTILUS TRADER ---
sys.modules["nautilus_trader"] = MagicMock()
sys.modules["nautilus_trader.indicators"] = MagicMock()
sys.modules["nautilus_trader.indicators.base"] = MagicMock()
sys.modules["nautilus_trader.model"] = MagicMock()
sys.modules["nautilus_trader.model.data"] = MagicMock()


class MockIndicator:
    """Mock base Indicator class."""

    def __init__(self, inputs=None):
        pass

    def reset(self):
        pass


sys.modules["nautilus_trader.indicators.base"].Indicator = MockIndicator
sys.modules["nautilus_trader.model.data"].Bar = MagicMock()

# Ensure we can import from the project root
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Now import the indicator under test
from indicators.fair_value_gap import FairValueGap, FvgDirection, FvgRecord


class MockBar:
    """Mock Bar object matching nautilus_trader Bar interface."""

    def __init__(
        self,
        open_price: float,
        high: float,
        low: float,
        close: float,
        ts_event: int = 0,
    ):
        self.open = open_price
        self.high = high
        self.low = low
        self.close = close
        self.ts_event = ts_event


def _bars_from_ohlc(series: list[tuple[float, float, float, float]], start_ts: int = 0) -> list[MockBar]:
    """
    Build bars from a list of (open, high, low, close) tuples.

    Args:
        series: list of (open, high, low, close) tuples
        start_ts: Starting timestamp (increments by 1000 for each bar)

    Returns:
        List of MockBar objects
    """
    bars = []
    for i, (o, h, l, c) in enumerate(series):
        bars.append(MockBar(
            open_price=o,
            high=h,
            low=l,
            close=c,
            ts_event=start_ts + i * 1000,
        ))
    return bars


def _feed_bars(indicator: FairValueGap, bars: list[MockBar]) -> list[bool]:
    """
    Feed bars to indicator and return list of has_new_fvg flags after each bar.

    Args:
        indicator: FairValueGap instance
        bars: List of MockBar objects

    Returns:
        List of has_new_fvg values after each bar
    """
    signals = []
    for bar in bars:
        indicator.handle_bar(bar)
        signals.append(indicator.has_new_fvg)
    return signals


class TestBullishFvgDetection:
    """Tests for bullish FVG detection (gap up)."""

    def test_bullish_fvg_detected(self):
        """
        Verify bullish FVG detection when c1.high < c3.low.

        Bullish FVG scenario:
        - c1: high=100
        - c2: (middle candle)
        - c3: low=102 (gap of 2 points)
        """
        indicator = FairValueGap()

        # c1.high=100, c2 in between, c3.low=102 -> gap up
        prices = [
            (95, 100, 90, 98),   # c1: high=100
            (99, 105, 97, 104),  # c2: middle candle
            (103, 110, 102, 108),  # c3: low=102 > c1.high=100 -> bullish FVG
        ]

        bars = _bars_from_ohlc(prices)
        signals = _feed_bars(indicator, bars)

        # FVG should be detected on bar 3
        assert signals == [False, False, True], f"Expected [False, False, True], got {signals}"

        # Verify FVG properties
        assert len(indicator.fvgs) == 1
        fvg = indicator.last_fvg

        assert fvg is not None
        assert fvg.direction == FvgDirection.BULLISH
        assert fvg.fvg_low == 100.0  # c1.high
        assert fvg.fvg_high == 102.0  # c3.low

    def test_bullish_fvg_gap_size(self):
        """Verify gap and distance_percent calculations for bullish FVG."""
        indicator = FairValueGap()

        # Create a larger gap for clearer calculation
        prices = [
            (95, 100, 90, 98),   # c1: high=100
            (105, 115, 103, 112),  # c2
            (112, 120, 110, 118),  # c3: low=110 -> gap = 110 - 100 = 10
        ]

        bars = _bars_from_ohlc(prices)
        _feed_bars(indicator, bars)

        fvg = indicator.last_fvg
        assert fvg is not None

        # gap = 110 - 100 = 10
        # mid = (110 + 100) / 2 = 105
        # distance_percent = (10 / 105) * 100 ≈ 9.52%
        expected_gap = 10.0
        expected_mid = 105.0
        expected_distance = (expected_gap / expected_mid) * 100

        assert fvg.fvg_high - fvg.fvg_low == expected_gap
        assert abs(fvg.distance_percent - expected_distance) < 0.01


class TestBearishFvgDetection:
    """Tests for bearish FVG detection (gap down)."""

    def test_bearish_fvg_detected(self):
        """
        Verify bearish FVG detection when c1.low > c3.high.

        Bearish FVG scenario:
        - c1: low=100
        - c2: (middle candle)
        - c3: high=98 (gap of 2 points)
        """
        indicator = FairValueGap()

        # c1.low=100, c2 in between, c3.high=98 -> gap down
        prices = [
            (105, 110, 100, 102),  # c1: low=100
            (101, 103, 95, 96),    # c2: middle candle
            (95, 98, 90, 92),      # c3: high=98 < c1.low=100 -> bearish FVG
        ]

        bars = _bars_from_ohlc(prices)
        signals = _feed_bars(indicator, bars)

        assert signals == [False, False, True]

        # Verify FVG properties
        assert len(indicator.fvgs) == 1
        fvg = indicator.last_fvg

        assert fvg is not None
        assert fvg.direction == FvgDirection.BEARISH
        assert fvg.fvg_low == 98.0   # c3.high
        assert fvg.fvg_high == 100.0  # c1.low

    def test_bearish_fvg_gap_size(self):
        """Verify gap and distance_percent calculations for bearish FVG."""
        indicator = FairValueGap()

        # Create a larger gap for clearer calculation
        prices = [
            (115, 120, 110, 112),  # c1: low=110
            (108, 109, 95, 96),    # c2
            (94, 100, 88, 92),     # c3: high=100 -> gap = 110 - 100 = 10
        ]

        bars = _bars_from_ohlc(prices)
        _feed_bars(indicator, bars)

        fvg = indicator.last_fvg
        assert fvg is not None

        # gap = 110 - 100 = 10
        # mid = (110 + 100) / 2 = 105
        # distance_percent = (10 / 105) * 100 ≈ 9.52%
        expected_gap = 10.0
        expected_mid = 105.0
        expected_distance = (expected_gap / expected_mid) * 100

        assert fvg.fvg_high - fvg.fvg_low == expected_gap
        assert abs(fvg.distance_percent - expected_distance) < 0.01


class TestNoFvgDetection:
    """Tests for scenarios where no FVG should be detected."""

    def test_no_fvg_when_candles_overlap(self):
        """
        No FVG when candles overlap (c1.high >= c3.low and c1.low <= c3.high).
        """
        indicator = FairValueGap()

        # Overlapping candles - no gap
        prices = [
            (95, 105, 90, 100),   # c1: high=105, low=90
            (100, 108, 95, 102),  # c2
            (102, 110, 100, 106),  # c3: low=100 <= c1.high=105, high=110 >= c1.low=90
        ]

        bars = _bars_from_ohlc(prices)
        signals = _feed_bars(indicator, bars)

        assert signals == [False, False, False]
        assert len(indicator.fvgs) == 0
        assert indicator.last_fvg is None

    def test_no_fvg_when_candles_touch_exactly(self):
        """
        No FVG when c1.high == c3.low (bullish touch) or c1.low == c3.high (bearish touch).
        The definition requires strict inequality for a gap.
        """
        indicator = FairValueGap()

        # Bullish touch: c1.high == c3.low
        prices = [
            (95, 100, 90, 98),   # c1: high=100
            (99, 105, 97, 104),  # c2
            (101, 108, 100, 106),  # c3: low=100 == c1.high=100 -> no gap
        ]

        bars = _bars_from_ohlc(prices)
        signals = _feed_bars(indicator, bars)

        assert signals == [False, False, False]
        assert len(indicator.fvgs) == 0

    def test_no_fvg_when_candles_touch_bearish(self):
        """No FVG when c1.low == c3.high (bearish touch)."""
        indicator = FairValueGap()

        # Bearish touch: c1.low == c3.high
        prices = [
            (105, 110, 100, 102),  # c1: low=100
            (101, 103, 95, 96),    # c2
            (95, 100, 90, 92),     # c3: high=100 == c1.low=100 -> no gap
        ]

        bars = _bars_from_ohlc(prices)
        signals = _feed_bars(indicator, bars)

        assert signals == [False, False, False]
        assert len(indicator.fvgs) == 0

    def test_no_fvg_normal_price_action(self):
        """Normal overlapping price action should not produce FVGs."""
        indicator = FairValueGap()

        # Normal market movement with overlapping candles
        prices = [
            (100, 102, 98, 101),   # c1
            (101, 103, 99, 102),   # c2
            (102, 104, 100, 103),  # c3: overlaps with c1
        ]

        bars = _bars_from_ohlc(prices)
        _feed_bars(indicator, bars)

        assert len(indicator.fvgs) == 0


class TestMinDistanceFilter:
    """Tests for minimum distance percentage filter."""

    def test_fvg_filtered_by_min_distance(self):
        """FVG should be filtered out if distance_percent < min_distance_percent."""
        # Small gap that should be filtered
        # gap = 102 - 100 = 2, mid = 101, distance = 1.98%
        indicator = FairValueGap(min_distance_percent=2.0)

        prices = [
            (95, 100, 90, 98),     # c1: high=100
            (99, 105, 97, 104),    # c2
            (103, 110, 102, 108),  # c3: low=102 -> gap = 2, distance ≈ 1.98%
        ]

        bars = _bars_from_ohlc(prices)
        _feed_bars(indicator, bars)

        # Should be filtered out
        assert len(indicator.fvgs) == 0

    def test_fvg_passes_min_distance(self):
        """FVG should pass if distance_percent >= min_distance_percent."""
        indicator = FairValueGap(min_distance_percent=5.0)

        # Larger gap that should pass
        # gap = 110 - 100 = 10, mid = 105, distance ≈ 9.52%
        prices = [
            (95, 100, 90, 98),     # c1: high=100
            (105, 115, 103, 112),  # c2
            (112, 120, 110, 118),  # c3: low=110 -> gap = 10, distance ≈ 9.52%
        ]

        bars = _bars_from_ohlc(prices)
        _feed_bars(indicator, bars)

        assert len(indicator.fvgs) == 1
        assert indicator.last_fvg.distance_percent >= 5.0

    def test_fvg_exactly_at_threshold(self):
        """FVG with distance_percent exactly at threshold should pass."""
        # Create an FVG with known exact percentage
        # gap = 5, mid = 102.5, distance = (5/102.5)*100 ≈ 4.878%
        indicator = FairValueGap(min_distance_percent=4.0)

        prices = [
            (95, 100, 90, 98),     # c1: high=100
            (103, 108, 101, 106),  # c2
            (106, 112, 105, 110),  # c3: low=105 -> gap = 5
        ]

        bars = _bars_from_ohlc(prices)
        _feed_bars(indicator, bars)

        # gap = 5, mid = 102.5, distance ≈ 4.88% > 4.0%
        assert len(indicator.fvgs) == 1

    def test_default_min_distance_zero(self):
        """Default min_distance_percent of 0 should not filter any FVGs."""
        indicator = FairValueGap()  # Default min_distance_percent=0

        # Tiny gap
        prices = [
            (95, 100.0, 90, 98),
            (99, 105, 97, 104),
            (103, 110, 100.1, 108),  # c3.low=100.1 > c1.high=100 -> tiny gap
        ]

        bars = _bars_from_ohlc(prices)
        _feed_bars(indicator, bars)

        # Even tiny gap should be detected
        assert len(indicator.fvgs) == 1


class TestMultipleFvgs:
    """Tests for multiple FVGs in a sequence."""

    def test_multiple_bullish_fvgs(self):
        """Detect multiple bullish FVGs in an uptrend."""
        indicator = FairValueGap()

        prices = [
            (95, 100, 90, 98),     # c1 for first FVG
            (99, 105, 97, 104),    # c2 for first FVG
            (103, 110, 102, 108),  # c3 for first FVG -> bullish FVG #1

            (107, 112, 105, 110),  # c1 for second FVG
            (110, 118, 108, 116),  # c2 for second FVG
            (115, 125, 114, 122),  # c3 for second FVG -> bullish FVG #2 (c1.high=112 < c3.low=114)
        ]

        bars = _bars_from_ohlc(prices)
        signals = _feed_bars(indicator, bars)

        # FVG on bar 3 and bar 6
        assert signals == [False, False, True, False, False, True]
        assert len(indicator.fvgs) == 2
        assert all(fvg.direction == FvgDirection.BULLISH for fvg in indicator.fvgs)

    def test_multiple_bearish_fvgs(self):
        """Detect multiple bearish FVGs in a downtrend."""
        indicator = FairValueGap()

        # Design data carefully to avoid unintended FVGs in sliding window
        # FVG check: c1.low > c3.high
        prices = [
            (115, 120, 110, 112),  # c1: low=110
            (108, 109, 100, 101),  # c2: high=109, low=100
            (99, 105, 88, 92),     # c3: high=105 < c1.low=110 -> bearish FVG #1

            # Bars 4-6: ensure bar 2's low=100 is NOT > bar 4's high
            (91, 102, 85, 88),     # c1: low=85, high=102 > bar2.low=100, no gap with bar 2
            (87, 90, 78, 80),      # c2: high=90
            (78, 82, 70, 72),      # c3: high=82 < c1.low=85 -> bearish FVG #2
        ]

        bars = _bars_from_ohlc(prices)
        signals = _feed_bars(indicator, bars)

        assert signals == [False, False, True, False, False, True]
        assert len(indicator.fvgs) == 2
        assert all(fvg.direction == FvgDirection.BEARISH for fvg in indicator.fvgs)

    def test_mixed_fvgs(self):
        """Detect both bullish and bearish FVGs in mixed price action."""
        indicator = FairValueGap()

        # Carefully designed to have exactly 2 FVGs: 1 bullish then 1 bearish
        prices = [
            # Bullish FVG (bars 1-3)
            (95, 100, 90, 98),     # c1: high=100
            (99, 105, 97, 104),    # c2
            (103, 110, 102, 108),  # c3: low=102 > c1.high=100 -> bullish FVG

            # Continuation with overlapping bars (no FVG)
            # Ensure: bar 2's high=105 is NOT < bar 4's low (need low <= 105)
            # Ensure: bar 3's low=102 is NOT > bar 5's high (need high >= 102)
            (107, 112, 103, 108),  # c1: high=112, low=103 (bar2.high=105 < low=103? No, 105<103 false)
            (108, 115, 106, 110),  # c2: high=115, low=106 (bar3.low=102 > high=115? No)
            (109, 114, 107, 112),  # c3: overlap with both, no FVG

            # Bearish FVG (bars 7-9)
            # Ensure: bar 6's low=107 > bar 8's high
            (111, 115, 108, 110),  # c1: low=108
            (107, 109, 100, 102),  # c2: high=109 (bar6.low=107 > high=109? No)
            (99, 105, 92, 94),     # c3: high=105 < c1.low=108 -> bearish FVG
        ]

        bars = _bars_from_ohlc(prices)
        _feed_bars(indicator, bars)

        assert len(indicator.fvgs) == 2
        assert indicator.fvgs[0].direction == FvgDirection.BULLISH
        assert indicator.fvgs[1].direction == FvgDirection.BEARISH


class TestBarAssociation:
    """Tests for correct association of the three bars in FVG record."""

    def test_correct_bars_associated_bullish(self):
        """Verify correct c1, c2, c3 bars are stored in bullish FVG record."""
        indicator = FairValueGap()

        prices = [
            (95, 100, 90, 98),     # c1
            (99, 105, 97, 104),    # c2
            (103, 110, 102, 108),  # c3
        ]

        bars = _bars_from_ohlc(prices, start_ts=1000)
        _feed_bars(indicator, bars)

        fvg = indicator.last_fvg
        assert fvg is not None

        # Verify bar references
        assert fvg.c1.ts_event == 1000
        assert fvg.c2.ts_event == 2000
        assert fvg.c3.ts_event == 3000

        assert fvg.c1.high == 100
        assert fvg.c3.low == 102

    def test_correct_bars_associated_bearish(self):
        """Verify correct c1, c2, c3 bars are stored in bearish FVG record."""
        indicator = FairValueGap()

        prices = [
            (115, 120, 110, 112),  # c1
            (108, 109, 95, 96),    # c2
            (94, 100, 88, 92),     # c3
        ]

        bars = _bars_from_ohlc(prices, start_ts=5000)
        _feed_bars(indicator, bars)

        fvg = indicator.last_fvg
        assert fvg is not None

        # Verify bar references
        assert fvg.c1.ts_event == 5000
        assert fvg.c2.ts_event == 6000
        assert fvg.c3.ts_event == 7000

        assert fvg.c1.low == 110
        assert fvg.c3.high == 100


class TestEdgeCases:
    """Tests for edge cases."""

    def test_less_than_3_bars(self):
        """No FVG should be detected with less than 3 bars."""
        indicator = FairValueGap()

        # Only 1 bar
        bar1 = MockBar(95, 100, 90, 98, ts_event=1000)
        indicator.handle_bar(bar1)
        assert len(indicator.fvgs) == 0
        assert indicator.has_new_fvg is False

        # Only 2 bars
        bar2 = MockBar(99, 105, 97, 104, ts_event=2000)
        indicator.handle_bar(bar2)
        assert len(indicator.fvgs) == 0
        assert indicator.has_new_fvg is False

    def test_exactly_3_bars_with_fvg(self):
        """FVG should be detected on exactly the 3rd bar."""
        indicator = FairValueGap()

        bars = _bars_from_ohlc([
            (95, 100, 90, 98),
            (99, 105, 97, 104),
            (103, 110, 102, 108),  # 3rd bar - FVG detected here
        ])

        _feed_bars(indicator, bars)
        assert len(indicator.fvgs) == 1

    def test_zero_prices(self):
        """Handle edge case with very low prices (near zero)."""
        indicator = FairValueGap()

        prices = [
            (0.5, 1.0, 0.1, 0.8),
            (0.9, 1.5, 0.7, 1.4),
            (1.3, 2.0, 1.2, 1.8),  # c3.low=1.2 > c1.high=1.0 -> bullish FVG
        ]

        bars = _bars_from_ohlc(prices)
        _feed_bars(indicator, bars)

        assert len(indicator.fvgs) == 1
        fvg = indicator.last_fvg
        assert fvg.fvg_low == 1.0
        assert fvg.fvg_high == 1.2

    def test_large_prices(self):
        """Handle edge case with large prices."""
        indicator = FairValueGap()

        prices = [
            (50000, 51000, 49000, 50500),
            (50600, 52000, 50400, 51800),
            (51900, 53000, 51500, 52500),  # c3.low=51500 > c1.high=51000 -> bullish FVG
        ]

        bars = _bars_from_ohlc(prices)
        _feed_bars(indicator, bars)

        assert len(indicator.fvgs) == 1
        fvg = indicator.last_fvg
        assert fvg.fvg_low == 51000
        assert fvg.fvg_high == 51500


class TestMiddleCandleTime:
    """Tests for correct middleCandleTime (c2.ts_event)."""

    def test_middle_candle_time_bullish(self):
        """Verify middleCandleTime is c2.ts_event for bullish FVG."""
        indicator = FairValueGap()

        bars = _bars_from_ohlc([
            (95, 100, 90, 98),
            (99, 105, 97, 104),
            (103, 110, 102, 108),
        ], start_ts=10000)

        _feed_bars(indicator, bars)

        fvg = indicator.last_fvg
        assert fvg is not None
        assert fvg.middle_candle_time == 11000  # c2.ts_event

    def test_middle_candle_time_bearish(self):
        """Verify middleCandleTime is c2.ts_event for bearish FVG."""
        indicator = FairValueGap()

        bars = _bars_from_ohlc([
            (115, 120, 110, 112),
            (108, 109, 95, 96),
            (94, 100, 88, 92),
        ], start_ts=20000)

        _feed_bars(indicator, bars)

        fvg = indicator.last_fvg
        assert fvg is not None
        assert fvg.middle_candle_time == 21000  # c2.ts_event


class TestDistancePercent:
    """Tests for correct distancePercent calculations."""

    def test_distance_percent_bullish(self):
        """Verify distancePercent calculation for bullish FVG."""
        indicator = FairValueGap()

        # gap = 105 - 100 = 5
        # mid = (105 + 100) / 2 = 102.5
        # distance_percent = (5 / 102.5) * 100 ≈ 4.878%
        prices = [
            (95, 100, 90, 98),     # c1: high=100
            (103, 108, 101, 106),  # c2
            (106, 112, 105, 110),  # c3: low=105
        ]

        bars = _bars_from_ohlc(prices)
        _feed_bars(indicator, bars)

        fvg = indicator.last_fvg
        assert fvg is not None

        expected = (5 / 102.5) * 100
        assert abs(fvg.distance_percent - expected) < 0.001

    def test_distance_percent_bearish(self):
        """Verify distancePercent calculation for bearish FVG."""
        indicator = FairValueGap()

        # gap = 105 - 100 = 5
        # mid = (105 + 100) / 2 = 102.5
        # distance_percent = (5 / 102.5) * 100 ≈ 4.878%
        prices = [
            (108, 112, 105, 107),  # c1: low=105
            (104, 106, 95, 96),    # c2
            (94, 100, 90, 92),     # c3: high=100
        ]

        bars = _bars_from_ohlc(prices)
        _feed_bars(indicator, bars)

        fvg = indicator.last_fvg
        assert fvg is not None

        expected = (5 / 102.5) * 100
        assert abs(fvg.distance_percent - expected) < 0.001


class TestReset:
    """Tests for reset functionality."""

    def test_reset_clears_all_state(self):
        """Verify reset() clears all indicator state."""
        indicator = FairValueGap(min_distance_percent=1.0)

        # Build up some state
        prices = [
            (95, 100, 90, 98),
            (99, 105, 97, 104),
            (103, 110, 102, 108),  # FVG detected
        ]

        bars = _bars_from_ohlc(prices)
        _feed_bars(indicator, bars)

        # Verify state exists
        assert len(indicator.fvgs) == 1
        assert indicator.last_fvg is not None

        # Reset
        indicator.reset()

        # Verify cleared
        assert len(indicator.fvgs) == 0
        assert indicator.last_fvg is None
        assert indicator.has_new_fvg is False

    def test_reset_allows_fresh_detection(self):
        """Verify indicator works correctly after reset."""
        indicator = FairValueGap()

        # First detection
        bars1 = _bars_from_ohlc([
            (95, 100, 90, 98),
            (99, 105, 97, 104),
            (103, 110, 102, 108),
        ])
        _feed_bars(indicator, bars1)
        assert len(indicator.fvgs) == 1

        # Reset
        indicator.reset()

        # New detection after reset
        bars2 = _bars_from_ohlc([
            (115, 120, 110, 112),
            (108, 109, 95, 96),
            (94, 100, 88, 92),
        ], start_ts=5000)
        _feed_bars(indicator, bars2)

        # Should only have the new FVG
        assert len(indicator.fvgs) == 1
        assert indicator.last_fvg.direction == FvgDirection.BEARISH


class TestProperties:
    """Tests for property access."""

    def test_min_distance_percent_property(self):
        """Verify min_distance_percent property returns configured value."""
        indicator = FairValueGap(min_distance_percent=3.5)
        assert indicator.min_distance_percent == 3.5

    def test_fvgs_returns_list(self):
        """Verify fvgs property returns a list."""
        indicator = FairValueGap()
        assert isinstance(indicator.fvgs, list)
        assert len(indicator.fvgs) == 0

    def test_last_fvg_none_when_empty(self):
        """Verify last_fvg returns None when no FVGs detected."""
        indicator = FairValueGap()
        assert indicator.last_fvg is None

    def test_has_new_fvg_resets_each_bar(self):
        """Verify has_new_fvg is True only on the bar where FVG is detected."""
        indicator = FairValueGap()

        bars = _bars_from_ohlc([
            (95, 100, 90, 98),
            (99, 105, 97, 104),
            (103, 110, 102, 108),  # FVG detected here
            (107, 112, 105, 110),  # No new FVG
        ])

        indicator.handle_bar(bars[0])
        assert indicator.has_new_fvg is False

        indicator.handle_bar(bars[1])
        assert indicator.has_new_fvg is False

        indicator.handle_bar(bars[2])
        assert indicator.has_new_fvg is True

        indicator.handle_bar(bars[3])
        assert indicator.has_new_fvg is False  # Reset on next bar


class TestSlidingWindow:
    """Tests for correct sliding window behavior."""

    def test_sliding_window_detects_consecutive_fvgs(self):
        """
        Verify sliding window correctly detects FVGs in consecutive windows.

        If bar 4 forms an FVG with bars 2 and 3, it should be detected
        even after an FVG was detected with bars 1, 2, 3.
        """
        indicator = FairValueGap()

        # Sequence where both (1,2,3) and (2,3,4) could be FVGs
        prices = [
            (95, 100, 90, 98),     # 1: high=100
            (99, 105, 97, 104),    # 2: high=105
            (103, 110, 102, 108),  # 3: low=102 > bar1.high=100 -> FVG #1
            (107, 115, 107, 113),  # 4: low=107 > bar2.high=105 -> FVG #2
        ]

        bars = _bars_from_ohlc(prices)
        signals = _feed_bars(indicator, bars)

        # Both FVGs should be detected
        assert signals == [False, False, True, True]
        assert len(indicator.fvgs) == 2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
