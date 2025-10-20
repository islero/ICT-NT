import pandas as pd
from nautilus_trader.model import Bar
from nautilus_trader.trading import Strategy
from core.rules.rule_base import RuleBase

class DebugRule(RuleBase):
    """
    Rule for debugging a specific time.
    """
    def __init__(self, strategy: Strategy, time: int):
        super().__init__()
        self.debug_time = time
        self.strategy = strategy

    def evaluate(self, bar: Bar, current_bar: Bar = None) -> bool:
        current_time_ns = self.strategy.clock.timestamp_ns()
        if current_time_ns >= self.debug_time:
            #time = pd.to_datetime(current_time_ns, unit="ns")
            return True

        return True