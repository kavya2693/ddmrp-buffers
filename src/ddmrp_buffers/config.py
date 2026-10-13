"""Calendar, range shape and policy constants shared by the generator and the simulation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

SEED = 20240101

HISTORY_START = date(2023, 1, 1)
SIM_START = date(2024, 1, 1)
SIM_END = date(2025, 12, 31)

N_SKUS = 800

# A local blend is made to order from base oil and additives on site; an import is a finished
# product shipped by sea. Anything up to this many days is treated as a short lead time.
SHORT_LT_MAX = 15
MEDIUM_LT_MAX = 40


@dataclass(frozen=True)
class DdmrpSettings:
    adu_window_days: int = 84
    recalc_every_days: int = 7
    # Lead-time factor by lead-time band: short lead times get a larger factor so that the
    # green zone (one order) is not tiny relative to how often the SKU can be replenished.
    ltf_short: float = 0.7
    ltf_medium: float = 0.5
    ltf_long: float = 0.3
    # Variability factor from the coefficient of variation of weekly demand.
    cv_low: float = 0.5
    cv_high: float = 1.0
    vf_low: float = 0.3
    vf_medium: float = 0.5
    vf_high: float = 0.8
    # An open customer order counts against the buffer early only if it is at least this
    # share of the red zone and due within the decoupled lead time.
    spike_threshold_share: float = 0.5
    order_cycle_local_days: int = 7
    order_cycle_import_days: int = 30


@dataclass(frozen=True)
class MinMaxSettings:
    """Legacy rule: parameters set once a year from last year's average daily usage."""

    safety_days: int = 30
    extra_cover_local_days: int = 90
    extra_cover_import_days: int = 180


@dataclass(frozen=True)
class ReorderPointSettings:
    """Statistical reorder point, recalculated as often as the DDMRP buffers."""

    window_days: int = 84
    recalc_every_days: int = 7
    z: float = 1.88  # 97% cycle service level
    order_cycle_local_days: int = 7
    order_cycle_import_days: int = 30


@dataclass(frozen=True)
class SlowMoverSettings:
    window_days: int = 180
    runner_share: float = 0.5
    repeater_share: float = 0.1
    dormant_after_days: int = 120


DDMRP = DdmrpSettings()
MINMAX = MinMaxSettings()
ROP = ReorderPointSettings()
SLOW = SlowMoverSettings()
