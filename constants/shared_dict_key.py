from enum import StrEnum, unique


@unique
class SharedDictKey(StrEnum):
    UPPER_LIQUIDITY_POOLS = "upper_liquidity_pools"
    LOWER_LIQUIDITY_POOLS = "lower_liquidity_pools"

    SMA_FILTER_SIGNAL = "sma_filter_signal"
    TURTLE_SOUP_RULE_SIGNAL = "turtle_soup_rule_signal"
    TURTLE_SOUP_LATEST_UPPER_POOL_PRICE = "turtle_soup_latest_upper_pool_price"
    TURTLE_SOUP_LATEST_LOWER_POOL_PRICE = "turtle_soup_latest_lower_pool_price"

    TURTLE_SOUP_USED_POOL = "turtle_soup_used_pool"

    EXPECTED_TARGET_LATEST_PIVOT_HIGH_PRICE = "expected_target_latest_pivot_high_price"
    EXPECTED_TARGET_LATEST_PIVOT_HIGH_TS = "expected_target_latest_pivot_high_ts"
    EXPECTED_TARGET_LATEST_PIVOT_LOW_PRICE = "expected_target_latest_pivot_low_price"
    EXPECTED_TARGET_LATEST_PIVOT_LOW_TS = "expected_target_latest_pivot_low_ts"

    MARKET_STRUCTURE_TREND_DIRECTION = "market_structure_trend_direction"
    MARKET_STRUCTURE_SHIFT = "market_structure_shift"
    MARKET_STRUCTURE_RULE_SIGNAL = "market_structure_rule_signal"

    # Weekly Context Rule keys
    WEEKLY_STRUCTURE = "weekly_structure"
    WEEKLY_ZONE = "weekly_zone"
    WEEKLY_BLOCK_LONGS = "weekly_block_longs"
    WEEKLY_BLOCK_SHORTS = "weekly_block_shorts"
    WEEKLY_RECOMMENDED_ENTRY_PRICE = "weekly_recommended_entry_price"
    WEEKLY_DEALING_RANGE_HIGH = "weekly_dealing_range_high"
    WEEKLY_DEALING_RANGE_LOW = "weekly_dealing_range_low"
    WEEKLY_EQUILIBRIUM = "weekly_equilibrium"
    WEEKLY_OTE_HIGH = "weekly_ote_high"
    WEEKLY_OTE_LOW = "weekly_ote_low"

    # Daily Bias Rule keys
    DAILY_BIAS = "daily_bias"
    DAILY_STRUCTURE = "daily_structure"
    DAILY_ZONE = "daily_zone"
    DAILY_BLOCK_LONGS = "daily_block_longs"
    DAILY_BLOCK_SHORTS = "daily_block_shorts"
    DAILY_RECOMMENDED_ENTRY_PRICE = "daily_recommended_entry_price"
    DAILY_DEALING_RANGE_HIGH = "daily_dealing_range_high"
    DAILY_DEALING_RANGE_LOW = "daily_dealing_range_low"
    DAILY_EQUILIBRIUM = "daily_equilibrium"
    DAILY_OTE_HIGH = "daily_ote_high"
    DAILY_OTE_LOW = "daily_ote_low"
    DAILY_BIAS_CONFIDENCE = "daily_bias_confidence"
    DAILY_BIAS_REASON_CODES = "daily_bias_reason_codes"
    DAILY_DISPLACEMENT_DETECTED = "daily_displacement_detected"
    DAILY_LAST_FVG_DIRECTION = "daily_last_fvg_direction"
