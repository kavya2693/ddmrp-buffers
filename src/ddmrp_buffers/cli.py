"""One command: load (or generate) the range, run every policy over two years, write results."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from ddmrp_buffers import charts, classify, config, data, metrics, policies, simulate

ROP_Z_SWEEP = [0.84, 1.28, 1.65, 1.88, 2.33, 2.75, 3.25, 3.75, 4.25, 4.75, 5.5]
DDMRP_RED_SWEEP = [0.5, 0.75, 1.0, 1.5, 2.0, 2.5, 3.0, 4.0]


def arms() -> list[policies.Policy]:
    return [
        policies.LegacyMinMax(),
        policies.ReorderPoint(),
        policies.Ddmrp(),
        policies.Ddmrp(use_spikes=False, name="DDMRP, no order-spike visibility"),
        policies.Ddmrp(slow_mover_rule=True),
    ]


def pick_trace_skus(ds: data.Dataset, start_class: np.ndarray) -> dict[int, str]:
    """A local runner, an imported runner and a stranger, each the highest-value of its kind."""
    sk = ds.skus
    value = np.nan_to_num(np.nanmean(ds.demand[: ds.sim_start_idx], axis=0)) * sk["unit_cost"].to_numpy()
    imp = (sk["source"] == "import").to_numpy()
    picks = {}
    for want_import, want_class in (
        (False, classify.RUNNER),
        (True, classify.RUNNER),
        (False, classify.STRANGER),
    ):
        cand = np.where((imp == want_import) & (start_class == want_class) & (sk["lifecycle"] == "stable"))[0]
        j = int(cand[np.argmax(value[cand])])
        row = sk.iloc[j]
        picks[j] = (
            f"{row['sku']}  {row['family'].replace('_', ' ')}, {row['pack_litres']:g} L pack, "
            f"{row['source'].replace('_', ' ')}, {row['lead_time_days']}-day lead time, "
            f"{classify.LABELS[int(start_class[j])]} at start"
        )
    return picks


def _fmt_table(rows: list[dict[str, object]], cols: list[tuple[str, str, str]]) -> str:
    head = "| " + " | ".join(c[1] for c in cols) + " |"
    sep = "|" + "|".join("---" if i == 0 else "---:" for i in range(len(cols))) + "|"
    body = []
    for r in rows:
        cells = []
        for key, _, fmt in cols:
            v = r[key]
            cells.append(
                "not reached" if v is None else fmt.format(v) if isinstance(v, float | int) else str(v)
            )
        body.append("| " + " | ".join(cells) + " |")
    return "\n".join([head, sep, *body])


KPI_COLS = [
    ("policy", "Policy", "{}"),
    ("avg_inventory_value", "Avg stock at cost", "{:,.0f}"),
    ("dio_days", "DIO (days)", "{:.1f}"),
    ("value_fill_rate", "Value fill rate", "{:.2%}"),
    ("stockout_sku_day_share", "Stockout SKU-days", "{:.2%}"),
    ("lost_sales_value", "Lost sales at cost", "{:,.0f}"),
    ("purchase_orders_per_month", "POs per month", "{:,.0f}"),
]


def sweep(
    ds: data.Dataset, ctx: policies.Context, days: slice, sim_seed: int = 7
) -> tuple[dict[str, list[tuple[float, float]]], list[dict[str, object]]]:
    """The stock-versus-service curve: each policy swept over its one safety knob."""
    cost = ctx.unit_cost
    curves: dict[str, list[tuple[float, float]]] = {"reorder point (tuned)": [], "DDMRP": []}
    rows: list[dict[str, object]] = []
    for zv in ROP_Z_SWEEP:
        r = simulate.simulate(ds, policies.ReorderPoint(z=zv), seed=sim_seed, ctx=ctx)
        k = metrics.kpis(r, cost, days)
        curves["reorder point (tuned)"].append((k["value_fill_rate"], k["dio_days"]))
        rows.append({"policy": "reorder point (tuned)", "knob": "z", "value": zv, **k})
    for mult in DDMRP_RED_SWEEP:
        r = simulate.simulate(ds, policies.Ddmrp(red_multiplier=mult), seed=sim_seed, ctx=ctx)
        k = metrics.kpis(r, cost, days)
        curves["DDMRP"].append((k["value_fill_rate"], k["dio_days"]))
        rows.append({"policy": "DDMRP", "knob": "red multiplier", "value": mult, **k})
    return curves, rows


def robustness_row(
    seed: int,
    days: slice,
    ds: data.Dataset,
    ctx: policies.Context,
    results: dict[str, dict[str, dict[str, float]]],
    matched: dict[str, float | None],
) -> dict[str, object]:
    def y2(name: str, key: str) -> float:
        return results[name]["year_2"][key]

    return {
        "seed": seed,
        "legacy_dio": y2("min-max (legacy)", "dio_days"),
        "legacy_fill": y2("min-max (legacy)", "value_fill_rate"),
        "rop_dio": y2("reorder point (tuned)", "dio_days"),
        "rop_fill": y2("reorder point (tuned)", "value_fill_rate"),
        "ddmrp_dio": y2("DDMRP", "dio_days"),
        "ddmrp_fill": y2("DDMRP", "value_fill_rate"),
        "rop_dio_at_legacy_fill": matched["reorder point (tuned)"],
        "ddmrp_dio_at_legacy_fill": matched["DDMRP"],
    }


def robustness_on_new_seed(seed: int, days: slice) -> dict[str, object]:
    """Same experiment on a freshly generated range and fresh lead-time draws, in memory."""
    ds = data.generate(seed=seed)
    ctx = simulate.context(ds)
    results = {
        p.name: {"year_2": metrics.kpis(simulate.simulate(ds, p, seed=seed, ctx=ctx), ctx.unit_cost, days)}
        for p in (policies.LegacyMinMax(), policies.ReorderPoint(), policies.Ddmrp())
    }
    curves, _ = sweep(ds, ctx, days, sim_seed=seed)
    target = results["min-max (legacy)"]["year_2"]["value_fill_rate"]
    matched = {name: metrics.stock_at_matched_service(pts, target) for name, pts in curves.items()}
    return robustness_row(seed, days, ds, ctx, results, matched)


def run(data_dir: Path, out_dir: Path, seed: int, n_extra_seeds: int = 3) -> dict[str, object]:
    if not (data_dir / "skus.csv").exists():
        data.save(data.generate(seed=seed), data_dir)
    ds = data.load(data_dir)
    ctx = simulate.context(ds)
    cost = ctx.unit_cost
    s = ds.sim_start_idx
    sim_dates = ds.dates[s:]
    year1 = slice(0, int((sim_dates.year == sim_dates[0].year).sum()))
    year2 = slice(year1.stop, None)
    start_class = classify.classify(ds.demand[:s], config.SLOW)
    trace_labels = pick_trace_skus(ds, start_class)
    out_dir.mkdir(parents=True, exist_ok=True)

    results: dict[str, dict[str, dict[str, float]]] = {}
    inventory_series: dict[str, np.ndarray] = {}
    segment_rows = []
    segments = {
        "local blend": ~ctx.is_import,
        "import": ctx.is_import,
        **{f"{classify.LABELS[c]} at start": start_class == c for c in classify.LABELS},
    }
    ddmrp_trace: dict[int, dict[str, np.ndarray]] = {}
    for policy in arms():
        traced = tuple(trace_labels) if policy.name == "DDMRP" else ()
        r = simulate.simulate(ds, policy, trace_skus=traced, ctx=ctx)
        if traced:
            ddmrp_trace = r.trace
        results[policy.name] = {
            "year_1": metrics.kpis(r, cost, year1),
            "year_2": metrics.kpis(r, cost, year2),
            "both_years": metrics.kpis(r, cost, slice(None)),
        }
        inventory_series[policy.name] = (r.on_hand * cost).sum(axis=1)
        for seg, mask in segments.items():
            k = metrics.kpis(r, cost, year2, mask)
            segment_rows.append({"policy": policy.name, "segment": seg, "skus": int(mask.sum()), **k})

    curves, frontier_rows = sweep(ds, ctx, year2)
    legacy_fill = results["min-max (legacy)"]["year_2"]["value_fill_rate"]
    matched = {name: metrics.stock_at_matched_service(pts, legacy_fill) for name, pts in curves.items()}
    robustness = [robustness_row(seed, year2, ds, ctx, results, matched)]
    for extra in range(1, n_extra_seeds + 1):
        robustness.append(robustness_on_new_seed(seed + extra, year2))

    opening = metrics.opening_dio(ds.initial_on_hand, ds.demand[s - 180 : s], cost)
    class_counts = {classify.LABELS[c]: int((start_class == c).sum()) for c in classify.LABELS}
    summary = {
        "dataset": data.summary(ds),
        "opening_dio_days": opening,
        "opening_stock_value": float((ds.initial_on_hand * cost).sum()),
        "classes_at_start": class_counts,
        "policies": results,
        "matched_service": {
            "target_value_fill_rate_year_2": legacy_fill,
            "dio_at_target": matched,
        },
        "robustness": robustness,
    }

    (out_dir / "results.json").write_text(json.dumps(summary, indent=2))
    pd.DataFrame(segment_rows).to_csv(out_dir / "segments.csv", index=False, float_format="%.4f")
    pd.DataFrame(frontier_rows).to_csv(out_dir / "frontier.csv", index=False, float_format="%.4f")

    md = [
        "# Results",
        "",
        f"Opening stock {summary['opening_stock_value']:,.0f} at cost, {opening:.1f} days of trailing usage. "
        f"SKUs at start: {class_counts}.",
    ]
    for window in ("year_2", "year_1", "both_years"):
        rows = [{"policy": name, **res[window]} for name, res in results.items()]
        md += ["", f"## {window.replace('_', ' ')}", "", _fmt_table(rows, KPI_COLS)]
    md += [
        "",
        "## Year 2 by segment",
        "",
        _fmt_table(segment_rows, [("segment", "Segment", "{}"), *KPI_COLS]),
    ]
    md += ["", "## Matched service", "", f"Target: legacy year-2 value fill rate {legacy_fill:.2%}."]
    for name, v in matched.items():
        md.append(f"- {name}: " + ("not reached in the sweep" if v is None else f"DIO {v:.1f} days"))
    md += [
        "",
        "## Sweep",
        "",
        _fmt_table(frontier_rows, [("knob", "Knob", "{}"), ("value", "Value", "{:g}"), *KPI_COLS]),
    ]
    rob_cols = [
        ("seed", "Seed", "{}"),
        ("legacy_dio", "Legacy DIO", "{:.1f}"),
        ("legacy_fill", "Legacy fill", "{:.2%}"),
        ("rop_dio", "ROP DIO", "{:.1f}"),
        ("rop_fill", "ROP fill", "{:.2%}"),
        ("ddmrp_dio", "DDMRP DIO", "{:.1f}"),
        ("ddmrp_fill", "DDMRP fill", "{:.2%}"),
        ("rop_dio_at_legacy_fill", "ROP DIO at legacy fill", "{:.1f}"),
        ("ddmrp_dio_at_legacy_fill", "DDMRP DIO at legacy fill", "{:.1f}"),
    ]
    md += ["", "## Other seeds (year 2)", "", _fmt_table(robustness, rob_cols)]
    (out_dir / "results.md").write_text("\n".join(md) + "\n")

    charts.buffer_chart(ddmrp_trace, trace_labels, sim_dates, out_dir / "buffer_chart.png")
    defaults = {
        name: (res["year_2"]["value_fill_rate"], res["year_2"]["dio_days"])
        for name, res in results.items()
        if name in ("min-max (legacy)", "reorder point (tuned)", "DDMRP")
    }
    charts.frontier_chart(curves, defaults, out_dir / "frontier.png")
    charts.inventory_chart(inventory_series, sim_dates, out_dir / "inventory_value.png")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=Path("data"))
    parser.add_argument("--out", type=Path, default=Path("outputs"))
    parser.add_argument("--seed", type=int, default=config.SEED)
    parser.add_argument("--extra-seeds", type=int, default=3, help="repeat on this many fresh ranges")
    args = parser.parse_args()
    summary = run(args.data, args.out, args.seed, args.extra_seeds)
    print((args.out / "results.md").read_text())
    print(f"opening DIO {summary['opening_dio_days']:.1f} days; wrote {args.out}/")


if __name__ == "__main__":
    main()
