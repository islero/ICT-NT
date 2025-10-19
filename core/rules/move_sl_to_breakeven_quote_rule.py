from __future__ import annotations
from typing import Dict
from nautilus_trader.model.instruments import Instrument
from nautilus_trader.model.orders import Order
from nautilus_trader.trading import Strategy
from nautilus_trader.model import Bar, QuoteTick
from nautilus_trader.model.identifiers import ClientOrderId, InstrumentId
from core.rules.quote_tick_rule_base import QuoteTickRuleBase
from core.constants import SharedDictKeyBase
from core import SharedState

class MoveStopLossToBreakevenQuoteRule(QuoteTickRuleBase):
    def __init__(self, shared_state: SharedState,
                 strategy: Strategy,
                 instrument_id: InstrumentId,
                 take_profit_percentage: float) -> None:
        super().__init__()
        self.shared_state: SharedState = shared_state
        self.strategy: Strategy = strategy
        self.instrument_id: InstrumentId = instrument_id
        self.take_profit_percentage: float = take_profit_percentage

        self.__moved_to_be: Dict[ClientOrderId, bool] = {}

    def evaluate(self, bar: Bar, current_bar: Bar = None) -> bool:
        """
        Evaluate rule for bars
        """
        if not current_bar:
            return False

        self.__handle_move_to_breakeven(current_bar.low, current_bar.high)
        return True

    def quote_tick_evaluate(self, tick: QuoteTick) -> bool:
        """Evaluate rule for quote ticks"""
        if not tick.ask_price or not tick.bid_price:
            return False

        self.__handle_move_to_breakeven(tick.bid_price, tick.ask_price)
        return True

    def __handle_move_to_breakeven(self, lowest_price: float, highest_price: float) -> bool:
        # Load orders from shared_state
        orders_list = self.shared_state.get(SharedDictKeyBase.ORDERS, [])
        if not orders_list:
            return False

        open_order_ids: set[ClientOrderId] = set()

        for orders in orders_list:
            entry_order:Order = orders.get(SharedDictKeyBase.ENTRY_ORDER)
            order_id:ClientOrderId = entry_order.client_order_id
            open_order_ids.add(order_id)

            moved_to_be:bool = self.__moved_to_be.get(order_id, False)

            if moved_to_be:
                continue

            entry_price: float = entry_order.avg_px

            if not self.__need_to_move_to_be(entry_order, lowest_price, highest_price, entry_price):
                continue

            sl_order: Order = orders.get(SharedDictKeyBase.SL_ORDER)
            sl_order_id:ClientOrderId = sl_order.client_order_id

            updated_sl_order = self.strategy.cache.order(sl_order_id)
            if updated_sl_order is None:
                continue

            instrument: Instrument = self.strategy.cache.instrument(self.instrument_id)
            breakeven_price = instrument.make_price(entry_price)

            try:
                self.strategy.modify_order(updated_sl_order, trigger_price=breakeven_price)
                self.__moved_to_be[order_id] = True
            except Exception as exc:
                self.strategy.log.error(f"Move SL to BE is failed: {exc}")
                continue

        self.__cleanup_be_state(open_order_ids)

        return True

    def __need_to_move_to_be(
            self,
            entry_order:Order,
            lowest_price: float,
            highest_price: float,
            entry_price: float) -> bool:
        percentage = self.take_profit_percentage / 100
        if not entry_order.is_closed:
            return False

        if entry_order.is_buy:
            level = entry_price + (entry_price * percentage)
            return highest_price >= level

        if entry_order.is_sell:
            level = entry_price - (entry_price * percentage)
            return lowest_price <= level

        return False

    def __cleanup_be_state(self, open_order_ids: set[ClientOrderId]) -> None:
        """
        Remove the cached be for orders that are no longer open.
        """
        # Build deletion lists to avoid mutating while iterating
        to_del_bes = [cid for cid in self.__moved_to_be.keys() if cid not in open_order_ids]
        for cid in to_del_bes:
            del self.__moved_to_be[cid]