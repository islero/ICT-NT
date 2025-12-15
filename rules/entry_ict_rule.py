"""
ICT Entry Rule for combining Turtle Soup with Weekly/Daily context filters.

This rule evaluates entry conditions using:
- Turtle Soup signal (base entry trigger)
- Weekly Context Rule (macro filter - WHERE trades make sense)
- Daily Bias Rule (operational bias - WHAT direction to trade)

Unlike EntryTurtleSoupRule, this rule does NOT use SMA filter.
Instead it relies on higher timeframe context for trade direction filtering.

Entry Logic:
- LONG: Turtle Soup BUY signal + Weekly allows longs + Daily allows longs
- SHORT: Turtle Soup SELL signal + Weekly allows shorts + Daily allows shorts
"""

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
class EntryIctRuleConfig:
    """
    Configuration for ICT Entry Rule.

    Parameters:
        risk_reward_ratio: Risk/reward ratio for take profit calculation.
    """
    risk_reward_ratio: float = 2.0


class EntryIctRule(RuleBase):
    """
    ICT Entry Rule combining Turtle Soup with Weekly/Daily context filters.

    This rule triggers entries when:
    1. Turtle Soup signal indicates a valid setup
    2. Weekly context allows the trade direction
    3. Daily bias allows the trade direction

    The rule does NOT use SMA filter - it relies on higher timeframe
    context (Weekly and Daily) for directional filtering.

    Attributes:
        strategy: The parent strategy instance
        config: Rule configuration
    """

    def __init__(
        self,
        shared_state: SharedState,
        strategy: Strategy,
        config: EntryIctRuleConfig
    ):
        super().__init__(shared_state)
        self.strategy = strategy
        self.config = config

    def evaluate(self, bar: Bar, current_bar: Bar = None) -> bool:
        """
        Evaluate entry conditions.

        Args:
            bar: The bar being processed
            current_bar: Optional current bar for real-time price reference

        Returns:
            bool: True if entry conditions are met
        """
        if not current_bar:
            return False

        return self.check_long(current_bar) or self.check_short(current_bar)

    def check_long(self, current_bar: Bar) -> bool:
        """
        Check conditions for a long entry.

        Conditions:
        1. Turtle Soup signal is BUY or BOTH
        2. Weekly context does NOT block longs
        3. Daily bias does NOT block longs
        4. Valid stop loss price exists and is below current price

        Args:
            current_bar: Current bar for price reference

        Returns:
            bool: True if long entry conditions are met
        """
        if self.shared_state is None:
            return False

        # Check Turtle Soup signal
        turtle_soup_signal: Optional[RuleSignal] = self.shared_state.get(
            SharedDictKey.TURTLE_SOUP_RULE_SIGNAL
        )
        if turtle_soup_signal not in (RuleSignal.BUY, RuleSignal.BOTH):
            return False

        # Check Weekly context - must NOT block longs
        weekly_blocks_longs: bool = self.shared_state.get(
            SharedDictKey.WEEKLY_BLOCK_LONGS, False
        )
        if weekly_blocks_longs:
            return False

        # Check Daily bias - must NOT block longs
        daily_blocks_longs: bool = self.shared_state.get(
            SharedDictKey.DAILY_BLOCK_LONGS, False
        )
        if daily_blocks_longs:
            return False

        # Validate stop loss price
        stop_loss_price = self.shared_state.get(SharedDictKeyBase.ENTRY_SL_PRICE, None)
        if stop_loss_price is None:
            return False

        if stop_loss_price >= current_bar.close:
            self.strategy.log.error(
                f"BUY sl {stop_loss_price} >= current bar close {current_bar.close}"
            )
            # Reset the rule signal
            self.shared_state.set(SharedDictKey.TURTLE_SOUP_RULE_SIGNAL, RuleSignal.NONE)
            return False

        # Calculate take profit price
        take_profit_price = current_bar.close + (
            self.config.risk_reward_ratio * abs(current_bar.close - stop_loss_price)
        )

        # Set entry signals
        self.shared_state.set(SharedDictKeyBase.ENTRY_RULE_SIGNAL, RuleSignal.BUY)
        self.shared_state.set(SharedDictKeyBase.ENTRY_TP_PRICE, take_profit_price)

        # Reset the Turtle Soup signal
        self.shared_state.set(SharedDictKey.TURTLE_SOUP_RULE_SIGNAL, RuleSignal.NONE)

        return True

    def check_short(self, current_bar: Bar) -> bool:
        """
        Check conditions for a short entry.

        Conditions:
        1. Turtle Soup signal is SELL or BOTH
        2. Weekly context does NOT block shorts
        3. Daily bias does NOT block shorts
        4. Valid stop loss price exists and is above current price

        Args:
            current_bar: Current bar for price reference

        Returns:
            bool: True if short entry conditions are met
        """
        if self.shared_state is None:
            return False

        # Check Turtle Soup signal
        turtle_soup_signal: Optional[RuleSignal] = self.shared_state.get(
            SharedDictKey.TURTLE_SOUP_RULE_SIGNAL
        )
        if turtle_soup_signal not in (RuleSignal.SELL, RuleSignal.BOTH):
            return False

        # Check Weekly context - must NOT block shorts
        weekly_blocks_shorts: bool = self.shared_state.get(
            SharedDictKey.WEEKLY_BLOCK_SHORTS, False
        )
        if weekly_blocks_shorts:
            return False

        # Check Daily bias - must NOT block shorts
        daily_blocks_shorts: bool = self.shared_state.get(
            SharedDictKey.DAILY_BLOCK_SHORTS, False
        )
        if daily_blocks_shorts:
            return False

        # Validate stop loss price
        stop_loss_price = self.shared_state.get(SharedDictKeyBase.ENTRY_SL_PRICE, None)
        if stop_loss_price is None:
            return False

        if stop_loss_price <= current_bar.close:
            self.strategy.log.error(
                f"SELL sl {stop_loss_price} <= current bar close {current_bar.close}"
            )
            # Reset the rule signal
            self.shared_state.set(SharedDictKey.TURTLE_SOUP_RULE_SIGNAL, RuleSignal.NONE)
            return False

        # Calculate take profit price
        take_profit_price = current_bar.close - (
            self.config.risk_reward_ratio * abs(stop_loss_price - current_bar.close)
        )

        # Set entry signals
        self.shared_state.set(SharedDictKeyBase.ENTRY_RULE_SIGNAL, RuleSignal.SELL)
        self.shared_state.set(SharedDictKeyBase.ENTRY_TP_PRICE, take_profit_price)

        # Reset the Turtle Soup signal
        self.shared_state.set(SharedDictKey.TURTLE_SOUP_RULE_SIGNAL, RuleSignal.NONE)

        return True

    def on_start(self) -> None:
        """Actions to be performed on strategy start."""
        pass

    def on_stop(self) -> None:
        """Actions to be performed on strategy stop."""
        pass
