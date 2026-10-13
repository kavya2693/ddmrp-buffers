"""Day-by-day stock simulation. Every policy runs against identical demand, identical opening
stock and identical supplier lead-time draws, so differences come from the rule alone."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from ddmrp_buffers.data import Dataset
from ddmrp_buffers.policies import Context, Ddmrp, Policy


@dataclass
class SimResult:
    name: str
    on_hand: np.ndarray  # end-of-day units, (sim days, skus)
    demand: np.ndarray
    filled: np.ndarray
    ordered: np.ndarray
    trace: dict[int, dict[str, np.ndarray]] = field(default_factory=dict)


def context(ds: Dataset) -> Context:
    sk = ds.skus
    return Context(
        dates=ds.dates,
        demand=ds.demand,
        lead_time=sk["lead_time_days"].to_numpy(dtype=int),
        is_import=(sk["source"] == "import").to_numpy(),
        moq=sk["moq"].to_numpy(dtype=float),
        multiple=sk["order_multiple"].to_numpy(dtype=float),
        unit_cost=sk["unit_cost"].to_numpy(dtype=float),
        bulk_sku=ds.bulk["sku_idx"].to_numpy(dtype=int),
        bulk_placed=ds.bulk["placed_day"].to_numpy(dtype=int),
        bulk_due=ds.bulk["due_day"].to_numpy(dtype=int),
        bulk_qty=ds.bulk["qty"].to_numpy(dtype=float),
    )


def actual_lead_times(ctx: Context, n_days: int, seed: int) -> np.ndarray:
    """Realised lead time for an order placed on each day: blends drift by a day or two,
    imports drift more and one shipment in ten is held at the port for two to five weeks."""
    rng = np.random.default_rng(seed)
    n = len(ctx.lead_time)
    noise = np.where(ctx.is_import, 0.10, 0.15)
    lt = ctx.lead_time * np.exp(noise * rng.standard_normal((n_days, n)))
    port_hold = (rng.random((n_days, n)) < 0.10) & ctx.is_import
    lt = lt + port_hold * rng.integers(14, 36, (n_days, n))
    return np.maximum(1, np.rint(lt)).astype(int)


def simulate(
    ds: Dataset, policy: Policy, seed: int = 7, trace_skus: tuple[int, ...] = (), ctx: Context | None = None
) -> SimResult:
    ctx = ctx or context(ds)
    s = ds.sim_start_idx
    n_days, n = ds.demand.shape[0] - s, ds.demand.shape[1]
    true_demand = ds.demand[s:]
    if np.isnan(true_demand).any():
        raise ValueError("simulated period must be fully recorded")
    lt_real = actual_lead_times(ctx, n_days, seed)
    cols = np.arange(n)

    on_hand = ds.initial_on_hand.astype(float).copy()
    on_order = np.zeros(n)
    arrivals = np.zeros((n_days + int(lt_real.max()) + 1, n))
    rec_oh = np.zeros((n_days, n))
    rec_fill = np.zeros((n_days, n))
    rec_ord = np.zeros((n_days, n))
    trace: dict[int, dict[str, np.ndarray]] = {
        j: {k: np.zeros(n_days) for k in ("on_hand", "nfp", "tor", "toy", "tog")} for j in trace_skus
    }

    for t in range(n_days):
        on_hand += arrivals[t]
        on_order -= arrivals[t]
        d = true_demand[t]
        filled = np.minimum(on_hand, d)
        on_hand -= filled  # unfilled demand is lost: lubricant buyers go to another distributor

        q = policy.order(s + t, ctx, on_hand, on_order)
        placed = q > 0
        np.add.at(arrivals, (t + lt_real[t, placed], cols[placed]), q[placed])
        on_order += q

        rec_oh[t], rec_fill[t], rec_ord[t] = on_hand, filled, q
        if trace_skus and isinstance(policy, Ddmrp) and policy.zones is not None:
            z = policy.zones
            for j in trace_skus:
                tr = trace[j]
                tr["on_hand"][t], tr["nfp"][t] = on_hand[j], policy.last_nfp[j]
                tr["tor"][t], tr["toy"][t], tr["tog"][t] = z.tor[j], z.toy[j], z.tog[j]

    return SimResult(policy.name, rec_oh, true_demand, rec_fill, rec_ord, trace)
