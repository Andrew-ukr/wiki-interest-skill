"""Topic -> Wikidata item -> article title in every requested language edition.

Wikidata is the language-independent anchor: one item (QID) links to the article
about the same concept in each Wikipedia, so "intermittent fasting" is compared
with "Přerušovaný půst" (cs) and "Інтервальне голодування" (uk) automatically.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

from .api import Client, parallel_map

# Sitelink keys ending in "wiki" that are NOT Wikipedias.
_NON_WIKIPEDIA = {
    "commonswiki", "specieswiki", "metawiki", "mediawikiwiki", "wikidatawiki", "sourceswiki",
    "outreachwiki", "wikimaniawiki", "foundationwiki", "incubatorwiki", "wikifunctionswiki",
    "testwiki", "test2wiki", "testwikidatawiki", "nostalgiawiki", "tenwiki",
}
_SPECIAL_SITE_TO_LANG = {"be_x_oldwiki": "be-tarask"}
_DISAMBIG_RE = re.compile(
    r"disambiguation|сторінка значень|страница значений|ujednoznacznia|rozcestník|Begriffsklärung|homonymie",
    re.IGNORECASE,
)
_QID_RE = re.compile(r"^[Qq]\d+$")


def site_to_lang(site: str) -> str | None:
    if site in _NON_WIKIPEDIA or not site.endswith("wiki"):
        return None
    if site in _SPECIAL_SITE_TO_LANG:
        return _SPECIAL_SITE_TO_LANG[site]
    return site[: -len("wiki")].replace("_", "-")


def lang_to_site(lang: str) -> str:
    for site, code in _SPECIAL_SITE_TO_LANG.items():
        if code == lang:
            return site
    return lang.replace("-", "_") + "wiki"


def parse_langs(value: str | list[str] | None) -> list[str]:
    if not value:
        return []
    items = value if isinstance(value, list) else [value]
    out: list[str] = []
    for item in items:
        for code in re.split(r"[,\s]+", item.strip()):
            code = code.strip().lower().removesuffix(".wikipedia")
            if code and code not in out:
                out.append(code)
    return out


@dataclass
class Candidate:
    qid: str
    label: str
    description: str
    sitelinks: int
    exact: bool
    disambiguation: bool


@dataclass
class ArticleRef:
    lang: str
    title: str | None
    status: str  # found | missing | override
    hints: list[str] = field(default_factory=list)


@dataclass
class Resolution:
    query: str
    qid: str
    label: str
    description: str
    sitelinks: int
    ambiguous: bool
    candidates: list[Candidate]
    articles: dict[str, ArticleRef]
    note: str = ""
    labels: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


def _entities(client: Client, qids: list[str], langs: list[str]) -> dict:
    ui_langs = "|".join(sorted({"en", *langs}))
    data = client.wikidata(
        {
            "action": "wbgetentities",
            "ids": "|".join(qids),
            "props": "sitelinks|labels|descriptions|aliases",
            "languages": ui_langs,
            "languagefallback": "1",
        }
    )
    return data.get("entities", {})


def _pick_text(mapping: dict, langs: list[str]) -> str:
    for lang in langs:
        if lang in mapping:
            value = mapping[lang]
            return value.get("value", "") if isinstance(value, dict) else value
    if mapping:
        value = next(iter(mapping.values()))
        return value.get("value", "") if isinstance(value, dict) else value
    return ""


def _wikipedia_sitelinks(entity: dict) -> dict[str, str]:
    out = {}
    for site, link in entity.get("sitelinks", {}).items():
        lang = site_to_lang(site)
        if lang:
            out[lang] = link["title"]
    return out


def search_candidates(client: Client, query: str, lang: str, langs: list[str], limit: int = 7) -> list[Candidate]:
    results: list[dict] = []
    for search_lang in dict.fromkeys([lang, "en"]):
        data = client.wikidata(
            {
                "action": "wbsearchentities",
                "search": query,
                "language": search_lang,
                "uselang": search_lang,
                "type": "item",
                "limit": str(limit),
            }
        )
        results = data.get("search", [])
        if results:
            break
    if not results:
        return []
    entities = _entities(client, [r["id"] for r in results], [lang, *langs])
    q = query.casefold().strip()
    out = []
    for r in results:
        ent = entities.get(r["id"], {})
        labels = {v.get("value", "").casefold() for v in ent.get("labels", {}).values()}
        aliases = {a.get("value", "").casefold() for al in ent.get("aliases", {}).values() for a in al}
        match_text = (r.get("match") or {}).get("text", "").casefold()
        desc = r.get("description") or _pick_text(ent.get("descriptions", {}), [lang, "en"])
        out.append(
            Candidate(
                qid=r["id"],
                label=r.get("label") or _pick_text(ent.get("labels", {}), [lang, "en"]),
                description=desc or "",
                sitelinks=len(_wikipedia_sitelinks(ent)),
                exact=q in labels or q in aliases or q == match_text,
                disambiguation=bool(_DISAMBIG_RE.search(desc or "")),
            )
        )
    return out


def choose(candidates: list[Candidate]) -> tuple[Candidate | None, bool]:
    """Pick the most likely concept: exact label match first, then popularity (sitelinks).

    Returns (choice, ambiguous). Ambiguous when several strong exact matches exist
    (e.g. "Mercury": planet, element, car brand) or when nothing matched exactly.
    """
    usable = [c for c in candidates if not c.disambiguation]
    if not usable:
        return None, True
    exact = [c for c in usable if c.exact]
    pool = exact or usable
    ranked = sorted(pool, key=lambda c: c.sitelinks, reverse=True)
    best = ranked[0]
    strong_rivals = [c for c in ranked[1:] if c.sitelinks >= max(10, best.sitelinks * 0.25)]
    ambiguous = not exact or bool(strong_rivals)
    return best, ambiguous


def _stems(text: str) -> set[str]:
    return {w[:4].casefold() for w in re.findall(r"\w{4,}", text)}


def _missing_hints(client: Client, lang: str, labels: list[str]) -> list[str]:
    """Search the target Wikipedia for the concept's labels; keep only hits sharing a word stem.

    Full-text search always returns *something*; unrelated hits would tempt an agent to use a wrong
    proxy article, so a hit is kept only if its title shares a 4-letter word stem with the searched label.
    """
    hints: list[str] = []
    for text in dict.fromkeys(t for t in labels if t):
        try:
            data = client.wiki(
                lang, {"action": "query", "list": "search", "srsearch": text, "srlimit": "10", "srnamespace": "0"}
            )
        except Exception:  # noqa: BLE001 - hints are best effort
            continue
        for hit in data.get("query", {}).get("search", []):
            if hit["title"] not in hints and _stems(hit["title"]) & _stems(text):
                hints.append(hit["title"])
        if hints:
            break
    return hints[:3]


def resolve(
    client: Client,
    query: str,
    langs: list[str],
    lang: str = "en",
    overrides: dict[str, str] | None = None,
) -> Resolution:
    overrides = overrides or {}
    candidates: list[Candidate] = []
    ambiguous = False
    note = ""
    if _QID_RE.match(query.strip()):
        qid = query.strip().upper()
    else:
        candidates = search_candidates(client, query, lang, langs)
        best, ambiguous = choose(candidates)
        if best is None:
            raise LookupError(
                f"No Wikidata item found for {query!r}. Try the English name, a different wording, or pass a QID."
            )
        qid = best.qid
        if ambiguous:
            note = "Several concepts match; verify the chosen QID or rerun with the right one from candidates."

    ent = _entities(client, [qid], [lang, *langs]).get(qid)
    if not ent or "missing" in ent:
        raise LookupError(f"Wikidata item {qid} does not exist.")
    links = _wikipedia_sitelinks(ent)
    label = _pick_text(ent.get("labels", {}), [lang, "en"])
    description = _pick_text(ent.get("descriptions", {}), [lang, "en"])

    articles: dict[str, ArticleRef] = {}
    missing: list[str] = []
    for code in langs:
        if code in overrides:
            articles[code] = ArticleRef(code, overrides[code], "override")
        elif code in links:
            articles[code] = ArticleRef(code, links[code], "found")
        else:
            articles[code] = ArticleRef(code, None, "missing")
            missing.append(code)

    if missing:
        labels_by_lang = ent.get("labels", {})
        en_label = labels_by_lang.get("en", {}).get("value", "")

        def hints_for(code: str) -> tuple[str, list[str]]:
            local = labels_by_lang.get(code, {}).get("value", "")
            aliases = [a["value"] for a in ent.get("aliases", {}).get(code, [])][:2]
            return code, _missing_hints(client, code, [local, *aliases, en_label])

        for code, hints in parallel_map(hints_for, missing):
            articles[code].hints = hints

    # Keep only the top candidates in the output (cheap-model friendly).
    candidates = sorted(candidates, key=lambda c: (not c.exact, -c.sitelinks))[:5]
    return Resolution(
        query=query,
        qid=qid,
        label=label,
        description=description,
        sitelinks=len(links),
        ambiguous=ambiguous,
        candidates=candidates,
        articles=articles,
        note=note,
        labels={k: v.get("value", "") for k, v in ent.get("labels", {}).items()},
    )


def langs_with_article(client: Client, qid: str) -> dict[str, str]:
    ent = _entities(client, [qid], []).get(qid, {})
    return _wikipedia_sitelinks(ent)
