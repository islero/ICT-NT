from __future__ import annotations

from nautilus_trader.model import Bar, InstrumentId, QuoteTick
from nautilus_trader.trading import Strategy

from core import SharedState
from core.constants import SharedDictKeyBase
from core.enums import MoneyManagementType, RuleSignal
from core.rules import EntryTradingRule, SyncSharedOrdersQuoteRule


class IctSmcStrategyRulesAdapter:
    """Thin adapter over shared, battle-tested order lifecycle rules."""

    def __init__(
        self,
        *,
        shared_state: SharedState,
        strategy: Strategy,
        instrument_id: InstrumentId,
        money_management_type: MoneyManagementType,
        fixed_lot: float,
        fixed_risk_percent: float,
        use_take_profit_order: bool,
    ) -> None:
        self.shared_state = shared_state
        self._sync_rule = SyncSharedOrdersQuoteRule(shared_state, strategy, instrument_id)
        self._entry_rule = EntryTradingRule(
            shared_state=shared_state,
            strategy=strategy,
            instrument_id=instrument_id,
            money_management_type=money_management_type,
            fixed_lot=fixed_lot,
            fixed_risk_percent=fixed_risk_percent,
            use_tp_order=use_take_profit_order,
        )

    def sync_orders(self) -> None:
        self._sync_rule.sync_orders()

    def sync_on_quote_tick(self, tick: QuoteTick) -> None:
        self._sync_rule.quote_tick_evaluate(tick)

    def has_active_order_groups(self) -> bool:
        groups = self.shared_state.get(SharedDictKeyBase.ORDERS, [])
        return isinstance(groups, list) and len(groups) > 0

    def clear_entry_intent(self) -> None:
        self.shared_state.set(SharedDictKeyBase.ENTRY_RULE_SIGNAL, RuleSignal.NONE)
        self.shared_state.set(SharedDictKeyBase.ENTRY_SL_PRICE, None)
        self.shared_state.set(SharedDictKeyBase.ENTRY_TP_PRICE, None)

    def submit_entry_with_brackets(self, *, signal: RuleSignal, stop_price: float, take_profit_price: float, bar: Bar) -> bool:
        self.shared_state.set(SharedDictKeyBase.ENTRY_RULE_SIGNAL, signal)
        self.shared_state.set(SharedDictKeyBase.ENTRY_SL_PRICE, stop_price)
        self.shared_state.set(SharedDictKeyBase.ENTRY_TP_PRICE, take_profit_price)

        try:
            return bool(self._entry_rule.evaluate(bar=bar, current_bar=bar))
        finally:
            # Prevent duplicate entries from sticky signals if downstream rule order changes.
            self.shared_state.set(SharedDictKeyBase.ENTRY_RULE_SIGNAL, RuleSignal.NONE)

