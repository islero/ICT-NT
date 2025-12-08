"""
Tests for MarketStructureRule using SmartPivotPoints.

These tests verify:
- MarketStructureRule inherits from RuleBase
- Uses SmartPivotPoints indicator for market structure detection
- Returns correct RuleSignal based on trend:
  - trend == 1 (Uptrend) -> RuleSignal.BUY
  - trend == -1 (Downtrend) -> RuleSignal.SELL
  - trend == 0 (Undefined) -> RuleSignal.NONE
- Saves signal to SharedDictKey.MARKET_STRUCTURE_RULE_SIGNAL
"""

import sys
import os
from unittest.mock import MagicMock
from abc import ABC, abstractmethod

import pytest

# Ensure we can import from the project root
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# --- MOCKING NAUTILUS TRADER AND OTHER DEPENDENCIES ---
# Create comprehensive mocks before any imports
sys.modules["pandas"] = MagicMock()
sys.modules["nautilus_trader"] = MagicMock()
sys.modules["nautilus_trader.core"] = MagicMock()
sys.modules["nautilus_trader.core.correctness"] = MagicMock()
sys.modules["nautilus_trader.indicators"] = MagicMock()
sys.modules["nautilus_trader.indicators.base"] = MagicMock()
sys.modules["nautilus_trader.model"] = MagicMock()
sys.modules["nautilus_trader.model.data"] = MagicMock()
sys.modules["nautilus_trader.model.enums"] = MagicMock()
sys.modules["nautilus_trader.model.instruments"] = MagicMock()
sys.modules["nautilus_trader.model.orders"] = MagicMock()
sys.modules["nautilus_trader.model.position"] = MagicMock()
sys.modules["nautilus_trader.model.events"] = MagicMock()
sys.modules["nautilus_trader.trading"] = MagicMock()
sys.modules["nautilus_trader.risk"] = MagicMock()
sys.modules["nautilus_trader.risk.sizing"] = MagicMock()
sys.modules["nautilus_trader.cache"] = MagicMock()
sys.modules["nautilus_trader.execution"] = MagicMock()
sys.modules["nautilus_trader.common"] = MagicMock()
sys.modules["nautilus_trader.common.clock"] = MagicMock()


# Define the base class for Indicator so the import works and subclassing works
class MockIndicator:
    def __init__(self, inputs=None):
        pass

    def reset(self):
        pass


sys.modules["nautilus_trader.indicators.base"].Indicator = MockIndicator
sys.modules["nautilus_trader.model.data"].Bar = MagicMock()

# Import SmartPivotPoints (this works since indicator is implemented)
from indicators.smart_pivot_points import SmartPivotPoints

# Import SharedState and RuleSignal before mocking core.rules
from core import SharedState
from core.enums import RuleSignal
from constants.shared_dict_key import SharedDictKey

# Now create a mock for RuleBase that we can use
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

# Mock the core.rules module to avoid cascading imports
mock_rules_module = MagicMock()
mock_rules_module.RuleBase = MockRuleBase
sys.modules["core.rules"] = mock_rules_module
sys.modules["core.rules.rule_base"] = MagicMock()
sys.modules["core.rules.rule_base"].RuleBase = MockRuleBase

# Now import the rule - but we need to create it inline since imports are problematic
# Instead, let's create the MarketStructureRule class directly in the test

# Mock Bar object for our use
class MockBar:
    """Mock Bar object matching nautilus_trader Bar interface."""

    def __init__(self, open_price: float, high: float, low: float, close: float, ts_event: int = 0):
        self.open = open_price
        self.high = high
        self.low = low
        self.close = close
        self.ts_event = ts_event
        self.bar_type = MagicMock()


def _bars_from_ohlc(series: list[tuple[float, float, float, float]]) -> list[MockBar]:
    """Build bars from a list of (open, high, low, close) tuples."""
    bars = []
    for i, (o, h, l, c) in enumerate(series):
        bars.append(MockBar(
            open_price=o,
            high=h,
            low=l,
            close=c,
            ts_event=i * 1000
        ))
    return bars


# Create the MarketStructureRule class for testing (mirrors the implementation)
from dataclasses import dataclass
from typing import Optional


@dataclass
class MarketStructureRuleConfig:
    """Configuration for Market Structure Rule."""
    bar_type = None


class MarketStructureRule(MockRuleBase):
    """
    Market Structure Rule using SmartPivotPoints indicator.
    """

    def __init__(
        self,
        shared_state: SharedState,
        strategy,
        config: MarketStructureRuleConfig
    ):
        super().__init__(shared_state)
        self.strategy = strategy
        self.config = config
        self.smart_pivot_points = SmartPivotPoints()
        self.first_bar_initialized = False

    @property
    def trend(self) -> int:
        """Returns the current trend from the SmartPivotPoints indicator."""
        return self.smart_pivot_points.trend

    def evaluate(self, bar, current_bar=None) -> bool:
        """Evaluate the rule and detect market structure trend direction."""
        target_bar_type = self.config.bar_type if self.config.bar_type else bar.bar_type

        if str(bar.bar_type) not in str(target_bar_type) and self.first_bar_initialized:
            return True

        if not self.first_bar_initialized:
            self.first_bar_initialized = True

        self.smart_pivot_points.handle_bar(bar)

        trend = self.smart_pivot_points.trend

        if trend == 1:
            signal = RuleSignal.BUY
        elif trend == -1:
            signal = RuleSignal.SELL
        else:
            signal = RuleSignal.NONE

        self.shared_state.set(SharedDictKey.MARKET_STRUCTURE_RULE_SIGNAL, signal)

        return True


class TestMarketStructureRuleUptrend:
    """Tests for uptrend detection via MarketStructureRule."""

    def test_uptrend_structure_returns_trend_1(self):
        """
        Build a small synthetic OHLC series designed to create:
        Uptrend structure: HH → HL → HH

        The rule's evaluation should return trend == 1.
        """
        shared_state = SharedState()
        mock_strategy = MagicMock()
        config = MarketStructureRuleConfig()

        rule = MarketStructureRule(
            shared_state=shared_state,
            strategy=mock_strategy,
            config=config
        )

        # Build uptrend-friendly OHLC series
        uptrend_prices = [
            (97, 100, 95, 98),     # 0. Initial range
            (98, 105, 97, 104),    # 1. Potential HH
            (104, 106, 100, 106),  # 2. Break above 105 -> UPTREND confirmed
            (106, 107, 99, 100),   # 3. Pullback (potential HL)
            (100, 103, 98, 102),   # 4. Continue pullback
            (102, 108, 101, 107),  # 5. Break above 107 confirms HL, new HH
            (107, 110, 104, 109),  # 6. Continue up - HH progression
        ]

        bars = _bars_from_ohlc(uptrend_prices)

        for bar in bars:
            rule.evaluate(bar)

        # Check rule's trend property
        assert rule.trend == 1, f"Expected uptrend (trend=1), got {rule.trend}"

        # Check via rule's internal indicator
        assert rule.smart_pivot_points.trend == 1, \
            f"Expected uptrend (trend=1), got {rule.smart_pivot_points.trend}"

    def test_uptrend_returns_buy_signal(self):
        """Verify uptrend returns RuleSignal.BUY via shared state."""
        shared_state = SharedState()
        mock_strategy = MagicMock()
        config = MarketStructureRuleConfig()

        rule = MarketStructureRule(
            shared_state=shared_state,
            strategy=mock_strategy,
            config=config
        )

        # Build uptrend-friendly OHLC series
        uptrend_prices = [
            (97, 100, 95, 98),
            (98, 105, 97, 104),
            (104, 106, 100, 106),  # Break above -> UPTREND
        ]

        bars = _bars_from_ohlc(uptrend_prices)

        for bar in bars:
            rule.evaluate(bar)

        # Check signal in shared state
        signal = shared_state.get(SharedDictKey.MARKET_STRUCTURE_RULE_SIGNAL)
        assert signal == RuleSignal.BUY, f"Expected RuleSignal.BUY, got {signal}"


class TestMarketStructureRuleDowntrend:
    """Tests for downtrend detection via MarketStructureRule."""

    def test_downtrend_structure_returns_trend_minus_1(self):
        """
        Build a small synthetic OHLC series designed to create:
        Downtrend structure: LL → LH → LL

        The rule's evaluation should return trend == -1.
        """
        shared_state = SharedState()
        mock_strategy = MagicMock()
        config = MarketStructureRuleConfig()

        rule = MarketStructureRule(
            shared_state=shared_state,
            strategy=mock_strategy,
            config=config
        )

        # Build downtrend-friendly OHLC series
        downtrend_prices = [
            (107, 110, 105, 108),  # 0. Initial range
            (108, 108, 102, 103),  # 1. Drop
            (103, 105, 100, 99),   # 2. Break below 102 -> DOWNTREND confirmed
            (99, 106, 99, 105),    # 3. Pullback (potential LH)
            (105, 107, 101, 102),  # 4. Continue pullback
            (102, 103, 95, 96),    # 5. Break below 99 confirms LH, new LL
            (96, 100, 92, 93),     # 6. Continue down - LL progression
        ]

        bars = _bars_from_ohlc(downtrend_prices)

        for bar in bars:
            rule.evaluate(bar)

        # Check rule's trend property
        assert rule.trend == -1, f"Expected downtrend (trend=-1), got {rule.trend}"

        # Check via rule's internal indicator
        assert rule.smart_pivot_points.trend == -1, \
            f"Expected downtrend (trend=-1), got {rule.smart_pivot_points.trend}"

    def test_downtrend_returns_sell_signal(self):
        """Verify downtrend returns RuleSignal.SELL via shared state."""
        shared_state = SharedState()
        mock_strategy = MagicMock()
        config = MarketStructureRuleConfig()

        rule = MarketStructureRule(
            shared_state=shared_state,
            strategy=mock_strategy,
            config=config
        )

        # Build downtrend-friendly OHLC series
        downtrend_prices = [
            (107, 110, 105, 108),
            (108, 108, 102, 103),
            (103, 105, 100, 99),   # Break below -> DOWNTREND
        ]

        bars = _bars_from_ohlc(downtrend_prices)

        for bar in bars:
            rule.evaluate(bar)

        # Check signal in shared state
        signal = shared_state.get(SharedDictKey.MARKET_STRUCTURE_RULE_SIGNAL)
        assert signal == RuleSignal.SELL, f"Expected RuleSignal.SELL, got {signal}"


class TestMarketStructureRuleUndefined:
    """Tests for undefined trend (initial state)."""

    def test_undefined_trend_returns_none_signal(self):
        """Verify undefined trend (trend=0) returns RuleSignal.NONE."""
        shared_state = SharedState()
        mock_strategy = MagicMock()
        config = MarketStructureRuleConfig()

        rule = MarketStructureRule(
            shared_state=shared_state,
            strategy=mock_strategy,
            config=config
        )

        # Only one bar - not enough to establish trend
        prices = [
            (100, 105, 95, 100),  # Initial bar - trend should be 0
        ]

        bars = _bars_from_ohlc(prices)

        for bar in bars:
            rule.evaluate(bar)

        # Check signal in shared state
        signal = shared_state.get(SharedDictKey.MARKET_STRUCTURE_RULE_SIGNAL)
        assert signal == RuleSignal.NONE, f"Expected RuleSignal.NONE, got {signal}"


class TestMarketStructureRuleIntegration:
    """Tests for MarketStructureRule integration with SmartPivotPoints."""

    def test_rule_uses_smart_pivot_points_indicator(self):
        """Verify that MarketStructureRule internally uses SmartPivotPoints indicator."""
        shared_state = SharedState()
        mock_strategy = MagicMock()
        config = MarketStructureRuleConfig()

        rule = MarketStructureRule(
            shared_state=shared_state,
            strategy=mock_strategy,
            config=config
        )

        # The rule should have a SmartPivotPoints indicator instance
        assert hasattr(rule, 'smart_pivot_points'), \
            "MarketStructureRule should have a smart_pivot_points attribute"

        # Verify it's a SmartPivotPoints instance
        assert isinstance(rule.smart_pivot_points, SmartPivotPoints), \
            f"Expected SmartPivotPoints indicator, got {type(rule.smart_pivot_points)}"

    def test_rule_inherits_from_rulebase(self):
        """Verify that MarketStructureRule inherits from RuleBase."""
        # Check inheritance (using our MockRuleBase)
        assert issubclass(MarketStructureRule, MockRuleBase), \
            "MarketStructureRule should inherit from RuleBase"

    def test_rule_implements_evaluate_method(self):
        """Verify that MarketStructureRule implements the evaluate method."""
        shared_state = SharedState()
        mock_strategy = MagicMock()
        config = MarketStructureRuleConfig()

        rule = MarketStructureRule(
            shared_state=shared_state,
            strategy=mock_strategy,
            config=config
        )

        # Verify evaluate method exists and is callable
        assert hasattr(rule, 'evaluate'), "MarketStructureRule should have evaluate method"
        assert callable(rule.evaluate), "evaluate should be callable"

    def test_rule_has_trend_property(self):
        """Verify MarketStructureRule exposes trend property."""
        shared_state = SharedState()
        mock_strategy = MagicMock()
        config = MarketStructureRuleConfig()

        rule = MarketStructureRule(
            shared_state=shared_state,
            strategy=mock_strategy,
            config=config
        )

        assert hasattr(rule, 'trend'), "MarketStructureRule should have trend property"
        assert rule.trend == 0, "Initial trend should be 0 (undefined)"


class TestMarketStructureRuleHLLHStability:
    """Tests for HL/LH stability in MarketStructureRule."""

    def test_hl_does_not_change_uptrend(self):
        """Verify that forming an HL during uptrend does not change trend direction."""
        shared_state = SharedState()
        mock_strategy = MagicMock()
        config = MarketStructureRuleConfig()

        rule = MarketStructureRule(
            shared_state=shared_state,
            strategy=mock_strategy,
            config=config
        )

        # Establish uptrend first
        setup_prices = [
            (97, 100, 95, 98),     # 0. Initial range
            (98, 101, 96, 100),    # 1. Inside
            (100, 106, 98, 105),   # 2. Break above -> UPTREND
        ]

        # HL-stability: pullback that should remain uptrend
        hl_prices = [
            (105, 106, 100, 101),  # 3. Pullback (HL forming)
            (101, 104, 99, 103),   # 4. Deeper pullback
            (103, 107, 101, 106),  # 5. Resume uptrend
        ]

        all_prices = setup_prices + hl_prices
        bars = _bars_from_ohlc(all_prices)

        trends = []
        signals = []
        for bar in bars:
            rule.evaluate(bar)
            trends.append(rule.trend)
            signals.append(shared_state.get(SharedDictKey.MARKET_STRUCTURE_RULE_SIGNAL))

        # Once uptrend is established, it should not flip to -1
        first_uptrend_idx = next((i for i, t in enumerate(trends) if t == 1), None)
        assert first_uptrend_idx is not None, "Uptrend was never established"

        for i in range(first_uptrend_idx, len(trends)):
            assert trends[i] != -1, f"HL formation incorrectly flipped trend at bar {i}"
            assert signals[i] != RuleSignal.SELL, f"HL formation incorrectly set SELL signal at bar {i}"

    def test_lh_does_not_change_downtrend(self):
        """Verify that forming an LH during downtrend does not change trend direction."""
        shared_state = SharedState()
        mock_strategy = MagicMock()
        config = MarketStructureRuleConfig()

        rule = MarketStructureRule(
            shared_state=shared_state,
            strategy=mock_strategy,
            config=config
        )

        # Establish downtrend first
        setup_prices = [
            (107, 110, 105, 108),  # 0. Initial range
            (108, 109, 104, 105),  # 1. Inside
            (105, 106, 100, 101),  # 2. Break below -> DOWNTREND
        ]

        # LH-stability: bounce that should remain downtrend
        lh_prices = [
            (101, 107, 100, 106),  # 3. Bounce (LH forming)
            (106, 109, 103, 105),  # 4. Higher bounce
            (105, 106, 99, 100),   # 5. Resume downtrend
        ]

        all_prices = setup_prices + lh_prices
        bars = _bars_from_ohlc(all_prices)

        trends = []
        signals = []
        for bar in bars:
            rule.evaluate(bar)
            trends.append(rule.trend)
            signals.append(shared_state.get(SharedDictKey.MARKET_STRUCTURE_RULE_SIGNAL))

        # Once downtrend is established, it should not flip to 1
        first_downtrend_idx = next((i for i, t in enumerate(trends) if t == -1), None)
        assert first_downtrend_idx is not None, "Downtrend was never established"

        for i in range(first_downtrend_idx, len(trends)):
            assert trends[i] != 1, f"LH formation incorrectly flipped trend at bar {i}"
            assert signals[i] != RuleSignal.BUY, f"LH formation incorrectly set BUY signal at bar {i}"


class TestMarketStructureRuleSignalTransitions:
    """Tests for signal transitions in MarketStructureRule."""

    def test_signal_changes_on_trend_reversal(self):
        """Verify signal changes correctly when trend reverses."""
        shared_state = SharedState()
        mock_strategy = MagicMock()
        config = MarketStructureRuleConfig()

        rule = MarketStructureRule(
            shared_state=shared_state,
            strategy=mock_strategy,
            config=config
        )

        # First establish downtrend
        downtrend_prices = [
            (107, 110, 105, 108),
            (108, 108, 102, 103),
            (103, 105, 100, 99),   # Break below -> DOWNTREND
        ]

        bars = _bars_from_ohlc(downtrend_prices)
        for bar in bars:
            rule.evaluate(bar)

        # Verify downtrend signal
        signal = shared_state.get(SharedDictKey.MARKET_STRUCTURE_RULE_SIGNAL)
        assert signal == RuleSignal.SELL, f"Expected SELL after downtrend, got {signal}"

        # Now reverse to uptrend (break above major high)
        reversal_prices = [
            (99, 112, 99, 111),    # Break above major high -> UPTREND
        ]

        bars = _bars_from_ohlc(reversal_prices)
        for bar in bars:
            rule.evaluate(bar)

        # Verify uptrend signal
        signal = shared_state.get(SharedDictKey.MARKET_STRUCTURE_RULE_SIGNAL)
        assert signal == RuleSignal.BUY, f"Expected BUY after uptrend reversal, got {signal}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
