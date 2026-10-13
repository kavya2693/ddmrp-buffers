"""DDMRP buffer arithmetic: ADU, factors, red/yellow/green zones, net flow and order generation.

Everything here is vectorised over SKUs and free of simulation state, so each formula can be
checked against a hand-worked example in the tests.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ddmrp_buffers.config import MEDIUM_LT_MAX, SHORT_LT_MAX, DdmrpSettings


@dataclass
class Zones:
    red: np.ndarray
    yellow: np.ndarray
    green: np.ndarray

    @property
    def tor(self) -> np.ndarray:
        return self.red

    @property
    def toy(self) -> np.ndarray:
        return self.red + self.yellow

    @property
    def tog(self) -> np.ndarray:
        return self.red + self.yellow + self.green


def average_daily_usage(window: np.ndarray) -> np.ndarray:
    """Mean over recorded days; a day missing from the extract is skipped, not read as zero."""
    with np.errstate(invalid="ignore"):
        recorded = np.sum(~np.isnan(window), axis=0)
        total = np.nansum(window, axis=0)
    return np.where(recorded > 0, total / np.maximum(recorded, 1), 0.0)


def weekly_cv(window: np.ndarray) -> np.ndarray:
    """Coefficient of variation of weekly demand. Daily CV is dominated by zero days on
    intermittent SKUs, so it says little about how much the buffer has to absorb."""
    n_weeks = window.shape[0] // 7
    if n_weeks < 2:
        return np.zeros(window.shape[1])
    w = window[-n_weeks * 7 :].reshape(n_weeks, 7, -1)
    recorded = np.sum(~np.isnan(w), axis=1)
    # Scale partially recorded weeks up to seven days so a gap does not look like a dip.
    weekly = np.nansum(w, axis=1) * 7.0 / np.maximum(recorded, 1)
    weekly = np.where(recorded > 0, weekly, np.nan)
    with np.errstate(invalid="ignore", divide="ignore"):
        mean = np.nanmean(weekly, axis=0)
        std = np.nanstd(weekly, axis=0)
        cv = np.where(mean > 0, std / np.where(mean > 0, mean, 1.0), 0.0)
    return np.nan_to_num(cv)


def lead_time_factor(lead_time: np.ndarray, s: DdmrpSettings) -> np.ndarray:
    lt = np.asarray(lead_time, dtype=float)
    if np.any(lt <= 0):
        raise ValueError("decoupled lead time must be positive")
    return np.where(lt <= SHORT_LT_MAX, s.ltf_short, np.where(lt <= MEDIUM_LT_MAX, s.ltf_medium, s.ltf_long))


def variability_factor(cv: np.ndarray, s: DdmrpSettings) -> np.ndarray:
    return np.where(cv < s.cv_low, s.vf_low, np.where(cv < s.cv_high, s.vf_medium, s.vf_high))


def zones(
    adu: np.ndarray,
    dlt: np.ndarray,
    ltf: np.ndarray,
    vf: np.ndarray,
    moq: np.ndarray,
    order_cycle_days: np.ndarray,
) -> Zones:
    """Red = ADU*DLT*LTF*(1+VF); yellow = ADU*DLT; green = max(ADU*DLT*LTF, MOQ, ADU*order cycle).

    A SKU with no usage gets no buffer at all, otherwise the MOQ alone would keep buying stock
    nobody asked for.
    """
    if np.any(np.asarray(adu) < 0):
        raise ValueError("ADU cannot be negative")
    red_base = adu * dlt * ltf
    red = red_base * (1.0 + vf)
    yellow = adu * dlt
    green = np.maximum.reduce([red_base, np.asarray(moq, dtype=float), adu * order_cycle_days])
    active = adu > 0
    return Zones(
        red=np.where(active, red, 0.0),
        yellow=np.where(active, yellow, 0.0),
        green=np.where(active, green, 0.0),
    )


def net_flow(on_hand: np.ndarray, on_order: np.ndarray, qualified_demand: np.ndarray) -> np.ndarray:
    """Net flow position = on hand + on order - qualified demand (due today, past due, spikes)."""
    return on_hand + on_order - qualified_demand


def round_up(qty: np.ndarray, moq: np.ndarray, multiple: np.ndarray) -> np.ndarray:
    q = np.where(qty > 0, np.maximum(qty, moq), 0.0)
    return np.ceil(q / multiple - 1e-9) * multiple


def order_quantity(
    nfp: np.ndarray, z: Zones, moq: np.ndarray, multiple: np.ndarray, trigger: np.ndarray | None = None
) -> np.ndarray:
    """Order up to top of green whenever net flow is at or below top of yellow.

    `trigger` replaces top of yellow as the reorder line, which is how the slow-mover rule
    turns a buffer into replenish-to-order.
    """
    line = z.toy if trigger is None else trigger
    raw = np.where(nfp <= line, z.tog - nfp, 0.0)
    return round_up(raw, moq, multiple)
