from decimal import Decimal

from nautilus_trader.core.correctness import PyCondition
from nautilus_trader.model.instruments.base import Instrument
from nautilus_trader.model.objects import Money
from nautilus_trader.model.objects import Price
from nautilus_trader.model.objects import Quantity
from nautilus_trader.risk.sizing import FixedRiskSizer


class MyFixedRiskSizer(FixedRiskSizer):
    """
    Provides position sizing calculations based on a given risk.

    Parameters
    ----------
    instrument : Instrument
        The instrument for position sizing.
    """

    def __init__(self, instrument: Instrument):
        super().__init__(instrument)

    def calculate(
            self,
            entry: Price,
            stop_loss: Price,
            equity: Money,
            risk: Decimal,
            commission_rate: Decimal = Decimal(0),
            exchange_rate: Decimal = Decimal(1),
            hard_limit: Decimal | None = None,
            unit_batch_size: Decimal=Decimal(1),
            units: int=1,
    ) -> Quantity:
        """
        Calculate the position size quantity.

        Parameters
        ----------
        entry : Price
            The entry price.
        stop_loss : Price
            The stop loss price.
        equity : Money
            The account equity.
        risk : Decimal
            The risk percentage.
        exchange_rate : Decimal
            The exchange rate for the instrument quote currency vs account currency.
        commission_rate : Decimal
            The commission rate (>= 0).
        hard_limit : Decimal, optional
            The hard limit for the total quantity (>= 0).
        unit_batch_size : Decimal
            The unit batch size (> 0).
        units : int
            The number of units to batch the position into (> 0).

        Raises
        ------
        ValueError
            If `risk_bp` is not positive (> 0).
        ValueError
            If `xrate` is not positive (> 0).
        ValueError
            If `commission_rate` is negative (< 0).
        ValueError
            If `hard_limit` is not ``None`` and is not positive (> 0).
        ValueError
            If `unit_batch_size` is not positive (> 0).
        ValueError
            If `units` is not positive (> 0).

        Returns
        -------
        Quantity

        """
        PyCondition.not_none(equity, "equity")
        PyCondition.not_none(entry, "price_entry")
        PyCondition.not_none(stop_loss, "price_stop_loss")
        PyCondition.type(risk, Decimal, "risk")
        PyCondition.positive(risk, "risk")
        PyCondition.type(exchange_rate, Decimal, "exchange_rate")
        PyCondition.not_negative(exchange_rate, "xrate")
        PyCondition.type(commission_rate, Decimal, "commission_rate")
        PyCondition.not_negative(commission_rate, "commission_rate")
        if hard_limit is not None:
            PyCondition.positive(hard_limit, "hard_limit")
        PyCondition.type(unit_batch_size, Decimal, "unit_batch_size")
        PyCondition.not_negative(unit_batch_size, "unit_batch_size")
        PyCondition.positive_int(units, "units")

        if exchange_rate == 0:
            return self.instrument.make_qty(0)

        risk_points: Decimal = self._calculate_risk_ticks(entry, stop_loss)
        risk_money: Decimal = self._calculate_riskable_money(equity.as_decimal(), risk, commission_rate)

        if risk_points <= 0:
            # Divide by zero protection
            return self.instrument.make_qty(0)

        # Calculate position size
        position_size: Decimal = ((risk_money / exchange_rate) / risk_points) / self.instrument.price_increment

        # Limit size on hard limit
        if hard_limit is not None:
            position_size = min(position_size, hard_limit)

        # Batch into units
        position_size_batched: Decimal = max(Decimal(0), position_size / units)

        if unit_batch_size > 0:
            # Round position size to the nearest unit batch size
            position_size_batched = (position_size_batched // unit_batch_size) * unit_batch_size

        # Limit size on max trade size
        if self.instrument.max_quantity is not None:
            position_size_batched = min(position_size_batched, self.instrument.max_quantity)

        return Quantity(position_size_batched, precision=self.instrument.size_precision)

    def _calculate_risk_ticks(self, entry: Price, stop_loss: Price):
        return abs(entry - stop_loss) / self.instrument.price_increment

    @staticmethod
    def _calculate_riskable_money(equity: Decimal,
                                  risk: Decimal,
                                  commission_rate: Decimal):
        if equity <= 0:
            return Decimal(0)
        risk_money: Decimal = equity * risk
        commission: Decimal = risk_money * commission_rate * 2  # (round turn)

        return risk_money - commission