"""
Tests for FibonacciLevels indicator.

These tests verify:
- Fibonacci level calculations are correct
- Premium/Discount zones are oriented correctly for BUY and SELL
- Zone classification works properly
- OTE (Optimal Trade Entry) zone detection
- Edge cases and invalid inputs
"""

import sys
import os
from unittest.mock import MagicMock

import pytest

# Ensure we can import from the project root
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# --- MOCKING NAUTILUS TRADER ---
sys.modules["pandas"] = MagicMock()
sys.modules["nautilus_trader"] = MagicMock()
sys.modules["nautilus_trader.core"] = MagicMock()
sys.modules["nautilus_trader.indicators"] = MagicMock()
sys.modules["nautilus_trader.indicators.base"] = MagicMock()
sys.modules["nautilus_trader.model"] = MagicMock()
sys.modules["nautilus_trader.model.data"] = MagicMock()


class MockIndicator:
    def __init__(self, inputs=None):
        pass

    def reset(self):
        pass


sys.modules["nautilus_trader.indicators.base"].Indicator = MockIndicator

# Now import the indicator
from indicators.fibonacci_levels import (
    FibonacciLevels,
    TradeDirection,
    PriceZone,
    FibonacciLevel,
)


class TestFibonacciLevelsBasicCalculations:
    """Tests for basic Fibonacci level calculations."""

    def test_initialization_state(self):
        """Test that indicator initializes with correct default state."""
        fib = FibonacciLevels()

        assert fib.is_valid is False
        assert fib.direction == TradeDirection.NONE
        assert fib.swing_high is None
        assert fib.swing_low is None
        assert fib.equilibrium is None
        assert fib.recommended_entry is None

    def test_buy_direction_fibonacci_levels(self):
        """Test Fibonacci levels are calculated correctly for BUY direction."""
        fib = FibonacciLevels()

        swing_low = 100.0
        swing_high = 200.0
        fib.update(swing_low, swing_high, TradeDirection.BUY)

        assert fib.is_valid is True
        assert fib.swing_low == 100.0
        assert fib.swing_high == 200.0
        assert fib.dealing_range == 100.0

        # For BUY: 0% = swing_high (200), 100% = swing_low (100)
        # Equilibrium at 50% = 150
        assert fib.equilibrium == 150.0

        # Check key Fibonacci levels
        levels = fib.levels
        assert levels["0"].price == 200.0  # 0% = swing_high
        assert levels["100"].price == 100.0  # 100% = swing_low
        assert levels["50"].price == 150.0  # 50% = equilibrium

        # 61.8% retracement from high
        expected_618 = 200.0 - (100.0 * 0.618)  # = 138.2
        assert abs(levels["61.8"].price - expected_618) < 0.01

        # 78.6% retracement from high
        expected_786 = 200.0 - (100.0 * 0.786)  # = 121.4
        assert abs(levels["78.6"].price - expected_786) < 0.01

    def test_sell_direction_fibonacci_levels(self):
        """Test Fibonacci levels are calculated correctly for SELL direction."""
        fib = FibonacciLevels()

        swing_low = 100.0
        swing_high = 200.0
        fib.update(swing_low, swing_high, TradeDirection.SELL)

        assert fib.is_valid is True

        # For SELL: 0% = swing_low (100), 100% = swing_high (200)
        # Equilibrium at 50% = 150
        assert fib.equilibrium == 150.0

        # Check key Fibonacci levels
        levels = fib.levels
        assert levels["0"].price == 100.0  # 0% = swing_low
        assert levels["100"].price == 200.0  # 100% = swing_high
        assert levels["50"].price == 150.0  # 50% = equilibrium

        # 61.8% retracement from low
        expected_618 = 100.0 + (100.0 * 0.618)  # = 161.8
        assert abs(levels["61.8"].price - expected_618) < 0.01

        # 78.6% retracement from low
        expected_786 = 100.0 + (100.0 * 0.786)  # = 178.6
        assert abs(levels["78.6"].price - expected_786) < 0.01


class TestFibonacciLevelsPremiumDiscount:
    """Tests for Premium/Discount zone calculations."""

    def test_buy_direction_premium_discount_zones(self):
        """Test premium/discount zones are correct for BUY direction."""
        fib = FibonacciLevels()

        swing_low = 100.0
        swing_high = 200.0
        fib.update(swing_low, swing_high, TradeDirection.BUY)

        # For BUY: Discount = below equilibrium (favorable for buying)
        # Premium = above equilibrium (unfavorable for buying)

        # Discount zone: 100 (swing_low) to 150 (equilibrium)
        assert fib.discount_zone_start == 100.0
        assert fib.discount_zone_end == 150.0

        # Premium zone: 150 (equilibrium) to 200 (swing_high)
        assert fib.premium_zone_start == 150.0
        assert fib.premium_zone_end == 200.0

    def test_sell_direction_premium_discount_zones(self):
        """Test premium/discount zones are correct for SELL direction."""
        fib = FibonacciLevels()

        swing_low = 100.0
        swing_high = 200.0
        fib.update(swing_low, swing_high, TradeDirection.SELL)

        # For SELL: Premium = above equilibrium (favorable for selling)
        # Discount = below equilibrium (unfavorable for selling)

        # Premium zone: 150 (equilibrium) to 200 (swing_high)
        assert fib.premium_zone_start == 150.0
        assert fib.premium_zone_end == 200.0

        # Discount zone: 100 (swing_low) to 150 (equilibrium)
        assert fib.discount_zone_start == 100.0
        assert fib.discount_zone_end == 150.0


class TestFibonacciLevelsZoneClassification:
    """Tests for price zone classification."""

    def test_buy_direction_zone_classification(self):
        """Test zone classification for BUY direction."""
        fib = FibonacciLevels()

        swing_low = 100.0
        swing_high = 200.0
        fib.update(swing_low, swing_high, TradeDirection.BUY)

        # For BUY: lower prices = discount (favorable)

        # Deep discount (below 78.6% = 121.4)
        assert fib.get_zone(110.0) == PriceZone.DEEP_DISCOUNT
        assert fib.get_zone(120.0) == PriceZone.DEEP_DISCOUNT

        # Discount (between 78.6% and 50%)
        assert fib.get_zone(130.0) == PriceZone.DISCOUNT
        assert fib.get_zone(140.0) == PriceZone.DISCOUNT

        # Premium (between 50% and 23.6% = 176.4)
        assert fib.get_zone(160.0) == PriceZone.PREMIUM
        assert fib.get_zone(170.0) == PriceZone.PREMIUM

        # Deep premium (above 23.6%)
        assert fib.get_zone(180.0) == PriceZone.DEEP_PREMIUM
        assert fib.get_zone(195.0) == PriceZone.DEEP_PREMIUM

    def test_sell_direction_zone_classification(self):
        """Test zone classification for SELL direction."""
        fib = FibonacciLevels()

        swing_low = 100.0
        swing_high = 200.0
        fib.update(swing_low, swing_high, TradeDirection.SELL)

        # For SELL: higher prices = premium (favorable)

        # Deep premium (above 78.6% = 178.6)
        assert fib.get_zone(180.0) == PriceZone.DEEP_PREMIUM
        assert fib.get_zone(195.0) == PriceZone.DEEP_PREMIUM

        # Premium (between 50% and 78.6%)
        assert fib.get_zone(160.0) == PriceZone.PREMIUM
        assert fib.get_zone(170.0) == PriceZone.PREMIUM

        # Discount (between 23.6% and 50%)
        assert fib.get_zone(130.0) == PriceZone.DISCOUNT
        assert fib.get_zone(140.0) == PriceZone.DISCOUNT

        # Deep discount (below 23.6% = 123.6)
        assert fib.get_zone(110.0) == PriceZone.DEEP_DISCOUNT
        assert fib.get_zone(120.0) == PriceZone.DEEP_DISCOUNT

    def test_is_in_discount_for_buy(self):
        """Test is_in_discount helper for BUY direction."""
        fib = FibonacciLevels()
        fib.update(100.0, 200.0, TradeDirection.BUY)

        # Prices below equilibrium should be in discount
        assert fib.is_in_discount(110.0) is True
        assert fib.is_in_discount(130.0) is True
        assert fib.is_in_discount(145.0) is True

        # Prices above equilibrium should NOT be in discount
        assert fib.is_in_discount(155.0) is False
        assert fib.is_in_discount(180.0) is False

    def test_is_in_premium_for_sell(self):
        """Test is_in_premium helper for SELL direction."""
        fib = FibonacciLevels()
        fib.update(100.0, 200.0, TradeDirection.SELL)

        # Prices above equilibrium should be in premium
        assert fib.is_in_premium(155.0) is True
        assert fib.is_in_premium(170.0) is True
        assert fib.is_in_premium(190.0) is True

        # Prices below equilibrium should NOT be in premium
        assert fib.is_in_premium(145.0) is False
        assert fib.is_in_premium(120.0) is False


class TestFibonacciLevelsOTE:
    """Tests for Optimal Trade Entry (OTE) zone."""

    def test_buy_direction_ote_zone(self):
        """Test OTE zone is correct for BUY direction (62%-79% retracement)."""
        fib = FibonacciLevels()

        swing_low = 100.0
        swing_high = 200.0
        fib.update(swing_low, swing_high, TradeDirection.BUY)

        # For BUY: OTE zone is in lower prices (discount)
        # 61.8% from 200 = 138.2
        # 78.6% from 200 = 121.4
        # OTE should be between these (lower = better for BUY)
        assert fib.optimal_entry_high is not None
        assert fib.optimal_entry_low is not None

        expected_618 = 200.0 - (100.0 * 0.618)  # 138.2
        expected_786 = 200.0 - (100.0 * 0.786)  # 121.4

        assert abs(fib.optimal_entry_high - expected_618) < 0.01
        assert abs(fib.optimal_entry_low - expected_786) < 0.01

        # Recommended entry at 70.5%
        expected_705 = 200.0 - (100.0 * 0.705)  # 129.5
        assert fib.recommended_entry is not None
        assert abs(fib.recommended_entry - expected_705) < 0.01

    def test_sell_direction_ote_zone(self):
        """Test OTE zone is correct for SELL direction (62%-79% retracement)."""
        fib = FibonacciLevels()

        swing_low = 100.0
        swing_high = 200.0
        fib.update(swing_low, swing_high, TradeDirection.SELL)

        # For SELL: OTE zone is in higher prices (premium)
        # 61.8% from 100 = 161.8
        # 78.6% from 100 = 178.6
        expected_618 = 100.0 + (100.0 * 0.618)  # 161.8
        expected_786 = 100.0 + (100.0 * 0.786)  # 178.6

        assert abs(fib.optimal_entry_low - expected_618) < 0.01
        assert abs(fib.optimal_entry_high - expected_786) < 0.01

        # Recommended entry at 70.5%
        expected_705 = 100.0 + (100.0 * 0.705)  # 170.5
        assert fib.recommended_entry is not None
        assert abs(fib.recommended_entry - expected_705) < 0.01

    def test_is_in_optimal_entry_zone(self):
        """Test is_in_optimal_entry_zone helper."""
        fib = FibonacciLevels()
        fib.update(100.0, 200.0, TradeDirection.BUY)

        # OTE zone for BUY is between 121.4 and 138.2
        assert fib.is_in_optimal_entry_zone(125.0) is True
        assert fib.is_in_optimal_entry_zone(130.0) is True
        assert fib.is_in_optimal_entry_zone(135.0) is True

        # Outside OTE zone
        assert fib.is_in_optimal_entry_zone(110.0) is False
        assert fib.is_in_optimal_entry_zone(150.0) is False
        assert fib.is_in_optimal_entry_zone(180.0) is False


class TestFibonacciLevelsEdgeCases:
    """Tests for edge cases and invalid inputs."""

    def test_invalid_swing_range_equal(self):
        """Test that equal swing_low and swing_high is invalid."""
        fib = FibonacciLevels()
        fib.update(100.0, 100.0, TradeDirection.BUY)

        assert fib.is_valid is False

    def test_invalid_swing_range_inverted(self):
        """Test that swing_low > swing_high is invalid."""
        fib = FibonacciLevels()
        fib.update(200.0, 100.0, TradeDirection.BUY)

        assert fib.is_valid is False

    def test_invalid_direction_none(self):
        """Test that TradeDirection.NONE is invalid."""
        fib = FibonacciLevels()
        fib.update(100.0, 200.0, TradeDirection.NONE)

        assert fib.is_valid is False

    def test_zone_classification_invalid_state(self):
        """Test zone classification returns UNKNOWN when invalid."""
        fib = FibonacciLevels()

        # Not updated yet
        assert fib.get_zone(150.0) == PriceZone.UNKNOWN

        # Invalid update
        fib.update(200.0, 100.0, TradeDirection.BUY)
        assert fib.get_zone(150.0) == PriceZone.UNKNOWN

    def test_helpers_return_false_when_invalid(self):
        """Test helper methods return False when indicator is invalid."""
        fib = FibonacciLevels()

        assert fib.is_in_discount(150.0) is False
        assert fib.is_in_premium(150.0) is False
        assert fib.is_in_optimal_entry_zone(150.0) is False

    def test_reset_clears_state(self):
        """Test reset clears all state."""
        fib = FibonacciLevels()
        fib.update(100.0, 200.0, TradeDirection.BUY)

        assert fib.is_valid is True

        fib.reset()

        assert fib.is_valid is False
        assert fib.direction == TradeDirection.NONE
        assert fib.swing_high is None
        assert fib.swing_low is None
        assert fib.equilibrium is None
        assert len(fib.levels) == 0

    def test_update_replaces_previous_state(self):
        """Test that update completely replaces previous calculation."""
        fib = FibonacciLevels()

        # First update
        fib.update(100.0, 200.0, TradeDirection.BUY)
        first_equilibrium = fib.equilibrium

        # Second update with different values
        fib.update(50.0, 150.0, TradeDirection.SELL)

        assert fib.equilibrium != first_equilibrium
        assert fib.direction == TradeDirection.SELL
        assert fib.swing_low == 50.0
        assert fib.swing_high == 150.0


class TestFibonacciLevelsPremiumMeaning:
    """Tests ensuring Premium always means 'favorable for trade direction'."""

    def test_premium_favorable_for_buy_is_in_lower_range(self):
        """
        For BUY context, the favorable zone (discount) is the LOWER half.
        Premium (unfavorable) is the UPPER half.
        """
        fib = FibonacciLevels()
        fib.update(100.0, 200.0, TradeDirection.BUY)

        # Favorable for BUY = lower prices = discount
        assert fib.is_in_discount(120.0) is True  # Good for buying
        assert fib.is_in_discount(180.0) is False  # Not good for buying

        # Unfavorable for BUY = higher prices = premium
        assert fib.is_in_premium(180.0) is True  # Bad for buying (overpriced)
        assert fib.is_in_premium(120.0) is False

    def test_premium_favorable_for_sell_is_in_upper_range(self):
        """
        For SELL context, the favorable zone (premium) is the UPPER half.
        Discount (unfavorable) is the LOWER half.
        """
        fib = FibonacciLevels()
        fib.update(100.0, 200.0, TradeDirection.SELL)

        # Favorable for SELL = higher prices = premium
        assert fib.is_in_premium(180.0) is True  # Good for selling
        assert fib.is_in_premium(120.0) is False  # Not good for selling

        # Unfavorable for SELL = lower prices = discount
        assert fib.is_in_discount(120.0) is True  # Bad for selling (underpriced)
        assert fib.is_in_discount(180.0) is False

    def test_equilibrium_is_always_50_percent(self):
        """Test that equilibrium is always at 50% regardless of direction."""
        fib = FibonacciLevels()

        # BUY direction
        fib.update(100.0, 200.0, TradeDirection.BUY)
        assert fib.equilibrium == 150.0

        # SELL direction (same range)
        fib.update(100.0, 200.0, TradeDirection.SELL)
        assert fib.equilibrium == 150.0

        # Different range
        fib.update(50.0, 250.0, TradeDirection.BUY)
        assert fib.equilibrium == 150.0  # (50 + 250) / 2

        fib.update(1000.0, 1100.0, TradeDirection.SELL)
        assert fib.equilibrium == 1050.0


class TestFibonacciLevelsGetLevelPrice:
    """Tests for get_level_price method."""

    def test_get_level_price_returns_correct_value(self):
        """Test get_level_price returns correct price for level."""
        fib = FibonacciLevels()
        fib.update(100.0, 200.0, TradeDirection.BUY)

        assert fib.get_level_price("0") == 200.0
        assert fib.get_level_price("50") == 150.0
        assert fib.get_level_price("100") == 100.0

    def test_get_level_price_invalid_key(self):
        """Test get_level_price returns None for invalid key."""
        fib = FibonacciLevels()
        fib.update(100.0, 200.0, TradeDirection.BUY)

        assert fib.get_level_price("999") is None
        assert fib.get_level_price("invalid") is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
