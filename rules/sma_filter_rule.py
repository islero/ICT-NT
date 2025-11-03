from dataclasses import dataclass

import pandas as pd
from nautilus_trader.indicators import SimpleMovingAverage
from nautilus_trader.model import BarType, Bar
from nautilus_trader.trading import Strategy
from constants.shared_dict_key import SharedDictKey
from core import SharedState
from core.constants import SharedDictKeyBase
from core.enums import RuleSignal
from core.rules import RuleBase

@dataclass
class SMAFilterRuleConfig:
    """Configuration for SMA filter rule."""
    bar_type: BarType  # BarType for the SMA calculation
    period: int = 50  # SMA period, default 50


class SMAFilterRule(RuleBase):
    """
    Rule that uses Simple Moving Average to control entry sides.
    If price is above SMA, allows long positions (BUY signal).
    If price is below SMA, allows short positions (SELL signal).
    Saves the signal as RuleSignal.BUY or RuleSignal.SELL in shared_state.
    """

    def __init__(self, shared_state: SharedState, strategy: Strategy, config: SMAFilterRuleConfig):
        super().__init__(shared_state)
        self.strategy = strategy
        self.config = config
        self.sma: SimpleMovingAverage = SimpleMovingAverage(period=config.period)
        self.first_bar_initialized = False

    def evaluate(self, bar: Bar, current_bar: Bar = None) -> bool:
        """Evaluate the SMA rule and update shared_state with BUY or SELL signal."""
        # Verify the bar type is correct
        if str(bar.bar_type) not in str(self.config.bar_type) and self.first_bar_initialized:
            return True

        if not self.first_bar_initialized:
            self.first_bar_initialized = True

        # Check if SMA is initialized (has enough data)
        if not self.sma.initialized:
            # Not enough data yet, set signal to NONE
            self.shared_state.set(SharedDictKey.SMA_FILTER_SIGNAL, RuleSignal.NONE)
            return True

        # Get the current price (close) and SMA value
        current_price = float(bar.close)
        sma_value = self.sma.value

        # Determine the signal based on price position relative to SMA
        if current_price > sma_value:
            # Price above SMA: allow long positions
            signal = RuleSignal.BUY
        else:
            # Price below SMA: allow short positions
            signal = RuleSignal.SELL

        # Save the signal to shared_state
        self.shared_state.set(SharedDictKey.SMA_FILTER_SIGNAL, signal)

        return True

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
