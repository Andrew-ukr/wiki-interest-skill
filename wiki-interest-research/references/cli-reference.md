# CLI reference

`python3 SKILL_DIR/scripts/wiki.py <command> [options]` (`WIKI` below). Exit code 2 + `ERROR: …` on bad input.

## resolve — topic → Wikidata item → article per language
```
WIKI resolve TOPIC [TOPIC ...] --langs pl,cs [--lang uk] [--title pl:Title] [--json]
```
- `TOPIC`: name in any language (set `--lang` to that language), or a QID like `Q333`.
- Output: chosen QID, label, description, number of Wikipedias with an article, `ambiguous`, article per
  language or `NO ARTICLE` + similar pages found by search in that Wikipedia, candidates when ambiguous.

## analyze — fetch, compute, save a run + charts
```
WIKI analyze --qid Q1 [--qid Q2 ...] --langs pl,cs,uk [--months 24 | --start 2024-09 [--end 2026-08]]
             [--title pl:Title] [--weights growth=2,size=1,intensity=1,trust=1] [--lang uk|en] [--json]
```
- Several `--qid` = topic basket (views summed per language).
- `--months N`: period of N full months ending at the last complete month (default 24).
- `--title lang:Title`: use this article for the first QID in that language (proxy / manual fix).
- `--lang`: language of chart labels (default uk). Summary text is always English.
- Saves `wiki-reports/<run-id>/analysis.json`, `trend.png`, `share.png`.
- `--json` prints the full run (large; prefer the default summary).

## report — one-page PDF + Markdown
```
WIKI report --run RUN [--lang uk|en] --conclusion "..." [--question "..."] [--title "..."] [--out file.pdf]
            [--conclusion-file notes.txt]
```
- `RUN`: run id, a unique part of it (e.g. `astronomy`, newest match wins), or a run directory.
- `--conclusion` ≤ 700 characters. Numbers in it are checked against the run.
- Writes `report-<lang>.pdf` and `report-<lang>.md` into the run folder (or `--out`).

## runs — previous analyses
```
WIKI runs list [--limit 15]
WIKI runs show RUN
```

## langs — where does the article exist (audience discovery)
```
WIKI langs --qid Q1860 [--top 15] [--exclude pl,de]
```
Lists the largest Wikipedias that have the article with its views over the last 12 months.

## cache
```
WIKI cache stats | clear
```

## Environment variables
| variable | default | purpose |
|---|---|---|
| `WIKI_INTEREST_OUT` | `./wiki-reports` | where runs and reports are written |
| `WIKI_INTEREST_CACHE` | `~/.cache/wiki-interest-research` | SQLite HTTP cache |
| `WIKI_INTEREST_VENV` | `SKILL_DIR/.venv` | virtualenv location |
| `WIKI_INTEREST_CONTACT` | project URL | contact info in the User-Agent (Wikimedia policy) |
| `WIKI_INTEREST_OFFLINE` | unset | `1` = use only cached responses |
