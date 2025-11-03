from enum import StrEnum, unique

@unique
class SharedDictKey(StrEnum):
    UPPER_LIQUIDITY_POOLS = "upper_liquidity_pools"
    LOWER_LIQUIDITY_POOLS = "lower_liquidity_pools"

    SMA_FILTER_SIGNAL = "sma_filter_signal"
    TURTLE_SOUP_RULE_SIGNAL = "turtle_soup_rule_signal"
    TURTLE_SOUP_LATEST_UPPER_POOL_PRICE = "turtle_soup_latest_upper_pool_price"
    TURTLE_SOUP_LATEST_LOWER_POOL_PRICE = "turtle_soup_latest_lower_pool_price"