from __future__ import annotations

from typing import Iterable, Sequence

from strategies.ict_smc_components.models import (
    BosEvent,
    BreakerBlock,
    FvgZone,
    LiquidityPool,
    LiquiditySide,
    MitigationMode,
    PriceBar,
    SwingPoint,
    SwingType,
    TradeDirection,
)
from strategies.ict_smc_components.utils import is_pivot_high, is_pivot_low


class FvgDetector:
    """Detects 3-candle fair value gaps on closed HTF bars.

    Assumption (deterministic ICT interpretation):
    - Bullish FVG: candle_1.high < candle_3.low
    - Bearish FVG: candle_1.low > candle_3.high
    - Zones remain active after midpoint mitigation and only deactivate on full fill.
    """

    def __init__(self, mitigation_mode: MitigationMode = MitigationMode.MIDPOINT):
        self._mitigation_mode = mitigation_mode
        self._seen_zone_ids: set[str] = set()

    def on_new_bar(self, bars: Sequence[PriceBar], zones: list[FvgZone]) -> FvgZone | None:
        if len(bars) < 3:
            return None

        c1, c2, c3 = bars[-3], bars[-2], bars[-1]
        created: FvgZone | None = None

        if c1.high < c3.low:
            zone = FvgZone(
                zone_id=f"fvg:bull:{c2.ts_init}",
                direction=TradeDirection.LONG,
                bottom=c1.high,
                top=c3.low,
                created_ts=c3.ts_init,
                mitigation_mode=self._mitigation_mode,
            )
            created = self._append_if_new(zone, zones)
        elif c1.low > c3.high:
            zone = FvgZone(
                zone_id=f"fvg:bear:{c2.ts_init}",
                direction=TradeDirection.SHORT,
                bottom=c3.high,
                top=c1.low,
                created_ts=c3.ts_init,
                mitigation_mode=self._mitigation_mode,
            )
            created = self._append_if_new(zone, zones)

        self._update_zone_status(c3, zones)
        return created

    def _append_if_new(self, zone: FvgZone, zones: list[FvgZone]) -> FvgZone | None:
        if zone.zone_id in self._seen_zone_ids:
            return None
        self._seen_zone_ids.add(zone.zone_id)
        zones.append(zone)
        return zone

    def _update_zone_status(self, bar: PriceBar, zones: list[FvgZone]) -> None:
        for zone in zones:
            if zone.filled:
                continue

            overlaps = bar.high >= zone.bottom and bar.low <= zone.top
            if overlaps:
                zone.touches += 1

            if zone.direction is TradeDirection.LONG and bar.low <= zone.bottom:
                zone.filled = True
                zone.filled_ts = bar.ts_init
            elif zone.direction is TradeDirection.SHORT and bar.high >= zone.top:
                zone.filled = True
                zone.filled_ts = bar.ts_init

            if zone.mitigated:
                continue

            if zone.mitigation_mode is MitigationMode.TOUCH and overlaps:
                zone.mitigated = True
                zone.mitigation_ts = bar.ts_init
                continue

            if zone.mitigation_mode is MitigationMode.MIDPOINT:
                if zone.direction is TradeDirection.LONG and bar.low <= zone.midpoint:
                    zone.mitigated = True
                    zone.mitigation_ts = bar.ts_init
                elif zone.direction is TradeDirection.SHORT and bar.high >= zone.midpoint:
                    zone.mitigated = True
                    zone.mitigation_ts = bar.ts_init
                continue

            if zone.mitigation_mode is MitigationMode.FULL_FILL and zone.filled:
                zone.mitigated = True
                zone.mitigation_ts = bar.ts_init


class BosDetector:
    """Causal BOS detector using pivot confirmation.

    Assumption:
    - A swing forms only after `right` bars close (no forward leak in live).
    - BOS requires close beyond the last protected swing by optional ATR buffer.
    """

    def __init__(self, left: int = 2, right: int = 2, close_break_atr_mult: float = 0.0):
        self.left = left
        self.right = right
        self.close_break_atr_mult = close_break_atr_mult

        self.swing_highs: list[SwingPoint] = []
        self.swing_lows: list[SwingPoint] = []
        self._confirmed_pivot_indices: set[int] = set()
        self._broken_high_ids: set[str] = set()
        self._broken_low_ids: set[str] = set()

    def on_new_bar(self, bars: Sequence[PriceBar], atr: float | None) -> BosEvent | None:
        self._update_confirmed_swings(bars)
        return self._detect_bos(bars, atr)

    def _update_confirmed_swings(self, bars: Sequence[PriceBar]) -> None:
        if len(bars) < self.left + self.right + 1:
            return

        pivot_index = len(bars) - 1 - self.right
        if pivot_index in self._confirmed_pivot_indices:
            return

        pivot_bar = bars[pivot_index]
        if is_pivot_high(bars, pivot_index, self.left, self.right):
            self.swing_highs.append(
                SwingPoint(
                    swing_id=f"swing:high:{pivot_bar.ts_init}",
                    ts_init=pivot_bar.ts_init,
                    price=pivot_bar.high,
                    swing_type=SwingType.HIGH,
                    pivot_index=pivot_index,
                )
            )
        if is_pivot_low(bars, pivot_index, self.left, self.right):
            self.swing_lows.append(
                SwingPoint(
                    swing_id=f"swing:low:{pivot_bar.ts_init}",
                    ts_init=pivot_bar.ts_init,
                    price=pivot_bar.low,
                    swing_type=SwingType.LOW,
                    pivot_index=pivot_index,
                )
            )

        self._confirmed_pivot_indices.add(pivot_index)

    def _detect_bos(self, bars: Sequence[PriceBar], atr: float | None) -> BosEvent | None:
        if not bars:
            return None

        latest = bars[-1]
        break_buffer = (atr or 0.0) * self.close_break_atr_mult

        if self.swing_highs:
            protected_high = self.swing_highs[-1]
            if (
                latest.close > protected_high.price + break_buffer
                and protected_high.swing_id not in self._broken_high_ids
            ):
                self._broken_high_ids.add(protected_high.swing_id)
                return BosEvent(
                    event_id=f"bos:bull:{latest.ts_init}",
                    direction=TradeDirection.LONG,
                    ts_init=latest.ts_init,
                    close_price=latest.close,
                    broken_swing_id=protected_high.swing_id,
                    broken_swing_price=protected_high.price,
                )

        if self.swing_lows:
            protected_low = self.swing_lows[-1]
            if (
                latest.close < protected_low.price - break_buffer
                and protected_low.swing_id not in self._broken_low_ids
            ):
                self._broken_low_ids.add(protected_low.swing_id)
                return BosEvent(
                    event_id=f"bos:bear:{latest.ts_init}",
                    direction=TradeDirection.SHORT,
                    ts_init=latest.ts_init,
                    close_price=latest.close,
                    broken_swing_id=protected_low.swing_id,
                    broken_swing_price=protected_low.price,
                )

        return None


class LiquidityPoolDetector:
    """Equal highs/lows clustering using local ATR-based tolerance."""

    def __init__(self, min_points: int = 2, atr_tolerance_mult: float = 0.15, swing_lookback: int = 25):
        self.min_points = max(2, min_points)
        self.atr_tolerance_mult = max(0.0, atr_tolerance_mult)
        self.swing_lookback = max(5, swing_lookback)

    def rebuild(
        self,
        swing_highs: Sequence[SwingPoint],
        swing_lows: Sequence[SwingPoint],
        atr: float | None,
        existing_pools: Sequence[LiquidityPool],
    ) -> list[LiquidityPool]:
        tolerance = max((atr or 0.0) * self.atr_tolerance_mult, 1e-9)

        highs_slice = list(swing_highs[-self.swing_lookback :])
        lows_slice = list(swing_lows[-self.swing_lookback :])

        new_pools: list[LiquidityPool] = []
        new_pools.extend(self._to_pools(self._cluster_by_price(highs_slice, tolerance), LiquiditySide.BUY_SIDE, tolerance))
        new_pools.extend(self._to_pools(self._cluster_by_price(lows_slice, tolerance), LiquiditySide.SELL_SIDE, tolerance))

        previous = {pool.pool_id: pool for pool in existing_pools}
        merged: list[LiquidityPool] = []
        for pool in new_pools:
            prev = previous.get(pool.pool_id)
            if prev is not None:
                pool.swept = prev.swept
                pool.sweep_ts = prev.sweep_ts
            merged.append(pool)
        return merged

    def _cluster_by_price(self, points: Sequence[SwingPoint], tolerance: float) -> list[list[SwingPoint]]:
        if len(points) < self.min_points:
            return []

        sorted_points = sorted(points, key=lambda p: p.price)
        clusters: list[list[SwingPoint]] = []
        current: list[SwingPoint] = [sorted_points[0]]

        for point in sorted_points[1:]:
            center = sum(x.price for x in current) / len(current)
            if abs(point.price - center) <= tolerance:
                current.append(point)
                continue

            if len(current) >= self.min_points:
                clusters.append(current.copy())
            current = [point]

        if len(current) >= self.min_points:
            clusters.append(current.copy())

        return clusters

    def _to_pools(
        self,
        clusters: Iterable[list[SwingPoint]],
        side: LiquiditySide,
        tolerance: float,
    ) -> list[LiquidityPool]:
        pools: list[LiquidityPool] = []
        for cluster in clusters:
            cluster_sorted = sorted(cluster, key=lambda x: x.ts_init)
            price = sum(x.price for x in cluster_sorted) / len(cluster_sorted)
            created_ts = cluster_sorted[0].ts_init
            last_seen_ts = cluster_sorted[-1].ts_init
            cluster_key = ",".join(x.swing_id for x in cluster_sorted)
            pool_id = f"pool:{side.value}:{cluster_key}"
            pools.append(
                LiquidityPool(
                    pool_id=pool_id,
                    side=side,
                    price=price,
                    tolerance=tolerance,
                    created_ts=created_ts,
                    last_seen_ts=last_seen_ts,
                    points_count=len(cluster_sorted),
                )
            )
        return pools

    def mark_sweeps(self, bar: PriceBar, pools: list[LiquidityPool], sweep_buffer: float = 0.0) -> None:
        for pool in pools:
            if pool.swept:
                continue

            if pool.side is LiquiditySide.BUY_SIDE and bar.high > pool.price + sweep_buffer:
                pool.swept = True
                pool.sweep_ts = bar.ts_init
            elif pool.side is LiquiditySide.SELL_SIDE and bar.low < pool.price - sweep_buffer:
                pool.swept = True
                pool.sweep_ts = bar.ts_init


class BreakerBlockDetector:
    """Breaker block detector derived from BOS displacement context.

    Assumption:
    - Bullish breaker: last bearish candle before bullish BOS.
    - Bearish breaker: last bullish candle before bearish BOS.
    - Reclaim event is a return into the breaker with a directional close away.
    """

    def __init__(self, source_lookback: int = 12):
        self.source_lookback = max(3, source_lookback)

    def on_bos_event(
        self,
        bos_event: BosEvent,
        bars: Sequence[PriceBar],
        existing_blocks: Sequence[BreakerBlock],
    ) -> BreakerBlock | None:
        if len(bars) < 2:
            return None

        recent = list(bars[:-1])[-self.source_lookback :]
        source: PriceBar | None = None
        if bos_event.direction is TradeDirection.LONG:
            for bar in reversed(recent):
                if bar.is_bearish:
                    source = bar
                    break
        elif bos_event.direction is TradeDirection.SHORT:
            for bar in reversed(recent):
                if bar.is_bullish:
                    source = bar
                    break

        if source is None:
            return None

        block = BreakerBlock(
            block_id=f"breaker:{bos_event.event_id}",
            direction=bos_event.direction,
            bottom=source.low,
            top=source.high,
            source_ts=source.ts_init,
            created_ts=bos_event.ts_init,
        )
        if any(existing.block_id == block.block_id for existing in existing_blocks):
            return None
        return block

    def update_status(self, bar: PriceBar, blocks: list[BreakerBlock]) -> None:
        for block in blocks:
            if block.invalidated:
                continue

            if block.direction is TradeDirection.LONG:
                if bar.close < block.bottom:
                    block.invalidated = True
                    block.invalidated_ts = bar.ts_init
                    continue
                if block.reclaim_ts is None and bar.low <= block.top and bar.close > block.top:
                    block.reclaim_ts = bar.ts_init
            else:
                if bar.close > block.top:
                    block.invalidated = True
                    block.invalidated_ts = bar.ts_init
                    continue
                if block.reclaim_ts is None and bar.high >= block.bottom and bar.close < block.bottom:
                    block.reclaim_ts = bar.ts_init


def detect_local_sweep(
    bars: Sequence[PriceBar],
    direction: TradeDirection,
    lookback: int,
) -> tuple[bool, float]:
    """Detect local 5m liquidity sweep with immediate close-back confirmation."""
    if lookback < 2 or len(bars) < lookback + 1:
        return False, 0.0

    current = bars[-1]
    history = bars[-(lookback + 1) : -1]

    if direction is TradeDirection.LONG:
        prior_low = min(bar.low for bar in history)
        swept = current.low < prior_low and current.close > prior_low
        return swept, prior_low

    if direction is TradeDirection.SHORT:
        prior_high = max(bar.high for bar in history)
        swept = current.high > prior_high and current.close < prior_high
        return swept, prior_high

    return False, 0.0


def is_displacement_candle(
    current: PriceBar,
    previous: PriceBar,
    atr: float | None,
    direction: TradeDirection,
    body_atr_mult: float,
) -> bool:
    """LTF displacement confirmation used as ICT trigger.

    Assumption:
    - Body must exceed `body_atr_mult * ATR(5m)`.
    - For longs, close must also clear previous high.
    - For shorts, close must clear previous low.
    """
    if atr is None or atr <= 0:
        return False

    body_ok = current.body >= atr * body_atr_mult
    if not body_ok:
        return False

    if direction is TradeDirection.LONG:
        return current.is_bullish and current.close > previous.high

    if direction is TradeDirection.SHORT:
        return current.is_bearish and current.close < previous.low

    return False

