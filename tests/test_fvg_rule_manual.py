import unittest
from unittest.mock import MagicMock
from decimal import Decimal
import pandas as pd
# Mocking Bar to avoid strict type requirements of Nautilus Trader C-ext classes
class MockBar:
    def __init__(self, bar_type, open_price, high, low, close_price, volume, ts_event, ts_init):
        self.bar_type = bar_type
        self.open = open_price
        self.high = high
        self.low = low
        self.close = close_price
        self.volume = volume
        self.ts_event = ts_event
        self.ts_init = ts_init

from nautilus_trader.model import BarType, InstrumentId
from nautilus_trader.model.enums import BarAggregation, PriceType

# Mock the SharedState and other dependencies
class MockSharedState:
    def __init__(self):
        self.state = {}
    
    def get(self, key, default=None):
        return self.state.get(key, default)
    
    def set(self, key, value):
        self.state[key] = value

import sys
import os

# Add project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from rules.fvg_rule import FvgRule, FvgRuleConfig
from core.constants import SharedDictKeyBase
from core.enums import RuleSignal

def create_bar(bar_type, close_price, open_price, high, low, ts):
    return MockBar(
        bar_type=bar_type,
        open_price=Decimal(open_price),
        high=Decimal(high),
        low=Decimal(low),
        close_price=Decimal(close_price),
        volume=Decimal(100),
        ts_event=ts,
        ts_init=ts,
    )

class TestFvgRule(unittest.TestCase):
    def setUp(self):
        self.shared_state = MockSharedState()
        self.strategy = MagicMock()
        self.instrument_id = InstrumentId.from_str("EURUSD.SIM")
        self.bar_type_1h = BarType.from_str("EURUSD.SIM-1-HOUR-LAST-EXTERNAL")
        self.bar_type_4h = BarType.from_str("EURUSD.SIM-4-HOUR-LAST-EXTERNAL")
        self.entry_bar_type = self.bar_type_1h # Entry on 1h bars

    def test_multi_timeframe_fvg(self):
        config = FvgRuleConfig(
            bar_type=self.entry_bar_type,
            instrument_id=self.instrument_id,
            fvg_bar_types=[self.bar_type_1h, self.bar_type_4h],
            safe_mode=False,
            sl_buffer_points=10.0,
            max_signal_age_bars=10
        )
        rule = FvgRule(self.shared_state, self.strategy, config)

        # 1. Create a Bullish FVG on 4h
        # c1: low=1.0000, high=1.0050
        # c2: low=1.0020, high=1.0080 (TS: 1000)
        # c3: low=1.0060, high=1.0100 -> FVG Low=1.0050, High=1.0060 (Gap=10 pips)
        ts_start = 1000
        c1_4h = create_bar(self.bar_type_4h, 1.0040, 1.0000, 1.0050, 1.0000, ts_start)
        c2_4h = create_bar(self.bar_type_4h, 1.0070, 1.0040, 1.0080, 1.0020, ts_start + 1)
        c3_4h = create_bar(self.bar_type_4h, 1.0090, 1.0070, 1.0100, 1.0060, ts_start + 2)

        rule.evaluate(c1_4h)
        rule.evaluate(c2_4h)
        rule.evaluate(c3_4h)

        # Verify FVG is detected in the 4h indicator
        self.assertTrue(rule.fvg_indicators[str(self.bar_type_4h)].last_fvg is not None)
        fvg = rule.fvg_indicators[str(self.bar_type_4h)].last_fvg
        self.assertEqual(float(fvg.fvg_low), 1.0050)
        self.assertEqual(float(fvg.fvg_high), 1.0060)

        # 2. Process Entry Bars (Bullish Engulfing inside FVG)
        # Prev Bar: Bearish, inside FVG
        prev_bar = create_bar(self.entry_bar_type, 1.0052, 1.0058, 1.0059, 1.0051, ts_start + 10)
        
        # Current Bar: Bullish, Engulfs prev, inside FVG
        # Open=1.0051 (<= prev.close), Close=1.0059 (>= prev.open)
        # Body low=1.0051, High=1.0059. Inside [1.0050, 1.0060]
        curr_bar = create_bar(self.entry_bar_type, 1.0059, 1.0051, 1.0060, 1.0050, ts_start + 11)

        rule.evaluate(prev_bar)
        rule.evaluate(curr_bar)

        # Check Signal
        signal = self.shared_state.get(SharedDictKeyBase.ENTRY_RULE_SIGNAL)
        self.assertEqual(signal, RuleSignal.BUY)

        # Check SL (Normal Mode -> Middle Candle Low)
        # Middle Candle (c2_4h) Low = 1.0020
        # Buffer = 10.0 ?? Wait, 10.0 is huge for these prices. 
        # But let's assume raw values. 1.0020 - 10.0 = -8.998. 
        # Ah, the logic uses raw subtraction: matching_fvg.c2.low - sl_buffer_points.
        # Let's check shared state value.
        sl_price = self.shared_state.get(SharedDictKeyBase.ENTRY_SL_PRICE)
        expected_sl = 1.0020 - 10.0
        self.assertAlmostEqual(sl_price, expected_sl)

    def test_safe_mode_sl(self):
        config = FvgRuleConfig(
            bar_type=self.entry_bar_type,
            instrument_id=self.instrument_id,
            fvg_bar_types=[self.bar_type_1h],
            safe_mode=True, # SAFE MODE
            sl_buffer_points=0.0001,
            max_signal_age_bars=10
        )
        rule = FvgRule(self.shared_state, self.strategy, config)

        # Create Bullish FVG
        # c1: Low=1.0000 -> Safe SL should be here
        ts_start = 2000
        c1 = create_bar(self.bar_type_1h, 1.0040, 1.0010, 1.0050, 1.0000, ts_start)
        c2 = create_bar(self.bar_type_1h, 1.0070, 1.0040, 1.0080, 1.0020, ts_start + 1)
        c3 = create_bar(self.bar_type_1h, 1.0090, 1.0070, 1.0100, 1.0060, ts_start + 2)
        # FVG: 1.0050 - 1.0060

        rule.evaluate(c1)
        rule.evaluate(c2)
        rule.evaluate(c3)

        # Trigger Entry
        prev_bar = create_bar(self.entry_bar_type, 1.0052, 1.0055, 1.0056, 1.0051, ts_start + 5)
        curr_bar = create_bar(self.entry_bar_type, 1.0058, 1.0051, 1.0059, 1.0050, ts_start + 6)
        
        rule.evaluate(prev_bar)
        rule.evaluate(curr_bar)

        # Check Signal
        self.assertEqual(self.shared_state.get(SharedDictKeyBase.ENTRY_RULE_SIGNAL), RuleSignal.BUY)
        
        # Check Safe SL (First Candle Low)
        # c1.low = 1.0000
        sl_price = self.shared_state.get(SharedDictKeyBase.ENTRY_SL_PRICE)
        expected_sl = 1.0000 - 0.0001
        self.assertAlmostEqual(sl_price, expected_sl)

    def test_duplicate_prevention(self):
        config = FvgRuleConfig(
            bar_type=self.entry_bar_type,
            instrument_id=self.instrument_id,
            fvg_bar_types=[self.bar_type_1h],
            safe_mode=False,
            max_signal_age_bars=10
        )
        rule = FvgRule(self.shared_state, self.strategy, config)

        # Create Bullish FVG
        ts_start = 3000
        c1 = create_bar(self.bar_type_1h, 1.0040, 1.0010, 1.0050, 1.0000, ts_start)
        c2 = create_bar(self.bar_type_1h, 1.0070, 1.0040, 1.0080, 1.0020, ts_start + 1)
        c3 = create_bar(self.bar_type_1h, 1.0090, 1.0070, 1.0100, 1.0060, ts_start + 2)
        
        rule.evaluate(c1)
        rule.evaluate(c2)
        rule.evaluate(c3)

        # Trigger First Entry
        prev_bar = create_bar(self.entry_bar_type, 1.0052, 1.0055, 1.0056, 1.0051, ts_start + 5)
        curr_bar = create_bar(self.entry_bar_type, 1.0058, 1.0051, 1.0059, 1.0050, ts_start + 6)
        
        rule.evaluate(prev_bar)
        rule.evaluate(curr_bar)

        self.assertEqual(self.shared_state.get(SharedDictKeyBase.ENTRY_RULE_SIGNAL), RuleSignal.BUY)
        
        # Clear signal from shared state to simulate trade taken
        self.shared_state.set(SharedDictKeyBase.ENTRY_RULE_SIGNAL, RuleSignal.NONE)

        # Trigger Second Entry (Same FVG)
        prev_bar_2 = create_bar(self.entry_bar_type, 1.0053, 1.0056, 1.0057, 1.0052, ts_start + 7)
        curr_bar_2 = create_bar(self.entry_bar_type, 1.0059, 1.0052, 1.0060, 1.0051, ts_start + 8)

        rule.evaluate(prev_bar_2)
        rule.evaluate(curr_bar_2)

        # Should NOT trigger again
        self.assertEqual(self.shared_state.get(SharedDictKeyBase.ENTRY_RULE_SIGNAL), RuleSignal.NONE)

if __name__ == '__main__':
    unittest.main()
