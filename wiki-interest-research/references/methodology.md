# Methodology

All logic lives in `wikiinterest/analyze.py`; thresholds are constants at the top of that file.

## Data
- Source: Wikimedia Pageviews API, `agent=user` (known spiders/automated traffic excluded), `all-access`
  (desktop + mobile web + app), monthly granularity, **complete months only**.
- Article per language: taken from the Wikidata item's sitelinks, so the same concept is compared across
  languages even if titles differ.
- Views of redirects to the article are added (up to 25 redirects). This also merges history of renamed
  articles, because the old title becomes a redirect.
- Months missing from the API response are zeros; an HTTP 404 series means no views at all.
- Basket: several QIDs are summed per language. If some basket articles are missing in a language the
  language gets `incomplete_basket` (confidence max medium) — comparisons are then biased.

## Why "adjusted change" is the primary metric
Wikipedia's own traffic changes a lot: in 2025-2026 many editions lost 7-25% of human views per year
(readers get answers from search snippets and AI assistants). Raw views of almost any topic therefore
fall. The adjusted metric uses the topic's **share** of all human views of the same edition:

`share = topic views / edition views × 1,000,000` (views per million)

`adjusted change = mean share(last 12 months) / mean share(previous 12 months) − 1` (computed on sums).

Comparing 12 vs 12 months keeps every calendar month on both sides, so seasonality (school year,
New Year resolutions, summer) cancels out.

## Metrics
| field | meaning |
|---|---|
| `median_monthly` | median human views per month (size of the audience on Wikipedia) |
| `share_per_million_median` | intensity: views per 1M views of the edition (comparable across languages of different size) |
| `growth_adj` | adjusted change (primary) |
| `growth_raw` | raw views change, last 12 vs previous 12 |
| `project_growth` | change of the whole edition's views |
| `yoy_up` | in how many of the last 12 months the share was higher than in the same month a year earlier |
| `growth_adj_ex_spikes` | adjusted change after dropping the 2 largest months of the 24-month window |
| `trend_adj_per_year` | Theil–Sen slope of log(share) after removing the average calendar-month effect, as %/year |
| `mk_p` | Mann–Kendall p-value of the same deseasonalised series (monotonic trend test) |
| `long_change_adj`, `cagr_adj` | for ≥ 36 months: first 12 vs last 12 months, and its yearly rate |
| `spikes` | months with robust z-score > 3.5 and ≥ 2× median; `seasonal` if the same calendar month is also ≥ 1.5× median in another year |
| `automated_share` | automated / (automated + user) views of the main article |

## Direction
`growing` if adjusted change ≥ +10%, `declining` if ≤ −10%, otherwise `stable` (decided on the rounded
percentage the reader sees). With < 24 months the halves of the period are compared (`short_period`).

## Confidence (in the direction label)
Checks for growing / declining:
1. **consistency** — ≥ 9 of 12 months move in the same direction year over year;
2. **robust_to_spikes** — without the 2 largest months the change keeps its sign and is ≥ 5% in size;
3. **raw_agrees** — raw views do not contradict the direction (tolerance 5 pp);
4. **significant_trend** — Mann–Kendall p < 0.05 and the Theil–Sen slope has the same sign.

Checks for stable: 3–9 of 12 months above last year; |change without spikes| < 10%; no significant trend.

Level: ≥ 75% of checks passed → high, ≥ 50% → medium, else low. Then caps:
- **low**: median < 100 views/month, period < 6 months, article created/renamed inside the period;
- **medium**: median < 1000 views/month, period < 24 months, automated share > 20%, incomplete basket.

Mann–Kendall assumes independent observations; monthly pageviews are autocorrelated, so p-values are
optimistic. That is why significance is only one of four checks, never the sole evidence.

## Ranking
Components are min–max normalised **within the chosen languages** (so the ranking is relative):
growth = adjusted change (clipped to −50%…+100%), size = log10(median views), intensity = share per
million, trust = high 1 / medium 0.5 / low 0. Score = weighted mean; default weights
growth 2, size 1, intensity 1, trust 1. Languages without an article are listed last.

## Conclusion check
`report` extracts every `N%` and `N/12` from the agent's conclusion and compares them with the run's
metrics (± rounding). Unmatched numbers are printed as a WARNING. It catches invented numbers, not a
correct number attributed to the wrong language — the agent must still use the findings verbatim.

## Known limitations
- Interest in an encyclopedia article ≠ product demand or willingness to pay.
- A language edition ≠ a country (Spanish Wikipedia serves Spain and Latin America; English serves the world).
- Some bots are classified as `user`; spikes in one month are the usual symptom.
- A single article is a proxy for a topic; baskets help, category-level coverage is future work.
- The edition's own traffic includes the Main Page and other non-topic traffic.
