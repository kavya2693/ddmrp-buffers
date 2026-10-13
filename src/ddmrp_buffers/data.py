"""Seeded generator for an 800-SKU lubricants range and the loader the simulation reads.

The range runs from 400 g grease cartridges to 1,000 L IBCs. Most SKUs are blended and filled
on site with lead times of one to two weeks; the rest are imported finished goods with lead
times of six weeks to three months and occasional port delays. Daily demand carries an annual
season, a weekly pattern, public holidays and a fasting month, product lifecycles (growing,
declining, phased out, newly launched), bulk fleet orders that customers announce days ahead,
and gaps in the first year's ERP extract.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from ddmrp_buffers import config

# family: (weight, packs in litres, cost per litre, import share, season amplitude, peak day-of-year)
FAMILIES: dict[str, tuple[float, list[float], float, float, float, int]] = {
    "engine_oil_passenger": (0.28, [1, 4, 5, 20, 208], 3.2, 0.20, 0.10, 200),
    "engine_oil_heavy_duty": (0.18, [5, 20, 208, 1000], 2.6, 0.15, 0.08, 120),
    "hydraulic": (0.14, [20, 208, 1000], 2.1, 0.20, 0.06, 180),
    "gear_oil": (0.10, [1, 4, 20, 208], 3.0, 0.30, 0.06, 200),
    "transmission_fluid": (0.08, [1, 4, 20, 208], 3.6, 0.35, 0.08, 200),
    "grease": (0.10, [0.4, 18, 180], 4.5, 0.60, 0.05, 150),
    "coolant": (0.07, [1, 4, 20, 208], 1.4, 0.10, 0.35, 200),
    "industrial": (0.05, [20, 208, 1000], 3.8, 0.50, 0.05, 100),
}

# Small packs cost more per litre (bottle, label, filling line time).
PACK_COST_FACTOR = {0.4: 1.8, 1: 1.4, 4: 1.15, 5: 1.15, 18: 1.0, 20: 1.0, 180: 0.9, 208: 0.9, 1000: 0.85}
CASE_SIZE = {0.4: 24, 1: 12, 4: 4, 5: 4, 18: 1, 20: 1, 180: 1, 208: 1, 1000: 1}
# Typical units on one customer order line, which sets how intermittent a SKU is.
LINE_SIZE = {0.4: 12, 1: 8, 4: 3, 5: 3, 18: 1.5, 20: 1.5, 180: 1.2, 208: 1.2, 1000: 1.0}

LIFECYCLES = ["stable", "growing", "declining", "phase_out", "new"]
LIFECYCLE_P = [0.72, 0.08, 0.12, 0.05, 0.03]

FIXED_HOLIDAYS = ["01-01", "12-02", "12-03"]
FASTING_MONTHS = [("2023-03-23", "2023-04-20"), ("2024-03-11", "2024-04-09"), ("2025-03-01", "2025-03-29")]
FEASTS = ["2023-04-21", "2023-06-28", "2024-04-10", "2024-06-16", "2025-03-30", "2025-06-06"]
ERP_OUTAGE = ("2023-08-14", "2023-08-23")


@dataclass
class Dataset:
    skus: pd.DataFrame
    dates: pd.DatetimeIndex
    demand: np.ndarray  # (days, skus) units; NaN where the history extract has a gap
    bulk: pd.DataFrame  # sku_idx, placed_day, due_day, qty (day indices into `dates`)
    initial_on_hand: np.ndarray

    @property
    def sim_start_idx(self) -> int:
        return int(self.dates.get_loc(pd.Timestamp(config.SIM_START)))


def _calendar_multiplier(dates: pd.DatetimeIndex) -> np.ndarray:
    mult = np.ones(len(dates))
    weekday_factor = np.array([1.08, 1.08, 1.08, 1.08, 0.55, 0.85, 1.08])  # Mon..Sun, Friday quiet
    mult *= weekday_factor[dates.dayofweek]
    md = dates.strftime("%m-%d")
    mult[np.isin(md, FIXED_HOLIDAYS)] *= 0.25
    for start, end in FASTING_MONTHS:
        mult[(dates >= start) & (dates <= end)] *= 0.85
    for feast in FEASTS:
        f = pd.Timestamp(feast)
        mult[(dates >= f) & (dates < f + timedelta(days=3))] *= 0.25
        # Workshops restock after the break.
        mult[(dates >= f + timedelta(days=3)) & (dates < f + timedelta(days=10))] *= 1.3
    return mult


def _lifecycle_multiplier(kind: str, n_days: int, sim_start: int, rng: np.random.Generator) -> np.ndarray:
    t = np.arange(n_days)
    if kind == "growing":
        return np.asarray(1.3 ** (t / 365.0))
    if kind == "declining":
        start = int(rng.integers(0, n_days // 2))
        return np.where(t < start, 1.0, 0.5 ** ((t - start) / 365.0))
    if kind == "phase_out":
        stop = int(rng.integers(sim_start - 120, n_days - 200))
        ramp = np.clip((stop - t) / 60.0, 0.0, 1.0)
        return np.asarray(ramp)
    if kind == "new":
        launch = int(rng.integers(sim_start - 150, sim_start + 200))
        return np.where(t < launch, 0.0, np.clip((t - launch) / 90.0, 0.2, 1.0))
    return np.ones(n_days)


def generate(seed: int = config.SEED, n_skus: int = config.N_SKUS) -> Dataset:
    rng = np.random.default_rng(seed)
    dates = pd.date_range(config.HISTORY_START, config.SIM_END, freq="D")
    n_days = len(dates)
    sim_start = int(dates.get_loc(pd.Timestamp(config.SIM_START)))

    names = list(FAMILIES)
    weights = np.array([FAMILIES[f][0] for f in names])
    rows = []
    for i in range(n_skus):
        fam = names[int(rng.choice(len(names), p=weights / weights.sum()))]
        _, packs, cpl, import_share, _, _ = FAMILIES[fam]
        pack = float(packs[int(rng.integers(len(packs)))])
        source = "import" if rng.random() < import_share else "local_blend"
        if source == "import":
            lt = int(rng.integers(45, 91))
            moq_litres = 1000.0 if pack == 1000 else (832.0 if pack >= 180 else 800.0)
        else:
            lt = int(rng.integers(5, 15))
            moq_litres = pack if pack >= 180 else 200.0
        case = CASE_SIZE[pack]
        moq = int(np.ceil(max(moq_litres / pack, case) / case) * case)
        unit_cost = round(pack * cpl * PACK_COST_FACTOR[pack] * float(rng.lognormal(0, 0.25)), 2)
        rows.append(
            {
                "sku": f"LUB-{i + 1:04d}",
                "family": fam,
                "pack_litres": pack,
                "source": source,
                "lead_time_days": lt,
                "unit_cost": unit_cost,
                "order_multiple": case,
                "moq": moq,
                "lifecycle": LIFECYCLES[int(rng.choice(len(LIFECYCLES), p=LIFECYCLE_P))],
            }
        )
    skus = pd.DataFrame(rows)

    # Volume in litres per day is heavy tailed: a few grades carry most of the throughput.
    litres_per_day = rng.lognormal(np.log(18.0), 1.4, n_skus)
    adu_units = litres_per_day / skus["pack_litres"].to_numpy()

    cal = _calendar_multiplier(dates)
    doy = dates.dayofyear.to_numpy()
    adu = np.empty((n_days, n_skus))
    for j in range(n_skus):
        _, _, _, _, amp, peak = FAMILIES[str(skus.at[j, "family"])]
        amp_j = amp * float(rng.uniform(0.6, 1.4))
        season = 1.0 + amp_j * np.cos(2 * np.pi * (doy - peak) / 365.25)
        life = _lifecycle_multiplier(str(skus.at[j, "lifecycle"]), n_days, sim_start, rng)
        adu[:, j] = adu_units[j] * season * cal * life

    line = skus["pack_litres"].map(LINE_SIZE).to_numpy()
    p_sale = 1.0 - np.exp(-adu / line)
    sold = rng.random(adu.shape) < p_sale
    mean_size = np.maximum(adu / np.maximum(p_sale, 1e-9), 1.0)
    lam = rng.gamma(2.0, (mean_size - 1.0) / 2.0 + 1e-9)
    demand = np.where(sold, 1.0 + rng.poisson(lam), 0.0)

    bulk_rows = []
    for j in range(n_skus):
        pack = float(skus.at[j, "pack_litres"])
        if pack >= 18 and rng.random() < 0.6:
            per_year = rng.uniform(2, 8)
        elif rng.random() < 0.15:
            per_year = 2.0
        else:
            continue
        n_orders = int(rng.poisson(per_year * n_days / 365.0))
        for due in rng.integers(30, n_days, n_orders):
            base = float(np.mean(adu[max(0, due - 90) : due, j]))
            if base <= 0:
                continue
            qty = max(2.0, round(base * float(rng.uniform(15, 45))))
            bulk_rows.append((j, int(due - rng.integers(3, 22)), int(due), qty))
    bulk = pd.DataFrame(bulk_rows, columns=["sku_idx", "placed_day", "due_day", "qty"])
    np.add.at(demand, (bulk["due_day"].to_numpy(), bulk["sku_idx"].to_numpy()), bulk["qty"].to_numpy())

    recorded = demand.copy()
    hist = recorded[:sim_start]
    hist[rng.random(hist.shape) < 0.02] = np.nan
    outage = (dates[:sim_start] >= ERP_OUTAGE[0]) & (dates[:sim_start] <= ERP_OUTAGE[1])
    hist[outage, :] = np.nan

    # Opening stock reflects how the range was run before: generous cover, more of it on imports,
    # and stock left behind on SKUs whose demand has started to fall away.
    hist_adu = np.nan_to_num(np.nanmean(recorded[sim_start - 180 : sim_start], axis=0))
    cover = rng.lognormal(np.log(110.0), 0.5, n_skus)
    cover = np.where(skus["source"] == "import", cover * 1.6, cover)
    cover = np.where(skus["lifecycle"].isin(["declining", "phase_out"]), cover * 1.6, cover)
    mult = skus["order_multiple"].to_numpy()
    initial = np.ceil(hist_adu * cover / mult) * mult

    return Dataset(skus=skus, dates=dates, demand=recorded, bulk=bulk, initial_on_hand=initial)


def save(ds: Dataset, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    skus = ds.skus.copy()
    skus["initial_on_hand"] = ds.initial_on_hand
    skus.to_csv(out_dir / "skus.csv", index=False)
    long = pd.DataFrame(ds.demand, index=ds.dates, columns=ds.skus["sku"]).stack(future_stack=True)
    long = long.rename("qty").reset_index().rename(columns={"level_0": "date"})
    long.to_csv(out_dir / "demand.csv.gz", index=False, compression="gzip")
    bulk = ds.bulk.copy()
    bulk["sku"] = ds.skus["sku"].to_numpy()[bulk["sku_idx"]]
    bulk["placed_date"] = ds.dates[bulk["placed_day"].clip(lower=0)].date
    bulk["due_date"] = ds.dates[bulk["due_day"]].date
    bulk[["sku", "placed_date", "due_date", "qty"]].to_csv(out_dir / "bulk_orders.csv", index=False)


def load(data_dir: Path) -> Dataset:
    skus = pd.read_csv(data_dir / "skus.csv")
    long = pd.read_csv(data_dir / "demand.csv.gz", parse_dates=["date"])
    wide = long.pivot(index="date", columns="sku", values="qty")[skus["sku"]]
    dates = pd.DatetimeIndex(wide.index)
    bulk_raw = pd.read_csv(data_dir / "bulk_orders.csv", parse_dates=["placed_date", "due_date"])
    sku_pos = {s: i for i, s in enumerate(skus["sku"])}
    bulk = pd.DataFrame(
        {
            "sku_idx": bulk_raw["sku"].map(sku_pos).astype(int),
            "placed_day": dates.get_indexer(bulk_raw["placed_date"]),
            "due_day": dates.get_indexer(bulk_raw["due_date"]),
            "qty": bulk_raw["qty"].astype(float),
        }
    )
    initial = skus.pop("initial_on_hand").to_numpy(dtype=float)
    return Dataset(
        skus=skus, dates=dates, demand=wide.to_numpy(dtype=float), bulk=bulk, initial_on_hand=initial
    )


def summary(ds: Dataset) -> dict[str, float]:
    s = ds.sim_start_idx
    sim = ds.demand[s:]
    cost = ds.skus["unit_cost"].to_numpy()
    b = ds.bulk[ds.bulk["due_day"] >= s]
    bulk_value = (b["qty"].to_numpy() * cost[b["sku_idx"].to_numpy()]).sum()
    return {
        "skus": float(len(ds.skus)),
        "days_total": float(len(ds.dates)),
        "days_simulated": float(sim.shape[0]),
        "import_share": float((ds.skus["source"] == "import").mean()),
        "history_missing_share": float(np.isnan(ds.demand[:s]).mean()),
        "bulk_orders": float(len(ds.bulk)),
        "zero_demand_day_share": float((sim == 0).mean()),
        "bulk_share_of_simulated_demand_value": float(bulk_value / (sim * cost).sum()),
    }
