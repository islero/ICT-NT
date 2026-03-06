import os
import sys
import types
from unittest.mock import MagicMock

# Allow importing project modules
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# Minimal Nautilus mocks for importing adapter module without the runtime engine.
sys.modules.setdefault("nautilus_trader", MagicMock())
sys.modules.setdefault("nautilus_trader.model", MagicMock())
sys.modules.setdefault("nautilus_trader.trading", MagicMock())

from core import SharedState
from core.constants import SharedDictKeyBase
from core.enums import MoneyManagementType, RuleSignal


class _FakeEntryTradingRule:
    def __init__(self, shared_state, **kwargs):
        self.shared_state = shared_state
        self.calls = 0

    def evaluate(self, bar, current_bar=None):
        self.calls += 1
        signal = self.shared_state.get(SharedDictKeyBase.ENTRY_RULE_SIGNAL, RuleSignal.NONE)
        return signal in (RuleSignal.BUY, RuleSignal.SELL)


class _FakeSyncSharedOrdersQuoteRule:
    def __init__(self, *args, **kwargs):
        self.sync_calls = 0
        self.tick_calls = 0

    def sync_orders(self):
        self.sync_calls += 1
        return True

    def quote_tick_evaluate(self, tick):
        self.tick_calls += 1
        return True


def _import_adapter_with_fake_rules(monkeypatch):
    fake_rules = types.ModuleType("core.rules")
    fake_rules.EntryTradingRule = _FakeEntryTradingRule
    fake_rules.SyncSharedOrdersQuoteRule = _FakeSyncSharedOrdersQuoteRule
    monkeypatch.setitem(sys.modules, "core.rules", fake_rules)
    sys.modules.pop("strategies.ict_smc_strategy_rules_adapter", None)

    import importlib

    return importlib.import_module("strategies.ict_smc_strategy_rules_adapter")


def test_adapter_submit_entry_clears_signal_and_delegates(monkeypatch):
    adapter_module = _import_adapter_with_fake_rules(monkeypatch)

    shared_state = SharedState()
    adapter = adapter_module.IctSmcStrategyRulesAdapter(
        shared_state=shared_state,
        strategy=MagicMock(),
        instrument_id="ESU5.GLBX",
        money_management_type=MoneyManagementType.FIXED_LOT,
        fixed_lot=1.0,
        fixed_risk_percent=1.0,
        use_take_profit_order=True,
    )

    ok = adapter.submit_entry_with_brackets(
        signal=RuleSignal.BUY,
        stop_price=100.0,
        take_profit_price=110.0,
        bar=MagicMock(),
    )

    assert ok is True
    assert shared_state.get(SharedDictKeyBase.ENTRY_RULE_SIGNAL) == RuleSignal.NONE
    assert adapter._entry_rule.calls == 1


def test_adapter_tracks_active_order_groups(monkeypatch):
    adapter_module = _import_adapter_with_fake_rules(monkeypatch)

    shared_state = SharedState()
    adapter = adapter_module.IctSmcStrategyRulesAdapter(
        shared_state=shared_state,
        strategy=MagicMock(),
        instrument_id="ESU5.GLBX",
        money_management_type=MoneyManagementType.FIXED_LOT,
        fixed_lot=1.0,
        fixed_risk_percent=1.0,
        use_take_profit_order=True,
    )

    assert adapter.has_active_order_groups() is False
    shared_state.set(SharedDictKeyBase.ORDERS, [{"ENTRY_ORDER": "entry"}])
    assert adapter.has_active_order_groups() is True
