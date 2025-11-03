from decimal import Decimal
import pandas as pd
from nautilus_trader.risk.sizing import FixedRiskSizer
from typing import Optional
from nautilus_trader.model import Bar, Quantity, InstrumentId, ClientOrderId, Position
from nautilus_trader.model.instruments import Instrument
from nautilus_trader.trading import Strategy
from nautilus_trader.model.enums import OrderSide, TimeInForce, OmsType
from core import SharedState
from core.enums import MoneyManagementType
from core.enums.rule_signal import RuleSignal
from core.rules.rule_base import RuleBase
from core.constants import SharedDictKeyBase
from risk.my_fixed_risk_sizer import MyFixedRiskSizer


class EntryTradingRule(RuleBase):
    def __init__(self, shared_state: SharedState, strategy: Strategy, instrument_id: InstrumentId,
                 money_management_type: MoneyManagementType, fixed_lot: float, fixed_risk_percent: float):
        super().__init__(shared_state)
        self.strategy = strategy
        self.instrument_id = instrument_id
        self.money_management_type = money_management_type
        self.fixed_lot = fixed_lot
        self.fixed_risk_percent = fixed_risk_percent

    def evaluate(self, bar: Bar, current_bar: Bar = None) -> bool:
        entry_signal: Optional[RuleSignal] = self.shared_state.get(SharedDictKeyBase.ENTRY_RULE_SIGNAL, RuleSignal.NONE)
        if entry_signal not in (RuleSignal.BUY, RuleSignal.SELL, RuleSignal.BOTH):
            return False

        instrument_id:InstrumentId = self.instrument_id
        instrument:Instrument = self.strategy.cache.instrument(instrument_id)

        if instrument is None:
            # Instrument must be available in the cache
            return False

        # Fetch SL/TP from a shared state (expected as floats/doubles) and convert to Price
        sl_val = self.shared_state.get(SharedDictKeyBase.ENTRY_SL_PRICE, None)
        tp_val = self.shared_state.get(SharedDictKeyBase.ENTRY_TP_PRICE, None)
        sl_price = instrument.make_price(sl_val) if sl_val is not None else None
        tp_price = instrument.make_price(tp_val) if tp_val is not None else None

        # Use the bar we were given (or current_bar if provided)
        base_bar = current_bar or bar
        if base_bar is None:
            return False

        quantity = instrument.min_quantity
        if self.money_management_type == MoneyManagementType.FIXED_RISK_PERCENT:
            # self.trade_size is a RISK PERCENT (e.g., 1 = 1%) per Nautilus docs
            # Requires a valid stop-loss price to compute risk per trade.
            if sl_price is None:
                # Cannot compute a risk-based size without a stop-loss
                return False
            quantity = self.get_quantity(base_bar, sl_price, Decimal(str(self.fixed_risk_percent)))

        if self.money_management_type == MoneyManagementType.FIXED_LOT:
            quantity = instrument.make_qty(self.fixed_lot)

        if self.money_management_type == MoneyManagementType.MIN_QUANTITY:
            quantity = instrument.min_quantity

        # Validate quantity
        if quantity <= 0:
            return False

        # Map signal to order sides
        if entry_signal == RuleSignal.BUY:
            entry_side = OrderSide.BUY
            exit_side = OrderSide.SELL
        elif entry_signal == RuleSignal.SELL:
            entry_side = OrderSide.SELL
            exit_side = OrderSide.BUY
        else:
            # BOTH are not handled here (requires separate logic)
            return False

        # do not allow entry in an opposite direction if the hedging mode is disabled
        is_hedging = getattr(self.strategy, "oms_type", OmsType.UNSPECIFIED) == OmsType.HEDGING
        if not is_hedging:
            open_positions:list[Position] = self.strategy.cache.positions_open()
            for pos in open_positions:
                if pos.is_long and entry_side is not OrderSide.BUY:
                    return False
                elif pos.is_short and entry_side is not OrderSide.SELL:
                    return False

        # 1) ENTRY
        entry_order = self.strategy.order_factory.market(
            instrument_id=instrument.id,
            order_side=entry_side,
            quantity=quantity,
            time_in_force=TimeInForce.GTC,
            reduce_only=False,
            tags=["ENTRY"],
        )
        self.strategy.submit_order(entry_order)

        if sl_price:
            # 2) STOP-LOSS (no contingency kwargs supported by stop_market in this build)
            sl_order = self.strategy.order_factory.stop_market(
                instrument_id=instrument.id,
                order_side=exit_side,
                quantity=quantity,
                trigger_price=sl_price,
                time_in_force=TimeInForce.GTC,
                reduce_only=True,  # prevents opening a new position
                tags=["STOP_LOSS"],
            )
            self.strategy.submit_order(sl_order)
            self.add_order_id_shared_state(entry_order, sl_order=sl_order)
            self.add_orders_to_shared_state(entry_order, sl_order=sl_order)

        if tp_price:
            # 2) TAKE PROFIT
            tp_order = self.strategy.order_factory.market_if_touched(
                instrument_id=instrument.id,
                order_side=exit_side,
                quantity=quantity,
                trigger_price=tp_price,
                time_in_force=TimeInForce.GTC,
                reduce_only=True,  # prevents opening a new position
                tags=["TAKE_PROFIT"],
            )
            self.strategy.submit_order(tp_order)
            self.add_order_id_shared_state(entry_order, tp_order=tp_order)
            self.add_orders_to_shared_state(entry_order, tp_order=tp_order)

        return True

    def add_order_id_shared_state(self, entry_order, sl_order=None, tp_order=None):
        """Store client order IDs for entry/SL/TP in a single group per entry.

        If a group for the given entry already exists, it will be updated in place
        (adding SL and/or TP) instead of appending a duplicate group.
        """
        key = SharedDictKeyBase.ORDERS_LIST
        orders_list = self.shared_state.get(key, [])
        if not orders_list:  # if the key was missing, we got the default []
            self.shared_state.set(key, orders_list)

        # Resolve keys from SharedDictKeyBase
        entry_id_key = SharedDictKeyBase.ORDER_ID_ENTRY
        sl_id_key = SharedDictKeyBase.ORDER_ID_STOP_LOSS
        tp_id_key = SharedDictKeyBase.ORDER_ID_TAKE_PROFIT

        entry_id = entry_order.client_order_id
        sl_id = sl_order.client_order_id if sl_order is not None else None
        tp_id = tp_order.client_order_id if tp_order is not None else None

        # Try to find an existing group for this entry
        existing_group = None
        for group in orders_list:
            if isinstance(group, dict) and group.get(entry_id_key) == entry_id:
                existing_group = group
                break

        if existing_group is None:
            # Create a new group
            new_group = {entry_id_key: entry_id}
            if sl_id is not None:
                new_group[sl_id_key] = sl_id
            if tp_id is not None and tp_id_key is not None:
                new_group[tp_id_key] = tp_id
            orders_list.append(new_group)
        else:
            # Update the existing group in place
            if sl_id is not None and sl_id_key not in existing_group:
                existing_group[sl_id_key] = sl_id
            if tp_id is not None and tp_id_key is not None and tp_id_key not in existing_group:
                existing_group[tp_id_key] = tp_id

    def add_orders_to_shared_state(self, entry_order, sl_order=None, tp_order=None):
        """Store order objects for entry/SL/TP in a single group per entry.

        If a group for the given entry already exists, it will be updated in place
        (adding SL and/or TP) instead of appending a duplicate group.
        """
        key = SharedDictKeyBase.ORDERS
        orders = self.shared_state.get(key, [])
        if not orders:  # if the key was missing, we got the default []
            self.shared_state.set(key, orders)

        # Resolve keys from SharedDictKeyBase
        entry_obj_key = SharedDictKeyBase.ENTRY_ORDER
        sl_obj_key = SharedDictKeyBase.SL_ORDER
        tp_obj_key = SharedDictKeyBase.TP_ORDER

        entry_id = entry_order.client_order_id

        # Try to find an existing group for this entry (match by client_order_id)
        existing_group = None
        for group in orders:
            if isinstance(group, dict):
                entry_obj = group.get(entry_obj_key)
                if entry_obj is not None and getattr(entry_obj, "client_order_id", None) == entry_id:
                    existing_group = group
                    break

        if existing_group is None:
            # Create a new group
            new_group = {entry_obj_key: entry_order}
            if sl_order is not None:
                new_group[sl_obj_key] = sl_order
            if tp_order is not None and tp_obj_key is not None:
                new_group[tp_obj_key] = tp_order
            orders.append(new_group)
        else:
            # Update the existing group in place
            if sl_order is not None and sl_obj_key not in existing_group:
                existing_group[sl_obj_key] = sl_order
            if tp_order is not None and tp_obj_key is not None and tp_obj_key not in existing_group:
                existing_group[tp_obj_key] = tp_order

    def get_quantity(self, bar:Bar, sl_price, risk:Decimal) -> Quantity:
        instrument_id:InstrumentId = self.instrument_id
        instrument:Instrument = self.strategy.cache.instrument(instrument_id)

        # 1) Inputs for sizing
        if bar is None:
            raise RuntimeError("Bar (for entry price) is required for risk sizing.")
        entry_price = instrument.make_price(bar.close)
        if sl_price is None:
            raise RuntimeError("Stop-loss price is required for risk sizing.")

        # 2) Equity in account currency (Money)
        venue = instrument.id.venue
        account = self.strategy.portfolio.account(venue)
        # Prefer the account base currency; otherwise use the instrument quote
        acct_ccy = getattr(account, "base_currency", None) or instrument.quote_currency

        # Try to obtain a Money value for total/free balance (equity proxy)
        equity = None
        try:
            equity = account.balance_total(acct_ccy)
            if equity is None:
                equity = account.balance_free(acct_ccy)
            if equity is None and hasattr(account, "balances_total"):
                balances = account.balances_total()
                if isinstance(balances, dict) and balances:
                    equity = balances.get(acct_ccy) or next(iter(balances.values()))
        except Exception:
            equity = None

        if equity is None:
            # Fallback: cannot perform risk sizing without balances; use fixed size
            return instrument.make_qty(self.trade_size)

        # 3) FX rate (quote/settlement -> equity currency). If same currency, use 1
        try:
            settlement_ccy = instrument.get_settlement_currency()
        except Exception:
            # Backwards compatibility if method not available
            settlement_ccy = getattr(instrument, "quote_currency", None)

        if settlement_ccy is None or settlement_ccy == equity.currency:
            xrate = Decimal("1")
        else:
            exchanger = getattr(self.strategy.portfolio, "exchange_rates", None)
            try:
                rate_val = exchanger.rate(settlement_ccy, equity.currency) if exchanger is not None else Decimal("1")
                xrate = rate_val if isinstance(rate_val, Decimal) else Decimal(str(rate_val))
            except Exception:
                # Default to 1 to avoid crashing; sizing will be conservative if currencies match
                xrate = Decimal("1")

        risk = risk / Decimal("100")

        # 5) Resolve unit_batch_size as Decimal (fall back to 1)
        try:
            size_inc = getattr(instrument, "size_increment", None)
            if size_inc is None:
                ubs = Decimal("1")
            elif hasattr(size_inc, "as_decimal"):
                ubs = size_inc.as_decimal()
            elif hasattr(size_inc, "value"):
                ubs = Decimal(str(size_inc.value))
            else:
                ubs = Decimal(str(size_inc))
            if ubs is None or ubs <= 0:
                ubs = Decimal("1")
        except Exception:
            ubs = Decimal("1")

        # 5) Compute quantity using FixedRiskSizer
        sizer = MyFixedRiskSizer(instrument)
        quantity = sizer.calculate(
            entry=entry_price,
            stop_loss=sl_price,
            equity=equity,
            risk=risk
        )

        return quantity