"""Inventory and service KPIs. DIO and working capital reward holding less; fill rate and
stockout days punish it. A policy is only better if it moves the first pair without the second."""

from __future__ import annotations

import itertools

import numpy as np

from ddmrp_buffers.simulate import SimResult


def kpis(
    r: SimResult, unit_cost: np.ndarray, days: slice, mask: np.ndarray | None = None
) -> dict[str, float]:
    m = np.ones(r.on_hand.shape[1], dtype=bool) if mask is None else mask
    c = unit_cost[m]
    oh, dem, fill, ordered = (x[days][:, m] for x in (r.on_hand, r.demand, r.filled, r.ordered))
    inv_value = (oh * c).sum(axis=1).mean()
    cogs_per_day = (fill * c).sum(axis=1).mean()
    demand_value = (dem * c).sum()
    lost = dem - fill > 1e-9
    n_days = oh.shape[0]
    return {
        "avg_inventory_value": float(inv_value),
        "dio_days": float(inv_value / cogs_per_day) if cogs_per_day > 0 else float("nan"),
        "value_fill_rate": float((fill * c).sum() / demand_value) if demand_value > 0 else float("nan"),
        "lost_sales_value": float(((dem - fill) * c).sum()),
        "stockout_sku_day_share": float(lost.mean()),
        "skus_with_stockout_share": float(lost.any(axis=0).mean()),
        "purchase_orders_per_month": float((ordered > 0).sum() / n_days * 30.4),
    }


def opening_dio(initial_on_hand: np.ndarray, history: np.ndarray, unit_cost: np.ndarray) -> float:
    """Opening stock value over the trailing usage rate the business had at the time."""
    with np.errstate(invalid="ignore"):
        daily_value = np.nansum(np.nanmean(history, axis=0) * unit_cost)
    return float((initial_on_hand * unit_cost).sum() / daily_value)


def stock_at_matched_service(points: list[tuple[float, float]], target_fill: float) -> float | None:
    """Linear interpolation of DIO at a target fill rate along a policy's (fill, DIO) curve;
    None if the policy never reaches that fill rate in the sweep."""
    pts = sorted(points)
    for (f0, d0), (f1, d1) in itertools.pairwise(pts):
        if f0 <= target_fill <= f1:
            return d0 if f1 == f0 else d0 + (d1 - d0) * (target_fill - f0) / (f1 - f0)
    return None
