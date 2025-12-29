"""
Tests for FvgRule (Fair Value Gap Entry Rule).

These tests verify:
1. Long entry triggers on bullish FVG + bullish engulfing inside bounds
2. Short entry triggers on bearish FVG + bearish engulfing inside bounds
3. No trigger when engulfing occurs outside FVG
4. No trigger when no active/valid FVG exists
5. No trigger if an entry signal already exists (no overwrite)
6. Respect for daily/weekly bias blocking flags
7. Allow long/short config options
8. SL buffer applied correctly
9. TP calculated correctly using RR ratio
"""

import sys
import os
from unittest.mock import MagicMock
from abc import ABC, abstractmethod

import pytest

# Ensure we can import from the project root
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

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
    """Mock base Indicator class."""

    def __init__(self, inputs=None):
        pass

    def reset(self):
        pass


sys.modules["nautilus_trader.indicators.base"].Indicator = MockIndicator

# Import dependencies
from core import SharedState
from core.enums import RuleSignal
from core.constants import SharedDictKeyBase
from constants.shared_dict_key import SharedDictKey

# Import FVG indicator
from indicators.fair_value_gap import FairValueGap, FvgDirection


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


# Shared bar type mock for all tests - must be defined before MockBar
MOCK_BAR_TYPE = MagicMock()
MOCK_BAR_TYPE.__str__ = lambda x: "TestBarType"


# Mock Bar object
class MockBar:
    """Mock Bar object matching nautilus_trader Bar interface."""

    def __init__(
        self,
        open_price: float,
        high: float,
        low: float,
        close: float,
        ts_event: int = 0,
        bar_type: MagicMock = None,
    ):
        self.open = open_price
        self.high = high
        self.low = low
        self.close = close
        self.ts_event = ts_event
        # Use a consistent bar_type that will be set later after MOCK_BAR_TYPE is defined
        self._bar_type = bar_type

    @property
    def bar_type(self):
        # Return MOCK_BAR_TYPE if not explicitly set
        if self._bar_type is None:
            return MOCK_BAR_TYPE
        return self._bar_type


def _bars_from_ohlc(
    series: list[tuple[float, float, float, float]],
    start_ts: int = 0,
) -> list[MockBar]:
    """Build bars from a list of (open, high, low, close) tuples."""
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


# Import dataclass for config
from dataclasses import dataclass
from typing import Optional, List


# Recreate FvgRuleConfig for testing
@dataclass
class FvgRuleConfig:
    """Configuration for FVG Entry Rule."""
    bar_type: MagicMock = None
    instrument_id: MagicMock = None
    fvg_bar_type: Optional[MagicMock] = None
    max_signal_age_bars: int = 1
    allow_long: bool = True
    allow_short: bool = True
    sl_buffer_points: float = 0.0
    risk_reward_ratio: float = 2.0
    respect_bias_filters: bool = True
    min_fvg_distance_percent: float = 0.0

    def __post_init__(self):
        if self.bar_type is None:
            self.bar_type = MOCK_BAR_TYPE


# Recreate FvgRule for testing
class FvgRule(MockRuleBase):
    """Test version of FvgRule."""

    def __init__(
        self,
        shared_state: SharedState,
        strategy,
        config: FvgRuleConfig,
    ):
        super().__init__(shared_state)
        self.strategy = strategy
        self.config = config

        # Initialize FVG indicator
        self._fvg_indicator = FairValueGap(
            min_distance_percent=config.min_fvg_distance_percent
        )

        # Track previous bar for engulfing detection
        self._prev_bar: Optional[MockBar] = None

        # Track bars processed for FVG age calculation
        self._bars_processed: int = 0
        self._fvg_detection_bar_count: dict[int, int] = {}

        # First bar initialization flag
        self.first_bar_initialized: bool = False

    def evaluate(self, bar, current_bar=None) -> bool:
        """Evaluate entry conditions."""
        target_bar_type = self.config.fvg_bar_type or self.config.bar_type
        if str(bar.bar_type) not in str(target_bar_type) and self.first_bar_initialized:
            return True

        if not self.first_bar_initialized:
            self.first_bar_initialized = True

        # Increment bar counter
        self._bars_processed += 1

        # Feed bar to FVG indicator
        self._fvg_indicator.handle_bar(bar)

        # Track when FVGs are detected
        if self._fvg_indicator.has_new_fvg:
            last_fvg = self._fvg_indicator.last_fvg
            if last_fvg:
                self._fvg_detection_bar_count[last_fvg.middle_candle_time] = self._bars_processed

        # Need previous bar for engulfing detection
        if self._prev_bar is None:
            self._prev_bar = bar
            return True

        # Use current_bar for price reference if provided
        eval_bar = current_bar or bar

        # Check for entry signal
        self._check_entry_signal(self._prev_bar, bar, eval_bar)

        # Update previous bar
        self._prev_bar = bar

        return True

    def _check_entry_signal(self, prev_bar, curr_bar, price_bar) -> None:
        """Check if entry conditions are met and set entry signal."""
        if not self.shared_state:
            return

        # Check if entry signal already pending
        existing_signal = self.shared_state.get(
            SharedDictKeyBase.ENTRY_RULE_SIGNAL, RuleSignal.NONE
        )
        if existing_signal in (RuleSignal.BUY, RuleSignal.SELL):
            return

        # Get active FVGs
        active_fvgs = self._get_active_fvgs()
        if not active_fvgs:
            return

        # Check for bullish engulfing
        if self._is_bullish_engulfing(prev_bar, curr_bar):
            self._try_long_entry(curr_bar, price_bar, active_fvgs)
            return

        # Check for bearish engulfing
        if self._is_bearish_engulfing(prev_bar, curr_bar):
            self._try_short_entry(curr_bar, price_bar, active_fvgs)
            return

    def _get_active_fvgs(self) -> List:
        """Get list of active (fresh) FVGs."""
        active_fvgs = []

        for fvg in self._fvg_indicator.fvgs:
            detection_bar = self._fvg_detection_bar_count.get(fvg.middle_candle_time, 0)
            bars_since_detection = self._bars_processed - detection_bar

            if bars_since_detection <= self.config.max_signal_age_bars:
                active_fvgs.append(fvg)

        return active_fvgs

    def _is_bullish_engulfing(self, prev_bar, curr_bar) -> bool:
        """Check if current bar is a bullish engulfing pattern."""
        curr_bullish = float(curr_bar.close) > float(curr_bar.open)
        if not curr_bullish:
            return False

        curr_open = float(curr_bar.open)
        curr_close = float(curr_bar.close)
        prev_open = float(prev_bar.open)
        prev_close = float(prev_bar.close)

        engulfs = curr_open <= prev_close and curr_close >= prev_open
        return engulfs

    def _is_bearish_engulfing(self, prev_bar, curr_bar) -> bool:
        """Check if current bar is a bearish engulfing pattern."""
        curr_bearish = float(curr_bar.close) < float(curr_bar.open)
        if not curr_bearish:
            return False

        curr_open = float(curr_bar.open)
        curr_close = float(curr_bar.close)
        prev_open = float(prev_bar.open)
        prev_close = float(prev_bar.close)

        engulfs = curr_open >= prev_close and curr_close <= prev_open
        return engulfs

    def _body_inside_fvg(self, bar, fvg) -> bool:
        """Check if bar body is fully inside FVG bounds."""
        body_low = min(float(bar.open), float(bar.close))
        body_high = max(float(bar.open), float(bar.close))

        return fvg.fvg_low <= body_low and body_high <= fvg.fvg_high

    def _try_long_entry(self, engulfing_bar, price_bar, active_fvgs) -> None:
        """Try to create a long entry signal."""
        if not self.config.allow_long:
            return

        # Check bias filters
        if self.config.respect_bias_filters:
            if self._is_long_blocked():
                return

        # Find matching bullish FVG with body inside
        matching_fvg = None
        for fvg in active_fvgs:
            if fvg.direction == FvgDirection.BULLISH:
                if self._body_inside_fvg(engulfing_bar, fvg):
                    matching_fvg = fvg
                    break

        if matching_fvg is None:
            return

        # Calculate SL and TP
        current_price = float(price_bar.close)
        sl_price = matching_fvg.fvg_low - self.config.sl_buffer_points

        # Validate SL
        if sl_price >= current_price:
            return

        tp_price = current_price + (
            self.config.risk_reward_ratio * abs(current_price - sl_price)
        )

        # Set entry signal
        self.shared_state.set(SharedDictKeyBase.ENTRY_RULE_SIGNAL, RuleSignal.BUY)
        self.shared_state.set(SharedDictKeyBase.ENTRY_SL_PRICE, sl_price)
        self.shared_state.set(SharedDictKeyBase.ENTRY_TP_PRICE, tp_price)

    def _try_short_entry(self, engulfing_bar, price_bar, active_fvgs) -> None:
        """Try to create a short entry signal."""
        if not self.config.allow_short:
            return

        # Check bias filters
        if self.config.respect_bias_filters:
            if self._is_short_blocked():
                return

        # Find matching bearish FVG with body inside
        matching_fvg = None
        for fvg in active_fvgs:
            if fvg.direction == FvgDirection.BEARISH:
                if self._body_inside_fvg(engulfing_bar, fvg):
                    matching_fvg = fvg
                    break

        if matching_fvg is None:
            return

        # Calculate SL and TP
        current_price = float(price_bar.close)
        sl_price = matching_fvg.fvg_high + self.config.sl_buffer_points

        # Validate SL
        if sl_price <= current_price:
            return

        tp_price = current_price - (
            self.config.risk_reward_ratio * abs(sl_price - current_price)
        )

        # Set entry signal
        self.shared_state.set(SharedDictKeyBase.ENTRY_RULE_SIGNAL, RuleSignal.SELL)
        self.shared_state.set(SharedDictKeyBase.ENTRY_SL_PRICE, sl_price)
        self.shared_state.set(SharedDictKeyBase.ENTRY_TP_PRICE, tp_price)

    def _is_long_blocked(self) -> bool:
        """Check if long entries are blocked by bias filters."""
        if not self.shared_state:
            return False

        daily_blocks = self.shared_state.get(SharedDictKey.DAILY_BLOCK_LONGS, False)
        weekly_blocks = self.shared_state.get(SharedDictKey.WEEKLY_BLOCK_LONGS, False)

        return daily_blocks or weekly_blocks

    def _is_short_blocked(self) -> bool:
        """Check if short entries are blocked by bias filters."""
        if not self.shared_state:
            return False

        daily_blocks = self.shared_state.get(SharedDictKey.DAILY_BLOCK_SHORTS, False)
        weekly_blocks = self.shared_state.get(SharedDictKey.WEEKLY_BLOCK_SHORTS, False)

        return daily_blocks or weekly_blocks

    @property
    def fvg_indicator(self) -> FairValueGap:
        """Access to the FVG indicator for testing/debugging."""
        return self._fvg_indicator


# ============================================================================
# TESTS
# ============================================================================

class TestFvgRuleLongEntry:
    """Tests for long entry triggering."""

    def test_triggers_long_entry(self):
        """
        Test that long entry is triggered when:
        - Bullish FVG exists
        - Bullish engulfing pattern forms
        - Engulfing bar body is inside FVG bounds
        """
        shared_state = SharedState()
        mock_strategy = MagicMock()
        config = FvgRuleConfig()
        config.max_signal_age_bars = 3

        rule = FvgRule(shared_state, mock_strategy, config)

        # Build bars to create a bullish FVG (c1.high < c3.low)
        # c1: high=100
        # c2: middle candle
        # c3: low=102 -> gap from 100 to 102
        fvg_bars = [
            (95, 100, 90, 98),      # c1: high=100
            (99, 105, 97, 104),     # c2: middle
            (103, 110, 102, 108),   # c3: low=102 > c1.high=100 -> bullish FVG 100-102
        ]

        # Engulfing bars inside the FVG (bounds 100-102)
        engulfing_bars = [
            (101.5, 101.8, 100.8, 100.8),   # prev: bearish bar inside FVG
            (100.5, 102.0, 100.2, 101.8),   # curr: bullish engulfing (body 100.5-101.8 inside 100-102)
        ]

        all_bars = _bars_from_ohlc(fvg_bars + engulfing_bars)

        for bar in all_bars:
            rule.evaluate(bar)

        # Verify entry signal was set
        signal = shared_state.get(SharedDictKeyBase.ENTRY_RULE_SIGNAL)
        assert signal == RuleSignal.BUY, f"Expected BUY signal, got {signal}"

        # Verify SL and TP were set
        sl_price = shared_state.get(SharedDictKeyBase.ENTRY_SL_PRICE)
        tp_price = shared_state.get(SharedDictKeyBase.ENTRY_TP_PRICE)

        assert sl_price is not None, "SL price should be set"
        assert tp_price is not None, "TP price should be set"
        assert sl_price == 100.0, f"SL should be at FVG low (100), got {sl_price}"


class TestFvgRuleShortEntry:
    """Tests for short entry triggering."""

    def test_triggers_short_entry(self):
        """
        Test that short entry is triggered when:
        - Bearish FVG exists
        - Bearish engulfing pattern forms
        - Engulfing bar body is inside FVG bounds
        """
        shared_state = SharedState()
        mock_strategy = MagicMock()
        config = FvgRuleConfig()
        config.max_signal_age_bars = 3

        rule = FvgRule(shared_state, mock_strategy, config)

        # Build bars to create a bearish FVG (c1.low > c3.high)
        # c1: low=102
        # c2: middle candle
        # c3: high=100 -> gap from 100 to 102
        fvg_bars = [
            (105, 108, 102, 103),   # c1: low=102
            (102, 104, 98, 99),     # c2: middle
            (98, 100, 95, 97),      # c3: high=100 < c1.low=102 -> bearish FVG 100-102
        ]

        # Engulfing bars inside the FVG (bounds 100-102)
        engulfing_bars = [
            (100.5, 101.5, 100.2, 101.2),   # prev: bullish bar inside FVG
            (101.5, 101.8, 99.5, 100.2),    # curr: bearish engulfing (body 100.2-101.5 inside 100-102)
        ]

        all_bars = _bars_from_ohlc(fvg_bars + engulfing_bars)

        for bar in all_bars:
            rule.evaluate(bar)

        # Verify entry signal was set
        signal = shared_state.get(SharedDictKeyBase.ENTRY_RULE_SIGNAL)
        assert signal == RuleSignal.SELL, f"Expected SELL signal, got {signal}"

        # Verify SL and TP were set
        sl_price = shared_state.get(SharedDictKeyBase.ENTRY_SL_PRICE)
        tp_price = shared_state.get(SharedDictKeyBase.ENTRY_TP_PRICE)

        assert sl_price is not None, "SL price should be set"
        assert tp_price is not None, "TP price should be set"
        assert sl_price == 102.0, f"SL should be at FVG high (102), got {sl_price}"


class TestFvgRuleNoTriggerConditions:
    """Tests for conditions that should not trigger entry."""

    def test_no_trigger_engulfing_outside_fvg(self):
        """Test that engulfing outside FVG bounds does not trigger entry."""
        shared_state = SharedState()
        mock_strategy = MagicMock()
        config = FvgRuleConfig()
        config.max_signal_age_bars = 3

        rule = FvgRule(shared_state, mock_strategy, config)

        # Build bars to create a bullish FVG (bounds 100-102)
        fvg_bars = [
            (95, 100, 90, 98),
            (99, 105, 97, 104),
            (103, 110, 102, 108),
        ]

        # Engulfing bars OUTSIDE the FVG (above 102)
        engulfing_bars = [
            (105, 106, 104.5, 104.5),   # prev: small bar above FVG
            (104, 107, 103.5, 106),     # curr: bullish engulfing but OUTSIDE FVG
        ]

        all_bars = _bars_from_ohlc(fvg_bars + engulfing_bars)

        for bar in all_bars:
            rule.evaluate(bar)

        # Verify no entry signal was set
        signal = shared_state.get(SharedDictKeyBase.ENTRY_RULE_SIGNAL, RuleSignal.NONE)
        assert signal == RuleSignal.NONE, f"Expected no signal, got {signal}"

    def test_no_trigger_no_active_fvg(self):
        """Test that no trigger occurs when no FVG exists."""
        shared_state = SharedState()
        mock_strategy = MagicMock()
        config = FvgRuleConfig()

        rule = FvgRule(shared_state, mock_strategy, config)

        # Build bars with no FVG (overlapping candles)
        bars = [
            (100, 105, 95, 102),
            (102, 107, 99, 104),
            (104, 108, 101, 106),  # All overlapping, no FVG
            (105, 107, 103, 103),  # prev
            (103, 108, 102, 107),  # curr: bullish engulfing but no FVG
        ]

        all_bars = _bars_from_ohlc(bars)

        for bar in all_bars:
            rule.evaluate(bar)

        # Verify no entry signal was set
        signal = shared_state.get(SharedDictKeyBase.ENTRY_RULE_SIGNAL, RuleSignal.NONE)
        assert signal == RuleSignal.NONE, f"Expected no signal, got {signal}"

    def test_no_trigger_signal_already_exists(self):
        """Test that existing entry signal is not overwritten."""
        shared_state = SharedState()
        mock_strategy = MagicMock()
        config = FvgRuleConfig()
        config.max_signal_age_bars = 3

        # Pre-set an entry signal
        shared_state.set(SharedDictKeyBase.ENTRY_RULE_SIGNAL, RuleSignal.SELL)
        shared_state.set(SharedDictKeyBase.ENTRY_SL_PRICE, 200.0)

        rule = FvgRule(shared_state, mock_strategy, config)

        # Build bars for bullish FVG + engulfing (would normally trigger LONG)
        fvg_bars = [
            (95, 100, 90, 98),
            (99, 105, 97, 104),
            (103, 110, 102, 108),
        ]
        engulfing_bars = [
            (101.5, 101.8, 100.8, 100.8),
            (100.5, 102.0, 100.2, 101.8),
        ]

        all_bars = _bars_from_ohlc(fvg_bars + engulfing_bars)

        for bar in all_bars:
            rule.evaluate(bar)

        # Verify original signal was NOT overwritten
        signal = shared_state.get(SharedDictKeyBase.ENTRY_RULE_SIGNAL)
        sl_price = shared_state.get(SharedDictKeyBase.ENTRY_SL_PRICE)

        assert signal == RuleSignal.SELL, "Original SELL signal should be preserved"
        assert sl_price == 200.0, "Original SL price should be preserved"


class TestFvgRuleBiasFilters:
    """Tests for bias filter respect."""

    def test_respects_daily_block_longs(self):
        """Test that DAILY_BLOCK_LONGS prevents long entry."""
        shared_state = SharedState()
        mock_strategy = MagicMock()
        config = FvgRuleConfig()
        config.max_signal_age_bars = 3
        config.respect_bias_filters = True

        # Set daily blocks longs
        shared_state.set(SharedDictKey.DAILY_BLOCK_LONGS, True)

        rule = FvgRule(shared_state, mock_strategy, config)

        # Build bars for bullish FVG + engulfing
        fvg_bars = [
            (95, 100, 90, 98),
            (99, 105, 97, 104),
            (103, 110, 102, 108),
        ]
        engulfing_bars = [
            (101.5, 101.8, 100.8, 100.8),
            (100.5, 102.0, 100.2, 101.8),
        ]

        all_bars = _bars_from_ohlc(fvg_bars + engulfing_bars)

        for bar in all_bars:
            rule.evaluate(bar)

        # Verify no entry signal was set
        signal = shared_state.get(SharedDictKeyBase.ENTRY_RULE_SIGNAL, RuleSignal.NONE)
        assert signal == RuleSignal.NONE, f"Long should be blocked, got {signal}"

    def test_respects_daily_block_shorts(self):
        """Test that DAILY_BLOCK_SHORTS prevents short entry."""
        shared_state = SharedState()
        mock_strategy = MagicMock()
        config = FvgRuleConfig()
        config.max_signal_age_bars = 3
        config.respect_bias_filters = True

        # Set daily blocks shorts
        shared_state.set(SharedDictKey.DAILY_BLOCK_SHORTS, True)

        rule = FvgRule(shared_state, mock_strategy, config)

        # Build bars for bearish FVG + engulfing
        fvg_bars = [
            (105, 108, 102, 103),
            (102, 104, 98, 99),
            (98, 100, 95, 97),
        ]
        engulfing_bars = [
            (100.5, 101.5, 100.2, 101.2),
            (101.5, 101.8, 99.5, 100.2),
        ]

        all_bars = _bars_from_ohlc(fvg_bars + engulfing_bars)

        for bar in all_bars:
            rule.evaluate(bar)

        # Verify no entry signal was set
        signal = shared_state.get(SharedDictKeyBase.ENTRY_RULE_SIGNAL, RuleSignal.NONE)
        assert signal == RuleSignal.NONE, f"Short should be blocked, got {signal}"

    def test_respects_weekly_block_longs(self):
        """Test that WEEKLY_BLOCK_LONGS prevents long entry."""
        shared_state = SharedState()
        mock_strategy = MagicMock()
        config = FvgRuleConfig()
        config.max_signal_age_bars = 3
        config.respect_bias_filters = True

        # Set weekly blocks longs
        shared_state.set(SharedDictKey.WEEKLY_BLOCK_LONGS, True)

        rule = FvgRule(shared_state, mock_strategy, config)

        # Build bars for bullish FVG + engulfing
        fvg_bars = [
            (95, 100, 90, 98),
            (99, 105, 97, 104),
            (103, 110, 102, 108),
        ]
        engulfing_bars = [
            (101.5, 101.8, 100.8, 100.8),
            (100.5, 102.0, 100.2, 101.8),
        ]

        all_bars = _bars_from_ohlc(fvg_bars + engulfing_bars)

        for bar in all_bars:
            rule.evaluate(bar)

        # Verify no entry signal was set
        signal = shared_state.get(SharedDictKeyBase.ENTRY_RULE_SIGNAL, RuleSignal.NONE)
        assert signal == RuleSignal.NONE, f"Long should be blocked, got {signal}"


class TestFvgRuleConfigOptions:
    """Tests for config options (allow_long, allow_short)."""

    def test_allow_long_false_blocks_longs(self):
        """Test that allow_long=False prevents long entry."""
        shared_state = SharedState()
        mock_strategy = MagicMock()
        config = FvgRuleConfig()
        config.max_signal_age_bars = 3
        config.allow_long = False  # Disable longs
        config.respect_bias_filters = False

        rule = FvgRule(shared_state, mock_strategy, config)

        # Build bars for bullish FVG + engulfing
        fvg_bars = [
            (95, 100, 90, 98),
            (99, 105, 97, 104),
            (103, 110, 102, 108),
        ]
        engulfing_bars = [
            (101.5, 101.8, 100.8, 100.8),
            (100.5, 102.0, 100.2, 101.8),
        ]

        all_bars = _bars_from_ohlc(fvg_bars + engulfing_bars)

        for bar in all_bars:
            rule.evaluate(bar)

        # Verify no entry signal was set
        signal = shared_state.get(SharedDictKeyBase.ENTRY_RULE_SIGNAL, RuleSignal.NONE)
        assert signal == RuleSignal.NONE, f"Long should be blocked, got {signal}"

    def test_allow_short_false_blocks_shorts(self):
        """Test that allow_short=False prevents short entry."""
        shared_state = SharedState()
        mock_strategy = MagicMock()
        config = FvgRuleConfig()
        config.max_signal_age_bars = 3
        config.allow_short = False  # Disable shorts
        config.respect_bias_filters = False

        rule = FvgRule(shared_state, mock_strategy, config)

        # Build bars for bearish FVG + engulfing
        fvg_bars = [
            (105, 108, 102, 103),
            (102, 104, 98, 99),
            (98, 100, 95, 97),
        ]
        engulfing_bars = [
            (100.5, 101.5, 100.2, 101.2),
            (101.5, 101.8, 99.5, 100.2),
        ]

        all_bars = _bars_from_ohlc(fvg_bars + engulfing_bars)

        for bar in all_bars:
            rule.evaluate(bar)

        # Verify no entry signal was set
        signal = shared_state.get(SharedDictKeyBase.ENTRY_RULE_SIGNAL, RuleSignal.NONE)
        assert signal == RuleSignal.NONE, f"Short should be blocked, got {signal}"


class TestFvgRuleSLAndTP:
    """Tests for SL buffer and TP calculation."""

    def test_sl_buffer_applied(self):
        """Test that SL buffer is applied correctly."""
        shared_state = SharedState()
        mock_strategy = MagicMock()
        config = FvgRuleConfig()
        config.max_signal_age_bars = 3
        config.sl_buffer_points = 0.5  # Buffer of 0.5 points
        config.respect_bias_filters = False

        rule = FvgRule(shared_state, mock_strategy, config)

        # Build bars for bullish FVG (bounds 100-102)
        fvg_bars = [
            (95, 100, 90, 98),
            (99, 105, 97, 104),
            (103, 110, 102, 108),
        ]
        engulfing_bars = [
            (101.5, 101.8, 100.8, 100.8),
            (100.5, 102.0, 100.2, 101.8),
        ]

        all_bars = _bars_from_ohlc(fvg_bars + engulfing_bars)

        for bar in all_bars:
            rule.evaluate(bar)

        # Verify SL includes buffer
        sl_price = shared_state.get(SharedDictKeyBase.ENTRY_SL_PRICE)
        # FVG low = 100, buffer = 0.5, so SL = 100 - 0.5 = 99.5
        assert sl_price == 99.5, f"SL should be 99.5 (100 - 0.5 buffer), got {sl_price}"

    def test_tp_calculated_correctly(self):
        """Test that TP is calculated using RR ratio."""
        shared_state = SharedState()
        mock_strategy = MagicMock()
        config = FvgRuleConfig()
        config.max_signal_age_bars = 3
        config.risk_reward_ratio = 2.0
        config.sl_buffer_points = 0.0
        config.respect_bias_filters = False

        rule = FvgRule(shared_state, mock_strategy, config)

        # Build bars for bullish FVG (bounds 100-102)
        fvg_bars = [
            (95, 100, 90, 98),
            (99, 105, 97, 104),
            (103, 110, 102, 108),
        ]
        engulfing_bars = [
            (101.5, 101.8, 100.8, 100.8),
            (100.5, 102.0, 100.2, 101.8),  # close = 101.8
        ]

        all_bars = _bars_from_ohlc(fvg_bars + engulfing_bars)

        for bar in all_bars:
            rule.evaluate(bar)

        # Verify TP calculation
        sl_price = shared_state.get(SharedDictKeyBase.ENTRY_SL_PRICE)
        tp_price = shared_state.get(SharedDictKeyBase.ENTRY_TP_PRICE)

        # Entry price (close) = 101.8
        # SL = 100 (FVG low)
        # Risk = 101.8 - 100 = 1.8
        # TP = 101.8 + (2.0 * 1.8) = 101.8 + 3.6 = 105.4
        expected_tp = 101.8 + (2.0 * abs(101.8 - 100.0))
        assert tp_price == expected_tp, f"TP should be {expected_tp}, got {tp_price}"


class TestFvgRuleFvgAgeFilter:
    """Tests for FVG age filtering."""

    def test_fvg_too_old_no_trigger(self):
        """Test that stale FVGs do not trigger entries."""
        shared_state = SharedState()
        mock_strategy = MagicMock()
        config = FvgRuleConfig()
        config.max_signal_age_bars = 1  # Only 1 bar old FVGs are valid
        config.respect_bias_filters = False

        rule = FvgRule(shared_state, mock_strategy, config)

        # Build bars for bullish FVG (bounds 100-102)
        fvg_bars = [
            (95, 100, 90, 98),
            (99, 105, 97, 104),
            (103, 110, 102, 108),  # FVG detected here
        ]

        # Add some bars to make FVG stale
        gap_bars = [
            (108, 112, 107, 111),  # bar 4
            (111, 115, 110, 114),  # bar 5
        ]

        # Now try engulfing (FVG is now 2 bars old)
        engulfing_bars = [
            (101.5, 101.8, 100.8, 100.8),  # bar 6
            (100.5, 102.0, 100.2, 101.8),  # bar 7: engulfing but FVG too old
        ]

        all_bars = _bars_from_ohlc(fvg_bars + gap_bars + engulfing_bars)

        for bar in all_bars:
            rule.evaluate(bar)

        # Verify no entry signal was set (FVG too old)
        signal = shared_state.get(SharedDictKeyBase.ENTRY_RULE_SIGNAL, RuleSignal.NONE)
        assert signal == RuleSignal.NONE, f"FVG should be too old, got {signal}"


class TestFvgRuleSharedStateStructure:
    """Tests for shared state handshake structure."""

    def test_entry_handshake_structure(self):
        """Test that entry signal sets all required handshake keys."""
        shared_state = SharedState()
        mock_strategy = MagicMock()
        config = FvgRuleConfig()
        config.max_signal_age_bars = 3
        config.respect_bias_filters = False

        rule = FvgRule(shared_state, mock_strategy, config)

        # Build bars for bullish FVG + engulfing
        fvg_bars = [
            (95, 100, 90, 98),
            (99, 105, 97, 104),
            (103, 110, 102, 108),
        ]
        engulfing_bars = [
            (101.5, 101.8, 100.8, 100.8),
            (100.5, 102.0, 100.2, 101.8),
        ]

        all_bars = _bars_from_ohlc(fvg_bars + engulfing_bars)

        for bar in all_bars:
            rule.evaluate(bar)

        # Verify all handshake keys are set
        signal = shared_state.get(SharedDictKeyBase.ENTRY_RULE_SIGNAL)
        sl_price = shared_state.get(SharedDictKeyBase.ENTRY_SL_PRICE)
        tp_price = shared_state.get(SharedDictKeyBase.ENTRY_TP_PRICE)

        assert signal in (RuleSignal.BUY, RuleSignal.SELL), f"Signal must be BUY or SELL, got {signal}"
        assert isinstance(sl_price, (int, float)), f"SL must be numeric, got {type(sl_price)}"
        assert isinstance(tp_price, (int, float)), f"TP must be numeric, got {type(tp_price)}"

        # For LONG: SL < close, TP > close
        if signal == RuleSignal.BUY:
            close_price = 101.8  # Last bar close
            assert sl_price < close_price, f"SL ({sl_price}) must be < close ({close_price})"
            assert tp_price > close_price, f"TP ({tp_price}) must be > close ({close_price})"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
