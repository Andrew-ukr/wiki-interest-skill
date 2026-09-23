"""Deterministic findings + one-page PDF (and a Markdown twin) from a saved run.

The agent contributes only the short conclusion; every number and finding in the
report is produced here from analysis.json, so the report cannot contradict the data.
"""
from __future__ import annotations

import re
from pathlib import Path

from fpdf import FPDF

from .charts import make_charts
from .i18n import lang_name, pct, render_check, t
from .paths import font_path

MAX_CONCLUSION = 700
PAGE_W, PAGE_H, MARGIN = 210, 297, 12
CONF_FILL = {"high": (220, 242, 222), "medium": (252, 240, 205), "low": (250, 222, 220)}
GREY = (82, 81, 78)
INK = (11, 11, 11)


# --- findings ---------------------------------------------------------------------------------
def _active_langs(run: dict) -> list[str]:
    return [l for l in run["params"]["langs"] if run["langs"][l]["status"] != "missing"]


def build_findings(run: dict, ui: str = "en", limit: int = 8, max_langs: int = 4) -> list[str]:
    tr = t(ui)
    out: list[str] = []
    langs = _active_langs(run)
    order = [r["lang"] for r in run["ranking"] if r["rank"]] or langs
    name = lambda code: lang_name(code, ui).capitalize()  # noqa: E731
    for code in order[:max_langs]:
        m = run["langs"][code]
        params = dict(name=name(code), direction=tr["direction"][m["direction"]], adj=pct(m["growth_adj"]),
                      raw=pct(m["growth_raw"]), conf=tr["confidence"][m["confidence"]], up=m["yoy_up"])
        out.append((tr["f_lang"] if m["yoy_n"] else tr["f_lang_short"]).format(**params))
    for code in run["params"]["langs"]:
        if run["langs"][code]["status"] == "missing":
            out.append(tr["f_missing"].format(name=name(code)))

    # Wikipedia-wide traffic context (why raw views mislead), once, if editions moved >= 5%.
    moves = [(code, run["langs"][code]["project_growth"]) for code in langs
             if run["langs"][code]["project_growth"] is not None]
    if moves and max(abs(g) for _, g in moves) >= 0.05:
        items = ", ".join(f"{code} {pct(g)}" for code, g in moves[:6])
        avg = sum(g for _, g in moves) / len(moves)
        out.append(tr["f_context"].format(items=items, bias=tr["f_bias_down"] if avg < 0 else tr["f_bias_up"]))

    spike_done = seasonal_done = False
    for code in langs:
        m = run["langs"][code]
        news = [s for s in m.get("spikes", []) if not s["seasonal"]]
        seasonal = [s for s in m.get("spikes", []) if s["seasonal"]]
        if news and not spike_done:
            s = news[0]
            out.append(tr["f_spike"].format(name=name(code), month=s["month"], x=s["x_median"],
                                            ex=pct(m["growth_adj_ex_spikes"])))
            spike_done = True
        if seasonal and not seasonal_done:
            months = sorted({s["month"][5:7] for s in seasonal})
            out.append(tr["f_seasonal"].format(name=name(code), months=", ".join(months)))
            seasonal_done = True
    for code in langs:
        m = run["langs"][code]
        if "low_volume" in m["flags"] or "modest_volume" in m["flags"]:
            out.append(tr["f_low_volume"].format(name=name(code), median=m["median_monthly"]))
        if m.get("long_change_adj") is not None and m.get("cagr_adj") is not None:
            out.append(tr["f_long"].format(name=name(code), n=m["months_n"], long=pct(m["long_change_adj"]),
                                           cagr=pct(m["cagr_adj"]), raw=pct(m["long_change_raw"])))
    if len(langs) >= 2:
        by_size = sorted(langs, key=lambda c: -run["langs"][c]["median_monthly"])
        out.append(tr["f_size"].format(order=" > ".join(
            f"{lang_name(c, ui)} {run['langs'][c]['median_monthly']:,}".replace(",", " ") for c in by_size)))
    ranked = [r for r in run["ranking"] if r["rank"]]
    if len(ranked) >= 2:
        weights = run["params"].get("weights") or {}
        wtxt = ", ".join(f"{k}={v:g}" for k, v in weights.items())
        out.append(tr["f_rank"].format(weights=wtxt, order=" > ".join(lang_name(r["lang"], ui) for r in ranked)))
    return out[:limit]


def draft_facts(run: dict, ui: str) -> str:
    """Deterministic factual part of the chat answer in the user's language (cheap models copy, not compute)."""
    tr = t(ui)
    lines = []
    for qid, rivals in (run["topic"].get("alternatives") or {}).items():
        if rivals:
            label = (run["topic"].get("labels_all", {}).get(qid, {}).get(ui) or run["topic"]["labels"].get(qid, qid))
            alts = "; ".join(r.split(" ", 1)[1] for r in rivals)
            lines.append(tr["f_ambiguous"].format(label=label, desc=run["topic"]["descriptions"].get(qid, ""), alts=alts))
    lines += build_findings(run, ui, limit=20, max_langs=12)
    lines += confidence_lines(run, ui)
    lines.append(tr["limitations"])
    return tr["draft_head"].format(lang=ui) + "\n" + "\n".join(f"- {l}" for l in lines)


def confidence_lines(run: dict, ui: str = "en", limit: int = 8) -> list[str]:
    tr = t(ui)
    lines = []
    for code in _active_langs(run)[:limit]:
        m = run["langs"][code]
        checks = "; ".join(render_check(c, ui) for c in m["checks"])
        lines.append(f"{lang_name(code, ui).capitalize()} — {tr['confidence'][m['confidence']]}: {checks}")
    return lines


def table_rows(run: dict, ui: str = "en") -> list[list[str]]:
    tr = t(ui)
    rows = []
    for code in run["params"]["langs"]:
        m = run["langs"][code]
        name = f"{lang_name(code, ui).capitalize()} ({code})"
        if m["status"] == "missing":
            rows.append([name, tr["no_article"], "—", "—", "—", "—", "—"])
            continue
        yoy = f"{m['yoy_up']}/{m['yoy_n']}" if m["yoy_n"] else "—"
        trend = pct(m["trend_adj_per_year"]) + ("*" if (m["mk_p"] or 1) < 0.05 else "")
        rows.append([name, f"{m['median_monthly']:,}".replace(",", " "), pct(m["growth_raw"]),
                     pct(m["growth_adj"]), yoy, trend,
                     f"{tr['confidence'][m['confidence']]} · {tr['direction'][m['direction']]}"])
    return rows


# --- PDF -----------------------------------------------------------------------------------------------
class _Pdf(FPDF):
    def __init__(self):
        super().__init__(format="A4")
        self.set_auto_page_break(False)
        self.set_margins(MARGIN, MARGIN, MARGIN)
        self.add_font("dv", "", str(font_path()))
        self.add_font("dv", "B", str(font_path(bold=True)))
        self.add_page()

    def para(self, text: str, size: float, style: str = "", color=INK, h: float | None = None, fill=None):
        self.set_font("dv", style, size)
        self.set_text_color(*color)
        if fill:
            self.set_fill_color(*fill)
        self.multi_cell(0, h or size * 0.48, text, new_x="LMARGIN", new_y="NEXT", fill=bool(fill), align="L")


def _topic_title(run: dict, ui: str) -> str:
    names = []
    for qid in run["params"]["qids"]:
        labels = run["topic"].get("labels_all", {}).get(qid, {})
        name = labels.get(ui) or run["topic"]["labels"].get(qid, qid)
        names.append(name[:1].upper() + name[1:])
    return " + ".join(names)


def _render(run: dict, charts: dict, ui: str, title: str, question: str | None, conclusion: str,
            n_findings: int, scale: float, n_conf: int = 8) -> _Pdf:
    tr = t(ui)
    pr = run["params"]
    pdf = _Pdf()
    pdf.para(title, 15 * scale, "B", h=7 * scale)
    pdf.para(tr["subtitle"].format(start=pr["start"], end=pr["end"], n=pr["months_n"]), 7 * scale, color=GREY)
    if question:
        pdf.ln(1)
        pdf.para(f"{tr['question']}: {question}", 7.5 * scale, color=GREY)
    pdf.ln(2.5)

    # Key numbers table
    widths = [34, 21, 27, 24, 21, 20, 39]
    rh = 5.2 * scale
    pdf.set_font("dv", "B", 6.8 * scale)
    pdf.set_fill_color(241, 240, 236)
    pdf.set_text_color(*INK)
    for w, head in zip(widths, tr["table"]):
        size = 6.8 * scale
        while pdf.get_string_width(head) > w - 1.5 and size > 4.5:
            size -= 0.2
            pdf.set_font("dv", "B", size)
        pdf.cell(w, rh, head, border=0, fill=True, align="C")
        pdf.set_font("dv", "B", 6.8 * scale)
    pdf.ln(rh)
    pdf.set_font("dv", "", 6.8 * scale)
    for code, row in zip(pr["langs"], table_rows(run, ui)):
        conf = run["langs"][code].get("confidence")
        for i, (w, val) in enumerate(zip(widths, row)):
            fill = i == len(row) - 1 and conf in CONF_FILL
            if fill:
                pdf.set_fill_color(*CONF_FILL[conf])
            pdf.cell(w, rh, val, border="B", fill=fill, align="L" if i == 0 else "C")
        pdf.ln(rh)
    pdf.set_font("dv", "", 5.5 * scale)
    pdf.set_text_color(*GREY)
    pdf.cell(0, 3.5, "* p < 0.05 (Mann–Kendall)", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(1.5)

    # Charts side by side
    if charts:
        w = (PAGE_W - 2 * MARGIN - 4) / 2
        h = w * 2.35 / 3.75
        y = pdf.get_y()
        pdf.image(charts["trend"], x=MARGIN, y=y, w=w, h=h)
        pdf.image(charts["share"], x=MARGIN + w + 4, y=y, w=w, h=h)
        pdf.set_y(y + h + 2)

    pdf.para(tr["findings"], 9 * scale, "B", h=5)
    for line in build_findings(run, ui, limit=n_findings):
        pdf.para(f"•  {line}", 7.3 * scale, h=3.7 * scale)
    pdf.ln(1.5)

    pdf.para(tr["conclusion"], 9 * scale, "B", h=5)
    pdf.para(conclusion, 7.6 * scale, h=3.9 * scale, fill=(234, 242, 251))
    pdf.ln(1.5)

    pdf.para(tr["confidence_head"], 6.8 * scale, "B", h=3.4)
    for line in confidence_lines(run, ui, n_conf):
        pdf.para(line, 6 * scale, color=GREY, h=3 * scale)
    pdf.ln(1.2)
    pdf.para(tr["method"], 6.8 * scale, "B", h=3.4)
    pdf.para(tr["method_text"], 5.7 * scale, color=GREY, h=2.8 * scale)
    pdf.ln(1)
    pdf.para(tr["footer"].format(run=run["run_id"], date=run["created_at"][:10]), 5.5 * scale, color=GREY)
    return pdf


def build_report(run: dict, run_dir: Path, ui: str, conclusion: str, title: str | None = None,
                 question: str | None = None, out: Path | None = None) -> dict:
    conclusion = " ".join(conclusion.split())
    if not conclusion:
        raise ValueError("--conclusion is required: 2-4 sentences with your recommendation, based on the numbers")
    if len(conclusion) > MAX_CONCLUSION:
        raise ValueError(f"--conclusion is {len(conclusion)} chars; shorten it to <= {MAX_CONCLUSION}")
    if not title:
        topic = _topic_title(run, ui)
        title = f"{topic[:1].upper()}{topic[1:]}: " + ", ".join(lang_name(l, ui) for l in run["params"]["langs"])
    charts = make_charts(run, run_dir, ui)

    # Try progressively denser layouts until everything fits on one page.
    pdf = None
    layouts = ((8, 1.1, 8), (8, 1.0, 8), (7, 1.0, 6), (6, 0.93, 6), (5, 0.88, 4), (4, 0.82, 3))
    for n_findings, scale, n_conf in layouts:
        pdf = _render(run, charts, ui, title, question, conclusion, n_findings, scale, n_conf)
        if pdf.page_no() == 1 and pdf.get_y() <= PAGE_H - 8:
            break
    else:
        raise RuntimeError("report does not fit on one page; shorten the title/question/conclusion")

    out = out or run_dir / f"report-{ui}.pdf"
    out.parent.mkdir(parents=True, exist_ok=True)
    pdf.output(str(out))
    md = write_markdown(run, run_dir, ui, title, question, conclusion, charts)
    return {"pdf": str(out), "markdown": str(md), "pages": pdf.page_no(), "charts": charts,
            "unverified_numbers": check_conclusion_numbers(run, conclusion),
            "wording": check_conclusion_wording(run, conclusion)}


_NEGATION = re.compile(r"\bне\b|немає|нема\b|відсутн|\bno\b|\bnot\b|without|замість", re.I)
_GROWTH_WORDS = re.compile(r"зроста|зріст|\bрост|\bріст|росте|виріс|grow|increas|rising", re.I)


def check_conclusion_wording(run: dict, text: str) -> str:
    """Flag 'growth' language when the analysis found no growing language."""
    langs = [m for m in run["langs"].values() if m.get("status") != "missing"]
    if not langs or any(m.get("direction") == "growing" for m in langs):
        return ""
    for match in _GROWTH_WORDS.finditer(text):
        window = text[max(0, match.start() - 25): match.end() + 25]
        if not _NEGATION.search(window):  # "зростання немає" / "no growth" is the correct wording
            return ("the conclusion uses growth wording, but no language is 'growing' in the analysis "
                    "(use 'stable'/'declining' as in the table, or say growth is absent)")
    return ""


_PCT_RE = re.compile(r"([+\-−–]?\s?\d+(?:[.,]\d+)?)\s?%")
_RANGE_RE = re.compile(r"([+\-−–]?\d+(?:[.,]\d+)?)\s?(?:…|\.\.\.?|–|—|-|до|to)\s?([+\-−–]?\d+(?:[.,]\d+)?)\s?%")
# 3+ digit integers, optionally with thousands separators ("7 170", "24,645"), not part of % or dates
_COUNT_RE = re.compile(r"(?<![\w.,%-])(\d{1,3}(?:[ \u00a0,]\d{3})+|\d{3,})(?![\d%.,]|\s?%|-\d)")
_YOY_RE = re.compile(r"\b(\d{1,2})\s?(?:/|з|of|із)\s?12\b")
_PCT_KEYS = ("growth_adj", "growth_raw", "project_growth", "growth_adj_ex_spikes", "trend_adj_per_year",
             "long_change_adj", "long_change_raw", "cagr_adj", "automated_share")


def check_conclusion_numbers(run: dict, text: str) -> list[str]:
    """Return numbers in the agent's conclusion that match no metric of the run (possible hallucination)."""
    known: list[float] = []
    yoy: set[int] = set()
    for m in run["langs"].values():
        for key in _PCT_KEYS:
            val = m.get(key)
            if isinstance(val, (int, float)):
                known.append(abs(val * 100))
        if m.get("yoy_n"):
            yoy.update({m["yoy_up"], m["yoy_n"] - m["yoy_up"]})
    def num(x: str) -> float:
        return float(x.replace("−", "-").replace("–", "-").replace(" ", "").replace(",", "."))
    found: list[str] = []
    candidates = [g for pair in _RANGE_RE.findall(text) for g in pair] + _PCT_RE.findall(text)
    for raw in candidates:
        value = num(raw)
        # tolerance = rounding to whole percent (a 1-decimal rounding also passes)
        if not any(abs(abs(value) - k) <= 0.55 for k in known):
            found.append(f"{raw.strip()}%")
    counts = []
    for m in run["langs"].values():
        counts += [m.get("median_monthly"), m.get("total_views")]
        counts += [a.get("median_monthly") for a in m.get("articles", [])]
    counts = [c for c in counts if isinstance(c, int) and c > 0]
    for raw in _COUNT_RE.findall(text):
        value = int(re.sub(r"[\s ,.]", "", raw))
        if 1900 <= value <= 2100 or value < 100:  # years and small numbers are not view counts
            continue
        if not any(abs(value - c) <= max(1, 0.01 * c) for c in counts):
            found.append(raw.strip())
    for raw in _YOY_RE.findall(text):
        if int(raw) not in yoy:
            found.append(f"{raw}/12")
    return sorted(set(found))


def write_markdown(run: dict, run_dir: Path, ui: str, title: str, question: str | None, conclusion: str,
                   charts: dict) -> Path:
    tr = t(ui)
    pr = run["params"]
    lines = [f"# {title}", "", tr["subtitle"].format(start=pr["start"], end=pr["end"], n=pr["months_n"]), ""]
    if question:
        lines += [f"**{tr['question']}:** {question}", ""]
    lines += ["| " + " | ".join(tr["table"]) + " |", "|" + "---|" * len(tr["table"])]
    lines += ["| " + " | ".join(r) + " |" for r in table_rows(run, ui)]
    lines += [""]
    for name, path in charts.items():
        lines.append(f"![{name}]({Path(path).name})")
    lines += ["", f"## {tr['findings']}", *[f"- {f}" for f in build_findings(run, ui)], "",
              f"## {tr['conclusion']}", conclusion, "", f"## {tr['method']}",
              *[f"- {l}" for l in confidence_lines(run, ui)], "", tr["method_text"], "",
              f"_{tr['footer'].format(run=run['run_id'], date=run['created_at'][:10])}_"]
    path = run_dir / f"report-{ui}.md"
    path.write_text("\n".join(lines))
    return path
