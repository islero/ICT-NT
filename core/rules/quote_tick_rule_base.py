from abc import abstractmethod

from nautilus_trader.model import Bar, QuoteTick

from core.rules.rule_base import RuleBase


class QuoteTickRuleBase(RuleBase):
    """
    Abstract base for quote tick rules.
    Child classes must implement the `evaluate` method as well as the `quote_tick_evaluate` method.
    """

    @abstractmethod
    def evaluate(self, bar: Bar, current_bar: Bar = None) -> bool:
        """Check if the rule is satisfied."""
        pass

    @abstractmethod
    def quote_tick_evaluate(self, tick: QuoteTick) -> bool:
        """Check if the rule is satisfied for quote ticks."""
        pass
