"""Grade Haiku transcripts produced by run_haiku.sh.

Automatic checks per turn (from the stream-json transcript + files in the case workdir):
  skill_used, right QIDs / languages / period / weights in `analyze`, PDF exists and has 1 page,
  missing article reported, confidence + limitations mentioned, every % and N/12 in the answer
  matches a metric of the run (no invented numbers), ambiguity handled.
Optional --judge: a stronger model scores the answer with a rubric (grounding, trust, limitations,
actionability) and lists factual errors.

Usage: .venv/bin/python evals/check.py evals/.runs/<stamp> [--judge] [--judge-model sonnet]
Writes <stamp>/results.md and prints it.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL_DIR))

from wikiinterest.report import check_conclusion_numbers  # noqa: E402

CASES = {c["id"]: c for c in json.loads((SKILL_DIR / "evals" / "cases.json").read_text())}
RE_CONF = re.compile(r"довір|надійн|confidence|впевнен", re.I)
RE_LIMIT = re.compile(r"обмежен|limitation|не означає|не дорівнює|≠|не є прям|лише проксі|проксі", re.I)
RE_MISSING = re.compile(r"немає статт|статті немає|відсутн|no article|не існує|немає окремої", re.I)


RE_RUN_ID = re.compile(r"(?:## Run |--run )(\d{8}-\d{6}-[\w-]+)")


def parse_turn(path: Path) -> dict:
    t = {"bash": [], "skills": [], "text": "", "cost": 0.0, "turns": 0, "ms": 0, "error": False, "tools": 0,
         "run_ids": [], "all_text": [], "tool_out": []}
    for line in path.read_text().splitlines():
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if e.get("type") == "assistant":
            for block in e["message"].get("content", []):
                if block.get("type") == "text":
                    t["all_text"].append(block["text"])
                if block.get("type") == "tool_use":
                    t["tools"] += 1
                    if block["name"] == "Bash":
                        t["bash"].append(block["input"].get("command", ""))
                    elif block["name"] == "Skill":
                        t["skills"].append(block["input"].get("skill", ""))
        elif e.get("type") == "user" and isinstance(e.get("message", {}).get("content"), list):
            for block in e["message"]["content"]:
                if block.get("type") == "tool_result":
                    content = block.get("content")
                    text = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)
                    t["run_ids"] += RE_RUN_ID.findall(text)
                    if "## Run " in text or "PDF:" in text or "## '" in text:
                        t["tool_out"].append(text)
        elif e.get("type") == "result":
            t["text"] = e.get("result") or ""
            t["cost"] = e.get("total_cost_usd") or 0.0
            t["turns"] = e.get("num_turns") or 0
            t["ms"] = e.get("duration_ms") or 0
            t["error"] = bool(e.get("is_error"))
    # What the user sees in chat = every assistant text block of the turn (the final one is t["text"]).
    t["all_text"] = "\n".join(t["all_text"]) or t["text"]
    return t


def analyze_calls(bash: list[str]) -> list[dict]:
    calls = []
    for cmd in bash:
        if "wiki.py" not in cmd or " analyze" not in cmd:
            continue
        langs = re.findall(r"--langs[ =]\"?([\w,\- ]+?)\"?(?:\s--|\s*$|\s*\|)", cmd)
        calls.append({
            "qids": [q.upper() for q in re.findall(r"--qid[ =]\"?(Q\d+)", cmd, re.I)],
            "langs": [l.strip() for l in (langs[-1] if langs else "").replace(" ", ",").split(",") if l.strip()],
            "months": int(m.group(1)) if (m := re.search(r"--months[ =](\d+)", cmd)) else None,
            "weights": "--weights" in cmd,
        })
    return calls


def pdf_pages(path: Path) -> int:
    data = path.read_bytes()
    return len(re.findall(rb"/Type\s*/Page[^s]", data))


def turn_run(workdir: Path, run_ids: list[str]) -> dict | None:
    """The run this turn worked with: last run id seen in its tool output, else the newest run on disk.

    Several runs in one turn are merged, so a number from any of them counts as verified."""
    runs = []
    for rid in dict.fromkeys(run_ids):
        f = workdir / "wiki-reports" / rid / "analysis.json"
        if f.exists():
            runs.append(json.loads(f.read_text()))
    if not runs:
        files = sorted((workdir / "wiki-reports").glob("*/analysis.json"), key=lambda p: p.stat().st_mtime)
        return json.loads(files[-1].read_text()) if files else None
    merged = runs[-1]
    if len(runs) > 1:
        merged = dict(merged, langs={f"{k}#{i}": v for i, r in enumerate(runs) for k, v in r["langs"].items()})
    return merged


def judge(case_prompt: str, answer: str, tool_out: list[str], model: str) -> dict:
    ground = "\n\n".join(tool_out)[-12000:] or "(the agent ran no analysis)"
    prompt = f"""You grade an AI analyst's answer. Reply with ONLY a JSON object.
User question: {case_prompt}
Ground truth = the exact tool output the analyst saw (the answer may only use facts from it):
<<<{ground}>>>
Answer to grade (everything the analyst wrote to the user in this turn):
<<<{answer}>>>
Score each 0-2: grounded (all numbers/claims supported by tool output), trust (explains how reliable the
signal is and why), limitations (states assumptions/limits), actionable (clear recommendation / next step),
language (answers in the user's language). List factual errors (claims contradicting the tool output).
JSON: {{"grounded":0,"trust":0,"limitations":0,"actionable":0,"language":0,"errors":["..."]}}"""
    out = subprocess.run(["claude", "-p", prompt, "--model", model, "--output-format", "json"],
                         capture_output=True, text=True, timeout=300)
    try:
        text = json.loads(out.stdout)["result"]
        return json.loads(re.search(r"\{.*\}", text, re.S).group(0))
    except Exception as exc:  # noqa: BLE001
        return {"error": f"judge failed: {exc}"}


def grade_case(case_dir: Path, use_judge: bool, judge_model: str) -> list[dict]:
    case = CASES[case_dir.name]
    rows = []
    turn_files = sorted(case_dir.glob("turn*.jsonl"), key=lambda p: int(p.stem[4:]))
    for i, tf in enumerate(turn_files):
        t = parse_turn(tf)
        spec = case if i == 0 else case["followups"][i - 1]
        exp = spec["expect"]
        calls = analyze_calls(t["bash"])
        last = calls[-1] if calls else {}
        run = turn_run(case_dir, t["run_ids"])
        checks: dict[str, bool] = {}
        checks["skill_used"] = bool(t["skills"]) or any("wiki.py" in c for c in t["bash"])
        if "qids" in exp:
            checks["qids"] = all(any(q in c["qids"] for c in calls) for q in exp["qids"])
        if "langs" in exp:
            checks["langs"] = bool(last) and set(exp["langs"]) <= set(last["langs"])
        if "months" in exp:
            checks["months"] = bool(last) and last["months"] == exp["months"]
        if exp.get("weights"):
            checks["weights"] = bool(last) and last["weights"]
        if exp.get("pdf"):
            pdfs = sorted((case_dir / "wiki-reports").glob("*/report-*.pdf"), key=lambda p: p.stat().st_mtime)
            ran_report = any("wiki.py" in c and " report" in c for c in t["bash"])
            checks["pdf_1_page"] = ran_report and bool(pdfs) and pdf_pages(pdfs[-1]) == 1
        if exp.get("missing"):
            checks["missing_reported"] = bool(RE_MISSING.search(t["text"]))
        if exp.get("ambiguity_handled"):
            all_q = [q for c in calls for q in c["qids"]]
            checks["ambiguity_handled"] = ("Q308" in all_q or "Q925" in all_q or "?" in t["all_text"]) and bool(
                re.search(r"хімічн|елемент|бог|альтернатив|уточн|який саме|неоднознач", t["all_text"], re.I))
        checks["confidence_stated"] = bool(RE_CONF.search(t["all_text"]))
        checks["limitations_stated"] = bool(RE_LIMIT.search(t["all_text"]))
        unverified = check_conclusion_numbers(run, t["all_text"]) if run else []
        checks["numbers_verified"] = not unverified
        row = {"case": case_dir.name, "turn": i, "checks": checks, "unverified": unverified, **{
            k: t[k] for k in ("cost", "turns", "ms", "tools", "error")}, "wiki_calls": sum("wiki.py" in c for c in t["bash"]),
            "answer": t["all_text"]}
        if use_judge:
            row["judge"] = judge(spec["prompt"], t["all_text"], t["tool_out"], judge_model)
        rows.append(row)
    return rows


def render(rows: list[dict], stamp_dir: Path) -> str:
    lines = [f"# Eval results: {stamp_dir.name}", "",
             "| case | turn | checks | wiki calls | tool calls | agent turns | time, s | cost, $ | failed / unverified |",
             "|---|---|---|---|---|---|---|---|---|"]
    total_ok = total = 0
    for r in rows:
        ok = sum(r["checks"].values())
        total_ok += ok
        total += len(r["checks"])
        failed = [k for k, v in r["checks"].items() if not v]
        extra = ", ".join(failed + ([f"nums: {' '.join(r['unverified'])}"] if r["unverified"] else [])) or "—"
        lines.append(f"| {r['case']} | {r['turn']} | {ok}/{len(r['checks'])} | {r['wiki_calls']} | {r['tools']} | "
                     f"{r['turns']} | {r['ms'] / 1000:.0f} | {r['cost']:.3f} | {extra} |")
    lines += ["", f"**Total: {total_ok}/{total} checks passed.**", ""]
    if any("judge" in r for r in rows):
        lines += ["## Judge scores (0-2 each)", "",
                  "| case | turn | grounded | trust | limitations | actionable | language | errors |", "|---|---|---|---|---|---|---|---|"]
        for r in rows:
            j = r.get("judge", {})
            lines.append(f"| {r['case']} | {r['turn']} | {j.get('grounded', '?')} | {j.get('trust', '?')} | "
                         f"{j.get('limitations', '?')} | {j.get('actionable', '?')} | {j.get('language', '?')} | "
                         f"{'; '.join(j.get('errors', [])) or j.get('error', '—')} |")
        lines.append("")
    lines += ["## Answers", ""]
    for r in rows:
        lines += [f"### {r['case']} / turn {r['turn']}", "", r["answer"].strip() or "_(empty)_", ""]
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("runs_dir")
    ap.add_argument("--judge", action="store_true")
    ap.add_argument("--judge-model", default="sonnet")
    args = ap.parse_args()
    stamp_dir = Path(args.runs_dir)
    rows = []
    for case_dir in sorted(p for p in stamp_dir.iterdir() if p.is_dir() and p.name in CASES):
        rows += grade_case(case_dir, args.judge, args.judge_model)
    text = render(rows, stamp_dir)
    (stamp_dir / "results.md").write_text(text)
    (stamp_dir / "results.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1))
    print(text)


if __name__ == "__main__":
    main()
