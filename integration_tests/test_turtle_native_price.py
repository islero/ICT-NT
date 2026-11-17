"""Run separately: python -m pytest integration_tests/test_turtle_native_price.py.

The legacy tests replace Nautilus modules with mocks in sys.modules; this
regression intentionally exercises actual Nautilus Price arithmetic.
"""
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nautilus_trader.model import Bar, BarType, Price, Quantity
from constants.shared_dict_key import SharedDictKey
from core import SharedState
from core.constants import SharedDictKeyBase
from core.enums import RuleSignal
from rules.entry_turtle_soup_rule import EntryTurtleSoupRule, EntryTurtleSoupRuleConfig


@pytest.mark.parametrize("signal,stop,expected", [(RuleSignal.BUY,95.0,110.0),(RuleSignal.SELL,105.0,90.0)])
def test_native_price_target_and_consumed_signal(signal,stop,expected):
    state=SharedState()
    state.set(SharedDictKey.TURTLE_SOUP_RULE_SIGNAL,signal)
    state.set(SharedDictKey.SMA_FILTER_SIGNAL,RuleSignal.BOTH)
    state.set(SharedDictKeyBase.ENTRY_SL_PRICE,stop)
    rule=EntryTurtleSoupRule(state,SimpleNamespace(),EntryTurtleSoupRuleConfig(2.0))
    bt=BarType.from_str("AAPL.XNAS-1-MINUTE-LAST-EXTERNAL")
    bar=Bar(bt,Price.from_str("100.00"),Price.from_str("101.00"),Price.from_str("99.00"),
            Price.from_str("100.00"),Quantity.from_int(1000),60_000_000_000,60_000_000_000)
    assert rule.evaluate(bar,bar)
    assert state.get(SharedDictKeyBase.ENTRY_TP_PRICE) == expected
    assert state.get(SharedDictKey.TURTLE_SOUP_RULE_SIGNAL) == RuleSignal.NONE
    assert not rule.evaluate(bar,bar)
