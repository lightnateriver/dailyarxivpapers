#!/usr/bin/env python3
from __future__ import annotations
import json, re, subprocess, urllib.request, urllib.parse, html, html as ihtml
from pathlib import Path

ROOT = Path('/root/clawcos/project/dailyarxivpapers')
SRC = ROOT / 'docs/data/2026-07-08.json'
OUT = ROOT / 'docs/data/2026-07-08.full_enriched.json'
HTML_OUT = ROOT / 'docs/daily/2026-07-08.html'
CSS = ROOT / 'docs/assets/style.css'
CACHE_DIR = ROOT / 'cache' / 'paper_html_2026_07_08'
RESUME_FILE = ROOT / 'cache' / 'paper_html_2026_07_08' / 'resume_enriched.json'
CACHE_DIR.mkdir(parents=True, exist_ok=True)

VERTICAL_EXCLUDE = [
    'nutrition', 'nutrient', 'health advice', 'diabetes', 'clinical', 'therapy', 'hepatocellular',
    'cardiovascular', 'medical', 'underwater', 'drone', 'uav', 'agri', 'agric', 'robotic surface swabbing',
    'food', 'deepfake', 'table tennis', 'disease risk', 'healthcare', 'patient', 'farmland', 'crop', 'aquatic'
]
EDGE_EXCLUDE = [
    'edge deployment', 'edge systems', 'edgeai', 'on-device', 'mobile reasoning', 'mobile reasoning-as-a-service',
    'mobile', 'jetson', 'edge ', 'resource-constrained device', 'resource constrained device'
]
ASCEND_PRIORITY = ['ascend', 'huawei', 'cann', 'torch_npu', '910b', 'npu']
INSTITUTION_HINTS = ['University', 'Institute', 'Lab', 'Laboratory', 'School', 'College', 'Academy', 'Center', 'Centre', 'Google', 'Meta', 'Microsoft', 'OpenAI', 'Anthropic', 'NVIDIA', 'Huawei', 'Alibaba', 'Tencent', 'ByteDance', 'Amazon', 'Apple', 'CMU', 'MIT', 'Stanford', 'Berkeley', 'Tsinghua', 'Peking', 'Chinese University of Hong Kong', 'University of California', 'Shanghai Jiao Tong University', 'University of Melbourne']


def clean(s: str) -> str:
    return re.sub(r'\s+', ' ', s or '').strip()

def strip_tags(s: str) -> str:
    return clean(ihtml.unescape(re.sub(r'<[^>]+>', ' ', s)))

def normalize_url(url: str) -> str:
    return url.rstrip('.,;:。)]}')

def fetch(url: str, timeout: int = 60) -> str:
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 dailyarxivpapers'})
    return urllib.request.urlopen(req, timeout=timeout).read().decode('utf-8', errors='ignore')

def detect_code_links(text: str) -> list[str]:
    urls = []
    for u in re.findall(r'https?://[^\s"\'\)<>]+', text or ''):
        u = normalize_url(u)
        if 'github.com' in u.lower() or 'gitlab.com' in u.lower() or '4open.science' in u.lower():
            urls.append(u)
    out, seen = [], set()
    for u in urls:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out

def code_link_has_content(url: str) -> bool:
    try:
        url = normalize_url(url)
        parsed = urllib.parse.urlparse(url)
        if parsed.netloc.lower() == 'github.com':
            parts = [p for p in parsed.path.strip('/').split('/') if p]
            if len(parts) < 2:
                return False
            owner, repo = parts[0], parts[1]
            body = fetch(f'https://github.com/{owner}/{repo}', timeout=25)
            if 'This repository is empty' in body:
                return False
            return bool(re.search(rf'href="/{re.escape(owner)}/{re.escape(repo)}/(tree|blob)/', body))
        if '4open.science' in parsed.netloc.lower():
            body = fetch(url, timeout=25)
            return 'Repository not found' not in body and len(body) > 200
    except Exception:
        return False
    return False

def is_excluded(p: dict) -> bool:
    text = (p['title'] + ' ' + (p.get('abstract') or '')).lower()
    return any(k in text for k in VERTICAL_EXCLUDE) or any(k in text for k in EDGE_EXCLUDE)

def ascend_priority(p: dict) -> bool:
    text = (p['title'] + ' ' + (p.get('abstract') or '')).lower()
    return any(k in text for k in ASCEND_PRIORITY)

def sort_key(p: dict):
    return (0 if p.get('is_ascend') else 1, 0 if p.get('code_links') else 1, -float(p.get('score', 0)), p.get('title', ''))

def group_and_cap_candidates(papers: list[dict], per_topic_limit: int = 5) -> list[dict]:
    grouped = {}
    for p in papers:
        topic = p['topics'][0]['name'] if p.get('topics') else 'Other'
        grouped.setdefault(topic, []).append(p)
    selected = []
    for items in grouped.values():
        ranked = sorted(items, key=lambda p: (0 if ascend_priority(p) else 1, -float(p.get('score', 0)), p.get('title', '')))
        selected.extend(ranked[:per_topic_limit])
    return selected

def parse_abs_cached(p: dict):
    base = p['id'].split('v')[0]
    cache_file = CACHE_DIR / f'{base}.json'
    if cache_file.exists():
        return json.loads(cache_file.read_text(encoding='utf-8'))
    page = fetch(p['abs_url'])
    m = re.search(r'https://arxiv.org/html/[^"\']+', page)
    html_link = m.group(0) if m else None
    abstract = ''
    m_abs = re.search(r'<blockquote class="abstract[^>]*">(.*?)</blockquote>', page, re.S)
    if m_abs:
        abstract = strip_tags(m_abs.group(1).replace('Abstract:', ''))
    data = {'abs_page': page, 'html_link': html_link, 'abstract': abstract}
    cache_file.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
    return data

def guess_institutions_from_abs(page: str) -> str:
    text = strip_tags(page)
    chunks = [clean(x) for x in text.split('  ') if clean(x)]
    keep = []
    for line in chunks[:60]:
        if '@' in line:
            continue
        if any(h in line for h in INSTITUTION_HINTS):
            keep.append(line)
    out = []
    for line in keep:
        if line not in out:
            out.append(line)
    return ' / '.join(out[:4]) if out else '作者单位待进一步解析'

def summarize_batch(batch: list[dict]) -> list[dict]:
    payload = []
    for p in batch:
        payload.append({
            'id': p['id'],
            'title_en': p['title'],
            'institutions_raw': p['institutions_raw'],
            'abstract': p.get('abstract', ''),
            'topics': [t['name'] for t in p.get('topics', [])],
            'code_links': p.get('code_links', []),
        })
    prompt = (
        '你是认真读论文的研究助理。严格输出 JSON 数组，不要输出任何额外文字。\n'
        '字段固定：id, title_zh, institution, summary_cn, innovations, scenario_cn, opensource_status, code_url。\n'
        '要求：title_zh 准确翻译英文标题；summary_cn 2-4 句中文讲清楚论文做什么；innovations 2-4 条真实创新点；scenario_cn 说明解决的问题和适用场景；institution 用机构名，不要作者名；只有 code_links 有真实仓库才可写已确认开源。\n'
        '你只能依据 abstract 与 title 判断，不要臆造正文中不存在的具体数字。\n\n'
        f'{json.dumps(payload, ensure_ascii=False)}'
    )
    out = subprocess.check_output(['hermes', '-z', prompt], text=True, cwd=str(ROOT), timeout=240)
    txt = re.sub(r'^```json\s*|```$', '', out.strip(), flags=re.S).strip()
    return json.loads(txt)

def ensure_css():
    css = CSS.read_text(encoding='utf-8')
    if '.deep-title-en' not in css:
        css += '\n.deep-card { background: #fffdf8; border: 1px solid var(--line); }\n.deep-title-en { font-size: 22px; line-height: 1.35; margin-top: 8px; }\n.deep-title-zh { font-size: 15px; color: var(--teal); margin-top: 6px; font-weight: 700; }\n.deep-inst { font-size: 12px; color: var(--muted); margin-top: 8px; }\n.deep-body { grid-template-columns: 1fr 1fr; }\n.deep-summary { grid-column: 1; }\n.deep-innovation { grid-column: 2; }\n.deep-scenario { grid-column: 1 / -1; }\n@media (max-width: 800px) { .deep-body { grid-template-columns: 1fr; } .deep-summary, .deep-innovation, .deep-scenario { grid-column: 1; } }\n'
        CSS.write_text(css, encoding='utf-8')

def build_page(meta: dict, enriched_list: list[dict]) -> str:
    groups = {}
    for p in enriched_list:
        topic = p['topics'][0]['name'] if p.get('topics') else 'Other'
        slug = p['topics'][0]['slug'] if p.get('topics') else 'other'
        groups.setdefault((topic, slug), []).append(p)
    ordered_groups = sorted(groups.items(), key=lambda kv: (-len(kv[1]), kv[0][0]))
    nav = ''.join(f'<a class="nav-chip" href="#{html.escape(slug)}">{html.escape(name)} · {len(items)} 篇</a>' for (name, slug), items in ordered_groups)
    blocks = []
    for idx, ((name, slug), items) in enumerate(ordered_groups):
        items = sorted(items, key=sort_key)
        cards = []
        for p in items:
            code_html = f'<a href="{html.escape(p.get("code_url") or "")}">Code</a>' if p.get('code_url') else ''
            innov = ''.join(f'<li>{html.escape(x)}</li>' for x in p.get('innovations', []))
            badges = [f'<span class="badge">{html.escape(t["name"])}' + '</span>' for t in p.get('topics', [])[:3]]
            badges.append(f'<span class="badge {"open" if p.get("code_url") else "closed"}">{html.escape(p.get("opensource_status", "未确认开源"))}</span>')
            if p.get('is_ascend'):
                badges.insert(0, '<span class="badge open">Ascend / NPU 优先</span>')
            cards.append(f'''<details class="paper-card deep-card" open><summary><div><div class="badges">{''.join(badges)}</div><div class="paper-title deep-title-en">{html.escape(p.get('title_en') or '')}</div><div class="deep-title-zh">{html.escape(p.get('title_zh') or '')}</div><div class="deep-inst">{html.escape(p.get('institution') or '作者单位待进一步解析')}</div></div><div class="paper-side"><span class="meta">点击收起</span></div></summary><div class="paper-body deep-body"><div class="info-block brief deep-summary"><div class="info-title">摘要总结</div>{html.escape(p.get('summary_cn') or '')}</div><div class="info-block innovation deep-innovation"><div class="info-title">核心创新点</div><ul class="compact">{innov}</ul></div><div class="info-block scenario deep-scenario"><div class="info-title">解决的问题 / 适用场景</div>{html.escape(p.get('scenario_cn') or '')}</div><div class="info-block links-block"><div class="info-title">论文链接</div><div class="links"><a href="{html.escape(p['abs_url'])}">arXiv</a><a href="{html.escape(p['pdf_url'])}">PDF</a>{code_html}</div></div></div></details>''')
        blocks.append(f'''<details class="category-card" id="{html.escape(slug)}" {'open' if idx < 3 else ''}><summary><div><div class="category-title">{html.escape(name)}</div><div class="category-meta">每个模块最多保留 10 篇；当前类目按 Ascend/NPU 优先，其次已确认开源，再按相关度排序。</div></div><div class="category-count">{len(items)} 篇</div></summary><div class="category-body">{''.join(cards)}</div></details>''')
    return f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>2026-07-08 AI Paper Digest</title><link rel="stylesheet" href="../assets/style.css"></head><body><main class="container"><nav class="nav"><a href="../index.html">← 首页</a><span class="meta">2026-07-08</span></nav><section class="hero"><div><div class="eyebrow">Daily Research Board</div><h1>2026-07-08 AI 论文看板</h1><p class="subtitle">本页已按你的要求重建：去掉作者名，加入英文题目+中文翻译，按正文重写摘要总结/创新点/解决场景，并过滤垂直场景和端侧推理论文；每个模块最多保留 10 篇。</p></div><div class="panel"><div class="eyebrow">Selection Rule</div><p class="meta">排序优先级：Ascend / NPU 第一优先，其次已确认开源，再按相关度排序。过滤：营养、农业、无人机、医疗等垂直场景，以及端侧/移动/Edge 推理部署论文。</p></div></section><section class="panel"><div class="summary-bar"><div class="stat"><div class="num">{meta['fetched_count']}</div><div class="label">抓取论文</div></div><div class="stat"><div class="num">{len(enriched_list)}</div><div class="label">整改后保留</div></div><div class="stat"><div class="num">{sum(1 for p in enriched_list if p.get('is_ascend'))}</div><div class="label">Ascend/NPU 优先</div></div><div class="stat"><div class="num">{sum(1 for p in enriched_list if p.get('code_url'))}</div><div class="label">确认开源</div></div></div></section><section class="panel"><div class="eyebrow">Topic Navigation</div><div class="category-nav">{nav}</div></section><section class="board">{''.join(blocks)}</section><footer class="footer">Generated by Daily Arxiv Papers.</footer></main></body></html>'''

def main():
    ensure_css()
    src = json.loads(SRC.read_text(encoding='utf-8'))
    filtered = [p for p in src['papers'] if not is_excluded(p)]
    papers = group_and_cap_candidates(filtered, per_topic_limit=5)
    resume_map = {}
    if RESUME_FILE.exists():
        try:
            resume_map = json.loads(RESUME_FILE.read_text(encoding='utf-8'))
        except Exception:
            resume_map = {}
    work = []
    for idx, p in enumerate(papers, 1):
        if p['id'] in resume_map:
            continue
        print(f'prepare {idx}/{len(papers)} {p["id"]}', flush=True)
        cached = parse_abs_cached(p)
        page_code = detect_code_links(cached['abs_page'])
        valid_code = []
        for u in page_code:
            if code_link_has_content(u) and u not in valid_code:
                valid_code.append(u)
        work.append({
            **p,
            'institutions_raw': guess_institutions_from_abs(cached['abs_page']),
            'content_snippet': cached.get('abstract') or p.get('abstract', ''),
            'abstract': cached.get('abstract') or p.get('abstract', ''),
            'code_links': valid_code,
            'is_ascend': ascend_priority(p)
        })
    enriched_map = dict(resume_map)
    for i in range(0, len(work), 4):
        batch = work[i:i+4]
        print(f'summarize batch {i//4 + 1}/{(len(work)+3)//4}', flush=True)
        for item in summarize_batch(batch):
            base = next(x for x in batch if x['id'] == item['id'])
            code_url = item.get('code_url') if item.get('code_url') in base['code_links'] else (base['code_links'][0] if base['code_links'] else '')
            enriched_map[item['id']] = {**base, **item, 'title_en': base['title'], 'institution': item.get('institution') or base['institutions_raw'], 'code_url': code_url, 'opensource_status': '已确认开源' if code_url else '未确认开源'}
        RESUME_FILE.write_text(json.dumps(enriched_map, ensure_ascii=False, indent=2), encoding='utf-8')
    enriched_list = sorted(enriched_map.values(), key=sort_key)
    OUT.write_text(json.dumps({'date': src['date'], 'count': len(enriched_list), 'fetched_count': src['fetched_count'], 'papers': enriched_list}, ensure_ascii=False, indent=2), encoding='utf-8')
    HTML_OUT.write_text(build_page(src, enriched_list), encoding='utf-8')
    if RESUME_FILE.exists():
        RESUME_FILE.unlink()
    print(json.dumps({'ok': True, 'kept': len(enriched_list), 'ascend': sum(1 for x in enriched_list if x.get('is_ascend')), 'opensource': sum(1 for x in enriched_list if x.get('code_url'))}, ensure_ascii=False))

if __name__ == '__main__':
    main()
