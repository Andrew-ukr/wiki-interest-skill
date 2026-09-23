"""Shared helpers: synthetic series and a fake Wikimedia API (tests run offline)."""
from __future__ import annotations

import json
import math
import sys
import urllib.parse
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from wikiinterest.api import Client  # noqa: E402
from wikiinterest.cache import Cache  # noqa: E402
from wikiinterest.fetch import month_range  # noqa: E402

MONTHS_24 = month_range("2024-09", "2026-08")


def seasonal(n: int, base: float, growth_per_year: float = 0.0, amplitude: float = 0.0, start_month: int = 9,
             noise: float = 0.0, seed: int = 1) -> list[int]:
    """base * (1+g)^(t/12) * (1 + amplitude*cos(season)) with deterministic pseudo-noise."""
    out = []
    state = seed
    for t in range(n):
        month = (start_month - 1 + t) % 12
        state = (state * 1103515245 + 12345) % (2**31)
        eps = ((state / 2**31) - 0.5) * 2 * noise
        value = base * (1 + growth_per_year) ** (t / 12) * (1 + amplitude * math.cos(2 * math.pi * (month - 8) / 12))
        out.append(max(0, int(round(value * (1 + eps)))))
    return out


class FakeClient(Client):
    """Client whose HTTP layer is a routing function; everything else is the real code."""

    def __init__(self, tmp_path: Path, router):
        super().__init__(cache=Cache(tmp_path / "cache.sqlite"), offline=False)
        self.router = router
        self.urls: list[str] = []

    def get(self, url: str, ttl, attempts: int = 5):
        self.urls.append(url)
        self.requests_made += 1
        status, payload = self.router(urllib.parse.unquote(url))
        return status, json.dumps(payload)


def pv_items(months: list[str], values: list[int], skip_zero: bool = True) -> dict:
    items = [{"timestamp": m.replace("-", "") + "0100", "views": v} for m, v in zip(months, values)
             if not (skip_zero and v == 0)]
    return {"items": items}


@pytest.fixture
def tmp_out(tmp_path, monkeypatch):
    monkeypatch.setenv("WIKI_INTEREST_OUT", str(tmp_path / "reports"))
    monkeypatch.setenv("WIKI_INTEREST_CACHE", str(tmp_path / "cache"))
    return tmp_path
