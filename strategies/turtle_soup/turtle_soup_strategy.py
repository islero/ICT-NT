import pandas as pd
from nautilus_trader.core.datetime import dt_to_unix_nanos
from nautilus_trader.model import BarType
from nautilus_trader.trading.config import StrategyConfig
from core.rules import RuleBase
from core.strategies import RuleBasedStrategy
from rules.debug_rule import DebugRule

class TurtleSoupStrategyConfig(StrategyConfig, frozen=True):
    base_bar_type: BarType
    is_backtest: bool = True

class TurtleSoupStrategy(RuleBasedStrategy):
    def __init__(self, config: TurtleSoupStrategyConfig):
        super().__init__(config, config.base_bar_type)

        # configure environment
        RuleBase.configure_environment(is_backtest=config.is_backtest)

        self._rules = [
            #DebugRule(self, dt_to_unix_nanos(pd.Timestamp("2021-03-15 10:00:00")))
        ]

    def on_start(self) -> None:
        # Subscribe base bars
        self.subscribe_bars(self.config.base_bar_type)

        # register indicators before the warmup period
        for rule in self._rules:
            rule.on_register_indicator_for_bars()

        # trigger rules on_start
        for rule in self._rules:
            rule.on_start()

    def on_stop(self) -> None:
        # Unsubscribe base bars
        self.unsubscribe_bars(self.config.base_bar_type)