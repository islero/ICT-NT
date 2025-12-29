"""
FVG (Fair Value Gap) Entry Rule.

This rule triggers entries when:
1. An active Fair Value Gap exists
2. Price forms an engulfing pattern with body fully inside the FVG bounds
3. Direction aligns with FVG direction and bias filters

The rule sets ENTRY_RULE_SIGNAL, ENTRY_SL_PRICE, and EXPECTED_TARGET_* for
validation by RewardRiskRatioRule.
"""

from dataclasses import dataclass
from typing import Optional, List

import pandas as pd
from nautilus_trader.model import Bar, BarType, InstrumentId
from nautilus_trader.trading import Strategy

from constants.shared_dict_key import SharedDictKey
from core import SharedState
from core.constants import SharedDictKeyBase
from core.enums import RuleSignal
from core.rules import RuleBase
from indicators.fair_value_gap import FairValueGap, FvgDirection, FvgRecord


@dataclass
class FvgRuleConfig:
    """
    Configuration for FVG Entry Rule.

    Attributes:
        bar_type: Bar type for evaluation (usually base timeframe).
        instrument_id: Instrument to trade.
        fvg_bar_type: Bar type for FVG indicator. If None, uses bar_type.
        max_signal_age_bars: Maximum bars since FVG formed to still be valid.
        allow_long: Whether to allow long signals.
        allow_short: Whether to allow short signals.
        sl_buffer_points: Buffer beyond FVG boundary for stop-loss.
        risk_reward_ratio: Risk/reward ratio for take-profit calculation.
        respect_bias_filters: Check DAILY/WEEKLY blocking flags.
        min_fvg_distance_percent: Minimum FVG size filter (percentage).
    """
    bar_type: BarType
    instrument_id: InstrumentId
    fvg_bar_type: BarType
    max_signal_age_bars: int = 1
    allow_long: bool = True
    allow_short: bool = True
    sl_buffer_points: float = 0.0
    risk_reward_ratio: float = 2.0
    respect_bias_filters: bool = True
    min_fvg_distance_percent: float = 0.0


class FvgRule(RuleBase):
    """
    FVG Entry Rule combining Fair Value Gap with engulfing pattern detection.

    This rule triggers entries when:
    1. An active Fair Value Gap exists (from FairValueGap indicator)
    2. Price forms an engulfing pattern (current bar engulfs previous bar body)
    3. The engulfing bar body is fully inside the FVG bounds
    4. Direction aligns (bullish FVG + bullish engulfing = LONG)
    5. Bias filters allow the direction (if respect_bias_filters=True)

    Entry signal handshake:
    - Sets ENTRY_RULE_SIGNAL (RuleSignal.BUY or RuleSignal.SELL)
    - Sets ENTRY_SL_PRICE (FVG boundary + buffer)
    - Sets EXPECTED_TARGET_LATEST_PIVOT_HIGH/LOW_PRICE (based on risk/reward ratio)

    Attributes:
        strategy: The parent strategy instance.
        config: Rule configuration.
    """

    def __init__(
        self,
        shared_state: SharedState,
        strategy: Strategy,
        config: FvgRuleConfig,
    ):
        super().__init__(shared_state)
        self.strategy = strategy
        self.config = config

        # Initialize FVG indicator
        self._fvg_indicator = FairValueGap(
            min_distance_percent=config.min_fvg_distance_percent
        )

        # Track previous bar for engulfing detection
        self._prev_bar: Optional[Bar] = None

        # Track bars processed for FVG age calculation
        self._bars_processed: int = 0
        self._fvg_detection_bar_count: dict[int, int] = {}  # middle_candle_time -> bar count

        # First bar initialization flag
        self.first_bar_initialized: bool = False

        # Track FVGs already used for entries to avoid repeated signals
        self._used_fvg_keys: set[tuple[int, FvgDirection]] = set()

    def evaluate(self, bar: Bar, current_bar: Bar = None) -> bool:
        """
        Evaluate entry conditions.

        Args:
            bar: The bar being processed.
            current_bar: Optional current bar for real-time price reference.

        Returns:
            bool: True to continue processing chain.
        """
        bar_type_str = str(bar.bar_type)
        entry_bar_type_str = str(self.config.bar_type)
        fvg_bar_type_str = str(self.config.fvg_bar_type) if self.config.fvg_bar_type else entry_bar_type_str

        is_fvg_bar = bar_type_str == fvg_bar_type_str
        is_entry_bar = bar_type_str == entry_bar_type_str

        # Process FVG bar type for FVG detection
        if is_fvg_bar:
            self._bars_processed += 1

            # Feed bar to FVG indicator
            self._fvg_indicator.handle_bar(bar)

            # Track when FVGs are detected
            if self._fvg_indicator.has_new_fvg:
                last_fvg = self._fvg_indicator.last_fvg
                if last_fvg:
                    self._fvg_detection_bar_count[last_fvg.middle_candle_time] = self._bars_processed

        # Process entry bar type for engulfing pattern detection
        if is_entry_bar:
            # Need previous bar for engulfing detection
            if self._prev_bar is None:
                self._prev_bar = bar
                return True

            # Use current_bar for price reference if provided
            eval_bar = current_bar or bar

            # Check for entry signal
            self._check_entry_signal(self._prev_bar, bar, eval_bar)

            # Update previous bar
            self._prev_bar = bar

        return True

    def _check_entry_signal(self, prev_bar: Bar, curr_bar: Bar, price_bar: Bar) -> None:
        """
        Check if entry conditions are met and set entry signal.

        Args:
            prev_bar: Previous bar for engulfing pattern.
            curr_bar: Current bar (the engulfing candle).
            price_bar: Bar to use for price reference (current_bar or bar).
        """
        if not self.shared_state:
            return

        # Check if entry signal already pending
        existing_signal = self.shared_state.get(
            SharedDictKeyBase.ENTRY_RULE_SIGNAL, RuleSignal.NONE
        )
        if existing_signal in (RuleSignal.BUY, RuleSignal.SELL):
            return

        # Get active FVGs
        active_fvgs = self._get_active_fvgs()
        if not active_fvgs:
            return

        # Check for bullish engulfing
        if self._is_bullish_engulfing(prev_bar, curr_bar):
            self._try_long_entry(curr_bar, price_bar, active_fvgs)
            return

        # Check for bearish engulfing
        if self._is_bearish_engulfing(prev_bar, curr_bar):
            self._try_short_entry(curr_bar, price_bar, active_fvgs)
            return

    def _get_active_fvgs(self) -> List[FvgRecord]:
        """
        Get list of active (fresh) FVGs.

        Returns:
            List of FvgRecord objects that are still valid.
        """
        active_fvgs = []

        for fvg in self._fvg_indicator.fvgs:
            detection_bar = self._fvg_detection_bar_count.get(fvg.middle_candle_time, 0)
            bars_since_detection = self._bars_processed - detection_bar

            if bars_since_detection <= self.config.max_signal_age_bars:
                active_fvgs.append(fvg)

        return active_fvgs

    def _is_bullish_engulfing(self, prev_bar: Bar, curr_bar: Bar) -> bool:
        """
        Check if current bar is a bullish engulfing pattern.

        Bullish engulfing:
        - Current bar is bullish (close > open)
        - Current body engulfs previous body:
          - current.open <= previous.close
          - current.close >= previous.open

        Args:
            prev_bar: Previous bar.
            curr_bar: Current bar.

        Returns:
            True if bullish engulfing pattern.
        """
        curr_bullish = float(curr_bar.close) > float(curr_bar.open)
        if not curr_bullish:
            return False

        # Current body must engulf previous body
        curr_open = float(curr_bar.open)
        curr_close = float(curr_bar.close)
        prev_open = float(prev_bar.open)
        prev_close = float(prev_bar.close)

        engulfs = curr_open <= prev_close and curr_close >= prev_open
        return engulfs

    def _is_bearish_engulfing(self, prev_bar: Bar, curr_bar: Bar) -> bool:
        """
        Check if current bar is a bearish engulfing pattern.

        Bearish engulfing:
        - Current bar is bearish (close < open)
        - Current body engulfs previous body:
          - current.open >= previous.close
          - current.close <= previous.open

        Args:
            prev_bar: Previous bar.
            curr_bar: Current bar.

        Returns:
            True if bearish engulfing pattern.
        """
        curr_bearish = float(curr_bar.close) < float(curr_bar.open)
        if not curr_bearish:
            return False

        # Current body must engulf previous body
        curr_open = float(curr_bar.open)
        curr_close = float(curr_bar.close)
        prev_open = float(prev_bar.open)
        prev_close = float(prev_bar.close)

        engulfs = curr_open >= prev_close and curr_close <= prev_open
        return engulfs

    def _body_inside_fvg(self, bar: Bar, fvg: FvgRecord) -> bool:
        """
        Check if bar body is fully inside FVG bounds.

        Args:
            bar: The bar to check.
            fvg: The FVG record.

        Returns:
            True if bar body is fully inside FVG.
        """
        body_low = min(float(bar.open), float(bar.close))
        body_high = max(float(bar.open), float(bar.close))

        return fvg.fvg_low <= body_low and body_high <= fvg.fvg_high

    def _try_long_entry(
        self,
        engulfing_bar: Bar,
        price_bar: Bar,
        active_fvgs: List[FvgRecord],
    ) -> None:
        """
        Try to create a long entry signal.

        Args:
            engulfing_bar: The bullish engulfing bar.
            price_bar: Bar for price reference.
            active_fvgs: List of active FVG records.
        """
        if not self.config.allow_long:
            return

        # Check bias filters
        if self.config.respect_bias_filters:
            if self._is_long_blocked():
                return

        # Find matching bullish FVG with body inside (skip already-used FVGs)
        matching_fvg = None
        for fvg in active_fvgs:
            if fvg.direction == FvgDirection.BULLISH:
                if (fvg.middle_candle_time, fvg.direction) in self._used_fvg_keys:
                    continue
                if self._body_inside_fvg(engulfing_bar, fvg):
                    matching_fvg = fvg
                    break

        if matching_fvg is None:
            return

        # Calculate SL and TP
        current_price = float(price_bar.close)
        sl_price = matching_fvg.fvg_low
        
        # Validate SL
        if sl_price >= current_price:
            return

        tp_price = current_price + (
            self.config.risk_reward_ratio * abs(current_price - sl_price)
        )

        # Mark FVG as used and set entry signal
        if self.shared_state is not None:
            self._used_fvg_keys.add((matching_fvg.middle_candle_time, matching_fvg.direction))
            self.shared_state.set(SharedDictKeyBase.ENTRY_RULE_SIGNAL, RuleSignal.BUY)
            self.shared_state.set(SharedDictKeyBase.ENTRY_SL_PRICE, sl_price)
            self.shared_state.set(SharedDictKey.EXPECTED_TARGET_LATEST_PIVOT_HIGH_PRICE, tp_price)

    def _try_short_entry(
        self,
        engulfing_bar: Bar,
        price_bar: Bar,
        active_fvgs: List[FvgRecord],
    ) -> None:
        """
        Try to create a short entry signal.

        Args:
            engulfing_bar: The bearish engulfing bar.
            price_bar: Bar for price reference.
            active_fvgs: List of active FVG records.
        """
        if not self.config.allow_short:
            return

        # Check bias filters
        if self.config.respect_bias_filters:
            if self._is_short_blocked():
                return

        # Find matching bearish FVG with body inside (skip already-used FVGs)
        matching_fvg = None
        for fvg in active_fvgs:
            if fvg.direction == FvgDirection.BEARISH:
                if (fvg.middle_candle_time, fvg.direction) in self._used_fvg_keys:
                    continue
                if self._body_inside_fvg(engulfing_bar, fvg):
                    matching_fvg = fvg
                    break

        if matching_fvg is None:
            return

        # Calculate SL and TP
        current_price = float(price_bar.close)
        sl_price = matching_fvg.fvg_high

        # Validate SL
        if sl_price <= current_price:
            return

        tp_price = current_price - (
            self.config.risk_reward_ratio * abs(sl_price - current_price)
        )

        # Mark FVG as used and set entry signal
        if self.shared_state is not None:
            self._used_fvg_keys.add((matching_fvg.middle_candle_time, matching_fvg.direction))
            self.shared_state.set(SharedDictKeyBase.ENTRY_RULE_SIGNAL, RuleSignal.SELL)
            self.shared_state.set(SharedDictKeyBase.ENTRY_SL_PRICE, sl_price)
            self.shared_state.set(SharedDictKey.EXPECTED_TARGET_LATEST_PIVOT_LOW_PRICE, tp_price)

    def _is_long_blocked(self) -> bool:
        """
        Check if long entries are blocked by bias filters.

        Returns:
            True if longs are blocked.
        """
        if not self.shared_state:
            return False

        daily_blocks = self.shared_state.get(SharedDictKey.DAILY_BLOCK_LONGS, False)
        weekly_blocks = self.shared_state.get(SharedDictKey.WEEKLY_BLOCK_LONGS, False)

        return daily_blocks or weekly_blocks

    def _is_short_blocked(self) -> bool:
        """
        Check if short entries are blocked by bias filters.

        Returns:
            True if shorts are blocked.
        """
        if not self.shared_state:
            return False

        daily_blocks = self.shared_state.get(SharedDictKey.DAILY_BLOCK_SHORTS, False)
        weekly_blocks = self.shared_state.get(SharedDictKey.WEEKLY_BLOCK_SHORTS, False)

        return daily_blocks or weekly_blocks

    def on_register_indicator_for_bars(self) -> None:
        """Register FVG indicator for bar updates."""
        self.strategy.register_indicator_for_bars(self.config.fvg_bar_type, self._fvg_indicator)

    def on_start(self) -> None:
        """Actions to be performed on strategy start."""
        # Check if shared_state is available
        if self.shared_state is None:
            return

        # Setting the warmed-up and subscribed bar type
        key = SharedDictKeyBase.WARMED_UP_AND_SUBSCRIBED_BAR_TYPES
        lst = self.shared_state.get(key, [])
        if not lst:  # if the key was missing, we got the default []
            self.shared_state.set(key, lst)

        # add if not already there (avoid duplicates)
        if self.config.fvg_bar_type.standard() not in lst:
            lst.append(self.config.fvg_bar_type.standard())

            now_ts = pd.Timestamp(self.strategy.clock.timestamp_ns(), tz="UTC", unit="ns")
            start_time = (now_ts - pd.Timedelta(days=89)).normalize()

            if self.is_backtest_mode:
                self.strategy.request_aggregated_bars([self.config.fvg_bar_type], start=start_time, update_subscriptions=True)
            else:  # live trading mode
                self.strategy.request_bars(self.config.fvg_bar_type, start=start_time, limit=1000)

            self.strategy.subscribe_bars(self.config.fvg_bar_type)

    def on_stop(self) -> None:
        """Actions to be performed on strategy stop."""
        self.strategy.unsubscribe_bars(self.config.fvg_bar_type)

        # Check if shared_state is available
        if self.shared_state is None:
            return
        
        # remove the bar type from a list
        key = SharedDictKeyBase.WARMED_UP_AND_SUBSCRIBED_BAR_TYPES
        lst = self.shared_state.get(key, [])
        if lst and self.config.fvg_bar_type.standard() in lst:
            lst.remove(self.config.fvg_bar_type.standard())
