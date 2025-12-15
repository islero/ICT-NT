from nautilus_trader.model import BarType, InstrumentId
from nautilus_trader.trading.config import StrategyConfig

from core.rules import RuleBase
from core.strategies import RuleBasedStrategy
from rules.market_structure_rule import MarketStructureRule, MarketStructureRuleConfig
from rules.weekly_context_rule import WeeklyContextRule, WeeklyContextRuleConfig
from rules.daily_bias_rule import DailyBiasRule, DailyBiasRuleConfig


class ICTStrategyConfig(StrategyConfig, frozen=True):
    """Configuration for ICT strategy."""
    instrument_id: InstrumentId
    base_bar_type: BarType
    weekly_bar_type: BarType | None = None
    daily_bar_type: BarType | None = None
    is_backtest: bool = True


class ICTStrategy(RuleBasedStrategy):
    def __init__(self, config: ICTStrategyConfig):
        super().__init__(config, config.base_bar_type)

        # configure environment
        RuleBase.configure_environment(is_backtest=config.is_backtest)

        # initialize rules
        self._rules = [
            WeeklyContextRule(
                shared_state=self.shared_state,
                strategy=self,
                config=WeeklyContextRuleConfig(
                    bar_type=config.weekly_bar_type,
                    base_bar_type=config.base_bar_type
                )
            ),
            DailyBiasRule(
                shared_state=self.shared_state,
                strategy=self,
                config=DailyBiasRuleConfig(
                    bar_type=config.daily_bar_type,
                    base_bar_type=config.base_bar_type
                )
            ),
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
