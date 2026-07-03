# GitHub Skill / Agent 开源项目雷达 —— 产品需求文档 (PRD)

**项目版本**：v1.0  
**文档状态**：修订中  
**编写时间**：2026-07-01  
**部署方案**：纯 GitHub Actions（单脚本采集/分析/导出） + GitHub Pages（极简静态展示） + Agent Skill 消费/维护入口

---

## 1. 背景与目标

随着 AI 浪潮的爆发，GitHub 上涌现出海量的 AI Agent 框架、工具和 AI Skill 项目。然而，目前缺乏一个具备以下特征的聚合平台：
- **可用性优先**：优先收录用户真正可以安装、调用、集成或运行的开源项目，而不是只按 Star 收藏量判断价值。
- **使用度评估**：第一版仅综合 Star、Fork、最近更新时间、README 可用性和安装入口，识别“更可能真实可用”的项目。
- **智能分类**：对项目进行自动化的结构化梳理（如区分哪些是供 Agent 调用的 Skill，哪些是 Agent 框架/应用）。
- **零成本运维**：在不采购云服务器、云数据库的前提下，通过 GitHub Actions 生成静态 JSON 并提交回仓库。

本项目采用轻量化静态交付方式：用 GitHub Actions 定时生成静态 JSON，用 GitHub Pages 做公开页面，用内置 Skill 让 Agent 可以继续消费、维护和扩展雷达。项目对象是 GitHub 上可安装、可集成、可运行的 Skill / Agent 开源项目。

### 1.1 核心目标
1. **可用项目发现与覆盖**：聚合 GitHub 上与 `Skill` 和 `Agent` 相关、具备明确可用性或真实使用信号的开源项目。`stars > 1000` 仅作为高热度信号之一，不再作为唯一入库标准。
2. **自动化轻量流水线**：每日定时触发，第一版允许全量重算候选项目；当项目数量变大后再引入增量缓存。
3. **模型 AI 深度赋能**：采用可配置的 OpenAI-compatible 模型进行双榜判定（一律以 AI 复判为准）、摘要提炼、可用性判断与多维度细分标签归纳。
4. **零服务器部署**：全套流程在 GitHub Actions 运行，数据持久化为仓库内 JSON 文件，前端托管在 GitHub Pages。
5. **极简检索**：前端纯静态渲染，第一版使用浏览器原生字符串过滤；数据量增长后再引入 `Fuse.js`。
6. **低摩擦能力交付**：面向用户默认提供一个 `github-radar` 主 Skill；主脚本保留 `collect-only` 和 `sync` 两个模式，Skill 额外支持读取公开 JSON 生成项目简报。

### 1.2 产品定位

当前项目不是严格意义上的自主智能体，而是一个 **AI 辅助的 GitHub Radar 数据管道 + Agent Skill 交付形态**。

- **确定性管道**：GitHub Actions 或本地 CLI 负责采集、去重、评分、导出。
- **AI 辅助判断**：配置的模型负责 Skill/Agent 归类、摘要、适用场景、安装入口和可用性风险判断。
- **静态内容产品**：GitHub Pages 面向普通用户展示双榜、筛选、项目详情和同步状态。
- **Agent 可读入口**：Skill 读取公开 JSON，给 Codex、Claude Code 等 Agent 输出可引用的项目推荐、选型摘要或候选清单。
- **可 fork 自建**：开发者可以 fork 仓库，调整 query、分类体系、评分权重和展示页面，形成自己的 GitHub 开源项目雷达。

本项目提供三层使用路径：

```text
看榜单 → 让 Agent 读榜单 → fork 自建雷达
```

第一版不追求让系统自主规划下一步任务，也不维护长期记忆或自动修复策略；这些能力属于后续 Agent 化增强，而非 MVP 必需项。

---

## 2. 用户与场景

- **AI 开发者**：寻找可以直接给自己的 Agent 调用的 Skill（如 Vercel 推荐的 React/Azure 技能等）。
- **技术选型者**：对比不同的开源 Agent 框架（如 `browser-use` 还是 `agent-browser`），并根据可用性、采用度和维护活跃判断优先级。
- **生态观察者**：了解每天新晋的热门 AI 技能和智能体，掌握行业最新风向。
- **Agent 使用者**：希望让 Codex / Claude Code / OpenClaw 等 Agent 直接读取结构化 JSON，生成“今天值得关注的 Skill/Agent 项目”简报。
- **自建雷达维护者**：fork 仓库后调整 GitHub query、分类体系、评分规则和页面样式，形成个人或团队内部雷达。

---

## 3. 术语定义

| 术语 | 英文名 | 定义 |
| --- | --- | --- |
| **能力单元** | Skill | 供智能体调用的具体功能封装或规则描述（如 book-to-skill、pdf 提取、frontend-design）。 |
| **智能体** | Agent | 具备自主规划、决策、工具调用、记忆和执行能力的主体框架或垂直应用。 |
| **归属类别** | kind | 顶层大类判定，本系统包含两类：`Skill` 与 `Agent`。 |
| **细分类型** | category | 处于各自大类（kind）内部的业务场景标签（如“学习”、“信息搜集”、“软件开发”等）。 |
| **可用性评分** | usability_score | 衡量项目是否能被用户直接安装、运行、调用或集成的评分。 |
| **使用度评分** | adoption_score | 衡量项目是否有真实用户采用的评分，第一版仅综合 Star、Fork、最近更新时间等 GitHub 基础信号。 |
| **推荐评分** | recommendation_score | 前端默认排序使用的综合评分，由可用性、使用度和维护活跃共同决定。 |
| **雷达管道** | Radar Pipeline | 定时采集、分析、评分、导出静态 JSON 的确定性工作流。 |
| **雷达简报** | brief | 从完整榜单派生的 Top 项目摘要，供页面首屏和 Agent 快速消费。 |
| **运行状态** | status | 本轮采集 query、成功数、失败数、warning 和降级信息。 |

---

## 4. 功能需求

### 4.1 数据采集模块 (GitHub API)
- **采集范围**：通过多路 Topic 及关键词交叉检索。
  - **Skill 相关**：`skill`、`agent-skill`、`claude-skill`、`agent-skills`。
  - **Agent 相关**：`ai-agent`、`llm-agent`、`autonomous-agent`、`agent-framework`、`mcp`（Model Context Protocol）等。
- **候选入库策略**：不再将 `stars > 1000` 作为唯一硬性过滤器，而是采用多路候选发现：
  - **高热度 Agent/框架**：`stars >= 1000`，用于覆盖成熟 Agent 框架和应用。
  - **可用 Skill/工具/MCP/插件**：`stars >= 300`，避免漏掉小而强、可直接安装使用的能力单元。
  - **明确安装信号项目**：README 中出现 npm、PyPI、Docker、CLI、MCP、VS Code Extension、Browser Extension、GitHub Release 等安装/使用入口，可进入候选。
- **展示配比**：
  - **Skill 榜**：第一版按 `recommendation_score` 降序取 **Top 200** 并在前端展示。
  - **Agent 榜**：第一版按 `recommendation_score` 降序取 **Top 200** 并在前端展示。
- **去重逻辑**：多路检索下可能重复命中同一仓库，需根据 `repo_id` 唯一主键去重，但合并保留其命中的所有 Topic 标签。

### 4.2 轻量处理与成本控制策略

第一版以“少代码、先跑通”为原则，不实现复杂增量系统：

1. **候选规模控制**：每次从 GitHub API 获取有限候选集，例如每个 query 最多取前 50 个结果，合并去重后控制在 300-500 个项目以内。
2. **README 截断**：仅将 README 前 3000-4000 个字符喂给大模型，避免长 README 浪费 Token。
3. **缓存延后**：第一版不实现 `content_hash` 缓存；如果 Token 或运行时间成为真实问题，第二版再加入 `data/cache.json`。
4. **无数据库依赖**：第一版不引入 SQLite，不维护历史趋势表，只输出 `data/*.json` 和 `docs/data/*.json`。
5. **候选失效处理**：第一版不做复杂 inactive 状态流转，只在导出时过滤低于推荐门槛或明显不可用的项目。

### 4.3 模型智能分析与 Kind 判定
使用 OpenAI-compatible 模型进行轻量语义分类、摘要和可用性判断；当前默认模型为 **`deepseek-ai/DeepSeek-R1-0528-Qwen3-8B`**。
- **一键复判（Kind Priority）**：
  - 采集时根据 Topic 进行初始 `kind` 猜测。
  - 统一调用配置的模型进行复判，**判定结果一律以 AI 复判为准**。
  - 若 AI 返回的置信度低于 0.6，回退采用话题初判，并打上 `kind_uncertain` 标记。
- **结构化输出**：模型须严格输出 JSON，格式包含：
  - `kind`："Skill" 或 "Agent"
  - `kind_confidence`：置信度 (0.0 - 1.0)
  - `summary`：一句话描述（在前端列表页直观展示）
  - `category`：细分类型（从预设体系中选择最贴合的一项）
  - `use_case`：使用场景说明
  - `solves`：解决的痛点标签（JSON 数组）
  - `install_methods`：识别到的安装/使用入口（如 npm、PyPI、Docker、CLI、MCP、Browser Extension、VS Code Extension、GitHub Release、源码运行）
  - `usability_flags`：可用性风险标记（如 `no_quickstart`、`no_release`、`inactive_repo`、`demo_only`、`unclear_installation`）

### 4.4 简化评分模型

第一版只保留一个可解释、容易实现的综合评分，不采集 npm/PyPI/Docker 下载量，也不计算复杂依赖引用。

1. **可用性评分 `usability_score` (0-100)**：
   - README 是否出现安装/运行关键词：`install`、`quickstart`、`usage`、`docker`、`npm`、`pip`、`uvx`、`npx`、`mcp`、`cli`。
   - AI 是否判断为可直接使用，而不是纯 demo、论文复现或概念项目。

2. **使用度评分 `adoption_score` (0-100)**：
   - 使用 GitHub 基础信号计算：Star、Fork、Watch、Open Issue 数。
   - 第一版不接入外部包下载量。

3. **维护活跃评分 `maintenance_score` (0-100)**：
   - 根据 `pushed_at` 或 `updated_at` 判断最近是否仍在维护。
   - 最近 90 天更新得高分，超过 1 年未更新得低分。

4. **推荐评分 `recommendation_score` (0-100)**：
   - 默认建议：`usability_score * 0.5 + adoption_score * 0.3 + maintenance_score * 0.2`。
   - 前端默认榜单按 `recommendation_score` 排序。

5. **推荐门槛**：
   - 默认展示：`recommendation_score >= 50`。
   - `demo_only`、`unclear_installation`、`inactive_repo` 可降低推荐分。

### 4.5 交付体验

第一版交付不只是生成一个 JSON 文件，而是形成三类入口：

1. **公开页面入口**：
   - GitHub Pages 展示 Skill 推荐榜、Agent 推荐榜、今日优先关注项目、同步时间和运行状态。
   - 页面不依赖后端服务，不要求普通用户配置 API Key。

2. **Agent 消费入口**：
   - `github-radar` Skill 可以读取 `docs/data/brief.json` 和 `docs/data/radar.json`。
   - 用户可以自然语言询问：“今天 GitHub 上有什么值得关注的 Agent 框架？”或“给我推荐 5 个可直接安装的 Skill 项目。”

3. **自建维护入口**：
   - fork 仓库后，用户可以通过修改 `config/queries.yaml`、`config/taxonomy.yaml` 和 GitHub Secrets 运行自己的雷达。
   - Skill 说明中必须强调：不要把 API Key、私有 token、cookie 或私有数据写进仓库。
   - 本地运行时可在仓库根目录创建 `.env`，填写 `PERSONAL_ACCESS_TOKENS` 和 `MODEL_API_KEY`；提交时必须忽略 `.env`。

页面首屏的“精选/简报”区域应宁缺毋滥：当没有足够高分项目时隐藏该区域，页面回退为纯榜单视图。

---

## 5. 建议细分分类体系 (Category)

双榜切换后，各自采用独立的细分分类体系，更贴合产品实际：

### 5.1 Skill 榜与 Agent 榜统一业务场景分类
- **学习**：教程、课程、书籍转换、知识体系整理、面试与训练材料。
- **信息搜集**：搜索、爬取、知识库构建、资料归档、数据提取与研究辅助。
- **知识管理**：RAG、记忆系统、知识库、文档沉淀、上下文管理。
- **内容创作**：写作、设计、PPT、图片、社媒素材与多模态内容生成。
- **视频处理**：视频采集、字幕、转录、剪辑、播客和视频内容理解。
- **办公协作**：邮件、文档、表格、会议、团队协作和日常办公提效。
- **数据分析**：分析、报表、指标、数据管道、BI 和洞察生成。
- **投资研究**：金融行情、投研分析、基金/股票研究、市场信息处理。
- **软件开发**：编程、调试、Agent 工程、MCP/CLI/插件、自动化开发工作流。
- **产品设计**：UI/UX、原型、设计系统、交互设计与体验优化。
- **市场营销**：SEO、广告投放、增长、获客、社媒运营和营销自动化。
- **安全攻防**：安全扫描、漏洞分析、渗透、攻防演练与安全运维辅助。
- **自动化运营**：浏览器自动化、流程编排、审批流、RPA 和重复任务执行。
- **其他**：无法稳定归入以上业务场景的项目。

---

## 6. 数据结构设计

第一版不使用 SQLite，只使用 JSON 文件作为持久化和前端数据源，降低实现复杂度。

### 6.1 输出文件

```text
data/collected_repos.json # collect-only 输出，供调试候选集
data/radar.json           # sync 完整数据，供调试和后续重跑使用
data/run-report.json      # 本轮运行报告，记录 query 命中、失败和 warning
docs/data/radar.json      # 前端展示数据
docs/data/brief.json      # 页面首屏和 Agent 快速消费的精选项目摘要
docs/data/metadata.json   # 同步时间、项目数量、版本信息
docs/data/status.json     # 页面展示的运行状态和降级信息
```

`radar.json` 是主数据源，`brief.json` 和 `status.json` 是派生产物。若派生产物生成失败，页面和 Skill 必须能回退读取 `radar.json`。

### 6.2 项目数据结构

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
  "updated_at": "2026-06-25T10:00:00Z",
  "candidate_reason": ["high_popularity", "installable_signal"]
}
```

### 6.3 雷达简报结构

`brief.json` 面向页面首屏和 Agent 消费，避免 Agent 每次读取完整榜单后再自行推断。

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

## 7. 前端静态展示设计 (GitHub Pages)

第一版前端保持极简：一个页面读取 `docs/data/radar.json`，并优先读取 `docs/data/brief.json` 和 `docs/data/status.json` 做首屏摘要与运行状态展示。

1. **首屏简报**：
   - 展示 `brief.json` 中的 Top Picks，用于回答“今天最值得看什么”。
   - 如果 `brief.json` 不存在、为空或分数不足，则隐藏首屏简报，直接展示双榜。
2. **双榜 Tab**：
   - 「Skill 推荐榜」和「Agent 推荐榜」。
   - 每榜默认展示 Top 200。
3. **列表展示**：
   - 展示项目名、推荐评分、Star、Fork、分类、语言、摘要、GitHub 链接。
   - 详情展开可展示 use case、solves、install methods、usability flags。
4. **搜索过滤**：
   - 第一版使用原生字符串匹配，不引入 Fuse.js。
   - 支持按项目名、摘要、分类、语言过滤。
5. **更新时间与状态**：
   - 从 `metadata.json` 显示 `synced_at`。
   - 从 `status.json` 显示本轮采集数量、失败 query、AI fallback 次数和 warning。

---

## 8. 技术方案与 Actions 工作流

### 8.1 简化运行架构

```text
GitHub Actions
    │
    ▼
python src/main.py
    │
    ├─ GitHub API 搜索候选项目
    ├─ 拉取 README 摘要
    ├─ 配置的模型分类和可用性判断
    ├─ 简单规则评分
    ├─ 生成 brief/status 派生数据
    └─ 导出 data/*.json + docs/data/*.json
    │
    ▼
GitHub Pages 静态展示
```

### 8.2 GitHub Actions 配置草稿 (`.github/workflows/radar.yml`)

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
          cache: 'pip'

      - name: Install Dependencies
        run: pip install -r requirements.txt

      - name: Run Radar Pipeline
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
          git commit -m "chore: sync radar data [$(date -u +'%Y-%m-%d %H:%M:%S')]" || echo "No changes to commit"
          git push origin main
```

## 9. 降 Token 与成本控制最佳实践

1. **候选数量控制**：第一版通过 query 数量、每个 query 返回数量和 Top N 导出限制控制 Token 成本。
2. **批量请求协议**：为了加快 Actions 处理速度和控制请求频次，可设计合并 Prompt，将 5-10 个新项目的元数据以数组形式合并发送，要求模型一次性返回规范的 JSON Array。
3. **缓存延后**：第一版项目数控制在 300-500 个以内，先不做复杂缓存；第二版再引入 `content_hash`。
4. **评分简化**：第一版只使用 Star、Fork、更新时间和 AI 可用性判断，不接入外部下载量。
5. **派生产物本地生成**：`brief.json` 和 `status.json` 必须由本地评分结果派生，不额外调用大模型。
6. **失败不清空旧数据**：若本轮导出为空或模型全量失败，Actions 应失败退出，避免用空数据覆盖上一次可用页面。

---

## 10. 里程碑与排期计划

- **里程碑 1 (Week 1)**：完成单脚本采集、README 截断、模型分析、简单评分和主 JSON 导出。
- **里程碑 2 (Week 2)**：完成 `brief.json`、`status.json`、GitHub Actions 自动运行和极简 GitHub Pages 页面。
- **里程碑 3 (Week 3)**：完成 `github-radar` Skill 的消费/维护说明，支持 Agent 读取公开 JSON 输出项目简报。
- **里程碑 4 (Week 4)**：按需要补充缓存、SQLite、趋势历史、Fuse.js 搜索等增强能力。





