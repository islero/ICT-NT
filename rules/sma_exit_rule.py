from __future__ import annotations
from dataclasses import dataclass

import pandas as pd
from nautilus_trader.indicators import SimpleMovingAverage
from nautilus_trader.model import BarType, Bar
from nautilus_trader.model.enums import OrderSide
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.instruments import Instrument
from nautilus_trader.model.orders import Order
from nautilus_trader.trading import Strategy

from core import SharedState
from core.constants import SharedDictKeyBase
from core.rules import RuleBase


@dataclass
class SMAExitRuleConfig:
    """Configuration for SMA exit rule."""
    bar_type: BarType  # BarType for the SMA calculation (default should be 30-minute bars)
    period: int = 10  # SMA period, default 10
    instrument_id: InstrumentId = None  # Instrument ID for creating close orders


class SMAExitRule(RuleBase):
    """
    Exit rule that uses Simple Moving Average to close positions.

    - If currently in a LONG position: close when a bar closes below SMA(N).
    - If currently in a SHORT position: close when a bar closes above SMA(N).

    This rule evaluates on completed bars of the configured bar_type.
    """

    shared_state: SharedState  # Override base class Optional type

    def __init__(self, shared_state: SharedState, strategy: Strategy, config: SMAExitRuleConfig):
        super().__init__(shared_state)
        self.shared_state = shared_state
        self.strategy = strategy
        self.config = config
        self.sma: SimpleMovingAverage = SimpleMovingAverage(period=config.period)
        self.first_bar_initialized = False

    def evaluate(self, bar: Bar, current_bar: Bar = None) -> bool:
        """
        Evaluate the SMA exit rule on completed bars.

        Closes positions when price closes on the wrong side of the SMA:
        - LONG positions: close when bar.close < SMA
        - SHORT positions: close when bar.close > SMA
        """
        # Verify the bar type is correct - only evaluate on configured bar type
        if str(bar.bar_type) not in str(self.config.bar_type) and self.first_bar_initialized:
            return True

        if not self.first_bar_initialized:
            self.first_bar_initialized = True

        # Check if SMA is initialized (has enough data)
        if not self.sma.initialized:
            return True

        # Get the current price (close) and SMA value
        current_price = float(bar.close)
        sma_value = self.sma.value

        # Check for exit conditions and close positions if needed
        self._check_and_close_positions(current_price, sma_value)

        return True

    def _check_and_close_positions(self, current_price: float, sma_value: float) -> None:
        """
        Check if any open positions should be closed based on SMA exit logic.

        - LONG positions: close when price < SMA
        - SHORT positions: close when price > SMA
        """
        # Load orders from shared_state
        orders_list = self.shared_state.get(SharedDictKeyBase.ORDERS, [])
        if not orders_list:
            return

        for orders in orders_list:
            entry_order: Order = orders.get(SharedDictKeyBase.ENTRY_ORDER)
            if entry_order is None:
                continue

            # Skip if the entry order is not filled/closed
            if not entry_order.is_closed:
                continue

            sl_order: Order = orders.get(SharedDictKeyBase.SL_ORDER)
            if sl_order is None:
                continue

            # Determine if we should exit based on position side
            should_exit = False

            if entry_order.is_buy:
                # LONG position: exit if price closes below SMA
                if current_price < sma_value:
                    should_exit = True
            elif entry_order.is_sell:
                # SHORT position: exit if price closes above SMA
                if current_price > sma_value:
                    should_exit = True

            if should_exit:
                self._execute_full_close(entry_order, sl_order)

    def _execute_full_close(self, entry_order: Order, sl_order: Order) -> bool:
        """
        Execute a full position close using a market order.

        Follows the same pattern as partial_close_quote_rule but closes 100% of the position.
        """
        try:
            instrument_id = self.config.instrument_id
            if instrument_id is None:
                self.strategy.log.error("SMAExitRule: instrument_id not configured")
                return False

            instrument: Instrument = self.strategy.cache.instrument(instrument_id)
            if instrument is None:
                self.strategy.log.error(f"SMAExitRule: instrument not found for {instrument_id}")
                return False

            # Get the current position quantity from the SL order
            # (SL order quantity tracks the remaining position size)
            close_quantity = sl_order.quantity

            # Determine the close order side (opposite of entry)
            if entry_order.is_buy:
                close_order_side = OrderSide.SELL
            else:
                close_order_side = OrderSide.BUY

            # Create and submit a market order to close the position
            order = self.strategy.order_factory.market(
                instrument_id=instrument_id,
                order_side=close_order_side,
                quantity=close_quantity,
                reduce_only=True,
            )
            self.strategy.submit_order(order)

            # Cancel the existing SL order since we're fully closing
            self.strategy.cancel_order(sl_order)

            self.strategy.log.info(
                f"SMAExitRule: Closed position - side={close_order_side}, qty={close_quantity}"
            )

            return True
        except Exception as exc:
            self.strategy.log.error(f"SMAExitRule: Failed to execute close - {exc}")
            return False

    def on_register_indicator_for_bars(self) -> None:
        """Register the SMA indicator for bars before the warmup period."""
        self.strategy.register_indicator_for_bars(self.config.bar_type, self.sma)

    def on_start(self) -> None:
        """Actions to be performed on strategy start."""
        # Setting the warmed-up and subscribed bar type
        key = SharedDictKeyBase.WARMED_UP_AND_SUBSCRIBED_BAR_TYPES
        lst = self.shared_state.get(key, [])
        if not lst:  # if the key was missing, we got the default []
            self.shared_state.set(key, lst)

        # add if not already there (avoid duplicates)
        if self.config.bar_type.standard() not in lst:
            lst.append(self.config.bar_type.standard())

            now_ts = pd.Timestamp(self.strategy.clock.timestamp_ns(), tz="UTC", unit="ns")
            start_time = (now_ts - pd.Timedelta(days=89)).normalize()

            if self.is_backtest_mode:
                self.strategy.request_aggregated_bars([self.config.bar_type], start=start_time, update_subscriptions=True)
            else:  # live trading mode
                self.strategy.request_bars(self.config.bar_type, start=start_time, limit=1000)

            self.strategy.subscribe_bars(self.config.bar_type)

    def on_stop(self) -> None:
        """Actions to be performed on strategy stop."""
        self.strategy.unsubscribe_bars(self.config.bar_type)

        # remove the bar type from a list
        key = SharedDictKeyBase.WARMED_UP_AND_SUBSCRIBED_BAR_TYPES
        lst = self.shared_state.get(key, [])
        if lst and self.config.bar_type.standard() in lst:
            lst.remove(self.config.bar_type.standard())
