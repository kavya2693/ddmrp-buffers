"""Re-run the repo's own DDMRP simulation and export one day's purchase-order proposals.

Same data (data/, seed 20240101), same lead-time draws (sim seed 7) and the same default
DDMRP policy as `make run`. A thin subclass of the repo's `policies.Ddmrp` records, on one
chosen day, every SKU the policy orders: stock on hand, open supplier orders, the customer
orders already placed that count against the buffer, the net flow position, the zones and
the order quantity. Nothing in the policy is changed; the subclass only reads its state.

Run:  cd <repo> && PYTHONPATH=src .venv/bin/python <this file> <out.json> [YYYY-MM-DD]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from ddmrp_buffers import buffers, data, policies, simulate

out_path = Path(sys.argv[1])
day = pd.Timestamp(sys.argv[2] if len(sys.argv) > 2 else "2025-09-08")

ds = data.load(Path("data"))
ctx = simulate.context(ds)
t_day = int(ds.dates.get_loc(day))
snap: dict[str, np.ndarray] = {}


class Recorder(policies.Ddmrp):
    def order(self, t, ctx, on_hand, on_order):  # type: ignore[no-untyped-def]
        q = super().order(t, ctx, on_hand, on_order)
        if t == t_day:
            assert self.zones is not None
            thr = self.s.spike_threshold_share * self.zones.red
            spikes = ctx.open_spikes(t, ctx.lead_time, thr)
            nfp_no_spike = buffers.net_flow(on_hand, on_order, np.zeros_like(on_hand))
            snap.update(
                on_hand=on_hand.copy(),
                on_order=on_order.copy(),
                spikes=spikes,
                nfp=self.last_nfp.copy(),
                nfp_no_spike=nfp_no_spike,
                tor=self.zones.tor.copy(),
                toy=self.zones.toy.copy(),
                tog=self.zones.tog.copy(),
                q=q.copy(),
            )
        return q


simulate.simulate(ds, Recorder(), ctx=ctx)  # default sim seed 7, as in make run
sk = ds.skus
q = snap["q"]
ordered = np.where(q > 0)[0]
cost = ctx.unit_cost


def zone(j: int) -> str:
    n = snap["nfp"][j]
    return "red" if n <= snap["tor"][j] else "yellow" if n <= snap["toy"][j] else "green"


rows = []
for j in ordered:
    lt = int(sk.at[j, "lead_time_days"])
    rows.append(
        {
            "sku_idx": int(j),
            "sku": str(sk.at[j, "sku"]),
            "family": str(sk.at[j, "family"]),
            "pack_litres": float(sk.at[j, "pack_litres"]),
            "source": str(sk.at[j, "source"]),
            "lead_time_days": lt,
            "due": str((day + pd.Timedelta(days=lt)).date()),
            "on_hand": float(snap["on_hand"][j]),
            "on_order": float(snap["on_order"][j]),
            "customer_orders": float(snap["spikes"][j]),
            "net_flow": float(snap["nfp"][j]),
            "tor": float(snap["tor"][j]),
            "toy": float(snap["toy"][j]),
            "tog": float(snap["tog"][j]),
            "zone": zone(j),
            "priority_pct": float(100 * snap["nfp"][j] / snap["tog"][j]),
            "order_qty": float(q[j]),
            "order_value": float(q[j] * cost[j]),
            "triggered_by_customer_orders": bool(snap["nfp_no_spike"][j] > snap["toy"][j]),
        }
    )
rows.sort(key=lambda r: r["priority_pct"])
out = {
    "day": str(day.date()),
    "weekday": day.day_name(),
    "policy": "DDMRP (default settings, as in make run)",
    "skus_in_range": len(sk),
    "orders": len(rows),
    "imports": sum(r["source"] == "import" for r in rows),
    "with_customer_orders": sum(r["customer_orders"] > 0 for r in rows),
    "triggered_by_customer_orders": sum(r["triggered_by_customer_orders"] for r in rows),
    "red_zone": sum(r["zone"] == "red" for r in rows),
    "order_value": float(sum(r["order_value"] for r in rows)),
    "rows": rows,
}
out_path.parent.mkdir(parents=True, exist_ok=True)
out_path.write_text(json.dumps(out, indent=1))
print(
    f"{out['day']}: {out['orders']} orders, {out['imports']} imports, "
    f"{out['with_customer_orders']} with customer orders "
    f"({out['triggered_by_customer_orders']} triggered by them), "
    f"{out['red_zone']} in red, value {out['order_value']:,.0f} -> {out_path}"
)
