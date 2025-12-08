from nautilus_trader.model import BarType, InstrumentId
from nautilus_trader.trading.config import StrategyConfig

from core.rules import RuleBase
from core.strategies import RuleBasedStrategy
from rules.market_structure_rule import MarketStructureRule, MarketStructureRuleConfig


class ICTStrategyConfig(StrategyConfig, frozen=True):
    """Configuration for ICT strategy."""
    instrument_id: InstrumentId
    base_bar_type: BarType
    is_backtest: bool = True


class ICTStrategy(RuleBasedStrategy):
    def __init__(self, config: ICTStrategyConfig):
        super().__init__(config, config.base_bar_type)

        # configure environment
        RuleBase.configure_environment(is_backtest=config.is_backtest)

        # initialize rules
        self._rules = [
            MarketStructureRule(
                shared_state=self.shared_state,
                strategy=self,
                config=MarketStructureRuleConfig(bar_type=config.base_bar_type)
            ),
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
