"""PNG charts for the report. One y-axis per chart; colour follows the language, never its rank."""
from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import matplotlib.ticker as mticker  # noqa: E402
import numpy as np  # noqa: E402

from .i18n import lang_name, t  # noqa: E402

# Validated categorical palette (light surface), fixed order.
PALETTE = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"]
INK, INK_2, GRID = "#0b0b0b", "#52514e", "#e6e5e1"
MAX_SERIES = 8


def _rolling(values: np.ndarray, k: int = 3) -> np.ndarray:
    out = np.full(len(values), np.nan)
    for i in range(k - 1, len(values)):
        out[i] = values[i - k + 1: i + 1].mean()
    return out


def _style(ax, title: str) -> None:
    ax.set_title(title, fontsize=7.5, color=INK, loc="left", pad=6)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(GRID)
    ax.tick_params(colors=INK_2, labelsize=6, length=0)
    ax.grid(axis="y", color=GRID, linewidth=0.6)
    ax.set_axisbelow(True)


def _x_ticks(ax, months: list[str]) -> None:
    step = max(1, len(months) // 8)
    idx = list(range(0, len(months), step))
    ax.set_xticks(idx)
    ax.set_xticklabels([f"{months[i][5:7]}.{months[i][2:4]}" for i in idx])
    ax.set_xlim(-0.5, len(months) - 0.5)


def _series_langs(run: dict) -> list[str]:
    return [l for l in run["params"]["langs"] if run["langs"][l]["status"] != "missing"][:MAX_SERIES]


def _color(run: dict, lang: str) -> str:
    return PALETTE[run["params"]["langs"].index(lang) % len(PALETTE)]


def _end_labels(ax, items: list[tuple[float, str, str]], x: float) -> None:
    """Direct labels at line ends, nudged apart so they do not collide."""
    if not items or len(items) > 4:
        return
    lo, hi = ax.get_ylim()
    gap = (hi - lo) * 0.07
    items = sorted(items, key=lambda it: it[0])
    placed: list[float] = []
    for y, text, _color in items:
        if placed and y - placed[-1] < gap:
            y = placed[-1] + gap
        placed.append(y)
        ax.text(x + 0.6, y, text, fontsize=6, color=INK, va="center", ha="left")


def _legend(ax, n: int) -> None:
    """Legend below the plot area so it never covers the lines."""
    ax.legend(fontsize=5.5, frameon=False, loc="upper center", bbox_to_anchor=(0.5, -0.1),
              ncol=min(n, 4), handlelength=1.2, columnspacing=1.0)


def trend_chart(run: dict, out: Path, ui: str) -> Path:
    months = run["months"]
    langs = _series_langs(run)
    x = np.arange(len(months))
    fig, ax = plt.subplots(figsize=(3.75, 2.35), dpi=220)
    single = len(langs) == 1
    ends = []
    for lang in langs:
        v = np.asarray(run["langs"][lang]["series"]["views"], dtype=float)
        color = _color(run, lang)
        if single:
            y_raw, y = v, _rolling(v)
        else:
            base = v[: min(12, len(v))].mean() or 1.0
            y_raw, y = v / base * 100, _rolling(v) / base * 100
        ax.plot(x, y_raw, color=color, linewidth=0.7, alpha=0.35)
        ax.plot(x, y, color=color, linewidth=1.6, label=lang_name(lang, ui))
        for spike in run["langs"][lang].get("spikes", []):
            if spike["month"] in months and not spike["seasonal"]:
                i = months.index(spike["month"])
                ax.plot([i], [y_raw[i]], "o", ms=3.2, color=color, mec="white", mew=0.8)
        last = y[~np.isnan(y)]
        if len(last):
            ends.append((last[-1], lang_name(lang, ui), color))
    if not single:
        ax.axhline(100, color=INK_2, linewidth=0.6, linestyle=(0, (2, 2)))
    _style(ax, t(ui)["chart_trend_single" if single else "chart_trend_multi"])
    _x_ticks(ax, months)
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda val, _: f"{val:,.0f}".replace(",", " ")))
    if len(langs) > 1:
        _legend(ax, len(langs))
        if len(langs) <= 4:
            ax.set_xlim(-0.5, len(months) + 3.5)
            _end_labels(ax, ends, len(months) - 1)
    fig.tight_layout(pad=0.4)
    path = out / "trend.png"
    fig.savefig(path, facecolor="white")
    plt.close(fig)
    return path


def share_chart(run: dict, out: Path, ui: str) -> Path:
    months = run["months"]
    langs = _series_langs(run)
    x = np.arange(len(months))
    fig, ax = plt.subplots(figsize=(3.75, 2.35), dpi=220)
    for lang in langs:
        s = np.asarray(run["langs"][lang]["series"]["share_per_million"], dtype=float)
        ax.plot(x, _rolling(s), color=_color(run, lang), linewidth=1.6, label=lang_name(lang, ui))
    _style(ax, t(ui)["chart_share"])
    _x_ticks(ax, months)
    ax.set_ylim(bottom=0)
    if len(langs) > 1:
        _legend(ax, len(langs))
    fig.tight_layout(pad=0.4)
    path = out / "share.png"
    fig.savefig(path, facecolor="white")
    plt.close(fig)
    return path


def make_charts(run: dict, out: Path, ui: str = "en") -> dict[str, str]:
    if not _series_langs(run):
        return {}
    return {"trend": str(trend_chart(run, out, ui)), "share": str(share_chart(run, out, ui))}
