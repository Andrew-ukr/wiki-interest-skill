#!/usr/bin/env bash
# Runs every case from cases.json through Claude Code on Claude Haiku 4.5 with ONLY this skill installed,
# in a clean working directory per case. Follow-ups continue the same session (--resume).
# Transcripts (stream-json) and generated reports land in evals/.runs/<timestamp>/<case>/.
#
# Usage: evals/run_haiku.sh [case-id ...]        (default: all cases)
# Then:  .venv/bin/python evals/check.py evals/.runs/<timestamp> [--judge]
set -euo pipefail

SKILL_DIR="$(cd "$(dirname "$0")/.." && pwd)"
MODEL="${EVAL_MODEL:-haiku}"
STAMP="$(date +%Y%m%d-%H%M%S)"
OUT="$SKILL_DIR/evals/.runs/$STAMP"
mkdir -p "$OUT"
python3 "$SKILL_DIR/scripts/wiki.py" --help >/dev/null  # make sure the venv exists before timing starts

IDS=("$@")
if [ ${#IDS[@]} -eq 0 ]; then
  IDS=($(python3 -c "import json;print(' '.join(c['id'] for c in json.load(open('$SKILL_DIR/evals/cases.json'))))"))
fi

ask() {  # ask <workdir> <prompt> <transcript> [session-id]
  local dir="$1" prompt="$2" log="$3" session="${4:-}"
  local resume=()
  [ -n "$session" ] && resume=(--resume "$session")
  (cd "$dir" && claude -p "$prompt" --model "$MODEL" ${resume[@]+"${resume[@]}"} \
      --output-format stream-json --verbose --setting-sources project,local \
      --allowedTools "Skill" "Read" "Glob" "Grep" "Bash(python3:*)" "Bash(ls:*)" "Bash(cat:*)" \
      --max-turns 30 > "$log" 2> "$log.stderr") || echo "  (claude exited with $?)" >&2
  python3 -c "
import json,sys
for line in open('$log'):
    try: e=json.loads(line)
    except ValueError: continue
    if e.get('type')=='result': print(e.get('session_id',''))" | tail -1
}

for id in "${IDS[@]}"; do
  dir="$OUT/$id"
  mkdir -p "$dir/.claude/skills"
  ln -s "$SKILL_DIR" "$dir/.claude/skills/wiki-interest-research"
  prompt=$(python3 -c "import json;c=[c for c in json.load(open('$SKILL_DIR/evals/cases.json')) if c['id']=='$id'][0];print(c['prompt'])")
  echo "== $id"
  session=$(ask "$dir" "$prompt" "$dir/turn0.jsonl")
  n=$(python3 -c "import json;c=[c for c in json.load(open('$SKILL_DIR/evals/cases.json')) if c['id']=='$id'][0];print(len(c.get('followups',[])))")
  for ((i=1; i<=n; i++)); do
    fp=$(python3 -c "import json;c=[c for c in json.load(open('$SKILL_DIR/evals/cases.json')) if c['id']=='$id'][0];print(c['followups'][$i-1]['prompt'])")
    echo "   follow-up $i"
    session=$(ask "$dir" "$fp" "$dir/turn$i.jsonl" "$session")
  done
done
echo "transcripts: $OUT"
echo "next: $SKILL_DIR/.venv/bin/python $SKILL_DIR/evals/check.py $OUT"
