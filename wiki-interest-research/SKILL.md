---
name: wiki-interest-research
description: Research audience interest in topics across languages using Wikipedia pageview statistics. Compares a topic between Wikipedia language editions, checks whether growth is real (seasonality, news spikes, bots, Wikipedia-wide traffic decline), ranks language audiences, draws charts and builds a shareable one-page PDF report. Use when a founder or product team asks which topics, courses or languages/markets to invest in next, whether interest in a subject is growing in some language, how much a trend can be trusted, or wants Wikipedia pageviews / interest trends / localization research. Also triggers on Ukrainian requests - інтерес до теми, Вікіпедія, перегляди, мовні розділи, локалізація, які мови чи ринки, тренд, звіт PDF.
license: MIT
compatibility: Requires Python 3.10+ and internet access to wikimedia.org / wikidata.org. Dependencies install automatically into .venv on first run.
metadata:
  author: a.pashulia
  version: "1.0"
---

# Wikipedia interest research

All data work is done by the CLI; you choose commands and explain results.
Below, `WIKI` = `python3 SKILL_DIR/scripts/wiki.py`, where SKILL_DIR is the absolute path of the directory that contains this file.
- **Execute every command yourself with your shell/Bash tool** and read its output before the next step. Never just print a command and wait.
- Stay in the current working directory; **do not `cd` into SKILL_DIR** — call the script by its absolute path (results go to `./wiki-reports/<run-id>/`).
- The first call installs dependencies (~1 min, once). Every command prints a `next:` line with a ready command and an answer checklist.

## Rules (always)
1. **Numbers come only from the tool output.** Never compute, estimate or invent figures. Quote the table/findings.
2. **"ADJUSTED change" is the main signal**: change of the topic's share of all views of that Wikipedia (last 12 months vs previous 12). Raw views fall almost everywhere because Wikipedia traffic itself falls; mention raw views only as context.
3. Say "interest is growing/declining" only as the tool's `direction` says. If confidence is LOW, say the data is not sufficient to conclude.
4. Always state confidence and 1-2 main limitations (Wikipedia interest ≠ demand/willingness to pay; a language ≠ a country).
5. "NO ARTICLE" is a finding: the concept has no page in that language. Report it; do not silently swap in another article. A substitute article is allowed only with `--title lang:Title` and must be called a proxy in the answer.
6. Use the tool's words: `stable` is never "growth"; "8/12 months above last year" is not "8 months of growth".
7. If `resolve` said `ambiguous: YES`, the first line of the answer names the meaning you analysed and the alternatives (e.g. planet, not the chemical element).
8. Answer in the user's language, with the template below, **also when you produced a PDF**. Keep it short.

## Workflow
**1. Parse the request** → topic(s), language codes, period, criteria.
- Language names → codes: English en, Ukrainian uk, Polish pl, Czech cs, Slovak sk, German de, French fr, Spanish es, Italian it, Portuguese pt, Romanian ro, Hungarian hu, Turkish tr, Dutch nl, Swedish sv, Japanese ja, Korean ko, Chinese zh, Arabic ar, Hindi hi, Indonesian id, Vietnamese vi, Russian ru.
- Period: default 24 full months. "last two years" → `--months 24`; "5 years" → `--months 60`; explicit dates → `--start YYYY-MM --end YYYY-MM`.
- If the user gave no languages for a "which audiences/languages" question, run `WIKI langs --qid Q…` to see where the article exists, then pick 5-8 candidates.

**2. Resolve the topic** (topic text in any language; pass its language with `--lang`):
```
WIKI resolve "intermittent fasting" --langs pl,cs
WIKI resolve "астрономія" "сонячна система" --lang uk --langs uk
```
- If `ambiguous: YES`, pick the candidate whose description matches the user's meaning (e.g. planet vs chemical element) and use its QID; say which one you picked (rule 7). If the meaning is unclear and the choice changes the answer, ask the user.
- Broad subject (a course, a field like "astronomy"): one article is a weak proxy. Resolve 2-4 core articles (e.g. astronomy + Solar System + black hole) and pass all QIDs to analyze as a basket.

**3. Analyze** (repeat `--qid` for a basket):
```
WIKI analyze --qid Q1666254 --langs pl,cs --months 24
```
Pass `--lang uk` (Ukrainian user) or `--lang en`. Read: the table, `confidence checks`, `flags`, `ranking`, and **`DRAFT FACTS`** — ready sentences in the user's language. Charts are saved in the run folder.
Optional criteria for ranking: `--weights growth=2,size=1,intensity=1,trust=1` (size = monthly views, intensity = views per 1M views of that Wikipedia, trust = confidence).

**4. Answer in chat** using the template below. Build the facts from `DRAFT FACTS` (copy or shorten; do not rephrase numbers, confidence levels or directions), then add your recommendation.

**5. PDF report** — when the user asks for a report/PDF/something to share (or when the request says "звіт"/"report"):
```
WIKI report --run <run-id> --lang uk --question "<user question>" --conclusion "<2-4 sentences>"
```
- `--conclusion`: your recommendation, max 700 chars, only numbers that appear in the findings/table.
- If the output says `WARNING in --conclusion`, fix what it names (invented number or wrong wording) and rerun the same command.
- Give the user the PDF path. `--lang en` for an English report.

## Answer template
```
**Коротко:** <1 sentence: direction + confidence per language / best audience>
**Дані:** <2-4 bullets: adjusted change, months above last year, median views/month, notable spikes or seasonality>
**Наскільки довіряти:** <confidence level + the failed checks/flags in plain words>
**Обмеження:** <1-2 bullets>
**Що далі:** <1-2 concrete next checks, e.g. other data sources, more languages, topic basket>
```

## Reading the output
- `direction`: growing (adjusted ≥ +10%), declining (≤ -10%), stable (between).
- `confidence`: share of passed checks — ✓/✗ consistency (months with share above last year), robust_to_spikes, raw_agrees, significant_trend; then capped by flags.
- Flags: `low_volume` (<100 views/mo → confidence low), `modest_volume` (<1000 → max medium), `news_spikes` (one-off peaks, maybe news), `seasonal_peaks` (e.g. school year; compare year over year), `high_automated` (>20% bot traffic), `article_new_or_renamed`, `incomplete_basket` (some basket articles missing in that language), `short_period` (<24 months).
- `ranking` is relative within the chosen languages: rank 1 is "best of this set", not "good" in absolute terms.
- Details and thresholds: [references/methodology.md](references/methodology.md). All flags: [references/cli-reference.md](references/cli-reference.md).

## Follow-up questions
The HTTP cache makes reruns fast; always rerun `analyze` with the changed parameters instead of reasoning from old numbers.
- "add Slovak" → same `analyze` command with `--langs pl,cs,sk`.
- "over 5 years" → `--months 60` (long-term change and yearly rate appear in findings).
- "growth matters more than size" → `--weights growth=3,size=1,intensity=1,trust=1`.
- "what did we look at before?" → `WIKI runs list`; `WIKI runs show <run-id>` reprints a saved summary.

## Errors
- `ERROR: No Wikidata item found` → try the English name or another wording.
- `project … not found` → wrong language code.
- Network errors are retried automatically; if one persists, tell the user Wikimedia is unreachable.
