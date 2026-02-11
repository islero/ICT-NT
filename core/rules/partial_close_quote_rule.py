from __future__ import annotations

from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal
from typing import Dict

import pandas as pd
from nautilus_trader.model import Bar, QuoteTick
from nautilus_trader.model.enums import OrderSide
from nautilus_trader.model.identifiers import ClientOrderId, InstrumentId
from nautilus_trader.model.instruments import Instrument
from nautilus_trader.model.orders import Order
from nautilus_trader.trading import Strategy

from core import SharedState
from core.constants import SharedDictKeyBase
from core.rules.quote_tick_rule_base import QuoteTickRuleBase


class PartialCloseQuoteRule(QuoteTickRuleBase):
    def __init__(
        self,
        shared_state: SharedState,
        strategy: Strategy,
        instrument_id: InstrumentId,
        take_profit_percentage: float = 0.0,
        close_percentage: float = 100.0,
        max_partial_close_count: int = 1,
        use_fixed_tp_price: bool = False,
    ) -> None:
        super().__init__()
        self.shared_state: SharedState = shared_state
        self.strategy: Strategy = strategy
        self.instrument_id: InstrumentId = instrument_id
        self.take_profit_percentage: float = take_profit_percentage
        self.close_percentage: float = close_percentage
        self.max_partial_close_count: int = max_partial_close_count
        self.use_fixed_tp_price: bool = use_fixed_tp_price

        self.__tps_base: Dict[ClientOrderId, float] = {}
        self.__partials_count: Dict[ClientOrderId, int] = {}

    def evaluate(self, bar: Bar, current_bar: Bar = None) -> bool:
        """
        Evaluate rule for bars
        """
        if not current_bar:
            return False

        self.__handle_partial_closes(current_bar.low, current_bar.high)
        return True

    def quote_tick_evaluate(self, tick: QuoteTick) -> bool:
        """Evaluate rule for quote ticks"""
        if not tick.ask_price or not tick.bid_price:
            return False

        self.__handle_partial_closes(tick.bid_price, tick.ask_price)
        return True

    def __handle_partial_closes(self, lowest_price: float, highest_price: float) -> bool:
        # Load orders from shared_state
        orders_list = self.shared_state.get(SharedDictKeyBase.ORDERS, [])
        if not orders_list:
            return False

        open_order_ids: set[ClientOrderId] = set()

        for orders in orders_list:
            entry_order: Order = orders.get(SharedDictKeyBase.ENTRY_ORDER)
            order_id: ClientOrderId = entry_order.client_order_id
            open_order_ids.add(order_id)
            sl_order: Order = orders.get(SharedDictKeyBase.SL_ORDER)

            avg_px = entry_order.avg_px
            if avg_px is None:
                continue
            base_price: float = self.__tps_base.get(order_id) or avg_px

            # checking if we have reached the maximum number of partial closes
            partial_close_count: int = self.__partials_count.get(order_id, 0)
            if partial_close_count >= self.max_partial_close_count:
                continue

            now_ts = pd.Timestamp(self.strategy.clock.timestamp_ns(), tz="UTC", unit="ns")

            # checking if we need to close the position partially
            need_to_close, level = self.__need_to_close(entry_order, lowest_price, highest_price, base_price)

            if not need_to_close:
                continue

            # executing a partial close
            base_qty_dec: Decimal = entry_order.quantity.as_decimal()
            p_dec: Decimal = Decimal(str(self.close_percentage)) / Decimal("100")

            instrument: Instrument = self.strategy.cache.instrument(self.instrument_id)
            # Align all arithmetic to the instrument's quantity step to avoid double rounding
            step_dec: Decimal = instrument.min_quantity.as_decimal()

            # Handle 100% close case (full exit)
            if p_dec >= Decimal("1"):
                next_close_dec = base_qty_dec
                remaining_dec = Decimal("0")
            else:
                # Compute current quantity after n partial closes (geometric model) and align DOWN to step
                current_qty_dec_raw: Decimal = base_qty_dec * ((Decimal("1") - p_dec) ** partial_close_count)
                current_qty_dec: Decimal = (current_qty_dec_raw / step_dec).to_integral_value(
                    rounding=ROUND_FLOOR
                ) * step_dec

                # Split: take the next close as CEILING to step to ensure progress, remainder is exact difference
                half_dec: Decimal = current_qty_dec * p_dec
                next_close_dec: Decimal = (half_dec / step_dec).to_integral_value(rounding=ROUND_CEILING) * step_dec
                remaining_dec: Decimal = current_qty_dec - next_close_dec

                # Guard: if remaining becomes zero but we still have at least one step available, shift one step from close to remain
                if remaining_dec <= Decimal("0") and current_qty_dec >= step_dec:
                    next_close_dec = current_qty_dec - step_dec
                    remaining_dec = step_dec

            # Build Quantity objects from already step-aligned Decimals; make_qty won't change aligned values
            next_close_quantity = instrument.make_qty(next_close_dec)
            remaining_quantity = instrument.make_qty(remaining_dec)

            if not self.__execute_partial_close(
                next_close_quantity, remaining_quantity, sl_order.side, sl_order.client_order_id
            ):
                continue

            self.__partials_count[order_id] = self.__partials_count.get(order_id, 0) + 1
            self.__tps_base[order_id] = level

        self.__cleanup_partial_state(open_order_ids)

        return True

    def __need_to_close(
        self, entry_order: Order, lowest_price: float, highest_price: float, base_price: float
    ) -> tuple[bool, float]:
        """
        Decide whether to trigger a partial close and return the decision plus the target level.

        Returns:
            (need_to_close, level)
            - need_to_close: bool flag
            - level: float price level used for the decision
        """
        if not entry_order.is_closed:
            return False, 0

        # Use fixed tp_price from shared state if enabled
        if self.use_fixed_tp_price:
            tp_price = self.shared_state.get(SharedDictKeyBase.ENTRY_TP_PRICE, None)
            if tp_price is None:
                return False, 0

            level = float(tp_price)
            if entry_order.is_buy:
                return highest_price >= level, level
            if entry_order.is_sell:
                return lowest_price <= level, level
            return False, 0

        # Use percentage-based calculation
        percentage = self.take_profit_percentage / 100
        if entry_order.is_buy:
            level = base_price + (base_price * percentage)
            return highest_price >= level, level

        if entry_order.is_sell:
            level = base_price - (base_price * percentage)
            return lowest_price <= level, level

        return False, 0

    def __execute_partial_close(
        self,
        next_close_quantity: float,
        remaining_quantity: float,
        close_order_side: OrderSide,
        sl_order_id: ClientOrderId,
    ) -> bool:
        try:
            order = self.strategy.order_factory.market(
                instrument_id=self.instrument_id,
                order_side=close_order_side,
                quantity=next_close_quantity,
                reduce_only=True,
            )
            self.strategy.submit_order(order)

            sl_order = self.strategy.cache.order(sl_order_id)
            if sl_order is None:
                return False

            self.strategy.modify_order(sl_order, quantity=remaining_quantity)

            return True
        except Exception as exc:
            self.strategy.log.error(f"Executing of the partial close is failed: {exc}")
            return False

    def __cleanup_partial_state(self, open_order_ids: set[ClientOrderId]) -> None:
        """
        Remove the cached partial-close state for orders that are no longer open.
        Cleans up entries in __partials_count and __tps_base whose ClientOrderId
        is not present in `open_order_ids`.
        """
        # Build deletion lists to avoid mutating while iterating
        to_del_partials = [cid for cid in self.__partials_count.keys() if cid not in open_order_ids]
        for cid in to_del_partials:
            del self.__partials_count[cid]

        to_del_tps = [cid for cid in self.__tps_base.keys() if cid not in open_order_ids]
        for cid in to_del_tps:
            del self.__tps_base[cid]
