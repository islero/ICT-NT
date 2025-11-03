from dataclasses import dataclass
from typing import Optional
from nautilus_trader.model import Bar
from nautilus_trader.trading import Strategy
from constants.shared_dict_key import SharedDictKey
from core import SharedState
from core.constants import SharedDictKeyBase
from core.enums import RuleSignal
from core.rules import RuleBase

@dataclass
class EntryTurtleSoupRuleConfig:
    risk_reward_ratio: float = 2.0

class EntryTurtleSoupRule(RuleBase):
    def __init__(self, shared_state: SharedState, strategy: Strategy, config: EntryTurtleSoupRuleConfig):
        super().__init__(shared_state)
        self.strategy = strategy
        self.config = config

    def evaluate(self, bar: Bar, current_bar: Bar = None) -> bool:
        # Validate current bar
        if not current_bar:
            return False

        return self.check_long(current_bar) or self.check_short(current_bar)

    def check_long(self, current_bar: Bar) -> bool:
        # Determine a Turtle Soup direction
        turtle_soup_signal: Optional[RuleSignal] = self.shared_state.get(SharedDictKey.TURTLE_SOUP_RULE_SIGNAL)
        if turtle_soup_signal not in (RuleSignal.BUY, RuleSignal.BOTH):
            return False

        # Determine a SMA filter direction
        sma_filter_signal: Optional[RuleSignal] = self.shared_state.get(SharedDictKey.SMA_FILTER_SIGNAL)
        if sma_filter_signal not in (RuleSignal.BUY, RuleSignal.BOTH):
            return False

        stop_loss_price = self.shared_state.get(SharedDictKeyBase.ENTRY_SL_PRICE, None)
        if stop_loss_price is None:
            return False

        if stop_loss_price >= current_bar.close:
            return False

        take_profit_price = current_bar.close + (self.config.risk_reward_ratio * abs(current_bar.close - stop_loss_price))

        self.shared_state.set(SharedDictKeyBase.ENTRY_RULE_SIGNAL, RuleSignal.BUY)
        self.shared_state.set(SharedDictKeyBase.ENTRY_TP_PRICE, take_profit_price)

        # Reset the rule signal
        self.shared_state.set(SharedDictKey.TURTLE_SOUP_RULE_SIGNAL, RuleSignal.NONE)

        return True

    def check_short(self, current_bar: Bar) -> bool:
        # Determine a Turtle Soup direction
        turtle_soup_signal: Optional[RuleSignal] = self.shared_state.get(SharedDictKey.TURTLE_SOUP_RULE_SIGNAL)
        if turtle_soup_signal not in (RuleSignal.SELL, RuleSignal.BOTH):
            return False

        # Determine a SMA filter direction
        sma_filter_signal: Optional[RuleSignal] = self.shared_state.get(SharedDictKey.SMA_FILTER_SIGNAL)
        if sma_filter_signal not in (RuleSignal.SELL, RuleSignal.BOTH):
            return False

        stop_loss_price = self.shared_state.get(SharedDictKeyBase.ENTRY_SL_PRICE, None)
        if stop_loss_price is None:
            return False

        if stop_loss_price <= current_bar.close:
            return False

        take_profit_price = current_bar.close - (self.config.risk_reward_ratio * abs(stop_loss_price - current_bar.close))

        self.shared_state.set(SharedDictKeyBase.ENTRY_RULE_SIGNAL, RuleSignal.SELL)
        self.shared_state.set(SharedDictKeyBase.ENTRY_TP_PRICE, take_profit_price)

        # Reset the rule signal
        self.shared_state.set(SharedDictKey.TURTLE_SOUP_RULE_SIGNAL, RuleSignal.NONE)

        return True

    # We don't need special start/stop handling here (no indicators used)
    def on_start(self) -> None:
        pass

    def on_stop(self) -> None:
        pass
