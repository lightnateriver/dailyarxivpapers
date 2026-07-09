# Daily Arxiv Papers

浅色扁平化 AI 论文雷达。每天抓取前一天 arXiv 新发布/更新论文，按用户关注方向筛选，生成 GitHub Pages 静态页面。

## 用户偏好

- 输出语言：尽量中文；英文论文标题保留原题。
- 关注方向：LLM 推理加速、多模态推理加速、Agent、Agent Reasoning/Test-time Scaling、World Model、Video Generation、AI Infra/Serving Systems、RAG/Long Context、Code Agent/SWE Agent、Model Compression/Quantization。
- 收录策略：不限制篇数；相关度高、质量过关都收录。
- 质量策略：不需要机构白/黑名单；但过滤明显概念包装、实验弱、相关性低的“小作坊感”内容。
- 开源优先：有 GitHub/项目页/代码仓库的论文加权，并在页面明确展示。

## 运行

```bash
python3 scripts/generate_daily.py --date YYYY-MM-DD
```

不传 `--date` 时默认生成“前一天”的日报。

## GitHub Pages

发布目录使用 `docs/`：

- `docs/index.html` 首页
- `docs/daily/YYYY-MM-DD.html` 每日页面
- `docs/data/YYYY-MM-DD.json` 当日结构化数据
