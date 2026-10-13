"""Stock bookkeeping, fairness between policies and the metrics that judge them."""

import numpy as np
import pandas as pd
import pytest

from ddmrp_buffers import classify, config, data, metrics, policies, simulate


def test_generator_is_deterministic_and_shaped(small_range: data.Dataset) -> None:
    again = data.generate(seed=11, n_skus=60)
    assert np.array_equal(np.nan_to_num(small_range.demand, nan=-1), np.nan_to_num(again.demand, nan=-1))
    assert small_range.demand.shape == (1096, 60)
    s = small_range.sim_start_idx
    assert np.isnan(small_range.demand[:s]).any(), "history should carry extract gaps"
    assert not np.isnan(small_range.demand[s:]).any(), "simulated period must be complete"
    assert set(small_range.skus["source"]) == {"import", "local_blend"}


def test_save_and_load_round_trip(small_range: data.Dataset, tmp_path) -> None:
    data.save(small_range, tmp_path)
    back = data.load(tmp_path)
    assert np.allclose(np.nan_to_num(back.demand, nan=-1), np.nan_to_num(small_range.demand, nan=-1))
    assert back.bulk[["sku_idx", "due_day"]].equals(small_range.bulk[["sku_idx", "due_day"]])
    assert np.array_equal(back.initial_on_hand, small_range.initial_on_hand)


@pytest.mark.parametrize("policy", [policies.LegacyMinMax(), policies.ReorderPoint(), policies.Ddmrp()])
def test_stock_balance_holds_every_day(small_range: data.Dataset, policy: policies.Policy) -> None:
    """Opening stock + receipts - shipments = closing stock, with nothing created or lost."""
    r = simulate.simulate(small_range, policy)
    assert r.received is not None
    assert (r.on_hand >= -1e-9).all()
    assert (r.filled <= r.demand + 1e-9).all()
    previous = np.vstack([small_range.initial_on_hand, r.on_hand[:-1]])
    assert np.allclose(r.on_hand, previous + r.received - r.filled)
    # Nothing arrives that was not ordered.
    assert (r.received.sum(axis=0) <= r.ordered.sum(axis=0) + 1e-9).all()


def test_policies_see_identical_lead_times(small_range: data.Dataset) -> None:
    ctx = simulate.context(small_range)
    a = simulate.actual_lead_times(ctx, 50, seed=7)
    b = simulate.actual_lead_times(ctx, 50, seed=7)
    assert np.array_equal(a, b)
    assert (a[:, ~ctx.is_import] < 30).all()
    assert (a[:, ctx.is_import] >= 30).all()


def test_steady_demand_never_stocks_out_under_ddmrp() -> None:
    n_days = (pd.Timestamp(config.SIM_END) - pd.Timestamp(config.HISTORY_START)).days + 1
    dates = pd.date_range(config.HISTORY_START, periods=n_days, freq="D")
    skus = pd.DataFrame(
        {
            "sku": ["A"],
            "family": ["hydraulic"],
            "pack_litres": [20.0],
            "source": ["local_blend"],
            "lead_time_days": [7],
            "unit_cost": [50.0],
            "order_multiple": [1],
            "moq": [10],
            "lifecycle": ["stable"],
        }
    )
    ds = data.Dataset(
        skus=skus,
        dates=dates,
        demand=np.full((n_days, 1), 5.0),
        bulk=pd.DataFrame({"sku_idx": [], "placed_day": [], "due_day": [], "qty": []}),
        initial_on_hand=np.array([100.0]),
    )
    r = simulate.simulate(ds, policies.Ddmrp())
    assert np.allclose(r.filled, r.demand)
    # Stock stays within the buffer: about red plus green, well under the opening level.
    assert r.on_hand[100:].max() < 100


def test_open_order_counts_against_buffer_only_while_open_and_large() -> None:
    ctx = policies.Context(
        dates=pd.date_range("2024-01-01", periods=40),
        demand=np.zeros((40, 2)),
        lead_time=np.array([10, 10]),
        is_import=np.array([False, False]),
        moq=np.ones(2),
        multiple=np.ones(2),
        unit_cost=np.ones(2),
        bulk_sku=np.array([0, 1]),
        bulk_placed=np.array([5, 5]),
        bulk_due=np.array([12, 30]),
        bulk_qty=np.array([50.0, 50.0]),
    )
    thr = np.array([10.0, 10.0])
    assert list(ctx.open_spikes(4, ctx.lead_time, thr)) == [0, 0]  # not yet placed
    assert list(ctx.open_spikes(6, ctx.lead_time, thr)) == [50, 0]  # second is beyond the horizon
    assert list(ctx.open_spikes(12, ctx.lead_time, thr)) == [0, 0]  # due today: already shipped
    assert list(ctx.open_spikes(6, ctx.lead_time, np.array([60.0, 60.0]))) == [0, 0]  # too small


def test_classifier_reads_frequency_and_recency() -> None:
    w = np.zeros((180, 4))
    w[:, 0] = 1  # sells every day
    w[::4, 1] = 3  # one day in four
    w[170, 2] = 9  # one recent sale
    w[10, 3] = 9  # one sale, long ago
    assert list(classify.classify(w, config.SLOW)) == [
        classify.RUNNER,
        classify.REPEATER,
        classify.STRANGER,
        classify.DORMANT,
    ]


def test_kpis_on_hand_example() -> None:
    r = simulate.SimResult(
        name="x",
        on_hand=np.array([[10.0], [30.0]]),
        demand=np.array([[4.0], [4.0]]),
        filled=np.array([[4.0], [2.0]]),
        ordered=np.array([[0.0], [5.0]]),
    )
    k = metrics.kpis(r, np.array([2.0]), slice(None))
    assert k["avg_inventory_value"] == 40.0  # mean of 20 and 60
    assert k["dio_days"] == pytest.approx(40.0 / 6.0)  # COGS per day = (8 + 4) / 2
    assert k["value_fill_rate"] == pytest.approx(0.75)
    assert k["stockout_sku_day_share"] == 0.5


def test_matched_service_interpolates_and_admits_misses() -> None:
    pts = [(0.90, 30.0), (0.95, 40.0), (0.99, 60.0)]
    assert metrics.stock_at_matched_service(pts, 0.97) == pytest.approx(50.0)
    assert metrics.stock_at_matched_service(pts, 0.995) is None
