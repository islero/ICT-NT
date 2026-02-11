from __future__ import annotations

from enum import Enum
from typing import Optional

from nautilus_trader.indicators.base import Indicator
from nautilus_trader.model.data import Bar


class Trend(Enum):
    """Market trend direction."""

    UNDEFINED = 0
    UP = 1
    DOWN = -1


class SmartPivotPoints(Indicator):
    """
    Smart Pivot Points indicator that identifies Major Market Structure (HH, HL, LH, LL)
    by filtering out minor internal structure.

    Logic:
    - A Major Lower High (LH) is confirmed ONLY when the price breaks below the previous Major Low (LL).
    - A Major Higher Low (HL) is confirmed ONLY when the price breaks above the previous Major High (HH).
    - This effectively filters out complex pullbacks that do not change the major trend.

    Attributes:
        trend (Trend): Trend.UP for Uptrend, Trend.DOWN for Downtrend, Trend.UNDEFINED for Undefined.
        major_high (float): Price of the active Major High.
        major_low (float): Price of the active Major Low.
    """

    def __init__(self) -> None:
        super().__init__([])  # No specific params for now, strictly structure based

        # State
        self._trend: Trend = Trend.UNDEFINED

        # Major Structure (The "Range" we are trading in)
        self._major_high: Optional[float] = None
        self._major_low: Optional[float] = None

        # Live tracking for candidates during a move/pullback
        # In a Downtrend (Trend=-1):
        #   - We are looking for the lowest point (new LL candidate)
        #   - We are monitoring the pullback high (candidate LH)
        self._candidate_high: Optional[float] = None
        self._candidate_low: Optional[float] = None

        # Output / Signals (set to True for one bar when confirmed)
        self._new_major_high: bool = False
        self._new_major_low: bool = False

    def handle_bar(self, bar: Bar) -> None:
        # Reset signal flags
        self._new_major_high = False
        self._new_major_low = False

        if self._trend == Trend.UNDEFINED:
            self._initialize_trend(bar)
            return

        # ---------------------------------------------------------------------
        # DOWNTREND LOGIC
        # ---------------------------------------------------------------------
        if self._trend == Trend.DOWN:
            # 1. Update Candidate Low (The lowest point of the current move)
            if self._major_low is None or bar.low < self._major_low:
                # We are making new lows (continuation), so the BOS point moves down
                self._major_low = bar.low
                # Reset candidate high because we just made a lower low,
                # so any high AFTER this new low will be the start of a new pullback.
                self._candidate_high = bar.high

            # 2. Track the Pullback High (Candidate LH)
            # We track the highest high seen SINCE the `major_low` was established.
            if bar.high > self._candidate_high:
                self._candidate_high = bar.high

            # 3. Check for REVERSAL CANDIDATE (Break of Major High)
            # If price breaks ABOVE the confirmed Major High, trend might chance.
            # However, standard structure requires a HL then a HH.
            # OR typically "Trend Change" is purely if closes above Major High.
            # Let's assume standard aggressive reversal: Close > Major High = TREND CHANGE.

            if self._major_high and bar.close > self._major_high:
                self._switch_to_uptrend(bar)
                return

            # Note: In a pure downtrend, we "Confirm" a LH when we break the LL.
            # But here we are already IN the downtrend.
            # If we were tracking a pullback, and now we break the `major_low` again:
            # That `candidate_high` BECOMES the new `major_high`.
            # Wait, `major_low` tracks the absolute lowest.
            # We need to track a "Confirmed Major Low" vs "Current Price".
            pass

        # ---------------------------------------------------------------------
        # OPTIMIZED LOGIC REWRITE
        # ---------------------------------------------------------------------
        # My logic above has a flaw: `major_low` keeps sliding down.
        # I need to distinguish between "Previous Confirmed Major Low" (the break level)
        # and "Current Working Low".

    def _initialize_trend(self, bar: Bar):
        # Simple initialization: assume the first bar sets boundaries
        if self._major_high is None:
            self._major_high = bar.high
            self._major_low = bar.low
            self._candidate_high = bar.high
            self._candidate_low = bar.low
            return

        # If we break out of initial range, start trend
        if bar.close > self._major_high:
            self._trend = Trend.UP
            self._major_low = self._candidate_low  # This becomes the HL
            self._major_high = bar.high  # Current high
            self._new_major_low = True  # We confirmed a low by breaking high
        elif bar.close < self._major_low:
            self._trend = Trend.DOWN
            self._major_high = self._candidate_high  # This becomes the LH
            self._major_low = bar.low  # Current low
            self._new_major_high = True  # We confirmed a high by breaking low

        # Always update candidates
        if bar.high > self._candidate_high:
            self._candidate_high = bar.high
        if bar.low < self._candidate_low:
            self._candidate_low = bar.low

    def handle_bar_optimized(self, bar: Bar):
        """
        Re-implementing the core logic to be cleaner.
        Reference: Smart Pivot Structure
        """
        self._new_major_high = False
        self._new_major_low = False

        if self._trend == Trend.UNDEFINED:
            self._initialize_trend(bar)
            return

        if self._trend == Trend.DOWN:  # DOWNTREND
            # Logic: We have a confirmed MAJOR HIGH (LH) and a provisional MAJOR LOW (LL).

            # 1. Check for Reversal (Model: Close > Major High)
            if bar.close > self._major_high:
                # TREND CHANGE TO UP
                self._trend = Trend.UP
                # The lowest point we ever reached is the Major Low
                # The current move up is establishing a new Major High
                self._major_low = self._candidate_low  # Finalize the LL
                self._new_major_low = True  # Alert

                # Reset for Uptrend
                self._major_high = bar.high  # New working HH
                self._candidate_low = bar.low  # Reset pullback tracker
                return

            # 2. Update Working Major Low (LL)
            # If we are pushing lower, simply update the LL
            if bar.low < self._major_low:
                self._major_low = bar.low
                # Since we are making new lows, the 'pullback' starts from here.
                # Any high tracked purely during the previous consolidation is now 'locked in'
                # effectively as part of the leg down, or we reset the candidate high.
                # Actually, if we just made a new low, the highest point SINCE the PREVIOUS BOS
                # was the Lower High.
                # BUT, we handle "Confirmation" at the moment of the break.
                # If we are already below the old low, we are just extending the impulse.
                self._candidate_high = bar.high  # Reset pullback high tracker

            else:
                # We are in a potential pullback (trading above Major Low, below Major High)
                # Update candidate_high (potential LH)
                if bar.high > self._candidate_high:
                    self._candidate_high = bar.high

                # WAIT: When do we confirm a NEW Lower High?
                # We confirm a NEW LH when price breaks the CURRENT Major Low.
                # But we just updated Major Low instantly above.
                # CONSTANT updating of Major Low means we never "Break" it in a structural sense
                # to confirm a pullback.
                # We need to lock the "Previous Major Low".
                pass

    # -------------------------------------------------------------------------
    # FINAL LOGIC IMPLEMENTATION
    # -------------------------------------------------------------------------
    # To detect a BOS, we must have a "Locked" Major Low that acts as support.
    # When price rallies (pullback), it sets a "Candidate LH".
    # When price eventually turns down and BREAKS the "Locked" Major Low,
    # THEN "Candidate LH" becomes "Confirmed Major High" (New LH).
    # And the price level at the break becomes the start of the new "Locked Major Low".

    def handle_bar_final(self, bar: Bar) -> None:
        self._new_major_high = False
        self._new_major_low = False

        # Ensure all state is initialized before using min/max and comparisons.
        if (
            self._major_high is None
            or self._major_low is None
            or self._candidate_high is None
            or self._candidate_low is None
        ):
            self._major_high = bar.high
            self._major_low = bar.low
            self._candidate_high = bar.high
            self._candidate_low = bar.low
            return

        if self._trend == Trend.UNDEFINED:
            # Initialization phase
            if bar.close > self._major_high:
                self._trend = Trend.UP
                # The low during this range is the first HL
                self._major_low = self._candidate_low
                self._new_major_low = True

                # Current bar sets the new working High
                self._major_high = bar.high
                self._candidate_low = bar.low  # Reset pullback tracker

            elif bar.close < self._major_low:
                self._trend = Trend.DOWN
                # The high during this range is the first LH
                self._major_high = self._candidate_high
                self._new_major_high = True

                # Current bar sets the new working Low
                self._major_low = bar.low
                self._candidate_high = bar.high  # Reset pullback tracker

            else:
                # Still in initial range, just expand range
                self._major_high = bar.high if self._major_high is None else max(self._major_high, bar.high)
                self._major_low = bar.low if self._major_low is None else min(self._major_low, bar.low)
                self._candidate_high = bar.high if self._candidate_high is None else max(self._candidate_high, bar.high)
                self._candidate_low = bar.low if self._candidate_low is None else min(self._candidate_low, bar.low)
            return

        # ---------------------------------------------------------------------
        # DOWNTREND (Trend = -1)
        # ---------------------------------------------------------------------
        if self._trend == Trend.DOWN:
            # 1. Check for Reversal (Break of Major LH)
            if bar.close > self._major_high:
                self._trend = Trend.UP
                # The lowest point found during the downtrend becomes the Major Low (Higher Low base)
                # Actually, the lowest point was `major_low` (working variable).
                # CONFIRM IT.
                # New trend started.
                self._new_major_low = True  # Confirmed the bottom

                # Set up for Uptrend
                self._major_low = self._major_low  # Stays as the bottom
                self._major_high = bar.high  # Current high is new working HH
                self._candidate_low = bar.low
                return

            # 2. Check for Break of Structure (Continuation Down)
            if bar.close < self._major_low:
                # We broke the support.
                # This confirms that the highest point seen since the last low (candidate_high)
                # is indeed the new Major Lower High.

                # Check if we actually had a pullback (candidate_high > major_low)
                # If we are just crashing bar after bar, candidate_high might be the previous bar high.

                # CONFIRM NEW LH
                self._major_high = self._candidate_high
                self._new_major_high = True

                # Update Major Low to current (working)
                self._major_low = bar.low

                # Reset pullback tracker
                self._candidate_high = bar.high
            else:
                # Inside range or pullback
                # 1. Update working low if we wick lower but don't close (optional, or stick to close?)
                # Usually structural low is the absolute low.
                if bar.low < self._major_low:
                    self._major_low = bar.low
                    # If we extend the low, the pullback high reset?
                    # No, usually we want the high of the *structure* between two lows.
                    # If we make a lower low, the potential LH point moves to "current bar high"
                    # ONLY IF we consider the previous move a "micro pullback".
                    # Let's simple keep candidate_high tracking:
                    self._candidate_high = bar.high  # Reset, because a lower low implies impulse.

                # 2. Update Pullback High
                if bar.high > self._candidate_high:
                    self._candidate_high = bar.high

        # ---------------------------------------------------------------------
        # UPTREND (Trend = 1)
        # ---------------------------------------------------------------------
        elif self._trend == Trend.UP:
            # 1. Check for Reversal (Break of Major HL)
            if bar.close < self._major_low:
                self._trend = Trend.DOWN
                # The highest point found becomes Major High (Lower High base)
                self._new_major_high = True  # Confirmed the top

                # Set up for Downtrend
                self._major_high = self._major_high
                self._major_low = bar.low  # Working LL
                self._candidate_high = bar.high
                return

            # 2. Check for BOS (Continuation Up)
            if bar.close > self._major_high:
                # We broke resistance.
                # Confirms candidate_low is the new Major Higher Low.
                self._major_low = self._candidate_low
                self._new_major_low = True

                # Update working Major High
                self._major_high = bar.high

                # Reset pullback tracker
                self._candidate_low = bar.low
            else:
                # Inside range or pullback
                if bar.high > self._major_high:
                    self._major_high = bar.high
                    self._candidate_low = bar.low  # Reset, impulse extended

                if bar.low < self._candidate_low:
                    self._candidate_low = bar.low

    def handle_trade_tick(self, tick) -> None:
        pass

    def handle_quote_tick(self, tick) -> None:
        pass

    def reset(self) -> None:
        super().reset()
        self._trend = Trend.UNDEFINED
        self._major_high = None
        self._major_low = None
        self._candidate_high = None
        self._candidate_low = None
        self._new_major_high = False
        self._new_major_low = False

    @property
    def trend(self) -> Trend:
        return self._trend

    @property
    def major_high(self) -> Optional[float]:
        return self._major_high

    @property
    def major_low(self) -> Optional[float]:
        return self._major_low

    @property
    def is_new_major_high(self) -> bool:
        return self._new_major_high

    @property
    def is_new_major_low(self) -> bool:
        return self._new_major_low

    # Wire up the optimized logic
    handle_bar = handle_bar_final
