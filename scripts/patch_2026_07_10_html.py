#!/usr/bin/env python3
from __future__ import annotations
import json, html
from pathlib import Path

ROOT = Path('/root/clawcos/project/dailyarxivpapers')
HTML = ROOT / 'docs/daily/2026-07-10.html'
ENRICHED = ROOT / 'docs/data/2026-07-10.enriched.json'
CSS = ROOT / 'docs/assets/style.css'

def build_section(data: dict) -> str:
    items = []
    for pid, p in data['papers'].items():
        code_html = f'<a href="{html.escape(p.get("code_url") or "")}">Code</a>' if p.get('code_url') else ''
        innovations = ''.join(f'<li>{html.escape(x)}</li>' for x in p.get('innovations', []))
        items.append(f'''
        <details class="paper-card deep-card" open>
          <summary>
            <div>
              <div class="badges"><span class="badge">精读版</span><span class="badge {'open' if p.get('code_url') else 'closed'}">{html.escape(p.get('opensource_status','未确认开源'))}</span></div>
              <div class="paper-title deep-title-en">{html.escape(p.get('title_en') or '')}</div>
              <div class="deep-title-zh">{html.escape(p.get('title_zh') or '')}</div>
              <div class="deep-inst">{html.escape(p['institution'])}</div>
            </div>
            <div class="paper-side"><span class="meta">点击收起</span></div>
          </summary>
          <div class="paper-body deep-body">
            <div class="info-block brief deep-summary"><div class="info-title">摘要总结</div>{html.escape(p['summary_cn'])}</div>
            <div class="info-block innovation deep-innovation"><div class="info-title">核心创新点</div><ul class="compact">{innovations}</ul></div>
            <div class="info-block scenario deep-scenario"><div class="info-title">解决的问题 / 适用场景</div>{html.escape(p['scenario_cn'])}</div>
            <div class="info-block links-block"><div class="info-title">论文链接</div><div class="links"><a href="https://arxiv.org/abs/{html.escape(p['id'].split('v')[0])}">arXiv</a><a href="https://arxiv.org/pdf/{html.escape(p['id'].split('v')[0])}">PDF</a>{code_html}</div></div>
          </div>
        </details>''')
    return f'''
<section class="panel deep-read-panel">
  <div class="eyebrow">Deep Read Preview</div>
  <h2 class="section-title">今日精读版卡片（首批 10 篇）</h2>
  <p class="subtitle">标题改为“英文原题 + 中文翻译”，作者单位降级为小字信息；卡片内容只保留你真正关心的三块：摘要总结、核心创新点、解决的问题 / 适用场景。</p>
  <div class="board">{''.join(items)}</div>
</section>
'''

def ensure_css():
    css = CSS.read_text(encoding='utf-8')
    # replace/append block conservatively
    add = '''
.section-title { font-family: "Noto Serif SC", "Source Han Serif SC", serif; font-size: 32px; margin: 10px 0 14px; letter-spacing: -0.03em; }
.deep-read-panel { margin-top: 18px; }
.deep-card { background: #fffdf8; border: 1px solid var(--line); }
.deep-title-en { font-size: 22px; line-height: 1.35; margin-top: 8px; }
.deep-title-zh { font-size: 15px; color: var(--teal); margin-top: 6px; font-weight: 700; }
.deep-inst { font-size: 12px; color: var(--muted); margin-top: 8px; }
.deep-body { grid-template-columns: 1fr 1fr; }
.deep-summary { grid-column: 1; }
.deep-innovation { grid-column: 2; }
.deep-scenario { grid-column: 1 / -1; }
@media (max-width: 800px) {
  .deep-body { grid-template-columns: 1fr; }
  .deep-summary, .deep-innovation, .deep-scenario { grid-column: 1; }
}
'''
    # remove previous deep block if duplicated minimally by marker
    if '.deep-title-en' not in css:
        css += add
        CSS.write_text(css, encoding='utf-8')

def main():
    ensure_css()
    page = HTML.read_text(encoding='utf-8')
    data = json.loads(ENRICHED.read_text(encoding='utf-8'))
    section = build_section(data)
    if 'Deep Read Preview' in page:
        start = page.index('<section class="panel deep-read-panel">')
        end = page.index('<section class="board">', start)
        page = page[:start] + section + page[end:]
    else:
        page = page.replace('<section class="board">', section + '<section class="board">', 1)
    HTML.write_text(page, encoding='utf-8')
    print('patched html v2')

if __name__ == '__main__':
    main()
