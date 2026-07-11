#!/usr/bin/env python3
from __future__ import annotations
import json, re, subprocess, urllib.request, html as ihtml
from pathlib import Path
import fitz

ROOT = Path('/root/clawcos/project/dailyarxivpapers')
DATA = ROOT / 'docs/data/2026-07-10.json'
OUT = ROOT / 'docs/data/2026-07-10.enriched.json'
TARGET_IDS = {
    '2607.08691v1', '2607.08215v1', '2607.08116v1', '2607.08027v1',
    '2607.08565v1', '2607.08010v1', '2607.08423v1', '2607.08029v1',
    '2607.08093v1', '2607.08057v1', '2607.08374v1', '2607.08214v1'
}
INSTITUTION_HINTS = [
    'University', 'Institute', 'Lab', 'Laboratory', 'School', 'College', 'Academy', 'Center', 'Centre',
    'Google', 'Meta', 'Microsoft', 'OpenAI', 'Anthropic', 'NVIDIA', 'Huawei', 'Alibaba', 'Tencent',
    'ByteDance', 'Amazon', 'Apple', 'CMU', 'MIT', 'Stanford', 'Berkeley', 'Tsinghua', 'Peking', 'UC '
]

def clean(s: str) -> str:
    return re.sub(r'\s+', ' ', s or '').strip()

def strip_tags(s: str) -> str:
    return clean(ihtml.unescape(re.sub(r'<[^>]+>', ' ', s)))

def fetch(url: str, timeout: int = 60) -> str:
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 dailyarxivpapers'})
    return urllib.request.urlopen(req, timeout=timeout).read().decode('utf-8', errors='ignore')

def extract_code_from_html(page: str) -> list[str]:
    urls = []
    for u in re.findall(r'https?://[^\s"\'\)<>]+', page):
        u = u.rstrip('.,;:。)]}')
        if 'github.com' in u.lower() or 'gitlab.com' in u.lower():
            urls.append(u)
    seen = set(); out = []
    for u in urls:
        if u not in seen:
            seen.add(u); out.append(u)
    return out

def parse_abs_page(abs_url: str) -> tuple[str, str | None, list[str]]:
    page = fetch(abs_url)
    html_link = None
    m = re.search(r'https://arxiv.org/html/[^"\']+', page)
    if m:
        html_link = m.group(0)
    return page, html_link, extract_code_from_html(page)

def extract_html_content(html_url: str) -> str:
    page = fetch(html_url, timeout=90)
    return strip_tags(page)[:22000]

def extract_pdf_content(pdf_url: str) -> str:
    raw = urllib.request.urlopen(pdf_url, timeout=90).read()
    doc = fitz.open(stream=raw, filetype='pdf')
    texts = []
    for i in range(min(2, len(doc))):
        texts.append(doc[i].get_text('text'))
    return clean('\n'.join(texts))[:18000]

def guess_institutions(content: str) -> str:
    lines = [clean(x) for x in content.splitlines() if clean(x)]
    kept = []
    for line in lines[:30]:
        if '@' in line:
            continue
        if any(h in line for h in INSTITUTION_HINTS):
            kept.append(line)
    if not kept:
        return '作者单位待进一步解析'
    out = []
    for line in kept:
        if line not in out:
            out.append(line)
    return ' / '.join(out[:4])

def run_batch(batch: list[dict]) -> list[dict]:
    payload = []
    for item in batch:
        payload.append({
            'id': item['id'],
            'title': item['title'],
            'institutions_raw': item['institutions_raw'],
            'abstract': item['abstract'],
            'content_snippet': item['content_snippet'][:6000],
            'code_links': item['code_links'],
            'topics': [t['name'] for t in item.get('topics', [])],
        })
    prompt = (
        '你是论文阅读助手。请基于我提供的论文正文/摘要片段，严格输出 JSON 数组，不要输出任何额外文字。\n'
        '每个对象字段固定为：id, institution, summary_cn, innovations, scenario_cn, opensource_status, code_url。\n'
        '要求：\n'
        '1. summary_cn 用 2-4 句中文总结这篇论文具体做什么，尽量具体。\n'
        '2. innovations 是 2-4 条中文列表，必须来自给定内容，不能写套话。\n'
        '3. scenario_cn 用中文说明它解决什么问题、在哪种工程/研究场景下有用。\n'
        '4. institution 优先整理 institutions_raw；如果 raw 已经足够，不要臆造其他机构。\n'
        '5. opensource_status 只能写：已确认开源 / 未确认开源。\n'
        '6. code_url 若没有确认开源则写空字符串。\n'
        '7. 不要输出作者姓名。\n\n'
        f'输入数据：\n{json.dumps(payload, ensure_ascii=False)}'
    )
    out = subprocess.check_output(['hermes', '-z', prompt], text=True, cwd=str(ROOT), timeout=240)
    text = out.strip()
    text = re.sub(r'^```json\s*|```$', '', text, flags=re.S).strip()
    return json.loads(text)

def main():
    data = json.loads(DATA.read_text(encoding='utf-8'))
    papers = [p for p in data['papers'] if p['id'] in TARGET_IDS]
    work = []
    for idx, p in enumerate(papers):
        print(f'prepare {idx+1}/{len(papers)} {p["id"]}', flush=True)
        abs_page, html_link, page_code = parse_abs_page(p['abs_url'])
        content = ''
        if html_link:
            try:
                content = extract_html_content(html_link)
            except Exception:
                content = ''
        if not content:
            try:
                content = extract_pdf_content(p['pdf_url'])
            except Exception:
                content = p.get('abstract', '')
        work.append({**p, 'institutions_raw': guess_institutions(content), 'content_snippet': content, 'code_links': page_code or p.get('code_links', [])})
    enriched = {}
    for i in range(0, len(work), 4):
        batch = work[i:i+4]
        print(f'summarize batch {i//4 + 1}', flush=True)
        for item in run_batch(batch):
            enriched[item['id']] = item
    OUT.write_text(json.dumps({'date': data['date'], 'papers': enriched}, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'ok': True, 'papers': len(enriched), 'out': str(OUT)}, ensure_ascii=False))

if __name__ == '__main__':
    main()
