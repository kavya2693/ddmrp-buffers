"""Buffer, frontier and inventory-over-time charts written as PNGs for the README."""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

INK, MUTED, GRID = "#1f2937", "#6b7280", "#e5e7eb"
SERIES = {
    "min-max (legacy)": "#6b7280",
    "reorder point (tuned)": "#2563eb",
    "DDMRP": "#d97706",
    "DDMRP, no order-spike visibility": "#0d9488",
    "DDMRP + slow-mover rule": "#7c3aed",
}
ZONE = {"red": "#f4a3a3", "yellow": "#f7dc8a", "green": "#a8d8a8"}


def _style(ax: plt.Axes) -> None:
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(MUTED)
    ax.tick_params(colors=MUTED, labelsize=8)


def buffer_chart(
    traces: dict[int, dict[str, np.ndarray]], labels: dict[int, str], dates: pd.DatetimeIndex, path: Path
) -> None:
    fig, axes = plt.subplots(len(traces), 1, figsize=(10, 3.1 * len(traces)), sharex=True)
    axes = np.atleast_1d(axes)
    for ax, (j, tr) in zip(axes, traces.items(), strict=True):
        ax.fill_between(dates, 0, tr["tor"], step="post", color=ZONE["red"], linewidth=0, label="red zone")
        ax.fill_between(
            dates, tr["tor"], tr["toy"], step="post", color=ZONE["yellow"], linewidth=0, label="yellow zone"
        )
        ax.fill_between(
            dates, tr["toy"], tr["tog"], step="post", color=ZONE["green"], linewidth=0, label="green zone"
        )
        ax.plot(dates, tr["on_hand"], color=INK, linewidth=1.2, label="on hand")
        ax.plot(dates, tr["nfp"], color="#2563eb", linewidth=1.0, alpha=0.8, label="net flow position")
        ax.set_title(labels[j], loc="left", fontsize=9, color=INK)
        ax.set_ylabel("units", fontsize=8, color=MUTED)
        ax.set_ylim(bottom=0)
        _style(ax)
    axes[0].legend(loc="upper right", fontsize=7, ncol=5, frameon=False)
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


def frontier_chart(
    curves: dict[str, list[tuple[float, float]]],
    defaults: dict[str, tuple[float, float]],
    path: Path,
) -> None:
    fig, ax = plt.subplots(figsize=(7.5, 4.6))
    for name, pts in curves.items():
        pts = sorted(pts)
        ax.plot(
            [p[0] * 100 for p in pts],
            [p[1] for p in pts],
            color=SERIES[name],
            linewidth=1.8,
            marker="o",
            markersize=4,
            label=f"{name}, swept",
        )
    for name, (fill, dio) in defaults.items():
        ax.scatter([fill * 100], [dio], s=70, color=SERIES[name], edgecolor="white", linewidth=1.5, zorder=5)
        ax.annotate(name, (fill * 100, dio), xytext=(6, 4), textcoords="offset points", fontsize=8, color=INK)
    ax.set_xlabel("value fill rate, year 2 (%)", fontsize=9, color=MUTED)
    ax.set_ylabel("days inventory outstanding, year 2", fontsize=9, color=MUTED)
    ax.set_title(
        "Stock held for a given service level (lower and to the right is better)", fontsize=10, loc="left"
    )
    ax.legend(fontsize=8, frameon=False, loc="upper left")
    _style(ax)
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


def inventory_chart(series: dict[str, np.ndarray], dates: pd.DatetimeIndex, path: Path) -> None:
    fig, ax = plt.subplots(figsize=(9, 4))
    for name, values in series.items():
        weekly = pd.Series(values, index=dates).resample("W").mean() / 1e6
        ax.plot(weekly.index, weekly.to_numpy(), color=SERIES[name], linewidth=1.8, label=name)
    ax.set_ylabel("inventory at cost (millions)", fontsize=9, color=MUTED)
    ax.set_title("Working capital in stock, weekly average", fontsize=10, loc="left")
    ax.set_ylim(bottom=0)
    ax.legend(fontsize=8, frameon=False)
    _style(ax)
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)
