"""Orchestration: QIDs x languages -> fetched series -> metrics -> saved run (analysis.json)."""
from __future__ import annotations

import datetime as dt
import json
import re
import unicodedata
from pathlib import Path

import numpy as np

from . import __version__
from .analyze import analyze_series, rank_languages
from .api import Client, parallel_map
from .fetch import fetch_article, month_range, project_series
from .paths import reports_dir
from .resolve import resolve, search_candidates


def slugify(text: str, max_len: int = 40) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return text[:max_len] or "topic"


def _round(obj, digits: int = 4):
    """Round floats and convert numpy scalars to plain Python types (JSON-safe)."""
    if isinstance(obj, np.generic):
        obj = obj.item()
    if isinstance(obj, bool):
        return obj
    if isinstance(obj, float):
        return round(obj, digits)
    if isinstance(obj, dict):
        return {k: _round(v, digits) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_round(v, digits) for v in obj]
    return obj


def run_analysis(
    client: Client,
    qids: list[str],
    langs: list[str],
    start: str,
    end: str,
    overrides: dict[str, str] | None = None,
    weights: dict[str, float] | None = None,
    ui_lang: str = "en",
) -> dict:
    overrides = overrides or {}
    months = month_range(start, end)

    # 1) Wikidata: title of each topic article in each language (override applies to the first QID).
    resolutions = parallel_map(
        lambda q: resolve(client, q, langs, lang=ui_lang, overrides=overrides if q == qids[0] else None), qids, 3
    )

    # 2) Pageviews for every (article, language) pair + the whole edition per language.
    jobs = [(res, code) for res in resolutions for code in langs]
    articles = parallel_map(
        lambda job: fetch_article(
            client, job[0].qid, job[1], job[0].articles[job[1]].title, job[0].articles[job[1]].status, months,
            job[0].articles[job[1]].hints,
        ),
        jobs,
        3,
    )
    totals = dict(zip(langs, parallel_map(lambda code: project_series(client, code, months), langs, 3)))

    # 3) Per language: sum the topic basket, analyse.
    per_lang: dict[str, dict] = {}
    for code in langs:
        arts = [a for a in articles if a.lang == code]
        found = [a for a in arts if a.status in ("found", "override")]
        flags = []
        if found and len(found) < len(arts):
            flags.append("incomplete_basket")
        if any(a.disambiguation for a in found):
            flags.append("disambiguation")
        n = len(months)
        views = [sum(a.views[i] for a in found) for i in range(n)]
        main = [sum(a.main_views[i] for a in found) for i in range(n)]
        auto = [sum(a.automated[i] for a in found) for i in range(n)]
        share = [round(v * 1e6 / t, 3) if t else 0.0 for v, t in zip(views, totals[code])]
        entry = {
            "status": "ok" if found and len(found) == len(arts) else "partial" if found else "missing",
            "articles": [
                {
                    "qid": a.qid, "title": a.title, "status": a.status, "hints": a.hints,
                    "median_monthly": int(np.median(a.views)) if a.views else 0,
                    "redirects_used": a.redirects_used, "redirects_total": a.redirects_total,
                    "redirect_share": round(1 - sum(a.main_views) / sum(a.views), 3) if sum(a.views) else 0.0,
                }
                for a in arts
            ],
            "series": {"views": views, "share_per_million": share, "project_totals": totals[code]},
        }
        if found:
            entry.update(analyze_series(months, views, totals[code], auto, main, extra_flags=flags))
        per_lang[code] = entry

    alternatives = dict(zip(qids, parallel_map(lambda r: _label_rivals(client, r), resolutions, 3)))
    ranking = rank_languages(per_lang, weights or {})
    labels = {res.qid: res.label for res in resolutions}
    labels_all = {res.qid: res.labels for res in resolutions}
    now = dt.datetime.now()
    first = resolutions[0]
    run_id = f"{now:%Y%m%d-%H%M%S}-{slugify(first.labels.get('en') or first.label)}"
    run = {
        "run_id": run_id,
        "created_at": now.isoformat(timespec="seconds"),
        "tool_version": __version__,
        "params": {
            "qids": qids, "langs": langs, "start": start, "end": end, "months_n": len(months),
            "overrides": overrides, "weights": weights, "agent": "user", "access": "all-access",
        },
        "topic": {"labels": labels, "labels_all": labels_all, "alternatives": alternatives, "descriptions": {r.qid: r.description for r in resolutions}},
        "months": months,
        "langs": per_lang,
        "ranking": ranking,
        "api": {"requests": client.requests_made, "cache_hits": client.cache_hits},
    }
    return _round(run)


def _label_rivals(client: Client, res) -> list[str]:
    """Other popular concepts with the same English name (e.g. Mercury: planet / element / god)."""
    name = res.labels.get("en") or res.label
    try:
        cands = search_candidates(client, name, "en", [])
    except Exception:  # noqa: BLE001 - informative only
        return []
    rivals = [c for c in cands if c.qid != res.qid and c.exact and not c.disambiguation
              and c.sitelinks >= max(10, res.sitelinks * 0.5)]
    return [f"{c.qid} {c.label} — {c.description[:60]}" for c in rivals[:3]]


def save_run(run: dict) -> Path:
    """Save under a unique directory; never overwrite an earlier run (ids are per-second timestamps)."""
    base, run_id, i = reports_dir(), run["run_id"], 1
    while (base / run_id).exists():
        i += 1
        run_id = f"{run['run_id']}-{i}"
    run["run_id"] = run_id
    out = base / run_id
    out.mkdir(parents=True)
    (out / "analysis.json").write_text(json.dumps(run, ensure_ascii=False, indent=1))
    return out


def load_run(run_id: str) -> tuple[dict, Path]:
    base = reports_dir()
    path = Path(run_id)
    if not path.is_dir():
        path = base / run_id
    if not path.is_dir():
        matches = sorted(p for p in base.iterdir() if p.is_dir() and run_id in p.name)
        if not matches:
            raise FileNotFoundError(f"run {run_id!r} not found in {base}")
        path = matches[-1]
    return json.loads((path / "analysis.json").read_text()), path


def list_runs() -> list[dict]:
    base = reports_dir()
    rows = []
    for p in sorted(base.iterdir(), reverse=True):
        f = p / "analysis.json"
        if not f.exists():
            continue
        try:
            run = json.loads(f.read_text())
        except json.JSONDecodeError:
            continue
        pr = run["params"]
        rows.append({
            "run_id": run["run_id"],
            "topic": ", ".join(run["topic"]["labels"].values()),
            "qids": pr["qids"], "langs": pr["langs"], "period": f"{pr['start']}..{pr['end']}",
            "has_report": any(p.glob("*.pdf")),
        })
    return rows
