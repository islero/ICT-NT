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

        # --- Risk-based sizing using FixedRiskSizer ---
        # self.trade_size is a RISK PERCENT (e.g., 1 = 1%) per Nautilus docs
        # Requires a valid stop-loss price to compute risk per trade.
        if sl_price is None:
            # Cannot compute a risk-based size without a stop-loss
            return False

        # Use the bar we were given (or current_bar if provided)
        base_bar = current_bar or bar
        if base_bar is None:
            return False

        quantity = instrument.min_quantity
        if self.money_management_type == MoneyManagementType.FIXED_RISK_PERCENT:
            quantity = self.get_quantity(base_bar, sl_price, Decimal(str(self.fixed_risk_percent)))

        if self.money_management_type == MoneyManagementType.FIXED_LOT:
            quantity = instrument.make_qty(self.fixed_lot)

        if self.money_management_type == MoneyManagementType.MIN_QUANTITY:
            quantity = instrument.min_quantity

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
        entry_time = pd.to_datetime(entry_order.ts_init, unit="ns")
        entry_price = base_bar.close
        sl = sl_price
        tp = tp_price
        open_positions = self.strategy.cache.positions_open()

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

        self.add_order_id_shared_state(entry_order, sl_order)
        self.add_orders_to_shared_state(entry_order, sl_order)

        return True

    def add_order_id_shared_state(self, entry_order, sl_order):
        key = SharedDictKeyBase.ORDERS_LIST
        orders_list = self.shared_state.get(key, [])
        if not orders_list:  # if the key was missing, we got the default []
            self.shared_state.set(key, orders_list)

        entry_order_exists = False
        sl_exists = False
        for group in orders_list:
            ids = group.values() if isinstance(group, dict) else group
            for order_id in ids:
                coid = order_id if isinstance(order_id, ClientOrderId) else ClientOrderId(str(order_id))
                if coid == entry_order.client_order_id:
                    entry_order_exists = True
                elif coid == sl_order.client_order_id:
                    sl_exists = True

        if not entry_order_exists and not sl_exists:
            orders_list.append({
                SharedDictKeyBase.ORDER_ID_ENTRY: entry_order.client_order_id,
                SharedDictKeyBase.ORDER_ID_STOP_LOSS: sl_order.client_order_id,
            })

    def add_orders_to_shared_state(self, entry_order, sl_order):
        key = SharedDictKeyBase.ORDERS
        orders = self.shared_state.get(key, [])
        if not orders:  # if the key was missing, we got the default []
            self.shared_state.set(key, orders)

        entry_order_exists = False
        sl_exists = False
        for group in orders:
            order_objects = group.values() if isinstance(group, dict) else group
            for order_obj in order_objects:
                if order_obj.client_order_id == entry_order.client_order_id:
                    entry_order_exists = True
                elif order_obj.client_order_id == sl_order.client_order_id:
                    sl_exists = True

        if not entry_order_exists and not sl_exists:
            orders.append({
                SharedDictKeyBase.ENTRY_ORDER: entry_order,
                SharedDictKeyBase.SL_ORDER: sl_order,
            })

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

        # 4) Commission rate as a fraction of notional (use taker fee for market entries when available)
        commission_rate = getattr(instrument, "taker_fee", None)
        if commission_rate is None:
            commission_rate = getattr(instrument, "maker_fee", None)
        if commission_rate is None:
            commission_rate = Decimal("0")
        elif not isinstance(commission_rate, Decimal):
            commission_rate = Decimal(str(commission_rate))

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
        sizer = FixedRiskSizer(instrument)
        quantity = sizer.calculate(
            entry=entry_price,
            stop_loss=sl_price,
            equity=equity,
            risk=risk,  # the risk is a PERCENT (1 = 1%) per docs
            commission_rate=commission_rate,
            exchange_rate=xrate,
            hard_limit=None,
            unit_batch_size=ubs,  # let sizer/venue handle rounding to size_increment
            units=1,
        )

        return quantity