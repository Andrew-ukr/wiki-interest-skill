"""Command line interface. Output is compact Markdown by default (cheap for small models), --json for raw."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .analyze import parse_weights
from .api import ApiError, Client, parallel_map
from .fetch import article_series, month_range, resolve_period
from .i18n import lang_name, pct, render_check
from .pipeline import list_runs, load_run, run_analysis, save_run
from .resolve import langs_with_article, parse_langs, resolve

# Absolute path in "next:" hints so the agent can copy the command from any working directory.
WIKI = f"python3 {Path(__file__).resolve().parent.parent / 'scripts' / 'wiki.py'}"
# Largest Wikipedias by pageviews (approximate order), used by `langs` to suggest audiences.
BIG_EDITIONS = [
    "en", "ja", "de", "es", "ru", "fr", "it", "zh", "pt", "pl", "fa", "ar", "nl", "tr", "id", "uk", "sv", "he",
    "cs", "vi", "ko", "hu", "fi", "ro", "th", "el", "no", "da", "bg", "sr", "hr", "sk", "ca", "lt", "sl", "et",
    "lv", "hi", "bn", "ms", "az", "kk", "ka", "hy", "uz", "be",
]


def _num(n: int | None) -> str:
    return "—" if n is None else f"{n:,}".replace(",", " ")


def _parse_overrides(values: list[str] | None) -> dict[str, str]:
    out = {}
    for item in values or []:
        lang, sep, title = item.partition(":")
        if not sep or not title.strip():
            raise ValueError(f"--title must look like LANG:Article title, got {item!r}")
        out[lang.strip().lower()] = title.strip()
    return out


# --- resolve -----------------------------------------------------------------------------------------
def cmd_resolve(args, client: Client) -> int:
    langs = parse_langs(args.langs) or [args.lang]
    results = [resolve(client, q, langs, lang=args.lang, overrides=_parse_overrides(args.title)) for q in args.topics]
    if args.json:
        print(json.dumps([r.to_dict() for r in results], ensure_ascii=False, indent=1))
        return 0
    for r in results:
        amb = "YES - check candidates below" if r.ambiguous else "no"
        print(f"## {r.query!r} -> {r.qid}: {r.label} — {r.description} ({r.sitelinks} Wikipedias) | ambiguous: {amb}")
        for code, a in r.articles.items():
            if a.status == "missing":
                hint = f" | similar pages in {code}wiki: " + "; ".join(a.hints) if a.hints else ""
                print(f"- {code}: NO ARTICLE for this item{hint}")
            else:
                print(f"- {code}: {a.title}" + (" (override)" if a.status == "override" else ""))
        if r.ambiguous and r.candidates:
            print("candidates (pick by meaning, rerun with --qid if needed):")
            for c in r.candidates:
                mark = " [disambiguation]" if c.disambiguation else ""
                print(f"  {c.qid}: {c.label} — {c.description[:90]} ({c.sitelinks} wikis){mark}")
        if r.note:
            print(f"note: {r.note} In your answer, say which meaning you analysed and name the alternatives.")
    qids = " ".join(f"--qid {r.qid}" for r in results)
    print(f"\nnext: {WIKI} analyze {qids} --langs {','.join(langs) or '<langs>'}")
    return 0


# --- analyze -----------------------------------------------------------------------------------------
def print_summary(run: dict, run_dir: Path, charts: dict, ui: str = "uk") -> None:
    from .report import build_findings

    pr = run["params"]
    labels = ", ".join(f"{v} [{k}]" for k, v in run["topic"]["labels"].items())
    print(f"## Run {run['run_id']}")
    print(f"saved: {run_dir / 'analysis.json'}")
    print(f"topic: {labels} | period {pr['start']}..{pr['end']} ({pr['months_n']} full months) | "
          "human views (agent=user), redirects summed")
    print("\n| lang | article(s) | median views/mo | ADJUSTED change | raw views change | edition traffic | "
          "months>last yr | trend/yr | direction | confidence |")
    print("|---|---|---|---|---|---|---|---|---|---|")
    for code in pr["langs"]:
        m = run["langs"][code]
        titles = "; ".join(a["title"] or "—" for a in m["articles"])
        if m["status"] == "missing":
            print(f"| {code} | NO ARTICLE | — | — | — | — | — | — | — | — |")
            continue
        yoy = f"{m['yoy_up']}/{m['yoy_n']}" if m["yoy_n"] else "—"
        sig = "*" if (m["mk_p"] or 1) < 0.05 else ""
        print(f"| {code} | {titles} | {_num(m['median_monthly'])} | {pct(m['growth_adj'])} | "
              f"{pct(m['growth_raw'])} | {pct(m['project_growth'])} | {yoy} | {pct(m['trend_adj_per_year'])}{sig} | "
              f"{m['direction']} | {m['confidence'].upper()} |")
    print("(ADJUSTED change = change of the topic's share of all views of that Wikipedia, last 12 vs previous 12 "
          "months; it is the primary signal. * = significant trend)")

    print("\nconfidence checks:")
    for code in pr["langs"]:
        m = run["langs"][code]
        if m["status"] == "missing":
            hints = [h for a in m["articles"] for h in a["hints"]]
            print(f"- {code}: no article" + (f"; similar pages: {'; '.join(hints)}" if hints else ""))
            continue
        print(f"- {code} {m['confidence'].upper()}: " + "; ".join(render_check(c, "en") for c in m["checks"]))
    spikes = [f"{c} {s['month']} {s['x_median']}x median ({'seasonal' if s['seasonal'] else 'news?'})"
              for c in pr["langs"] for s in run["langs"][c].get("spikes", [])[:3]]
    if spikes:
        print("spikes: " + "; ".join(spikes))
    flags = [f"{c}: {', '.join(run['langs'][c]['flags'])}" for c in pr["langs"] if run["langs"][c].get("flags")]
    if flags:
        print("flags: " + " | ".join(flags))
    bots = [f"{c} {pct(run['langs'][c]['automated_share']).lstrip('+')}" for c in pr["langs"]
            if run["langs"][c].get("automated_share") is not None]
    if bots:
        print("automated (bot) share of views: " + ", ".join(bots))
    ranked = [r for r in run["ranking"] if r["rank"]]
    if len(ranked) > 1:
        w = ",".join(f"{k}={v:g}" for k, v in (pr["weights"] or {}).items())
        print(f"ranking ({w}): " + ", ".join(f"{r['rank']}. {r['lang']} ({r['score']:.2f})" for r in ranked))
    print("\nfindings (use these facts, do not invent numbers):")
    for f in build_findings(run, "en"):
        print(f"- {f}")
    if charts:
        print(f"\ncharts: {charts['trend']} , {charts['share']}")
    print(f'next (if a report/PDF is wanted): {WIKI} report --run {run["run_id"]} --lang uk '
          '--question "<user question>" --conclusion "<2-4 sentences>"')
    from .report import draft_facts

    print("\n" + draft_facts(run, ui))
    print(answer_checklist(run))


def answer_checklist(run: dict) -> str:
    """Printed last on purpose: small models follow the most recent instructions best."""
    say = []
    for code in run["params"]["langs"]:
        m = run["langs"][code]
        if m["status"] == "missing":
            say.append(f"{code}=NO ARTICLE")
        else:
            say.append(f"{code}={m['direction']} ({pct(m['growth_adj'])} adjusted), confidence {m['confidence']}")
    items = []
    for qid, rivals in (run["topic"].get("alternatives") or {}).items():
        if rivals:
            label = run["topic"]["labels"].get(qid, qid)
            items.append(f"The name is ambiguous. First line of the answer: you analysed {label} [{qid}] "
                         f"({run['topic']['descriptions'].get(qid, '')[:60]}), not: " + "; ".join(rivals) + ".")
    items += [
        "Per language use exactly: " + "; ".join(say) + ".",
        "Explain the confidence with the ✗ checks / flags above in plain words.",
        "State 1-2 limitations: Wikipedia interest ≠ demand or willingness to pay; a language ≠ a country.",
        "Numbers only from this output. 'N/12 months above last year' is not 'N months of growth'.",
    ]
    ranked = [r["lang"] for r in run["ranking"] if r["rank"]]
    if len(ranked) > 1:
        items.append("Ranking order (keep it exactly): " + " > ".join(ranked) + ".")
    if not any(run["langs"][c].get("direction") == "growing" for c in run["params"]["langs"]):
        items.append("No language is growing here: do not describe any of them as growing.")
    return "\nANSWER CHECKLIST (reply in the user's language):\n" + "\n".join(
        f"{i}. {item}" for i, item in enumerate(items, 1))


def cmd_analyze(args, client: Client) -> int:
    from .charts import make_charts

    langs = parse_langs(args.langs)
    if not langs:
        raise ValueError("--langs is required, e.g. --langs pl,cs")
    qids = [q.upper() for q in args.qid]
    start, end = resolve_period(args.months, args.start, args.end)
    run = run_analysis(client, qids, langs, start, end, overrides=_parse_overrides(args.title),
                       weights=parse_weights(args.weights), ui_lang=args.lang)
    run_dir = save_run(run)
    charts = make_charts(run, run_dir, args.lang)
    if args.json:
        print(json.dumps({"run_dir": str(run_dir), "charts": charts, **run}, ensure_ascii=False, indent=1))
    else:
        print_summary(run, run_dir, charts, args.lang)
    print(f"(api: {client.requests_made} requests, {client.cache_hits} from cache)", file=sys.stderr)
    return 0


# --- report ------------------------------------------------------------------------------------------
def cmd_report(args, client: Client) -> int:
    from .report import build_report

    run, run_dir = load_run(args.run)
    conclusion = args.conclusion
    if args.conclusion_file:
        conclusion = Path(args.conclusion_file).read_text()
    result = build_report(run, run_dir, args.lang, conclusion or "", title=args.title, question=args.question,
                          out=Path(args.out) if args.out else None)
    print(f"PDF: {result['pdf']} ({result['pages']} page)")
    print(f"Markdown: {result['markdown']}")
    print(f"charts: {', '.join(result['charts'].values())}")
    problems = []
    if result["unverified_numbers"]:
        problems.append("these numbers match no metric of the run: " + ", ".join(result["unverified_numbers"]))
    if result["wording"]:
        problems.append(result["wording"])
    if problems:
        print("WARNING in --conclusion: " + " | ".join(problems) +
              ". Fix the conclusion and rerun the same report command.")
    else:
        print("conclusion check: OK (numbers match the analysis)")
    print("\nNow answer the user in chat as well (template in SKILL.md: short answer, data, confidence and why, "
          "limitations, next steps) and give the PDF path.")
    return 0


# --- runs / langs / cache ---------------------------------------------------------------------------
def cmd_runs(args, client: Client) -> int:
    if args.action == "show":
        if not args.run_id:
            raise ValueError("runs show needs a run id")
        run, run_dir = load_run(args.run_id)
        print_summary(run, run_dir, {})
        return 0
    rows = list_runs()
    if not rows:
        print("no runs yet")
    for r in rows[: args.limit]:
        print(f"- {r['run_id']} | {r['topic']} | {' '.join(r['qids'])} | langs {','.join(r['langs'])} | "
              f"{r['period']}" + (" | report" if r["has_report"] else ""))
    return 0


def cmd_langs(args, client: Client) -> int:
    qid = args.qid.upper()
    links = langs_with_article(client, qid)
    _, end = resolve_period(12, None, None)
    months = month_range(resolve_period(12, None, None)[0], end)
    pool = [c for c in BIG_EDITIONS if c in links]
    exclude = set(parse_langs(args.exclude))
    pool = [c for c in pool if c not in exclude][: args.top]
    views = parallel_map(lambda c: sum(article_series(client, c, links[c], months)), pool, 4)
    rows = sorted(zip(pool, views), key=lambda r: -r[1])
    print(f"## {qid}: article exists in {len(links)} Wikipedias; largest editions shown "
          f"(views of the main article, last 12 months {months[0]}..{months[-1]})")
    print("| lang | name | article | views 12m |")
    print("|---|---|---|---|")
    for code, v in rows:
        print(f"| {code} | {lang_name(code)} | {links[code]} | {_num(v)} |")
    missing = [c for c in BIG_EDITIONS[:25] if c not in links]
    if missing:
        print(f"no article in: {', '.join(missing)}")
    print(f"next: {WIKI} analyze --qid {qid} --langs {','.join(c for c, _ in rows[:6])}")
    return 0


def cmd_cache(args, client: Client) -> int:
    if args.action == "clear":
        client.cache.clear()
        print("cache cleared")
    else:
        print(json.dumps(client.cache.stats()))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="wiki.py", description="Wikipedia interest research (pageviews).")
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("resolve", help="topic name -> Wikidata QID + article title per language")
    r.add_argument("topics", nargs="+", help="topic name(s) in any language, or QIDs")
    r.add_argument("--langs", help="Wikipedia language codes, e.g. pl,cs,uk (default: --lang)")
    r.add_argument("--lang", default="en", help="language of the topic name you typed (default en)")
    r.add_argument("--title", action="append", help="manual article: LANG:Title (repeatable)")
    r.add_argument("--json", action="store_true")
    r.set_defaults(fn=cmd_resolve)

    a = sub.add_parser("analyze", help="fetch pageviews, compute growth/trust, save a run + charts")
    a.add_argument("--qid", action="append", required=True, help="Wikidata QID; repeat to build a topic basket")
    a.add_argument("--langs", required=True)
    a.add_argument("--months", type=int, default=24, help="period length ending at the last full month (default 24)")
    a.add_argument("--start", help="YYYY-MM (overrides --months)")
    a.add_argument("--end", help="YYYY-MM (default: last complete month)")
    a.add_argument("--title", action="append", help="manual article for the first QID: LANG:Title")
    a.add_argument("--weights", help="ranking weights, e.g. growth=2,size=1,intensity=1,trust=1")
    a.add_argument("--lang", default="uk", choices=["uk", "en"],
                   help="language of chart labels and of the DRAFT FACTS for your answer (default uk)")
    a.add_argument("--json", action="store_true")
    a.set_defaults(fn=cmd_analyze)

    rp = sub.add_parser("report", help="one-page PDF + Markdown from a saved run")
    rp.add_argument("--run", required=True, help="run id (or unique part of it) or run directory")
    rp.add_argument("--lang", default="uk", choices=["uk", "en"])
    rp.add_argument("--conclusion", help="your 2-4 sentence recommendation (<= 700 chars)")
    rp.add_argument("--conclusion-file", help="read the conclusion from a text file instead")
    rp.add_argument("--title")
    rp.add_argument("--question", help="the user's question, printed under the title")
    rp.add_argument("--out", help="output PDF path (default: inside the run directory)")
    rp.set_defaults(fn=cmd_report)

    ru = sub.add_parser("runs", help="list previous runs or show one (for follow-up questions)")
    ru.add_argument("action", nargs="?", default="list", choices=["list", "show"])
    ru.add_argument("run_id", nargs="?")
    ru.add_argument("--limit", type=int, default=15)
    ru.set_defaults(fn=cmd_runs)

    lg = sub.add_parser("langs", help="which large Wikipedias have the article + their 12-month views")
    lg.add_argument("--qid", required=True)
    lg.add_argument("--top", type=int, default=15)
    lg.add_argument("--exclude", help="language codes to skip (already analysed)")
    lg.set_defaults(fn=cmd_langs)

    c = sub.add_parser("cache", help="cache stats or clear")
    c.add_argument("action", nargs="?", default="stats", choices=["stats", "clear"])
    c.set_defaults(fn=cmd_cache)
    return p


def main(argv: list[str] | None = None) -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = build_parser().parse_args(argv)
    try:
        code = args.fn(args, Client())
    except (ValueError, LookupError, FileNotFoundError, ApiError, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        code = 2
    sys.exit(code)
