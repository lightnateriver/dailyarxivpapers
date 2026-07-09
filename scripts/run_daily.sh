#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
python3 scripts/generate_daily.py "$@"
if ! git diff --quiet -- docs data config scripts AGENTS.md 2>/dev/null; then
  git add AGENTS.md config scripts docs data
  git commit -m "daily paper digest: $(date -d yesterday +%F)" || true
fi
git push origin main
