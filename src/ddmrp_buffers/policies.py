"""Replenishment policies the simulation compares. Each one sees the same recorded history,
the same stock position and the same open customer orders; only the rule differs."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

import numpy as np
import pandas as pd

from ddmrp_buffers import buffers, classify
from ddmrp_buffers.config import (
    DDMRP,
    MINMAX,
    ROP,
    SLOW,
    DdmrpSettings,
    MinMaxSettings,
    ReorderPointSettings,
    SlowMoverSettings,
)


@dataclass
class Context:
    dates: pd.DatetimeIndex
    demand: np.ndarray  # recorded demand, (days, skus)
    lead_time: np.ndarray
    is_import: np.ndarray
    moq: np.ndarray
    multiple: np.ndarray
    unit_cost: np.ndarray
    bulk_sku: np.ndarray
    bulk_placed: np.ndarray
    bulk_due: np.ndarray
    bulk_qty: np.ndarray

    def open_spikes(self, t: int, horizon: np.ndarray, threshold: np.ndarray) -> np.ndarray:
        """Customer orders already placed, due after today but within the horizon, and large
        enough to count as a spike against the buffer."""
        sku = self.bulk_sku
        live = (self.bulk_placed <= t) & (self.bulk_due > t) & (self.bulk_due <= t + horizon[sku])
        live &= self.bulk_qty >= threshold[sku]
        out = np.zeros(len(self.lead_time))
        np.add.at(out, sku[live], self.bulk_qty[live])
        return out


class Policy(Protocol):
    name: str

    def order(self, t: int, ctx: Context, on_hand: np.ndarray, on_order: np.ndarray) -> np.ndarray: ...


def _window(ctx: Context, t: int, days: int) -> np.ndarray:
    return ctx.demand[max(0, t - days + 1) : t + 1]


@dataclass
class LegacyMinMax:
    """What many distributors run: min = usage over lead time plus a month, max = min plus
    three (blend) or six (import) months, reset once a year from last year's average."""

    s: MinMaxSettings = MINMAX
    name: str = "min-max (legacy)"
    _min: np.ndarray | None = None
    _max: np.ndarray | None = None

    def order(self, t: int, ctx: Context, on_hand: np.ndarray, on_order: np.ndarray) -> np.ndarray:
        if self._min is None or ctx.dates[t].dayofyear == 1:
            adu = buffers.average_daily_usage(_window(ctx, t, 365))
            extra = np.where(ctx.is_import, self.s.extra_cover_import_days, self.s.extra_cover_local_days)
            self._min = adu * (ctx.lead_time + self.s.safety_days)
            self._max = self._min + adu * extra
        assert self._max is not None
        ip = on_hand + on_order
        raw = np.where((ip <= self._min) & (self._max > 0), self._max - ip, 0.0)
        return buffers.round_up(raw, ctx.moq, ctx.multiple)


@dataclass
class ReorderPoint:
    """The fair comparator: textbook reorder point with z-sigma safety stock, recalculated
    weekly on the same window and with the same order cycle as the DDMRP buffers."""

    s: ReorderPointSettings = ROP
    name: str = "reorder point (tuned)"
    z: float | None = None
    _rop: np.ndarray | None = None
    _target: np.ndarray | None = None
    _next_recalc: int = -1

    def order(self, t: int, ctx: Context, on_hand: np.ndarray, on_order: np.ndarray) -> np.ndarray:
        if t >= self._next_recalc:
            w = _window(ctx, t, self.s.window_days)
            mu = buffers.average_daily_usage(w)
            with np.errstate(invalid="ignore"):
                sigma = np.nan_to_num(np.nanstd(w, axis=0))
            lt = ctx.lead_time
            z = self.s.z if self.z is None else self.z
            self._rop = mu * lt + z * sigma * np.sqrt(lt)
            cycle = np.where(ctx.is_import, self.s.order_cycle_import_days, self.s.order_cycle_local_days)
            self._target = self._rop + np.maximum(mu * cycle, ctx.moq)
            self._target = np.where(mu > 0, self._target, 0.0)
            self._next_recalc = t + self.s.recalc_every_days
        assert self._rop is not None and self._target is not None
        ip = on_hand + on_order
        raw = np.where((ip <= self._rop) & (self._target > 0), self._target - ip, 0.0)
        return buffers.round_up(raw, ctx.moq, ctx.multiple)


@dataclass
class Ddmrp:
    s: DdmrpSettings = DDMRP
    slow_mover_rule: bool = False
    # Scales the red zone; used only to trace the stock-versus-service curve.
    red_multiplier: float = 1.0
    use_spikes: bool = True
    slow: SlowMoverSettings = SLOW
    name: str = "DDMRP"
    zones: buffers.Zones | None = None
    classes: np.ndarray | None = None
    last_nfp: np.ndarray = field(default_factory=lambda: np.zeros(0))
    _moq: np.ndarray | None = None
    _next_recalc: int = -1

    def __post_init__(self) -> None:
        if self.slow_mover_rule and self.name == "DDMRP":
            self.name = "DDMRP + slow-mover rule"

    def recalc(self, t: int, ctx: Context) -> None:
        w = _window(ctx, t, self.s.adu_window_days)
        adu = buffers.average_daily_usage(w)
        dlt = ctx.lead_time.astype(float)
        ltf = buffers.lead_time_factor(dlt, self.s)
        vf = buffers.variability_factor(buffers.weekly_cv(w), self.s)
        cycle = np.where(ctx.is_import, self.s.order_cycle_import_days, self.s.order_cycle_local_days)
        moq = ctx.moq.astype(float).copy()
        z = buffers.zones(adu, dlt, ltf, vf, moq, cycle.astype(float))
        z.red = z.red * self.red_multiplier
        if self.slow_mover_rule:
            cls = classify.classify(_window(ctx, t, self.slow.window_days), self.slow)
            # Strangers keep only the red zone and are bought in the quantity actually needed;
            # dormant SKUs hold nothing and are bought only against a customer order in hand.
            stranger = cls == classify.STRANGER
            dormant = cls == classify.DORMANT
            z.yellow = np.where(stranger | dormant, 0.0, z.yellow)
            z.green = np.where(stranger | dormant, 0.0, z.green)
            z.red = np.where(dormant, 0.0, z.red)
            moq = np.where(stranger | dormant, 0.0, moq)
            self.classes = cls
        self.zones, self._moq = z, moq
        self._next_recalc = t + self.s.recalc_every_days

    def order(self, t: int, ctx: Context, on_hand: np.ndarray, on_order: np.ndarray) -> np.ndarray:
        if t >= self._next_recalc:
            self.recalc(t, ctx)
        assert self.zones is not None and self._moq is not None
        if self.use_spikes:
            thr = self.s.spike_threshold_share * self.zones.red
            qualified = ctx.open_spikes(t, ctx.lead_time, thr)
        else:
            qualified = np.zeros_like(on_hand)
        nfp = buffers.net_flow(on_hand, on_order, qualified)
        self.last_nfp = nfp
        return buffers.order_quantity(nfp, self.zones, self._moq, ctx.multiple)
