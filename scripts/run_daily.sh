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

# 抓取基础数据（带重试）
DAILY_HTML="docs/daily/${TARGET_DATE}.html"
DAILY_JSON="docs/data/${TARGET_DATE}.json"
retry 3 60 python3 scripts/generate_daily.py --date "${TARGET_DATE}" --fail-on-empty-fetch || {
  echo "[warn] fetch failed after retries; skipping v2 pipeline"
  SKIP_V2=1
}

if [ "${SKIP_V2:-0}" != "1" ]; then
  # v2 摘要生成（带独立超时保护）
  timeout 600 python3 scripts/generate_daily_v2.py --date "${TARGET_DATE}" || {
    echo "[warn] v2 pipeline failed/timed out; page may have raw abstract content"
  }
fi

# 如果 v2 失败但基础数据存在，用降级方案生成页面
FULL_ENRICHED="docs/data/${TARGET_DATE}.full_enriched.json"
if [ ! -s "$FULL_ENRICHED" ] && [ -s "$DAILY_JSON" ]; then
  echo "[info] v2 enriched data missing; building fallback page"
  python3 -c "
import json, sys
from pathlib import Path
sys.path.insert(0, 'scripts')
from generate_daily_v2 import is_excluded, group_and_cap_candidates, ascend_priority, build_page, sort_key
ROOT = Path('.')
src = json.loads(Path('$DAILY_JSON').read_text())
filtered = [p for p in src['papers'] if not is_excluded(p)]
papers = group_and_cap_candidates(filtered, per_topic_limit=5)
enriched = [{**p, 'title_en': p['title'], 'title_zh': p['title'],
  'summary_cn': (p.get('abstract') or '')[:500],
  'innovations': ['见正文'], 'scenario_cn': (p.get('abstract') or '')[:300],
  'institution': '未明确披露', 'opensource_status': '未确认开源', 'code_url': '',
  'is_ascend': ascend_priority(p)} for p in papers]
enriched = sorted(enriched, key=sort_key)
Path('$FULL_ENRICHED').write_text(json.dumps({'date':'$TARGET_DATE','count':len(enriched),
  'fetched_count':src['fetched_count'],'papers':enriched}, ensure_ascii=False))
Path('$DAILY_HTML').write_text(build_page(src, enriched))
print('fallback ok, kept:', len(enriched))
"
fi

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

# 自动重建首页 index.html
python3 - <<PY
import json
from pathlib import Path
root = Path('.')
entries = []
for f in sorted(root.glob('docs/data/*.full_enriched.json')):
    try:
        d = json.loads(f.read_text())
        entries.append({'date': f.stem.replace('.full_enriched',''), 'count': d['count']})
    except:
        pass
entries = sorted(entries, key=lambda x: x['date'], reverse=True)
if entries:
    latest = entries[0]
    index_html = '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Paper Radar</title><link rel="stylesheet" href="./assets/style.css"></head><body><main class="container"><section class="hero"><div class="eyebrow">AI Paper Radar</div><h1>每日AI 论文</h1><p class="subtitle">浅色扁平化 arXiv 论文日报。</p></section>'
    index_html += '<div class="panel"><div class="eyebrow">Latest</div><h2>最新日报：' + latest['date'] + '</h2>'
    index_html += '<p><a href="./daily/' + latest['date'] + '.html">查看 ' + latest['date'] + ' 日报 →</a></p></div>'
    index_html += '<section class="grid"><div class="card"><h3>最近日报</h3><ul class="date-list">'
    for e in entries:
        index_html += '<li><a href="./daily/' + e['date'] + '.html">' + e['date'] + '</a><span>' + str(e['count']) + ' 篇</span></li>'
    index_html += '</ul></div></section></main></body></html>'
    root.joinpath('docs/index.html').write_text(index_html)
    print('index rebuilt, latest:', latest['date'])
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
