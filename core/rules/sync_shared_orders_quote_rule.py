from typing import Any

from nautilus_trader.model import Bar, QuoteTick
from nautilus_trader.model.identifiers import ClientOrderId, InstrumentId
from nautilus_trader.model.orders import Order
from nautilus_trader.trading import Strategy

from core import SharedState
from core.constants import SharedDictKeyBase
from core.rules.quote_tick_rule_base import QuoteTickRuleBase


class SyncSharedOrdersQuoteRule(QuoteTickRuleBase):
    def __init__(self, shared_state: SharedState, strategy: Strategy, instrument_id: InstrumentId):
        super().__init__()
        self.strategy = strategy
        self.shared_state = shared_state
        self.instrument_id = instrument_id

    def evaluate(self, bar: Bar, current_bar: Bar = None) -> bool:
        """Check if the rule is satisfied."""
        # Verify the bar type is the lowest bar type
        if not current_bar:
            return False

        self.sync_orders()
        return True

    def quote_tick_evaluate(self, tick: QuoteTick) -> bool:
        """Check if the rule is satisfied for quote ticks."""
        if not tick:
            return False

        self.sync_orders()
        return True

    def sync_orders(self) -> bool:
        # Load orders from shared_state
        orders_list = self.shared_state.get(SharedDictKeyBase.ORDERS, [])
        if not orders_list:
            return False

        entry_orders_filled = True
        entry_orders: list[Order] = []
        for orders in orders_list:
            entry_order: Order = orders.get(SharedDictKeyBase.ENTRY_ORDER)
            if entry_order is None:
                entry_orders_filled = False
                continue
            entry_orders.append(entry_order)
            if not entry_order.is_closed:
                entry_orders_filled = False

        if not entry_orders_filled:
            return True

        open_positions = self.strategy.cache.positions_open()
        if not open_positions:
            if len(orders_list) > 0:
                orders_list.clear()

            open_orders = self.strategy.cache.orders_open()
            if open_orders and len(open_orders) > 0:
                self.strategy.cancel_all_orders(self.instrument_id)
            return True

        orders_to_remove: list[Any] = []
        for orders in orders_list:
            entry_order: Order = orders.get(SharedDictKeyBase.ENTRY_ORDER)
            entry_order_id: ClientOrderId = entry_order.client_order_id

            entry_order_exists = False
            for position in open_positions:
                if entry_order_id in position.client_order_ids:
                    entry_order_exists = True
                    break

            sl_order: Order = orders.get(SharedDictKeyBase.SL_ORDER)
            sl_order_id: ClientOrderId = sl_order.client_order_id

            tp_order: Order = orders.get(SharedDictKeyBase.TP_ORDER)
            tp_order_id: ClientOrderId = tp_order.client_order_id if tp_order else None

            if not entry_order_exists:
                updated_sl_order = self.strategy.cache.order(sl_order_id)
                if updated_sl_order is not None and updated_sl_order.is_open and not updated_sl_order.is_canceled:
                    self.strategy.cancel_order(updated_sl_order)

                if tp_order_id:
                    updated_tp_order = self.strategy.cache.order(tp_order_id)
                    if updated_tp_order is not None and updated_tp_order.is_open and not updated_tp_order.is_canceled:
                        self.strategy.cancel_order(updated_tp_order)

                orders_to_remove.append(orders)

            # check if sl is filled
            if sl_order.is_closed:
                orders_to_remove.append(orders)

        for order in reversed(orders_to_remove):
            try:
                orders_list.remove(order)
            except ValueError:
                pass

        return True
