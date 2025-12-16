from typing import List

from nautilus_trader.model import BarType, InstrumentId
from nautilus_trader.trading.config import StrategyConfig
from nautilus_trader.core.datetime import dt_to_unix_nanos
from pandas import Timedelta
import pandas as pd

from core.enums import MoneyManagementType
from core.rules import RuleBase, EntryTradingRule, SyncSharedOrdersQuoteRule
from core.strategies import RuleBasedStrategy
from rules.daily_bias_rule import DailyBiasRule, DailyBiasRuleConfig
from rules.debug_rule import DebugRule
from rules.entry_ict_rule import EntryIctRule, EntryIctRuleConfig
from rules.expected_target_rule import ExpectedTargetRule, ExpectedTargetRuleConfig
from rules.liquidity_pool_reuse_rule import LiquidityPoolReuseRule, LiquidityPoolReuseRuleConfig
from rules.market_structure_rule import MarketStructureRule, MarketStructureRuleConfig
from rules.reward_risk_ratio_rule import RewardRiskRatioRule, RewardRiskRatioRuleConfig
from rules.search_liquidity_pools_rule import SearchLiquidityPoolsRule, SearchLiquidityPoolsRuleConfig
from rules.turtle_soup_multi_tf_rule import TurtleSoupMultiTFRule, TurtleSoupMultiTFRuleConfig
from rules.weekly_context_rule import WeeklyContextRule, WeeklyContextRuleConfig


class ICTStrategyConfig(StrategyConfig, frozen=True):
    """Configuration for ICT strategy."""
    instrument_id: InstrumentId
    base_bar_type: BarType
    weekly_bar_type: BarType | None = None
    daily_bar_type: BarType | None = None
    is_backtest: bool = True

    # ------------- Liquidity Pool Search -------------
    liquidity_pool_bar_type: BarType | None = None
    liquidity_pool_lower_timeframe_bar_type: BarType | None = None
    liquidity_pool_time_delta: Timedelta = Timedelta(days=1)
    liquidity_pool_min_lower_timeframe_count: int = 3
    liquidity_pool_extremums_count: int = 3
    liquidity_pool_upper_period_window: int = 3
    liquidity_pool_lower_period_window: int = 3

    # ------------- Turtle Soup -------------
    turtle_soup_analysis_chain_bar_type: List[BarType] | None = None
    turtle_soup_stop_loss_bar_type: BarType | None = None
    turtle_soup_bars_count: int = 20
    retries_count_on_stop_out: int = 2
    sl_shift: float = 0.0

    # ------------- Risk/Reward -------------
    risk_reward_ratio: float = 2.0

    # ------------- Expected Target -------------
    expected_target_bar_type: BarType | None = None
    expected_target_left: int = 10
    expected_target_right: int = 10

    # ------------- Liquidity Pool Reuse -------------
    liquidity_pool_reuse_bar_type: BarType | None = None
    liquidity_pool_uses_count: int = 1

    # ------------- Money Management -------------
    money_management_type: MoneyManagementType = MoneyManagementType.FIXED_LOT
    fixed_lot: float = 0.01
    fixed_risk_percent: float = 1.0


class ICTStrategy(RuleBasedStrategy):
    def __init__(self, config: ICTStrategyConfig):
        super().__init__(config, config.base_bar_type)

        # configure environment
        RuleBase.configure_environment(is_backtest=config.is_backtest)

        # Initialize search liquidity pool rule
        search_liquidity_pool_rule = SearchLiquidityPoolsRule(
            self.shared_state,
            self,
            SearchLiquidityPoolsRuleConfig(
                config.liquidity_pool_bar_type,
                config.liquidity_pool_upper_period_window,
                config.liquidity_pool_lower_period_window,
                config.liquidity_pool_lower_timeframe_bar_type,
                config.liquidity_pool_time_delta,
                config.liquidity_pool_min_lower_timeframe_count,
                config.liquidity_pool_extremums_count,
            ),
        )

        # Initialize expected target rule
        expected_target_rule = ExpectedTargetRule(
            self.shared_state,
            self,
            ExpectedTargetRuleConfig(
                config.expected_target_bar_type,
                config.expected_target_left,
                config.expected_target_right,
            ),
        )

        # Initialize turtle soup rule
        turtle_soup_rule = TurtleSoupMultiTFRule(
            self.shared_state,
            self,
            TurtleSoupMultiTFRuleConfig(
                levels_sources=[config.liquidity_pool_bar_type] if config.liquidity_pool_bar_type else [],
                analysis_chain=config.turtle_soup_analysis_chain_bar_type or [],
                stop_loss_bar_type=config.turtle_soup_stop_loss_bar_type,
                turtle_bars_count=config.turtle_soup_bars_count,
                retries_count_on_stop_out=config.retries_count_on_stop_out,
                sl_shift=config.sl_shift,
            ),
        )

        # Initialize reward risk ratio rule
        reward_risk_ratio_rule = RewardRiskRatioRule(
            self.shared_state,
            self,
            RewardRiskRatioRuleConfig(config.risk_reward_ratio),
        )

        # Initialize liquidity pool reuse rule
        liquidity_pool_reuse_rule = LiquidityPoolReuseRule(
            self.shared_state,
            self,
            LiquidityPoolReuseRuleConfig(
                config.liquidity_pool_reuse_bar_type,
                config.instrument_id,
                config.turtle_soup_bars_count,
                config.liquidity_pool_uses_count,
            ),
        )

        # Initialize entry ICT rule (uses weekly/daily context instead of SMA)
        entry_ict_rule = EntryIctRule(
            self.shared_state,
            self,
            EntryIctRuleConfig(config.risk_reward_ratio),
        )

        # Initialize entry trading rule
        entry_trading_rule = EntryTradingRule(
            self.shared_state,
            self,
            config.instrument_id,
            config.money_management_type,
            config.fixed_lot,
            config.fixed_risk_percent,
        )

        # Initialize rules list
        self._rules = [
            SyncSharedOrdersQuoteRule(self.shared_state, self, config.instrument_id),
            #WeeklyContextRule(
            #    shared_state=self.shared_state,
            #    strategy=self,
            #    config=WeeklyContextRuleConfig(
            #        bar_type=config.weekly_bar_type,
            #        base_bar_type=config.base_bar_type,
            #    ),
            #),
            #DebugRule(self, dt_to_unix_nanos(pd.Timestamp("2025-07-10 15:00:00"))),
            DailyBiasRule(
                shared_state=self.shared_state,
                strategy=self,
                config=DailyBiasRuleConfig(
                    bar_type=config.daily_bar_type,
                    base_bar_type=config.base_bar_type,
                ),
            ),
            MarketStructureRule(
                shared_state=self.shared_state,
                strategy=self,
                config=MarketStructureRuleConfig(bar_type=config.base_bar_type),
            ),
            search_liquidity_pool_rule,
            expected_target_rule,
            turtle_soup_rule,
            reward_risk_ratio_rule,
            liquidity_pool_reuse_rule,
            entry_ict_rule,
            entry_trading_rule,
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
