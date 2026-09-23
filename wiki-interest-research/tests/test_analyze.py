import numpy as np
import pytest

from conftest import MONTHS_24, seasonal
from wikiinterest.analyze import (
    analyze_series,
    find_spikes,
    mann_kendall_p,
    parse_weights,
    rank_languages,
    theil_sen_slope,
)

FLAT_EDITION = [100_000_000] * 24


def test_theil_sen_ignores_single_outlier():
    y = list(range(20))
    y[10] = 500
    assert theil_sen_slope(y) == pytest.approx(1.0)


def test_mann_kendall_detects_monotonic_trend_and_not_noise():
    assert mann_kendall_p(np.arange(24)) < 0.001
    rng = np.random.default_rng(0)
    assert mann_kendall_p(rng.normal(size=24)) > 0.05


def test_growing_topic_with_seasonality_is_growing_high_confidence():
    views = seasonal(24, 5000, growth_per_year=0.4, amplitude=0.3, noise=0.03)
    m = analyze_series(MONTHS_24, views, FLAT_EDITION)
    assert m["direction"] == "growing"
    assert m["confidence"] == "high"
    assert m["growth_adj"] == pytest.approx(0.4, abs=0.08)
    assert m["yoy_up"] >= 11


def test_seasonal_flat_topic_is_stable_and_peaks_are_seasonal():
    views = seasonal(24, 3000, amplitude=0.0, noise=0.02)
    views[0] = views[12] = 12000  # September peak every year (school year)
    m = analyze_series(MONTHS_24, views, FLAT_EDITION)
    assert m["direction"] == "stable"
    assert "seasonal_peaks" in m["flags"]
    assert "news_spikes" not in m["flags"]


def test_wikipedia_wide_decline_is_not_topic_decline():
    """Topic and whole edition both lose 20%: raw views fall, adjusted change is ~0 -> stable."""
    edition = seasonal(24, 100_000_000, growth_per_year=-0.2)
    views = seasonal(24, 4000, growth_per_year=-0.2, noise=0.02)
    m = analyze_series(MONTHS_24, views, edition)
    assert m["growth_raw"] < -0.15
    assert abs(m["growth_adj"]) < 0.05
    assert m["direction"] == "stable"


def test_single_news_spike_does_not_make_growth_trustworthy():
    views = seasonal(24, 2000, noise=0.03)
    views[20] = 30000  # one viral month in the last year
    m = analyze_series(MONTHS_24, views, FLAT_EDITION)
    assert m["growth_raw"] > 0.4  # naive comparison says "big growth"
    assert "news_spikes" in m["flags"]
    assert m["spikes"][0]["month"] == MONTHS_24[20] and not m["spikes"][0]["seasonal"]
    assert m["confidence"] != "high"


def test_low_volume_caps_confidence():
    views = seasonal(24, 40, growth_per_year=0.8, noise=0.02)
    m = analyze_series(MONTHS_24, views, FLAT_EDITION)
    assert "low_volume" in m["flags"]
    assert m["confidence"] == "low"


def test_article_created_mid_period_is_flagged():
    views = [0] * 6 + seasonal(18, 3000)
    m = analyze_series(MONTHS_24, views, FLAT_EDITION)
    assert "article_new_or_renamed" in m["flags"]
    assert m["confidence"] == "low"


def test_short_period_uses_halves_and_caps_medium():
    months = MONTHS_24[:12]
    views = seasonal(12, 5000, growth_per_year=1.0, noise=0.01)
    m = analyze_series(months, views, FLAT_EDITION[:12])
    assert "short_period" in m["flags"]
    assert m["yoy_n"] == 0
    assert m["confidence"] in ("medium", "low")


def test_find_spikes_empty_for_smooth_series():
    assert find_spikes(seasonal(24, 1000, noise=0.05), MONTHS_24) == []


def test_ranking_is_relative_and_missing_languages_last():
    good = analyze_series(MONTHS_24, seasonal(24, 5000, growth_per_year=0.4, noise=0.02), FLAT_EDITION)
    flat = analyze_series(MONTHS_24, seasonal(24, 5000, noise=0.02), FLAT_EDITION)
    per_lang = {"pl": {**flat, "status": "ok"}, "cs": {**good, "status": "ok"}, "sk": {"status": "missing"}}
    ranking = rank_languages(per_lang, parse_weights(None))
    assert [r["lang"] for r in ranking] == ["cs", "pl", "sk"]
    assert ranking[-1]["rank"] is None


def test_parse_weights_rejects_unknown_key():
    assert parse_weights("growth=3")["growth"] == 3
    with pytest.raises(ValueError):
        parse_weights("price=1")
