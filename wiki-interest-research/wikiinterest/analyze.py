"""Metrics, trust assessment and ranking. Pure functions over monthly series.

Every threshold lives in the constants below and is explained in
references/methodology.md, so the agent (and the reader of the report) can see
exactly why a result got "high", "medium" or "low" confidence.
"""
from __future__ import annotations

import math
from typing import Sequence

import numpy as np

STABLE_BAND = 0.10  # |growth| below 10% -> "stable"
LOW_VOLUME = 100  # median views/month below this -> confidence at most "low"
MEDIUM_VOLUME = 1000  # below this -> at most "medium"
AUTOMATED_SHARE_FLAG = 0.20  # automated/(automated+user) above this -> suspicious traffic
SPIKE_Z = 3.5  # robust z-score of a spike month
SPIKE_MIN_RATIO = 2.0  # and at least 2x the median month
SEASONAL_RATIO = 1.5  # same calendar month elevated in another year -> seasonal, not news
CONSISTENT_MONTHS = 9  # >= 9 of 12 months above (or below) last year -> consistent
MK_ALPHA = 0.05
TRUST_VALUE = {"high": 1.0, "medium": 0.5, "low": 0.0}
# Data-quality flags that limit the confidence level regardless of the checks.
CAPS = {
    "low": ("low_volume", "too_short", "article_new_or_renamed"),
    "medium": ("modest_volume", "short_period", "high_automated", "incomplete_basket"),
}
DEFAULT_WEIGHTS = {"growth": 2.0, "size": 1.0, "intensity": 1.0, "trust": 1.0}


# --- small statistics ---------------------------------------------------------------------
def pct_change(new: float, old: float) -> float | None:
    if old is None or new is None or old <= 0:
        return None
    return new / old - 1.0


def theil_sen_slope(y: Sequence[float]) -> float:
    """Median of pairwise slopes; robust to outliers (a single viral month)."""
    y = np.asarray(y, dtype=float)
    n = len(y)
    if n < 3:
        return 0.0
    i, j = np.triu_indices(n, k=1)
    return float(np.median((y[j] - y[i]) / (j - i)))


def mann_kendall_p(y: Sequence[float]) -> float:
    """Two-sided p-value of the Mann-Kendall monotonic trend test (normal approx., tie-corrected)."""
    y = np.asarray(y, dtype=float)
    n = len(y)
    if n < 4:
        return 1.0
    i, j = np.triu_indices(n, k=1)
    s = float(np.sign(y[j] - y[i]).sum())
    _, counts = np.unique(y, return_counts=True)
    ties = float(np.sum(counts * (counts - 1) * (2 * counts + 5)))
    var = (n * (n - 1) * (2 * n + 5) - ties) / 18.0
    if var <= 0:
        return 1.0
    if s > 0:
        z = (s - 1) / math.sqrt(var)
    elif s < 0:
        z = (s + 1) / math.sqrt(var)
    else:
        z = 0.0
    return float(math.erfc(abs(z) / math.sqrt(2)))


def deseasonalize(log_values: np.ndarray, months: Sequence[str]) -> np.ndarray:
    """Remove the average calendar-month effect (needs >= 2 full years)."""
    if len(log_values) < 24:
        return log_values
    cal = np.array([int(m[5:7]) for m in months])
    out = log_values.copy()
    grand = log_values.mean()
    for c in range(1, 13):
        mask = cal == c
        if mask.any():
            out[mask] = log_values[mask] - log_values[mask].mean() + grand
    return out


def find_spikes(values: Sequence[int], months: Sequence[str]) -> list[dict]:
    v = np.asarray(values, dtype=float)
    if len(v) < 6 or v.max() <= 0:
        return []
    med = float(np.median(v))
    mad = float(np.median(np.abs(v - med))) * 1.4826 or max(med * 0.1, 1.0)
    spikes = []
    for idx, (month, value) in enumerate(zip(months, v)):
        z = (value - med) / mad
        if z < SPIKE_Z or value < SPIKE_MIN_RATIO * max(med, 1.0):
            continue
        same_cal = [v[k] for k, m in enumerate(months) if m[5:7] == month[5:7] and k != idx]
        seasonal = any(x >= SEASONAL_RATIO * med for x in same_cal)
        spikes.append(
            {"month": month, "views": int(value), "x_median": round(value / max(med, 1.0), 1), "seasonal": seasonal}
        )
    spikes.sort(key=lambda s: -s["views"])
    return spikes[:5]


def growth_excluding_top(values: Sequence[int], k: int = 2) -> float | None:
    """Last-12 vs previous-12 on monthly means, after dropping the k biggest months of the window."""
    v = np.asarray(values[-24:], dtype=float)
    if len(v) < 24:
        return None
    keep = np.ones(24, dtype=bool)
    keep[np.argsort(v)[-k:]] = False
    prev, last = v[:12][keep[:12]], v[12:][keep[12:]]
    if len(prev) == 0 or len(last) == 0:
        return None
    return pct_change(float(last.mean()), float(prev.mean()))


# --- per-language analysis ---------------------------------------------------------------------
def analyze_series(
    months: list[str],
    views: list[int],
    project_totals: list[int],
    automated: list[int] | None = None,
    main_views: list[int] | None = None,
    extra_flags: list[str] | None = None,
) -> dict:
    """Metrics for one language.

    Primary signal = the topic's *share* of all human views of that Wikipedia edition
    ("adjusted" change). Raw views are context: Wikipedia traffic itself shifts by
    10-25% a year (e.g. readers moving to AI assistants), which would otherwise make
    almost every topic look like it is declining.
    """
    n = len(months)
    v = np.asarray(views, dtype=float)
    totals = np.asarray(project_totals, dtype=float)
    share = np.divide(v * 1e6, totals, out=np.zeros_like(v), where=totals > 0)
    flags: list[str] = list(extra_flags or [])

    m: dict = {
        "months_n": n,
        "total_views": int(v.sum()),
        "median_monthly": int(np.median(v)) if n else 0,
        "share_per_million_median": float(np.median(share)) if n else 0.0,
        "growth_adj": None,  # change of topic share (last 12 vs previous 12 months)
        "growth_raw": None,  # change of raw views
        "project_growth": None,  # change of the whole edition
        "growth_adj_ex_spikes": None,
        "yoy_up": None,  # months (of last 12) where the share beat the same month a year earlier
        "yoy_n": 0,
        "trend_adj_per_year": None,
        "mk_p": None,
        "long_change_adj": None,
        "long_change_raw": None,
        "cagr_adj": None,
        "automated_share": None,
        "zero_months": int((v == 0).sum()),
        "leading_zero_months": int(np.argmax(v > 0)) if (v > 0).any() else n,
        "spikes": find_spikes(views, months),
    }

    if n >= 24:
        m["growth_raw"] = pct_change(v[-12:].sum(), v[-24:-12].sum())
        m["project_growth"] = pct_change(totals[-12:].sum(), totals[-24:-12].sum())
        m["growth_adj"] = pct_change(
            v[-12:].sum() / max(totals[-12:].sum(), 1), v[-24:-12].sum() / max(totals[-24:-12].sum(), 1)
        )
        m["growth_adj_ex_spikes"] = growth_excluding_top(share)
        m["yoy_up"] = int((share[-12:] > share[-24:-12]).sum())
        m["yoy_n"] = 12
    elif n >= 6:
        flags.append("short_period")
        h = n // 2
        m["growth_raw"] = pct_change(v[-h:].mean(), v[:h].mean())
        m["growth_adj"] = pct_change(share[-h:].mean(), share[:h].mean())
        m["project_growth"] = pct_change(totals[-h:].mean(), totals[:h].mean())
    else:
        flags.append("too_short")

    if n >= 36:
        m["long_change_raw"] = pct_change(v[-12:].sum(), v[:12].sum())
        m["long_change_adj"] = pct_change(share[-12:].mean(), share[:12].mean())
        if m["long_change_adj"] is not None and m["long_change_adj"] > -1:
            m["cagr_adj"] = (1 + m["long_change_adj"]) ** (12 / (n - 12)) - 1

    if n >= 6 and share.max() > 0:
        ls = deseasonalize(np.log(share + 1e-3), months)
        m["trend_adj_per_year"] = math.expm1(theil_sen_slope(ls) * 12)
        m["mk_p"] = mann_kendall_p(ls)

    if automated is not None and main_views is not None:
        auto, user = float(sum(automated)), float(sum(main_views))
        if auto + user > 0:
            m["automated_share"] = auto / (auto + user)
            if m["automated_share"] > AUTOMATED_SHARE_FLAG:
                flags.append("high_automated")

    if m["median_monthly"] < LOW_VOLUME:
        flags.append("low_volume")
    elif m["median_monthly"] < MEDIUM_VOLUME:
        flags.append("modest_volume")
    if 2 <= m["leading_zero_months"] < n:
        flags.append("article_new_or_renamed")
    elif m["zero_months"] >= 2 and m["median_monthly"] > 0:
        flags.append("gaps")
    if any(not s["seasonal"] for s in m["spikes"]):
        flags.append("news_spikes")
    if any(s["seasonal"] for s in m["spikes"]):
        flags.append("seasonal_peaks")

    m["flags"] = flags
    m["direction"] = direction(m)
    m["confidence"], m["checks"] = confidence(m)
    return m


def direction(m: dict) -> str:
    g = m["growth_adj"] if m["growth_adj"] is not None else m["growth_raw"]
    if g is None:
        return "insufficient_data"
    g = round(g, 2)  # decide on the value the reader sees (whole percent), so "-10%" never reads "stable"
    if g >= STABLE_BAND:
        return "growing"
    if g <= -STABLE_BAND:
        return "declining"
    return "stable"


def confidence(m: dict) -> tuple[str, list[dict]]:
    """Confidence in the *direction* label. Returns (level, checks[]) with a reason per check."""
    d = m["direction"]
    checks: list[dict] = []
    if d == "insufficient_data":
        return "low", [{"code": "insufficient_data", "ok": False}]

    up, yn, ge, raw = m["yoy_up"], m["yoy_n"], m["growth_adj_ex_spikes"], m["growth_raw"]
    if d in ("growing", "declining"):
        sign = 1 if d == "growing" else -1
        if yn:
            ok = up >= CONSISTENT_MONTHS if sign > 0 else up <= yn - CONSISTENT_MONTHS
            checks.append({"code": "consistency", "ok": ok, "up": up, "n": yn})
        if ge is not None:
            checks.append({"code": "robust_to_spikes", "ok": sign * ge >= 0.05, "value": ge})
        if raw is not None:
            # Absolute views should not contradict the adjusted direction (5 pp tolerance).
            checks.append({"code": "raw_agrees", "ok": sign * raw > -0.05, "value": raw,
                           "project": m["project_growth"]})
        if m["mk_p"] is not None:
            tr = m["trend_adj_per_year"] or 0
            checks.append({"code": "significant_trend", "ok": m["mk_p"] < MK_ALPHA and (tr > 0) == (sign > 0),
                           "p": m["mk_p"], "trend": tr})
    else:  # stable
        if yn:
            checks.append({"code": "no_consistent_shift", "ok": 3 <= up <= 9, "up": up, "n": yn})
        if ge is not None:
            checks.append({"code": "stable_without_spikes", "ok": abs(ge) < STABLE_BAND, "value": ge})
        if m["mk_p"] is not None:
            checks.append({"code": "no_significant_trend", "ok": m["mk_p"] >= MK_ALPHA, "p": m["mk_p"],
                           "trend": m["trend_adj_per_year"] or 0})

    passed = sum(c["ok"] for c in checks)
    ratio = passed / len(checks) if checks else 0
    level = "high" if ratio >= 0.75 else "medium" if ratio >= 0.5 else "low"
    for cap, cap_flags in CAPS.items():
        hit = [f for f in m["flags"] if f in cap_flags]
        if hit:
            checks.append({"code": f"cap_{cap}", "ok": False, "flags": hit})
            if TRUST_VALUE[cap] < TRUST_VALUE[level]:
                level = cap
    return level, checks


# --- ranking -----------------------------------------------------------------------------------------
def parse_weights(text: str | None) -> dict[str, float]:
    weights = dict(DEFAULT_WEIGHTS)
    if not text:
        return weights
    for part in text.split(","):
        if not part.strip():
            continue
        key, _, value = part.partition("=")
        key = key.strip()
        if key not in weights:
            raise ValueError(f"unknown weight {key!r}; allowed: {', '.join(weights)}")
        weights[key] = float(value)
    return weights


def _minmax(values: list[float]) -> list[float]:
    lo, hi = min(values), max(values)
    if hi - lo < 1e-12:
        return [0.5] * len(values)
    return [(x - lo) / (hi - lo) for x in values]


def rank_languages(per_lang: dict[str, dict], weights: dict[str, float]) -> list[dict]:
    """Composite score of growth, size, intensity and trust (min-max normalised across languages)."""
    langs = [l for l, m in per_lang.items() if m.get("status") != "missing"]
    missing = [l for l, m in per_lang.items() if m.get("status") == "missing"]
    rows = []
    if langs:
        growth = []
        for l in langs:
            m = per_lang[l]
            g = m["growth_adj"] if m["growth_adj"] is not None else m["growth_raw"]
            growth.append(min(max(g if g is not None else 0.0, -0.5), 1.0))
        comps = {
            "growth": _minmax(growth),
            "size": _minmax([math.log10(1 + per_lang[l]["median_monthly"]) for l in langs]),
            "intensity": _minmax([per_lang[l]["share_per_million_median"] for l in langs]),
            "trust": [TRUST_VALUE[per_lang[l]["confidence"]] for l in langs],
        }
        total_w = sum(weights.values()) or 1.0
        for i, l in enumerate(langs):
            score = sum(weights[k] * comps[k][i] for k in weights) / total_w
            rows.append({"lang": l, "score": round(score, 3),
                         "components": {k: round(comps[k][i], 2) for k in comps}})
        rows.sort(key=lambda r: -r["score"])
    for i, row in enumerate(rows, 1):
        row["rank"] = i
    rows += [{"lang": l, "score": None, "rank": None, "components": {}, "note": "no_article"} for l in missing]
    return rows
