from __future__ import annotations

from datetime import time as dt_time
from typing import TYPE_CHECKING, Any, Iterable, Sequence

import pandas as pd

from strategies.ict_smc_components.models import PriceBar

if TYPE_CHECKING:
    from nautilus_trader.model import Bar
else:
    Bar = Any


def to_float(value) -> float:
    """Convert Nautilus scalar-like values to float safely."""
    return float(value)


def to_price_bar(bar: Bar) -> PriceBar:
    """Convert Nautilus Bar to a pure-python bar for deterministic detectors."""
    return PriceBar(
        ts_init=bar.ts_init,
        open=to_float(bar.open),
        high=to_float(bar.high),
        low=to_float(bar.low),
        close=to_float(bar.close),
    )


def calculate_true_range(current: PriceBar, previous_close: float) -> float:
    return max(
        current.high - current.low,
        abs(current.high - previous_close),
        abs(current.low - previous_close),
    )


def calculate_atr(bars: Sequence[PriceBar], period: int) -> float | None:
    """Wilder-style ATR over closed bars."""
    if period <= 0 or len(bars) < period + 1:
        return None

    trs: list[float] = []
    for i in range(1, len(bars)):
        trs.append(calculate_true_range(bars[i], bars[i - 1].close))

    if len(trs) < period:
        return None

    seed = sum(trs[:period]) / period
    atr = seed
    for tr in trs[period:]:
        atr = ((atr * (period - 1)) + tr) / period
    return atr


def is_pivot_high(bars: Sequence[PriceBar], index: int, left: int, right: int) -> bool:
    if index - left < 0 or index + right >= len(bars):
        return False

    pivot_high = bars[index].high
    for i in range(index - left, index + right + 1):
        if i == index:
            continue
        if bars[i].high >= pivot_high:
            return False
    return True


def is_pivot_low(bars: Sequence[PriceBar], index: int, left: int, right: int) -> bool:
    if index - left < 0 or index + right >= len(bars):
        return False

    pivot_low = bars[index].low
    for i in range(index - left, index + right + 1):
        if i == index:
            continue
        if bars[i].low <= pivot_low:
            return False
    return True


def parse_hhmm(value: str) -> dt_time:
    hour, minute = value.split(":")
    return dt_time(hour=int(hour), minute=int(minute))


def timestamp_to_local(ts_ns: int, timezone: str) -> pd.Timestamp:
    return pd.Timestamp(ts_ns, unit="ns", tz="UTC").tz_convert(timezone)


def session_day_key(ts_ns: int, timezone: str) -> str:
    return timestamp_to_local(ts_ns, timezone).strftime("%Y-%m-%d")


def is_within_session(ts_ns: int, timezone: str, session_start: str, session_end: str) -> bool:
    """Session gate with support for both intraday and overnight windows."""
    local_dt = timestamp_to_local(ts_ns, timezone)
    current_t = local_dt.time()
    start_t = parse_hhmm(session_start)
    end_t = parse_hhmm(session_end)

    if start_t <= end_t:
        return start_t <= current_t <= end_t
    return current_t >= start_t or current_t <= end_t


def overlaps_zone(bar_low: float, bar_high: float, zone_bottom: float, zone_top: float, tolerance: float = 0.0) -> bool:
    lower = zone_bottom - tolerance
    upper = zone_top + tolerance
    return bar_high >= lower and bar_low <= upper


def nearest_above(levels: Iterable[float], price: float) -> float | None:
    candidates = [x for x in levels if x > price]
    return min(candidates) if candidates else None


def nearest_below(levels: Iterable[float], price: float) -> float | None:
    candidates = [x for x in levels if x < price]
    return max(candidates) if candidates else None


def infer_bar_interval_ns(bars: Sequence[PriceBar]) -> int:
    if len(bars) < 2:
        return 0
    return max(0, bars[-1].ts_init - bars[-2].ts_init)
