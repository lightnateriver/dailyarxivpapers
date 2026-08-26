#!/usr/bin/env python3
"""Quality gate for generated daily paper pages.

Rejects a daily page before commit/push when summaries are empty, English-only,
placeholder-like, or duplicated across fields/papers.
"""
import argparse
import json
import re
from collections import Counter
from difflib import SequenceMatcher
from pathlib import Path

BAD_PHRASES = (
    'comments:', 'accepted by', 'accepted for', '见正文', '论文标题：',
    '无法根据摘要', '未提供论文摘要',
)


def compact(text: object) -> str:
    return re.sub(r'\s+', '', str(text or '')).strip()


def chinese_count(text: str) -> int:
    return sum('\u4e00' <= c <= '\u9fff' for c in text)


def validate(data_path: Path, html_path: Path) -> dict:
    data = json.loads(data_path.read_text(encoding='utf-8'))
    html = html_path.read_text(encoding='utf-8')
    papers = data.get('papers') or []
    issues = []
    summaries = []

    for paper in papers:
        pid = paper.get('id', 'unknown')
        summary = compact(paper.get('summary_cn'))
        scenario = compact(paper.get('scenario_cn'))
        innovations = paper.get('innovations') or []
        if isinstance(innovations, str):
            innovation_items = [x.strip() for x in innovations.splitlines() if x.strip()]
        else:
            innovation_items = [str(x).strip() for x in innovations if str(x).strip()]
        innovation_text = compact(' '.join(innovation_items))
        combined = (summary + scenario + innovation_text).lower()
        reasons = []

        if len(summary) < 40 or chinese_count(summary) < 8:
            reasons.append('summary_empty_short_or_non_chinese')
        if len(scenario) < 30 or chinese_count(scenario) < 6:
            reasons.append('scenario_empty_short_or_non_chinese')
        if len(innovation_items) < 2 or len(innovation_text) < 30 or chinese_count(innovation_text) < 6:
            reasons.append('innovations_insufficient')
        if any(x in combined for x in BAD_PHRASES):
            reasons.append('placeholder_or_comment_text')
        if summary and scenario and SequenceMatcher(None, summary, scenario).ratio() > 0.72:
            reasons.append('summary_scenario_too_similar')
        if summary and innovation_text and SequenceMatcher(None, summary, innovation_text).ratio() > 0.72:
            reasons.append('summary_innovation_too_similar')
        if reasons:
            issues.append({'id': pid, 'reasons': reasons})
        summaries.append(summary)

    duplicate_summaries = [s for s, n in Counter(summaries).items() if s and n > 1]
    checks = {
        'non_empty_papers': len(papers) > 0,
        'count_matches': data.get('count') == len(papers),
        'no_paper_quality_issues': not issues,
        'no_cross_paper_duplicate_summaries': not duplicate_summaries,
        'card_count_matches': html.count('class="paper-card deep-card"') == len(papers),
        'feedback_controls_present': all(x in html for x in ('偏好反馈', '喜欢', '不喜欢', '生成反馈总结')),
    }
    return {
        'ok': all(checks.values()),
        'checks': checks,
        'paper_count': len(papers),
        'issues': issues[:20],
        'duplicate_summary_count': len(duplicate_summaries),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--date', required=True)
    ap.add_argument('--root', default='.')
    args = ap.parse_args()
    root = Path(args.root)
    result = validate(
        root / f'docs/data/{args.date}.full_enriched.json',
        root / f'docs/daily/{args.date}.html',
    )
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
