"""
Tests for WeeklyContextRule.

These tests verify:
- Weekly structure detection (bullish/bearish/neutral)
- Premium/Discount zone correctness
- Recommended entry level validity
- Trade blocking conditions
- Integration with SmartPivotPoints and FibonacciLevels
- SharedState outputs
"""

import os
import sys
from abc import ABC, abstractmethod
from typing import Sequence
from unittest.mock import MagicMock

import pytest

# Ensure we can import from the project root
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# --- MOCKING NAUTILUS TRADER ---
sys.modules["pandas"] = MagicMock()
sys.modules["nautilus_trader"] = MagicMock()
sys.modules["nautilus_trader.core"] = MagicMock()
sys.modules["nautilus_trader.core.correctness"] = MagicMock()
sys.modules["nautilus_trader.indicators"] = MagicMock()
sys.modules["nautilus_trader.indicators.base"] = MagicMock()
sys.modules["nautilus_trader.model"] = MagicMock()
sys.modules["nautilus_trader.model.data"] = MagicMock()
sys.modules["nautilus_trader.model.enums"] = MagicMock()
sys.modules["nautilus_trader.trading"] = MagicMock()


class MockIndicator:
    def __init__(self, inputs=None):
        pass

    def reset(self):
        pass


sys.modules["nautilus_trader.indicators.base"].Indicator = MockIndicator

from constants.shared_dict_key import SharedDictKey

# Import dependencies
from core import SharedState
from indicators.fibonacci_levels import FibonacciLevels, PriceZone, TradeDirection

# Import indicators
from indicators.smart_pivot_points import SmartPivotPoints, Trend


# Mock RuleBase
class MockRuleBase(ABC):
    """Mock RuleBase for testing."""

    is_backtest = False

    def __init__(self, shared_state=None):
        self.shared_state = shared_state

    @abstractmethod
    def evaluate(self, bar, current_bar=None):
        pass

    def on_register_indicator_for_bars(self):
        pass

    def on_start(self):
        pass

    def on_stop(self):
        pass


# Mock the core.rules module
mock_rules_module = MagicMock()
mock_rules_module.RuleBase = MockRuleBase
sys.modules["core.rules"] = mock_rules_module
sys.modules["core.rules.rule_base"] = MagicMock()
sys.modules["core.rules.rule_base"].RuleBase = MockRuleBase


# Mock Bar object
class MockBar:
    """Mock Bar object matching nautilus_trader Bar interface."""

    def __init__(self, open_price: float, high: float, low: float, close: float, ts_event: int = 0):
        self.open = open_price
        self.high = high
        self.low = low
        self.close = close
        self.ts_event = ts_event
        self.bar_type = MagicMock()


def _bars_from_ohlc(series: Sequence[tuple[float, float, float, float]]) -> list[MockBar]:
    """Build bars from a list of (open, high, low, close) tuples."""
    bars = []
    for i, (o, h, l, c) in enumerate(series):
        bars.append(MockBar(open_price=o, high=h, low=l, close=c, ts_event=i * 1000))
    return bars


# Import and recreate WeeklyContextRule for testing
from dataclasses import dataclass
from enum import Enum
from typing import Optional


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
    bar_type = None
    base_bar_type = None


class WeeklyContextRule(MockRuleBase):
    """Test version of WeeklyContextRule."""

    def __init__(self, shared_state: SharedState, strategy, config: WeeklyContextRuleConfig):
        super().__init__(shared_state)
        self.strategy = strategy
        self.config = config
        self.smart_pivot_points = SmartPivotPoints()
        self.fibonacci_levels = FibonacciLevels()
        self.first_bar_initialized = False
        self._last_close_price: Optional[float] = None
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

    def evaluate(self, bar, current_bar=None) -> bool:
        target_bar_type = self.config.bar_type if self.config.bar_type else bar.bar_type
        if str(bar.bar_type) not in str(target_bar_type) and self.first_bar_initialized:
            return True
        if not self.first_bar_initialized:
            self.first_bar_initialized = True

        self.smart_pivot_points.handle_bar(bar)
        self._last_close_price = float(bar.close)
        current_price = float(current_bar.close) if current_bar else float(bar.close)

        self._update_weekly_structure()
        self._update_fibonacci_levels()
        self._update_weekly_zone(current_price)
        self._update_blocking_flags(current_price)
        self._save_to_shared_state()
        return True

    def _update_weekly_structure(self) -> None:
        trend = self.smart_pivot_points.trend
        if trend == Trend.UP:
            self._weekly_structure = WeeklyStructure.BULLISH
        elif trend == Trend.DOWN:
            self._weekly_structure = WeeklyStructure.BEARISH
        else:
            self._weekly_structure = WeeklyStructure.NEUTRAL

    def _update_fibonacci_levels(self) -> None:
        major_high = self.smart_pivot_points.major_high
        major_low = self.smart_pivot_points.major_low

        if major_high is None or major_low is None or major_low >= major_high:
            self._reset_fibonacci_state()
            return

        self._dealing_range_high = major_high
        self._dealing_range_low = major_low

        if self._weekly_structure == WeeklyStructure.BULLISH:
            fib_direction = TradeDirection.BUY
        elif self._weekly_structure == WeeklyStructure.BEARISH:
            fib_direction = TradeDirection.SELL
        else:
            fib_direction = TradeDirection.BUY

        self.fibonacci_levels.update(major_low, major_high, fib_direction)

        if self.fibonacci_levels.is_valid:
            self._equilibrium = self.fibonacci_levels.equilibrium
            self._recommended_entry_price = self.fibonacci_levels.recommended_entry
            self._ote_high = self.fibonacci_levels.optimal_entry_high
            self._ote_low = self.fibonacci_levels.optimal_entry_low

    def _reset_fibonacci_state(self) -> None:
        self._dealing_range_high = None
        self._dealing_range_low = None
        self._equilibrium = None
        self._recommended_entry_price = None
        self._ote_high = None
        self._ote_low = None
        self.fibonacci_levels.reset()

    def _update_weekly_zone(self, current_price: float) -> None:
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
        self._block_longs = False
        self._block_shorts = False

        if self._weekly_structure == WeeklyStructure.NEUTRAL:
            return
        if self._weekly_zone == WeeklyZone.UNKNOWN:
            return

        if self._weekly_structure == WeeklyStructure.BULLISH:
            if self._weekly_zone == WeeklyZone.DISCOUNT:
                self._block_shorts = True
        elif self._weekly_structure == WeeklyStructure.BEARISH:
            if self._weekly_zone == WeeklyZone.PREMIUM:
                self._block_longs = True

    def _save_to_shared_state(self) -> None:
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

    @property
    def weekly_structure(self) -> WeeklyStructure:
        return self._weekly_structure

    @property
    def weekly_zone(self) -> WeeklyZone:
        return self._weekly_zone

    @property
    def block_longs(self) -> bool:
        return self._block_longs

    @property
    def block_shorts(self) -> bool:
        return self._block_shorts

    @property
    def recommended_entry_price(self) -> Optional[float]:
        return self._recommended_entry_price

    @property
    def dealing_range_high(self) -> Optional[float]:
        return self._dealing_range_high

    @property
    def dealing_range_low(self) -> Optional[float]:
        return self._dealing_range_low

    @property
    def equilibrium(self) -> Optional[float]:
        return self._equilibrium

    @property
    def trend(self) -> Trend:
        return self.smart_pivot_points.trend

    def is_favorable_for_longs(self, price: Optional[float] = None) -> bool:
        if self._weekly_structure != WeeklyStructure.BULLISH:
            return False
        check_price = price if price is not None else self._last_close_price
        if check_price is None:
            return False
        return self.fibonacci_levels.is_in_discount(check_price)

    def is_favorable_for_shorts(self, price: Optional[float] = None) -> bool:
        if self._weekly_structure != WeeklyStructure.BEARISH:
            return False
        check_price = price if price is not None else self._last_close_price
        if check_price is None:
            return False
        return self.fibonacci_levels.is_in_premium(check_price)


# ============================================================================
# TESTS
# ============================================================================


class TestWeeklyContextRuleBullishStructure:
    """Tests for bullish Weekly structure detection."""

    def test_bullish_structure_detected(self):
        """Test that bullish Weekly structure is correctly detected."""
        shared_state = SharedState()
        mock_strategy = MagicMock()
        config = WeeklyContextRuleConfig()

        rule = WeeklyContextRule(shared_state, mock_strategy, config)

        # Build uptrend-friendly OHLC series (HH -> HL -> HH)
        uptrend_prices = [
            (97, 100, 95, 98),  # 0. Initial range
            (98, 105, 97, 104),  # 1. Potential HH
            (104, 106, 100, 106),  # 2. Break above -> BULLISH confirmed
            (106, 107, 99, 100),  # 3. Pullback (potential HL)
            (100, 108, 98, 107),  # 4. Break above confirms HL
        ]

        bars = _bars_from_ohlc(uptrend_prices)
        for bar in bars:
            rule.evaluate(bar)

        assert rule.weekly_structure == WeeklyStructure.BULLISH
        assert rule.trend == Trend.UP
        assert shared_state.get(SharedDictKey.WEEKLY_STRUCTURE) == "bullish"

    def test_bullish_structure_fibonacci_orientation(self):
        """Test that Fibonacci is oriented for BUY in bullish structure."""
        shared_state = SharedState()
        mock_strategy = MagicMock()
        config = WeeklyContextRuleConfig()

        rule = WeeklyContextRule(shared_state, mock_strategy, config)

        # Establish bullish structure
        uptrend_prices = [
            (97, 100, 95, 98),
            (98, 105, 97, 104),
            (104, 106, 100, 106),  # Break above -> BULLISH
        ]

        bars = _bars_from_ohlc(uptrend_prices)
        for bar in bars:
            rule.evaluate(bar)

        # Verify Fibonacci is set for BUY direction
        assert rule.fibonacci_levels.direction == TradeDirection.BUY
        assert rule.fibonacci_levels.is_valid


class TestWeeklyContextRuleBearishStructure:
    """Tests for bearish Weekly structure detection."""

    def test_bearish_structure_detected(self):
        """Test that bearish Weekly structure is correctly detected."""
        shared_state = SharedState()
        mock_strategy = MagicMock()
        config = WeeklyContextRuleConfig()

        rule = WeeklyContextRule(shared_state, mock_strategy, config)

        # Build downtrend-friendly OHLC series (LL -> LH -> LL)
        downtrend_prices = [
            (107, 110, 105, 108),  # 0. Initial range
            (108, 108, 102, 103),  # 1. Drop
            (103, 105, 100, 99),  # 2. Break below -> BEARISH confirmed
            (99, 106, 99, 105),  # 3. Pullback (potential LH)
            (105, 106, 95, 96),  # 4. Break below confirms LH
        ]

        bars = _bars_from_ohlc(downtrend_prices)
        for bar in bars:
            rule.evaluate(bar)

        assert rule.weekly_structure == WeeklyStructure.BEARISH
        assert rule.trend == Trend.DOWN
        assert shared_state.get(SharedDictKey.WEEKLY_STRUCTURE) == "bearish"

    def test_bearish_structure_fibonacci_orientation(self):
        """Test that Fibonacci is oriented for SELL in bearish structure."""
        shared_state = SharedState()
        mock_strategy = MagicMock()
        config = WeeklyContextRuleConfig()

        rule = WeeklyContextRule(shared_state, mock_strategy, config)

        # Establish bearish structure
        downtrend_prices = [
            (107, 110, 105, 108),
            (108, 108, 102, 103),
            (103, 105, 100, 99),  # Break below -> BEARISH
        ]

        bars = _bars_from_ohlc(downtrend_prices)
        for bar in bars:
            rule.evaluate(bar)

        # Verify Fibonacci is set for SELL direction
        assert rule.fibonacci_levels.direction == TradeDirection.SELL
        assert rule.fibonacci_levels.is_valid


class TestWeeklyContextRuleNeutralStructure:
    """Tests for neutral Weekly structure."""

    def test_neutral_structure_on_initialization(self):
        """Test that structure is neutral on initialization."""
        shared_state = SharedState()
        mock_strategy = MagicMock()
        config = WeeklyContextRuleConfig()

        rule = WeeklyContextRule(shared_state, mock_strategy, config)

        # Only one bar - not enough to establish structure
        prices = [(100, 105, 95, 100)]
        bars = _bars_from_ohlc(prices)

        for bar in bars:
            rule.evaluate(bar)

        assert rule.weekly_structure == WeeklyStructure.NEUTRAL
        assert rule.trend == Trend.UNDEFINED
        assert shared_state.get(SharedDictKey.WEEKLY_STRUCTURE) == "neutral"


class TestWeeklyContextRuleZoneClassification:
    """Tests for Weekly zone classification."""

    def test_discount_zone_in_bullish_structure(self):
        """Test discount zone is detected when price below equilibrium in bullish structure."""
        shared_state = SharedState()
        mock_strategy = MagicMock()
        config = WeeklyContextRuleConfig()

        rule = WeeklyContextRule(shared_state, mock_strategy, config)

        # Establish bullish structure with clear range
        uptrend_prices = [
            (95, 100, 90, 95),  # Range: 90-100
            (95, 105, 94, 104),  # Potential HH
            (104, 110, 100, 108),  # Break above -> BULLISH, new high
            (108, 112, 102, 103),  # Pullback
            (103, 106, 92, 93),  # Deep pullback to discount zone
        ]

        bars = _bars_from_ohlc(uptrend_prices)
        for bar in bars:
            rule.evaluate(bar)

        # Price at 93 should be in discount zone for bullish structure
        # Dealing range is roughly 92-112, equilibrium ~102
        # 93 < 102 so discount
        assert rule.weekly_zone == WeeklyZone.DISCOUNT
        assert shared_state.get(SharedDictKey.WEEKLY_ZONE) == "discount"

    def test_premium_zone_in_bearish_structure(self):
        """Test premium zone is detected when price above equilibrium in bearish structure."""
        shared_state = SharedState()
        mock_strategy = MagicMock()
        config = WeeklyContextRuleConfig()

        rule = WeeklyContextRule(shared_state, mock_strategy, config)

        # Establish bearish structure
        downtrend_prices = [
            (107, 110, 105, 108),  # Range: 105-110
            (108, 108, 100, 101),  # Drop
            (101, 103, 95, 96),  # Break below -> BEARISH
            (96, 98, 90, 92),  # New low
            (92, 105, 91, 103),  # Rally back to premium zone
        ]

        bars = _bars_from_ohlc(downtrend_prices)
        for bar in bars:
            rule.evaluate(bar)

        # Price at 103 should be in premium zone for bearish structure
        # with dealing range around 90-105, equilibrium ~97.5
        # 103 > 97.5 so premium
        assert rule.weekly_zone == WeeklyZone.PREMIUM
        assert shared_state.get(SharedDictKey.WEEKLY_ZONE) == "premium"


class TestWeeklyContextRuleTradeBlocking:
    """Tests for trade blocking logic."""

    def test_block_shorts_in_bullish_discount(self):
        """Test shorts are blocked when bullish structure + discount zone."""
        shared_state = SharedState()
        mock_strategy = MagicMock()
        config = WeeklyContextRuleConfig()

        rule = WeeklyContextRule(shared_state, mock_strategy, config)

        # Establish bullish structure with controlled pullback
        # SmartPivotPoints updates major_low on each BOS, so we need to track:
        # After bar 1 (break above 100): major_low=90, major_high=105, candidate_low=94
        # After bar 2 (113 > 105): major_low=94, major_high=115, candidate_low=100
        # After bar 3 (116 > 115): major_low=100, major_high=118, candidate_low=110
        # Bar 4: Need close > 100 to avoid reversal, but < equilibrium (109) for discount
        uptrend_prices = [
            (95, 100, 90, 95),  # 0. Initial range (90-100)
            (95, 105, 94, 104),  # 1. Break above -> BULLISH
            (104, 115, 100, 113),  # 2. Continue up
            (113, 118, 110, 116),  # 3. Continue up, major_low becomes 100
            (116, 117, 102, 104),  # 4. Pullback, close=104 > major_low=100, equilibrium~109
        ]

        bars = _bars_from_ohlc(uptrend_prices)
        for bar in bars:
            rule.evaluate(bar)

        # Verify bullish structure maintained
        assert rule.weekly_structure == WeeklyStructure.BULLISH, f"Expected BULLISH, got {rule.weekly_structure}"

        # Close at 104 with dealing range ~100-118, equilibrium ~109
        # 104 < 109, so should be in discount
        assert rule.weekly_zone == WeeklyZone.DISCOUNT, f"Expected DISCOUNT, got {rule.weekly_zone}"

        # Bullish + Discount = Block shorts
        assert rule.block_shorts is True
        assert rule.block_longs is False
        assert shared_state.get(SharedDictKey.WEEKLY_BLOCK_SHORTS) is True
        assert shared_state.get(SharedDictKey.WEEKLY_BLOCK_LONGS) is False

    def test_block_longs_in_bearish_premium(self):
        """Test longs are blocked when bearish structure + premium zone."""
        shared_state = SharedState()
        mock_strategy = MagicMock()
        config = WeeklyContextRuleConfig()

        rule = WeeklyContextRule(shared_state, mock_strategy, config)

        # Establish bearish structure
        downtrend_prices = [
            (107, 110, 105, 108),
            (108, 108, 100, 101),
            (101, 103, 95, 96),  # Break below -> BEARISH
            (96, 98, 90, 92),  # New low
            (92, 105, 91, 103),  # Rally to premium
        ]

        bars = _bars_from_ohlc(downtrend_prices)
        for bar in bars:
            rule.evaluate(bar)

        # Bearish + Premium = Block longs
        assert rule.block_longs is True
        assert rule.block_shorts is False
        assert shared_state.get(SharedDictKey.WEEKLY_BLOCK_LONGS) is True
        assert shared_state.get(SharedDictKey.WEEKLY_BLOCK_SHORTS) is False

    def test_no_blocking_in_neutral_structure(self):
        """Test no blocking when structure is neutral."""
        shared_state = SharedState()
        mock_strategy = MagicMock()
        config = WeeklyContextRuleConfig()

        rule = WeeklyContextRule(shared_state, mock_strategy, config)

        # Only one bar - neutral structure
        prices = [(100, 105, 95, 100)]
        bars = _bars_from_ohlc(prices)

        for bar in bars:
            rule.evaluate(bar)

        assert rule.block_longs is False
        assert rule.block_shorts is False

    def test_no_blocking_bullish_premium(self):
        """Test no blocking when bullish structure but price in premium."""
        shared_state = SharedState()
        mock_strategy = MagicMock()
        config = WeeklyContextRuleConfig()

        rule = WeeklyContextRule(shared_state, mock_strategy, config)

        # Establish bullish structure with price staying high
        uptrend_prices = [
            (95, 100, 90, 95),
            (95, 105, 94, 104),
            (104, 110, 100, 108),  # Break above -> BULLISH
            (108, 115, 105, 114),  # Continues higher (premium zone)
        ]

        bars = _bars_from_ohlc(uptrend_prices)
        for bar in bars:
            rule.evaluate(bar)

        # Bullish + Premium = No blocking (neutral)
        assert rule.block_shorts is False
        assert rule.block_longs is False


class TestWeeklyContextRuleRecommendedEntry:
    """Tests for recommended entry price."""

    def test_recommended_entry_in_bullish_structure(self):
        """Test recommended entry is in discount zone for bullish structure."""
        shared_state = SharedState()
        mock_strategy = MagicMock()
        config = WeeklyContextRuleConfig()

        rule = WeeklyContextRule(shared_state, mock_strategy, config)

        # Establish bullish structure
        uptrend_prices = [
            (95, 100, 90, 95),
            (95, 105, 94, 104),
            (104, 110, 100, 108),  # Break above -> BULLISH
        ]

        bars = _bars_from_ohlc(uptrend_prices)
        for bar in bars:
            rule.evaluate(bar)

        # Recommended entry should exist and be in lower half of range
        assert rule.recommended_entry_price is not None
        assert rule.equilibrium is not None

        # For BUY, recommended entry should be below equilibrium
        assert rule.recommended_entry_price < rule.equilibrium

        # Should be stored in shared state
        assert shared_state.get(SharedDictKey.WEEKLY_RECOMMENDED_ENTRY_PRICE) is not None

    def test_recommended_entry_in_bearish_structure(self):
        """Test recommended entry is in premium zone for bearish structure."""
        shared_state = SharedState()
        mock_strategy = MagicMock()
        config = WeeklyContextRuleConfig()

        rule = WeeklyContextRule(shared_state, mock_strategy, config)

        # Establish bearish structure
        downtrend_prices = [
            (107, 110, 105, 108),
            (108, 108, 100, 101),
            (101, 103, 95, 96),  # Break below -> BEARISH
        ]

        bars = _bars_from_ohlc(downtrend_prices)
        for bar in bars:
            rule.evaluate(bar)

        # Recommended entry should exist and be in upper half of range
        assert rule.recommended_entry_price is not None
        assert rule.equilibrium is not None

        # For SELL, recommended entry should be above equilibrium
        assert rule.recommended_entry_price > rule.equilibrium

    def test_recommended_entry_in_ote_zone(self):
        """Test recommended entry is within OTE zone (62%-79% retracement)."""
        shared_state = SharedState()
        mock_strategy = MagicMock()
        config = WeeklyContextRuleConfig()

        rule = WeeklyContextRule(shared_state, mock_strategy, config)

        # Establish bullish structure
        uptrend_prices = [
            (95, 100, 90, 95),
            (95, 105, 94, 104),
            (104, 110, 100, 108),
        ]

        bars = _bars_from_ohlc(uptrend_prices)
        for bar in bars:
            rule.evaluate(bar)

        # Recommended entry should be at 70.5% level (between OTE bounds)
        assert rule.recommended_entry_price is not None

        ote_low = shared_state.get(SharedDictKey.WEEKLY_OTE_LOW)
        ote_high = shared_state.get(SharedDictKey.WEEKLY_OTE_HIGH)

        assert ote_low is not None
        assert ote_high is not None

        # For BUY direction, OTE low < recommended < OTE high
        assert ote_low <= rule.recommended_entry_price <= ote_high


class TestWeeklyContextRuleDealingRange:
    """Tests for dealing range outputs."""

    def test_dealing_range_stored_correctly(self):
        """Test dealing range is stored correctly in shared state."""
        shared_state = SharedState()
        mock_strategy = MagicMock()
        config = WeeklyContextRuleConfig()

        rule = WeeklyContextRule(shared_state, mock_strategy, config)

        # Establish structure
        prices = [
            (95, 100, 90, 95),
            (95, 105, 94, 104),
            (104, 110, 100, 108),
        ]

        bars = _bars_from_ohlc(prices)
        for bar in bars:
            rule.evaluate(bar)

        # Dealing range should be set
        assert rule.dealing_range_high is not None
        assert rule.dealing_range_low is not None
        assert rule.dealing_range_high > rule.dealing_range_low

        # Should match shared state
        assert shared_state.get(SharedDictKey.WEEKLY_DEALING_RANGE_HIGH) == rule.dealing_range_high
        assert shared_state.get(SharedDictKey.WEEKLY_DEALING_RANGE_LOW) == rule.dealing_range_low

    def test_equilibrium_is_midpoint(self):
        """Test equilibrium is midpoint of dealing range."""
        shared_state = SharedState()
        mock_strategy = MagicMock()
        config = WeeklyContextRuleConfig()

        rule = WeeklyContextRule(shared_state, mock_strategy, config)

        prices = [
            (95, 100, 90, 95),
            (95, 105, 94, 104),
            (104, 110, 100, 108),
        ]

        bars = _bars_from_ohlc(prices)
        for bar in bars:
            rule.evaluate(bar)

        # Equilibrium should be midpoint
        assert rule.dealing_range_high is not None
        assert rule.dealing_range_low is not None
        expected_equilibrium = (rule.dealing_range_high + rule.dealing_range_low) / 2
        assert rule.equilibrium is not None
        assert abs(rule.equilibrium - expected_equilibrium) < 0.01


class TestWeeklyContextRuleFavorability:
    """Tests for is_favorable_for_longs/shorts methods."""

    def test_favorable_for_longs_in_bullish_discount(self):
        """Test is_favorable_for_longs returns True in bullish + discount."""
        shared_state = SharedState()
        mock_strategy = MagicMock()
        config = WeeklyContextRuleConfig()

        rule = WeeklyContextRule(shared_state, mock_strategy, config)

        # Establish bullish structure with controlled pullback
        # Close must stay above major_low to maintain structure
        uptrend_prices = [
            (95, 100, 90, 95),  # 0. Initial range (90-100)
            (95, 105, 94, 104),  # 1. Break above -> BULLISH
            (104, 115, 100, 113),  # 2. Continue up
            (113, 118, 110, 116),  # 3. Continue up, major_low becomes 100
            (116, 117, 102, 104),  # 4. Pullback, close=104 > major_low=100
        ]

        bars = _bars_from_ohlc(uptrend_prices)
        for bar in bars:
            rule.evaluate(bar)

        # Verify structure is bullish
        assert rule.weekly_structure == WeeklyStructure.BULLISH

        # Should be favorable for longs (bullish + discount zone)
        # Close at 104 is below equilibrium ~109, so in discount
        assert rule.is_favorable_for_longs() is True

    def test_not_favorable_for_longs_in_bearish(self):
        """Test is_favorable_for_longs returns False in bearish structure."""
        shared_state = SharedState()
        mock_strategy = MagicMock()
        config = WeeklyContextRuleConfig()

        rule = WeeklyContextRule(shared_state, mock_strategy, config)

        # Establish bearish structure
        downtrend_prices = [
            (107, 110, 105, 108),
            (108, 108, 100, 101),
            (101, 103, 95, 96),
        ]

        bars = _bars_from_ohlc(downtrend_prices)
        for bar in bars:
            rule.evaluate(bar)

        # Should NOT be favorable for longs
        assert rule.is_favorable_for_longs() is False

    def test_favorable_for_shorts_in_bearish_premium(self):
        """Test is_favorable_for_shorts returns True in bearish + premium."""
        shared_state = SharedState()
        mock_strategy = MagicMock()
        config = WeeklyContextRuleConfig()

        rule = WeeklyContextRule(shared_state, mock_strategy, config)

        # Establish bearish structure
        downtrend_prices = [
            (107, 110, 105, 108),
            (108, 108, 100, 101),
            (101, 103, 95, 96),
            (96, 98, 90, 92),
            (92, 105, 91, 103),  # Rally to premium
        ]

        bars = _bars_from_ohlc(downtrend_prices)
        for bar in bars:
            rule.evaluate(bar)

        # Should be favorable for shorts
        assert rule.is_favorable_for_shorts() is True

    def test_not_favorable_for_shorts_in_bullish(self):
        """Test is_favorable_for_shorts returns False in bullish structure."""
        shared_state = SharedState()
        mock_strategy = MagicMock()
        config = WeeklyContextRuleConfig()

        rule = WeeklyContextRule(shared_state, mock_strategy, config)

        # Establish bullish structure
        uptrend_prices = [
            (95, 100, 90, 95),
            (95, 105, 94, 104),
            (104, 110, 100, 108),
        ]

        bars = _bars_from_ohlc(uptrend_prices)
        for bar in bars:
            rule.evaluate(bar)

        # Should NOT be favorable for shorts
        assert rule.is_favorable_for_shorts() is False


class TestWeeklyContextRuleSharedStateIntegration:
    """Tests for SharedState integration."""

    def test_all_outputs_saved_to_shared_state(self):
        """Test all required outputs are saved to shared state."""
        shared_state = SharedState()
        mock_strategy = MagicMock()
        config = WeeklyContextRuleConfig()

        rule = WeeklyContextRule(shared_state, mock_strategy, config)

        # Establish structure
        prices = [
            (95, 100, 90, 95),
            (95, 105, 94, 104),
            (104, 110, 100, 108),
        ]

        bars = _bars_from_ohlc(prices)
        for bar in bars:
            rule.evaluate(bar)

        # All required keys should be set
        assert shared_state.get(SharedDictKey.WEEKLY_STRUCTURE) is not None
        assert shared_state.get(SharedDictKey.WEEKLY_ZONE) is not None
        assert shared_state.get(SharedDictKey.WEEKLY_BLOCK_LONGS) is not None
        assert shared_state.get(SharedDictKey.WEEKLY_BLOCK_SHORTS) is not None
        assert shared_state.get(SharedDictKey.WEEKLY_RECOMMENDED_ENTRY_PRICE) is not None
        assert shared_state.get(SharedDictKey.WEEKLY_DEALING_RANGE_HIGH) is not None
        assert shared_state.get(SharedDictKey.WEEKLY_DEALING_RANGE_LOW) is not None
        assert shared_state.get(SharedDictKey.WEEKLY_EQUILIBRIUM) is not None
        assert shared_state.get(SharedDictKey.WEEKLY_OTE_HIGH) is not None
        assert shared_state.get(SharedDictKey.WEEKLY_OTE_LOW) is not None


class TestWeeklyContextRuleNoExecutionLogic:
    """Tests ensuring rule has no execution logic."""

    def test_evaluate_always_returns_true(self):
        """Test that evaluate always returns True (no blocking)."""
        shared_state = SharedState()
        mock_strategy = MagicMock()
        config = WeeklyContextRuleConfig()

        rule = WeeklyContextRule(shared_state, mock_strategy, config)

        # Various scenarios
        scenarios = [
            [(100, 105, 95, 100)],  # Single bar
            [(95, 100, 90, 95), (95, 105, 94, 104), (104, 110, 100, 108)],  # Bullish
            [(107, 110, 105, 108), (108, 108, 100, 101), (101, 103, 95, 96)],  # Bearish
        ]

        for prices in scenarios:
            bars = _bars_from_ohlc(prices)
            for bar in bars:
                result = rule.evaluate(bar)
                assert result is True, "Context rule must always return True"

    def test_rule_has_no_signal_output(self):
        """Test rule doesn't output entry signals (BUY/SELL)."""
        shared_state = SharedState()
        mock_strategy = MagicMock()
        config = WeeklyContextRuleConfig()

        rule = WeeklyContextRule(shared_state, mock_strategy, config)

        prices = [
            (95, 100, 90, 95),
            (95, 105, 94, 104),
            (104, 110, 100, 108),
        ]

        bars = _bars_from_ohlc(prices)
        for bar in bars:
            rule.evaluate(bar)

        # Rule should NOT have a signal attribute or entry_rule_signal
        assert not hasattr(rule, "signal")
        # entry_rule_signal key should NOT be set by this rule
        # (it may exist from other rules, but this rule doesn't set it)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
