"""
Weekly Context Rule for ICT Trading.

This rule evaluates Weekly timeframe market structure and premium/discount zones
to provide trade-direction filtering context. It acts ONLY as a context/filter
rule and does NOT generate entry signals or execution logic.

Key Responsibilities:
- Evaluate Weekly market structure using SmartPivotPoints
- Determine Weekly premium/discount zones using Fibonacci levels
- Output trade-direction filters (block_longs, block_shorts)
- Output recommended entry price zone to improve win rate
- Expose dealing range and zone boundaries

Output Signals (via SharedState):
- WEEKLY_STRUCTURE: Market structure ("bullish", "bearish", "neutral")
- WEEKLY_ZONE: Current price zone ("premium", "discount", "equilibrium", "unknown")
- WEEKLY_BLOCK_LONGS: True if long trades should be blocked
- WEEKLY_BLOCK_SHORTS: True if short trades should be blocked
- WEEKLY_RECOMMENDED_ENTRY_PRICE: Recommended entry price (OTE level)
- WEEKLY_DEALING_RANGE_HIGH: Upper boundary of weekly dealing range
- WEEKLY_DEALING_RANGE_LOW: Lower boundary of weekly dealing range
- WEEKLY_EQUILIBRIUM: 50% equilibrium level
- WEEKLY_OTE_HIGH: Upper bound of OTE zone
- WEEKLY_OTE_LOW: Lower bound of OTE zone

Trade Blocking Logic:
- If WeeklyStructure == Bullish AND price in Discount -> BLOCK_SHORTS
- If WeeklyStructure == Bearish AND price in Premium -> BLOCK_LONGS
- All other cases -> neutral (no forced blocking)
"""

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from nautilus_trader.model import Bar, BarType
from nautilus_trader.trading import Strategy

from constants.shared_dict_key import SharedDictKey
from core import SharedState
from core.rules.rule_base import RuleBase
from indicators.smart_pivot_points import SmartPivotPoints, Trend
from indicators.fibonacci_levels import FibonacciLevels, TradeDirection, PriceZone


class WeeklyStructure(Enum):
    """Weekly market structure classification."""
    NEUTRAL = "neutral"
    BULLISH = "bullish"
    BEARISH = "bearish"


class WeeklyZone(Enum):
    """Weekly price zone classification."""
    UNKNOWN = "unknown"
    DISCOUNT = "discount"
    PREMIUM = "premium"
    EQUILIBRIUM = "equilibrium"


@dataclass
class WeeklyContextRuleConfig:
    """
    Configuration for Weekly Context Rule.

    Parameters:
        bar_type: BarType for the Weekly timeframe.
                  MUST be a Weekly bar type for proper structure detection.
        base_bar_type: Optional lower timeframe bar type for current price reference.
                       If provided, used to get current price for zone classification.
    """
    bar_type: Optional[BarType] = None
    base_bar_type: Optional[BarType] = None


class WeeklyContextRule(RuleBase):
    """
    Weekly Timeframe Context Rule using SmartPivotPoints and Fibonacci.

    This rule provides Weekly timeframe context for trade filtering.
    It evaluates market structure and premium/discount zones on the Weekly chart
    to help filter lower timeframe entries.

    IMPORTANT: This is a CONTEXT/FILTER rule ONLY.
    It does NOT generate entry signals or execute trades.

    Usage:
    1. Create with Weekly bar type configuration
    2. Rule automatically detects Weekly structure (bullish/bearish/neutral)
    3. Rule calculates Fibonacci levels for premium/discount zones
    4. Check block_longs/block_shorts flags before taking trades
    5. Use recommended_entry_price for optimal entry zone

    Trade Filtering Logic:
    - Bullish Weekly Structure + Discount Zone = BLOCK SHORTS (favor longs)
    - Bearish Weekly Structure + Premium Zone = BLOCK LONGS (favor shorts)

    Attributes:
        weekly_structure: Current Weekly structure (bullish/bearish/neutral)
        weekly_zone: Current price zone (premium/discount/equilibrium/unknown)
        block_longs: True if long trades should be avoided
        block_shorts: True if short trades should be avoided
        recommended_entry_price: Optimal entry level (OTE 70.5% retracement)
        dealing_range_high: Upper boundary of Weekly dealing range
        dealing_range_low: Lower boundary of Weekly dealing range
        equilibrium: 50% level of Weekly dealing range
    """

    def __init__(
        self,
        shared_state: SharedState,
        strategy: Strategy,
        config: WeeklyContextRuleConfig
    ):
        super().__init__(shared_state)
        self.strategy = strategy
        self.config = config

        # Initialize indicators
        self.smart_pivot_points = SmartPivotPoints()
        self.fibonacci_levels = FibonacciLevels()

        # Internal state
        self.first_bar_initialized = False
        self._last_close_price: Optional[float] = None

        # Computed state (exposed via properties)
        self._weekly_structure: WeeklyStructure = WeeklyStructure.NEUTRAL
        self._weekly_zone: WeeklyZone = WeeklyZone.UNKNOWN
        self._block_longs: bool = False
        self._block_shorts: bool = False
        self._recommended_entry_price: Optional[float] = None
        self._dealing_range_high: Optional[float] = None
        self._dealing_range_low: Optional[float] = None
        self._equilibrium: Optional[float] = None
        self._ote_high: Optional[float] = None
        self._ote_low: Optional[float] = None

    def evaluate(self, bar: Bar, current_bar: Bar = None) -> bool:
        """
        Evaluate Weekly context from the incoming bar.

        This method:
        1. Updates SmartPivotPoints with Weekly bar data
        2. Determines Weekly market structure
        3. Calculates Fibonacci levels for the dealing range
        4. Classifies current price zone
        5. Sets trade blocking flags
        6. Saves all outputs to shared state

        Args:
            bar: The Weekly bar being processed
            current_bar: Optional current bar for real-time price reference

        Returns:
            bool: Always returns True (context rules don't block processing)
        """
        # Determine target bar type
        target_bar_type = self.config.bar_type if self.config.bar_type else bar.bar_type

        # Filter bars - only process matching bar type
        if str(bar.bar_type) not in str(target_bar_type) and self.first_bar_initialized:
            return True

        if not self.first_bar_initialized:
            self.first_bar_initialized = True

        # Update SmartPivotPoints with Weekly bar
        self.smart_pivot_points.handle_bar(bar)

        # Store last close price for zone classification
        self._last_close_price = float(bar.close)

        # Get current price for zone classification
        current_price = self._get_current_price(bar, current_bar)

        # Determine Weekly structure from SmartPivotPoints trend
        self._update_weekly_structure()

        # Update Fibonacci levels based on dealing range and structure
        self._update_fibonacci_levels()

        # Classify current price zone
        self._update_weekly_zone(current_price)

        # Apply trade blocking logic
        self._update_blocking_flags(current_price)

        # Save all outputs to shared state
        self._save_to_shared_state()

        return True

    def _get_current_price(self, bar: Bar, current_bar: Optional[Bar]) -> float:
        """Get current price for zone classification."""
        if current_bar is not None:
            return float(current_bar.close)
        return float(bar.close)

    def _update_weekly_structure(self) -> None:
        """Update Weekly structure based on SmartPivotPoints trend."""
        trend = self.smart_pivot_points.trend

        if trend == Trend.UP:
            # Uptrend: HH -> HL -> HH structure = Bullish
            self._weekly_structure = WeeklyStructure.BULLISH
        elif trend == Trend.DOWN:
            # Downtrend: LL -> LH -> LL structure = Bearish
            self._weekly_structure = WeeklyStructure.BEARISH
        else:
            # Undefined trend = Neutral
            self._weekly_structure = WeeklyStructure.NEUTRAL

    def _update_fibonacci_levels(self) -> None:
        """Update Fibonacci levels based on current dealing range and structure."""
        major_high = self.smart_pivot_points.major_high
        major_low = self.smart_pivot_points.major_low

        if major_high is None or major_low is None:
            self._reset_fibonacci_state()
            return

        if major_low >= major_high:
            self._reset_fibonacci_state()
            return

        # Store dealing range
        self._dealing_range_high = major_high
        self._dealing_range_low = major_low

        # Determine Fibonacci direction based on Weekly structure
        if self._weekly_structure == WeeklyStructure.BULLISH:
            # Bullish: We want to BUY at discount
            fib_direction = TradeDirection.BUY
        elif self._weekly_structure == WeeklyStructure.BEARISH:
            # Bearish: We want to SELL at premium
            fib_direction = TradeDirection.SELL
        else:
            # Neutral: Default to BUY orientation (discount = lower half)
            fib_direction = TradeDirection.BUY

        # Update Fibonacci levels
        self.fibonacci_levels.update(
            swing_low=major_low,
            swing_high=major_high,
            direction=fib_direction
        )

        # Extract key levels
        if self.fibonacci_levels.is_valid:
            self._equilibrium = self.fibonacci_levels.equilibrium
            self._recommended_entry_price = self.fibonacci_levels.recommended_entry
            self._ote_high = self.fibonacci_levels.optimal_entry_high
            self._ote_low = self.fibonacci_levels.optimal_entry_low

    def _reset_fibonacci_state(self) -> None:
        """Reset Fibonacci-related state when invalid."""
        self._dealing_range_high = None
        self._dealing_range_low = None
        self._equilibrium = None
        self._recommended_entry_price = None
        self._ote_high = None
        self._ote_low = None
        self.fibonacci_levels.reset()

    def _update_weekly_zone(self, current_price: float) -> None:
        """Classify current price into Weekly zone."""
        if not self.fibonacci_levels.is_valid:
            self._weekly_zone = WeeklyZone.UNKNOWN
            return

        zone = self.fibonacci_levels.get_zone(current_price)

        if zone in (PriceZone.DISCOUNT, PriceZone.DEEP_DISCOUNT):
            self._weekly_zone = WeeklyZone.DISCOUNT
        elif zone in (PriceZone.PREMIUM, PriceZone.DEEP_PREMIUM):
            self._weekly_zone = WeeklyZone.PREMIUM
        elif zone == PriceZone.EQUILIBRIUM:
            self._weekly_zone = WeeklyZone.EQUILIBRIUM
        else:
            self._weekly_zone = WeeklyZone.UNKNOWN

    def _update_blocking_flags(self, current_price: float) -> None:
        """
        Apply trade blocking logic based on structure and zone.

        Blocking Logic:
        - Bullish structure + Discount zone -> Block shorts (favor longs)
        - Bearish structure + Premium zone -> Block longs (favor shorts)
        - All other combinations -> No blocking (neutral)

        The logic ensures traders trade WITH the Weekly trend in favorable zones.
        """
        # Reset flags
        self._block_longs = False
        self._block_shorts = False

        if self._weekly_structure == WeeklyStructure.NEUTRAL:
            # Neutral structure: no blocking
            return

        if self._weekly_zone == WeeklyZone.UNKNOWN:
            # Unknown zone: no blocking
            return

        # Apply blocking logic
        if self._weekly_structure == WeeklyStructure.BULLISH:
            if self._weekly_zone == WeeklyZone.DISCOUNT:
                # Bullish + Discount = Perfect BUY zone, block shorts
                self._block_shorts = True

        elif self._weekly_structure == WeeklyStructure.BEARISH:
            if self._weekly_zone == WeeklyZone.PREMIUM:
                # Bearish + Premium = Perfect SELL zone, block longs
                self._block_longs = True

    def _save_to_shared_state(self) -> None:
        """Save all computed values to shared state."""
        if self.shared_state is None:
            return
        self.shared_state.set(SharedDictKey.WEEKLY_STRUCTURE, self._weekly_structure.value)
        self.shared_state.set(SharedDictKey.WEEKLY_ZONE, self._weekly_zone.value)
        self.shared_state.set(SharedDictKey.WEEKLY_BLOCK_LONGS, self._block_longs)
        self.shared_state.set(SharedDictKey.WEEKLY_BLOCK_SHORTS, self._block_shorts)
        self.shared_state.set(SharedDictKey.WEEKLY_RECOMMENDED_ENTRY_PRICE, self._recommended_entry_price)
        self.shared_state.set(SharedDictKey.WEEKLY_DEALING_RANGE_HIGH, self._dealing_range_high)
        self.shared_state.set(SharedDictKey.WEEKLY_DEALING_RANGE_LOW, self._dealing_range_low)
        self.shared_state.set(SharedDictKey.WEEKLY_EQUILIBRIUM, self._equilibrium)
        self.shared_state.set(SharedDictKey.WEEKLY_OTE_HIGH, self._ote_high)
        self.shared_state.set(SharedDictKey.WEEKLY_OTE_LOW, self._ote_low)

    def on_register_indicator_for_bars(self) -> None:
        """Register indicators for bar updates before warmup period."""
        bar_type = self.config.bar_type
        if bar_type:
            self.strategy.register_indicator_for_bars(bar_type, self.smart_pivot_points)

    def on_start(self) -> None:
        """Actions to be performed on strategy start."""
        pass

    def on_stop(self) -> None:
        """Actions to be performed on strategy stop."""
        pass

    # --- Public Properties ---

    @property
    def weekly_structure(self) -> WeeklyStructure:
        """Current Weekly market structure (bullish/bearish/neutral)."""
        return self._weekly_structure

    @property
    def weekly_zone(self) -> WeeklyZone:
        """Current price zone (premium/discount/equilibrium/unknown)."""
        return self._weekly_zone

    @property
    def block_longs(self) -> bool:
        """True if long trades should be blocked based on Weekly context."""
        return self._block_longs

    @property
    def block_shorts(self) -> bool:
        """True if short trades should be blocked based on Weekly context."""
        return self._block_shorts

    @property
    def recommended_entry_price(self) -> Optional[float]:
        """
        Recommended entry price for optimal win rate.

        This is the 70.5% OTE (Optimal Trade Entry) level:
        - For bullish structure: Price level in discount zone (lower half)
        - For bearish structure: Price level in premium zone (upper half)

        Returns None if Weekly structure is undefined or dealing range is invalid.
        """
        return self._recommended_entry_price

    @property
    def dealing_range_high(self) -> Optional[float]:
        """Upper boundary of the Weekly dealing range (major high)."""
        return self._dealing_range_high

    @property
    def dealing_range_low(self) -> Optional[float]:
        """Lower boundary of the Weekly dealing range (major low)."""
        return self._dealing_range_low

    @property
    def equilibrium(self) -> Optional[float]:
        """50% level of the Weekly dealing range."""
        return self._equilibrium

    @property
    def ote_high(self) -> Optional[float]:
        """Upper bound of the OTE (Optimal Trade Entry) zone."""
        return self._ote_high

    @property
    def ote_low(self) -> Optional[float]:
        """Lower bound of the OTE (Optimal Trade Entry) zone."""
        return self._ote_low

    @property
    def trend(self) -> Trend:
        """Raw trend from SmartPivotPoints."""
        return self.smart_pivot_points.trend

    def is_favorable_for_longs(self, price: Optional[float] = None) -> bool:
        """
        Check if current context favors long trades.

        A context is favorable for longs when:
        - Weekly structure is bullish
        - Price is in discount zone (or equilibrium)
        - Shorts are blocked

        Args:
            price: Price to check. If None, uses last bar close.

        Returns:
            True if context favors long trades.
        """
        if self._weekly_structure != WeeklyStructure.BULLISH:
            return False

        check_price = price if price is not None else self._last_close_price
        if check_price is None:
            return False

        return self.fibonacci_levels.is_in_discount(check_price)

    def is_favorable_for_shorts(self, price: Optional[float] = None) -> bool:
        """
        Check if current context favors short trades.

        A context is favorable for shorts when:
        - Weekly structure is bearish
        - Price is in premium zone (or equilibrium)
        - Longs are blocked

        Args:
            price: Price to check. If None, uses last bar close.

        Returns:
            True if context favors short trades.
        """
        if self._weekly_structure != WeeklyStructure.BEARISH:
            return False

        check_price = price if price is not None else self._last_close_price
        if check_price is None:
            return False

        return self.fibonacci_levels.is_in_premium(check_price)

    def is_price_at_ote(self, price: Optional[float] = None) -> bool:
        """
        Check if price is in the Optimal Trade Entry zone (62%-79% retracement).

        Args:
            price: Price to check. If None, uses last bar close.

        Returns:
            True if price is in OTE zone.
        """
        check_price = price if price is not None else self._last_close_price
        if check_price is None:
            return False

        return self.fibonacci_levels.is_in_optimal_entry_zone(check_price)
