from abc import abstractmethod
from nautilus_trader.model import Bar, QuoteTick
from nautilus_trader.model.enums import PositionSide
from nautilus_trader.trading import Strategy
from rule_base import RuleBase
from nautilus_trader.model.identifiers import ClientOrderId

class QuoteTickRuleBase(RuleBase):
    """
    Abstract base for quote tick rules.
    Child classes must implement the `evaluate` method as well as the `quote_tick_evaluate` method.
    """
    @abstractmethod
    def evaluate(self, bar: Bar, current_bar: Bar = None) -> bool:
        """Check if the rule is satisfied."""
        pass

    @abstractmethod
    def quote_tick_evaluate(self, tick: QuoteTick) -> bool:
        """Check if the rule is satisfied for quote ticks."""
        pass

    @staticmethod
    def _get_position_info_by_client_order_id(strategy: Strategy, client_order_id: ClientOrderId):
        """
        Return (position, is_open, avg_px_open, side) for a position created by the given client order.

        Parameters
        ----------
        strategy: Strategy
            Strategy instance.
        client_order_id : ClientOrderId
            Client order id of the ENTRY order (e.g., market order).

        Returns
        -------
        tuple
            (position, is_open, avg_px_open, side)
            - position     : Position | None
            - is_open      : bool | None
            - avg_px_open  : Any | None # Price-like object per your model
            - side         : PositionSide | None
        """
        coid = client_order_id if isinstance(client_order_id, ClientOrderId) else ClientOrderId(str(client_order_id))

        is_ready = False

        # 1) If the order is still in-flight, the position may not exist yet.
        if strategy.cache.is_order_inflight(coid):
            return is_ready, None, None, None, None

        # 2) Locate the position by scanning all positions via `opening_order_id` only
        all_positions = list(strategy.cache.positions())
        position = None
        for p in all_positions:
            oid = getattr(p, "opening_order_id", None)
            if oid is None:
                continue
            # Normalize and compare against the provided client order id
            if isinstance(oid, ClientOrderId):
                if oid == coid:
                    position = p
                    break
                else:
                    cods = getattr(p, "client_order_ids", None)
                    if cods is None:
                        continue
                    else:
                        if isinstance(cods, list):
                            if coid in cods:
                                #is_ready = True
                                pass
            else:
                if str(oid) == str(coid):
                    position = p
                    break

        if position is None:
            return is_ready, None, None, None, None

        is_ready = True

        # 5) Open/closed via documented property.
        #    is_open is simply the negation of is_closed.
        is_open = not position.is_closed

        # 6) Entry price per docs: avg_px_open
        avg_px_open = getattr(position, "avg_px_open", None)

        # 7) Position side (PositionSide enum)
        side: PositionSide | None = getattr(position, "side", None)
        return is_ready, position, is_open, avg_px_open, side