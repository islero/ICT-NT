from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
from nautilus_trader.model import Bar, BarType, InstrumentId, QuoteTick
from nautilus_trader.trading import Strategy
from nautilus_trader.trading.config import StrategyConfig

from core import SharedState
from core.enums import MoneyManagementType, RuleSignal
from core.rules import RuleBase
from strategies.ict_smc_components import (
    BosDetector,
    BreakerBlockDetector,
    FvgDetector,
    IctSmcRuntimeState,
    LiquidityPoolDetector,
    LiquiditySide,
    MitigationMode,
    PendingSetup,
    TradeDirection,
    ZoneReference,
    ZoneType,
    detect_local_sweep,
    is_displacement_candle,
)
from strategies.ict_smc_components.utils import (
    calculate_atr,
    infer_bar_interval_ns,
    is_within_session,
    nearest_above,
    nearest_below,
    overlaps_zone,
    session_day_key,
    to_price_bar,
)
from strategies.ict_smc_strategy_rules_adapter import IctSmcStrategyRulesAdapter


class IctSmcStrategyConfig(StrategyConfig, frozen=True):
    """Configuration for a deterministic ICT/SMC 1H+5m strategy."""

    instrument_id: InstrumentId
    base_bar_type: BarType
    htf_bar_type: BarType
    ltf_bar_type: BarType
    is_backtest: bool = True

    # Warmup / subscriptions
    warmup_lookback_days: int = 120

    # Risk and sizing (delegated to EntryTradingRule)
    money_management_type: MoneyManagementType = MoneyManagementType.FIXED_RISK_PERCENT
    fixed_lot: float = 1.0
    fixed_risk_percent: float = 1.0
    use_take_profit_order: bool = True

    # HTF detectors (1H)
    htf_pivot_left: int = 2
    htf_pivot_right: int = 2
    htf_bos_close_break_atr_mult: float = 0.0
    htf_atr_period: int = 14
    htf_fvg_mitigation_mode: str = "midpoint"
    htf_liquidity_min_points: int = 2
    htf_liquidity_atr_tolerance_mult: float = 0.15
    htf_liquidity_swing_lookback: int = 25
    htf_breaker_source_lookback: int = 12
    htf_recent_liquidity_sweep_bars: int = 8
    htf_breaker_reclaim_valid_bars: int = 6
    htf_liquidity_sweep_buffer_atr_mult: float = 0.05

    # LTF trigger (5m)
    ltf_atr_period: int = 14
    ltf_displacement_body_atr_mult: float = 1.2
    ltf_local_sweep_lookback: int = 8
    ltf_setup_expiry_bars: int = 3
    ltf_interval_minutes_fallback: int = 5
    entry_buffer_atr_mult: float = 0.02
    stop_buffer_atr_mult: float = 0.05
    zone_touch_tolerance_atr_mult: float = 0.10

    # Risk/exit
    min_risk_reward: float = 1.0
    fallback_risk_reward: float = 2.0

    # Trade governance
    session_timezone: str = "America/New_York"
    session_start: str = "09:30"
    session_end: str = "16:00"
    max_trades_per_day: int = 2
    cooldown_bars: int = 6
    max_open_positions: int = 1


class IctSmcStrategy(Strategy):
    """ICT strategy with causal 1H context and 5m confirmation.

    Why no external SMC library:
    - Many SMC libraries detect structure using future candles or redraw zones.
    - This implementation enforces causal updates on closed bars only, making
      backtests and live behavior consistent and auditable.
    """

    def __init__(self, config: IctSmcStrategyConfig):
        super().__init__(config)

        self.shared_state = SharedState()
        RuleBase.configure_environment(is_backtest=config.is_backtest)

        mitigation_mode = self._parse_mitigation_mode(config.htf_fvg_mitigation_mode)
        self._state = IctSmcRuntimeState()
        self._fvg_detector = FvgDetector(mitigation_mode=mitigation_mode)
        self._bos_detector = BosDetector(
            left=config.htf_pivot_left,
            right=config.htf_pivot_right,
            close_break_atr_mult=config.htf_bos_close_break_atr_mult,
        )
        self._liquidity_detector = LiquidityPoolDetector(
            min_points=config.htf_liquidity_min_points,
            atr_tolerance_mult=config.htf_liquidity_atr_tolerance_mult,
            swing_lookback=config.htf_liquidity_swing_lookback,
        )
        self._breaker_detector = BreakerBlockDetector(source_lookback=config.htf_breaker_source_lookback)
        self._rules_adapter = IctSmcStrategyRulesAdapter(
            shared_state=self.shared_state,
            strategy=self,
            instrument_id=config.instrument_id,
            money_management_type=config.money_management_type,
            fixed_lot=config.fixed_lot,
            fixed_risk_percent=config.fixed_risk_percent,
            use_take_profit_order=config.use_take_profit_order,
        )

        self._htf_key = str(config.htf_bar_type.standard())
        self._ltf_key = str(config.ltf_bar_type.standard())
        self._subscribed_bar_types: list[BarType] = []

    @staticmethod
    def _parse_mitigation_mode(raw_value: str) -> MitigationMode:
        value = (raw_value or "").strip().lower()
        mapping = {
            MitigationMode.TOUCH.value: MitigationMode.TOUCH,
            MitigationMode.MIDPOINT.value: MitigationMode.MIDPOINT,
            MitigationMode.FULL_FILL.value: MitigationMode.FULL_FILL,
        }
        return mapping.get(value, MitigationMode.MIDPOINT)

    def on_start(self) -> None:
        now_ts = pd.Timestamp(self.clock.timestamp_ns(), tz="UTC", unit="ns")
        start_time = (now_ts - pd.Timedelta(days=self.config.warmup_lookback_days)).normalize()

        to_subscribe = self._deduplicate_bar_types([self.config.ltf_bar_type, self.config.htf_bar_type])
        if self.config.is_backtest:
            self.request_aggregated_bars(to_subscribe, start=start_time, update_subscriptions=True)
        else:
            for bar_type in to_subscribe:
                self.request_bars(bar_type, start=start_time, limit=3000)

        for bar_type in to_subscribe:
            self.subscribe_bars(bar_type)
        self._subscribed_bar_types = to_subscribe

    def on_stop(self) -> None:
        for bar_type in self._subscribed_bar_types:
            try:
                self.unsubscribe_bars(bar_type)
            except Exception:
                pass

    @staticmethod
    def _deduplicate_bar_types(bar_types: list[BarType]) -> list[BarType]:
        unique: dict[str, BarType] = {}
        for bar_type in bar_types:
            unique[str(bar_type.standard())] = bar_type
        return list(unique.values())

    def on_quote_tick(self, tick: QuoteTick) -> None:
        self._rules_adapter.sync_on_quote_tick(tick)

    def on_bar(self, bar: Bar) -> None:
        self._rules_adapter.sync_orders()
        bar_key = str(bar.bar_type.standard())

        if bar_key == self._htf_key:
            self._handle_htf_bar(bar)
            return

        if bar_key == self._ltf_key:
            self._handle_ltf_bar(bar)
            return

    def _handle_htf_bar(self, bar: Bar) -> None:
        htf_bar = to_price_bar(bar)
        self._state.append_htf_bar(htf_bar)
        htf_bars = list(self._state.htf_bars)
        self._state.htf_atr = calculate_atr(htf_bars, self.config.htf_atr_period)

        self._fvg_detector.on_new_bar(htf_bars, self._state.fvg_zones)

        bos_event = self._bos_detector.on_new_bar(htf_bars, self._state.htf_atr)
        self._state.swings_highs = list(self._bos_detector.swing_highs)
        self._state.swings_lows = list(self._bos_detector.swing_lows)
        if bos_event is not None:
            self._state.record_bos(bos_event)
            breaker = self._breaker_detector.on_bos_event(bos_event, htf_bars, self._state.breaker_blocks)
            if breaker is not None:
                self._state.breaker_blocks.append(breaker)

        self._state.liquidity_pools = self._liquidity_detector.rebuild(
            swing_highs=self._state.swings_highs,
            swing_lows=self._state.swings_lows,
            atr=self._state.htf_atr,
            existing_pools=self._state.liquidity_pools,
        )
        sweep_buffer = (self._state.htf_atr or 0.0) * self.config.htf_liquidity_sweep_buffer_atr_mult
        self._liquidity_detector.mark_sweeps(htf_bar, self._state.liquidity_pools, sweep_buffer=sweep_buffer)
        self._breaker_detector.update_status(htf_bar, self._state.breaker_blocks)
        self._state.prune_state()

    def _handle_ltf_bar(self, bar: Bar) -> None:
        ltf_bar = to_price_bar(bar)
        self._state.append_ltf_bar(ltf_bar)
        ltf_bars = list(self._state.ltf_bars)
        self._state.ltf_atr = calculate_atr(ltf_bars, self.config.ltf_atr_period)
        day_key = session_day_key(ltf_bar.ts_init, self.config.session_timezone)

        if self._state.pending_setup and ltf_bar.ts_init > self._state.pending_setup.expires_ts:
            self._state.clear_pending_setup()

        if self._state.pending_setup is not None:
            if self._is_pending_setup_triggered(self._state.pending_setup, ltf_bar):
                self._execute_setup(self._state.pending_setup, ltf_bar, bar, day_key)
            return

        if not self._can_open_new_trade(ltf_bar.ts_init, day_key):
            return

        setup = self._build_pending_setup(ltf_bar)
        if setup is not None:
            self._state.pending_setup = setup

    def _can_open_new_trade(self, ts_ns: int, day_key: str) -> bool:
        if not is_within_session(
            ts_ns=ts_ns,
            timezone=self.config.session_timezone,
            session_start=self.config.session_start,
            session_end=self.config.session_end,
        ):
            return False

        if self._state.trades_today(day_key) >= self.config.max_trades_per_day:
            return False

        if self._state.last_trade_ltf_index is not None:
            bars_since_last_trade = self._state.ltf_index - self._state.last_trade_ltf_index
            if bars_since_last_trade <= self.config.cooldown_bars:
                return False

        if self._rules_adapter.has_active_order_groups():
            return False

        if self._open_positions_count() >= self.config.max_open_positions:
            return False

        return True

    def _open_positions_count(self) -> int:
        positions = self.cache.positions_open()
        if not positions:
            return 0
        instrument_key = str(self.config.instrument_id)
        return sum(1 for pos in positions if str(getattr(pos, "instrument_id", "")) == instrument_key)

    def _build_pending_setup(self, bar) -> PendingSetup | None:
        direction_candidates: list[TradeDirection]
        if self._state.bias is TradeDirection.LONG:
            direction_candidates = [TradeDirection.LONG, TradeDirection.SHORT]
        elif self._state.bias is TradeDirection.SHORT:
            direction_candidates = [TradeDirection.SHORT, TradeDirection.LONG]
        else:
            direction_candidates = [TradeDirection.LONG, TradeDirection.SHORT]

        for direction in direction_candidates:
            if not self._has_directional_context(direction):
                continue
            setup = self._build_directional_setup(bar, direction)
            if setup is not None:
                return setup
        return None

    def _has_directional_context(self, direction: TradeDirection) -> bool:
        if self._state.bias is direction:
            return True
        min_ts = self._threshold_ts_from_htf_lookback(self.config.htf_breaker_reclaim_valid_bars)
        return self._state.has_recent_breaker_reclaim(direction, min_ts)

    def _threshold_ts_from_htf_lookback(self, bars_lookback: int) -> int:
        htf_bars = list(self._state.htf_bars)
        if not htf_bars:
            return 0
        index = max(0, len(htf_bars) - bars_lookback)
        return htf_bars[index].ts_init

    def _build_directional_setup(self, bar, direction: TradeDirection) -> PendingSetup | None:
        zone = self._find_tapped_zone(direction, bar)
        if zone is None:
            return None

        htf_sweep = self._has_recent_htf_sweep(direction)
        local_sweep, local_sweep_level = detect_local_sweep(
            bars=list(self._state.ltf_bars),
            direction=direction,
            lookback=self.config.ltf_local_sweep_lookback,
        )
        if not (htf_sweep or local_sweep):
            return None

        ltf_bars = list(self._state.ltf_bars)
        if len(ltf_bars) < 2:
            return None

        previous = ltf_bars[-2]
        if not is_displacement_candle(
            current=bar,
            previous=previous,
            atr=self._state.ltf_atr,
            direction=direction,
            body_atr_mult=self.config.ltf_displacement_body_atr_mult,
        ):
            return None

        atr_for_offsets = self._state.ltf_atr or 0.0
        entry_buffer = atr_for_offsets * self.config.entry_buffer_atr_mult
        stop_buffer = max(self._state.ltf_atr or 0.0, self._state.htf_atr or 0.0) * self.config.stop_buffer_atr_mult
        interval_ns = infer_bar_interval_ns(ltf_bars)
        if interval_ns <= 0:
            interval_ns = self.config.ltf_interval_minutes_fallback * 60 * 1_000_000_000

        if direction is TradeDirection.LONG:
            confirmation = bar.high + entry_buffer
            base_stop = min(zone.bottom, local_sweep_level if local_sweep else bar.low)
            stop_price = base_stop - stop_buffer
            sweep_price = local_sweep_level if local_sweep else bar.low
            if stop_price >= confirmation:
                return None
        else:
            confirmation = bar.low - entry_buffer
            base_stop = max(zone.top, local_sweep_level if local_sweep else bar.high)
            stop_price = base_stop + stop_buffer
            sweep_price = local_sweep_level if local_sweep else bar.high
            if stop_price <= confirmation:
                return None

        return PendingSetup(
            direction=direction,
            zone=zone,
            confirmation_price=confirmation,
            stop_price=stop_price,
            sweep_price=sweep_price,
            created_ts=bar.ts_init,
            expires_ts=bar.ts_init + (self.config.ltf_setup_expiry_bars * interval_ns),
        )

    def _find_tapped_zone(self, direction: TradeDirection, ltf_bar) -> ZoneReference | None:
        tolerance = (self._state.htf_atr or 0.0) * self.config.zone_touch_tolerance_atr_mult
        candidates: list[ZoneReference] = []

        for zone in self._state.fvg_zones:
            if zone.direction is not direction or not zone.is_active:
                continue
            if overlaps_zone(ltf_bar.low, ltf_bar.high, zone.bottom, zone.top, tolerance=tolerance):
                candidates.append(
                    ZoneReference(
                        zone_id=zone.zone_id,
                        zone_type=ZoneType.FVG,
                        direction=direction,
                        bottom=zone.bottom,
                        top=zone.top,
                    )
                )

        for block in self._state.breaker_blocks:
            if block.direction is not direction or not block.is_active:
                continue
            if overlaps_zone(ltf_bar.low, ltf_bar.high, block.bottom, block.top, tolerance=tolerance):
                candidates.append(
                    ZoneReference(
                        zone_id=block.block_id,
                        zone_type=ZoneType.BREAKER,
                        direction=direction,
                        bottom=block.bottom,
                        top=block.top,
                    )
                )

        if not candidates:
            return None

        def zone_distance(candidate: ZoneReference) -> float:
            midpoint = (candidate.bottom + candidate.top) / 2.0
            return abs(midpoint - ltf_bar.close)

        return min(candidates, key=zone_distance)

    def _has_recent_htf_sweep(self, direction: TradeDirection) -> bool:
        needed_side = LiquiditySide.SELL_SIDE if direction is TradeDirection.LONG else LiquiditySide.BUY_SIDE
        threshold_ts = self._threshold_ts_from_htf_lookback(self.config.htf_recent_liquidity_sweep_bars)
        for pool in self._state.liquidity_pools:
            if pool.side is not needed_side:
                continue
            if pool.swept and pool.sweep_ts is not None and pool.sweep_ts >= threshold_ts:
                return True
        return False

    @staticmethod
    def _is_pending_setup_triggered(setup: PendingSetup, bar) -> bool:
        if setup.direction is TradeDirection.LONG:
            return bar.high >= setup.confirmation_price
        if setup.direction is TradeDirection.SHORT:
            return bar.low <= setup.confirmation_price
        return False

    def _execute_setup(self, setup: PendingSetup, ltf_bar, raw_bar: Bar, day_key: str) -> None:
        entry_price = setup.confirmation_price
        stop_price = setup.stop_price
        tp_price = self._compute_take_profit(
            direction=setup.direction,
            entry_price=entry_price,
            stop_price=stop_price,
        )

        if setup.direction is TradeDirection.LONG:
            if stop_price >= entry_price or tp_price <= entry_price:
                self._state.clear_pending_setup()
                return
            signal = RuleSignal.BUY
        else:
            if stop_price <= entry_price or tp_price >= entry_price:
                self._state.clear_pending_setup()
                return
            signal = RuleSignal.SELL

        submitted = self._rules_adapter.submit_entry_with_brackets(
            signal=signal,
            stop_price=stop_price,
            take_profit_price=tp_price,
            bar=raw_bar,
        )
        if submitted:
            self._state.register_trade(day_key)
        self._state.clear_pending_setup()

    def _compute_take_profit(self, direction: TradeDirection, entry_price: float, stop_price: float) -> float:
        risk = abs(entry_price - stop_price)
        if risk <= 0:
            return entry_price

        min_rr = max(1.0, self.config.min_risk_reward)
        fallback_rr = max(min_rr, self.config.fallback_risk_reward)

        if direction is TradeDirection.LONG:
            levels = [
                pool.price
                for pool in self._state.liquidity_pools
                if pool.side is LiquiditySide.BUY_SIDE and not pool.swept
            ]
            target = nearest_above(levels, entry_price)
            minimum_target = entry_price + (min_rr * risk)
            fallback_target = entry_price + (fallback_rr * risk)
            if target is None:
                return fallback_target
            return max(target, minimum_target)

        levels = [
            pool.price
            for pool in self._state.liquidity_pools
            if pool.side is LiquiditySide.SELL_SIDE and not pool.swept
        ]
        target = nearest_below(levels, entry_price)
        minimum_target = entry_price - (min_rr * risk)
        fallback_target = entry_price - (fallback_rr * risk)
        if target is None:
            return fallback_target
        return min(target, minimum_target)

