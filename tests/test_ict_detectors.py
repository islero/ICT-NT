import os
import sys

# Allow importing project modules
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from strategies.ict_smc_components.detectors import (
    BosDetector,
    BreakerBlockDetector,
    FvgDetector,
    LiquidityPoolDetector,
)
from strategies.ict_smc_components.models import (
    BosEvent,
    LiquiditySide,
    MitigationMode,
    PriceBar,
    SwingPoint,
    SwingType,
    TradeDirection,
)


def _bar(ts: int, o: float, h: float, l: float, c: float) -> PriceBar:
    return PriceBar(ts_init=ts, open=o, high=h, low=l, close=c)


def test_fvg_detector_creates_bullish_zone_and_marks_midpoint_mitigation():
    detector = FvgDetector(mitigation_mode=MitigationMode.MIDPOINT)
    zones = []
    bars = [
        _bar(1, 95, 100, 90, 98),
        _bar(2, 99, 104, 97, 103),
        _bar(3, 105, 110, 105, 109),  # bullish FVG: c1.high(100) < c3.low(105)
    ]

    for idx in range(len(bars)):
        detector.on_new_bar(bars=bars[: idx + 1], zones=zones)

    assert len(zones) == 1
    zone = zones[0]
    assert zone.direction is TradeDirection.LONG
    assert zone.bottom == 100
    assert zone.top == 105
    assert zone.mitigated is False

    # 50% fill is enough for mitigation (midpoint = 102.5), full fill not reached.
    detector.on_new_bar(
        bars=[bars[1], bars[2], _bar(4, 108, 109, 102.4, 107)],
        zones=zones,
    )
    assert zone.mitigated is True
    assert zone.filled is False


def test_bos_detector_confirms_pivot_and_detects_bullish_break():
    detector = BosDetector(left=1, right=1)
    bars = [
        _bar(1, 97, 100, 95, 99),
        _bar(2, 100, 106, 98, 105),  # pivot high candidate
        _bar(3, 104, 103, 97, 98),  # confirms pivot high at ts=2
        _bar(4, 99, 108, 99, 107),  # close breaks above pivot high => bullish BOS
    ]

    event = None
    for i in range(len(bars)):
        event = detector.on_new_bar(bars[: i + 1], atr=None) or event

    assert len(detector.swing_highs) >= 1
    assert event is not None
    assert event.direction is TradeDirection.LONG
    assert event.broken_swing_price == 106


def test_liquidity_pool_detector_clusters_equal_highs_and_marks_sweep():
    detector = LiquidityPoolDetector(min_points=2, atr_tolerance_mult=0.15, swing_lookback=10)
    highs = [
        SwingPoint("h1", 1, 110.0, SwingType.HIGH, 1),
        SwingPoint("h2", 2, 110.3, SwingType.HIGH, 2),
        SwingPoint("h3", 3, 109.9, SwingType.HIGH, 3),
    ]
    lows = [
        SwingPoint("l1", 4, 100.0, SwingType.LOW, 4),
        SwingPoint("l2", 5, 99.8, SwingType.LOW, 5),
    ]

    pools = detector.rebuild(highs, lows, atr=4.0, existing_pools=[])
    assert any(pool.side is LiquiditySide.BUY_SIDE for pool in pools)

    detector.mark_sweeps(_bar(6, 109, 111.5, 108, 111), pools, sweep_buffer=0.1)
    buy_side = [pool for pool in pools if pool.side is LiquiditySide.BUY_SIDE][0]
    assert buy_side.swept is True
    assert buy_side.sweep_ts == 6


def test_breaker_detector_creates_and_updates_bullish_block():
    detector = BreakerBlockDetector(source_lookback=6)
    bars = [
        _bar(1, 105, 106, 99, 100),  # last bearish candle before bullish BOS
        _bar(2, 100, 104, 99, 103),
        _bar(3, 103, 109, 102, 108),
    ]
    bos = BosEvent(
        event_id="bos:bull:3",
        direction=TradeDirection.LONG,
        ts_init=3,
        close_price=108,
        broken_swing_id="swing:high:2",
        broken_swing_price=104,
    )

    block = detector.on_bos_event(bos, bars, existing_blocks=[])
    assert block is not None
    assert block.direction is TradeDirection.LONG
    assert block.bottom == 99
    assert block.top == 106

    blocks = [block]
    detector.update_status(_bar(4, 106.2, 107.1, 105.5, 106.8), blocks)
    assert block.reclaim_ts == 4

    detector.update_status(_bar(5, 101, 102, 98.5, 98.8), blocks)
    assert block.invalidated is True
