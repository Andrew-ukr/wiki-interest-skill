"""End-to-end (offline): fake Wikidata/MediaWiki/Pageviews -> run -> charts -> 1-page PDF."""
import re

from conftest import MONTHS_24, FakeClient, pv_items, seasonal
from wikiinterest.pipeline import load_run, run_analysis, save_run
from wikiinterest.report import build_report, check_conclusion_numbers, check_conclusion_wording

SERIES = {
    ("cs", "Přerušovaný_půst"): seasonal(24, 3000, growth_per_year=0.5, noise=0.02),
    ("cs", "Intermittent_fasting"): [3] * 24,  # redirect
    ("uk", "Інтервальне_голодування"): seasonal(24, 2000, noise=0.02),
}
EDITION = {"cs": [50_000_000] * 24, "uk": [80_000_000] * 24, "pl": [150_000_000] * 24}


def router(url: str):
    if "wikidata.org" in url and "wbgetentities" in url:
        return 200, {"entities": {"Q1666254": {
            "id": "Q1666254",
            "labels": {"en": {"value": "intermittent fasting"}, "uk": {"value": "Інтервальне голодування"}},
            "descriptions": {"en": {"value": "diet"}},
            "sitelinks": {"cswiki": {"title": "Přerušovaný půst"}, "ukwiki": {"title": "Інтервальне голодування"},
                          "enwiki": {"title": "Intermittent fasting"}, "commonswiki": {"title": "x"}},
        }}}
    if "wikipedia.org/w/api.php" in url and "list=search" in url:
        return 200, {"query": {"search": [{"title": "Stres oksydacyjny"}, {"title": "Intermittent fasting (dieta)"}]}}
    if "wikipedia.org/w/api.php" in url:
        lang = re.search(r"https://(\w+)\.wikipedia", url).group(1)
        title = re.search(r"titles=([^&]+)", url).group(1).replace("+", " ")
        redirects = [{"title": "Intermittent fasting"}] if lang == "cs" else []
        return 200, {"query": {"pages": [{"title": title, "redirects": redirects}]}}
    if "/aggregate/" in url:
        lang = re.search(r"aggregate/(\w+)\.wikipedia", url).group(1)
        return 200, pv_items(MONTHS_24, EDITION[lang])
    if "/per-article/" in url:
        m = re.search(r"per-article/(\w+)\.wikipedia/all-access/(\w+)/(.+?)/monthly", url)
        lang, agent, title = m.groups()
        if agent == "automated":
            return 404, {}
        values = SERIES.get((lang, title))
        return (200, pv_items(MONTHS_24, values)) if values else (404, {})
    raise AssertionError(f"unexpected url {url}")


def make_run(tmp_out):
    client = FakeClient(tmp_out, router)
    run = run_analysis(client, ["Q1666254"], ["pl", "cs", "uk"], "2024-09", "2026-08", ui_lang="uk")
    return run, save_run(run)


def test_pipeline_end_to_end(tmp_out):
    run, run_dir = make_run(tmp_out)
    langs = run["langs"]
    assert langs["pl"]["status"] == "missing"
    # unrelated search hits are dropped, hits sharing a word with the label are kept
    assert langs["pl"]["articles"][0]["hints"] == ["Intermittent fasting (dieta)"]
    assert langs["cs"]["direction"] == "growing"
    assert langs["uk"]["direction"] == "stable"
    # redirect views are summed into the article
    assert langs["cs"]["series"]["views"][0] == SERIES[("cs", "Přerušovaný_půst")][0] + 3
    assert [r["lang"] for r in run["ranking"]][:2] == ["cs", "uk"]
    loaded, _ = load_run("intermittent")
    assert loaded["run_id"] == run["run_id"]


def test_runs_in_same_second_do_not_overwrite(tmp_out):
    run, _ = make_run(tmp_out)
    twin = dict(run, run_id=run["run_id"])
    from wikiinterest.pipeline import save_run as save
    second = save(twin)
    assert second.name == run["run_id"] + "-2"


def test_report_is_one_page_pdf(tmp_out):
    run, run_dir = make_run(tmp_out)
    g = round(run["langs"]["cs"]["growth_adj"] * 100)
    result = build_report(run, run_dir, "uk", f"Чеська аудиторія росте (+{g}%), варто перевірити попит.",
                          question="Порівняй інтерес у pl та cs")
    assert result["pages"] == 1
    assert result["unverified_numbers"] == []
    pdf = open(result["pdf"], "rb").read()
    assert pdf.startswith(b"%PDF") and pdf.count(b"/Type /Page\n") + pdf.count(b"/Type /Page ") <= 2
    assert "Чеська" in open(result["markdown"], encoding="utf-8").read()


def test_conclusion_check_flags_invented_numbers(tmp_out):
    run, _ = make_run(tmp_out)
    bad = check_conclusion_numbers(run, "Польська аудиторія зросла на 73%, у 11/12 місяців вище.")
    assert "73%" in bad and "11/12" in bad


def test_report_rejects_long_conclusion(tmp_out):
    run, run_dir = make_run(tmp_out)
    try:
        build_report(run, run_dir, "uk", "x" * 900)
    except ValueError as exc:
        assert "700" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_growth_wording_flagged_only_when_nothing_grows(tmp_out):
    run, _ = make_run(tmp_out)  # cs is growing in the fixture
    assert check_conclusion_wording(run, "Чеська аудиторія зростає.") == ""
    for m in run["langs"].values():
        if m.get("direction") == "growing":
            m["direction"] = "stable"
    assert "growth wording" in check_conclusion_wording(run, "Турецька — стійке зростання інтересу.")
    assert check_conclusion_wording(run, "Інтерес стабільний, зростання немає.") == ""  # negation is fine
    assert check_conclusion_wording(run, "Інтерес не зростає.") == ""


def test_answer_checklist_lists_every_language(tmp_out):
    from wikiinterest.cli import answer_checklist

    run, _ = make_run(tmp_out)
    text = answer_checklist(run)
    assert "pl=NO ARTICLE" in text and "cs=growing" in text and "uk=stable" in text


def test_conclusion_check_covers_view_counts(tmp_out):
    run, _ = make_run(tmp_out)
    median = run["langs"]["cs"]["median_monthly"]
    ok = f"Чеська: {median:,} переглядів на місяць у 2025 році.".replace(",", " ")
    assert check_conclusion_numbers(run, ok) == []
    assert check_conclusion_numbers(run, "Чеська: 751 переглядів на місяць.") == ["751"]
    assert check_conclusion_numbers(run, "Тема Q1666254 (див. також Q130192).") == []  # QIDs are not counts


def test_draft_facts_cover_all_languages(tmp_out):
    from wikiinterest.report import draft_facts

    run, _ = make_run(tmp_out)
    text = draft_facts(run, "uk")
    assert "Чеська" in text and "Українська" in text and "Польська" in text and "Обмеження" in text
