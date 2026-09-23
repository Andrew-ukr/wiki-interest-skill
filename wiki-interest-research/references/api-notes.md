# Wikimedia API notes

Docs: https://doc.wikimedia.org/generated-data-platform/aqs/analytics-api/reference/page-views.html

## Endpoints used
- Per article: `https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/{lang}.wikipedia/all-access/{agent}/{title}/monthly/{YYYYMMDD}/{YYYYMMDD}`
- Whole edition: `https://wikimedia.org/api/rest_v1/metrics/pageviews/aggregate/{lang}.wikipedia/all-access/{agent}/monthly/{YYYYMMDD00}/{YYYYMMDD00}`
- Wikidata: `wbsearchentities` (search by label in a language), `wbgetentities` (sitelinks, labels, aliases).
- MediaWiki `action=query&prop=redirects|pageprops&redirects=1` (canonical title, redirects, disambiguation).
- MediaWiki `list=search` (hints for a language without the article).

## Quirks handled in code
- Data starts on 2015-07-01; the current month is not returned in monthly granularity.
- Months with zero views are **absent**; a series with no views returns **HTTP 404** (not an error).
- Titles use underscores and must be URL-encoded including `/`.
- `agent`: `user` (humans; default), `automated` (bots detected by heuristics), `spider` (self-declared crawlers).
- Wikimedia requires a descriptive `User-Agent` with contact info; excessive clients get HTTP 429.
  The client retries 429/5xx with exponential backoff and uses at most 6 parallel requests.
- Sitelink keys: `plwiki` → `pl`, `zh_yuewiki` → `zh-yue`, `be_x_oldwiki` → `be-tarask`; non-Wikipedia
  sites (`commonswiki`, `specieswiki`, …) are ignored.

## Caching
SQLite at `~/.cache/wiki-interest-research/http-cache.sqlite`. Metadata (Wikidata, redirects, search):
7 days. Pageviews: 60 days for closed periods, 1 day if the period ends in the last two months.
A follow-up question that adds one language downloads only that language.

## Request budget
Per (article × language): 1 metadata + 1 user series + 1 automated series + up to 25 redirect series;
per language: 1 edition series. Typical 6-language run: ~40-100 requests, 5-10 s; reruns: 0 requests.
