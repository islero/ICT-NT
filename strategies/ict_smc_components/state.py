from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

from strategies.ict_smc_components.models import (
    BosEvent,
    BreakerBlock,
    FvgZone,
    LiquidityPool,
    PendingSetup,
    PriceBar,
    SwingPoint,
    TradeDirection,
)


@dataclass(slots=True)
class IctSmcRuntimeState:
    """Mutable strategy state kept separate from strategy orchestration."""

    max_htf_bars: int = 3000
    max_ltf_bars: int = 6000
    max_active_zones: int = 120
    max_active_pools: int = 120

    htf_bars: deque[PriceBar] = field(default_factory=lambda: deque(maxlen=3000))
    ltf_bars: deque[PriceBar] = field(default_factory=lambda: deque(maxlen=6000))

    swings_highs: list[SwingPoint] = field(default_factory=list)
    swings_lows: list[SwingPoint] = field(default_factory=list)
    fvg_zones: list[FvgZone] = field(default_factory=list)
    breaker_blocks: list[BreakerBlock] = field(default_factory=list)
    liquidity_pools: list[LiquidityPool] = field(default_factory=list)

    last_bos: BosEvent | None = None
    bias: TradeDirection = TradeDirection.NEUTRAL
    pending_setup: PendingSetup | None = None

    htf_atr: float | None = None
    ltf_atr: float | None = None

    ltf_index: int = 0
    last_trade_ltf_index: int | None = None
    trades_per_day: dict[str, int] = field(default_factory=dict)

    def append_htf_bar(self, bar: PriceBar) -> None:
        self.htf_bars.append(bar)

    def append_ltf_bar(self, bar: PriceBar) -> None:
        self.ltf_bars.append(bar)
        self.ltf_index += 1

    def record_bos(self, event: BosEvent) -> None:
        self.last_bos = event
        self.bias = event.direction

    def register_trade(self, day_key: str) -> None:
        self.trades_per_day[day_key] = self.trades_per_day.get(day_key, 0) + 1
        self.last_trade_ltf_index = self.ltf_index

    def trades_today(self, day_key: str) -> int:
        return self.trades_per_day.get(day_key, 0)

    def clear_pending_setup(self) -> None:
        self.pending_setup = None

    def has_recent_breaker_reclaim(self, direction: TradeDirection, min_ts: int) -> bool:
        for block in self.breaker_blocks:
            if block.direction is not direction:
                continue
            if block.reclaim_ts is not None and block.reclaim_ts >= min_ts and block.is_active:
                return True
        return False

    def prune_state(self) -> None:
        if len(self.fvg_zones) > self.max_active_zones:
            self.fvg_zones = self.fvg_zones[-self.max_active_zones :]
        if len(self.breaker_blocks) > self.max_active_zones:
            self.breaker_blocks = self.breaker_blocks[-self.max_active_zones :]
        if len(self.liquidity_pools) > self.max_active_pools:
            self.liquidity_pools = self.liquidity_pools[-self.max_active_pools :]
        if len(self.swings_highs) > self.max_active_pools:
            self.swings_highs = self.swings_highs[-self.max_active_pools :]
        if len(self.swings_lows) > self.max_active_pools:
            self.swings_lows = self.swings_lows[-self.max_active_pools :]

