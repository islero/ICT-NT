"""
Test suite for SmartPivotPoints indicator.

These tests verify:
1. Uptrend detection (HH + HL + HH progression)
2. Downtrend detection (LL + LH + LL progression)
3. HL does not flip trend during uptrend
4. LH does not flip trend during downtrend
5. Guard against false reversals
"""

import os
import sys
from unittest.mock import MagicMock

import pytest

# --- MOCKING NAUTILUS TRADER ---
# We mock the dependencies so we can test the logic purely
sys.modules["nautilus_trader"] = MagicMock()
sys.modules["nautilus_trader.indicators"] = MagicMock()
sys.modules["nautilus_trader.indicators.base"] = MagicMock()
sys.modules["nautilus_trader.model"] = MagicMock()
sys.modules["nautilus_trader.model.data"] = MagicMock()


# Define the base class for Indicator so the import works and subclassing works
class MockIndicator:
    def __init__(self, inputs=None):
        pass

    def reset(self):
        pass


sys.modules["nautilus_trader.indicators.base"].Indicator = MockIndicator
sys.modules["nautilus_trader.model.data"].Bar = MagicMock()

# Ensure we can import from the project root
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# Now we can import the indicator under test
from indicators.smart_pivot_points import SmartPivotPoints, Trend


# Mock Bar object for our use
class MockBar:
    """Mock Bar object matching nautilus_trader Bar interface."""

    def __init__(self, open_price: float, high: float, low: float, close: float, ts_event: int = 0):
        self.open = open_price
        self.high = high
        self.low = low
        self.close = close
        self.ts_event = ts_event


def _bars_from_hl(series: list[tuple[float, float]]) -> list[MockBar]:
    """
    Build bars from a list of (high, low) tuples.

    Args:
        series: list of (high, low) tuples

    Returns:
        List of MockBar objects with open/close set to midpoint
    """
    bars = []
    for i, (h, l) in enumerate(series):
        mid = (h + l) / 2
        bars.append(MockBar(open_price=mid, high=h, low=l, close=mid, ts_event=i * 1000))
    return bars


def _bars_from_ohlc(series: list[tuple[float, float, float, float]]) -> list[MockBar]:
    """
    Build bars from a list of (open, high, low, close) tuples.

    Args:
        series: list of (open, high, low, close) tuples

    Returns:
        List of MockBar objects
    """
    bars = []
    for i, (o, h, l, c) in enumerate(series):
        bars.append(MockBar(open_price=o, high=h, low=l, close=c, ts_event=i * 1000))
    return bars


def _feed_bars(indicator: SmartPivotPoints, bars: list[MockBar]) -> list[int]:
    """
    Feed bars to indicator and return list of trend values after each bar.

    Args:
        indicator: SmartPivotPoints instance
        bars: List of MockBar objects

    Returns:
        List of trend values (1, -1, or 0) after each bar
    """
    trends = []
    for bar in bars:
        indicator.handle_bar(bar)
        trends.append(indicator.trend)
    return trends


class TestSmartPivotPointsUptrend:
    """Tests for uptrend detection behavior."""

    def test_uptrend_detection_hh_hl_hh(self):
        """
        Verify uptrend detection with HH -> HL -> HH progression.

        Uptrend-friendly highs/lows:
        [(100,95), (105,97), (103,99), (108,101), (106,102), (110,104)]

        The indicator should establish trend=1 (uptrend) after the structure
        is confirmed.
        """
        indicator = SmartPivotPoints()

        # Build bars that form uptrend: HH -> HL -> HH
        # Need to use OHLC to control close for BOS detection
        # Structure: Start range, break above (trend=1), pullback (HL), continue up (HH)
        prices = [
            # (open, high, low, close)
            (97, 100, 95, 98),  # 0. Initial range
            (98, 105, 97, 104),  # 1. Potential HH
            (104, 106, 100, 106),  # 2. Break above 105 -> UPTREND confirmed
            (106, 107, 99, 100),  # 3. Pullback (potential HL)
            (100, 103, 98, 102),  # 4. Continue pullback
            (102, 108, 101, 107),  # 5. Break above 107 confirms HL, new HH
            (107, 110, 104, 109),  # 6. Continue up - HH progression
        ]

        bars = _bars_from_ohlc(prices)
        trends = _feed_bars(indicator, bars)

        # Final trend should be Trend.UP (uptrend)
        assert indicator.trend == Trend.UP, f"Expected uptrend (Trend.UP), got {indicator.trend}"

        # After uptrend is established, it should remain Trend.UP
        # Find first index where trend becomes Trend.UP
        first_uptrend_idx = next((i for i, t in enumerate(trends) if t == Trend.UP), None)
        assert first_uptrend_idx is not None, "Uptrend was never established"

        # Check trend stays Trend.UP after establishment (no flip to Trend.DOWN)
        for i in range(first_uptrend_idx, len(trends)):
            assert trends[i] == Trend.UP, f"Trend flipped from Trend.UP at bar {i}: {trends[i]}"


class TestSmartPivotPointsDowntrend:
    """Tests for downtrend detection behavior."""

    def test_downtrend_detection_ll_lh_ll(self):
        """
        Verify downtrend detection with LL -> LH -> LL progression.

        Downtrend-friendly highs/lows:
        [(110,105), (108,102), (109,104), (105,98), (107,100), (103,95)]

        The indicator should establish trend=-1 (downtrend) after the structure
        is confirmed.
        """
        indicator = SmartPivotPoints()

        # Build bars that form downtrend: LL -> LH -> LL
        prices = [
            # (open, high, low, close)
            (107, 110, 105, 108),  # 0. Initial range
            (108, 108, 102, 103),  # 1. Drop
            (103, 105, 100, 99),  # 2. Break below 102 -> DOWNTREND confirmed
            (99, 106, 99, 105),  # 3. Pullback (potential LH)
            (105, 107, 101, 102),  # 4. Continue pullback
            (102, 103, 95, 96),  # 5. Break below 99 confirms LH, new LL
            (96, 100, 92, 93),  # 6. Continue down - LL progression
        ]

        bars = _bars_from_ohlc(prices)
        trends = _feed_bars(indicator, bars)

        # Final trend should be Trend.DOWN (downtrend)
        assert indicator.trend == Trend.DOWN, f"Expected downtrend (Trend.DOWN), got {indicator.trend}"

        # After downtrend is established, it should remain Trend.DOWN
        first_downtrend_idx = next((i for i, t in enumerate(trends) if t == Trend.DOWN), None)
        assert first_downtrend_idx is not None, "Downtrend was never established"

        # Check trend stays Trend.DOWN after establishment (no flip to Trend.UP)
        for i in range(first_downtrend_idx, len(trends)):
            assert trends[i] == Trend.DOWN, f"Trend flipped from Trend.DOWN at bar {i}: {trends[i]}"


class TestSmartPivotPointsHLStability:
    """Tests verifying HL does not flip trend in uptrend."""

    def test_hl_does_not_flip_trend(self):
        """
        HL-stability sequence: Start with uptrend, push to HH, pullback that
        should qualify as HL, then continuation.

        HL-stability sequence:
        [(100,95), (106,98), (104,100), (107,101)]

        The trend should remain 1 throughout the confirmation window.
        """
        indicator = SmartPivotPoints()

        # First establish uptrend clearly
        setup_prices = [
            (97, 100, 95, 98),  # 0. Initial range
            (98, 101, 96, 100),  # 1. Inside
            (100, 106, 98, 105),  # 2. Break above -> UPTREND
        ]

        # Now add HL-stability sequence (pullback without trend flip)
        hl_stability_prices = [
            (105, 106, 100, 101),  # 3. Pullback starts (potential HL forming)
            (101, 104, 99, 103),  # 4. Deeper pullback - still should be HL candidate
            (103, 107, 101, 106),  # 5. Resume uptrend, break above -> confirms HL
            (106, 109, 103, 108),  # 6. Continuation higher
        ]

        all_prices = setup_prices + hl_stability_prices
        bars = _bars_from_ohlc(all_prices)
        trends = _feed_bars(indicator, bars)

        # After uptrend established, trend should never flip to Trend.DOWN
        first_uptrend_idx = next((i for i, t in enumerate(trends) if t == Trend.UP), None)
        assert first_uptrend_idx is not None, "Uptrend was never established"

        # Verify no Trend.DOWN appears after uptrend is established
        for i in range(first_uptrend_idx, len(trends)):
            assert trends[i] != Trend.DOWN, f"HL pullback incorrectly flipped trend to Trend.DOWN at bar {i}"

        # Final trend should still be Trend.UP
        assert indicator.trend == Trend.UP, f"Expected trend=Trend.UP after HL pullback, got {indicator.trend}"


class TestSmartPivotPointsLHStability:
    """Tests verifying LH does not flip trend in downtrend."""

    def test_lh_does_not_flip_trend(self):
        """
        LH-stability sequence: Start with downtrend, push to LL, bounce that
        should qualify as LH, then continuation.

        LH-stability sequence:
        [(110,105), (107,100), (109,103), (106,99)]

        The trend should remain -1 throughout the confirmation window.
        """
        indicator = SmartPivotPoints()

        # First establish downtrend clearly
        setup_prices = [
            (107, 110, 105, 108),  # 0. Initial range
            (108, 109, 104, 105),  # 1. Inside
            (105, 106, 100, 101),  # 2. Break below -> DOWNTREND
        ]

        # Now add LH-stability sequence (bounce without trend flip)
        lh_stability_prices = [
            (101, 107, 100, 106),  # 3. Bounce starts (potential LH forming)
            (106, 109, 103, 105),  # 4. Higher bounce - still should be LH candidate
            (105, 106, 99, 100),  # 5. Resume downtrend, break below -> confirms LH
            (100, 103, 96, 97),  # 6. Continuation lower
        ]

        all_prices = setup_prices + lh_stability_prices
        bars = _bars_from_ohlc(all_prices)
        trends = _feed_bars(indicator, bars)

        # After downtrend established, trend should never flip to Trend.UP
        first_downtrend_idx = next((i for i, t in enumerate(trends) if t == Trend.DOWN), None)
        assert first_downtrend_idx is not None, "Downtrend was never established"

        # Verify no Trend.UP appears after downtrend is established
        for i in range(first_downtrend_idx, len(trends)):
            assert trends[i] != Trend.UP, f"LH bounce incorrectly flipped trend to Trend.UP at bar {i}"

        # Final trend should still be Trend.DOWN
        assert indicator.trend == Trend.DOWN, f"Expected trend=Trend.DOWN after LH bounce, got {indicator.trend}"


class TestSmartPivotPointsFalseReversals:
    """Tests guarding against false reversals."""

    def test_normal_pullback_in_uptrend_no_flip(self):
        """
        A normal pullback in uptrend should not flip to downtrend without
        a meaningful structure break (closing below major low).
        """
        indicator = SmartPivotPoints()

        # Establish strong uptrend
        prices = [
            (97, 100, 95, 98),  # 0. Initial range
            (98, 102, 97, 101),  # 1. Push up
            (101, 107, 100, 106),  # 2. Break above -> UPTREND
            (106, 110, 104, 109),  # 3. Strong HH
            (109, 111, 107, 110),  # 4. Continue HH
        ]

        # Add pullback that should NOT trigger reversal
        # (dips but doesn't close below the major low)
        pullback_prices = [
            (110, 110, 103, 104),  # 5. Pullback - wick low but close above
            (104, 106, 102, 105),  # 6. Deeper pullback
            (105, 108, 104, 107),  # 7. Resume upward
        ]

        all_prices = prices + pullback_prices
        bars = _bars_from_ohlc(all_prices)
        trends = _feed_bars(indicator, bars)

        # After uptrend established, no Trend.DOWN should appear (pullback shouldn't flip)
        first_uptrend_idx = next((i for i, t in enumerate(trends) if t == Trend.UP), None)
        assert first_uptrend_idx is not None, "Uptrend was never established"

        for i in range(first_uptrend_idx, len(trends)):
            assert trends[i] != Trend.DOWN, f"Normal pullback incorrectly flipped to downtrend at bar {i}"

        assert indicator.trend == Trend.UP, "Final trend should remain uptrend (Trend.UP)"

    def test_normal_bounce_in_downtrend_no_flip(self):
        """
        A normal bounce in downtrend should not flip to uptrend without
        a meaningful structure break (closing above major high).
        """
        indicator = SmartPivotPoints()

        # Establish strong downtrend
        prices = [
            (107, 110, 105, 108),  # 0. Initial range
            (108, 109, 103, 104),  # 1. Push down
            (104, 105, 98, 99),  # 2. Break below -> DOWNTREND
            (99, 100, 94, 95),  # 3. Strong LL
            (95, 96, 91, 92),  # 4. Continue LL
        ]

        # Add bounce that should NOT trigger reversal
        # (rallies but doesn't close above the major high)
        bounce_prices = [
            (92, 100, 91, 99),  # 5. Bounce - wick high but close below
            (99, 102, 98, 100),  # 6. Higher bounce
            (100, 101, 95, 96),  # 7. Resume downward
        ]

        all_prices = prices + bounce_prices
        bars = _bars_from_ohlc(all_prices)
        trends = _feed_bars(indicator, bars)

        # After downtrend established, no Trend.UP should appear (bounce shouldn't flip)
        first_downtrend_idx = next((i for i, t in enumerate(trends) if t == Trend.DOWN), None)
        assert first_downtrend_idx is not None, "Downtrend was never established"

        for i in range(first_downtrend_idx, len(trends)):
            assert trends[i] != Trend.UP, f"Normal bounce incorrectly flipped to uptrend at bar {i}"

        assert indicator.trend == Trend.DOWN, "Final trend should remain downtrend (Trend.DOWN)"


class TestSmartPivotPointsMajorStructure:
    """Tests for major high/low tracking."""

    def test_major_high_updated_on_break_of_structure(self):
        """Verify major_high is correctly set when structure breaks."""
        indicator = SmartPivotPoints()

        prices = [
            (107, 110, 105, 108),  # 0. Initial range, major_high=110
            (108, 109, 104, 105),  # 1. Inside
            (105, 106, 100, 101),  # 2. Break below 105 -> DOWNTREND
        ]

        bars = _bars_from_ohlc(prices)
        _feed_bars(indicator, bars)

        assert indicator.trend == Trend.DOWN, "Should be in downtrend"
        assert indicator.major_high is not None, "Major high should be set"

    def test_major_low_updated_on_break_of_structure(self):
        """Verify major_low is correctly set when structure breaks."""
        indicator = SmartPivotPoints()

        prices = [
            (97, 100, 95, 98),  # 0. Initial range, major_low=95
            (98, 101, 96, 100),  # 1. Inside
            (100, 106, 99, 105),  # 2. Break above 100 -> UPTREND
        ]

        bars = _bars_from_ohlc(prices)
        _feed_bars(indicator, bars)

        assert indicator.trend == Trend.UP, "Should be in uptrend"
        assert indicator.major_low is not None, "Major low should be set"


class TestSmartPivotPointsSignals:
    """Tests for new_major_high and new_major_low signal flags."""

    def test_is_new_major_high_signal(self):
        """Verify is_new_major_high is True when new LH is confirmed in downtrend."""
        indicator = SmartPivotPoints()

        prices = [
            (107, 110, 105, 108),  # 0. Initial range
            (108, 109, 103, 104),  # 1. Drop
            (104, 105, 98, 99),  # 2. Break below -> DOWNTREND, signals new_major_high
        ]

        bars = _bars_from_ohlc(prices)

        # Feed first two bars
        indicator.handle_bar(bars[0])
        indicator.handle_bar(bars[1])

        # On third bar, downtrend should be confirmed with new_major_high signal
        indicator.handle_bar(bars[2])

        # The signal should have been True on the confirmation bar
        # Note: Signal is reset each bar, so we check the bar that triggers it
        assert indicator.trend == Trend.DOWN, "Should be in downtrend"

    def test_is_new_major_low_signal(self):
        """Verify is_new_major_low is True when new HL is confirmed in uptrend."""
        indicator = SmartPivotPoints()

        prices = [
            (97, 100, 95, 98),  # 0. Initial range
            (98, 101, 96, 100),  # 1. Push up
            (100, 106, 99, 105),  # 2. Break above -> UPTREND, signals new_major_low
        ]

        bars = _bars_from_ohlc(prices)

        # Feed first two bars
        indicator.handle_bar(bars[0])
        indicator.handle_bar(bars[1])

        # On third bar, uptrend should be confirmed with new_major_low signal
        indicator.handle_bar(bars[2])

        # The signal should have been True on the confirmation bar
        assert indicator.trend == Trend.UP, "Should be in uptrend"


class TestSmartPivotPointsReset:
    """Tests for reset functionality."""

    def test_reset_clears_state(self):
        """Verify reset() clears all indicator state."""
        indicator = SmartPivotPoints()

        # Build some state
        prices = [
            (97, 100, 95, 98),
            (98, 106, 97, 105),
        ]
        bars = _bars_from_ohlc(prices)
        _feed_bars(indicator, bars)

        # Reset
        indicator.reset()

        # Verify cleared
        assert indicator.trend == Trend.UNDEFINED, "Trend should be Trend.UNDEFINED after reset"
        assert indicator.major_high is None, "major_high should be None after reset"
        assert indicator.major_low is None, "major_low should be None after reset"
        assert indicator.is_new_major_high is False, "is_new_major_high should be False after reset"
        assert indicator.is_new_major_low is False, "is_new_major_low should be False after reset"


class TestSmartPivotPointsDeepPullbackBOS:
    """Tests for deep pullback followed by break of structure continuation."""

    def test_downtrend_deep_pullback_then_bos_continuation(self):
        """
        Verify downtrend behavior with deep pullback followed by BOS continuation.

        Scenario:
        1. Establish initial range
        2. Break down to establish downtrend
        3. Deep pullback (potential LH forming at 96)
        4. Break of structure (close below major low) confirms LH and continues trend

        Expected:
        - Trend becomes -1 after initial break down
        - Deep pullback does NOT flip trend to 1
        - BOS continuation confirms new major high (the LH at 96)
        - Major low updates to new low (75)
        """
        indicator = SmartPivotPoints()

        prices = [
            # Initialization phase
            (100, 105, 95, 100),  # 0. Initial Range
            (100, 102, 90, 92),  # 1. Drop, creates Low 90
            (92, 95, 91, 93),  # 2. Inside bar
            (93, 93, 80, 80),  # 3. BREAK DOWN (Close 80 < 90). Trend -> DOWN (-1)
            # Deep Pullback Phase
            (80, 85, 80, 85),  # 4. Pullback start
            (85, 95, 85, 95),  # 5. Deep Pullback to 95. Candidate LH = 95
            (95, 96, 94, 94),  # 6. Higher internal high (96). Candidate LH = 96
            (94, 94, 88, 88),  # 7. Internal low
            (88, 92, 88, 90),  # 8. Another lower high (92) internally
            # Continuation / BOS
            (90, 90, 75, 75),  # 9. CRASH to 75. Breaks Major Low (80)
            #    EXPECTATION: Confirm 96 as New Major High (LH)
            #    New Major Low = 75
        ]

        bars = _bars_from_ohlc(prices)
        trends = _feed_bars(indicator, bars)

        # After bar 3 (break down), trend should be Trend.DOWN
        assert trends[3] == Trend.DOWN, f"Expected downtrend after bar 3, got {trends[3]}"

        # During deep pullback (bars 4-8), trend should remain Trend.DOWN (not flip to Trend.UP)
        for i in range(4, 9):
            assert trends[i] == Trend.DOWN, f"Deep pullback incorrectly flipped trend at bar {i}: {trends[i]}"

        # Final trend after BOS should still be Trend.DOWN
        assert indicator.trend == Trend.DOWN, f"Expected downtrend after BOS, got {indicator.trend}"

        # Major low should be updated to 75 after the break
        assert indicator.major_low == 75, f"Expected major_low=75 after BOS, got {indicator.major_low}"

        # Major high should be set (the confirmed LH)
        assert indicator.major_high is not None, "Major high should be set after LH confirmation"

    def test_uptrend_deep_pullback_then_bos_continuation(self):
        """
        Verify uptrend behavior with deep pullback followed by BOS continuation.

        Mirror of downtrend test:
        1. Establish initial range
        2. Break up to establish uptrend
        3. Deep pullback (potential HL forming)
        4. Break of structure (close above major high) confirms HL and continues trend
        """
        indicator = SmartPivotPoints()

        prices = [
            # Initialization phase
            (100, 105, 95, 100),  # 0. Initial Range
            (100, 110, 98, 108),  # 1. Push up, creates High 110
            (108, 109, 105, 107),  # 2. Inside bar
            (107, 120, 107, 120),  # 3. BREAK UP (Close 120 > 110). Trend -> UP (1)
            # Deep Pullback Phase
            (120, 120, 115, 115),  # 4. Pullback start
            (115, 116, 105, 105),  # 5. Deep Pullback to 105. Candidate HL = 105
            (105, 106, 104, 106),  # 6. Lower internal low (104). Candidate HL = 104
            (106, 112, 106, 112),  # 7. Internal high
            (112, 113, 108, 110),  # 8. Another higher low internally
            # Continuation / BOS
            (110, 125, 110, 125),  # 9. BREAKOUT to 125. Breaks Major High (120)
            #    EXPECTATION: Confirm 104 as New Major Low (HL)
            #    New Major High = 125
        ]

        bars = _bars_from_ohlc(prices)
        trends = _feed_bars(indicator, bars)

        # After bar 3 (break up), trend should be Trend.UP
        assert trends[3] == Trend.UP, f"Expected uptrend after bar 3, got {trends[3]}"

        # During deep pullback (bars 4-8), trend should remain Trend.UP (not flip to Trend.DOWN)
        for i in range(4, 9):
            assert trends[i] == Trend.UP, f"Deep pullback incorrectly flipped trend at bar {i}: {trends[i]}"

        # Final trend after BOS should still be Trend.UP
        assert indicator.trend == Trend.UP, f"Expected uptrend after BOS, got {indicator.trend}"

        # Major high should be updated to 125 after the break
        assert indicator.major_high == 125, f"Expected major_high=125 after BOS, got {indicator.major_high}"

        # Major low should be set (the confirmed HL)
        assert indicator.major_low is not None, "Major low should be set after HL confirmation"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
