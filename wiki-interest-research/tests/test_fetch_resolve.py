import datetime as dt

import pytest

from conftest import FakeClient, pv_items
from wikiinterest.fetch import (
    _items_to_series,
    add_months,
    article_series,
    encode_title,
    last_complete_month,
    month_range,
    resolve_period,
)
from wikiinterest.resolve import Candidate, choose, parse_langs, site_to_lang


def test_month_helpers():
    assert add_months("2025-12", 1) == "2026-01"
    assert add_months("2025-01", -1) == "2024-12"
    assert len(month_range("2024-09", "2026-08")) == 24


def test_last_complete_month_waits_for_publication():
    assert last_complete_month(dt.date(2026, 9, 23)) == "2026-08"
    assert last_complete_month(dt.date(2026, 9, 2)) == "2026-07"


def test_resolve_period_defaults_and_validation():
    today = dt.date(2026, 9, 23)
    assert resolve_period(24, None, None, today) == ("2024-09", "2026-08")
    assert resolve_period(None, "2014-01", "2015-12", today)[0] == "2015-07"  # API starts 2015-07
    with pytest.raises(ValueError):
        resolve_period(None, None, "2026-09", today)  # not complete yet
    with pytest.raises(ValueError):
        resolve_period(None, "2026-05", "2026-01", today)


def test_missing_months_are_zero_filled():
    months = month_range("2025-01", "2025-04")
    items = pv_items(months, [5, 0, 7, 0])["items"]
    assert len(items) == 2
    assert _items_to_series(items, months) == [5, 0, 7, 0]


def test_404_series_means_zero_views(tmp_path):
    client = FakeClient(tmp_path, lambda url: (404, {"title": "Not Found"}))
    assert article_series(client, "pl", "Nic", month_range("2025-01", "2025-03")) == [0, 0, 0]


def test_title_encoding_escapes_slash_and_spaces():
    assert encode_title("AC/DC band") == "AC%2FDC_band"


def test_site_codes():
    assert site_to_lang("plwiki") == "pl"
    assert site_to_lang("zh_yuewiki") == "zh-yue"
    assert site_to_lang("be_x_oldwiki") == "be-tarask"
    assert site_to_lang("commonswiki") is None
    assert site_to_lang("enwikiquote") is None


def test_parse_langs():
    assert parse_langs("pl, cs  uk,pl") == ["pl", "cs", "uk"]
    assert parse_langs(["de.wikipedia"]) == ["de"]


def test_choose_prefers_popular_exact_match_and_flags_ambiguity():
    cands = [
        Candidate("Q613883", "Mercury", "automobile marque", 27, True, False),
        Candidate("Q308", "Mercury", "planet", 251, True, False),
        Candidate("Q925", "mercury", "chemical element", 176, True, False),
        Candidate("Q1", "Mercury", "Wikimedia disambiguation page", 90, True, True),
    ]
    best, ambiguous = choose(cands)
    assert best.qid == "Q308"
    assert ambiguous


def test_choose_unambiguous():
    cands = [Candidate("Q333", "astronomy", "natural science", 253, True, False),
             Candidate("Q5", "astronomy education", "", 3, False, False)]
    best, ambiguous = choose(cands)
    assert best.qid == "Q333" and not ambiguous
