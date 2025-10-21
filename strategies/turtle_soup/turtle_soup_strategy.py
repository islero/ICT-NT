from nautilus_trader.model import BarType, InstrumentId
from nautilus_trader.trading.config import StrategyConfig

from core.enums import MoneyManagementType
from core.rules import RuleBase, EntryTradingRule
from core.strategies import RuleBasedStrategy
from rules.entry_turtle_soup_rule import EntryTurtleSoupRuleConfig, EntryTurtleSoupRule
from rules.search_liquidity_pools_rule import SearchLiquidityPoolsRuleConfig, SearchLiquidityPoolsRule
from rules.turtle_soup_rule import TurtleSoupRuleConfig, TurtleSoupRule


class TurtleSoupStrategyConfig(StrategyConfig, frozen=True):
    """Configuration for searching liquidity pools rule."""
    liquidity_pool_bar_type: BarType                       # target bar type to search the liquidity pools
    liquidity_pool_upper_period_window: int                # the upper period window | 3 on 1D TF means the last 3 daily bars highs inclusive
    liquidity_pool_lower_period_window: int                # the lower period window | 3 on 1D TF means the last 3 daily bars lows inclusive

    """Configuration for turtle soup rule."""
    turtle_soup_bar_type: BarType          # target bar type to search the liquidity pools
    turtle_soup_bars_count: int            # how many bars to consider when forming a turtle soup

    risk_reward_ratio: float               # TP to SL ratio, which is actually R:R ratio

    # ------------- Money Management -------------
    money_management_type: MoneyManagementType
    fixed_lot: float
    fixed_risk_percent: float

    # ------------- Utils -------------
    instrument_id: InstrumentId
    base_bar_type: BarType
    is_backtest: bool = True

class TurtleSoupStrategy(RuleBasedStrategy):
    def __init__(self, config: TurtleSoupStrategyConfig):
        super().__init__(config, config.base_bar_type)

        # configure environment
        RuleBase.configure_environment(is_backtest=config.is_backtest)

        # initialize rules
        search_liquidity_pool_rule_config = SearchLiquidityPoolsRuleConfig(config.liquidity_pool_bar_type,
                                                                           config.liquidity_pool_upper_period_window,
                                                                           config.liquidity_pool_lower_period_window,)
        search_liquidity_pool_rule = SearchLiquidityPoolsRule(self.shared_state, self, search_liquidity_pool_rule_config)

        turtle_soup_rule_config = TurtleSoupRuleConfig(config.turtle_soup_bar_type, config.turtle_soup_bars_count)
        turtle_soup_rule = TurtleSoupRule(self.shared_state, self, turtle_soup_rule_config)

        entry_turtle_soup_rule_config = EntryTurtleSoupRuleConfig(config.risk_reward_ratio)
        entry_turtle_soup_rule = EntryTurtleSoupRule(self.shared_state, self, entry_turtle_soup_rule_config)

        entry_trading_rule = EntryTradingRule(self.shared_state, self, config.instrument_id,
                                              self.config.money_management_type,
                                              self.config.fixed_lot, self.config.fixed_risk_percent)

        self._rules = [
            #DebugRule(self, dt_to_unix_nanos(pd.Timestamp("2021-03-15 10:00:00"))),
            search_liquidity_pool_rule,
            turtle_soup_rule,
            entry_turtle_soup_rule,
            entry_trading_rule
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