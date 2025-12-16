"""
Daily Bias Rule for ICT Trading.

This rule determines the daily directional bias (bullish/bearish/neutral) using
ICT concepts and provides consistent, configurable outputs to downstream rules
and strategies.

Daily Bias Role in the System:
- Weekly: WHERE trades make sense (macro filter)
- Daily: WHAT direction to trade (operational bias) <- THIS RULE
- H4/H1: HOW price is delivering (path)
- M15/M5: WHEN to enter (execution)

IMPORTANT: This is a CONTEXT/FILTER rule ONLY.
It does NOT generate entry signals or execute trades.

Key Features:
- Daily structure detection via SmartPivotPoints
- Displacement confirmation (strong-bodied candles, FVG creation)
- Premium/Discount zone awareness via FibonacciLevels
- Weekly block reconciliation (respects higher timeframe context)
- Configurable gating pipeline for bias determination
- Reason codes for transparency and debugging
- Confidence levels for downstream filtering

Output Signals (via SharedState):
- DAILY_BIAS: Operational bias ("bullish", "bearish", "neutral")
- DAILY_STRUCTURE: Market structure ("bullish", "bearish", "neutral")
- DAILY_ZONE: Current price zone ("premium", "discount", "equilibrium", "unknown")
- DAILY_BLOCK_LONGS: True if long trades should be blocked
- DAILY_BLOCK_SHORTS: True if short trades should be blocked
- DAILY_RECOMMENDED_ENTRY_PRICE: Recommended entry price (OTE level)
- DAILY_DEALING_RANGE_HIGH/LOW: Dealing range boundaries
- DAILY_EQUILIBRIUM: 50% level
- DAILY_OTE_HIGH/LOW: OTE zone boundaries
- DAILY_BIAS_CONFIDENCE: "low" | "medium" | "high"
- DAILY_BIAS_REASON_CODES: List of reason tokens
- DAILY_DISPLACEMENT_DETECTED: True if displacement was detected
- DAILY_LAST_FVG_DIRECTION: Direction of last FVG if any

Bias Determination Pipeline:
1. Determine daily structure from SmartPivotPoints
2. Check for displacement confirmation (if enabled)
3. Check zone/OTE confluence (if enabled)
4. Reconcile with weekly blocks (if enabled)
5. Apply staleness guard
6. Output final bias with confidence and reasons
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, List

from nautilus_trader.model import Bar, BarType
from nautilus_trader.trading import Strategy

from constants.shared_dict_key import SharedDictKey
from core import SharedState
from core.rules.rule_base import RuleBase
from indicators.smart_pivot_points import SmartPivotPoints, Trend
from indicators.fibonacci_levels import FibonacciLevels, TradeDirection, PriceZone
from indicators.fair_value_gap import FairValueGap, FvgDirection


class DailyBias(Enum):
    """Daily operational bias classification."""
    NEUTRAL = "neutral"
    BULLISH = "bullish"
    BEARISH = "bearish"


class DailyStructure(Enum):
    """Daily market structure classification."""
    NEUTRAL = "neutral"
    BULLISH = "bullish"
    BEARISH = "bearish"


class DailyZone(Enum):
    """Daily price zone classification."""
    UNKNOWN = "unknown"
    DISCOUNT = "discount"
    PREMIUM = "premium"
    EQUILIBRIUM = "equilibrium"


class BiasConfidence(Enum):
    """Confidence level for the daily bias."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


# Reason code constants for transparency
class ReasonCode:
    """Reason codes for bias determination."""
    STRUCT_BULL = "STRUCT_BULL"
    STRUCT_BEAR = "STRUCT_BEAR"
    STRUCT_NEUTRAL = "STRUCT_NEUTRAL"
    DISPLACEMENT_UP = "DISPLACEMENT_UP"
    DISPLACEMENT_DOWN = "DISPLACEMENT_DOWN"
    NO_DISPLACEMENT = "NO_DISPLACEMENT"
    IN_DISCOUNT = "IN_DISCOUNT"
    IN_PREMIUM = "IN_PREMIUM"
    IN_OTE = "IN_OTE"
    AT_EQUILIBRIUM = "AT_EQUILIBRIUM"
    ZONE_UNKNOWN = "ZONE_UNKNOWN"
    FVG_BULLISH = "FVG_BULLISH"
    FVG_BEARISH = "FVG_BEARISH"
    WEEKLY_BLOCKS_LONGS = "WEEKLY_BLOCKS_LONGS"
    WEEKLY_BLOCKS_SHORTS = "WEEKLY_BLOCKS_SHORTS"
    WEEKLY_CONFLICT = "WEEKLY_CONFLICT"
    STALE_DATA = "STALE_DATA"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    ZONE_MISMATCH = "ZONE_MISMATCH"
    CANDLE_SEQUENCE_BULLISH = "CANDLE_SEQUENCE_BULLISH"
    CANDLE_SEQUENCE_BEARISH = "CANDLE_SEQUENCE_BEARISH"
    CANDLE_SEQUENCE_NO_LONG = "CANDLE_SEQUENCE_NO_LONG"
    CANDLE_SEQUENCE_NO_SHORT = "CANDLE_SEQUENCE_NO_SHORT"


@dataclass
class DailyBiasRuleConfig:
    """
    Configuration for Daily Bias Rule.

    Parameters:
        bar_type: BarType for the Daily timeframe. MUST be a Daily bar type.
        base_bar_type: Optional lower timeframe for current price reference.
        bias_horizon_days: Number of days the bias is expected to be valid (1-2).
        min_swing_points: Minimum swing points required to classify structure.
        require_displacement: If True, bias requires displacement confirmation.
        displacement_body_ratio: Minimum body-to-range ratio for displacement (0.0-1.0).
        displacement_lookback: Number of bars to look back for displacement.
        require_pd_array_confluence: If True, require PD array (FVG/zone) confluence.
        ote_filter_enabled: If True, prefer OTE zone for bias confirmation.
        ote_levels: Tuple of (low, high) retracement levels for OTE (default 0.62-0.79).
        equilibrium_filter_enabled: If True, consider equilibrium in zone logic.
        neutral_on_conflict: If True, return neutral when evidence conflicts.
        respect_weekly_blocks: If True, reconcile with weekly blocking flags.
        max_bias_age_bars: Staleness guard - max bars since last structure confirmation.
        fvg_min_distance_percent: Minimum FVG size as percentage of price.
        require_candle_sequence: If True, require HH/HL for long bias, LH/LL for short bias.
    """
    bar_type: Optional[BarType] = None
    base_bar_type: Optional[BarType] = None
    bias_horizon_days: int = 1
    min_swing_points: int = 2
    require_displacement: bool = False
    displacement_body_ratio: float = 0.6
    displacement_lookback: int = 3
    require_pd_array_confluence: bool = False
    ote_filter_enabled: bool = False
    ote_levels: tuple = (0.62, 0.79)
    equilibrium_filter_enabled: bool = False
    neutral_on_conflict: bool = True
    respect_weekly_blocks: bool = True
    max_bias_age_bars: int = 3
    fvg_min_distance_percent: float = 0.0
    require_candle_sequence: bool = False  # Require HH/HL for longs, LH/LL for shorts


class DailyBiasRule(RuleBase):
    """
    Daily Bias Context Rule using SmartPivotPoints, Fibonacci, and FVG.

    This rule provides the daily operational bias for trade filtering.
    It determines WHAT direction to trade based on:
    - Daily market structure (bullish/bearish/neutral)
    - Displacement confirmation (strong moves, FVG creation)
    - Premium/Discount zone context
    - Weekly timeframe reconciliation

    The bias is computed via a gated pipeline that scores multiple factors
    and produces a deterministic, explainable output.

    IMPORTANT: This is a CONTEXT/FILTER rule ONLY.
    It does NOT generate entry signals or execute trades.

    Usage:
    1. Create with Daily bar type configuration
    2. Rule automatically detects Daily structure and bias
    3. Check block_longs/block_shorts flags before taking trades
    4. Use bias_confidence to filter low-confidence situations
    5. Inspect reason_codes for debugging and optimization

    Attributes:
        daily_bias: Current operational bias (bullish/bearish/neutral)
        daily_structure: Current structure from SmartPivotPoints
        daily_zone: Current price zone classification
        block_longs: True if long trades should be avoided
        block_shorts: True if short trades should be avoided
        bias_confidence: Confidence level (low/medium/high)
        reason_codes: List of reason tokens explaining the bias
    """

    def __init__(
        self,
        shared_state: SharedState,
        strategy: Strategy,
        config: DailyBiasRuleConfig
    ):
        super().__init__(shared_state)
        self.strategy = strategy
        self.config = config

        # Initialize indicators
        self.smart_pivot_points = SmartPivotPoints()
        self.fibonacci_levels = FibonacciLevels()
        self.fvg_indicator = FairValueGap(min_distance_percent=config.fvg_min_distance_percent)

        # Internal state
        self.first_bar_initialized = False
        self._last_close_price: Optional[float] = None
        self._bars_since_structure_change: int = 0
        self._recent_bars: List[Bar] = []  # For displacement detection

        # Computed state (exposed via properties)
        self._daily_bias: DailyBias = DailyBias.NEUTRAL
        self._daily_structure: DailyStructure = DailyStructure.NEUTRAL
        self._daily_zone: DailyZone = DailyZone.UNKNOWN
        self._block_longs: bool = False
        self._block_shorts: bool = False
        self._recommended_entry_price: Optional[float] = None
        self._dealing_range_high: Optional[float] = None
        self._dealing_range_low: Optional[float] = None
        self._equilibrium: Optional[float] = None
        self._ote_high: Optional[float] = None
        self._ote_low: Optional[float] = None
        self._bias_confidence: BiasConfidence = BiasConfidence.LOW
        self._reason_codes: List[str] = []
        self._displacement_detected: bool = False
        self._last_fvg_direction: Optional[str] = None

    def evaluate(self, bar: Bar, current_bar: Bar = None) -> bool:
        """
        Evaluate Daily bias from the incoming bar.

        This method implements a gated pipeline:
        1. Update indicators with bar data
        2. Determine daily structure
        3. Check for displacement confirmation
        4. Classify current price zone
        5. Reconcile with weekly blocks
        6. Compute final bias with confidence
        7. Set blocking flags
        8. Save all outputs to shared state

        Args:
            bar: The Daily bar being processed
            current_bar: Optional current bar for real-time price reference

        Returns:
            bool: Always returns True (context rules don't block processing)
        """
        # Determine target bar type
        target_bar_type = self.config.bar_type if self.config.bar_type else bar.bar_type

        # Filter bars - only process matching bar type
        if str(bar.bar_type) not in str(target_bar_type) and self.first_bar_initialized:
            return True

        if not self.first_bar_initialized:
            self.first_bar_initialized = True

        # Reset reason codes for this evaluation
        self._reason_codes = []

        # Track recent bars for displacement detection
        self._update_recent_bars(bar)

        # Store previous trend for structure change detection
        prev_trend = self.smart_pivot_points.trend

        # Update indicators
        self.smart_pivot_points.handle_bar(bar)
        self.fvg_indicator.handle_bar(bar)

        # Track bars since structure change
        if self.smart_pivot_points.trend != prev_trend:
            self._bars_since_structure_change = 0
        else:
            self._bars_since_structure_change += 1

        # Store last close price
        self._last_close_price = float(bar.close)

        # Get current price for zone classification
        current_price = self._get_current_price(bar, current_bar)

        # Step 1: Determine daily structure
        self._update_daily_structure()

        # Step 2: Update Fibonacci levels
        self._update_fibonacci_levels()

        # Step 3: Classify current price zone
        self._update_daily_zone(current_price)

        # Step 4: Check displacement
        self._displacement_detected = self._check_displacement(bar, current_price)

        # Step 5: Track FVG direction
        self._update_fvg_direction()

        # Step 6: Compute daily bias via gated pipeline
        self._compute_daily_bias(current_price)

        # Step 7: Apply blocking logic
        self._update_blocking_flags()

        # Step 8: Save all outputs to shared state
        self._save_to_shared_state()

        return True

    def _update_recent_bars(self, bar: Bar) -> None:
        """Maintain a window of recent bars for displacement detection."""
        self._recent_bars.append(bar)
        max_lookback = max(self.config.displacement_lookback, 5)
        if len(self._recent_bars) > max_lookback:
            self._recent_bars.pop(0)

    def _get_current_price(self, bar: Bar, current_bar: Optional[Bar]) -> float:
        """Get current price for zone classification."""
        if current_bar is not None:
            return float(current_bar.close)
        return float(bar.close)

    def _update_daily_structure(self) -> None:
        """Update daily structure based on SmartPivotPoints trend."""
        trend = self.smart_pivot_points.trend

        if trend == Trend.UP:
            self._daily_structure = DailyStructure.BULLISH
            self._reason_codes.append(ReasonCode.STRUCT_BULL)
        elif trend == Trend.DOWN:
            self._daily_structure = DailyStructure.BEARISH
            self._reason_codes.append(ReasonCode.STRUCT_BEAR)
        else:
            self._daily_structure = DailyStructure.NEUTRAL
            self._reason_codes.append(ReasonCode.STRUCT_NEUTRAL)

    def _update_fibonacci_levels(self) -> None:
        """Update Fibonacci levels based on current dealing range and structure."""
        major_high = self.smart_pivot_points.major_high
        major_low = self.smart_pivot_points.major_low

        if major_high is None or major_low is None:
            self._reset_fibonacci_state()
            return

        if major_low >= major_high:
            self._reset_fibonacci_state()
            return

        # Store dealing range
        self._dealing_range_high = major_high
        self._dealing_range_low = major_low

        # Determine Fibonacci direction based on daily structure
        if self._daily_structure == DailyStructure.BULLISH:
            fib_direction = TradeDirection.BUY
        elif self._daily_structure == DailyStructure.BEARISH:
            fib_direction = TradeDirection.SELL
        else:
            fib_direction = TradeDirection.BUY

        # Update Fibonacci levels
        self.fibonacci_levels.update(
            swing_low=major_low,
            swing_high=major_high,
            direction=fib_direction
        )

        # Extract key levels
        if self.fibonacci_levels.is_valid:
            self._equilibrium = self.fibonacci_levels.equilibrium
            self._recommended_entry_price = self.fibonacci_levels.recommended_entry
            self._ote_high = self.fibonacci_levels.optimal_entry_high
            self._ote_low = self.fibonacci_levels.optimal_entry_low

    def _reset_fibonacci_state(self) -> None:
        """Reset Fibonacci-related state when invalid."""
        self._dealing_range_high = None
        self._dealing_range_low = None
        self._equilibrium = None
        self._recommended_entry_price = None
        self._ote_high = None
        self._ote_low = None
        self.fibonacci_levels.reset()

    def _update_daily_zone(self, current_price: float) -> None:
        """Classify current price into daily zone."""
        if not self.fibonacci_levels.is_valid:
            self._daily_zone = DailyZone.UNKNOWN
            self._reason_codes.append(ReasonCode.ZONE_UNKNOWN)
            return

        zone = self.fibonacci_levels.get_zone(current_price)

        if zone in (PriceZone.DISCOUNT, PriceZone.DEEP_DISCOUNT):
            self._daily_zone = DailyZone.DISCOUNT
            self._reason_codes.append(ReasonCode.IN_DISCOUNT)
        elif zone in (PriceZone.PREMIUM, PriceZone.DEEP_PREMIUM):
            self._daily_zone = DailyZone.PREMIUM
            self._reason_codes.append(ReasonCode.IN_PREMIUM)
        elif zone == PriceZone.EQUILIBRIUM:
            self._daily_zone = DailyZone.EQUILIBRIUM
            self._reason_codes.append(ReasonCode.AT_EQUILIBRIUM)
        else:
            self._daily_zone = DailyZone.UNKNOWN
            self._reason_codes.append(ReasonCode.ZONE_UNKNOWN)

        # Check OTE zone
        if self.fibonacci_levels.is_in_optimal_entry_zone(current_price):
            self._reason_codes.append(ReasonCode.IN_OTE)

    def _check_displacement(self, bar: Bar, current_price: float) -> bool:
        """
        Check for displacement confirmation.

        Displacement in ICT terms:
        - Strong-bodied candle (body > displacement_body_ratio of range)
        - Close beyond prior swing / break of structure
        - Presence of an FVG created in the bias direction

        Returns:
            True if displacement is detected in the bias direction
        """
        if len(self._recent_bars) < 2:
            return False

        # Check for strong body candle (displacement candle)
        body = abs(float(bar.close) - float(bar.open))
        bar_range = float(bar.high) - float(bar.low)

        if bar_range > 0:
            body_ratio = body / bar_range
            is_strong_body = body_ratio >= self.config.displacement_body_ratio
        else:
            is_strong_body = False

        # Check direction of the strong move
        is_bullish_displacement = False
        is_bearish_displacement = False

        if is_strong_body:
            if float(bar.close) > float(bar.open):
                # Bullish candle with strong body
                is_bullish_displacement = True
            else:
                # Bearish candle with strong body
                is_bearish_displacement = True

        # Check for FVG confirmation
        if self.fvg_indicator.has_new_fvg:
            last_fvg = self.fvg_indicator.last_fvg
            if last_fvg is not None:
                if last_fvg.direction == FvgDirection.BULLISH:
                    is_bullish_displacement = True
                elif last_fvg.direction == FvgDirection.BEARISH:
                    is_bearish_displacement = True

        # Check for break of structure (close beyond prior levels)
        if len(self._recent_bars) >= 2:
            prior_bar = self._recent_bars[-2]
            if float(bar.close) > float(prior_bar.high):
                is_bullish_displacement = True
            elif float(bar.close) < float(prior_bar.low):
                is_bearish_displacement = True

        # Add reason codes
        if is_bullish_displacement:
            self._reason_codes.append(ReasonCode.DISPLACEMENT_UP)
            return self._daily_structure == DailyStructure.BULLISH

        if is_bearish_displacement:
            self._reason_codes.append(ReasonCode.DISPLACEMENT_DOWN)
            return self._daily_structure == DailyStructure.BEARISH

        self._reason_codes.append(ReasonCode.NO_DISPLACEMENT)
        return False

    def _update_fvg_direction(self) -> None:
        """Track the direction of the last FVG."""
        if self.fvg_indicator.has_new_fvg:
            last_fvg = self.fvg_indicator.last_fvg
            if last_fvg is not None:
                self._last_fvg_direction = last_fvg.direction.value
                if last_fvg.direction == FvgDirection.BULLISH:
                    self._reason_codes.append(ReasonCode.FVG_BULLISH)
                else:
                    self._reason_codes.append(ReasonCode.FVG_BEARISH)

    def _check_candle_sequence(self) -> tuple[bool, bool]:
        """
        Check if last 2 candles form HH/HL (bullish) or LH/LL (bearish) sequence.

        Returns:
            Tuple of (allows_long, allows_short):
            - allows_long: True if last 2 candles formed higher high AND higher low
            - allows_short: True if last 2 candles formed lower high AND lower low
        """
        if len(self._recent_bars) < 2:
            # Not enough data, allow both directions
            return True, True

        # Get last 2 bars
        prev_bar = self._recent_bars[-2]
        curr_bar = self._recent_bars[-1]

        prev_high = float(prev_bar.high)
        prev_low = float(prev_bar.low)
        curr_high = float(curr_bar.high)
        curr_low = float(curr_bar.low)

        # Check for higher high and higher low (bullish sequence)
        higher_high = curr_high > prev_high
        higher_low = curr_low > prev_low
        allows_long = higher_high and higher_low

        # Check for lower high and lower low (bearish sequence)
        lower_high = curr_high < prev_high
        lower_low = curr_low < prev_low
        allows_short = lower_high and lower_low

        # Add reason codes
        if allows_long:
            self._reason_codes.append(ReasonCode.CANDLE_SEQUENCE_BULLISH)
        elif not allows_long and self._daily_structure == DailyStructure.BULLISH:
            self._reason_codes.append(ReasonCode.CANDLE_SEQUENCE_NO_LONG)

        if allows_short:
            self._reason_codes.append(ReasonCode.CANDLE_SEQUENCE_BEARISH)
        elif not allows_short and self._daily_structure == DailyStructure.BEARISH:
            self._reason_codes.append(ReasonCode.CANDLE_SEQUENCE_NO_SHORT)

        return allows_long, allows_short

    def _compute_daily_bias(self, current_price: float) -> None:
        """
        Compute daily bias via gated decision pipeline.

        Decision logic:
        1. Start with structure-based bias
        2. Gate by candle sequence (HH/HL for longs, LH/LL for shorts)
        3. Gate by displacement (if required)
        4. Gate by zone confluence (if required)
        5. Reconcile with weekly blocks (if enabled)
        6. Apply staleness guard
        7. Compute confidence level
        """
        # Start with structure-based bias
        if self._daily_structure == DailyStructure.BULLISH:
            candidate_bias = DailyBias.BULLISH
        elif self._daily_structure == DailyStructure.BEARISH:
            candidate_bias = DailyBias.BEARISH
        else:
            candidate_bias = DailyBias.NEUTRAL
            self._reason_codes.append(ReasonCode.INSUFFICIENT_DATA)

        # Gate 1: Candle sequence requirement (HH/HL for longs, LH/LL for shorts)
        if self.config.require_candle_sequence and candidate_bias != DailyBias.NEUTRAL:
            allows_long, allows_short = self._check_candle_sequence()
            if candidate_bias == DailyBias.BULLISH and not allows_long:
                candidate_bias = DailyBias.NEUTRAL
            elif candidate_bias == DailyBias.BEARISH and not allows_short:
                candidate_bias = DailyBias.NEUTRAL

        # Gate 2: Displacement requirement
        if self.config.require_displacement and candidate_bias != DailyBias.NEUTRAL:
            if not self._displacement_detected:
                if self.config.neutral_on_conflict:
                    candidate_bias = DailyBias.NEUTRAL

        # Gate 3: Zone confluence (OTE filter)
        if self.config.ote_filter_enabled and candidate_bias != DailyBias.NEUTRAL:
            zone_ok = self._check_zone_confluence(candidate_bias, current_price)
            if not zone_ok and self.config.neutral_on_conflict:
                self._reason_codes.append(ReasonCode.ZONE_MISMATCH)
                candidate_bias = DailyBias.NEUTRAL

        # Gate 4: Weekly reconciliation
        if self.config.respect_weekly_blocks and candidate_bias != DailyBias.NEUTRAL:
            candidate_bias = self._reconcile_with_weekly(candidate_bias)

        # Gate 5: Staleness guard
        if self._bars_since_structure_change > self.config.max_bias_age_bars:
            if candidate_bias != DailyBias.NEUTRAL:
                self._reason_codes.append(ReasonCode.STALE_DATA)
                # Don't force neutral, but reduce confidence

        # Compute confidence
        self._bias_confidence = self._compute_confidence(candidate_bias)

        self._daily_bias = candidate_bias

    def _check_zone_confluence(self, candidate_bias: DailyBias, current_price: float) -> bool:
        """
        Check if the current zone is confluent with the candidate bias.

        For bullish bias: prefer discount or OTE zone
        For bearish bias: prefer premium or OTE zone
        """
        if not self.fibonacci_levels.is_valid:
            return True  # Can't check, allow through

        in_ote = self.fibonacci_levels.is_in_optimal_entry_zone(current_price)

        if candidate_bias == DailyBias.BULLISH:
            # Bullish bias should ideally be in discount or OTE
            return self._daily_zone == DailyZone.DISCOUNT or in_ote

        elif candidate_bias == DailyBias.BEARISH:
            # Bearish bias should ideally be in premium or OTE
            return self._daily_zone == DailyZone.PREMIUM or in_ote

        return True

    def _reconcile_with_weekly(self, candidate_bias: DailyBias) -> DailyBias:
        """
        Reconcile daily bias with weekly blocking flags.

        If weekly blocks longs and daily is bullish -> conflict
        If weekly blocks shorts and daily is bearish -> conflict
        """
        shared_state = self.shared_state
        if shared_state is None:
            return candidate_bias

        weekly_blocks_longs = shared_state.get(SharedDictKey.WEEKLY_BLOCK_LONGS, False)
        weekly_blocks_shorts = shared_state.get(SharedDictKey.WEEKLY_BLOCK_SHORTS, False)

        if weekly_blocks_longs:
            self._reason_codes.append(ReasonCode.WEEKLY_BLOCKS_LONGS)
            if candidate_bias == DailyBias.BULLISH:
                self._reason_codes.append(ReasonCode.WEEKLY_CONFLICT)
                if self.config.neutral_on_conflict:
                    return DailyBias.NEUTRAL

        if weekly_blocks_shorts:
            self._reason_codes.append(ReasonCode.WEEKLY_BLOCKS_SHORTS)
            if candidate_bias == DailyBias.BEARISH:
                self._reason_codes.append(ReasonCode.WEEKLY_CONFLICT)
                if self.config.neutral_on_conflict:
                    return DailyBias.NEUTRAL

        return candidate_bias

    def _compute_confidence(self, bias: DailyBias) -> BiasConfidence:
        """
        Compute confidence level based on evidence strength.

        High confidence:
        - Structure confirmed
        - Displacement detected
        - Zone confluent
        - Fresh data (not stale)

        Medium confidence:
        - Structure confirmed
        - Missing one of: displacement, zone confluence

        Low confidence:
        - Neutral bias
        - Missing multiple confirmations
        - Stale data
        """
        if bias == DailyBias.NEUTRAL:
            return BiasConfidence.LOW

        score = 0

        # Structure confirmation
        if self._daily_structure != DailyStructure.NEUTRAL:
            score += 1

        # Displacement confirmation
        if self._displacement_detected:
            score += 1

        # Zone confluence
        if ReasonCode.IN_OTE in self._reason_codes:
            score += 1
        elif (bias == DailyBias.BULLISH and ReasonCode.IN_DISCOUNT in self._reason_codes):
            score += 1
        elif (bias == DailyBias.BEARISH and ReasonCode.IN_PREMIUM in self._reason_codes):
            score += 1

        # Freshness
        if self._bars_since_structure_change <= 1:
            score += 1

        # Weekly alignment (no conflict)
        if ReasonCode.WEEKLY_CONFLICT not in self._reason_codes:
            score += 1

        if score >= 4:
            return BiasConfidence.HIGH
        elif score >= 2:
            return BiasConfidence.MEDIUM
        else:
            return BiasConfidence.LOW

    def _update_blocking_flags(self) -> None:
        """
        Apply blocking logic based on daily bias.

        - Bullish bias: Block shorts (favor longs)
        - Bearish bias: Block longs (favor shorts)
        - Neutral bias: No blocking
        """
        self._block_longs = True
        self._block_shorts = True

        if self._daily_bias == DailyBias.BULLISH:
            self._block_longs = False
        elif self._daily_bias == DailyBias.BEARISH:
            self._block_shorts = False

    def _save_to_shared_state(self) -> None:
        """Save all computed values to shared state."""
        if self.shared_state is None:
            return
        self.shared_state.set(SharedDictKey.DAILY_BIAS, self._daily_bias.value)
        self.shared_state.set(SharedDictKey.DAILY_STRUCTURE, self._daily_structure.value)
        self.shared_state.set(SharedDictKey.DAILY_ZONE, self._daily_zone.value)
        self.shared_state.set(SharedDictKey.DAILY_BLOCK_LONGS, self._block_longs)
        self.shared_state.set(SharedDictKey.DAILY_BLOCK_SHORTS, self._block_shorts)
        self.shared_state.set(SharedDictKey.DAILY_RECOMMENDED_ENTRY_PRICE, self._recommended_entry_price)
        self.shared_state.set(SharedDictKey.DAILY_DEALING_RANGE_HIGH, self._dealing_range_high)
        self.shared_state.set(SharedDictKey.DAILY_DEALING_RANGE_LOW, self._dealing_range_low)
        self.shared_state.set(SharedDictKey.DAILY_EQUILIBRIUM, self._equilibrium)
        self.shared_state.set(SharedDictKey.DAILY_OTE_HIGH, self._ote_high)
        self.shared_state.set(SharedDictKey.DAILY_OTE_LOW, self._ote_low)
        self.shared_state.set(SharedDictKey.DAILY_BIAS_CONFIDENCE, self._bias_confidence.value)
        self.shared_state.set(SharedDictKey.DAILY_BIAS_REASON_CODES, self._reason_codes.copy())
        self.shared_state.set(SharedDictKey.DAILY_DISPLACEMENT_DETECTED, self._displacement_detected)
        self.shared_state.set(SharedDictKey.DAILY_LAST_FVG_DIRECTION, self._last_fvg_direction)

    def on_register_indicator_for_bars(self) -> None:
        """Register indicators for bar updates before warmup period."""
        bar_type = self.config.bar_type
        if bar_type:
            self.strategy.register_indicator_for_bars(bar_type, self.smart_pivot_points)
            self.strategy.register_indicator_for_bars(bar_type, self.fvg_indicator)

    def on_start(self) -> None:
        """Actions to be performed on strategy start."""
        pass

    def on_stop(self) -> None:
        """Actions to be performed on strategy stop."""
        pass

    # --- Public Properties ---

    @property
    def daily_bias(self) -> DailyBias:
        """Current daily operational bias (bullish/bearish/neutral)."""
        return self._daily_bias

    @property
    def daily_structure(self) -> DailyStructure:
        """Current daily market structure (bullish/bearish/neutral)."""
        return self._daily_structure

    @property
    def daily_zone(self) -> DailyZone:
        """Current price zone (premium/discount/equilibrium/unknown)."""
        return self._daily_zone

    @property
    def block_longs(self) -> bool:
        """True if long trades should be blocked based on daily bias."""
        return self._block_longs

    @property
    def block_shorts(self) -> bool:
        """True if short trades should be blocked based on daily bias."""
        return self._block_shorts

    @property
    def recommended_entry_price(self) -> Optional[float]:
        """Recommended entry price (OTE 70.5% level)."""
        return self._recommended_entry_price

    @property
    def dealing_range_high(self) -> Optional[float]:
        """Upper boundary of the daily dealing range."""
        return self._dealing_range_high

    @property
    def dealing_range_low(self) -> Optional[float]:
        """Lower boundary of the daily dealing range."""
        return self._dealing_range_low

    @property
    def equilibrium(self) -> Optional[float]:
        """50% level of the daily dealing range."""
        return self._equilibrium

    @property
    def ote_high(self) -> Optional[float]:
        """Upper bound of the OTE zone."""
        return self._ote_high

    @property
    def ote_low(self) -> Optional[float]:
        """Lower bound of the OTE zone."""
        return self._ote_low

    @property
    def bias_confidence(self) -> BiasConfidence:
        """Confidence level of the current bias."""
        return self._bias_confidence

    @property
    def reason_codes(self) -> List[str]:
        """List of reason codes explaining the bias determination."""
        return self._reason_codes.copy()

    @property
    def displacement_detected(self) -> bool:
        """True if displacement was detected in the bias direction."""
        return self._displacement_detected

    @property
    def last_fvg_direction(self) -> Optional[str]:
        """Direction of the last detected FVG."""
        return self._last_fvg_direction

    @property
    def trend(self) -> Trend:
        """Raw trend from SmartPivotPoints."""
        return self.smart_pivot_points.trend

    @property
    def bars_since_structure_change(self) -> int:
        """Number of bars since the last structure change."""
        return self._bars_since_structure_change

    def is_favorable_for_longs(self, price: Optional[float] = None) -> bool:
        """
        Check if current context favors long trades.

        Returns True when:
        - Daily bias is bullish
        - Price is in discount zone or OTE

        Args:
            price: Price to check. If None, uses last bar close.
        """
        if self._daily_bias != DailyBias.BULLISH:
            return False

        check_price = price if price is not None else self._last_close_price
        if check_price is None:
            return False

        return self.fibonacci_levels.is_in_discount(check_price) or \
               self.fibonacci_levels.is_in_optimal_entry_zone(check_price)

    def is_favorable_for_shorts(self, price: Optional[float] = None) -> bool:
        """
        Check if current context favors short trades.

        Returns True when:
        - Daily bias is bearish
        - Price is in premium zone or OTE

        Args:
            price: Price to check. If None, uses last bar close.
        """
        if self._daily_bias != DailyBias.BEARISH:
            return False

        check_price = price if price is not None else self._last_close_price
        if check_price is None:
            return False

        return self.fibonacci_levels.is_in_premium(check_price) or \
               self.fibonacci_levels.is_in_optimal_entry_zone(check_price)

    def is_high_confidence(self) -> bool:
        """Check if the current bias has high confidence."""
        return self._bias_confidence == BiasConfidence.HIGH
