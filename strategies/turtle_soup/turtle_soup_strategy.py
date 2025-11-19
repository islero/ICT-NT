from typing import List

import pandas as pd
from nautilus_trader.core.datetime import dt_to_unix_nanos
from nautilus_trader.model import BarType, InstrumentId
from nautilus_trader.trading.config import StrategyConfig
from pandas import Timedelta

from core.enums import MoneyManagementType
from core.rules import RuleBase, EntryTradingRule, SyncSharedOrdersQuoteRule
from core.strategies import RuleBasedStrategy
from rules.debug_rule import DebugRule
from rules.entry_turtle_soup_rule import EntryTurtleSoupRuleConfig, EntryTurtleSoupRule
from rules.expected_target_rule import ExpectedTargetRule, ExpectedTargetRuleConfig
from rules.liquidity_pool_reuse_rule import LiquidityPoolReuseRuleConfig, LiquidityPoolReuseRule
from rules.reward_risk_ratio_rule import RewardRiskRatioRule, RewardRiskRatioRuleConfig
from rules.search_liquidity_pools_rule import SearchLiquidityPoolsRuleConfig, SearchLiquidityPoolsRule
from rules.sma_filter_rule import SMAFilterRuleConfig, SMAFilterRule
from rules.turtle_soup_multi_tf_rule import TurtleSoupMultiTFRuleConfig, TurtleSoupMultiTFRule

class TurtleSoupStrategyConfig(StrategyConfig, frozen=True):
    """Configuration for searching liquidity pools rule."""
    liquidity_pool_bar_type: BarType                       # target bar type to search the liquidity pools
    liquidity_pool_lower_timeframe_bar_type: BarType
    liquidity_pool_time_delta: Timedelta
    liquidity_pool_min_lower_timeframe_count: int
    liquidity_pool_extremums_count:int
    liquidity_pool_upper_period_window: int                # the upper period window | 3 on 1D TF means the last 3 daily bars highs inclusive
    liquidity_pool_lower_period_window: int                # the lower period window | 3 on 1D TF means the last 3 daily bars lows inclusive

    """Configuration for turtle soup rule."""
    turtle_soup_bar_type: BarType                         # target bar type to search the liquidity pools
    turtle_soup_analysis_chain_bar_type: List[BarType]    # target bar type to search the liquidity pools
    turtle_soup_stop_loss_bar_type: BarType
    turtle_soup_bars_count: int                           # how many bars to consider when forming a turtle soup
    retries_count_on_stop_out: int                        # e.g., 2 - means 2 retries on the same day
    sl_shift: float

    risk_reward_ratio: float                              # TP to SL ratio, which is actually R:R ratio

    # ------------- SMA Filter -------------
    sma_filter_bar_type: BarType                          # bar type for SMA filter (default 1-DAY)
    sma_filter_period: int                                # SMA period (default 50)

    # ------------- Expected Target -------------
    expected_target_bar_type: BarType                     # expected target bar type
    expected_target_left: int
    expected_target_right: int

    # ------------- Liquidity Pool Reuse -------------
    liquidity_pool_reuse_bar_type: BarType
    liquidity_pool_uses_count: int

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
                                                                           config.liquidity_pool_lower_period_window,
                                                                           config.liquidity_pool_lower_timeframe_bar_type,
                                                                           config.liquidity_pool_time_delta,
                                                                           config.liquidity_pool_min_lower_timeframe_count,
                                                                           config.liquidity_pool_extremums_count)
        search_liquidity_pool_rule = SearchLiquidityPoolsRule(self.shared_state, self, search_liquidity_pool_rule_config)

        #turtle_soup_rule_config = TurtleSoupRuleConfig(config.turtle_soup_bar_type, config.turtle_soup_bars_count)
        #turtle_soup_rule = TurtleSoupRule(self.shared_state, self, turtle_soup_rule_config)

        turtle_soup_rule_config = TurtleSoupMultiTFRuleConfig(levels_sources=[config.liquidity_pool_bar_type],
                                                              analysis_chain=config.turtle_soup_analysis_chain_bar_type,
                                                              stop_loss_bar_type=config.turtle_soup_stop_loss_bar_type,
                                                              turtle_bars_count=config.turtle_soup_bars_count,
                                                              retries_count_on_stop_out=config.retries_count_on_stop_out,
                                                              sl_shift=config.sl_shift)
        turtle_soup_rule = TurtleSoupMultiTFRule(self.shared_state, self, turtle_soup_rule_config)

        sma_filter_rule_config = SMAFilterRuleConfig(config.sma_filter_bar_type, config.sma_filter_period)
        sma_filter_rule = SMAFilterRule(self.shared_state, self, sma_filter_rule_config)

        expected_target_rule_config = ExpectedTargetRuleConfig(config.expected_target_bar_type,
                                                               config.expected_target_left,
                                                               config.expected_target_right)
        expected_target_rule = ExpectedTargetRule(self.shared_state, self, expected_target_rule_config)

        reward_risk_ratio_rule_config = RewardRiskRatioRuleConfig(config.risk_reward_ratio)
        reward_risk_ratio_rule = RewardRiskRatioRule(self.shared_state, self, reward_risk_ratio_rule_config)

        liquidity_pool_reuse_rule_config = LiquidityPoolReuseRuleConfig(config.liquidity_pool_reuse_bar_type,
                                                                        config.instrument_id,
                                                                        config.turtle_soup_bars_count,
                                                                        config.liquidity_pool_uses_count)
        liquidity_pool_reuse_rule = LiquidityPoolReuseRule(self.shared_state, self, liquidity_pool_reuse_rule_config)

        entry_turtle_soup_rule_config = EntryTurtleSoupRuleConfig(config.risk_reward_ratio)
        entry_turtle_soup_rule = EntryTurtleSoupRule(self.shared_state, self, entry_turtle_soup_rule_config)

        entry_trading_rule = EntryTradingRule(self.shared_state, self, config.instrument_id,
                                              self.config.money_management_type,
                                              self.config.fixed_lot, self.config.fixed_risk_percent)

        self._rules = [
            SyncSharedOrdersQuoteRule(self.shared_state, self, config.instrument_id),
            #DebugRule(self, dt_to_unix_nanos(pd.Timestamp("2025-10-17 08:50:00"))),
            search_liquidity_pool_rule,
            sma_filter_rule,
            expected_target_rule,
            turtle_soup_rule,
            reward_risk_ratio_rule,
            liquidity_pool_reuse_rule,
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