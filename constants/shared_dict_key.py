from enum import StrEnum, unique
from core.constants import SharedDictKeyBase

@unique
class SharedDictKey(SharedDictKeyBase):
    UPPER_LIQUIDITY_POOLS = "upper_liquidity_pools"
    LOWER_LIQUIDITY_POOLS = "lower_liquidity_pools"

    TURTLE_SOUP_RULE_SIGNAL = "turtle_soup_rule_signal"