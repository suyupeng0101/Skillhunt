# GitHub Skill / Agent Radar 技术架构设计文档

**版本**：v1.0  
**基于 PRD**：`github_radar_prd.md` v1.0  
**编写时间**：2026-07-01  
**目标**：将 GitHub Skill / Agent 开源项目雷达从产品需求拆解为可开发、可运行、可复用、可按需安装的 AI 辅助雷达管道与 Agent Skill 交付架构。

---

## 1. 设计目标

第一版目标不是构建完整数据平台，也不是构建完整自主智能体，而是跑通一个低复杂度、可每日更新、可验证、可被 Agent 消费的 GitHub Skill/Agent Radar。

核心目标：

1. **单脚本闭环**：一个 `src/main.py` 完成采集、AI 分析、评分、派生数据生成和 JSON 导出。
2. **无数据库依赖**：第一版不使用 SQLite，不建历史表，只输出 `data/*.json` 和 `docs/data/*.json`。
3. **简单评分**：只用 GitHub 基础信号和 AI 可用性判断，不接入 npm/PyPI/Docker 下载量。
4. **静态展示**：GitHub Pages 优先读取 `brief.json`、`radar.json` 和 `status.json`，先用原生搜索，不引入复杂前端。
5. **派生简报**：额外生成 `brief.json` 给页面首屏和 Agent 快速消费。
6. **低摩擦 Skill**：用户只安装 `github-radar` 一个主 skill，通过 `collect-only`、`sync` 或读取公开 JSON 的自然语言请求使用。
7. **可逐步升级**：缓存、SQLite、趋势历史、Fuse.js、多来源下载量放到第二版。

### 1.1 工程原则

本项目只保留适合 GitHub 项目雷达的轻量工程形态：

- **保留**：GitHub Actions 定时生成数据、GitHub Pages 静态展示、`data/*.json` 作为事实源、派生 brief/status 文件、Skill 作为 Agent 消费和维护入口。
- **调整**：新闻项目里的“信源”“故事线”“24 小时窗口”替换为 GitHub 仓库、Skill/Agent 双榜、可用性/使用度/维护活跃评分。
- **不照搬**：不引入新闻事件聚类、多源故事线合并、社交媒体/邮箱信源抓取、付费内容源预算控制。

对应的产品路径：

```text
普通用户看榜单
        |
        v
Agent 读取 JSON 生成项目简报
        |
        v
开发者 fork 后自建雷达
```

第一版的 `category` 采用统一的业务场景分类，而不是按技术形态拆 Skill/Agent 子类。推荐分类包括：

- 学习
- 信息搜集
- 知识管理
- 内容创作
- 视频处理
- 办公协作
- 数据分析
- 投资研究
- 软件开发
- 产品设计
- 市场营销
- 安全攻防
- 自动化运营
- 其他

---

## 2. 简化设计原则

### 2.1 先跑通，再优化

第一版优先完成可运行闭环，不提前引入复杂状态管理：

- 可以全量重算 300-500 个候选项目。
- 可以不保存 AI 原始事件表。
- 可以不维护历史趋势。
- 可以不做多来源下载量采集。

当数据量、成本或功能明确需要时，再引入缓存和数据库。

### 2.2 确定性代码优先，大模型只做语义判断

确定性代码负责：

- GitHub 搜索、去重、候选规则过滤。
- README 拉取和截断。
- 简单评分计算。
- `brief.json` 和 `status.json` 派生。
- JSON 导出。

配置的模型只负责：

- 判断 `kind` 是 `Skill` 还是 `Agent`。
- 选择 `category`。
- 生成 `summary`、`use_case`、`solves`。
- 判断是否有安装入口和可用性风险。

### 2.3 文件即状态

第一版维护主数据和派生数据两类文件：

```text
data/collected_repos.json
  collect-only 模式输出，供调试候选集。

data/radar.json
  sync 完整结果，供调试、复用和后续导入数据库。

data/run-report.json
  本轮运行报告，记录 query 命中、失败、fallback 和 warning。

docs/data/radar.json
  前端展示数据，通常由 data/radar.json 精简/排序后复制得到。

docs/data/brief.json
  从 radar.json 派生的精选摘要，供页面首屏和 Agent 快速消费。

docs/data/metadata.json
  同步时间、项目数量、版本号。

docs/data/status.json
  页面和 Agent 可读的本轮运行状态。
```

其中 `radar.json` 是主事实源，`brief.json` 和 `status.json` 必须可以从主事实源和本轮运行日志重新生成。若派生文件缺失，页面和 Skill 回退读取 `radar.json`。

可选第二版再增加：

```text
data/cache.json      # content_hash -> AI 分析结果
data/radar.db        # SQLite 长期状态
data/history.json    # 趋势历史
```

### 2.4 Skill 保持一个入口

`github-radar` 只有一个用户可见 skill。内部可以拆 Python 函数，但不要让用户安装多个能力包。

第一版的主 skill 同时覆盖两类用法：

- **消费侧**：读取公开 `docs/data/brief.json` 和 `docs/data/radar.json`，生成项目简报、选型建议或候选清单。
- **维护侧**：在 fork 仓库后运行 `collect-only` 或 `sync`，维护采集、分析、评分、导出流程。

---

## 3. 简化总体架构

### 3.1 MVP 架构

```text
GitHub Actions / 本地 CLI
        |
        v
python src/main.py
        |
        +-- 读取 config/queries.yaml
        +-- GitHub API 搜索候选仓库
        +-- 去重 + 候选规则过滤
        +-- 拉取 README 前 3000-4000 字符
        +-- 调用配置的模型批量分类和可用性判断
        +-- 计算简单 recommendation_score
        +-- 生成 brief/status 派生数据
        +-- 导出 data/*.json + docs/data/*.json
        |
        v
GitHub Pages 读取静态 JSON
        |
        v
Agent Skill 读取公开 JSON
```

### 3.2 MVP 数据流

```text
queries.yaml
    |
    v
GitHub Search API
    | RepoCandidate[]
    v
去重 + 候选过滤
    | CandidateRepo[]
    v
README 截断
    | RepoForAI[]
    v
模型批量分析
    | AiRepo[]
    v
简单评分
    | RadarRepo[]
    v
JSON 导出
    +-- radar.json
    +-- brief.json
    +-- status.json
```

### 3.3 第二版再引入的能力

以下能力暂不进入 MVP：

- SQLite。
- `repos_history` 趋势表。
- `runs`、`ai_analysis_events` 审计表。
- npm/PyPI/Docker 下载量。
- GitHub dependents。
- 复杂增量重跑。
- Fuse.js 高级搜索。
- 完整自主智能体的长期记忆、自主规划和自我修复。

---

## 4. 核心脚本设计

### 4.1 `src/main.py`

第一版只需要一个入口脚本，后续再按需要拆模块。

职责：

1. 加载配置。
2. 搜索 GitHub 仓库。
3. 去重并生成 `candidate_reason`。
4. 拉取 README snippet。
5. 调用配置的模型。
6. 计算评分。
7. 生成 `brief.json` 和 `status.json`。
8. 排序并导出 JSON。

推荐命令：

```bash
python src/main.py sync
python src/main.py collect-only
```

### 4.2 最小函数拆分

不需要一开始创建复杂包结构，建议先在一个文件内保持清晰函数：

```python
load_config()
build_queries()
search_repos()
fetch_readme_snippet()
analyze_with_model()
score_repo()
build_brief()
build_status()
export_json()
main()
```

当单文件超过 500-700 行，再拆成：

```text
src/collector.py
src/analyzer.py
src/scorer.py
src/exporter.py
```

### 4.3 简化运行模式

| 模式 | 作用 | 是否需要模型 |
| --- | --- | --- |
| `collect-only` | 只采集候选仓库，输出 `data/collected_repos.json` | 否 |
| `sync` | 采集、AI 分析、评分、导出 | 是 |
| 读取公开 JSON | Skill 消费 `docs/data/brief.json` 和 `docs/data/radar.json`，输出自然语言简报 | 否 |

暂不实现 `analyze`、`score`、`export`、`init-actions` 独立模式，避免 CLI 过早膨胀。

---

## 5. Skill 交付方案

### 5.1 调研结论

用户通常期望的是“安装一个能力，然后通过命令或自然语言完成读取、采集、同步”，而不是按内部流水线安装多个 skill。

因此，本项目不建议把采集、增量、AI 分析、评分、导出、前端拆成 6 个用户可见 skills。这样虽然架构清晰，但安装和使用成本太高，也不符合“用户只想拿结果”的真实心智。

推荐方案：**1 个主 skill + 1 个可选前端模板包**。主 skill 同时覆盖消费侧和维护侧：消费侧读取公开 JSON 生成选型简报，维护侧在 fork 仓库后运行采集、分析、评分和导出。

### 5.2 主 Skill：`github-radar`

`github-radar` 是唯一默认安装的主 skill。第一版暴露三类常用能力：

- `read-radar`：无需 API Key，读取公开 `brief.json` / `radar.json`，为 Agent 生成项目简报、选型建议或候选清单。
- `collect-only`：只采集候选仓库，输出 JSON。
- `sync`：采集、AI 分析、简单评分、导出前端 JSON。

目录结构保持轻量：

```text
github-radar/
├── SKILL.md
├── scripts/
│   └── radar_cli.py
└── references/
    ├── github_queries.md
    ├── classification_prompt.md
    └── scoring_formula.md
```

对 Codex 用户的自然语言用法：

```text
使用 github-radar，读取公开榜单，告诉我今天值得关注的 5 个 AI Agent 项目。
```

```text
使用 github-radar，只采集 GitHub 上具备高热度或明确安装入口的 AI Agent 和 Skill 仓库，输出 JSON。
```

```text
使用 github-radar，运行完整同步：采集、模型分析、简单评分，并导出 GitHub Pages 数据。
```

核心能力：

- 读取公开 `brief.json` 和 `radar.json`。
- 采集 GitHub topic/keyword 搜索结果。
- 按候选规则过滤仓库。
- 合并重复仓库并保留 `matched_queries` 与 `candidate_reason`。
- 拉取 README 摘要。
- 调用配置的模型完成 kind/category/summary/use_case/solves/install_methods/usability_flags。
- 用简单规则计算 `usability_score`、`adoption_score`、`maintenance_score`、`recommendation_score`。
- 生成 Agent 友好的 `brief.json` 和页面状态 `status.json`。
- 导出 `data/radar.json`、`data/run-report.json`、`docs/data/radar.json`、`docs/data/brief.json`、`docs/data/metadata.json`、`docs/data/status.json`。

### 5.3 可选前端模板

前端模板不是必须能力。第一版可以直接在主仓库放一个极简页面：

```text
docs/
├── index.html
└── data/
    ├── brief.json
    ├── radar.json
    ├── metadata.json
    └── status.json
```

只有当页面复杂度上升时，再把模板放进 `github-radar/assets/pages-template/`。

### 5.4 不拆成多个用户可见 Skill 的原因

内部模块可以拆函数，但不要拆成多个安装包。

| 内部步骤 | 是否独立 skill | 第一版处理 |
| --- | --- | --- |
| Reader | 否 | `github-radar` 读取公开 JSON |
| Collector | 否 | `src/main.py collect-only` |
| Analyzer | 否 | `src/main.py sync` 内部步骤 |
| Scorer | 否 | 一个 `score_repo()` 函数 |
| Brief Builder | 否 | 一个 `build_brief()` 函数 |
| Exporter | 否 | 一个 `export_json()` 函数 |
| Pages Template | 否 | 直接放 `docs/index.html` |

---

## 6. MVP 数据契约

第一版只维护一个项目对象结构，避免多阶段 DTO 膨胀。

```json
{
  "repo_id": 123456,
  "repo_name": "owner/repo",
  "owner": "owner",
  "kind": "Agent",
  "kind_confidence": 0.91,
  "category": "软件开发",
  "summary": "一个用于驱动浏览器完成自动化任务的 AI Agent 框架。",
  "use_case": "适合构建网页操作、信息提取、自动填表和流程自动化智能体。",
  "solves": ["浏览器操作自动化", "网页任务执行"],
  "install_methods": ["pypi", "cli"],
  "usability_flags": [],
  "usability_score": 86,
  "adoption_score": 78,
  "maintenance_score": 82,
  "recommendation_score": 83,
  "stars": 12000,
  "forks": 900,
  "watchers": 120,
  "open_issues": 42,
  "language": "Python",
  "topics": ["ai-agent", "mcp"],
  "url": "https://github.com/owner/repo",
  "pushed_at": "2026-06-25T10:00:00Z",
  "candidate_reason": ["high_popularity", "installable_signal"]
}
```

### 6.1 文件输出

```text
data/collected_repos.json   # collect-only 输出
data/radar.json             # sync 完整输出
data/run-report.json        # 本轮运行报告
docs/data/radar.json        # 前端数据
docs/data/brief.json        # 首屏精选和 Agent 快速消费数据
docs/data/metadata.json     # synced_at、repo_count、skill_count、agent_count
docs/data/status.json       # query 成功/失败、fallback 和 warning 状态
```

### 6.2 `brief.json` 生成规则

`brief.json` 不额外调用大模型，只从已经评分完成的 `RadarRepo[]` 派生：

- `top_picks`：从 Skill 和 Agent 两榜中混合选取推荐分最高、无严重风险、近期维护活跃的项目。
- `skill_top`：Skill 榜 Top 5，字段保持轻量。
- `agent_top`：Agent 榜 Top 5，字段保持轻量。
- `why_pick`：由规则生成，例如 `高可用性`、`安装入口明确`、`近期维护活跃`、`社区采用度高`。
- `warnings`：继承本轮运行的关键 warning，但不暴露 token、header 或私有环境变量。

如果没有项目达到 `RECOMMENDATION_MIN_SCORE`，仍生成空数组，页面隐藏精选区，Agent 返回“本轮没有足够可靠的新推荐”。

示例：

```json
{
  "generated_at": "2026-07-01T02:00:00Z",
  "window": "latest_sync",
  "top_picks": [
    {
      "repo_id": 123456,
      "repo_name": "owner/repo",
      "kind": "Agent",
      "category": "软件开发",
      "summary": "一个用于驱动浏览器完成自动化任务的 AI Agent 框架。",
      "recommendation_score": 83,
      "why_pick": ["高可用性", "近期维护活跃", "安装入口明确"],
      "url": "https://github.com/owner/repo"
    }
  ],
  "skill_top": [],
  "agent_top": [],
  "warnings": []
}
```

---

## 7. 仓库代码结构建议

```text
Skillhunt/
├── github_radar_prd.md
├── github_radar_agent_architecture.md
├── requirements.txt
├── config/
│   ├── queries.yaml
│   └── taxonomy.yaml
├── src/
│   └── main.py
├── data/
│   ├── collected_repos.json
│   ├── radar.json
│   └── run-report.json
├── docs/
│   ├── index.html
│   └── data/
│       ├── brief.json
│       ├── radar.json
│       ├── metadata.json
│       └── status.json
├── skills/
│   └── github-radar/
│       ├── SKILL.md
│       ├── scripts/radar_cli.py
│       └── references/
└── tests/
    └── test_main.py
```

第二版再拆：

```text
src/collector.py
src/analyzer.py
src/scorer.py
src/exporter.py
# 可选：data/radar.db
```

---

## 8. 配置设计

### 8.1 `config/queries.yaml`

```yaml
skill:
  topics:
    - skill
    - agent-skill
    - claude-skill
    - agent-skills
  keywords:
    - "AI skill"
    - "agent skill"
agent:
  topics:
    - ai-agent
    - llm-agent
    - autonomous-agent
    - agent-framework
    - mcp
  keywords:
    - "AI agent"
    - "agent framework"
```

### 8.2 内置常量

第一版不需要单独 `radar.yaml`，常量可以先放在 `src/main.py` 顶部：

```python
HIGH_POPULARITY_MIN_STARS = 1000
USABLE_TOOL_MIN_STARS = 300
README_MAX_CHARS = 4000
AI_BATCH_SIZE = 8
SKILL_TOP_N = 200
AGENT_TOP_N = 200
RECOMMENDATION_MIN_SCORE = 50
```

当常量开始频繁调整时，再迁移到配置文件。

---

## 9. 模型分析设计

### 9.1 Prompt 原则

Prompt 应当短、稳定、可测试：

- 只能从给定 kind/category 中选择。
- 输出 JSON Array，不返回 Markdown。
- 判断是否有安装入口、Quickstart、示例、真实运行方式。
- 如果像 demo、论文复现或概念项目，加入 `usability_flags`。

### 9.2 AI 输出字段

配置的模型只需要补全这些字段：

```json
{
  "repo_id": 123456,
  "kind": "Agent",
  "kind_confidence": 0.91,
  "category": "软件开发",
  "summary": "一句话摘要",
  "use_case": "适用场景",
  "solves": ["痛点1", "痛点2"],
  "install_methods": ["pypi", "cli"],
  "usability_flags": []
}
```

### 9.3 失败处理

- JSON 解析失败：重试一次。
- 重试仍失败：使用 topic 初判，`category = "其他"`。
- 低置信度：保留结果，但添加 `kind_uncertain`。

---

## 10. 简单评分设计

第一版评分必须可解释、可快速实现。

```text
recommendation_score = usability_score * 0.5 + adoption_score * 0.3 + maintenance_score * 0.2
```

建议规则：

- `usability_score`：有安装入口 +40，有 Quickstart/Usage +30，无明显风险 +30。
- `adoption_score`：按 Star、Fork、Watch 简单归一化。
- `maintenance_score`：90 天内更新 100 分，180 天内 70 分，365 天内 40 分，更久 10 分。
- `demo_only`、`unclear_installation`、`inactive_repo` 每个风险扣 10-30 分。

---

## 11. GitHub 采集设计

### 11.1 Query 策略

```text
topic:ai-agent stars:>1000
topic:llm-agent stars:>1000
topic:autonomous-agent stars:>1000
topic:agent-framework stars:>1000
topic:mcp stars:>1000
topic:skill stars:>300
topic:agent-skill stars:>300
topic:claude-skill stars:>300
topic:agent-skills stars:>300
"AI agent" stars:>1000
"agent framework" stars:>1000
"AI skill" stars:>300
"agent skill" stars:>300
```

每个 query 第一版最多取 50 条，去重后控制候选集大小。

### 11.2 候选规则

- 高热度候选：`stars >= 1000`。
- 可用工具候选：`stars >= 300` 且命中 Skill/MCP/插件/CLI 相关主题或关键词。
- 安装信号候选：README 中识别到 `npm`、`pip`、`uvx`、`npx`、`docker`、`mcp`、`cli` 等关键词。

暂不实现 7/30 日增长候选，因为需要历史数据。

---

## 12. GitHub Actions 编排

```yaml
name: GitHub Skill Agent Radar Daily Sync

on:
  schedule:
    - cron: '0 2 * * *'
  workflow_dispatch:

permissions:
  contents: write

jobs:
  sync_and_generate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          token: ${{ secrets.PERSONAL_ACCESS_TOKENS || secrets.PERSONAL_ACCESS_TOKEN || secrets.GH_TOKEN || github.token }}
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - run: pip install -r requirements.txt
      - name: Run radar sync
        env:
          PERSONAL_ACCESS_TOKENS: ${{ secrets.PERSONAL_ACCESS_TOKENS }}
          PERSONAL_ACCESS_TOKEN: ${{ secrets.PERSONAL_ACCESS_TOKEN }}
          GH_TOKEN: ${{ secrets.GH_TOKEN }}
          MODEL_API_KEY: ${{ secrets.MODEL_API_KEY }}
          MODEL_API_BASE: ${{ vars.MODEL_API_BASE || 'https://api.siliconflow.cn/v1/chat/completions' }}
          MODEL_NAME: ${{ vars.MODEL_NAME || 'deepseek-ai/DeepSeek-R1-0528-Qwen3-8B' }}
        run: python src/main.py sync
      - name: Commit generated data
        run: |
          git config --local user.email "action@github.com"
          git config --local user.name "GitHub Action"
          git add data/ docs/data/
          git commit -m "chore: sync radar data" || echo "No changes to commit"
          git push origin main
```

提交范围采用 `git add data/ docs/data/`，避免未来新增 `brief.json`、`status.json`、`run-report.json` 等文件后忘记纳入 Actions。

---

## 13. 用户安装与使用设计

### 13.1 默认安装

```bash
mkdir -p ~/.codex/skills
cp -r skills/github-radar ~/.codex/skills/
```

需要配置：

```text
PERSONAL_ACCESS_TOKENS  # GitHub personal access token，collect-only 和 sync 都建议配置
PERSONAL_ACCESS_TOKEN   # 兼容的单数命名
GH_TOKEN                # fallback 命名
MODEL_API_KEY    # sync 需要
MODEL_API_BASE   # 可选，默认 https://api.siliconflow.cn/v1/chat/completions
MODEL_NAME       # 可选，默认 deepseek-ai/DeepSeek-R1-0528-Qwen3-8B
```

本地开发时，在仓库根目录创建 `.env` 即可。项目自带 `.env.example`，`src/main.py` 会自动加载 `.env`。

### 13.2 常用模式

```text
使用 github-radar，读取公开 GitHub Skill/Agent Radar 数据，给我 5 个今天最值得关注的 Agent 项目。
```

```text
使用 github-radar，只采集 GitHub 上具备高热度或明确安装入口的 AI Agent 和 Skill 仓库，输出 data/collected_repos.json。
```

```text
使用 github-radar，运行完整同步并生成 docs/data/*.json。
```

---

## 14. Skill 创建规范

```yaml
---
name: github-radar
description: Build, consume, and operate a simplified GitHub Skill/Agent Radar with read-radar, collect-only, and sync usage. Use for GitHub repository collection, model classification, simple usability/adoption scoring, static JSON export, and Agent-readable project briefs without requiring separate pipeline skills or a database.
---
```

`SKILL.md` body 只保留：

- 如何读取公开 `brief.json` / `radar.json` 并生成简报。
- 何时使用 `collect-only`。
- 何时使用 `sync`。
- 需要哪些 secrets。
- 输出哪些 JSON 文件。
- 失败时如何降级。

---

## 15. 测试策略

第一版只做必要测试，避免测试体系比代码还复杂。

必须覆盖：

- Query 生成。
- 仓库去重。
- README 截断。
- AI JSON 解析和 fallback。
- 简单评分计算。
- `brief.json` 的 Top Picks 和空结果隐藏逻辑。
- `status.json` / `run-report.json` 的 warning 与 fallback 统计。
- `data/radar.json`、`docs/data/radar.json`、`docs/data/brief.json` 和 `docs/data/status.json` 导出。

建议 fixture：

```text
tests/fixtures/
├── github_search_response.json
├── readme.md
├── model_success_response.json
└── model_invalid_response.txt
```

---

## 16. 错误处理与降级

| 错误 | 第一版处理 |
| --- | --- |
| GitHub rate limit | 停止后续 query，保留已采集结果 |
| README 404 | 使用 description + topics |
| 模型超时 | 重试一次 |
| 模型非 JSON | 重试一次，仍失败则使用 topic 初判 |
| 单个仓库失败 | 跳过该仓库并记录 warning |
| 导出为空 | 直接失败，避免覆盖旧数据 |
| `brief.json` 为空 | 页面隐藏精选区，Skill 回退读取 `radar.json` |
| `status.json` 生成失败 | 不阻塞主榜导出，但在 `run-report.json` 记录 warning |

---

## 17. 安全与权限

必需 secrets：

```text
PERSONAL_ACCESS_TOKENS
PERSONAL_ACCESS_TOKEN
GH_TOKEN
MODEL_API_KEY
```

原则：

- 不打印 secrets。
- 不保存请求 header。
- 不把 API Key、cookie、token、私有邮箱或私有数据写入仓库。
- Actions 只授予 `contents: write`。

依赖第一版控制在：

```text
requests
pydantic
PyYAML
```

---

## 18. 可观测性

第一版输出一个简单 summary 到控制台和 `metadata.json`：

```json
{
  "synced_at": "2026-07-01T02:00:00Z",
  "collected_count": 320,
  "analyzed_count": 320,
  "skill_count": 140,
  "agent_count": 180,
  "exported_count": 300,
  "brief_count": 10,
  "fallback_count": 3,
  "warnings": []
}
```

`status.json` 面向页面和 Agent，可以比 `metadata.json` 更偏运行态：

```json
{
  "ok": true,
  "synced_at": "2026-07-01T02:00:00Z",
  "query_count": 13,
  "failed_queries": [],
  "github_rate_limited": false,
  "ai_fallback_count": 3,
  "warnings": []
}
```

---

## 19. 开发里程碑

### Phase 1：单脚本数据闭环

交付：

- `src/main.py collect-only`。
- `src/main.py sync`。
- `data/radar.json`。
- `docs/data/radar.json`。
- `docs/data/brief.json`。
- `docs/data/status.json`。
- 基础测试。

验收：

- 能采集 Skill/Agent 候选仓库。
- 能调用模型生成分类和摘要。
- 能计算简单推荐分。
- 能导出前端 JSON。
- 能从评分结果派生 Agent 可读简报和运行状态。

### Phase 2：极简页面和 Actions

交付：

- `docs/index.html`。
- `.github/workflows/radar.yml`。
- `metadata.json`。

验收：

- GitHub Actions 能每日运行。
- GitHub Pages 能展示 Skill/Agent 推荐榜。
- 页面能展示或隐藏首屏精选区。
- 页面支持关键词过滤。

### Phase 3：Skill 消费与维护入口

交付：

- `skills/github-radar/SKILL.md`。
- 读取公开 JSON 的自然语言用法。
- fork 自建雷达的维护说明。

验收：

- Agent 可读取 `brief.json` 输出项目简报。
- Agent 可在用户授权下运行 `collect-only` 或 `sync`。
- Skill 文档明确 secret 和私有数据不得写入仓库。

### Phase 4：按需增强

只有当第一版跑起来后，再考虑：

- `data/cache.json`。
- SQLite。
- 历史趋势。
- Fuse.js。
- npm/PyPI/Docker 下载量。
- 更复杂的前端筛选。

---

## 20. MVP 范围

MVP 包含：

- GitHub topic/keyword 采集。
- 候选规则过滤。
- README 截断。
- 模型批量分析。
- 简单评分。
- JSON 导出。
- `brief.json` 精选摘要。
- `status.json` 运行状态。
- GitHub Actions 每日运行。
- 极简 GitHub Pages 展示。
- `github-radar` Skill 消费公开 JSON。

MVP 不包含：

- SQLite。
- 趋势历史。
- 复杂增量。
- 下载量和 dependents 采集。
- 多模型评审。
- 复杂前端应用。
- 完整自主智能体的长期记忆、自主规划和自我修复。

---

## 21. 关键开发决策

1. **第一版不用数据库**：JSON 足够承载 300-500 个项目。
2. **第一版主脚本只做两个模式**：`collect-only` 和 `sync`；Skill 额外支持读取公开 JSON 的消费侧用法。
3. **第一版评分简单可解释**：不要为了“精确”引入大量外部数据源。
4. **失败可降级**：AI 失败时用 topic 初判，不阻塞整轮运行。
5. **派生文件不额外耗费模型调用**：`brief.json` 和 `status.json` 只从本地结果生成。
6. **第二版再优化成本**：当 Token 或运行时间成为真实问题，再做 `content_hash` 缓存。

---

## 22. 后续可扩展方向

- `data/cache.json`：减少重复 AI 调用。
- SQLite：需要历史趋势和复杂查询时再引入。
- Fuse.js：数据量变大、搜索体验不足时再引入。
- 趋势榜：有历史数据后再做 7/30 日增长。
- 下载量采集：需要更准确 adoption score 时再接 npm/PyPI/Docker。
- 更强 Agent 化能力：在已有管道稳定后，再考虑目标规划、自动调参、失败自修复和长期记忆。

---

## 23. 结论

简化后的架构是：**一个 skill、一个脚本、一个主 JSON、一组派生 JSON、一个静态页面**。

第一版应优先把 GitHub Radar 跑起来，并让普通用户能看榜单、Agent 能读榜单、开发者能 fork 自建雷达，而不是提前建设完整平台或完整自主智能体。等真实数据、真实用户和真实瓶颈出现后，再把缓存、SQLite、趋势、复杂搜索和更强 Agent 化能力逐步加回来。
