"""HTTP access to Wikimedia APIs: User-Agent, retries, caching, bounded parallelism."""
from __future__ import annotations

import json
import os
import random
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Iterable, TypeVar

from . import __version__
from .cache import Cache

PAGEVIEWS_BASE = "https://wikimedia.org/api/rest_v1/metrics/pageviews"
WIKIDATA_API = "https://www.wikidata.org/w/api.php"

DAY = 24 * 3600
TTL_METADATA = 7 * DAY  # Wikidata entities, redirects, search results
TTL_CLOSED_MONTHS = 60 * DAY  # pageviews for already finished months
TTL_RECENT = 1 * DAY  # anything touching the current or previous month

MAX_WORKERS = 6
_RETRY_STATUSES = {429, 500, 502, 503, 504}


class ApiError(RuntimeError):
    pass


def user_agent() -> str:
    # Wikimedia policy requires an identifying User-Agent with contact information.
    contact = os.environ.get("WIKI_INTEREST_CONTACT", "https://agentskills.io; skill wiki-interest-research")
    return f"wiki-interest-research/{__version__} ({contact}) python-urllib"


def _ssl_context() -> ssl.SSLContext:
    # Some Python builds (python.org / Homebrew on macOS) ship without a usable CA store.
    if os.environ.get("SSL_CERT_FILE"):
        return ssl.create_default_context()
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


_SSL = _ssl_context()


def _http_get(url: str, timeout: float = 30.0) -> tuple[int, str]:
    """Single GET. Returns (status, body); network failures raise ApiError."""
    req = urllib.request.Request(url, headers={"User-Agent": user_agent(), "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=_SSL) as resp:
            return resp.status, resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
        retry_after = exc.headers.get("Retry-After") if exc.headers else None
        if exc.code in _RETRY_STATUSES and retry_after:
            body = json.dumps({"_retry_after": retry_after, "body": body})
        return exc.code, body
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise ApiError(f"network error for {url}: {exc}") from exc


class Client:
    def __init__(self, cache: Cache | None = None, offline: bool | None = None):
        self.cache = cache or Cache()
        self.offline = offline if offline is not None else os.environ.get("WIKI_INTEREST_OFFLINE") == "1"
        self.requests_made = 0
        self.cache_hits = 0

    def get(self, url: str, ttl: float | None, attempts: int = 5) -> tuple[int, str]:
        cached = self.cache.get(url)
        if cached is not None:
            self.cache_hits += 1
            return cached
        if self.offline:
            raise ApiError(f"offline mode and no cached response for {url}")
        delay = 1.0
        for attempt in range(1, attempts + 1):
            try:
                status, body = _http_get(url)
            except ApiError:
                if attempt == attempts:
                    raise
                time.sleep(delay)
                delay *= 2
                continue
            self.requests_made += 1
            if status in _RETRY_STATUSES and attempt < attempts:
                wait = delay
                try:
                    wait = max(wait, float(json.loads(body).get("_retry_after", 0)))
                except (ValueError, AttributeError):
                    pass
                time.sleep(wait + random.random() * 0.3)
                delay *= 2
                continue
            if status == 200 or status == 404:
                # 404 is a valid answer for pageviews ("no views recorded") -> cache it too.
                self.cache.put(url, status, body, ttl)
            return status, body
        raise ApiError(f"giving up on {url}")

    def get_json(self, url: str, ttl: float | None) -> tuple[int, dict]:
        status, body = self.get(url, ttl)
        try:
            data = json.loads(body) if body else {}
        except json.JSONDecodeError:
            data = {"_raw": body[:500]}
        return status, data

    # --- MediaWiki / Wikidata helpers -------------------------------------------------
    def mediawiki(self, api_url: str, params: dict, ttl: float = TTL_METADATA) -> dict:
        query = {"format": "json", "formatversion": "2", **params}
        url = api_url + "?" + urllib.parse.urlencode(query)
        status, data = self.get_json(url, ttl)
        if status != 200:
            raise ApiError(f"HTTP {status} from {api_url}: {str(data)[:200]}")
        if "error" in data:
            raise ApiError(f"API error from {api_url}: {data['error']}")
        return data

    def wikidata(self, params: dict) -> dict:
        return self.mediawiki(WIKIDATA_API, params)

    def wiki(self, lang: str, params: dict) -> dict:
        return self.mediawiki(f"https://{lang}.wikipedia.org/w/api.php", params)


T = TypeVar("T")
R = TypeVar("R")


def parallel_map(fn: Callable[[T], R], items: Iterable[T], workers: int = MAX_WORKERS) -> list[R]:
    items = list(items)
    if len(items) <= 1:
        return [fn(x) for x in items]
    with ThreadPoolExecutor(max_workers=min(workers, len(items))) as pool:
        return list(pool.map(fn, items))
