"""
Kalshi-style taker fee estimation for binary contracts.

Kalshi’s published fee form is proportional to :math:`p(1-p)` on the traded contract price
(in probability / dollar terms). This module implements a **simplified** estimator suitable
for back-of-the-envelope cost modeling in research — not a guarantee of live billings.

See ``estimate_taker_fee_cents`` for details and assumptions.
"""

from __future__ import annotations

import math
from typing import Literal

FeeSide = Literal["yes", "no"]


def estimate_taker_fee_cents(
    *,
    price_cents: int,
    contracts: int,
    fee_rate: float = 0.07,
    side: FeeSide = "no",
) -> int:
    """
    Estimate total taker fee in **integer cents** for opening a position.

    Model (scaffold assumption, verify against Kalshi fee schedule for production research):
    For a contract traded at implied probability ``p = price_cents / 100`` on the **specified
    side**, taker fee per dollar of notional scales with :math:`p(1-p)`. We approximate total fee as:

    .. code-block:: text

        fee_usd = fee_rate * contracts * (p * (1 - p))

    Then convert to cents with **ceiling** (conservative for cost estimation).

    :param price_cents: Traded price in cents on the chosen ``side`` (1–99 typical for binaries).
    :param contracts: Number of contracts (must be non-negative).
    :param fee_rate: Fee coefficient (default 0.07 matches common Kalshi examples; confirm live).
    :param side: Which leg is priced by ``price_cents`` (accepted for API clarity; same formula for YES/NO price).
    :return: Non-negative fee in whole cents.
    """
    if contracts < 0:
        raise ValueError("contracts must be non-negative")
    if not 0 <= price_cents <= 100:
        raise ValueError("price_cents must be between 0 and 100 inclusive")
    if fee_rate < 0:
        raise ValueError("fee_rate must be non-negative")
    _ = side  # YES/NO symmetry at a given implied probability for this simplified model

    p = price_cents / 100.0
    fee_usd = fee_rate * contracts * (p * (1.0 - p))
    return int(math.ceil(fee_usd * 100))
