from dataclasses import dataclass
from typing import Optional

from nautilus_trader.model import Bar
from nautilus_trader.trading import Strategy

from constants.shared_dict_key import SharedDictKey
from core import SharedState
from core.constants import SharedDictKeyBase
from core.enums import RuleSignal
from core.rules import RuleBase


@dataclass
class RewardRiskRatioRuleConfig:
    """
    Configuration for Reward Risk Ratio Rule.

    Parameters:
        reward_risk_ratio: Minimum required reward to risk ratio (default: 2.0 means 2:1)
    """
    reward_risk_ratio: float = 2.0


class RewardRiskRatioRule(RuleBase):
    """
    Reward Risk Ratio Rule that validates if the potential reward justifies the risk.

    For BUY signals:
        - Reward = Expected Target (Pivot High) - Current Price
        - Risk = Current Price - Stop Loss
        - Ratio = Reward / Risk

    For SELL signals:
        - Reward = Current Price - Expected Target (Pivot Low)
        - Risk = Stop Loss - Current Price
        - Ratio = Reward / Risk

    The rule only passes if the calculated ratio >= configured reward_risk_ratio.
    """

    def __init__(
        self,
        shared_state: SharedState,
        strategy: Strategy,
        config: RewardRiskRatioRuleConfig
    ):
        super().__init__(shared_state)
        self.strategy = strategy
        self.config = config

    def evaluate(self, bar: Bar, current_bar: Bar = None) -> bool:
        """
        Evaluate if the reward/risk ratio meets the minimum requirement.

        Args:
            bar: The bar being processed
            current_bar: The current bar (optional)

        Returns:
            bool: True if ratio meets requirement, False otherwise
        """
        # Validate current bar
        if not current_bar:
            return False

        # Get the turtle soup signal direction
        turtle_soup_signal: Optional[RuleSignal] = self.shared_state.get(
            SharedDictKey.TURTLE_SOUP_RULE_SIGNAL
        )

        if turtle_soup_signal == RuleSignal.BUY:
            if self.check_long_ratio(current_bar):
                return True

        if turtle_soup_signal == RuleSignal.SELL:
            if self.check_short_ratio(current_bar):
                return True

        return False

    def check_long_ratio(self, current_bar: Bar) -> bool:
        """
        Check if the reward/risk ratio is sufficient for a long position.

        Args:
            current_bar: The current bar

        Returns:
            bool: True if ratio >= configured reward_risk_ratio
        """
        # Get expected target (pivot high)
        expected_target: Optional[float] = self.shared_state.get(
            SharedDictKey.EXPECTED_TARGET_LATEST_PIVOT_HIGH_PRICE
        )
        if expected_target is None:
            self.strategy.log.warning("BUY: Expected target (pivot high) not available")
            return False

        # Get stop loss price
        stop_loss_price: Optional[float] = self.shared_state.get(
            SharedDictKeyBase.ENTRY_SL_PRICE
        )
        if stop_loss_price is None:
            self.strategy.log.warning("BUY: Stop loss price not available")
            return False

        current_price = float(current_bar.close)

        # Calculate reward and risk
        reward = expected_target - current_price
        risk = current_price - stop_loss_price

        # Validate reward and risk are positive
        if reward <= 0:
            self.strategy.log.warning(
                f"BUY: Invalid reward={reward:.5f} (target={expected_target:.5f}, price={current_price:.5f})"
            )
            return False

        if risk <= 0:
            self.strategy.log.warning(
                f"BUY: Invalid risk={risk:.5f} (price={current_price:.5f}, sl={stop_loss_price:.5f})"
            )
            return False

        # Calculate ratio
        calculated_ratio = reward / risk

        # Check if ratio meets requirement
        if calculated_ratio >= self.config.reward_risk_ratio:
            self.strategy.log.info(
                f"BUY: R/R ratio {calculated_ratio:.2f} >= {self.config.reward_risk_ratio:.2f} "
                f"(reward={reward:.5f}, risk={risk:.5f})"
            )
            return True
        else:
            self.strategy.log.info(
                f"BUY: R/R ratio {calculated_ratio:.2f} < {self.config.reward_risk_ratio:.2f} - REJECTED "
                f"(reward={reward:.5f}, risk={risk:.5f})"
            )
            return False

    def check_short_ratio(self, current_bar: Bar) -> bool:
        """
        Check if the reward/risk ratio is sufficient for a short position.

        Args:
            current_bar: The current bar

        Returns:
            bool: True if ratio >= configured reward_risk_ratio
        """
        # Get expected target (pivot low)
        expected_target: Optional[float] = self.shared_state.get(
            SharedDictKey.EXPECTED_TARGET_LATEST_PIVOT_LOW_PRICE
        )
        if expected_target is None:
            self.strategy.log.warning("SELL: Expected target (pivot low) not available")
            return False

        # Get stop loss price
        stop_loss_price: Optional[float] = self.shared_state.get(
            SharedDictKeyBase.ENTRY_SL_PRICE
        )
        if stop_loss_price is None:
            self.strategy.log.warning("SELL: Stop loss price not available")
            return False

        current_price = float(current_bar.close)

        # Calculate reward and risk
        reward = current_price - expected_target
        risk = stop_loss_price - current_price

        # Validate reward and risk are positive
        if reward <= 0:
            self.strategy.log.warning(
                f"SELL: Invalid reward={reward:.5f} (price={current_price:.5f}, target={expected_target:.5f})"
            )
            return False

        if risk <= 0:
            self.strategy.log.warning(
                f"SELL: Invalid risk={risk:.5f} (sl={stop_loss_price:.5f}, price={current_price:.5f})"
            )
            return False

        # Calculate ratio
        calculated_ratio = reward / risk

        # Check if ratio meets requirement
        if calculated_ratio >= self.config.reward_risk_ratio:
            self.strategy.log.info(
                f"SELL: R/R ratio {calculated_ratio:.2f} >= {self.config.reward_risk_ratio:.2f} "
                f"(reward={reward:.5f}, risk={risk:.5f})"
            )
            return True
        else:
            self.strategy.log.info(
                f"SELL: R/R ratio {calculated_ratio:.2f} < {self.config.reward_risk_ratio:.2f} - REJECTED "
                f"(reward={reward:.5f}, risk={risk:.5f})"
            )
            return False

    def on_start(self) -> None:
        """Called when the rule starts."""
        self.strategy.log.info(
            f"RewardRiskRatioRule started with minimum ratio {self.config.reward_risk_ratio}:1"
        )

    def on_stop(self) -> None:
        """Called when the rule stops."""
        pass
