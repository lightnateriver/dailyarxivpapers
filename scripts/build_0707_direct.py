#!/usr/bin/env python3
import json, subprocess, re, sys
from pathlib import Path
from collections import Counter
sys.path.insert(0, str(Path(__file__).parent))
from generate_daily_v2 import is_excluded, group_and_cap_candidates, ascend_priority, build_page

ROOT = Path('/root/clawcos/project/dailyarxivpapers')
SRC = ROOT / 'docs/data/2026-07-07.json'
OUT = ROOT / 'docs/data/2026-07-07.full_enriched.json'
HTML_OUT = ROOT / 'docs/daily/2026-07-07.html'

src = json.loads(SRC.read_text(encoding='utf-8'))
filtered = [p for p in src['papers'] if not is_excluded(p)]
papers = group_and_cap_candidates(filtered, per_topic_limit=5)

work = []
for p in papers:
    abstract = p.get('abstract', '')
    work.append({
        **p,
        'institutions_raw': '未明确披露',
        'content_snippet': abstract,
        'abstract': abstract,
        'code_links': [],
        'is_ascend': ascend_priority(p)
    })

# Batch summarize via hermes
for i in range(0, len(work), 2):
    batch = work[i:i+2]
    print(f'summarize batch {i//2 + 1}/{(len(work)+1)//2}', flush=True)
    payload = [{
        'id': p['id'], 'title_en': p['title'], 'institutions_raw': p['institutions_raw'],
        'abstract': p.get('abstract', '')[:2000],
        'topics': [t['name'] for t in p.get('topics', [])],
        'code_links': p.get('code_links', []),
    } for p in batch]
    prompt = (
        '你是认真读论文的研究助理。严格输出 JSON 数组，不要输出任何额外文字。\n'
        '字段固定：id, title_zh, institution, summary_cn, innovations, scenario_cn, opensource_status, code_url。\n'
        '要求：title_zh 准确翻译英文标题；summary_cn 2-4 句中文讲清楚论文做什么；innovations 2-4 条真实创新点；scenario_cn 说明解决的问题和适用场景；institution 用机构名，不要作者名；'
        '只有 code_links 有真实仓库才可写已确认开源。\n'
        '你只能依据 abstract 与 title 判断，不要臆造正文中不存在的具体数字。\n\n'
        f'{json.dumps(payload, ensure_ascii=False)}'
    )
    try:
        out = subprocess.check_output(['hermes', '-z', prompt], text=True, cwd=str(ROOT), timeout=480)
        txt = re.sub(r'^```json\s*|```$', '', out.strip(), flags=re.S).strip()
        txt = re.sub(r'(?<=[,\[])\s*,\s*', '', txt)
        txt = re.sub(r',\s*([}\]])', r'\1', txt)
        enriched = json.loads(txt)
        for item in enriched:
            base = next(x for x in batch if x['id'] == item['id'])
            base['title_zh'] = item.get('title_zh', base['title'])
            base['summary_cn'] = item.get('summary_cn', base.get('abstract', '')[:500])
            base['innovations'] = item.get('innovations', ['见正文'])
            base['scenario_cn'] = item.get('scenario_cn', base.get('summary_cn', '')[:300])
            base['institution'] = item.get('institution', '未明确披露')
    except Exception as e:
        print(f'[warn] batch failed: {e}', flush=True)
        # Fallback: retry once with single paper per batch
        for p in batch:
            single_payload = [{
                'id': p['id'], 'title_en': p['title'], 'institutions_raw': '未明确披露',
                'abstract': p.get('abstract', '')[:2000],
                'topics': [t['name'] for t in p.get('topics', [])],
                'code_links': [],
            }]
            single_prompt = (
                '你是认真读论文的研究助理。严格输出 JSON 数组。\n'
                '字段固定：id, title_zh, summary_cn, innovations, scenario_cn。\n'
                '用中文。summary_cn 2-4 句；innovations 2-4 条；scenario_cn 说明解决什么问题。\n'
                f'{json.dumps(single_payload, ensure_ascii=False)}'
            )
            try:
                out2 = subprocess.check_output(['hermes', '-z', single_prompt], text=True, cwd=str(ROOT), timeout=480)
                txt2 = re.sub(r'^```json\s*|```$', '', out2.strip(), flags=re.S).strip()
                txt2 = re.sub(r',\s*([}\]])', r'\1', txt2)
                item2 = json.loads(txt2)[0]
                p['title_zh'] = item2.get('title_zh', p['title'])
                p['summary_cn'] = item2.get('summary_cn', p.get('abstract', '')[:500])
                p['innovations'] = item2.get('innovations', ['见正文'])
                p['scenario_cn'] = item2.get('scenario_cn', p.get('abstract', '')[:300])
                p['institution'] = '未明确披露'
            except Exception:
                p['title_zh'] = p['title']
                p['summary_cn'] = p.get('abstract', '')[:500]
                p['innovations'] = ['见正文：' + p.get('abstract', '')[:100]]
                p['scenario_cn'] = p.get('abstract', '')[:300]
                p['institution'] = '未明确披露'

enriched_list = sorted(work, key=lambda p: (0 if p.get('is_ascend') else 1, 0 if p.get('code_links') else 1, -float(p.get('score', 0)), p.get('title', '')))
OUT.write_text(json.dumps({'date': src['date'], 'count': len(enriched_list), 'fetched_count': src['fetched_count'], 'papers': enriched_list}, ensure_ascii=False, indent=2), encoding='utf-8')
HTML_OUT.write_text(build_page(src, enriched_list), encoding='utf-8')
print(json.dumps({'ok': True, 'kept': len(enriched_list)}, ensure_ascii=False))
