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
              <div class="paper-title">{html.escape(p['id'])} · {html.escape(p['institution'])}</div>
              <div class="paper-preview"><strong>{html.escape(p['summary_cn'])}</strong></div>
            </div>
            <div class="paper-side"><span class="meta">点击收起</span></div>
          </summary>
          <div class="paper-body deep-body">
            <div class="info-block brief"><div class="info-title">摘要总结</div>{html.escape(p['summary_cn'])}</div>
            <div class="info-block innovation"><div class="info-title">核心创新点</div><ul class="compact">{innovations}</ul></div>
            <div class="info-block scenario"><div class="info-title">解决的问题 / 适用场景</div>{html.escape(p['scenario_cn'])}</div>
            <div class="info-block"><div class="info-title">作者单位</div>{html.escape(p['institution'])}</div>
            <div class="info-block links-block"><div class="info-title">论文链接</div><div class="links"><a href="https://arxiv.org/abs/{html.escape(p['id'].split('v')[0])}">arXiv</a><a href="https://arxiv.org/pdf/{html.escape(p['id'].split('v')[0])}">PDF</a>{code_html}</div></div>
          </div>
        </details>''')
    return f'''
<section class="panel deep-read-panel">
  <div class="eyebrow">Deep Read Preview</div>
  <h2 class="section-title">今日精读版卡片（首批 10 篇）</h2>
  <p class="subtitle">这部分不再展示作者姓名，改为作者单位；摘要总结、核心创新点和解决场景均基于论文正文/摘要片段重新整理。你先看这 10 篇的效果，如果满意，我再把前两天页面全部按同样标准重做。</p>
  <div class="board">{''.join(items)}</div>
</section>
'''

def ensure_css():
    css = CSS.read_text(encoding='utf-8')
    if '.deep-read-panel' in css:
        return
    css += '''
.section-title { font-family: "Noto Serif SC", "Source Han Serif SC", serif; font-size: 32px; margin: 10px 0 14px; letter-spacing: -0.03em; }
.deep-read-panel { margin-top: 18px; }
.deep-card { background: #fffdf8; border: 1px solid var(--line); }
.deep-body { grid-template-columns: repeat(2, minmax(0, 1fr)); }
@media (max-width: 800px) { .deep-body { grid-template-columns: 1fr; } }
'''
    CSS.write_text(css, encoding='utf-8')


def main():
    ensure_css()
    page = HTML.read_text(encoding='utf-8')
    data = json.loads(ENRICHED.read_text(encoding='utf-8'))
    section = build_section(data)
    marker = '<section class="board">'
    if 'Deep Read Preview' in page:
        start = page.index('<section class="panel deep-read-panel">')
        end = page.index('<section class="board">', start)
        page = page[:start] + section + page[end:]
    else:
        page = page.replace(marker, section + marker, 1)
    HTML.write_text(page, encoding='utf-8')
    print('patched html')

if __name__ == '__main__':
    main()
