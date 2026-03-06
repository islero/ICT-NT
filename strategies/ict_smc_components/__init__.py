"""Causal ICT/SMC components used by :mod:`strategies.ict_smc_strategy`.

The package intentionally avoids third-party SMC libraries because many are
lookahead/repainting by design. All detectors here consume only closed bars and
confirm pivots with right-side bars, making the outputs auditable for both
backtesting and live execution.
"""

from .detectors import (
    BosDetector,
    BreakerBlockDetector,
    FvgDetector,
    LiquidityPoolDetector,
    detect_local_sweep,
    is_displacement_candle,
)
from .models import (
    BosEvent,
    BreakerBlock,
    FvgZone,
    LiquidityPool,
    LiquiditySide,
    MitigationMode,
    PendingSetup,
    PriceBar,
    SwingPoint,
    TradeDirection,
    ZoneReference,
    ZoneType,
)
from .state import IctSmcRuntimeState

__all__ = [
    "BosDetector",
    "BosEvent",
    "BreakerBlock",
    "BreakerBlockDetector",
    "FvgDetector",
    "FvgZone",
    "IctSmcRuntimeState",
    "LiquidityPool",
    "LiquidityPoolDetector",
    "LiquiditySide",
    "MitigationMode",
    "PendingSetup",
    "PriceBar",
    "SwingPoint",
    "TradeDirection",
    "ZoneReference",
    "ZoneType",
    "detect_local_sweep",
    "is_displacement_candle",
]
