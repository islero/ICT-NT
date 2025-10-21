from enum import StrEnum, unique
from core.constants import SharedDictKeyBase

@unique
class SharedDictKey(SharedDictKeyBase):
    UPPER_LIQUIDITY_POOLS = "upper_liquidity_pools"
    LOWER_LIQUIDITY_POOLS = "lower_liquidity_pools"

    TURTLE_SOUP_RULE_SIGNAL = "turtle_soup_rule_signal"
    TURTLE_SOUP_LATEST_UPPER_POOL_PRICE = "turtle_soup_latest_upper_pool_price"
    TURTLE_SOUP_LATEST_LOWER_POOL_PRICE = "turtle_soup_latest_lower_pool_price"