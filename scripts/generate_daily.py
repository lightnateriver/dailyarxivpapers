#!/usr/bin/env python3
"""Generate a lightweight arXiv daily paper radar as static GitHub Pages HTML."""
from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import re
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config" / "topics.yaml"
DOCS = ROOT / "docs"
DAILY = DOCS / "daily"
DATA = DOCS / "data"
STATE = ROOT / "data" / "seen_papers.json"

ARXIV_NS = {"a": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}


def load_config() -> dict:
    try:
        import yaml  # type: ignore
        return yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    except Exception:
        # Small fallback for environments without PyYAML: this project expects PyYAML,
        # but fail loudly with a clear message rather than producing wrong filters.
        raise SystemExit("Missing dependency PyYAML. Install with: python3 -m pip install pyyaml")


def default_date() -> dt.date:
    return dt.date.today() - dt.timedelta(days=1)


def arxiv_query(categories: list[str]) -> str:
    cat_q = " OR ".join(f"cat:{c}" for c in categories)
    return f"({cat_q})"


def fetch_arxiv(config: dict) -> list[dict]:
    fetch_cfg = config.get("fetch", {})
    categories = fetch_cfg.get("arxiv_categories", ["cs.AI", "cs.CL", "cs.LG", "cs.CV"])
    max_results = int(fetch_cfg.get("max_results", 300))
    params = {
        "search_query": arxiv_query(categories),
        "start": 0,
        "max_results": max_results,
        "sortBy": "lastUpdatedDate",
        "sortOrder": "descending",
    }
    url = "https://export.arxiv.org/api/query?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=60) as resp:
        xml = resp.read()
    root = ET.fromstring(xml)
    papers = []
    for entry in root.findall("a:entry", ARXIV_NS):
        arxiv_id_url = entry.findtext("a:id", default="", namespaces=ARXIV_NS)
        arxiv_id = arxiv_id_url.rstrip("/").split("/")[-1]
        title = clean_text(entry.findtext("a:title", default="", namespaces=ARXIV_NS))
        abstract = clean_text(entry.findtext("a:summary", default="", namespaces=ARXIV_NS))
        published = parse_time(entry.findtext("a:published", default="", namespaces=ARXIV_NS))
        updated = parse_time(entry.findtext("a:updated", default="", namespaces=ARXIV_NS))
        authors = [clean_text(a.findtext("a:name", default="", namespaces=ARXIV_NS)) for a in entry.findall("a:author", ARXIV_NS)]
        categories = [c.attrib.get("term", "") for c in entry.findall("a:category", ARXIV_NS)]
        pdf = ""
        for link in entry.findall("a:link", ARXIV_NS):
            if link.attrib.get("title") == "pdf" or link.attrib.get("type") == "application/pdf":
                pdf = link.attrib.get("href", "")
        papers.append({
            "id": arxiv_id,
            "title": title,
            "abstract": abstract,
            "published": published.isoformat() if published else "",
            "updated": updated.isoformat() if updated else "",
            "authors": authors,
            "categories": categories,
            "abs_url": arxiv_id_url,
            "pdf_url": pdf or arxiv_id_url.replace("/abs/", "/pdf/"),
        })
    return papers


def parse_time(s: str) -> dt.datetime | None:
    if not s:
        return None
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))


def clean_text(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def paper_date_matches(paper: dict, target: dt.date) -> bool:
    # arXiv publishes in UTC. For the daily radar, include papers first published or updated on target date.
    for key in ("published", "updated"):
        if paper.get(key):
            try:
                if dt.datetime.fromisoformat(paper[key]).date() == target:
                    return True
            except ValueError:
                pass
    return False


def load_seen() -> dict:
    if STATE.exists():
        return json.loads(STATE.read_text(encoding="utf-8"))
    return {}


def save_seen(seen: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(seen, ensure_ascii=False, indent=2), encoding="utf-8")


def github_search_url(title: str) -> str:
    q = urllib.parse.quote(title + " arxiv github")
    return f"https://github.com/search?q={q}&type=repositories"


def detect_code_links(text: str) -> list[str]:
    urls = re.findall(r"https?://[^\s)\]}>,]+", text)
    return [u for u in urls if "github.com" in u.lower() or "gitlab.com" in u.lower()]


def score_paper(paper: dict, config: dict) -> dict:
    title_abs = f"{paper['title']}\n{paper['abstract']}".lower()
    topics = []
    score = 0.0
    matched = []
    for topic in config.get("topics", []):
        hits = []
        for kw in topic.get("keywords", []):
            if kw.lower() in title_abs:
                hits.append(kw)
        if hits:
            weight = float(topic.get("weight", 1.0))
            topic_score = weight * (2.0 if any(h.lower() in paper["title"].lower() for h in hits) else 1.0)
            topic_score += min(len(hits) * 0.4, 2.0)
            score += topic_score
            topics.append({"name": topic["name"], "slug": topic["slug"], "hits": hits[:6]})
            matched.extend(hits)
    code_links = detect_code_links(paper["abstract"])
    if code_links:
        score += float(config.get("quality", {}).get("open_source_bonus", 2.0))
    # Penalize weak generic surveys if user asked for actionable fresh papers.
    for bad in config.get("quality", {}).get("exclude_keywords", []):
        if bad.lower() in title_abs:
            score -= 1.5
    return {
        **paper,
        "score": round(score, 2),
        "topics": topics,
        "matched_keywords": sorted(set(matched))[:12],
        "code_links": code_links,
        "github_search_url": github_search_url(paper["title"]),
    }


def chinese_brief(p: dict) -> dict:
    title = p["title"]
    topics = "、".join(t["name"] for t in p["topics"][:3]) or "AI"
    hits = "、".join(p.get("matched_keywords", [])[:5])
    abstract = p["abstract"]
    first_sentence = re.split(r"(?<=[.!?])\s+", abstract)[0] if abstract else ""
    return {
        "brief": f"这篇论文与 {topics} 相关，重点信号包括：{hits or '相关方法与系统优化'}。{first_sentence[:260]}",
        "innovation": [
            "从标题和摘要看，论文围绕相关方向提出新的方法、系统设计或评测设置。",
            "第一版页面暂基于 arXiv 元数据自动生成摘要；后续接入 LLM 后会替换为更精确的中文创新点。",
        ],
        "scenario": f"适合关注 {topics} 的研究和工程落地场景，尤其是需要跟踪最新 arXiv 动态时。",
    }


def org_hint(authors: list[str]) -> str:
    # arXiv Atom usually lacks affiliations. Be explicit rather than hallucinating.
    return "arXiv 元数据未提供作者单位，后续可从 PDF 首页补充"


def render_index(reports: list[dict], config: dict) -> None:
    reports = sorted(reports, key=lambda x: x["date"], reverse=True)
    latest = reports[0] if reports else None
    items = "".join(
        f'<li><a href="./daily/{r["date"]}.html">{r["date"]} 论文日报</a><span>{r["count"]} 篇</span></li>'
        for r in reports[:60]
    )
    topics = "".join(f'<span class="topic-chip">{html.escape(t["name"])}</span>' for t in config.get("topics", []))
    latest_html = ""
    if latest:
        latest_html = f'''
        <div class="panel">
          <div class="eyebrow">Latest</div>
          <h2>最新日报：{latest["date"]}</h2>
          <p class="meta">收录 {latest["count"]} 篇相关论文。每天抓取前一天 arXiv 新发布/更新内容，去重后生成。</p>
          <p><a href="./daily/{latest["date"]}.html">查看 {latest["date"]} 日报 →</a></p>
        </div>'''
    content = f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Paper Radar</title><link rel="stylesheet" href="./assets/style.css"></head>
<body><main class="container"><section class="hero"><div class="eyebrow">AI Paper Radar</div><h1>每日 AI 论文雷达</h1><p class="subtitle">浅色扁平化 arXiv 论文日报，关注 LLM 推理加速、多模态推理、Agent、世界模型、视频生成和 AI Infra。</p></section>{latest_html}
<section class="grid"><div class="card"><h3>最近日报</h3><ul class="date-list">{items or '<li>暂无日报</li>'}</ul></div><div class="card"><h3>关注方向</h3><div class="topic-cloud">{topics}</div></div></section><footer class="footer">Generated by Daily Arxiv Papers.</footer></main></body></html>'''
    (DOCS / "index.html").write_text(content, encoding="utf-8")


def render_daily(target: dt.date, selected: list[dict], fetched_count: int) -> dict:
    date_s = target.isoformat()
    DAILY.mkdir(parents=True, exist_ok=True)
    DATA.mkdir(parents=True, exist_ok=True)
    topic_counts: dict[str, int] = {}
    cards = []
    for p in selected:
        for t in p["topics"]:
            topic_counts[t["name"]] = topic_counts.get(t["name"], 0) + 1
        brief = chinese_brief(p)
        badges = "".join(f'<span class="badge">{html.escape(t["name"])}</span>' for t in p["topics"][:4])
        open_badge = '<span class="badge open">发现开源链接</span>' if p["code_links"] else '<span class="badge closed">未发现开源仓库</span>'
        code_links = "".join(f'<a href="{html.escape(u)}">GitHub/Code</a>' for u in p["code_links"])
        if not code_links:
            code_links = f'<a href="{html.escape(p["github_search_url"])}">GitHub 搜索</a>'
        innovations = "".join(f"<li>{html.escape(x)}</li>" for x in brief["innovation"])
        authors = ", ".join(p["authors"][:8]) + (" 等" if len(p["authors"]) > 8 else "")
        cards.append(f'''
        <article class="card">
          <div class="badges">{badges}{open_badge}<span class="badge score">score {p["score"]}</span></div>
          <h2 class="paper-title">{html.escape(p["title"])}</h2>
          <div class="meta"><strong>作者：</strong>{html.escape(authors or 'Unknown')}</div>
          <div class="meta"><strong>作者单位：</strong>{html.escape(org_hint(p["authors"]))}</div>
          <div class="meta"><strong>是否开源：</strong>{'是，发现开源链接' if p["code_links"] else '未发现开源仓库，提供 GitHub 搜索入口'}</div>
          <div class="paper-section"><strong>论文简要</strong>{html.escape(brief["brief"])}</div>
          <div class="paper-section"><strong>核心创新点</strong><ul class="compact">{innovations}</ul></div>
          <div class="paper-section"><strong>解决什么场景的问题</strong>{html.escape(brief["scenario"])}</div>
          <div class="links"><a href="{html.escape(p["abs_url"])}">arXiv</a><a href="{html.escape(p["pdf_url"])}">PDF</a>{code_links}</div>
        </article>''')
    topic_html = "".join(f'<div class="stat"><div class="num">{n}</div><div class="label">{html.escape(k)}</div></div>' for k, n in sorted(topic_counts.items(), key=lambda x: -x[1]))
    content = f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>{date_s} AI Paper Digest</title><link rel="stylesheet" href="../assets/style.css"></head>
<body><main class="container"><nav class="nav"><a href="../index.html">← 首页</a><span class="meta">{date_s}</span></nav><section class="hero"><div class="eyebrow">Daily Digest</div><h1>{date_s} AI 论文日报</h1><p class="subtitle">抓取前一天 arXiv 新发布/更新论文，按相关度、质量信号和开源倾向筛选。第一版摘要基于元数据自动生成，后续可接入 LLM 深度摘要。</p></section>
<section class="panel"><div class="summary-bar"><div class="stat"><div class="num">{fetched_count}</div><div class="label">抓取论文</div></div><div class="stat"><div class="num">{len(selected)}</div><div class="label">入选论文</div></div>{topic_html}</div></section>
<section class="grid">{''.join(cards) if cards else '<div class="card"><h2>今日没有符合条件的新论文</h2><p class="meta">可调整关键词或降低相关度阈值。</p></div>'}</section><footer class="footer">Generated by Daily Arxiv Papers.</footer></main></body></html>'''
    (DAILY / f"{date_s}.html").write_text(content, encoding="utf-8")
    report = {"date": date_s, "count": len(selected), "fetched_count": fetched_count, "papers": selected}
    (DATA / f"{date_s}.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def existing_reports() -> list[dict]:
    reports = []
    if DATA.exists():
        for f in DATA.glob("*.json"):
            try:
                d = json.loads(f.read_text(encoding="utf-8"))
                reports.append({"date": d["date"], "count": d.get("count", len(d.get("papers", [])))})
            except Exception:
                continue
    return reports


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", help="target arXiv date YYYY-MM-DD; default: yesterday")
    ap.add_argument("--ignore-seen", action="store_true", help="include already seen papers, useful for first manual preview")
    args = ap.parse_args()
    target = dt.date.fromisoformat(args.date) if args.date else default_date()
    config = load_config()
    papers = fetch_arxiv(config)
    dated = [p for p in papers if paper_date_matches(p, target)]
    seen = load_seen()
    selected = []
    min_score = float(config.get("quality", {}).get("min_score", 3.0))
    for p in dated:
        if not args.ignore_seen and p["id"] in seen:
            continue
        sp = score_paper(p, config)
        if sp["score"] >= min_score and sp["topics"]:
            selected.append(sp)
            seen[p["id"]] = {"first_seen": target.isoformat(), "title": p["title"]}
    selected.sort(key=lambda x: x["score"], reverse=True)
    report = render_daily(target, selected, len(dated))
    if not args.ignore_seen:
        save_seen(seen)
    render_index(existing_reports(), config)
    print(json.dumps({"date": report["date"], "fetched": len(dated), "selected": len(selected), "daily_html": str(DAILY / f'{target.isoformat()}.html')}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
