#!/usr/bin/env python3
import json, re, subprocess
from pathlib import Path
ROOT = Path('/root/clawcos/project/dailyarxivpapers')
ENRICHED = ROOT / 'docs/data/2026-07-10.enriched.json'

def main():
    data = json.loads(ENRICHED.read_text(encoding='utf-8'))
    payload = [{'id': k, 'title': v.get('title') or ''} for k, v in data['papers'].items()]
    # merge original english title from source dataset
    src = json.loads((ROOT / 'docs/data/2026-07-10.json').read_text(encoding='utf-8'))
    title_map = {p['id']: p['title'] for p in src['papers']}
    for item in payload:
        item['title'] = title_map.get(item['id'], item['title'])
    prompt = (
        '请把下面论文英文标题翻译成自然、准确、偏技术风格的中文标题。严格输出 JSON 数组，不要输出任何额外文字。\n'
        '每个对象字段固定为：id, title_zh。不要解释，不要加序号。\n\n'
        f'{json.dumps(payload, ensure_ascii=False)}'
    )
    out = subprocess.check_output(['hermes', '-z', prompt], text=True, cwd=str(ROOT), timeout=180)
    text = re.sub(r'^```json\s*|```$', '', out.strip(), flags=re.S).strip()
    arr = json.loads(text)
    zh_map = {x['id']: x['title_zh'] for x in arr}
    for pid, item in data['papers'].items():
        item['title_en'] = title_map.get(pid, '')
        item['title_zh'] = zh_map.get(pid, '')
    ENRICHED.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'ok': True, 'count': len(arr)}, ensure_ascii=False))

if __name__ == '__main__':
    main()
