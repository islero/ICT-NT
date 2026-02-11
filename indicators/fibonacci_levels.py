"""
Fibonacci Levels Indicator for ICT Trading.

This indicator calculates Fibonacci retracement levels based on a swing range
and trade direction. It dynamically orients levels so that "Premium" always
represents the favorable zone for the given trade direction.

Key Concept:
- For BUY context: Discount (lower half) is favorable, Premium (upper half) is unfavorable
- For SELL context: Premium (upper half) is favorable, Discount (lower half) is unfavorable

The indicator ensures Premium/Discount meaning stays consistent with trade direction,
regardless of whether price is trending up or down.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from nautilus_trader.indicators.base import Indicator


class TradeDirection(Enum):
    """Trade direction for Fibonacci orientation."""

    NONE = 0
    BUY = 1
    SELL = -1


class PriceZone(Enum):
    """Price zone classification relative to Fibonacci levels."""

    UNKNOWN = "unknown"
    DEEP_DISCOUNT = "deep_discount"  # Below 79% retracement (most favorable for BUY)
    DISCOUNT = "discount"  # 50%-79% retracement (favorable for BUY)
    EQUILIBRIUM = "equilibrium"  # Around 50% level
    PREMIUM = "premium"  # 21%-50% retracement (favorable for SELL)
    DEEP_PREMIUM = "deep_premium"  # Above 21% retracement (most favorable for SELL)


@dataclass
class FibonacciLevel:
    """Represents a single Fibonacci level with price and percentage."""

    percentage: float  # 0.0 to 1.0
    price: float
    label: str


class FibonacciLevels(Indicator):
    """
    Fibonacci Levels Indicator.

    Calculates Fibonacci retracement levels from a swing range and trade direction.
    Automatically orients levels so that Premium/Discount zones align with
    the trade direction.

    Standard Fibonacci Levels:
    - 0% (swing start)
    - 23.6%
    - 38.2%
    - 50% (Equilibrium)
    - 61.8%
    - 70.5% (OTE - Optimal Trade Entry)
    - 78.6%
    - 100% (swing end)

    Attributes:
        direction: Current trade direction (BUY/SELL/NONE)
        swing_high: Upper boundary of the dealing range
        swing_low: Lower boundary of the dealing range
        equilibrium: 50% retracement level (middle of range)
        premium_zone: Price zone favorable for the current direction
        discount_zone: Price zone unfavorable for the current direction
        optimal_entry_low: Lower bound of OTE zone (62%-79%)
        optimal_entry_high: Upper bound of OTE zone (62%-79%)
        recommended_entry: Recommended entry price (70.5% retracement)
    """

    # Standard Fibonacci percentages
    FIB_0 = 0.0
    FIB_236 = 0.236
    FIB_382 = 0.382
    FIB_500 = 0.500
    FIB_618 = 0.618
    FIB_705 = 0.705  # OTE (Optimal Trade Entry)
    FIB_786 = 0.786
    FIB_100 = 1.0

    def __init__(self) -> None:
        super().__init__([])

        # Input state
        self._direction: TradeDirection = TradeDirection.NONE
        self._swing_high: Optional[float] = None
        self._swing_low: Optional[float] = None

        # Computed Fibonacci levels (prices)
        self._levels: dict[str, FibonacciLevel] = {}

        # Key zone boundaries
        self._equilibrium: Optional[float] = None
        self._premium_zone_start: Optional[float] = None
        self._premium_zone_end: Optional[float] = None
        self._discount_zone_start: Optional[float] = None
        self._discount_zone_end: Optional[float] = None

        # Optimal Trade Entry zone (62%-79% retracement)
        self._optimal_entry_low: Optional[float] = None
        self._optimal_entry_high: Optional[float] = None
        self._recommended_entry: Optional[float] = None

        # Flag for valid calculation
        self._is_valid: bool = False

    def update(self, swing_low: float, swing_high: float, direction: TradeDirection) -> None:
        """
        Update Fibonacci levels with new swing range and direction.

        The Fibonacci is drawn based on the trade direction:
        - BUY direction: Fibonacci drawn from swing_high (0%) to swing_low (100%)
          - Discount = 50%-100% of range (lower prices, favorable for buying)
          - Premium = 0%-50% of range (higher prices, unfavorable for buying)

        - SELL direction: Fibonacci drawn from swing_low (0%) to swing_high (100%)
          - Premium = 50%-100% of range (higher prices, favorable for selling)
          - Discount = 0%-50% of range (lower prices, unfavorable for selling)

        Args:
            swing_low: Lower price of the dealing range
            swing_high: Upper price of the dealing range
            direction: Trade direction (BUY/SELL)
        """
        # Convert to float to handle decimal.Decimal from nautilus_trader
        swing_low = float(swing_low)
        swing_high = float(swing_high)

        if swing_low >= swing_high:
            self._is_valid = False
            return

        if direction == TradeDirection.NONE:
            self._is_valid = False
            return

        self._swing_low = swing_low
        self._swing_high = swing_high
        self._direction = direction

        self._calculate_levels()
        self._is_valid = True

    def _calculate_levels(self) -> None:
        """Calculate all Fibonacci levels based on direction."""
        if self._swing_low is None or self._swing_high is None:
            return

        range_size = self._swing_high - self._swing_low

        # Calculate standard Fibonacci levels
        # For BUY: 0% = swing_high (start), 100% = swing_low (end)
        # For SELL: 0% = swing_low (start), 100% = swing_high (end)

        if self._direction == TradeDirection.BUY:
            # BUY context: We want to buy at discount (low prices)
            # Fibonacci drawn from high to low
            # 0% = swing_high, 100% = swing_low
            self._levels = {
                "0": FibonacciLevel(self.FIB_0, self._swing_high, "0% (High)"),
                "23.6": FibonacciLevel(self.FIB_236, self._swing_high - range_size * self.FIB_236, "23.6%"),
                "38.2": FibonacciLevel(self.FIB_382, self._swing_high - range_size * self.FIB_382, "38.2%"),
                "50": FibonacciLevel(self.FIB_500, self._swing_high - range_size * self.FIB_500, "50% (EQ)"),
                "61.8": FibonacciLevel(self.FIB_618, self._swing_high - range_size * self.FIB_618, "61.8%"),
                "70.5": FibonacciLevel(self.FIB_705, self._swing_high - range_size * self.FIB_705, "70.5% (OTE)"),
                "78.6": FibonacciLevel(self.FIB_786, self._swing_high - range_size * self.FIB_786, "78.6%"),
                "100": FibonacciLevel(self.FIB_100, self._swing_low, "100% (Low)"),
            }

            # Equilibrium is at 50%
            self._equilibrium = self._levels["50"].price

            # For BUY: Discount = below equilibrium (favorable)
            # Premium = above equilibrium (unfavorable)
            self._discount_zone_start = self._swing_low  # 100%
            self._discount_zone_end = self._equilibrium  # 50%
            self._premium_zone_start = self._equilibrium  # 50%
            self._premium_zone_end = self._swing_high  # 0%

            # OTE zone for BUY: 62%-79% retracement (low prices)
            self._optimal_entry_high = self._levels["61.8"].price
            self._optimal_entry_low = self._levels["78.6"].price
            self._recommended_entry = self._levels["70.5"].price

        elif self._direction == TradeDirection.SELL:
            # SELL context: We want to sell at premium (high prices)
            # Fibonacci drawn from low to high
            # 0% = swing_low, 100% = swing_high
            self._levels = {
                "0": FibonacciLevel(self.FIB_0, self._swing_low, "0% (Low)"),
                "23.6": FibonacciLevel(self.FIB_236, self._swing_low + range_size * self.FIB_236, "23.6%"),
                "38.2": FibonacciLevel(self.FIB_382, self._swing_low + range_size * self.FIB_382, "38.2%"),
                "50": FibonacciLevel(self.FIB_500, self._swing_low + range_size * self.FIB_500, "50% (EQ)"),
                "61.8": FibonacciLevel(self.FIB_618, self._swing_low + range_size * self.FIB_618, "61.8%"),
                "70.5": FibonacciLevel(self.FIB_705, self._swing_low + range_size * self.FIB_705, "70.5% (OTE)"),
                "78.6": FibonacciLevel(self.FIB_786, self._swing_low + range_size * self.FIB_786, "78.6%"),
                "100": FibonacciLevel(self.FIB_100, self._swing_high, "100% (High)"),
            }

            # Equilibrium is at 50%
            self._equilibrium = self._levels["50"].price

            # For SELL: Premium = above equilibrium (favorable)
            # Discount = below equilibrium (unfavorable)
            self._premium_zone_start = self._equilibrium  # 50%
            self._premium_zone_end = self._swing_high  # 100%
            self._discount_zone_start = self._swing_low  # 0%
            self._discount_zone_end = self._equilibrium  # 50%

            # OTE zone for SELL: 62%-79% retracement (high prices)
            self._optimal_entry_low = self._levels["61.8"].price
            self._optimal_entry_high = self._levels["78.6"].price
            self._recommended_entry = self._levels["70.5"].price

    def get_zone(self, price: float) -> PriceZone:
        """
        Determine which price zone a given price falls into.

        Args:
            price: Current price to classify

        Returns:
            PriceZone classification relative to current direction
        """
        if not self._is_valid or self._equilibrium is None:
            return PriceZone.UNKNOWN

        if self._direction == TradeDirection.BUY:
            # For BUY: lower = better (discount)
            if price <= self._levels["78.6"].price:
                return PriceZone.DEEP_DISCOUNT
            elif price <= self._equilibrium:
                return PriceZone.DISCOUNT
            elif abs(price - self._equilibrium) < (self._swing_high - self._swing_low) * 0.02:
                return PriceZone.EQUILIBRIUM
            elif price <= self._levels["23.6"].price:
                return PriceZone.PREMIUM
            else:
                return PriceZone.DEEP_PREMIUM

        elif self._direction == TradeDirection.SELL:
            # For SELL: higher = better (premium)
            if price >= self._levels["78.6"].price:
                return PriceZone.DEEP_PREMIUM
            elif price >= self._equilibrium:
                return PriceZone.PREMIUM
            elif abs(price - self._equilibrium) < (self._swing_high - self._swing_low) * 0.02:
                return PriceZone.EQUILIBRIUM
            elif price >= self._levels["23.6"].price:
                return PriceZone.DISCOUNT
            else:
                return PriceZone.DEEP_DISCOUNT

        return PriceZone.UNKNOWN

    def is_in_discount(self, price: float) -> bool:
        """Check if price is in discount zone (favorable for BUY)."""
        if not self._is_valid:
            return False
        zone = self.get_zone(price)
        return zone in (PriceZone.DISCOUNT, PriceZone.DEEP_DISCOUNT)

    def is_in_premium(self, price: float) -> bool:
        """Check if price is in premium zone (favorable for SELL)."""
        if not self._is_valid:
            return False
        zone = self.get_zone(price)
        return zone in (PriceZone.PREMIUM, PriceZone.DEEP_PREMIUM)

    def is_in_optimal_entry_zone(self, price: float) -> bool:
        """Check if price is in the optimal trade entry zone (62%-79%)."""
        if not self._is_valid:
            return False
        if self._optimal_entry_low is None or self._optimal_entry_high is None:
            return False
        return self._optimal_entry_low <= price <= self._optimal_entry_high

    def handle_bar(self, bar) -> None:
        """Not used - this indicator is updated via update() method."""
        pass

    def handle_trade_tick(self, tick) -> None:
        """Not used - this indicator is updated via update() method."""
        pass

    def handle_quote_tick(self, tick) -> None:
        """Not used - this indicator is updated via update() method."""
        pass

    def reset(self) -> None:
        """Reset the indicator state."""
        super().reset()
        self._direction = TradeDirection.NONE
        self._swing_high = None
        self._swing_low = None
        self._levels = {}
        self._equilibrium = None
        self._premium_zone_start = None
        self._premium_zone_end = None
        self._discount_zone_start = None
        self._discount_zone_end = None
        self._optimal_entry_low = None
        self._optimal_entry_high = None
        self._recommended_entry = None
        self._is_valid = False

    # --- Properties ---

    @property
    def is_valid(self) -> bool:
        """Whether the indicator has valid calculated levels."""
        return self._is_valid

    @property
    def direction(self) -> TradeDirection:
        """Current trade direction."""
        return self._direction

    @property
    def swing_high(self) -> Optional[float]:
        """Upper boundary of the dealing range."""
        return self._swing_high

    @property
    def swing_low(self) -> Optional[float]:
        """Lower boundary of the dealing range."""
        return self._swing_low

    @property
    def dealing_range(self) -> Optional[float]:
        """Size of the dealing range (swing_high - swing_low)."""
        if self._swing_high is None or self._swing_low is None:
            return None
        return self._swing_high - self._swing_low

    @property
    def equilibrium(self) -> Optional[float]:
        """50% retracement level (middle of the range)."""
        return self._equilibrium

    @property
    def premium_zone_start(self) -> Optional[float]:
        """Start of premium zone."""
        return self._premium_zone_start

    @property
    def premium_zone_end(self) -> Optional[float]:
        """End of premium zone."""
        return self._premium_zone_end

    @property
    def discount_zone_start(self) -> Optional[float]:
        """Start of discount zone."""
        return self._discount_zone_start

    @property
    def discount_zone_end(self) -> Optional[float]:
        """End of discount zone."""
        return self._discount_zone_end

    @property
    def optimal_entry_low(self) -> Optional[float]:
        """Lower bound of optimal trade entry zone."""
        return self._optimal_entry_low

    @property
    def optimal_entry_high(self) -> Optional[float]:
        """Upper bound of optimal trade entry zone."""
        return self._optimal_entry_high

    @property
    def recommended_entry(self) -> Optional[float]:
        """Recommended entry price (70.5% OTE level)."""
        return self._recommended_entry

    @property
    def levels(self) -> dict[str, FibonacciLevel]:
        """All calculated Fibonacci levels."""
        return self._levels.copy()

    def get_level_price(self, percentage: str) -> Optional[float]:
        """Get price for a specific Fibonacci level by percentage string."""
        level = self._levels.get(percentage)
        return level.price if level else None
