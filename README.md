# GitHub Skill / Agent Radar

## GitHub 开源 Skill / Agent 雷达｜github-radar

`GitHub Skill / Agent Radar` 是一个面向 AI Skill、Agent、MCP、开发工具和可运行开源项目的静态雷达。

它不只是把 GitHub 仓库抓回来，而是尽量判断：

- 哪些项目真的可安装、可运行、可集成
- 哪些项目更可能有真实采用度
- 哪些项目值得优先关注

项目围绕 GitHub 上的 Skill / Agent 开源项目构建，提供从榜单浏览、Agent 读取到 fork 自建的一条完整路径：

看榜单 -> 让 Agent 读榜单 -> fork 自建雷达

---

## 30 秒选边上车

1. 只想看榜单  
   

2. 想让 Agent 替你读  
   直接让 Agent 读取 `docs/data/brief.json` / `docs/data/radar.json`，或者使用：

   ```bash
   python skills/github-radar/scripts/radar_cli.py read-radar --root .
   ```

3. 想要一个完全属于自己的雷达  
   fork 本仓库，配置 GitHub personal access token 和模型 API Key，让 GitHub Actions 每天自动更新数据。

---

## 这是什么

这是一个低运维的 GitHub Radar 管道：

- GitHub API 搜索 Skill / Agent 候选项目
- 拉取 README 片段
- 用 OpenAI-compatible 模型或本地启发式规则补全 `kind`、`category`、`summary`、`install_methods`
- 基于可用性、采用度、维护活跃计算推荐分
- 导出 `data/*.json` 和 `docs/data/*.json`
- 用 GitHub Pages 展示双榜

第一版刻意保持轻量：

- 无数据库
- 无后端服务
- 无复杂缓存
- 无下载量采集
- 前端纯静态页面

---

## 它能做什么

### 给普通读者

- 看 Skill 推荐榜和 Agent 推荐榜
- 先看 `brief.json` 里的今日优先关注项目
- 按项目名、摘要、分类、语言做前端过滤
- 展开查看安装方式、适用场景、风险标记

### 给开发者

- fork 后用自己的 query 和 taxonomy 跑一套雷达
- 用 GitHub Actions 每日自动同步
- 用 GitHub Pages 托管成公开静态页面
- 用 JSON 结果继续做二次分析或别的前端

### 给 Agent

- 读取 `docs/data/brief.json` 给出快速推荐
- 回退读取 `docs/data/radar.json` 生成更完整的候选清单
- 在本地运行 `collect-only` / `sync`
- 帮你维护 query、分类体系、评分规则和导出逻辑

---

## 仓库结构

```text
Skillhunt/
├── config/
│   ├── queries.yaml
│   ├── seeds.yaml
│   └── taxonomy.yaml
├── src/
│   └── main.py
├── data/
├── docs/
│   ├── index.html
│   └── data/
├── skills/
│   └── github-radar/
├── tests/
├── .env.example
└── .github/workflows/radar.yml
```

关键文件：

- `src/main.py`：主脚本入口，只保留 `collect-only` 和 `sync`
- `config/queries.yaml`：GitHub 搜索 query
- `config/seeds.yaml`：必须纳入的重点仓库
- `config/taxonomy.yaml`：业务场景分类和安装信号
- `docs/index.html`：静态页面
- `skills/github-radar/SKILL.md`：Agent 使用说明

---

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置本地环境变量

复制 `.env.example` 为 `.env`：

PowerShell:

```powershell
Copy-Item .env.example .env
```

Bash:

```bash
cp .env.example .env
```

填写最少配置：

```env
PERSONAL_ACCESS_TOKENS=your_github_personal_access_token
MODEL_PROVIDER=openai-compatible
MODEL_API_KEY=your_model_api_key
MODEL_API_BASE=https://api.siliconflow.cn/v1/chat/completions
MODEL_NAME=deepseek-ai/DeepSeek-R1-0528-Qwen3-8B
```

说明：

- `src/main.py` 会自动加载仓库根目录下的 `.env`
- `.env` 已经被 `.gitignore` 忽略，不会被提交
- 没有配置当前模型 provider 的 API Key 时，`sync` 会自动退回本地启发式分类

### 3. 只采集候选仓库

```bash
python src/main.py collect-only
```

输出：

- `data/collected_repos.json`
- `data/run-report.json`

### 4. 运行完整同步

```bash
python src/main.py sync
```

输出：

- `data/radar.json`
- `data/run-report.json`
- `docs/data/radar.json`
- `docs/data/brief.json`
- `docs/data/metadata.json`
- `docs/data/status.json`

### 5. 本地预览页面

因为页面通过 `fetch()` 读取 JSON，建议起一个本地静态服务器：

```bash
python -m http.server 8000 --directory docs
```

然后打开：

```text
http://127.0.0.1:8000/
```

---

## 如何配置

### 本地 `.env`

支持这些环境变量：

- `PERSONAL_ACCESS_TOKENS`：推荐使用的 GitHub personal access token
- `PERSONAL_ACCESS_TOKEN`：兼容的备用命名
- `GITHUB_PERSONAL_ACCESS_TOKEN`：兼容的备用命名
- `GH_TOKEN` / `GITHUB_TOKEN`：兼容 fallback
- `MODEL_PROVIDER`：可选，模型服务商标签，默认示例为 `openai-compatible`
- `MODEL_API_KEY`：模型 API Key
- `MODEL_API_BASE`：OpenAI-compatible Chat Completions endpoint，当前示例为 SiliconFlow 地址
- `MODEL_NAME`：模型名称，当前示例为 `deepseek-ai/DeepSeek-R1-0528-Qwen3-8B`
- `SKILL_SEARCH_MIN_STARS`：可选，Skill 主检索 star 阈值，默认 `1000`
- `AGENT_SEARCH_MIN_STARS`：可选，Agent 主检索 star 阈值，默认 `2000`
- `MAX_RESULTS_PER_QUERY`：可选，限制每个 query 返回数量
- `GITHUB_SEARCH_PAGES`：可选，每个 query 拉取多少页 GitHub Search 结果，页数越大召回越高、API 消耗越多
- `ENABLE_GITHUB_TRENDING`：可选，是否补充抓取 GitHub Trending，默认 `1`
- `GITHUB_TRENDING_PERIODS`：可选，Trending 时间窗口，默认 `daily,weekly`
- `GITHUB_TRENDING_FETCH_LIMIT`：可选，每个 Trending 窗口最多检查多少个仓库，默认 `25`
- `GITHUB_SEARCH_QUALIFIERS`：可选，追加到 GitHub Search 的限定条件，默认 `fork:false archived:false`
- `FILTER_ARCHIVED_REPOS` / `FILTER_FORK_REPOS` / `FILTER_TEMPLATE_REPOS` / `FILTER_DISABLED_REPOS`：可选，是否过滤对应仓库，默认 `1`
- `CANDIDATE_MAX_PUSH_AGE_DAYS`：可选，最后 push 超过多少天则过滤，默认 `730`；设为 `0` 表示关闭
- `CANDIDATE_NOISE_TERMS`：可选，按仓库名或 topic 过滤明显噪音词
- `README_FETCH_LIMIT`：可选，限制本轮最多拉取多少个 README，`0` 表示不限制
- `HTTP_TIMEOUT`：可选，请求超时时间
- `GITHUB_REQUEST_INTERVAL_SECONDS`：可选，GitHub API 请求间隔，默认 `0.2`
- `GITHUB_SEARCH_REQUEST_INTERVAL_SECONDS`：可选，GitHub Search API 请求间隔，默认 `2.2`
- `GITHUB_WAIT_ON_RATE_LIMIT`：可选，遇到 GitHub rate limit 是否等待重试，默认 `1`
- `GITHUB_RATE_LIMIT_RETRIES`：可选，GitHub rate limit 最大等待重试次数，默认 `2`
- `GITHUB_RATE_LIMIT_MAX_WAIT_SECONDS`：可选，单次最多等待多少秒，默认 `120.0`
- `AI_BATCH_SIZE`：可选，模型批量分析大小
- `MODEL_INPUT_CHAR_BUDGET`：可选，单个模型 batch 的输入字符预算，默认 `90000`
- `MODEL_REQUEST_INTERVAL_SECONDS`：可选，模型请求间隔，默认 `2.0`
- `MODEL_MAX_RETRIES`：可选，模型请求最大重试次数，默认 `5`
- `MODEL_RETRY_BASE_SECONDS`：可选，模型指数退避基础等待秒数，默认 `2.0`
- `MODEL_RETRY_MAX_SECONDS`：可选，模型单次最大退避秒数，默认 `60.0`
- `LOG_LEVEL`：可选，默认 `INFO`，调试时可设为 `DEBUG`
- `DEBUG_LOG_FILE`：可选，默认 `data/debug.log`

### 性能与限速配置

模型服务通常对调用有速率限制。当前脚本默认采用顺序调用、动态批量、请求间隔和指数退避来降低触发限制的概率。

推荐先用这组保守配置跑通：

```env
AI_BATCH_SIZE=8
MODEL_INPUT_CHAR_BUDGET=90000
MODEL_REQUEST_INTERVAL_SECONDS=2.0
MODEL_MAX_RETRIES=5
GITHUB_REQUEST_INTERVAL_SECONDS=0.2
GITHUB_SEARCH_REQUEST_INTERVAL_SECONDS=2.2
GITHUB_WAIT_ON_RATE_LIMIT=1
GITHUB_RATE_LIMIT_RETRIES=2
GITHUB_RATE_LIMIT_MAX_WAIT_SECONDS=120.0
SKILL_SEARCH_MIN_STARS=1000
AGENT_SEARCH_MIN_STARS=2000
GITHUB_SEARCH_QUALIFIERS=fork:false archived:false
GITHUB_SEARCH_PAGES=1
ENABLE_GITHUB_TRENDING=1
GITHUB_TRENDING_PERIODS=daily,weekly
GITHUB_TRENDING_FETCH_LIMIT=25
FILTER_ARCHIVED_REPOS=1
FILTER_FORK_REPOS=1
FILTER_TEMPLATE_REPOS=1
FILTER_DISABLED_REPOS=1
CANDIDATE_MAX_PUSH_AGE_DAYS=730
README_FETCH_LIMIT=0
```

如果遇到模型 rate limit，把 `MODEL_REQUEST_INTERVAL_SECONDS` 调大到 `5` 或 `10`，或者把 `AI_BATCH_SIZE` 调小到 `4`。如果遇到上下文过长，把 `MODEL_INPUT_CHAR_BUDGET` 或 `README_MAX_CHARS` 调小。

如果 GitHub 拉 README 太慢，可以设置：

```env
README_FETCH_LIMIT=100
```

这样会只给前 100 个候选仓库拉 README，其余项目仍会用 repo metadata 和本地启发式规则参与评分。

如果你更关注 GitHub 爆款项目，推荐主检索用高 star 阈值降噪，再用 Trending 补充新增且增长快的项目：

```env
SKILL_SEARCH_MIN_STARS=1000
AGENT_SEARCH_MIN_STARS=2000
MAX_RESULTS_PER_QUERY=30
GITHUB_SEARCH_PAGES=2
ENABLE_GITHUB_TRENDING=1
GITHUB_TRENDING_PERIODS=daily,weekly
GITHUB_TRENDING_FETCH_LIMIT=25
FILTER_ARCHIVED_REPOS=1
FILTER_FORK_REPOS=1
CANDIDATE_MAX_PUSH_AGE_DAYS=730
README_FETCH_LIMIT=150
GITHUB_REQUEST_INTERVAL_SECONDS=0.3
GITHUB_SEARCH_REQUEST_INTERVAL_SECONDS=2.2
GITHUB_WAIT_ON_RATE_LIMIT=1
```

这套策略会显著减少低质量候选：历史成熟项目靠 `stars` 过滤，新项目靠 Trending 捕捉增长信号。页数和 Trending 元数据拉取都会增加 GitHub API 调用量，建议配合 `PERSONAL_ACCESS_TOKENS` 使用。

GitHub Search API 有独立限流，比普通 repo API 更严格。建议保持 `GITHUB_SEARCH_REQUEST_INTERVAL_SECONDS=2.2`，如果仍然遇到 rate limit，脚本会优先根据 `Retry-After` 或 `X-RateLimit-Reset` 等待后重试。想更稳，可以调到 `3` 或 `5`。

### 噪音过滤配置

候选项目入池前会先过滤明显噪音：

- GitHub Search 默认追加 `fork:false archived:false`
- 过滤 archived、fork、template、disabled 仓库
- 过滤最后 push 超过 `CANDIDATE_MAX_PUSH_AGE_DAYS` 的长期未维护仓库，默认 730 天
- 过滤仓库名或 topic 命中 `awesome`、`paper-list`、`dataset`、`demo`、`tutorial` 等明显非工具型项目

过滤统计会写入 `data/run-report.json` 的 `filtered_candidates` 和 `filter_reasons`。如果某个项目很重要，不希望被过滤，可以放进 `config/seeds.yaml`，seed 仓库会作为保底清单直接纳入。

### 调试日志

默认运行时会在终端输出阶段进度，并写入 `data/debug.log`。

如果你想看更细的 GitHub query、README、模型 batch 和 fallback 信息，在 `.env` 中打开：

```env
LOG_LEVEL=DEBUG
DEBUG_LOG_FILE=data/debug.log
```

然后运行：

```bash
python src/main.py sync
```

日志文件 `data/debug.log` 已加入 `.gitignore`，不会被提交。

### GitHub 查询配置

在 [`config/queries.yaml`](./config/queries.yaml) 中修改：

- Skill topics
- Agent topics
- keyword 搜索词

这是决定“抓什么仓库”的第一层入口。当前已按软件开发、自媒体（douyin / 视频号 / 小红书 / 公众号）、内容创作、视频处理、基金理财 / 投资研究等方向扩充 query。

在 [`config/seeds.yaml`](./config/seeds.yaml) 中维护必须纳入的仓库：

- 适合补救 GitHub Search 没排进前几页、但你确定值得追踪的热门项目
- 支持 `repo`、`kind_hint`、`category_hint`
- 例如 `geekjourneyx/md2wechat-skill` 会被直接通过 GitHub repo API 拉取，不依赖搜索命中

整体召回策略现在分四层：先用高 star query 找历史爆款，再用 GitHub Trending 补新增爆发项目，再用 `GITHUB_SEARCH_PAGES` 翻页提高召回，最后用 `config/seeds.yaml` 保底纳入重点仓库。

### 业务场景分类配置

在 [`config/taxonomy.yaml`](./config/taxonomy.yaml) 中修改：

- `skill_categories`
- `agent_categories`
- `install_methods`

当前分类采用统一业务场景 taxonomy，例如：

- `学习`
- `信息搜集`
- `知识管理`
- `内容创作`
- `视频处理`
- `办公协作`
- `数据分析`
- `投资研究`
- `软件开发`
- `产品设计`
- `市场营销`
- `安全攻防`
- `自动化运营`
- `其他`

### 启发式分类规则

如果你想改“没有模型 Key 时怎么分类”，看 [`src/main.py`](./src/main.py) 里的：

- `guess_category()`
- `build_fallback_solves()`

---

## GitHub Actions 配置

工作流文件在 [`.github/workflows/radar.yml`](./.github/workflows/radar.yml)。

在仓库 `Settings -> Secrets and variables -> Actions` 中至少配置：

Secrets：

- `PERSONAL_ACCESS_TOKENS`
- `MODEL_API_KEY`

可选：

- `PERSONAL_ACCESS_TOKEN`
- `GH_TOKEN`
- `MODEL_API_BASE`
- `MODEL_NAME`

Variables：

这些是非密钥调参项，可以放在 Actions Variables 中，也可以使用 workflow 里的默认值：

- `SKILL_SEARCH_MIN_STARS`
- `AGENT_SEARCH_MIN_STARS`
- `GITHUB_SEARCH_QUALIFIERS`
- `MAX_RESULTS_PER_QUERY`
- `GITHUB_SEARCH_PAGES`
- `ENABLE_GITHUB_TRENDING`
- `GITHUB_TRENDING_PERIODS`
- `GITHUB_TRENDING_FETCH_LIMIT`
- `FILTER_ARCHIVED_REPOS`
- `FILTER_FORK_REPOS`
- `FILTER_TEMPLATE_REPOS`
- `FILTER_DISABLED_REPOS`
- `CANDIDATE_MAX_PUSH_AGE_DAYS`
- `CANDIDATE_NOISE_TERMS`
- `README_FETCH_LIMIT`
- `README_MAX_CHARS`
- `GITHUB_REQUEST_INTERVAL_SECONDS`
- `GITHUB_SEARCH_REQUEST_INTERVAL_SECONDS`
- `GITHUB_WAIT_ON_RATE_LIMIT`
- `GITHUB_RATE_LIMIT_RETRIES`
- `GITHUB_RATE_LIMIT_MAX_WAIT_SECONDS`
- `AI_BATCH_SIZE`
- `MODEL_INPUT_CHAR_BUDGET`
- `MODEL_REQUEST_INTERVAL_SECONDS`

然后手动触发一次 `GitHub Skill Agent Radar Daily Sync`，确认：

- 能成功跑 `python src/main.py sync`
- 能提交 `data/` 和 `docs/data/`

---

## GitHub Pages 部署

推荐设置：

1. 仓库开启 GitHub Pages
2. Source 选择 `Deploy from a branch`
3. Branch 选择 `main`
4. Folder 选择 `/docs`

页面会读取：

- `docs/data/radar.json`
- `docs/data/brief.json`
- `docs/data/metadata.json`
- `docs/data/status.json`

---

## 如何让 Agent 使用

### 读取当前榜单

```bash
python skills/github-radar/scripts/radar_cli.py read-radar --root . --limit 5
```

如果你已经部署到 GitHub Pages：

```bash
python skills/github-radar/scripts/radar_cli.py read-radar --base-url https://OWNER.github.io/REPO --limit 5
```

### 给 Agent 的一句话

可以直接这样说：

```text
使用 github-radar，读取当前公开榜单，告诉我今天最值得关注的 5 个 Skill 或 Agent 项目，并说明为什么。
```

或者：

```text
使用 github-radar，运行完整同步：采集 GitHub 仓库、用配置的模型分析、重新评分，并导出 GitHub Pages 数据。
```

---

## 数据输出说明

主事实源：

- `data/radar.json`

调试与运行状态：

- `data/collected_repos.json`
- `data/run-report.json`

前端和 Agent 消费入口：

- `docs/data/radar.json`
- `docs/data/brief.json`
- `docs/data/metadata.json`
- `docs/data/status.json`

其中：

- `brief.json` 适合首屏和 Agent 快读
- `radar.json` 适合完整榜单与二次分析
- `status.json` 用于展示失败 query、rate limit 和 fallback

---

## 降级与失败处理

项目默认接受“有降级但不中断”的运行方式：

- GitHub README 404：继续使用 repo metadata
- GitHub rate limit：优先按 GitHub 返回的 reset 时间等待重试；超过最大等待或重试次数后，停止剩余 query 并保留已采集结果
- 模型超时或返回非 JSON：重试一次，失败后走本地启发式分类
- `brief.json` 为空：页面隐藏精选区，Agent 回退读取 `radar.json`
- 导出为空：默认拒绝覆盖旧数据，除非显式设置 `ALLOW_EMPTY_EXPORT=1`

---

## 常见问题

### 没有 `MODEL_API_KEY` 能跑吗？

可以。

`collect-only` 完全不依赖模型。

`sync` 没有模型 Key 时，会使用本地启发式分类并记录 fallback。

### 没有 GitHub personal access token 能跑吗？

可以，但很容易遇到 GitHub API rate limit。

建议始终配置 `PERSONAL_ACCESS_TOKENS`。

### 为什么页面建议用 `http.server` 打开？

因为 `docs/index.html` 会通过 `fetch()` 读取 JSON。很多浏览器在直接打开本地 `file://` 页面时会拦截这类请求。

---

## 安全说明

- 不要把 `.env`、token、API Key、cookie、私有邮箱内容、私有仓库数据提交进仓库
- 本地 `.env` 只用于本机运行，已被 `.gitignore` 忽略；`.env.*` 也默认忽略，只有 `.env.example` 可以提交
- GitHub Actions 中，`PERSONAL_ACCESS_TOKENS`、`MODEL_API_KEY` 等密钥只放 Secrets
- star 阈值、过滤规则、Trending 开关等非密钥配置放 Variables，或使用 workflow 默认值
- GitHub Pages 只发布 `docs/` 静态页面和 `docs/data/*.json`，这些 JSON 不应包含任何环境变量值
- 公开 JSON 中不应包含任何私密凭证

---

## 下一步可以扩展什么

- 增加更细的业务场景分类
- 引入缓存，减少重复调用模型
- 增加历史趋势和增量同步
- 接入更多 adoption 信号，例如包下载量
- 升级前端检索和趋势展示

---

## 相关文档

- [产品需求文档](./github_radar_prd.md)
- [技术架构设计](./github_radar_agent_architecture.md)
- [github-radar Skill 说明](./skills/github-radar/SKILL.md)
