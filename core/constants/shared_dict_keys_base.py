from enum import StrEnum, unique

@unique
class SharedDictKeyBase(StrEnum):
    # Warm up and subscribed bar types
    WARMED_UP_AND_SUBSCRIBED_BAR_TYPES = "warm_up_and_subscribed_bar_types"

    # Order tracking keys
    ORDERS = "ORDERS"
    ENTRY_ORDER = "ENTRY_ORDER"
    SL_ORDER = "SL_ORDER"

    # Key for tracking the sync state of the bar types
    TIMEFRAMES_SYNC = "timeframes_sync"

    # Entry rule outputs / coordination keys
    ENTRY_RULE_SIGNAL = "entry_rule_signal"  # RuleSignal for entry intent
    ENTRY_SL_PRICE = "entry_sl_price"
    ENTRY_TP_PRICE = "entry_tp_price"