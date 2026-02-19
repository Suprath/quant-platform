"""
Position Sizing — Risk-Adjusted Trade Sizing

Uses Half-Kelly criterion with volatility and uncertainty adjustments.
"""

import numpy as np
from config import (
    setup_logger,
    KELLY_FRACTION,
    MAX_SINGLE_TRADE,
    MAX_POSITION_SIZE,
)

logger = setup_logger("esti.risk.position_sizing")


class PositionSizer:
    """
    Determines safe position sizes using Kelly criterion,
    volatility scaling, and uncertainty from the ESTIPolicy.
    """

    def __init__(
        self,
        kelly_fraction: float = KELLY_FRACTION,
        max_single_trade: float = MAX_SINGLE_TRADE,
        max_position: float = MAX_POSITION_SIZE,
    ):
        self.kelly_fraction = kelly_fraction
        self.max_single_trade = max_single_trade
        self.max_position = max_position

        logger.info(
            f"📏 PositionSizer initialised | kelly={kelly_fraction} "
            f"| max_trade={max_single_trade:.0%} | max_pos={max_position:.0%}"
        )

    def calculate_size(
        self,
        raw_size: float,
        uncertainty: float,
        volatility: float,
        win_rate: float = 0.5,
        avg_win_loss_ratio: float = 1.0,
    ) -> float:
        """
        Calculate risk-adjusted position size.

        Args:
            raw_size:    ESTIPolicy output [0, 1]
            uncertainty: ESTIPolicy uncertainty [0, 1] (higher = less confident)
            volatility:  current market volatility
            win_rate:    historical win rate of this agent
            avg_win_loss_ratio: avg winner / avg loser

        Returns:
            Final position fraction [0, max_single_trade]
        """
        # Kelly criterion: f* = (bp - q) / b
        # b = avg_win_loss_ratio, p = win_rate, q = 1-win_rate
        b = max(avg_win_loss_ratio, 0.01)
        kelly_full = (b * win_rate - (1 - win_rate)) / b
        kelly_full = max(kelly_full, 0.0)

        # Half-Kelly for safety
        kelly = kelly_full * self.kelly_fraction

        # Blend raw model output with Kelly
        blended = 0.5 * raw_size + 0.5 * kelly

        # Volatility adjustment: reduce size in high vol
        vol_safe = max(volatility, 0.001)
        vol_scalar = min(1.0, 0.02 / vol_safe)  # target ~2% daily vol
        blended *= vol_scalar

        # Uncertainty scaling: reduce size when model is uncertain
        confidence = 1.0 - uncertainty
        blended *= confidence

        # Clamp to limits
        final = min(blended, self.max_single_trade, self.max_position)
        final = max(final, 0.0)

        if logger.isEnabledFor(10):  # DEBUG
            logger.debug(
                f"📏 Size calc | raw={raw_size:.3f} kelly_full={kelly_full:.4f} "
                f"kelly_half={kelly:.4f} | vol_scalar={vol_scalar:.3f} "
                f"confidence={confidence:.3f} | final={final:.4f}"
            )

        return final
