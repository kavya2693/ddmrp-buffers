"""Slow-mover classification from how often a SKU sells, not from how much.

A drum that sells twice a month and a bottle that sells every day can carry the same value
of demand, but only one of them justifies a buffer sized from an average.
"""

from __future__ import annotations

import numpy as np

from ddmrp_buffers.config import SlowMoverSettings

RUNNER, REPEATER, STRANGER, DORMANT = 0, 1, 2, 3
LABELS = {RUNNER: "runner", REPEATER: "repeater", STRANGER: "stranger", DORMANT: "dormant"}


def classify(window: np.ndarray, s: SlowMoverSettings) -> np.ndarray:
    """window: (days, skus) recorded demand, most recent day last, NaN for unrecorded days."""
    w = window[-s.window_days :]
    recorded = np.sum(~np.isnan(w), axis=0)
    sold = np.nan_to_num(w) > 0
    share = np.sum(sold, axis=0) / np.maximum(recorded, 1)

    any_sale = sold.any(axis=0)
    # Position of the last sale counted back from today; a SKU with no sale in the window is
    # treated as older than the window.
    days_since = np.where(any_sale, np.argmax(sold[::-1], axis=0), w.shape[0])

    cls = np.full(w.shape[1], STRANGER)
    cls[share >= s.repeater_share] = REPEATER
    cls[share >= s.runner_share] = RUNNER
    cls[days_since >= s.dormant_after_days] = DORMANT
    return cls
