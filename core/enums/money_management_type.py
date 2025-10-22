from enum import Enum

class MoneyManagementType(Enum):
    """
    Enumeration representing different types of money management.
    """
    FIXED_RISK_PERCENT = "fixed risk percent"
    FIXED_LOT = "fixed lot"
    MIN_QUANTITY = "min quantity"