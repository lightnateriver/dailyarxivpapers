#!/usr/bin/env python3
"""Generate a lightweight arXiv daily paper radar as static GitHub Pages HTML."""
from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import re
import sys
import time
import urllib.error
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


def arxiv_query(categories: list[str], target: dt.date | None = None) -> str:
    cat_q = " OR ".join(f"cat:{c}" for c in categories)
    if target:
        day = target.strftime("%Y%m%d")
        # arXiv API supports submittedDate range. Use it so a daily run does not miss
        # yesterday's papers when newer papers have already pushed them out of the
        # first max_results page sorted by update time.
        return f"submittedDate:[{day}0000 TO {day}2359] AND ({cat_q})"
    return f"({cat_q})"


def fetch_arxiv(config: dict, target: dt.date | None = None) -> list[dict]:
    fetch_cfg = config.get("fetch", {})
    categories = fetch_cfg.get("arxiv_categories", ["cs.AI", "cs.CL", "cs.LG", "cs.CV"])
    per_category = int(fetch_cfg.get("max_results", 120))
    papers_by_id: dict[str, dict] = {}
    for idx, category in enumerate(categories):
        if idx:
            time.sleep(3)
        params = {
            "search_query": arxiv_query([category], target),
            "start": 0,
            "max_results": per_category,
            "sortBy": "submittedDate" if target else "lastUpdatedDate",
            "sortOrder": "descending",
        }
        url = "https://export.arxiv.org/api/query?" + urllib.parse.urlencode(params)
        xml = b""
        for attempt in range(4):
            try:
                with urllib.request.urlopen(url, timeout=60) as resp:
                    xml = resp.read()
                break
            except urllib.error.HTTPError as e:
                if e.code == 429 and attempt < 3:
                    time.sleep(8 * (attempt + 1))
                    continue
                raise
        root = ET.fromstring(xml)
        for entry in root.findall("a:entry", ARXIV_NS):
            arxiv_id_url = entry.findtext("a:id", default="", namespaces=ARXIV_NS)
            arxiv_id = arxiv_id_url.rstrip("/").split("/")[-1]
            title = clean_text(entry.findtext("a:title", default="", namespaces=ARXIV_NS))
            abstract = clean_text(entry.findtext("a:summary", default="", namespaces=ARXIV_NS))
            published = parse_time(entry.findtext("a:published", default="", namespaces=ARXIV_NS))
            updated = parse_time(entry.findtext("a:updated", default="", namespaces=ARXIV_NS))
            authors = [clean_text(a.findtext("a:name", default="", namespaces=ARXIV_NS)) for a in entry.findall("a:author", ARXIV_NS)]
            cats = [c.attrib.get("term", "") for c in entry.findall("a:category", ARXIV_NS)]
            pdf = ""
            for link in entry.findall("a:link", ARXIV_NS):
                if link.attrib.get("title") == "pdf" or link.attrib.get("type") == "application/pdf":
                    pdf = link.attrib.get("href", "")
            papers_by_id[arxiv_id] = {
                "id": arxiv_id,
                "title": title,
                "abstract": abstract,
                "published": published.isoformat() if published else "",
                "updated": updated.isoformat() if updated else "",
                "authors": authors,
                "categories": cats,
                "abs_url": arxiv_id_url,
                "pdf_url": pdf or arxiv_id_url.replace("/abs/", "/pdf/"),
            }
    return list(papers_by_id.values())


def parse_time(s: str) -> dt.datetime | None:
    if not s:
        return None
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))


def clean_text(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


MONTHS = {
    "Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
    "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12,
}


def parse_recent_date(header: str) -> dt.date | None:
    m = re.search(r"(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun),\s+(\d{1,2})\s+(\w{3})\s+(\d{4})", header)
    if not m:
        return None
    return dt.date(int(m.group(3)), MONTHS[m.group(2)], int(m.group(1)))


def strip_tags(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text)
    return html.unescape(clean_text(text))


def parse_recent_block(block: str, target: dt.date) -> list[dict]:
    papers = []
    for item in re.finditer(r"<dt>(.*?)</dt>\s*<dd>(.*?)</dd>", block, re.S):
        dt_html, dd_html = item.group(1), item.group(2)
        id_match = re.search(r'id="(\d{4}\.\d{4,5})"', dt_html)
        if not id_match:
            continue
        arxiv_id = id_match.group(1) + "v1"
        title_match = re.search(r"<div class='list-title mathjax'>\s*<span class='descriptor'>Title:</span>(.*?)</div>", dd_html, re.S)
        authors_match = re.search(r"<div class='list-authors'>(.*?)</div>", dd_html, re.S)
        subjects_match = re.search(r"<div class='list-subjects'>(.*?)</div>", dd_html, re.S)
        abstract_match = re.search(r"<p class='mathjax'>(.*?)</p>", dd_html, re.S)
        comments_match = re.search(r"<div class='list-comments mathjax'>(.*?)</div>", dd_html, re.S)
        authors = []
        if authors_match:
            authors = [strip_tags(a) for a in re.findall(r"<a [^>]*>(.*?)</a>", authors_match.group(1), re.S)]
        subject_text = strip_tags(subjects_match.group(1)) if subjects_match else ""
        cats = re.findall(r"\(([a-z\-]+\.[A-Z]{2})\)", subject_text)
        abstract = strip_tags(abstract_match.group(1)) if abstract_match else ""
        comments = strip_tags(comments_match.group(1)) if comments_match else ""
        if comments:
            abstract = f"{abstract} {comments}"
        bare_id = arxiv_id.removesuffix("v1")
        papers.append({
            "id": arxiv_id,
            "title": strip_tags(title_match.group(1)) if title_match else bare_id,
            "abstract": abstract,
            "published": dt.datetime.combine(target, dt.time(0, 0, tzinfo=dt.timezone.utc)).isoformat(),
            "updated": dt.datetime.combine(target, dt.time(0, 0, tzinfo=dt.timezone.utc)).isoformat(),
            "authors": authors,
            "categories": cats,
            "abs_url": f"https://arxiv.org/abs/{bare_id}",
            "pdf_url": f"https://arxiv.org/pdf/{bare_id}",
        })
    return papers


def fetch_arxiv_recent_html(target: dt.date) -> list[dict]:
    url = "https://arxiv.org/list/cs/recent?skip=0&show=1000"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 dailyarxivpapers"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        page = resp.read().decode("utf-8", errors="ignore")
    headers = list(re.finditer(r"<h3>(.*?)</h3>", page, re.S))
    for i, h in enumerate(headers):
        header = strip_tags(h.group(1))
        if parse_recent_date(header) == target:
            start = h.end()
            end = headers[i + 1].start() if i + 1 < len(headers) else page.find("</dl>", start)
            return parse_recent_block(page[start:end], target)
    return []


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


def normalize_url(url: str) -> str:
    return url.rstrip(".,;:。），)]}")


def detect_code_links(text: str) -> list[str]:
    urls = re.findall(r"https?://[^\s)\]}>,]+", text)
    code_urls = []
    for u in urls:
        cleaned = normalize_url(u)
        if "github.com" in cleaned.lower() or "gitlab.com" in cleaned.lower():
            code_urls.append(cleaned)
    return code_urls


def code_link_has_content(url: str) -> bool:
    url = normalize_url(url)
    parsed = urllib.parse.urlparse(url)
    try:
        if parsed.netloc.lower() == "github.com":
            parts = [p for p in parsed.path.strip("/").split("/") if p]
            if len(parts) < 2:
                return False
            owner, repo = parts[0], parts[1]
            html_url = f"https://github.com/{owner}/{repo}"
            html_req = urllib.request.Request(html_url, headers={"User-Agent": "Mozilla/5.0 dailyarxivpapers-link-check"})
            with urllib.request.urlopen(html_req, timeout=25) as html_resp:
                body = html_resp.read(800000).decode("utf-8", errors="ignore")
            if "This repository is empty" in body:
                return False
            if re.search(rf'href="/{re.escape(owner)}/{re.escape(repo)}/(tree|blob)/', body):
                return True
            api = f"https://api.github.com/repos/{owner}/{repo}"
            req = urllib.request.Request(api, headers={"User-Agent": "dailyarxivpapers-link-check"})
            with urllib.request.urlopen(req, timeout=20) as resp:
                meta = json.loads(resp.read().decode("utf-8"))
            return int(meta.get("size") or 0) > 0
        req = urllib.request.Request(url, headers={"User-Agent": "dailyarxivpapers-link-check"})
        with urllib.request.urlopen(req, timeout=20) as resp:
            return 200 <= resp.status < 400
    except Exception:
        return False


def keep_valid_code_links(papers: list[dict]) -> None:
    cache: dict[str, bool] = {}
    for paper in papers:
        valid = []
        for url in paper.get("code_links", []):
            url = normalize_url(url)
            if url not in cache:
                cache[url] = code_link_has_content(url)
            if cache[url]:
                valid.append(url)
        paper["code_links"] = valid


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
<body><main class="container"><section class="hero"><div class="eyebrow">AI Paper Radar</div><h1>每日AI 论文</h1><p class="subtitle">浅色扁平化 arXiv 论文日报，关注 LLM 推理加速、多模态推理、Agent、世界模型、视频生成和 AI Infra。</p></section>{latest_html}
<section class="grid"><div class="card"><h3>最近日报</h3><ul class="date-list">{items or '<li>暂无日报</li>'}</ul></div><div class="card"><h3>关注方向</h3><div class="topic-cloud">{topics}</div></div></section><footer class="footer">Generated by Daily Arxiv Papers.</footer></main></body></html>'''
    (DOCS / "index.html").write_text(content, encoding="utf-8")


def primary_topic(p: dict) -> dict:
    return p["topics"][0] if p.get("topics") else {"name": "Other", "slug": "other", "hits": []}


def render_daily(target: dt.date, selected: list[dict], fetched_count: int) -> dict:
    date_s = target.isoformat()
    DAILY.mkdir(parents=True, exist_ok=True)
    DATA.mkdir(parents=True, exist_ok=True)

    grouped: dict[str, dict] = {}
    for p in selected:
        topic = primary_topic(p)
        name = topic["name"]
        if name not in grouped:
            grouped[name] = {"slug": topic.get("slug", "other"), "name": name, "papers": [], "keywords": []}
        grouped[name]["papers"].append(p)
        grouped[name]["keywords"].extend(topic.get("hits", []))

    groups = sorted(grouped.values(), key=lambda g: len(g["papers"]), reverse=True)
    open_count = sum(1 for p in selected if p.get("code_links"))
    nav_html = "".join(
        f'<a class="nav-chip" href="#{html.escape(g["slug"])}">{html.escape(g["name"])} · {len(g["papers"])} 篇</a>'
        for g in groups
    )

    category_html = []
    for idx, group in enumerate(groups):
        papers = sorted(group["papers"], key=lambda p: (bool(p.get("code_links")), p["score"]), reverse=True)
        top_title = papers[0]["title"] if papers else ""
        keyword_preview = " / ".join(sorted(set(group["keywords"]))[:6]) or "相关关键词"
        paper_items = []
        for p in papers:
            brief = chinese_brief(p)
            topic_badges = "".join(f'<span class="badge">{html.escape(t["name"])}</span>' for t in p["topics"][:4])
            open_badge = '<span class="badge open">Code 已确认</span>' if p["code_links"] else '<span class="badge closed">开源未确认</span>'
            innovations = "".join(f"<li>{html.escape(x)}</li>" for x in brief["innovation"])
            authors = ", ".join(p["authors"][:6]) + (" 等" if len(p["authors"]) > 6 else "")
            code_links = "".join(f'<a href="{html.escape(u)}">Code</a>' for u in p["code_links"])
            links = f'<a href="{html.escape(p["abs_url"])}">arXiv</a><a href="{html.escape(p["pdf_url"])}">PDF</a>{code_links}'
            paper_items.append(f'''
            <details class="paper-card">
              <summary>
                <div>
                  <div class="badges">{topic_badges}{open_badge}</div>
                  <div class="paper-title">{html.escape(p["title"])}</div>
                  <div class="meta"><strong>作者：</strong>{html.escape(authors or 'Unknown')}</div>
                  <div class="paper-preview">{html.escape(brief["brief"][:180])}...</div>
                </div>
                <div class="paper-side">
                  <span class="badge score">score {p["score"]}</span>
                  <span class="meta">点击展开</span>
                </div>
              </summary>
              <div class="paper-body">
                <div class="info-block brief"><div class="info-title">论文简要</div>{html.escape(brief["brief"])}</div>
                <div class="info-block innovation"><div class="info-title">核心创新点</div><ul class="compact">{innovations}</ul></div>
                <div class="info-block scenario"><div class="info-title">解决场景</div>{html.escape(brief["scenario"])}</div>
                <div class="info-block"><div class="info-title">作者单位</div>{html.escape(org_hint(p["authors"]))}</div>
                <div class="info-block"><div class="info-title">开源状态</div>{'已在 arXiv 元数据中发现真实代码链接。' if p["code_links"] else '未在 arXiv 摘要/元数据中确认开源仓库，因此不展示代码入口。'}</div>
                <div class="info-block"><div class="info-title">命中关键词</div>{html.escape('、'.join(p.get("matched_keywords", [])[:8]) or '无')}</div>
                <div class="info-block links-block"><div class="info-title">论文链接</div><div class="links">{links}</div></div>
              </div>
            </details>''')
        category_html.append(f'''
        <details class="category-card" id="{html.escape(group["slug"])}" {'open' if idx < 3 else ''}>
          <summary>
            <div>
              <div class="category-title">{html.escape(group["name"])}</div>
              <div class="category-meta">关键词：{html.escape(keyword_preview)}</div>
              <div class="category-meta">类目最高分论文：{html.escape(top_title)}</div>
            </div>
            <div class="category-count">{len(papers)} 篇</div>
          </summary>
          <div class="category-body">{''.join(paper_items)}</div>
        </details>''')

    content = f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>{date_s} AI Paper Digest</title><link rel="stylesheet" href="../assets/style.css"></head>
<body><main class="container"><nav class="nav"><a href="../index.html">← 首页</a><span class="meta">{date_s}</span></nav>
<section class="hero"><div><div class="eyebrow">Daily Research Board</div><h1>{date_s} AI 论文看板</h1><p class="subtitle">按研究方向聚合的 arXiv 日报。类目卡片可收缩，论文卡片点击后展开详情；只有确认存在真实代码链接时才展示 Code。</p></div><div class="panel"><div class="eyebrow">Design Spec</div><p class="meta">Aesthetic: Editorial / magazine. Palette: warm paper, teal accent, amber notes. Layout: asymmetric hero + collapsible research board.</p></div></section>
<section class="panel"><div class="summary-bar"><div class="stat"><div class="num">{fetched_count}</div><div class="label">抓取论文</div></div><div class="stat"><div class="num">{len(selected)}</div><div class="label">入选论文</div></div><div class="stat"><div class="num">{len(groups)}</div><div class="label">覆盖方向</div></div><div class="stat"><div class="num">{open_count}</div><div class="label">确认开源</div></div></div></section>
<section class="panel"><div class="eyebrow">Topic Navigation</div><div class="category-nav">{nav_html or '<span class="meta">暂无类目</span>'}</div></section>
<section class="board">{''.join(category_html) if category_html else '<div class="card"><h2>今日没有符合条件的新论文</h2><p class="meta">可调整关键词或降低相关度阈值。</p></div>'}</section>
<footer class="footer">Generated by Daily Arxiv Papers. No unverified GitHub search links are shown.</footer></main></body></html>'''
    (DAILY / f"{date_s}.html").write_text(content, encoding="utf-8")
    report = {"date": date_s, "count": len(selected), "fetched_count": fetched_count, "open_source_count": open_count, "topics": [{"name": g["name"], "slug": g["slug"], "count": len(g["papers"])} for g in groups], "papers": selected}
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
    papers = fetch_arxiv_recent_html(target)
    if not papers:
        papers = fetch_arxiv(config, target)
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
    keep_valid_code_links(selected)
    report = render_daily(target, selected, len(dated))
    if not args.ignore_seen:
        save_seen(seen)
    render_index(existing_reports(), config)
    print(json.dumps({"date": report["date"], "fetched": len(dated), "selected": len(selected), "daily_html": str(DAILY / f'{target.isoformat()}.html')}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
