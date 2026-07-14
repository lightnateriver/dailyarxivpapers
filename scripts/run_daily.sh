#!/usr/bin/env bash
set -Eeuo pipefail

cd "$(dirname "$0")/.."
mkdir -p logs

TARGET_DATE="${TARGET_DATE:-$(date -d yesterday +%F)}"
LOG_FILE="logs/${TARGET_DATE}.log"
exec > >(tee -a "$LOG_FILE") 2>&1

echo "========== dailyarxivpapers run: $(date -Is) =========="
echo "workdir: $(pwd)"
echo "target_date: ${TARGET_DATE}"

retry() {
  local attempts="$1"; shift
  local delay="$1"; shift
  local n=1
  while true; do
    echo "[try ${n}/${attempts}] $*"
    if "$@"; then
      return 0
    fi
    if [ "$n" -ge "$attempts" ]; then
      echo "[error] command failed after ${attempts} attempts: $*"
      return 1
    fi
    echo "[warn] command failed; sleep ${delay}s then retry"
    sleep "$delay"
    n=$((n + 1))
    delay=$((delay * 2))
  done
}

# 先补推历史未推送 commit；失败不终止，后续 push 阶段会重试。
git fetch origin main || true
if git rev-parse --verify origin/main >/dev/null 2>&1; then
  git rebase origin/main || {
    echo "[warn] git rebase origin/main failed; aborting rebase and continuing with local state"
    git rebase --abort || true
  }
fi

python3 scripts/generate_daily.py --date "${TARGET_DATE}" --fail-on-empty-fetch
python3 scripts/generate_daily_v2.py --date "${TARGET_DATE}"

DAILY_HTML="docs/daily/${TARGET_DATE}.html"
DAILY_JSON="docs/data/${TARGET_DATE}.json"
if [ ! -s "$DAILY_HTML" ] || [ ! -s "$DAILY_JSON" ]; then
  echo "[error] expected output missing: $DAILY_HTML / $DAILY_JSON"
  exit 1
fi

python3 - <<PY
import json
from pathlib import Path
html = Path("$DAILY_HTML")
data = Path("$DAILY_JSON")
payload = json.loads(data.read_text(encoding="utf-8"))
assert payload.get("date") == "$TARGET_DATE", payload.get("date")
assert payload.get("count") == len(payload.get("papers", []))
assert "class=\"category-card\"" in html.read_text(encoding="utf-8") or payload.get("count") == 0
print({"verified": True, "date": payload.get("date"), "count": payload.get("count"), "topics": len(payload.get("topics", [])), "open_source_count": payload.get("open_source_count", 0)})
PY

if ! git diff --quiet -- docs config scripts AGENTS.md README.md .gitignore 2>/dev/null; then
  git add .gitignore AGENTS.md README.md config scripts docs
  git commit -m "daily paper digest: ${TARGET_DATE}" || true
else
  echo "[info] no changes to commit"
fi

if [ "${SKIP_PUSH:-0}" = "1" ]; then
  echo "[info] SKIP_PUSH=1, skip git push"
  exit 0
fi

if [ -f .env ]; then
  # .env is git-ignored. Supported variable: GITHUB_TOKEN=ghp_xxx
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

if [ -n "${GITHUB_TOKEN:-}" ]; then
  PUSH_URL="https://lightnateriver:${GITHUB_TOKEN}@github.com/lightnateriver/dailyarxivpapers.git"
  retry 3 30 git push "$PUSH_URL" main
else
  retry 3 30 git push origin main
fi

git remote set-url origin https://github.com/lightnateriver/dailyarxivpapers.git

echo "[ok] dailyarxivpapers finished: ${TARGET_DATE}"
