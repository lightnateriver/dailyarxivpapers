# Daily Arxiv Papers

Daily Arxiv Papers 是一个面向个人研究跟踪的 **AI 论文雷达**。它会抓取前一天 arXiv 新发布或更新的论文，按照预设关注方向进行相关度筛选，然后生成浅色扁平化风格的 GitHub Pages 静态网页。

当前第一版重点服务以下目标：

- 每天自动跟踪最新 AI 论文。
- 聚焦 LLM 推理加速、多模态推理、Agent、世界模型、视频生成、AI Infra 等方向。
- 页面尽量中文展示，英文论文标题保留原题。
- 每篇论文展示标题、作者、作者单位说明、是否开源、论文简要、核心创新点、解决场景和论文链接。
- 优先展示有 GitHub / 项目页 / 代码仓库的论文。
- 生成 `index.html` 作为首页入口，并跳转到每日子页面。

---

## 目录结构

```text
.
├── AGENTS.md                  # 项目上下文和用户偏好
├── README.md                  # 项目说明
├── config/
│   └── topics.yaml            # 关注方向、关键词、权重和抓取配置
├── scripts/
│   ├── generate_daily.py      # 抓取、筛选、生成 HTML/JSON 的主脚本
│   └── run_daily.sh           # 日常运行入口，后续用于定时任务
├── docs/
│   ├── index.html             # GitHub Pages 首页
│   ├── assets/
│   │   └── style.css          # 浅色扁平化样式
│   ├── daily/
│   │   └── YYYY-MM-DD.html    # 每日论文页面
│   └── data/
│       └── YYYY-MM-DD.json    # 每日结构化数据
└── data/
    └── seen_papers.json       # 已收录论文去重状态，自动生成
```

---

## 当前关注方向

配置文件位于：

```text
config/topics.yaml
```

第一版内置方向：

1. LLM 推理加速
2. 多模态推理加速
3. Agent
4. Agent Reasoning / Test-time Scaling
5. World Model
6. Video Generation
7. AI Infra / Serving Systems
8. RAG / Long Context
9. Code Agent / SWE Agent
10. Model Compression / Quantization

每个方向都有关键词和权重。脚本会根据论文标题和摘要命中情况计算相关度分数。

---

## 页面设计

页面发布目录是 `docs/`，适配 GitHub Pages。

### 首页

```text
docs/index.html
```

首页负责展示：

- 最新日报入口
- 最近日报列表
- 当前关注方向标签

### 每日页面

```text
docs/daily/YYYY-MM-DD.html
```

每日页面负责展示：

- 当天抓取论文数量
- 入选论文数量
- 方向分布
- 论文卡片列表

每篇论文卡片包含：

- 标题
- 作者
- 作者单位说明
- 是否发现开源仓库
- 论文简要
- 核心创新点
- 解决什么场景的问题
- arXiv / PDF / GitHub 搜索或代码链接

---

## 本地运行

进入项目目录：

```bash
cd /root/clawcos/project/dailyarxivpapers
```

生成默认日报，默认日期是“前一天”：

```bash
python3 scripts/generate_daily.py
```

生成指定日期日报：

```bash
python3 scripts/generate_daily.py --date 2026-07-08
```

忽略去重状态，适合预览和调试：

```bash
python3 scripts/generate_daily.py --date 2026-07-08 --ignore-seen
```

运行成功后会生成：

```text
docs/index.html
docs/daily/YYYY-MM-DD.html
docs/data/YYYY-MM-DD.json
```

---

## GitHub Pages 设置

仓库地址：

```text
https://github.com/lightnateriver/dailyarxivpapers
```

建议 GitHub Pages 设置：

```text
Settings → Pages → Deploy from branch → main / docs
```

发布后访问：

```text
https://lightnateriver.github.io/dailyarxivpapers/
```

每日子页面示例：

```text
https://lightnateriver.github.io/dailyarxivpapers/daily/2026-07-08.html
```

---

## 定时任务规划

后续可以用 Hermes cronjob 每天早上 9 点运行：

```bash
cd /root/clawcos/project/dailyarxivpapers
bash scripts/run_daily.sh
```

`run_daily.sh` 会：

1. 生成前一天论文日报。
2. 更新首页索引。
3. 提交本地变更。
4. push 到 GitHub。

注意：当前环境如果没有配置 GitHub 凭据，自动 push 会失败。建议后续配置 SSH key 或安全的 credential helper，而不是长期把 token 写进 remote。

---

## 当前限制

第一版仍有几个限制：

1. **作者单位**  
   arXiv API 默认不提供作者单位。目前页面会明确说明“arXiv 元数据未提供作者单位”。后续可以通过解析 PDF 首页补充。

2. **中文摘要质量**  
   当前摘要基于标题和 abstract 自动生成，是轻量版本。后续可以接入 LLM，对入选论文生成更准确的中文摘要、创新点和应用场景判断。

3. **开源仓库识别**  
   当前只识别 abstract 中显式出现的 GitHub/GitLab 链接。如果没有显式链接，会提供 GitHub 搜索入口。后续可以接 GitHub Search API 或 Papers with Code。

4. **质量过滤**  
   当前主要根据关键词、权重和简单负向词过滤。后续可以增加 LLM 质量判断，过滤概念包装、实验弱或相关性不足的论文。

---

## 后续增强方向

建议逐步增强：

- PDF 首页解析作者单位。
- LLM 生成中文摘要、核心创新点和工程价值判断。
- GitHub Search API 自动发现代码仓库。
- Papers with Code 数据源补充。
- 每周趋势总结。
- 按主题归档页面。
- 前端搜索。
- Hermes 每日 9 点定时任务。
