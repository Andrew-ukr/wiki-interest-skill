"""Download monthly pageview series for articles (incl. redirects) and whole projects.

API quirks handled here (see references/api-notes.md):
* months with zero views are simply absent from the response -> filled with 0;
* a series with no views at all returns HTTP 404 -> treated as all zeros;
* views of redirects are counted separately -> summed into the target article
  (this also glues together articles that were renamed during the period).
"""
from __future__ import annotations

import calendar
import datetime as dt
import re
import urllib.parse
from dataclasses import dataclass, field

from .api import (
    PAGEVIEWS_BASE,
    TTL_CLOSED_MONTHS,
    TTL_RECENT,
    ApiError,
    Client,
    parallel_map,
)

FIRST_MONTH = "2015-07"  # pageviews API starts on 2015-07-01
MAX_REDIRECTS = 25
_MONTH_RE = re.compile(r"^(\d{4})-(\d{2})$")


# --- month helpers ---------------------------------------------------------------------
def parse_month(value: str) -> tuple[int, int]:
    m = _MONTH_RE.match(value.strip())
    if not m:
        raise ValueError(f"month must look like YYYY-MM, got {value!r}")
    year, month = int(m.group(1)), int(m.group(2))
    if not 1 <= month <= 12:
        raise ValueError(f"invalid month {value!r}")
    return year, month


def fmt_month(year: int, month: int) -> str:
    return f"{year:04d}-{month:02d}"


def add_months(value: str, delta: int) -> str:
    year, month = parse_month(value)
    idx = year * 12 + (month - 1) + delta
    return fmt_month(idx // 12, idx % 12 + 1)


def month_range(start: str, end: str) -> list[str]:
    out = []
    cur = start
    while cur <= end:
        out.append(cur)
        cur = add_months(cur, 1)
    return out


def last_complete_month(today: dt.date | None = None) -> str:
    today = today or dt.date.today()
    # Monthly data for month M is published during the first days of M+1; be safe.
    return add_months(fmt_month(today.year, today.month), -1 if today.day > 3 else -2)


def resolve_period(months: int | None, start: str | None, end: str | None, today: dt.date | None = None) -> tuple[str, str]:
    end = end or last_complete_month(today)
    parse_month(end)
    if start:
        parse_month(start)
    else:
        start = add_months(end, -((months or 24) - 1))
    if start < FIRST_MONTH:
        start = FIRST_MONTH
    if start > end:
        raise ValueError(f"start {start} is after end {end}")
    limit = last_complete_month(today)
    if end > limit:
        raise ValueError(f"end {end} is not a complete month yet (latest complete: {limit})")
    return start, end


def _api_range(start: str, end: str) -> tuple[str, str]:
    y1, m1 = parse_month(start)
    y2, m2 = parse_month(end)
    last_day = calendar.monthrange(y2, m2)[1]
    return f"{y1:04d}{m1:02d}01", f"{y2:04d}{m2:02d}{last_day:02d}"


def _ttl_for(end: str) -> float:
    return TTL_RECENT if end >= add_months(last_complete_month(), -1) else TTL_CLOSED_MONTHS


def _items_to_series(items: list[dict], months: list[str]) -> list[int]:
    by_month = {}
    for item in items:
        ts = item.get("timestamp", "")
        by_month[f"{ts[:4]}-{ts[4:6]}"] = by_month.get(f"{ts[:4]}-{ts[4:6]}", 0) + int(item.get("views", 0))
    return [by_month.get(m, 0) for m in months]


def project_name(lang: str) -> str:
    return f"{lang}.wikipedia"


def encode_title(title: str) -> str:
    return urllib.parse.quote(title.replace(" ", "_"), safe="")


# --- series ------------------------------------------------------------------------------
def article_series(client: Client, lang: str, title: str, months: list[str], agent: str = "user") -> list[int]:
    a, b = _api_range(months[0], months[-1])
    url = f"{PAGEVIEWS_BASE}/per-article/{project_name(lang)}/all-access/{agent}/{encode_title(title)}/monthly/{a}/{b}"
    status, data = client.get_json(url, _ttl_for(months[-1]))
    if status == 404:
        return [0] * len(months)
    if status != 200:
        raise ApiError(f"HTTP {status} for {lang}:{title}: {str(data)[:200]}")
    return _items_to_series(data.get("items", []), months)


def project_series(client: Client, lang: str, months: list[str], agent: str = "user") -> list[int]:
    a, b = _api_range(months[0], months[-1])
    url = f"{PAGEVIEWS_BASE}/aggregate/{project_name(lang)}/all-access/{agent}/monthly/{a}00/{b}00"
    status, data = client.get_json(url, _ttl_for(months[-1]))
    if status == 404:
        raise ApiError(f"project {project_name(lang)} not found in pageviews API (check the language code)")
    if status != 200:
        raise ApiError(f"HTTP {status} for project {lang}: {str(data)[:200]}")
    return _items_to_series(data.get("items", []), months)


@dataclass
class PageInfo:
    exists: bool
    title: str
    disambiguation: bool = False
    redirects: list[str] = field(default_factory=list)
    redirected_from: str | None = None


def page_info(client: Client, lang: str, title: str) -> PageInfo:
    data = client.wiki(
        lang,
        {
            "action": "query",
            "titles": title,
            "redirects": "1",
            "prop": "redirects|pageprops",
            "rdlimit": "max",
            "rdnamespace": "0",
            "ppprop": "disambiguation",
        },
    )
    query = data.get("query", {})
    pages = query.get("pages", [])
    if not pages:
        return PageInfo(False, title)
    page = pages[0]
    redirected_from = None
    for r in query.get("redirects", []):
        redirected_from = r.get("from")
    if page.get("missing") or page.get("invalid"):
        return PageInfo(False, page.get("title", title))
    return PageInfo(
        exists=True,
        title=page["title"],
        disambiguation="disambiguation" in page.get("pageprops", {}),
        redirects=[r["title"] for r in page.get("redirects", [])],
        redirected_from=redirected_from,
    )


@dataclass
class ArticleData:
    qid: str
    lang: str
    title: str | None
    status: str  # found | override | missing | not_found
    views: list[int]  # user views incl. redirects
    main_views: list[int]
    automated: list[int]
    redirects_total: int = 0
    redirects_used: int = 0
    disambiguation: bool = False
    hints: list[str] = field(default_factory=list)


def fetch_article(
    client: Client, qid: str, lang: str, title: str | None, status: str, months: list[str], hints: list[str] | None = None
) -> ArticleData:
    zeros = [0] * len(months)
    if not title:
        return ArticleData(qid, lang, None, "missing", zeros, zeros, zeros, hints=hints or [])
    info = page_info(client, lang, title)
    if not info.exists:
        return ArticleData(qid, lang, title, "not_found", zeros, zeros, zeros, hints=hints or [])
    redirects = info.redirects[:MAX_REDIRECTS]
    titles = [info.title, *redirects]
    user_series = parallel_map(lambda t: article_series(client, lang, t, months), titles)
    automated = article_series(client, lang, info.title, months, agent="automated")
    total = [sum(col) for col in zip(*user_series)]
    return ArticleData(
        qid=qid,
        lang=lang,
        title=info.title,
        status=status,
        views=total,
        main_views=user_series[0],
        automated=automated,
        redirects_total=len(info.redirects),
        redirects_used=len(redirects),
        disambiguation=info.disambiguation,
        hints=hints or [],
    )
