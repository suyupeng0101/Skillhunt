"""GitHub Skill / Agent Radar 主采集管道。

这个脚本负责从 GitHub 发现候选仓库，并把它们整理成前端和 Agent 都能消费的 JSON：

1. 基于 `config/queries.yaml` 构造 GitHub Search 查询。
2. 用高 star 阈值、GitHub Trending、seed 清单三类来源召回候选仓库。
3. 在候选入池前过滤明显噪音，例如 archived/fork/template、长期未 push、awesome/demo/tutorial 类仓库。
4. 拉取 README 片段，补充安装方式、quickstart 等可用性信号。
5. 优先调用配置的 OpenAI-compatible 模型做分类和摘要；失败或未配置 Key 时走本地启发式兜底。
6. 按可用性、采用度、维护活跃度打分，并导出 `data/` 与 `docs/data/`。

代码刻意保持单文件 MVP 结构，方便在 GitHub Actions 中直接运行，也方便后续迁移为多模块。
"""

from __future__ import annotations

import argparse
import base64
import json
import logging
import math
import os
import random
import re
import sys
import time
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
import yaml
from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = ROOT / "config"
DATA_DIR = ROOT / "data"
DOCS_DATA_DIR = ROOT / "docs" / "data"

load_dotenv(ROOT / ".env")

# 版本号写入 metadata，便于前端或 Agent 判断当前数据结构是否兼容。
VERSION = "v1.0"

# Star 阈值分两层：
# - HIGH_POPULARITY_MIN_STARS / USABLE_TOOL_MIN_STARS 用于候选原因和评分信号。
# - SKILL_SEARCH_MIN_STARS / AGENT_SEARCH_MIN_STARS 用于 GitHub Search 主召回，默认更严格以减少噪音。
HIGH_POPULARITY_MIN_STARS = int(os.getenv("HIGH_POPULARITY_MIN_STARS", "1000"))
USABLE_TOOL_MIN_STARS = int(os.getenv("USABLE_TOOL_MIN_STARS", "300"))
SKILL_SEARCH_MIN_STARS = int(os.getenv("SKILL_SEARCH_MIN_STARS", "1000"))
AGENT_SEARCH_MIN_STARS = int(os.getenv("AGENT_SEARCH_MIN_STARS", "2000"))

# 追加到每条 GitHub Search query 的限定条件。默认过滤 fork 和 archived，可在 .env 中放宽。
GITHUB_SEARCH_QUALIFIERS = os.getenv("GITHUB_SEARCH_QUALIFIERS", "fork:false archived:false").strip()

# README 拉取和 GitHub Search 翻页都很消耗 API 配额，默认值偏保守；需要更高召回时再调大。
README_MAX_CHARS = int(os.getenv("README_MAX_CHARS", "4000"))
README_FETCH_LIMIT = int(os.getenv("README_FETCH_LIMIT", "0"))
MAX_RESULTS_PER_QUERY = int(os.getenv("MAX_RESULTS_PER_QUERY", "50"))
GITHUB_SEARCH_PAGES = int(os.getenv("GITHUB_SEARCH_PAGES", "1"))

# Trending 用来补足“新增且增长快”的项目，弥补纯 star 阈值对新项目不友好的问题。
ENABLE_GITHUB_TRENDING = os.getenv("ENABLE_GITHUB_TRENDING", "1") != "0"
GITHUB_TRENDING_PERIODS = [period.strip() for period in os.getenv("GITHUB_TRENDING_PERIODS", "daily,weekly").split(",") if period.strip()]
GITHUB_TRENDING_FETCH_LIMIT = int(os.getenv("GITHUB_TRENDING_FETCH_LIMIT", "25"))

# 候选过滤在 README 和模型调用前执行，目的是节省 GitHub/模型配额并降低无用结果。
FILTER_ARCHIVED_REPOS = os.getenv("FILTER_ARCHIVED_REPOS", "1") != "0"
FILTER_FORK_REPOS = os.getenv("FILTER_FORK_REPOS", "1") != "0"
FILTER_TEMPLATE_REPOS = os.getenv("FILTER_TEMPLATE_REPOS", "1") != "0"
FILTER_DISABLED_REPOS = os.getenv("FILTER_DISABLED_REPOS", "1") != "0"
CANDIDATE_MAX_PUSH_AGE_DAYS = int(os.getenv("CANDIDATE_MAX_PUSH_AGE_DAYS", "730"))
CANDIDATE_NOISE_TERMS = tuple(
    term.strip().lower()
    for term in os.getenv(
        "CANDIDATE_NOISE_TERMS",
        "awesome,curated-list,paper-list,papers,survey,benchmark,dataset,datasets,example,examples,demo,demos,tutorial,tutorials,course,courses",
    ).split(",")
    if term.strip()
)

# 模型批处理通过“条数 + 字符预算”双限制，避免触发上下文上限或速率限制。
AI_BATCH_SIZE = int(os.getenv("AI_BATCH_SIZE", "8"))
MODEL_INPUT_CHAR_BUDGET = int(os.getenv("MODEL_INPUT_CHAR_BUDGET", "90000"))
MODEL_MAX_TOKENS = int(os.getenv("MODEL_MAX_TOKENS", "4096"))

# 前端导出数量限制，避免页面和 JSON 过大。
SKILL_TOP_N = int(os.getenv("SKILL_TOP_N", "200"))
AGENT_TOP_N = int(os.getenv("AGENT_TOP_N", "200"))
RECOMMENDATION_MIN_SCORE = int(os.getenv("RECOMMENDATION_MIN_SCORE", "50"))
ANALYSIS_REPO_LIMIT = int(os.getenv("ANALYSIS_REPO_LIMIT", "0"))

# 网络和模型限速参数。GitHub 与模型分别节流，因为二者的限制策略不同。
HTTP_TIMEOUT = int(os.getenv("HTTP_TIMEOUT", "30"))
MODEL_HTTP_TIMEOUT = int(os.getenv("MODEL_HTTP_TIMEOUT", str(HTTP_TIMEOUT)))
GITHUB_REQUEST_INTERVAL_SECONDS = float(os.getenv("GITHUB_REQUEST_INTERVAL_SECONDS", "0.2"))
GITHUB_SEARCH_REQUEST_INTERVAL_SECONDS = float(os.getenv("GITHUB_SEARCH_REQUEST_INTERVAL_SECONDS", "2.2"))
GITHUB_WAIT_ON_RATE_LIMIT = os.getenv("GITHUB_WAIT_ON_RATE_LIMIT", "1") != "0"
GITHUB_RATE_LIMIT_RETRIES = int(os.getenv("GITHUB_RATE_LIMIT_RETRIES", "2"))
GITHUB_RATE_LIMIT_MAX_WAIT_SECONDS = float(os.getenv("GITHUB_RATE_LIMIT_MAX_WAIT_SECONDS", "120.0"))
MODEL_REQUEST_INTERVAL_SECONDS = float(os.getenv("MODEL_REQUEST_INTERVAL_SECONDS", "2.0"))
MODEL_MAX_RETRIES = int(os.getenv("MODEL_MAX_RETRIES", "1"))
MODEL_RETRY_BASE_SECONDS = float(os.getenv("MODEL_RETRY_BASE_SECONDS", "2.0"))
MODEL_RETRY_MAX_SECONDS = float(os.getenv("MODEL_RETRY_MAX_SECONDS", "60.0"))
MODEL_FAILURE_CIRCUIT_BREAKER = int(os.getenv("MODEL_FAILURE_CIRCUIT_BREAKER", "3"))
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
DEBUG_LOG_FILE = os.getenv("DEBUG_LOG_FILE", str(DATA_DIR / "debug.log"))

GITHUB_API = "https://api.github.com"
DEFAULT_MODEL_PROVIDER = "openai-compatible"
DEFAULT_MODEL_NAME = ""
DEFAULT_MODEL_API_BASE = ""
MODEL_PROVIDER = os.getenv("MODEL_PROVIDER") or os.getenv("AI_MODEL_PROVIDER") or ""
MODEL_NAME = os.getenv("MODEL_NAME") or os.getenv("MODEL") or ""
MODEL_API_BASE = os.getenv("MODEL_API_BASE") or ""
QUICKSTART_TERMS = (
    "quickstart",
    "quick start",
    "getting started",
    "usage",
    "example",
    "examples",
    "install",
    "installation",
    "run",
)

SEVERE_FLAGS = {"demo_only", "unclear_installation", "inactive_repo"}
LOGGER = logging.getLogger("github_radar")
HTTP_SESSION = requests.Session()
_LAST_GITHUB_REQUEST_AT = 0.0
_LAST_GITHUB_SEARCH_REQUEST_AT = 0.0
_LAST_MODEL_REQUEST_AT = 0.0


def setup_logging() -> None:
    """初始化终端日志和调试日志文件。

    终端日志等级受 `LOG_LEVEL` 控制；文件日志始终写 DEBUG，方便排查 GitHub query、
    README 拉取、模型 batch 和 fallback 细节。每次初始化都会清空旧 handler，避免测试或重复调用时重复输出。
    """
    level = getattr(logging, LOG_LEVEL, logging.INFO)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")

    stream_handler = logging.StreamHandler()
    stream_handler.setLevel(level)
    stream_handler.setFormatter(formatter)

    file_handler = logging.FileHandler(DEBUG_LOG_FILE, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)

    LOGGER.handlers.clear()
    LOGGER.setLevel(logging.DEBUG)
    LOGGER.addHandler(stream_handler)
    LOGGER.addHandler(file_handler)
    LOGGER.propagate = False


def add_warning(report_or_warnings: dict[str, Any] | list[str], message: str) -> None:
    """同时把 warning 写入运行报告和日志。

    有些调用点只有 warnings list，有些调用点拿到完整 report dict，所以这里兼容两种容器。
    """
    if isinstance(report_or_warnings, dict):
        report_or_warnings.setdefault("warnings", []).append(message)
    else:
        report_or_warnings.append(message)
    LOGGER.warning(message)


def throttle_requests(kind: str, interval_seconds: float) -> None:
    """对 GitHub API 和模型 API 分别做简单串行节流。

    当前管道刻意不用并发请求：GitHub Search、README、Trending 元数据和模型 API 都有速率限制，
    串行节流虽然慢一点，但更容易稳定跑完，也方便在 GitHub Actions 中排查失败原因。
    """
    global _LAST_GITHUB_REQUEST_AT, _LAST_GITHUB_SEARCH_REQUEST_AT, _LAST_MODEL_REQUEST_AT
    if interval_seconds <= 0:
        return
    now = time.monotonic()
    if kind == "model":
        last_request_at = _LAST_MODEL_REQUEST_AT
    elif kind == "github_search":
        last_request_at = _LAST_GITHUB_SEARCH_REQUEST_AT
    else:
        last_request_at = _LAST_GITHUB_REQUEST_AT
    wait_seconds = interval_seconds - (now - last_request_at)
    if wait_seconds > 0:
        LOGGER.debug("Throttling %s request for %.2fs", kind, wait_seconds)
        time.sleep(wait_seconds)
    if kind == "model":
        _LAST_MODEL_REQUEST_AT = time.monotonic()
    elif kind == "github_search":
        _LAST_GITHUB_SEARCH_REQUEST_AT = time.monotonic()
    else:
        _LAST_GITHUB_REQUEST_AT = time.monotonic()


def retry_after_seconds(response: requests.Response | None, attempt: int) -> float:
    """计算模型请求重试等待时间。

    优先尊重服务端 `Retry-After`；没有该 header 时使用指数退避并加入少量随机抖动，
    防止固定间隔反复撞到同一轮 rate limit 窗口。
    """
    if response is not None:
        retry_after = response.headers.get("Retry-After")
        if retry_after:
            try:
                return min(MODEL_RETRY_MAX_SECONDS, max(0.0, float(retry_after)))
            except ValueError:
                pass
    backoff = min(MODEL_RETRY_MAX_SECONDS, MODEL_RETRY_BASE_SECONDS * (2**attempt))
    return backoff + random.uniform(0, min(1.0, MODEL_RETRY_BASE_SECONDS))


def response_json_or_empty(response: requests.Response) -> dict[str, Any]:
    """Best-effort JSON parsing for API error responses."""
    try:
        payload = response.json()
    except ValueError:
        return {}
    return payload if isinstance(payload, dict) else {}


def is_github_rate_limited(response: requests.Response) -> bool:
    """Return True for primary or secondary GitHub rate-limit responses."""
    if response.status_code not in {403, 429}:
        return False
    if response.headers.get("X-RateLimit-Remaining") == "0":
        return True
    message = str(response_json_or_empty(response).get("message") or "").lower()
    return "rate limit" in message or "secondary rate" in message


def github_rate_limit_wait_seconds(response: requests.Response) -> float:
    """Calculate how long to wait before retrying a GitHub rate-limited request."""
    retry_after = response.headers.get("Retry-After")
    if retry_after:
        try:
            return max(0.0, float(retry_after))
        except ValueError:
            pass
    reset_at = response.headers.get("X-RateLimit-Reset")
    if reset_at:
        try:
            return max(0.0, float(reset_at) - time.time() + 1.0)
        except ValueError:
            pass
    return max(10.0, GITHUB_SEARCH_REQUEST_INTERVAL_SECONDS * 2)


def maybe_wait_for_github_rate_limit(response: requests.Response, report: dict[str, Any], context: str, attempt: int) -> bool:
    """Wait for a GitHub rate limit window if configured and the wait is acceptable."""
    if not is_github_rate_limited(response):
        return False
    wait_seconds = github_rate_limit_wait_seconds(response)
    if not GITHUB_WAIT_ON_RATE_LIMIT or attempt >= GITHUB_RATE_LIMIT_RETRIES or wait_seconds > GITHUB_RATE_LIMIT_MAX_WAIT_SECONDS:
        report["github_rate_limited"] = True
        add_warning(report, f"GitHub rate limit reached during {context}; stopped remaining queries.")
        return False
    report["github_rate_limit_waits"] = int(report.get("github_rate_limit_waits") or 0) + 1
    report["github_rate_limit_wait_seconds"] = round(float(report.get("github_rate_limit_wait_seconds") or 0.0) + wait_seconds, 2)
    add_warning(report, f"GitHub rate limit reached during {context}; waiting {wait_seconds:.1f}s before retry.")
    time.sleep(wait_seconds)
    return True


def model_error_code(response: requests.Response | None) -> str:
    """从 OpenAI-compatible 错误响应中尽量解析错误码。"""
    if response is None:
        return ""
    try:
        payload = response.json()
    except ValueError:
        return ""
    error = payload.get("error") if isinstance(payload, dict) else None
    if isinstance(error, dict):
        return str(error.get("code") or error.get("status") or "")
    if isinstance(payload, dict):
        return str(payload.get("code") or payload.get("status") or "")
    return ""


def is_retryable_model_error(exc: Exception) -> tuple[bool, requests.Response | None, str]:
    """判断模型调用异常是否值得重试。

    HTTP 429/5xx、网络错误，以及常见限流码 1302/1305 都视为可重试。
    非临时错误直接抛出，避免无意义等待。
    """
    response = exc.response if isinstance(exc, requests.HTTPError) else None
    if response is not None:
        code = model_error_code(response)
        if response.status_code in {408, 409, 429, 500, 502, 503, 504}:
            return True, response, code
        if code in {"1302", "1305"}:
            return True, response, code
        return False, response, code
    if isinstance(exc, requests.RequestException):
        return True, None, ""
    return False, None, ""


def is_model_timeout_error(exc: Exception) -> bool:
    """Return True for model request timeouts that should not spam stack traces."""
    return isinstance(exc, requests.Timeout) or "read timed out" in str(exc).lower()


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_yaml(path: Path) -> dict[str, Any]:
    """读取 YAML 配置文件；空文件按空 dict 处理。"""
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def load_config() -> tuple[dict[str, Any], dict[str, Any]]:
    """加载查询配置和分类 taxonomy。"""
    return load_yaml(CONFIG_DIR / "queries.yaml"), load_yaml(CONFIG_DIR / "taxonomy.yaml")


def github_token() -> str | None:
    """按兼容优先级读取 GitHub token。

    `PERSONAL_ACCESS_TOKENS` 是当前项目推荐名称；其它名称用于兼容 GitHub Actions、
    gh CLI 或早期配置。
    """
    return (
        os.getenv("PERSONAL_ACCESS_TOKENS")
        or os.getenv("PERSONAL_ACCESS_TOKEN")
        or os.getenv("GITHUB_PERSONAL_ACCESS_TOKEN")
        or os.getenv("GH_TOKEN")
        or os.getenv("GITHUB_TOKEN")
    )


def github_headers() -> dict[str, str]:
    """构造 GitHub API 请求头。未配置 token 时仍可请求，但更容易触发 rate limit。"""
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "github-skill-agent-radar",
    }
    token = github_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def normalize_model_provider(value: str | None) -> str:
    """Normalize model provider aliases used by local env and GitHub Actions."""
    provider = (value or "").strip().lower().replace("_", "-")
    aliases = {
        "sf": "siliconflow",
        "silicon-flow": "siliconflow",
    }
    return aliases.get(provider, provider)


def model_provider() -> str:
    """Return the configured model provider."""
    configured = normalize_model_provider(os.getenv("MODEL_PROVIDER") or os.getenv("AI_MODEL_PROVIDER") or MODEL_PROVIDER)
    if configured:
        return configured
    return DEFAULT_MODEL_PROVIDER


def model_name() -> str:
    """Return the chat-completions model name for the active provider."""
    generic = os.getenv("MODEL_NAME") or os.getenv("MODEL") or MODEL_NAME
    if generic:
        return generic
    return DEFAULT_MODEL_NAME


def model_api_base() -> str:
    """Return the OpenAI-compatible chat-completions endpoint."""
    generic = os.getenv("MODEL_API_BASE") or MODEL_API_BASE
    if generic:
        return generic
    return DEFAULT_MODEL_API_BASE


def model_api_key() -> str | None:
    """Read the API key for the active model provider."""
    generic_key = os.getenv("MODEL_API_KEY")
    provider = model_provider()
    if provider == "siliconflow":
        return generic_key or os.getenv("SILICONFLOW_API_KEY")
    return generic_key or os.getenv(f"{provider.upper().replace('-', '_')}_API_KEY")


def model_configured() -> bool:
    """Return True only when the generic chat-completions config is complete."""
    return bool(model_api_key() and model_api_base() and model_name())


def model_label() -> str:
    """Human-readable provider/model label for logs and warnings."""
    return f"{model_provider()}:{model_name()}"


def build_queries(config: dict[str, Any]) -> list[dict[str, str]]:
    """把 `config/queries.yaml` 转成 GitHub Search API 查询列表。

    Skill 和 Agent 使用不同 star 阈值：Skill 通常是小而专的能力单元，1000 stars 已经算强信号；
    Agent 框架/平台类项目更容易泛化和噪音更大，因此默认 2000 stars。
    """
    queries: list[dict[str, str]] = []
    for kind, min_stars in (("skill", SKILL_SEARCH_MIN_STARS), ("agent", AGENT_SEARCH_MIN_STARS)):
        section = config.get(kind, {})
        for topic in section.get("topics", []):
            query = f"topic:{topic} stars:>{min_stars}"
            if GITHUB_SEARCH_QUALIFIERS:
                query = f"{query} {GITHUB_SEARCH_QUALIFIERS}"
            queries.append(
                {
                    "kind_hint": kind.title(),
                    "label": f"topic:{topic}",
                    "query": query,
                }
            )
        for keyword in section.get("keywords", []):
            query = f'"{keyword}" stars:>{min_stars}'
            if GITHUB_SEARCH_QUALIFIERS:
                query = f"{query} {GITHUB_SEARCH_QUALIFIERS}"
            queries.append(
                {
                    "kind_hint": kind.title(),
                    "label": f"keyword:{keyword}",
                    "query": query,
                }
            )
    return queries


def load_seed_repos() -> list[dict[str, str]]:
    """读取必须纳入的仓库清单。

    seed 仓库绕过 GitHub Search 和噪音过滤，适合补救“很重要但搜索排名不靠前”的项目。
    支持两种写法：
    - `owner/repo`
    - `{repo, kind_hint, category_hint}`
    """
    path = CONFIG_DIR / "seeds.yaml"
    if not path.exists():
        return []
    payload = load_yaml(path)
    seeds: list[dict[str, str]] = []
    for entry in payload.get("repos", []):
        if isinstance(entry, str):
            seeds.append({"repo_name": entry, "kind_hint": "Skill", "label": f"seed:{entry}", "category_hint": ""})
        elif isinstance(entry, dict) and entry.get("repo"):
            repo_name = str(entry["repo"])
            seeds.append(
                {
                    "repo_name": repo_name,
                    "kind_hint": str(entry.get("kind_hint") or "Skill"),
                    "label": f"seed:{repo_name}",
                    "category_hint": str(entry.get("category_hint") or ""),
                }
            )
    return seeds


def request_json(url: str, *, params: dict[str, Any] | None = None, headers: dict[str, str] | None = None) -> requests.Response:
    """统一发起 GitHub 相关 GET 请求，并应用 GitHub 节流。"""
    if "/search/" in url:
        throttle_requests("github_search", GITHUB_SEARCH_REQUEST_INTERVAL_SECONDS)
    else:
        throttle_requests("github", GITHUB_REQUEST_INTERVAL_SECONDS)
    return HTTP_SESSION.get(url, params=params, headers=headers or github_headers(), timeout=HTTP_TIMEOUT)


def repo_push_age_days(item: dict[str, Any]) -> int | None:
    """计算仓库距离最后 push/update 的天数。

    GitHub Search 和 repo API 都会返回 `pushed_at`；如果缺失则退回 `updated_at`。
    返回 None 表示无法解析，此时不过滤，避免因为 GitHub 响应缺字段误杀。
    """
    pushed_at = item.get("pushed_at") or item.get("updated_at")
    parsed = parse_iso_datetime(pushed_at)
    if not parsed:
        return None
    return max(0, (datetime.now(timezone.utc) - parsed).days)


def repo_name_has_noise_term(item: dict[str, Any]) -> str:
    """检查仓库名或 topic 是否命中明显噪音词。

    这里故意只看 repo slug 和 topics，不看 description。description 中出现 demo/tutorial
    可能只是说明有示例，不一定代表项目本身是 demo；仓库名和 topic 更适合做强过滤。
    """
    full_name = str(item.get("full_name") or "").lower()
    repo_slug = full_name.split("/")[-1]
    topics = {str(topic).lower() for topic in item.get("topics") or []}
    slug_tokens = {token for token in re.split(r"[^a-z0-9]+", repo_slug) if token}
    for term in CANDIDATE_NOISE_TERMS:
        normalized = term.replace("_", "-")
        term_tokens = {token for token in re.split(r"[^a-z0-9]+", normalized) if token}
        if normalized in topics or normalized == repo_slug:
            return term
        if term_tokens and term_tokens <= slug_tokens:
            return term
        if repo_slug.startswith(f"{normalized}-") or repo_slug.endswith(f"-{normalized}"):
            return term
    return ""


def candidate_noise_reason(item: dict[str, Any]) -> str:
    """返回候选应被过滤的原因；空字符串表示保留。

    过滤发生在 README 拉取和模型分析之前，用来节省 API 配额。seed 仓库不走这里，
    因为 seed 的语义是“用户明确要求保底纳入”。
    """
    if FILTER_ARCHIVED_REPOS and item.get("archived"):
        return "archived_repo"
    if FILTER_FORK_REPOS and item.get("fork"):
        return "fork_repo"
    if FILTER_TEMPLATE_REPOS and item.get("is_template"):
        return "template_repo"
    if FILTER_DISABLED_REPOS and item.get("disabled"):
        return "disabled_repo"
    if CANDIDATE_MAX_PUSH_AGE_DAYS > 0:
        age_days = repo_push_age_days(item)
        if age_days is not None and age_days > CANDIDATE_MAX_PUSH_AGE_DAYS:
            return "stale_repo"
    noise_term = repo_name_has_noise_term(item)
    if noise_term:
        return f"noise_term:{noise_term}"
    return ""


def record_filtered_candidate(report: dict[str, Any], reason: str, repo_name: str) -> None:
    """记录过滤统计，便于在 `run-report.json` 和 `status.json` 中观察噪音来源。"""
    report["filtered_candidates"] = int(report.get("filtered_candidates") or 0) + 1
    reasons = report.setdefault("filter_reasons", {})
    reasons[reason] = int(reasons.get(reason) or 0) + 1
    LOGGER.debug("Candidate filtered: repo=%s reason=%s", repo_name, reason)


def normalize_repo(item: dict[str, Any], query_meta: dict[str, str]) -> dict[str, Any]:
    """把 GitHub API 原始仓库对象规范化为管道内部统一结构。

    后续 README、AI 分析、评分和导出都依赖这个结构。`query_meta` 用来记录候选来自哪条 query、
    seed 或 Trending，并携带 kind/category hint。
    """
    owner = item.get("owner") or {}
    full_name = item.get("full_name", "")
    topics = item.get("topics") or []
    stars = int(item.get("stargazers_count") or 0)
    candidate_reason = []
    if stars >= HIGH_POPULARITY_MIN_STARS:
        candidate_reason.append("high_popularity")
    if stars >= USABLE_TOOL_MIN_STARS and query_meta["kind_hint"] == "Skill":
        candidate_reason.append("usable_tool_signal")
    if "mcp" in topics or "cli" in topics:
        candidate_reason.append("installable_topic_signal")
    candidate_reason.append(query_meta["label"])

    return {
        "repo_id": item.get("id"),
        "repo_name": full_name,
        "owner": owner.get("login") or full_name.split("/")[0],
        "description": item.get("description") or "",
        "initial_kind": query_meta["kind_hint"],
        "matched_queries": [query_meta["label"]],
        "candidate_reason": sorted(set(candidate_reason)),
        "category_hint": query_meta.get("category_hint", ""),
        "stars": stars,
        "forks": int(item.get("forks_count") or 0),
        "watchers": int(item.get("watchers_count") or 0),
        "open_issues": int(item.get("open_issues_count") or 0),
        "archived": bool(item.get("archived")),
        "fork": bool(item.get("fork")),
        "is_template": bool(item.get("is_template")),
        "disabled": bool(item.get("disabled")),
        "language": item.get("language") or "",
        "topics": topics,
        "url": item.get("html_url") or f"https://github.com/{full_name}",
        "pushed_at": item.get("pushed_at"),
        "updated_at": item.get("updated_at"),
        "readme_snippet": "",
    }


def fetch_seed_repos(seeds: list[dict[str, str]], report: dict[str, Any]) -> list[dict[str, Any]]:
    """按 `owner/repo` 直接拉取 seed 仓库元数据。

    seed 是最后一道召回兜底，不依赖 GitHub Search 排名，也不走噪音过滤。这样像
    `md2wechat-skill` 这类明确重要但 query 可能漏掉的项目仍会进入结果。
    """
    if not seeds:
        return []
    repos = []
    headers = github_headers()
    LOGGER.info("Fetching seed repositories: count=%s", len(seeds))
    for seed in seeds:
        repo_name = seed["repo_name"]
        try:
            response = request_json(f"{GITHUB_API}/repos/{repo_name}", headers=headers)
        except requests.RequestException as exc:
            add_warning(report, f"Seed repo fetch failed: {repo_name} ({exc.__class__.__name__})")
            continue
        if response.status_code == 403 and response.headers.get("X-RateLimit-Remaining") == "0":
            report["github_rate_limited"] = True
            add_warning(report, "GitHub rate limit reached while fetching seed repositories.")
            break
        if not response.ok:
            add_warning(report, f"Seed repo fetch failed: {repo_name} (HTTP {response.status_code})")
            continue
        meta = {
            "kind_hint": seed.get("kind_hint", "Skill"),
            "label": seed.get("label", f"seed:{repo_name}"),
            "category_hint": seed.get("category_hint", ""),
        }
        candidate = normalize_repo(response.json(), meta)
        candidate["candidate_reason"] = sorted(set(candidate.get("candidate_reason", []) + ["seed_repo"]))
        repos.append(candidate)
    LOGGER.info("Seed repository fetch completed: fetched=%s", len(repos))
    return repos


def parse_trending_repo_names(html: str) -> list[str]:
    """从 GitHub Trending HTML 页面中解析 `owner/repo`。

    GitHub 没有公开稳定的 Trending JSON API，因此这里用轻量 HTML 解析。只提取 repo 链接，
    具体元数据仍通过 GitHub repo API 获取，避免依赖页面上的非结构化信息。
    """
    names: list[str] = []
    for article in re.findall(r"<article\b.*?</article>", html, flags=re.DOTALL | re.IGNORECASE):
        match = re.search(r'href="/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)"', article)
        if match:
            repo_name = match.group(1)
            if repo_name not in names:
                names.append(repo_name)
    return names


def relevance_terms(config: dict[str, Any]) -> set[str]:
    """从 query 配置中提取 Trending 相关性判断词。

    Trending 覆盖全站热门项目，如果不做相关性过滤，会混入大量非 AI Skill/Agent 项目。
    """
    terms: set[str] = set()
    for section_name in ("skill", "agent"):
        section = config.get(section_name, {})
        for value in section.get("topics", []) + section.get("keywords", []):
            normalized = str(value).strip().lower()
            if normalized:
                terms.add(normalized)
                terms.update(part for part in re.split(r"[-_\s/]+", normalized) if len(part) >= 3)
    return terms


def is_relevant_trending_repo(item: dict[str, Any], terms: set[str]) -> bool:
    """判断 Trending 仓库是否和当前 radar 的领域相关。"""
    blob = " ".join(
        [
            item.get("full_name", ""),
            item.get("description") or "",
            " ".join(item.get("topics") or []),
            item.get("language") or "",
        ]
    ).lower()
    return any(term and term in blob for term in terms)


def infer_trending_kind(item: dict[str, Any]) -> str:
    """给 Trending 仓库推断初始 kind。

    Trending 来源没有明确的 skill/agent query hint，因此先用名称、描述和 topic 做粗判断，
    后续模型或本地启发式还会进一步校正。
    """
    blob = " ".join(
        [
            item.get("full_name", ""),
            item.get("description") or "",
            " ".join(item.get("topics") or []),
        ]
    ).lower()
    if matches_any(blob, ("skill", "skills", "claude-skill", "claude-skills", "codex-skill", "mcp", "cli")):
        return "Skill"
    return "Agent"


def fetch_trending_repos(config: dict[str, Any], report: dict[str, Any]) -> list[dict[str, Any]]:
    """抓取 GitHub Trending 作为增长型项目补充来源。

    主搜索依赖 star 阈值，容易错过新近爆发但总 star 尚未很高的项目；Trending 正好补这个缺口。
    流程是：Trending HTML -> repo 名称 -> GitHub repo API 元数据 -> 相关性过滤 -> 噪音过滤。
    """
    if not ENABLE_GITHUB_TRENDING:
        return []
    terms = relevance_terms(config)
    if not terms:
        return []

    report["trending_enabled"] = True
    report["trending_periods"] = GITHUB_TRENDING_PERIODS
    report.setdefault("trending_repos_seen", 0)
    report.setdefault("trending_repos_added", 0)
    repos: list[dict[str, Any]] = []
    headers = github_headers()
    trending_headers = github_headers()
    trending_headers["Accept"] = "text/html,application/xhtml+xml"

    LOGGER.info(
        "Fetching GitHub Trending repositories: periods=%s limit=%s",
        GITHUB_TRENDING_PERIODS,
        GITHUB_TRENDING_FETCH_LIMIT,
    )
    for period in GITHUB_TRENDING_PERIODS:
        try:
            response = request_json("https://github.com/trending", params={"since": period}, headers=trending_headers)
        except requests.RequestException as exc:
            add_warning(report, f"GitHub Trending fetch failed: {period} ({exc.__class__.__name__})")
            continue
        if not response.ok:
            add_warning(report, f"GitHub Trending fetch failed: {period} (HTTP {response.status_code})")
            continue

        repo_names = parse_trending_repo_names(response.text)[:GITHUB_TRENDING_FETCH_LIMIT]
        report["trending_repos_seen"] += len(repo_names)
        LOGGER.info("GitHub Trending period fetched: period=%s repos=%s", period, len(repo_names))
        for repo_name in repo_names:
            try:
                repo_response = request_json(f"{GITHUB_API}/repos/{repo_name}", headers=headers)
            except requests.RequestException as exc:
                add_warning(report, f"Trending repo metadata fetch failed: {repo_name} ({exc.__class__.__name__})")
                continue
            if repo_response.status_code == 403 and repo_response.headers.get("X-RateLimit-Remaining") == "0":
                report["github_rate_limited"] = True
                add_warning(report, "GitHub rate limit reached while fetching Trending repositories.")
                return repos
            if not repo_response.ok:
                add_warning(report, f"Trending repo metadata fetch failed: {repo_name} (HTTP {repo_response.status_code})")
                continue

            item = repo_response.json()
            if not is_relevant_trending_repo(item, terms):
                LOGGER.debug("Trending repo skipped as irrelevant: %s", repo_name)
                continue
            noise_reason = candidate_noise_reason(item)
            if noise_reason:
                record_filtered_candidate(report, noise_reason, repo_name)
                continue
            meta = {
                "kind_hint": infer_trending_kind(item),
                "label": f"trending:{period}",
                "category_hint": "",
            }
            candidate = normalize_repo(item, meta)
            candidate["candidate_reason"] = sorted(
                set(candidate.get("candidate_reason", []) + ["github_trending", f"trending:{period}"])
            )
            repos.append(candidate)
            report["trending_repos_added"] += 1
    LOGGER.info("GitHub Trending fetch completed: added=%s seen=%s", report["trending_repos_added"], report["trending_repos_seen"])
    return repos


def merge_candidate(existing: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    """合并同一仓库从多条 query/seed/Trending 命中的信息。

    多来源命中会提高可解释性：`matched_queries` 和 `candidate_reason` 会保留所有来源；
    star 等动态字段使用更新、更高 star 的那份数据。
    """
    merged = deepcopy(existing)
    merged["matched_queries"] = sorted(set(existing.get("matched_queries", []) + incoming.get("matched_queries", [])))
    merged["candidate_reason"] = sorted(set(existing.get("candidate_reason", []) + incoming.get("candidate_reason", [])))
    merged["topics"] = sorted(set(existing.get("topics", []) + incoming.get("topics", [])))
    if incoming.get("category_hint") and not existing.get("category_hint"):
        merged["category_hint"] = incoming.get("category_hint")
    if incoming.get("stars", 0) > existing.get("stars", 0):
        for field in ("stars", "forks", "watchers", "open_issues", "pushed_at", "updated_at", "description"):
            merged[field] = incoming.get(field, merged.get(field))
    return merged


def search_repos(queries: list[dict[str, str]], queries_config: dict[str, Any] | None = None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """执行完整候选召回阶段。

    顺序是：
    1. GitHub Search 主召回，按 star 排序并翻页。
    2. Trending 补充增长型项目。
    3. seed 清单兜底纳入重点仓库。

    函数返回候选列表和运行报告；报告中包含失败 query、rate limit、过滤统计等调试信息。
    """
    by_id: dict[int, dict[str, Any]] = {}
    report = {
        "query_count": len(queries),
        "search_pages": GITHUB_SEARCH_PAGES,
        "queries": [],
        "failed_queries": [],
        "github_rate_limited": False,
        "filtered_candidates": 0,
        "filter_reasons": {},
        "warnings": [],
    }
    headers = github_headers()
    LOGGER.info("Starting GitHub repository search: queries=%s pages=%s max_results_per_query=%s token_configured=%s", len(queries), GITHUB_SEARCH_PAGES, MAX_RESULTS_PER_QUERY, bool(github_token()))

    for query_meta in queries:
        LOGGER.info("GitHub query started: %s", query_meta["query"])
        query_total = 0
        query_failed = False
        for page in range(1, max(1, GITHUB_SEARCH_PAGES) + 1):
            params = {
                "q": query_meta["query"],
                "sort": "stars",
                "order": "desc",
                "per_page": MAX_RESULTS_PER_QUERY,
                "page": page,
            }
            response = None
            for attempt in range(GITHUB_RATE_LIMIT_RETRIES + 1):
                try:
                    response = request_json(f"{GITHUB_API}/search/repositories", params=params, headers=headers)
                except requests.RequestException as exc:
                    report["failed_queries"].append(query_meta["label"])
                    add_warning(report, f"GitHub query failed: {query_meta['label']} page {page} ({exc.__class__.__name__})")
                    query_failed = True
                    break
                if maybe_wait_for_github_rate_limit(response, report, f"search {query_meta['label']} page {page}", attempt):
                    continue
                break

            if response is None:
                break
            if is_github_rate_limited(response):
                report["failed_queries"].append(query_meta["label"])
                query_failed = True
                break
            if not response.ok:
                report["failed_queries"].append(query_meta["label"])
                add_warning(report, f"GitHub query failed: {query_meta['label']} page {page} (HTTP {response.status_code})")
                query_failed = True
                break

            payload = response.json()
            items = payload.get("items", [])
            query_total += len(items)
            LOGGER.info("GitHub query page finished: label=%s page=%s status=%s count=%s remaining=%s", query_meta["label"], page, response.status_code, len(items), response.headers.get("X-RateLimit-Remaining"))
            for item in items:
                noise_reason = candidate_noise_reason(item)
                if noise_reason:
                    record_filtered_candidate(report, noise_reason, item.get("full_name", ""))
                    continue
                candidate = normalize_repo(item, query_meta)
                repo_id = candidate.get("repo_id")
                if repo_id is None:
                    continue
                by_id[repo_id] = merge_candidate(by_id[repo_id], candidate) if repo_id in by_id else candidate
            if len(items) < MAX_RESULTS_PER_QUERY:
                break
        if query_failed and report["github_rate_limited"]:
            break
        report["queries"].append(
            {
                "label": query_meta["label"],
                "query": query_meta["query"],
                "count": query_total,
            }
        )

    if queries_config and not report.get("github_rate_limited"):
        for candidate in fetch_trending_repos(queries_config, report):
            repo_id = candidate.get("repo_id")
            if repo_id is None:
                continue
            by_id[repo_id] = merge_candidate(by_id[repo_id], candidate) if repo_id in by_id else candidate

    for candidate in fetch_seed_repos(load_seed_repos(), report):
        repo_id = candidate.get("repo_id")
        if repo_id is None:
            continue
        by_id[repo_id] = merge_candidate(by_id[repo_id], candidate) if repo_id in by_id else candidate

    repos = sorted(by_id.values(), key=lambda item: item.get("stars", 0), reverse=True)
    LOGGER.info("GitHub repository search completed: unique_repos=%s failed_queries=%s rate_limited=%s", len(repos), len(report["failed_queries"]), report["github_rate_limited"])
    return repos, report


def fetch_readme_snippet(repo: dict[str, Any], warnings: list[str]) -> str:
    """拉取仓库 README 的前 `README_MAX_CHARS` 字符。

    README 是判断安装方式、quickstart、demo 风险的重要信号。为了控制上下文长度，只截取开头片段；
    多数项目的安装和使用说明也通常在 README 前半部分。
    """
    repo_name = repo.get("repo_name")
    if not repo_name:
        return ""
    url = f"{GITHUB_API}/repos/{repo_name}/readme"
    headers = github_headers()
    headers["Accept"] = "application/vnd.github.raw"
    try:
        response = request_json(url, headers=headers)
    except requests.RequestException:
        add_warning(warnings, f"README fetch failed: {repo_name}")
        return ""
    if response.status_code == 404:
        LOGGER.debug("README not found: %s", repo_name)
        return ""
    if not response.ok:
        add_warning(warnings, f"README fetch failed: {repo_name} (HTTP {response.status_code})")
        return ""

    text = response.text
    if not text and response.headers.get("content-type", "").startswith("application/json"):
        payload = response.json()
        content = payload.get("content", "")
        if content:
            text = base64.b64decode(content).decode("utf-8", errors="ignore")
    snippet = text[:README_MAX_CHARS]
    LOGGER.debug("README fetched: repo=%s chars=%s", repo_name, len(snippet))
    return snippet


def attach_readmes(repos: list[dict[str, Any]], warnings: list[str]) -> list[dict[str, Any]]:
    """给候选仓库补充 README 片段，并根据 README 增加可安装信号。

    `README_FETCH_LIMIT` 可限制拉取数量。未拉 README 的项目仍会参与后续分析，但会打上
    `readme_fetch_skipped`，便于解释评分不确定性。
    """
    enriched = []
    limit = README_FETCH_LIMIT if README_FETCH_LIMIT > 0 else len(repos)
    LOGGER.info("Fetching README snippets: repos=%s limit=%s max_chars=%s", len(repos), limit, README_MAX_CHARS)
    for index, repo in enumerate(repos):
        item = deepcopy(repo)
        if index < limit:
            item["readme_snippet"] = fetch_readme_snippet(item, warnings)
        else:
            item["readme_snippet"] = ""
            item["candidate_reason"] = sorted(set(item.get("candidate_reason", []) + ["readme_fetch_skipped"]))
        if item["readme_snippet"] and has_install_signal(item["readme_snippet"]):
            item["candidate_reason"] = sorted(set(item.get("candidate_reason", []) + ["installable_signal"]))
        enriched.append(item)
    LOGGER.info("README fetch completed: repos=%s warnings=%s", len(enriched), len(warnings))
    return enriched


def limit_repos_for_analysis(repos: list[dict[str, Any]], report: dict[str, Any]) -> list[dict[str, Any]]:
    """Limit expensive README/model work while keeping explicit seed repositories."""
    report["analysis_repo_limit"] = ANALYSIS_REPO_LIMIT
    report["collected_before_analysis_limit"] = len(repos)
    if ANALYSIS_REPO_LIMIT <= 0 or len(repos) <= ANALYSIS_REPO_LIMIT:
        report["analysis_repo_limit_applied"] = False
        return repos

    selected: list[dict[str, Any]] = []
    selected_ids: set[Any] = set()

    for repo in repos:
        if "seed_repo" not in set(repo.get("candidate_reason") or []):
            continue
        repo_id = repo.get("repo_id")
        if repo_id in selected_ids:
            continue
        selected.append(repo)
        selected_ids.add(repo_id)

    for repo in repos:
        if len(selected) >= ANALYSIS_REPO_LIMIT:
            break
        repo_id = repo.get("repo_id")
        if repo_id in selected_ids:
            continue
        selected.append(repo)
        selected_ids.add(repo_id)

    selected = sorted(selected, key=lambda item: item.get("stars", 0), reverse=True)
    report["analysis_repo_limit_applied"] = True
    report["analysis_repo_limit_selected"] = len(selected)
    add_warning(report, f"Analysis repo limit applied: selected {len(selected)} of {len(repos)} collected repositories.")
    LOGGER.info("Analysis repository limit applied: collected=%s selected=%s limit=%s", len(repos), len(selected), ANALYSIS_REPO_LIMIT)
    return selected


def lower_blob(repo: dict[str, Any]) -> str:
    """把仓库主要文本字段拼成小写文本块，供启发式匹配复用。"""
    return " ".join(
        [
            repo.get("repo_name", ""),
            repo.get("description", ""),
            " ".join(repo.get("topics", [])),
            repo.get("readme_snippet", ""),
        ]
    ).lower()


def contains_term(blob: str, term: str) -> bool:
    """判断文本块是否包含词项。

    对短英文词使用单词边界，避免例如 `ai`、`cli` 这类短词误匹配到更长单词内部。
    """
    lowered = term.lower()
    if re.fullmatch(r"[a-z0-9_+-]+", lowered) and len(lowered) <= 4:
        pattern = rf"(?<![a-z0-9]){re.escape(lowered)}(?![a-z0-9])"
        return re.search(pattern, blob) is not None
    return lowered in blob


def matches_any(blob: str, terms: tuple[str, ...]) -> bool:
    """判断文本块是否命中任意关键词。"""
    return any(contains_term(blob, term) for term in terms)


def has_install_signal(text: str) -> bool:
    """根据 README 片段判断是否存在明确安装/运行入口。"""
    blob = text.lower()
    return any(term in blob for term in ("npm install", "pip install", "uvx", "npx", "docker", "mcp", "cli", "github release"))


def has_quickstart_signal(repo: dict[str, Any]) -> bool:
    """判断仓库是否有 quickstart/usage/example 等快速上手信号。"""
    blob = lower_blob(repo)
    return any(term in blob for term in QUICKSTART_TERMS)


def find_install_methods(repo: dict[str, Any], taxonomy: dict[str, Any]) -> list[str]:
    """根据 taxonomy 中的安装信号识别 npm/pypi/docker/mcp/cli 等安装方式。"""
    blob = lower_blob(repo)
    methods = []
    for method, terms in (taxonomy.get("install_methods") or {}).items():
        if any(term.lower() in blob for term in terms):
            methods.append(method)
    return sorted(set(methods))


def guess_kind(repo: dict[str, Any]) -> str:
    """本地启发式判断仓库是 Skill 还是 Agent。

    这里优先看 topics 和强关键词；如果无法判断，则退回 GitHub query 带来的 `initial_kind`。
    """
    blob = lower_blob(repo)
    topics = set(repo.get("topics", []))
    if {"agent-skill", "agent-skills", "claude-skill", "claude-skills", "codex-skill", "skill", "skills"} & topics:
        return "Skill"
    if "agent" in blob or {"ai-agent", "llm-agent", "autonomous-agent", "agent-framework"} & topics:
        return "Agent"
    if "mcp" in topics or "model context protocol" in blob:
        return "Skill"
    return repo.get("initial_kind", "Agent")


def guess_category(repo: dict[str, Any], kind: str) -> str:
    """本地启发式业务场景分类。

    这个函数是没有模型 Key、模型调用失败、或 AI 返回非法分类时的兜底。分类必须返回 taxonomy
    中存在的中文业务场景，保证前端筛选和导出结构稳定。
    """
    blob = lower_blob(repo)

    if matches_any(blob, ("tutorial", "course", "learn", "book", "education", "guide", "interview", "training")):
        return "学习"
    if matches_any(
        blob,
        (
            "knowledge base",
            "notebooklm",
            "memory",
            "rag",
            "notes",
            "second brain",
            "wiki",
            "document store",
            "knowledge hub",
            "知识库",
            "记忆",
            "笔记",
        )
    ):
        return "知识管理"
    if matches_any(
        blob,
        (
            "video",
            "subtitle",
            "transcript",
            "transcription",
            "youtube",
            "tiktok",
            "bilibili",
            "podcast",
            "ffmpeg",
            "剪辑",
            "字幕",
            "视频",
        )
    ):
        return "视频处理"
    if matches_any(
        blob,
        (
            "stock",
            "finance",
            "financial",
            "fund",
            "trading",
            "invest",
            "investment",
            "market data",
            "portfolio",
            "alpha",
            "quant",
            "基金",
            "投资",
            "股票",
        )
    ):
        return "投资研究"
    if matches_any(
        blob,
        (
            "dashboard",
            "analytics",
            "analysis",
            "bi",
            "sql",
            "warehouse",
            "metrics",
            "reporting",
            "insight",
            "dataset",
            "数据分析",
            "报表",
        )
    ):
        return "数据分析"
    if matches_any(
        blob,
        (
            "calendar",
            "meeting",
            "email",
            "docs",
            "spreadsheet",
            "office",
            "workspace",
            "document processing",
            "pptx",
            "word",
            "协作",
            "办公",
            "文档处理",
        )
    ):
        return "办公协作"
    if matches_any(
        blob,
        (
            "content",
            "copywriting",
            "writing",
            "blog",
            "presentation",
            "slides",
            "ppt",
            "image",
            "poster",
            "social card",
            "creative",
            "deck",
            "内容",
            "文案",
            "海报",
        )
    ):
        return "内容创作"
    if matches_any(
        blob,
        (
            "ui",
            "ux",
            "design system",
            "prototype",
            "wireframe",
            "figma",
            "视觉",
            "原型",
            "交互设计",
            "design",
        )
    ):
        return "产品设计"
    if matches_any(
        blob,
        (
            "marketing",
            "growth",
            "seo",
            "campaign",
            "social media",
            "lead generation",
            "crm",
            "广告",
            "营销",
            "投放",
            "获客",
        )
    ):
        return "市场营销"
    if matches_any(
        blob,
        (
            "security",
            "pentest",
            "vulnerability",
            "scan",
            "scanner",
            "exploit",
            "attack",
            "defense",
            "soc",
            "渗透",
            "漏洞",
            "安全",
            "攻防",
        )
    ):
        return "安全攻防"
    if matches_any(
        blob,
        (
            "research",
            "paper",
            "crawler",
            "scrape",
            "search",
            "map",
            "extract",
            "collect",
            "信息收集",
            "采集",
            "搜索",
        )
    ):
        return "信息搜集"
    if matches_any(
        blob,
        (
            "browser automation",
            "playwright",
            "selenium",
            "desktop automation",
            "workflow automation",
            "form filling",
            "workflow",
            "approval flow",
            "rpa",
            "自动化",
            "流程",
        )
    ):
        return "自动化运营"
    if matches_any(
        blob,
        (
            "code",
            "coding",
            "developer",
            "debug",
            "pull request",
            "software engineer",
            "framework",
            "multi-agent",
            "autonomous",
            "orchestration",
            "mcp",
            "model context protocol",
            "cli",
            "plugin",
            "extension",
            "sdk",
            "library",
            "package",
            "starter",
            "template",
            "boilerplate",
            "开发",
            "编程",
            "代码",
        )
    ):
        return "软件开发"
    return "其他"


def fallback_analysis(repo: dict[str, Any], taxonomy: dict[str, Any], reason: str = "heuristic_fallback") -> dict[str, Any]:
    """在模型不可用或模型漏返回时生成本地分析结果。

    fallback 结果会带 `heuristic_fallback` 标记，前端和 Agent 可以据此知道该条结果置信度较低。
    如果 seed/query 提供了有效 `category_hint`，会优先使用 hint。
    """
    kind = guess_kind(repo)
    allowed_categories = taxonomy.get("skill_categories" if kind == "Skill" else "agent_categories", [])
    category = repo.get("category_hint") if repo.get("category_hint") in allowed_categories else guess_category(repo, kind)
    methods = find_install_methods(repo, taxonomy)
    flags = []
    if not has_quickstart_signal(repo):
        flags.append("no_quickstart")
    if not methods:
        flags.append("unclear_installation")
    if "demo" in lower_blob(repo) and "framework" not in lower_blob(repo):
        flags.append("demo_only")

    summary_source = repo.get("description") or f"{repo.get('repo_name')} 的 GitHub 开源项目。"
    return {
        "repo_id": repo.get("repo_id"),
        "kind": kind,
        "kind_confidence": 0.62 if reason == "heuristic_fallback" else 0.5,
        "category": category,
        "summary": summary_source[:160],
        "use_case": build_fallback_use_case(repo, kind),
        "solves": build_fallback_solves(repo, kind),
        "install_methods": methods,
        "usability_flags": sorted(set(flags + [reason])),
    }


def build_fallback_use_case(repo: dict[str, Any], kind: str) -> str:
    """为本地 fallback 生成通用使用场景描述。"""
    if kind == "Skill":
        return "适合需要快速评估、安装或复用单一 Agent 能力单元的场景。"
    return "适合评估 AI Agent 框架、自动化应用或可二次开发的智能体项目。"


def build_fallback_solves(repo: dict[str, Any], kind: str) -> list[str]:
    """根据业务分类生成 fallback 的痛点标签。"""
    category = repo.get("category_hint") or guess_category(repo, kind)
    if category == "学习":
        return ["知识获取", "学习路径整理"]
    if category == "信息搜集":
        return ["资料收集", "信息提取"]
    if category == "知识管理":
        return ["知识沉淀", "上下文管理"]
    if category == "内容创作":
        return ["内容生成", "素材制作"]
    if category == "视频处理":
        return ["视频内容处理", "字幕与转录"]
    if category == "办公协作":
        return ["文档协作", "团队办公提效"]
    if category == "数据分析":
        return ["数据洞察", "分析提效"]
    if category == "投资研究":
        return ["市场信息分析", "投资研究辅助"]
    if category == "产品设计":
        return ["原型与设计产出", "设计协作"]
    if category == "市场营销":
        return ["营销内容生成", "增长运营支持"]
    if category == "安全攻防":
        return ["风险识别", "安全测试辅助"]
    if category == "自动化运营":
        return ["流程自动执行", "重复工作自动化"]
    if category == "软件开发":
        return ["代码生成", "开发效率提升"]
    if kind == "Skill":
        return ["能力复用", "Agent 工具扩展"]
    return ["智能体开发", "任务自动化"]


def extract_json_array(text: str) -> list[dict[str, Any]]:
    """从模型响应中提取 JSON 数组。

    模型有时会返回裸数组，有时会返回 `{items: [...]}`，也可能包在 markdown fence 中。
    这里统一解析成 list[dict]，解析失败会触发上层 fallback。
    """
    cleaned = text.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", cleaned, re.DOTALL | re.IGNORECASE)
    if fenced:
        cleaned = fenced.group(1).strip()
    if not cleaned.startswith(("[", "{")):
        object_start = cleaned.find("{")
        object_end = cleaned.rfind("}")
        if object_start != -1 and object_end != -1:
            cleaned = cleaned[object_start : object_end + 1]
    if not cleaned.startswith(("[", "{")):
        start = cleaned.find("[")
        end = cleaned.rfind("]")
        if start != -1 and end != -1:
            cleaned = cleaned[start : end + 1]
    parsed = json.loads(cleaned)
    if isinstance(parsed, dict):
        for key in ("items", "repos", "results"):
            values = parsed.get(key)
            if isinstance(values, list):
                return [item for item in values if isinstance(item, dict)]
    if not isinstance(parsed, list):
        raise ValueError("AI response does not contain a JSON array")
    return [item for item in parsed if isinstance(item, dict)]


def build_ai_messages(batch: list[dict[str, Any]], taxonomy: dict[str, Any]) -> list[dict[str, str]]:
    """构造发送给模型的 system/user messages。

    Prompt 明确要求只返回 JSON，并把允许的分类、安装方式和输出 schema 一起传入，
    减少模型自由发挥导致的非法字段。
    """
    projects = [
        {
            "repo_id": repo.get("repo_id"),
            "repo_name": repo.get("repo_name"),
            "description": repo.get("description"),
            "topics": repo.get("topics"),
            "language": repo.get("language"),
            "initial_kind": repo.get("initial_kind"),
            "readme_snippet": repo.get("readme_snippet", "")[:README_MAX_CHARS],
        }
        for repo in batch
    ]
    system = (
        "You classify GitHub repositories for a Skill/Agent radar. "
        "Return only the final JSON object in the assistant content. "
        "Do not include reasoning, explanations, prefaces, markdown, or code fences. "
        "Use exactly one object with an items array. "
        "kind must be Skill or Agent. category must be selected from the provided taxonomy. "
        "Identify install_methods and usability_flags from repository metadata and README."
    )
    user = {
        "skill_categories": taxonomy.get("skill_categories", []),
        "agent_categories": taxonomy.get("agent_categories", []),
        "allowed_install_methods": list((taxonomy.get("install_methods") or {}).keys()),
        "required_schema": {
            "items": [
                {
                    "repo_id": 123,
                    "kind": "Skill|Agent",
                    "kind_confidence": "0.0-1.0",
                    "category": "one taxonomy category",
                    "summary": "one concise Chinese sentence",
                    "use_case": "Chinese use case sentence",
                    "solves": ["pain point"],
                    "install_methods": ["npm"],
                    "usability_flags": ["no_quickstart|no_release|inactive_repo|demo_only|unclear_installation"],
                }
            ]
        },
        "projects": projects,
    }
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": json.dumps(user, ensure_ascii=False)},
    ]


def estimate_repo_payload_chars(repo: dict[str, Any]) -> int:
    """估算单个仓库进入模型上下文的字符数。"""
    payload = {
        "repo_id": repo.get("repo_id"),
        "repo_name": repo.get("repo_name"),
        "description": repo.get("description"),
        "topics": repo.get("topics"),
        "language": repo.get("language"),
        "initial_kind": repo.get("initial_kind"),
        "readme_snippet": repo.get("readme_snippet", "")[:README_MAX_CHARS],
    }
    return len(json.dumps(payload, ensure_ascii=False))


def iter_model_batches(repos: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """按数量和字符预算切分模型 batch。

    `AI_BATCH_SIZE` 控制每批最多仓库数，`MODEL_INPUT_CHAR_BUDGET` 控制近似上下文大小。
    两者同时存在，是为了兼顾速率限制和模型上下文限制。
    """
    batches: list[list[dict[str, Any]]] = []
    batch: list[dict[str, Any]] = []
    batch_chars = 0
    for repo in repos:
        repo_chars = estimate_repo_payload_chars(repo)
        would_exceed_count = len(batch) >= AI_BATCH_SIZE
        would_exceed_budget = bool(batch) and batch_chars + repo_chars > MODEL_INPUT_CHAR_BUDGET
        if would_exceed_count or would_exceed_budget:
            batches.append(batch)
            batch = []
            batch_chars = 0
        batch.append(repo)
        batch_chars += repo_chars
    if batch:
        batches.append(batch)
    return batches


def call_model(batch: list[dict[str, Any]], taxonomy: dict[str, Any]) -> list[dict[str, Any]]:
    """调用配置的模型完成仓库分类与摘要。

    这里实现了模型侧节流、429/5xx 限流码重试、指数退避和响应 JSON 解析。
    最终失败会抛给 `analyze_repos()`，由它记录 warning 并切换到本地 fallback。
    """
    api_key = model_api_key()
    endpoint = model_api_base()
    configured_model = model_name()
    missing = []
    if not api_key:
        missing.append("MODEL_API_KEY")
    if not endpoint:
        missing.append("MODEL_API_BASE")
    if not configured_model:
        missing.append("MODEL_NAME")
    if missing:
        raise RuntimeError(f"Model config is incomplete: {', '.join(missing)}")
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": configured_model,
        "messages": build_ai_messages(batch, taxonomy),
        "temperature": 0.1,
        "max_tokens": MODEL_MAX_TOKENS,
        "response_format": {"type": "json_object"},
    }
    estimated_chars = sum(estimate_repo_payload_chars(repo) for repo in batch)
    for attempt in range(MODEL_MAX_RETRIES):
        throttle_requests("model", MODEL_REQUEST_INTERVAL_SECONDS)
        LOGGER.debug(
            "Model request started: provider=%s model=%s endpoint=%s batch_size=%s estimated_chars=%s attempt=%s repo_ids=%s",
            model_provider(),
            configured_model,
            endpoint,
            len(batch),
            estimated_chars,
            attempt + 1,
            [repo.get("repo_id") for repo in batch],
        )
        try:
            response = HTTP_SESSION.post(endpoint, headers=headers, json=payload, timeout=MODEL_HTTP_TIMEOUT)
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
            items = extract_json_array(content)
            LOGGER.debug("Model request completed: batch_size=%s parsed_items=%s", len(batch), len(items))
            return items
        except Exception as exc:  # noqa: BLE001 - intentionally normalized for retry policy
            retryable, response, code = is_retryable_model_error(exc)
            if not retryable or attempt >= MODEL_MAX_RETRIES - 1:
                message = (
                    "Model request failed permanently: provider=%s batch_size=%s attempt=%s status=%s code=%s error=%s"
                )
                args = (
                    model_provider(),
                    len(batch),
                    attempt + 1,
                    response.status_code if response is not None else None,
                    code,
                    exc.__class__.__name__,
                )
                if is_model_timeout_error(exc):
                    LOGGER.warning(message, *args)
                else:
                    LOGGER.exception(message, *args)
                raise
            wait_seconds = retry_after_seconds(response, attempt)
            LOGGER.warning(
                "Model request retry scheduled: provider=%s batch_size=%s attempt=%s wait=%.2fs status=%s code=%s",
                model_provider(),
                len(batch),
                attempt + 1,
                wait_seconds,
                response.status_code if response is not None else None,
                code,
            )
            time.sleep(wait_seconds)
    raise RuntimeError("Model request exhausted retry policy")


def validate_analysis(item: dict[str, Any], repo: dict[str, Any], taxonomy: dict[str, Any]) -> dict[str, Any]:
    """校验并修正模型返回的分析结果。

    模型可能返回不存在的分类、非法安装方式或低置信度 kind。这里把输出收敛到前端可消费的
    稳定 schema，并在必要时用本地启发式或 category_hint 修正。
    """
    kind = item.get("kind") if item.get("kind") in {"Skill", "Agent"} else guess_kind(repo)
    allowed_categories = taxonomy.get("skill_categories" if kind == "Skill" else "agent_categories", [])
    category = item.get("category") if item.get("category") in allowed_categories else repo.get("category_hint")
    if category not in allowed_categories:
        category = guess_category(repo, kind)
    methods = [str(method).lower() for method in item.get("install_methods", []) if method]
    allowed_methods = set((taxonomy.get("install_methods") or {}).keys())
    methods = sorted(set(method for method in methods if method in allowed_methods))
    if not methods:
        methods = find_install_methods(repo, taxonomy)

    flags = [str(flag) for flag in item.get("usability_flags", []) if flag]
    confidence = float(item.get("kind_confidence") or 0)
    if confidence < 0.6:
        flags.append("kind_uncertain")
        if repo.get("initial_kind") in {"Skill", "Agent"}:
            kind = repo["initial_kind"]
            category = guess_category(repo, kind)

    return {
        "repo_id": repo.get("repo_id"),
        "kind": kind,
        "kind_confidence": max(0.0, min(1.0, confidence or 0.6)),
        "category": category,
        "summary": str(item.get("summary") or repo.get("description") or repo.get("repo_name"))[:180],
        "use_case": str(item.get("use_case") or build_fallback_use_case(repo, kind))[:260],
        "solves": [str(value)[:40] for value in item.get("solves", []) if value][:5] or build_fallback_solves(repo, kind),
        "install_methods": methods,
        "usability_flags": sorted(set(flags)),
    }


def analyze_repos(repos: list[dict[str, Any]], taxonomy: dict[str, Any], report: dict[str, Any]) -> list[dict[str, Any]]:
    """对候选仓库执行 AI 分析或本地 fallback 分析。

    每个 batch 独立容错：某批模型调用失败不会中断整轮同步，只会为该批记录 warning 并使用启发式结果。
    """
    analyzed: list[dict[str, Any]] = []
    report.setdefault("ai_fallback_count", 0)
    batches = iter_model_batches(repos)
    LOGGER.info(
        "Analyzing repositories: repos=%s batches=%s max_batch_size=%s char_budget=%s model_configured=%s model=%s",
        len(repos),
        len(batches),
        AI_BATCH_SIZE,
        MODEL_INPUT_CHAR_BUDGET,
        model_configured(),
        model_label(),
    )

    consecutive_model_failures = 0
    model_circuit_open = False
    for batch_number, batch in enumerate(batches, start=1):
        ai_items: list[dict[str, Any]] | None = None
        if model_circuit_open:
            if batch_number == 1 or report.get("model_circuit_breaker_notified") is not True:
                report["model_circuit_breaker_notified"] = True
                add_warning(report, "Model analysis circuit breaker is open; using local heuristic analysis for remaining batches.")
        elif model_configured():
            LOGGER.info("Model analysis batch started: model=%s batch=%s/%s size=%s", model_label(), batch_number, len(batches), len(batch))
            try:
                ai_items = call_model(batch, taxonomy)
                consecutive_model_failures = 0
            except Exception as exc:  # noqa: BLE001 - recorded as degraded pipeline status
                consecutive_model_failures += 1
                report["model_batch_failures"] = int(report.get("model_batch_failures") or 0) + 1
                if is_model_timeout_error(exc):
                    LOGGER.warning(
                        "Model analysis batch timed out: model=%s batch=%s/%s consecutive_failures=%s",
                        model_label(),
                        batch_number,
                        len(batches),
                        consecutive_model_failures,
                    )
                else:
                    LOGGER.exception(
                        "Model analysis batch failed: model=%s batch=%s/%s consecutive_failures=%s",
                        model_label(),
                        batch_number,
                        len(batches),
                        consecutive_model_failures,
                    )
                add_warning(report, f"Model analysis fallback for batch {batch_number}: {exc.__class__.__name__}")
                if MODEL_FAILURE_CIRCUIT_BREAKER > 0 and consecutive_model_failures >= MODEL_FAILURE_CIRCUIT_BREAKER:
                    model_circuit_open = True
                    report["model_circuit_breaker_tripped"] = True
                    report["model_circuit_breaker_batch"] = batch_number
                    add_warning(
                        report,
                        f"Model analysis circuit breaker tripped after {consecutive_model_failures} consecutive failures; remaining batches use local heuristic analysis.",
                    )
        else:
            if batch_number == 1:
                add_warning(report, "Model config is incomplete; using local heuristic analysis.")

        ai_by_id = {item.get("repo_id"): item for item in ai_items or []}
        for repo in batch:
            ai_item = ai_by_id.get(repo.get("repo_id"))
            if ai_item:
                analysis = validate_analysis(ai_item, repo, taxonomy)
            else:
                analysis = fallback_analysis(repo, taxonomy)
                report["ai_fallback_count"] += 1
                LOGGER.debug("Using heuristic fallback: repo=%s repo_id=%s", repo.get("repo_name"), repo.get("repo_id"))
            combined = deepcopy(repo)
            combined.update(analysis)
            analyzed.append(combined)
    LOGGER.info("Repository analysis completed: analyzed=%s fallback_count=%s", len(analyzed), report.get("ai_fallback_count", 0))
    return analyzed


def parse_iso_datetime(value: str | None) -> datetime | None:
    """解析 GitHub ISO 时间字符串。解析失败返回 None，避免同步被单条脏数据中断。"""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def days_since(value: str | None) -> int | None:
    """计算距离指定时间的天数。"""
    dt = parse_iso_datetime(value)
    if not dt:
        return None
    return max(0, (datetime.now(timezone.utc) - dt).days)


def clamp_score(value: float) -> int:
    """把浮点分数压到 0-100 的整数区间。"""
    return int(round(max(0, min(100, value))))


def score_adoption(repo: dict[str, Any]) -> int:
    """计算采用度分数。

    stars、forks、watchers 使用对数缩放，避免头部巨型项目把其它项目完全压扁；
    open issues 相对 stars 太高时会轻微扣分。
    """
    stars = max(0, int(repo.get("stars") or 0))
    forks = max(0, int(repo.get("forks") or 0))
    watchers = max(0, int(repo.get("watchers") or 0))
    issues = max(0, int(repo.get("open_issues") or 0))

    stars_score = min(60, math.log10(stars + 1) / 5 * 60)
    forks_score = min(25, math.log10(forks + 1) / 4 * 25)
    watchers_score = min(15, math.log10(watchers + 1) / 4 * 15)
    issue_penalty = min(18, (issues / max(stars, 1)) * 120)
    return clamp_score(stars_score + forks_score + watchers_score - issue_penalty)


def score_maintenance(repo: dict[str, Any]) -> int:
    """根据最近 push/update 时间计算维护活跃度。"""
    age = days_since(repo.get("pushed_at") or repo.get("updated_at"))
    if age is None:
        return 35
    if age <= 90:
        return 100
    if age <= 180:
        return 70
    if age <= 365:
        return 40
    return 10


def score_usability(repo: dict[str, Any]) -> int:
    """计算可用性分数。

    明确安装方式、quickstart、没有严重风险标记会加分；demo_only、unclear_installation、
    inactive_repo 等会扣分。
    """
    methods = repo.get("install_methods") or []
    flags = set(repo.get("usability_flags") or [])
    score = 0
    if methods:
        score += 40
    if has_quickstart_signal(repo):
        score += 30
    if not (flags & SEVERE_FLAGS):
        score += 30
    penalties = {
        "demo_only": 25,
        "unclear_installation": 20,
        "no_quickstart": 10,
        "inactive_repo": 20,
        "kind_uncertain": 5,
        "heuristic_fallback": 5,
    }
    for flag, penalty in penalties.items():
        if flag in flags:
            score -= penalty
    return clamp_score(score)


def has_cjk_text(value: str) -> bool:
    """Return True when text contains Chinese/Japanese/Korean characters."""
    return re.search(r"[\u4e00-\u9fff]", value or "") is not None


def chinese_repo_description(repo: dict[str, Any]) -> str:
    """Build the exported Chinese description shown by the frontend radar."""
    summary = str(repo.get("summary") or "").strip()
    if summary and has_cjk_text(summary):
        return summary[:180]

    kind_label = "Skill 能力工具" if repo.get("kind") == "Skill" else "Agent 项目框架"
    category = str(repo.get("category") or repo.get("category_hint") or "通用").strip()
    use_case = str(repo.get("use_case") or "").strip()
    if not use_case or not has_cjk_text(use_case):
        use_case = build_fallback_use_case(repo, repo.get("kind", "Agent"))
    repo_name = str(repo.get("repo_name") or "该项目")
    return f"{repo_name} 是一个面向{category}场景的{kind_label}，适合用于{use_case}"[:180]


def score_repo(repo: dict[str, Any]) -> dict[str, Any]:
    """给单个仓库补充分项分数和最终推荐分。"""
    item = deepcopy(repo)
    flags = set(item.get("usability_flags") or [])
    if days_since(item.get("pushed_at") or item.get("updated_at")) and days_since(item.get("pushed_at") or item.get("updated_at")) > 365:
        flags.add("inactive_repo")
    item["usability_flags"] = sorted(flags)

    item["usability_score"] = score_usability(item)
    item["adoption_score"] = score_adoption(item)
    item["maintenance_score"] = score_maintenance(item)
    recommendation = item["usability_score"] * 0.5 + item["adoption_score"] * 0.3 + item["maintenance_score"] * 0.2
    item["recommendation_score"] = clamp_score(recommendation)
    item["description"] = chinese_repo_description(item)
    item.pop("readme_snippet", None)
    item.pop("initial_kind", None)
    return item


def score_repos(repos: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """对所有仓库评分，并按推荐分降序排序。"""
    return sorted((score_repo(repo) for repo in repos), key=lambda item: item["recommendation_score"], reverse=True)


def why_pick(repo: dict[str, Any]) -> list[str]:
    """生成 brief/top picks 中展示的推荐理由。"""
    reasons = []
    if repo.get("usability_score", 0) >= 75:
        reasons.append("高可用性")
    if repo.get("install_methods"):
        reasons.append("安装入口明确")
    if repo.get("maintenance_score", 0) >= 70:
        reasons.append("近期维护活跃")
    if repo.get("adoption_score", 0) >= 55:
        reasons.append("社区采用度高")
    return reasons[:3] or ["综合评分靠前"]


def brief_item(repo: dict[str, Any]) -> dict[str, Any]:
    """把完整仓库记录压缩成 brief 里的轻量条目。"""
    return {
        "repo_id": repo.get("repo_id"),
        "repo_name": repo.get("repo_name"),
        "kind": repo.get("kind"),
        "category": repo.get("category"),
        "summary": repo.get("summary"),
        "recommendation_score": repo.get("recommendation_score"),
        "why_pick": why_pick(repo),
        "url": repo.get("url"),
    }


def build_brief(repos: list[dict[str, Any]], warnings: list[str], synced_at: str) -> dict[str, Any]:
    """生成首页和 Agent 快读用的简版数据。"""
    eligible = [
        repo
        for repo in repos
        if repo.get("recommendation_score", 0) >= RECOMMENDATION_MIN_SCORE
        and "demo_only" not in set(repo.get("usability_flags") or [])
    ]
    skill_top = [brief_item(repo) for repo in eligible if repo.get("kind") == "Skill"][:5]
    agent_top = [brief_item(repo) for repo in eligible if repo.get("kind") == "Agent"][:5]
    return {
        "generated_at": synced_at,
        "window": "latest_sync",
        "top_picks": [brief_item(repo) for repo in eligible[:10]],
        "skill_top": skill_top,
        "agent_top": agent_top,
        "warnings": warnings[:20],
    }


def build_metadata(repos: list[dict[str, Any]], collected_count: int, fallback_count: int, warnings: list[str], synced_at: str) -> dict[str, Any]:
    """生成前端展示和调试用的同步元数据。"""
    return {
        "synced_at": synced_at,
        "version": VERSION,
        "collected_count": collected_count,
        "analyzed_count": len(repos),
        "skill_count": sum(1 for repo in repos if repo.get("kind") == "Skill"),
        "agent_count": sum(1 for repo in repos if repo.get("kind") == "Agent"),
        "exported_count": len(repos),
        "brief_count": min(10, sum(1 for repo in repos if repo.get("recommendation_score", 0) >= RECOMMENDATION_MIN_SCORE)),
        "fallback_count": fallback_count,
        "warnings": warnings[:20],
    }


def build_status(report: dict[str, Any], synced_at: str) -> dict[str, Any]:
    """把运行报告压缩成前端状态文件。"""
    return {
        "ok": not report.get("github_rate_limited") and not report.get("failed_queries"),
        "synced_at": synced_at,
        "query_count": report.get("query_count", 0),
        "failed_queries": report.get("failed_queries", []),
        "github_rate_limited": report.get("github_rate_limited", False),
        "github_rate_limit_waits": report.get("github_rate_limit_waits", 0),
        "github_rate_limit_wait_seconds": report.get("github_rate_limit_wait_seconds", 0),
        "filtered_candidates": report.get("filtered_candidates", 0),
        "filter_reasons": report.get("filter_reasons", {}),
        "trending_repos_seen": report.get("trending_repos_seen", 0),
        "trending_repos_added": report.get("trending_repos_added", 0),
        "ai_fallback_count": report.get("ai_fallback_count", 0),
        "model_batch_failures": report.get("model_batch_failures", 0),
        "model_circuit_breaker_tripped": report.get("model_circuit_breaker_tripped", False),
        "model_circuit_breaker_batch": report.get("model_circuit_breaker_batch"),
        "warnings": report.get("warnings", [])[:20],
    }


def write_json(path: Path, payload: Any) -> None:
    """原子写 JSON 文件。

    先写 `.tmp` 再 replace，避免进程中断时留下半截 JSON，尤其适合 GitHub Actions 定时任务。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with tmp_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    tmp_path.replace(path)


def export_collect_only(repos: list[dict[str, Any]], report: dict[str, Any]) -> None:
    """导出只采集模式的数据。"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    write_json(DATA_DIR / "collected_repos.json", repos)
    write_json(DATA_DIR / "run-report.json", report)


def select_frontend_repos(repos: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """限制前端导出的 Skill/Agent 数量，避免页面加载过重。"""
    skill = [repo for repo in repos if repo.get("kind") == "Skill"][:SKILL_TOP_N]
    agent = [repo for repo in repos if repo.get("kind") == "Agent"][:AGENT_TOP_N]
    return sorted(skill + agent, key=lambda item: item.get("recommendation_score", 0), reverse=True)


def export_sync(repos: list[dict[str, Any]], report: dict[str, Any], collected_count: int, synced_at: str) -> None:
    """导出完整同步结果到 `data/` 和 `docs/data/`。

    默认拒绝空导出，防止一次 API 失败把已有前端数据覆盖成空列表。确实需要空导出时，
    可以显式设置 `ALLOW_EMPTY_EXPORT=1`。
    """
    frontend_repos = select_frontend_repos(repos)
    LOGGER.info("Exporting sync data: scored=%s frontend=%s collected=%s", len(repos), len(frontend_repos), collected_count)
    if not frontend_repos and os.getenv("ALLOW_EMPTY_EXPORT") != "1":
        add_warning(report, "Export aborted because no repositories passed the pipeline.")
        write_json(DATA_DIR / "run-report.json", report)
        raise SystemExit("No radar data generated; refusing to overwrite existing frontend data.")

    metadata = build_metadata(frontend_repos, collected_count, report.get("ai_fallback_count", 0), report.get("warnings", []), synced_at)
    status = build_status(report, synced_at)
    brief = build_brief(frontend_repos, report.get("warnings", []), synced_at)

    write_json(DATA_DIR / "radar.json", frontend_repos)
    write_json(DATA_DIR / "run-report.json", report)
    write_json(DOCS_DATA_DIR / "radar.json", frontend_repos)
    write_json(DOCS_DATA_DIR / "brief.json", brief)
    write_json(DOCS_DATA_DIR / "metadata.json", metadata)
    write_json(DOCS_DATA_DIR / "status.json", status)
    LOGGER.info("Export completed: data_dir=%s docs_data_dir=%s", DATA_DIR, DOCS_DATA_DIR)


def run_collect_only() -> int:
    """CLI 模式：只执行候选召回，不拉 README、不调用模型。"""
    LOGGER.info("Collect-only run started")
    queries_config, _ = load_config()
    queries = build_queries(queries_config)
    repos, report = search_repos(queries, queries_config)
    report["ok"] = not report.get("failed_queries")
    report["synced_at"] = utc_now_iso()
    report["collected_count"] = len(repos)
    export_collect_only(repos, report)
    LOGGER.info("Collect-only run completed: collected=%s", len(repos))
    print(f"Collected {len(repos)} repositories into data/collected_repos.json")
    return 0


def run_sync() -> int:
    """CLI 模式：执行完整采集、分析、评分和导出流程。"""
    LOGGER.info("Sync run started")
    queries_config, taxonomy = load_config()
    queries = build_queries(queries_config)
    repos, report = search_repos(queries, queries_config)
    collected_count = len(repos)
    repos = limit_repos_for_analysis(repos, report)
    warnings = report.setdefault("warnings", [])
    repos = attach_readmes(repos, warnings)
    analyzed = analyze_repos(repos, taxonomy, report)
    scored = score_repos(analyzed)
    synced_at = utc_now_iso()
    report.update(
        {
            "ok": not report.get("github_rate_limited") and not report.get("failed_queries"),
            "synced_at": synced_at,
            "collected_count": collected_count,
            "analyzed_count": len(analyzed),
            "exported_count": len(select_frontend_repos(scored)),
        }
    )
    export_sync(scored, report, collected_count, synced_at)
    LOGGER.info("Sync run completed: scored=%s exported=%s warnings=%s", len(scored), report["exported_count"], len(report.get("warnings", [])))
    print(f"Synced {len(scored)} repositories; exported {report['exported_count']} frontend records.")
    return 0


def main(argv: list[str] | None = None) -> int:
    """命令行入口。"""
    setup_logging()
    parser = argparse.ArgumentParser(description="GitHub Skill/Agent Radar pipeline")
    parser.add_argument("mode", choices=("collect-only", "sync"), help="Pipeline mode to run")
    args = parser.parse_args(argv)

    if args.mode == "collect-only":
        return run_collect_only()
    if args.mode == "sync":
        return run_sync()
    return 1


if __name__ == "__main__":
    sys.exit(main())
