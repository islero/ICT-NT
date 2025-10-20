import pandas as pd
from nautilus_trader.model import Bar
from nautilus_trader.trading import Strategy
from pandas import Timestamp
from core.rules.rule_base import RuleBase

class DebugRule(RuleBase):
    """
    Rule for debugging a specific time.
    """
    def __init__(self, strategy: Strategy, time: Timestamp):
        super().__init__()
        self.debug_time = time
        self.strategy = strategy

    def evaluate(self, bar: Bar, current_bar: Bar = None) -> bool:
        current_time_ns = self.strategy.clock.timestamp_ns()
        current_time = pd.to_datetime(current_time_ns, unit="ns")

        if current_time >= self.debug_time:
            return True

        return True