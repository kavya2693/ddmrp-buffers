"""Buffer arithmetic against a hand-worked example, before any simulation exists."""

import numpy as np
import pytest

from ddmrp_buffers import buffers
from ddmrp_buffers.config import DdmrpSettings

S = DdmrpSettings()


def test_zones_match_hand_worked_example() -> None:
    # ADU 10, DLT 10 days (short, LTF 0.7), weekly CV 0.6 (medium, VF 0.5), MOQ 50, cycle 7 days.
    adu, dlt = np.array([10.0]), np.array([10.0])
    ltf = buffers.lead_time_factor(dlt, S)
    vf = buffers.variability_factor(np.array([0.6]), S)
    assert ltf[0] == 0.7 and vf[0] == 0.5
    z = buffers.zones(adu, dlt, ltf, vf, moq=np.array([50.0]), order_cycle_days=np.array([7.0]))
    # red base 70, red safety 35 -> red 105; yellow 100; green max(70, 50, 70) = 70
    assert z.tor[0] == pytest.approx(105)
    assert z.toy[0] == pytest.approx(205)
    assert z.tog[0] == pytest.approx(275)

    nfp = buffers.net_flow(np.array([120.0]), np.array([50.0]), np.array([30.0]))
    assert nfp[0] == 140
    q = buffers.order_quantity(nfp, z, moq=np.array([50.0]), multiple=np.array([12.0]))
    assert q[0] == 144  # 275 - 140 = 135, rounded up to a case of 12


def test_no_order_above_top_of_yellow() -> None:
    z = buffers.Zones(red=np.array([10.0]), yellow=np.array([20.0]), green=np.array([15.0]))
    assert buffers.order_quantity(np.array([30.1]), z, np.array([1.0]), np.array([1.0]))[0] == 0
    assert buffers.order_quantity(np.array([30.0]), z, np.array([1.0]), np.array([1.0]))[0] == 15


def test_moq_dominates_green_on_slow_import() -> None:
    adu, dlt = np.array([0.5]), np.array([70.0])
    z = buffers.zones(
        adu, dlt, buffers.lead_time_factor(dlt, S), np.array([0.8]), np.array([200.0]), np.array([30.0])
    )
    assert z.green[0] == 200.0
    assert z.yellow[0] == pytest.approx(35.0)


def test_unused_sku_gets_no_buffer_even_with_moq() -> None:
    z = buffers.zones(
        np.array([0.0]),
        np.array([10.0]),
        np.array([0.7]),
        np.array([0.5]),
        np.array([200.0]),
        np.array([7.0]),
    )
    assert z.tog[0] == 0
    assert buffers.order_quantity(np.array([0.0]), z, np.array([200.0]), np.array([12.0]))[0] == 0


def test_lead_time_bands() -> None:
    ltf = buffers.lead_time_factor(np.array([5, 15, 16, 40, 41, 90]), S)
    assert list(ltf) == [0.7, 0.7, 0.5, 0.5, 0.3, 0.3]


def test_broken_inputs_are_rejected() -> None:
    with pytest.raises(ValueError):
        buffers.lead_time_factor(np.array([0.0]), S)
    with pytest.raises(ValueError):
        buffers.zones(
            np.array([-1.0]),
            np.array([5.0]),
            np.array([0.7]),
            np.array([0.5]),
            np.array([1.0]),
            np.array([7.0]),
        )


def test_adu_skips_missing_days_instead_of_counting_zero() -> None:
    window = np.array([[4.0], [np.nan], [np.nan], [8.0]])
    assert buffers.average_daily_usage(window)[0] == 6.0


def test_weekly_cv_steady_demand_is_zero_and_lumpy_is_high() -> None:
    steady = np.full((84, 1), 3.0)
    lumpy = np.zeros((84, 1))
    lumpy[::20] = 100.0
    assert buffers.weekly_cv(steady)[0] == pytest.approx(0.0)
    assert buffers.weekly_cv(lumpy)[0] > 1.0
