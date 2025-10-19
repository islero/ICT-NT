from enum import Enum

class RuleSignal(Enum):
    """
    Represents the possible outcomes of evaluating a trading rule.

    Attributes
    ----------
    NONE: The rule is not triggered; no action should be taken.
    BUY: The rule indicates a buy signal.
    SELL: The rule indicates a sell signal.
    BOTH: The rule indicates both buy and sell signals are valid
    """
    NONE = "none"
    BUY = "buy"
    SELL = "sell"
    BOTH = "both"