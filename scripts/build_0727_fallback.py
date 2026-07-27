#!/usr/bin/env python3
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path('/root/clawcos/project/dailyarxivpapers/scripts')))
from generate_daily_v2 import is_excluded, group_and_cap_candidates, ascend_priority, build_page, sort_key

ROOT = Path('/root/clawcos/project/dailyarxivpapers')
src = json.loads((ROOT / 'docs/data/2026-07-27.json').read_text())
filtered = [p for p in src['papers'] if not is_excluded(p)]
papers = group_and_cap_candidates(filtered, per_topic_limit=5)

enriched = []
for p in papers:
    enriched.append({
        **p,
        'title_en': p['title'],
        'title_zh': p['title'],
        'summary_cn': p.get('abstract', '')[:500],
        'innovations': ['见正文'],
        'scenario_cn': p.get('abstract', '')[:300],
        'institution': '未明确披露',
        'opensource_status': '未确认开源',
        'code_url': '',
        'is_ascend': ascend_priority(p),
    })

enriched = sorted(enriched, key=sort_key)
html = build_page(src, enriched)
(ROOT / 'docs/daily/2026-07-27.html').write_text(html)
(ROOT / 'docs/data/2026-07-27.full_enriched.json').write_text(
    json.dumps({'date': '2026-07-27', 'count': len(enriched), 'fetched_count': src['fetched_count'], 'papers': enriched}, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps({'ok': True, 'kept': len(enriched)}))
