from abc import ABC
from typing import Final, List

from nautilus_trader.model import Bar, BarType, QuoteTick
from nautilus_trader.trading import Strategy
from nautilus_trader.trading.config import StrategyConfig

from core import SharedState
from core.rules.quote_tick_rule_base import QuoteTickRuleBase
from core.rules.rule_base import RuleBase


class RuleBasedStrategy(ABC, Strategy):
    """
    Base class for all trading strategies that operate on a list of conditions.
    Conditions are executed in order, and trading logic is triggered if all conditions are met.
    """

    def __init__(self, config: StrategyConfig, base_bar_type: BarType):
        """
        :param config: `StrategyConfig` for initializing strategy settings.
        """
        super().__init__(config)
        self.shared_state: Final[SharedState] = SharedState()
        self._rules: List[RuleBase] = []
        self._quote_tick_rules: List[QuoteTickRuleBase] = []
        self._base_bar_type: Final[BarType] = base_bar_type

    def execute(self, bar: Bar, current_bar: Bar = None):
        """
        Should return trading signals based on input data.
        Must be implemented by child classes.
        """
        for rule in self._rules:
            if not rule.evaluate(bar, current_bar):
                return
        return

    def execute_quote_tick(self, tick: QuoteTick):
        """
        Should return trading signals based on input data.
        Must be implemented by child classes.
        """
        for rule in self._quote_tick_rules:
            if not rule.quote_tick_evaluate(tick):
                return
        return

    def on_bar(self, bar: Bar) -> None:
        """
        Actions to be performed when the strategy is running and receives a bar.

        Parameters
        ----------
        bar : Bar
            The bar received.
        """
        for rule in self._rules:
            rule.on_bar(bar)

        if str(bar.bar_type) in str(self._base_bar_type):
            self.execute(bar, bar)
        else:
            base_bar = self.cache.bar(self._base_bar_type.standard(), index=0)
            self.execute(bar, base_bar)

    def on_quote_tick(self, tick: QuoteTick):
        """
        Handles the processing of a single quote tick. This method takes a tick object
        of type QuoteTick and processes it by invoking the `execute_quote_tick` method.

        The function is designed to ensure that the provided tick object is processed
        accordingly within the system for further usage.

        :param tick: The quote tick object to the process.
        :type tick: QuoteTick
        """
        self.execute_quote_tick(tick)

    def on_start(self) -> None:
        """
        Actions to be performed on strategy start.
        """
        pass

    def on_stop(self) -> None:
        """
        Actions to be performed on strategy stop.
        """
        pass

    def on_historical_data(self, data) -> None:
        """
        Handle historical data (from requests)
        """
        for rule in self._rules:
            rule.on_historical_data(data)
