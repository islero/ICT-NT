from __future__ import annotations
from typing import Dict
from nautilus_trader.model.instruments import Instrument
from nautilus_trader.model.orders import Order, StopMarketOrder
from nautilus_trader.trading import Strategy
from nautilus_trader.model.identifiers import InstrumentId, ClientOrderId
from nautilus_trader.model import QuoteTick, Bar
from core import SharedState
from core.constants import SharedDictKeyBase
from core.rules.quote_tick_rule_base import QuoteTickRuleBase

class TrailingStopQuoteRule(QuoteTickRuleBase):
    def __init__(self, shared_state:SharedState,
                 strategy:Strategy,
                 instrument_id:InstrumentId,
                 distance_percentage: float,
                 step: float = 0.0,  # absolute price step required to move SL; 0 => move whenever better
                 enable_trailing_from_breakeven: bool = True) -> None:
        super().__init__()
        self.shared_state:SharedState = shared_state
        self.strategy:Strategy = strategy
        self.instrument_id:InstrumentId = instrument_id
        self.distance_percentage:float = distance_percentage
        self.step:float = step
        self.enable_trailing_from_breakeven:bool = enable_trailing_from_breakeven
        self.__sl_prices: Dict[ClientOrderId, float] = {}

    def evaluate(self, bar: Bar, current_bar: Bar = None) -> bool:
        """
        Evaluate rule for bars
        """
        if not current_bar:
            return False

        self.__handle_trailing_stop(current_bar.low, current_bar.high)
        return True

    def quote_tick_evaluate(self, tick: QuoteTick) -> bool:
        """Evaluate rule for quote ticks"""
        if not tick.ask_price or not tick.bid_price:
            return False

        self.__handle_trailing_stop(tick.bid_price, tick.ask_price)
        return True

    def __handle_trailing_stop(self, lowest_price: float, highest_price: float) -> bool:
        # Load orders from shared_state
        orders_list = self.shared_state.get(SharedDictKeyBase.ORDERS, [])
        if not orders_list:
            return False

        open_order_ids: set[ClientOrderId] = set()

        for orders in orders_list:
            entry_order: Order = orders.get(SharedDictKeyBase.ENTRY_ORDER)
            order_id: ClientOrderId = entry_order.client_order_id
            open_order_ids.add(order_id)
            sl_order: StopMarketOrder = orders.get(SharedDictKeyBase.SL_ORDER)

            entry_price: float = entry_order.avg_px
            instrument: Instrument = self.strategy.cache.instrument(self.instrument_id)
            normalized_entry_price = instrument.make_price(entry_price)

            sl_price: float = self.__sl_prices.get(order_id, sl_order.trigger_price)

            if not self.__is_trailing_allowed(entry_order.is_buy, entry_order.is_sell, normalized_entry_price, sl_price):
                continue

            desired_sl_price = self.__desired_trailing_stop(lowest_price, highest_price, entry_order)
            if not desired_sl_price:
                continue

            if not self.__can_use_new_sl(sl_price, desired_sl_price, entry_order):
                continue

            new_sl_price = instrument.make_price(desired_sl_price)

            updated_sl_order = self.strategy.cache.order(sl_order.client_order_id)
            if updated_sl_order is None:
                continue

            try:
                self.strategy.modify_order(updated_sl_order, trigger_price=new_sl_price)
                self.__sl_prices[order_id] = new_sl_price
            except Exception as exc:
                self.strategy.log.error(f"Trailing stop is failed: {exc}")
                continue

        self.__cleanup_sl_state(open_order_ids)

        return True

    def __is_trailing_allowed(self, is_buy:bool, is_sell:bool, entry_price:float, sl_price:float) -> bool:
        """Checks if the trailing stop is allowed"""
        if not self.enable_trailing_from_breakeven:
            return True

        if is_buy:
            return sl_price >= entry_price
        elif is_sell:
            return sl_price <= entry_price

        return False

    def __desired_trailing_stop(self, lowest_price: float, highest_price: float, entry_order:Order) -> float | None:
        """
        For LONG: SL = current * (1 - distance%)
        For SHORT: SL = current * (1 + distance%)
        """
        percentage = self.distance_percentage / 100
        if entry_order.is_buy:
            return highest_price * (1 - percentage)
        elif entry_order.is_sell:
            return lowest_price * (1 + percentage)
        return None

    def __can_use_new_sl(self, old_sl_price:float, new_sl_price:float, entry_order:Order) -> float | None:
        if entry_order.is_buy:
            move_percent:float = ((new_sl_price - old_sl_price) / old_sl_price) * 100.0
            return move_percent >= self.step
        elif entry_order.is_sell:
            move_percent = ((old_sl_price - new_sl_price) / old_sl_price) * 100.0
            return move_percent >= self.step
        return None

    def __cleanup_sl_state(self, open_order_ids: set[ClientOrderId]) -> None:
        """
        Remove the cached partial-close state for orders that are no longer open.
        Cleans up entries in __partials_count and __tps_base whose ClientOrderId
        is not present in `open_order_ids`.
        """
        # Build deletion lists to avoid mutating while iterating
        to_del_partials = [cid for cid in self.__sl_prices.keys() if cid not in open_order_ids]
        for cid in to_del_partials:
            del self.__sl_prices[cid]