from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class TradeDirection(Enum):
    """Directional bias used by the strategy.

    Mapping:
    - LONG  -> bullish context / buy-side execution.
    - SHORT -> bearish context / sell-side execution.
    """

    LONG = "long"
    SHORT = "short"
    NEUTRAL = "neutral"


class SwingType(Enum):
    HIGH = "high"
    LOW = "low"


class MitigationMode(Enum):
    """How FVG mitigation is declared.

    Assumption:
    - TOUCH: any overlap with zone.
    - MIDPOINT: 50% fill of the zone.
    - FULL_FILL: full sweep of the far boundary.
    """

    TOUCH = "touch"
    MIDPOINT = "midpoint"
    FULL_FILL = "full_fill"


class LiquiditySide(Enum):
    """Liquidity pool side in ICT terms.

    - BUY_SIDE pools sit above clustered highs.
    - SELL_SIDE pools sit below clustered lows.
    """

    BUY_SIDE = "buy_side"
    SELL_SIDE = "sell_side"


class ZoneType(Enum):
    FVG = "fvg"
    BREAKER = "breaker"


@dataclass(slots=True)
class PriceBar:
    """Lightweight OHLC container detached from Nautilus-specific classes."""

    ts_init: int
    open: float
    high: float
    low: float
    close: float

    @property
    def body(self) -> float:
        return abs(self.close - self.open)

    @property
    def is_bullish(self) -> bool:
        return self.close > self.open

    @property
    def is_bearish(self) -> bool:
        return self.close < self.open


@dataclass(slots=True)
class SwingPoint:
    swing_id: str
    ts_init: int
    price: float
    swing_type: SwingType
    pivot_index: int


@dataclass(slots=True)
class BosEvent:
    event_id: str
    direction: TradeDirection
    ts_init: int
    close_price: float
    broken_swing_id: str
    broken_swing_price: float


@dataclass(slots=True)
class FvgZone:
    zone_id: str
    direction: TradeDirection
    bottom: float
    top: float
    created_ts: int
    mitigation_mode: MitigationMode
    mitigated: bool = False
    mitigation_ts: Optional[int] = None
    filled: bool = False
    filled_ts: Optional[int] = None
    touches: int = 0

    @property
    def midpoint(self) -> float:
        return (self.bottom + self.top) / 2.0

    @property
    def is_active(self) -> bool:
        # "Active" includes partially mitigated zones; only full fill deactivates.
        return not self.filled


@dataclass(slots=True)
class LiquidityPool:
    pool_id: str
    side: LiquiditySide
    price: float
    tolerance: float
    created_ts: int
    last_seen_ts: int
    points_count: int
    swept: bool = False
    sweep_ts: Optional[int] = None

    @property
    def lower_bound(self) -> float:
        return self.price - self.tolerance

    @property
    def upper_bound(self) -> float:
        return self.price + self.tolerance


@dataclass(slots=True)
class BreakerBlock:
    block_id: str
    direction: TradeDirection
    bottom: float
    top: float
    source_ts: int
    created_ts: int
    reclaim_ts: Optional[int] = None
    invalidated: bool = False
    invalidated_ts: Optional[int] = None

    @property
    def is_active(self) -> bool:
        return not self.invalidated


@dataclass(slots=True)
class ZoneReference:
    zone_id: str
    zone_type: ZoneType
    direction: TradeDirection
    bottom: float
    top: float


@dataclass(slots=True)
class PendingSetup:
    direction: TradeDirection
    zone: ZoneReference
    confirmation_price: float
    stop_price: float
    sweep_price: float
    created_ts: int
    expires_ts: int

