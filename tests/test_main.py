from __future__ import annotations

from datetime import datetime, timezone

import pytest
import requests

from src import main as radar


def sample_taxonomy():
    return {
        "skill_categories": ["学习", "信息搜集", "知识管理", "内容创作", "视频处理", "办公协作", "数据分析", "投资研究", "软件开发", "产品设计", "市场营销", "安全攻防", "自动化运营", "其他"],
        "agent_categories": ["学习", "信息搜集", "知识管理", "内容创作", "视频处理", "办公协作", "数据分析", "投资研究", "软件开发", "产品设计", "市场营销", "安全攻防", "自动化运营", "其他"],
        "install_methods": {
            "npm": ["npm install", "npx"],
            "pypi": ["pip install", "uvx"],
            "docker": ["docker run"],
            "mcp": ["mcp"],
            "cli": ["cli"],
        },
    }


def sample_repo(**overrides):
    repo = {
        "repo_id": 1,
        "repo_name": "owner/browser-agent",
        "owner": "owner",
        "description": "AI agent framework for browser automation",
        "initial_kind": "Agent",
        "matched_queries": ["topic:ai-agent"],
        "candidate_reason": ["high_popularity"],
        "stars": 5000,
        "forks": 500,
        "watchers": 80,
        "open_issues": 20,
        "language": "Python",
        "topics": ["ai-agent", "browser"],
        "url": "https://github.com/owner/browser-agent",
        "pushed_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "updated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "readme_snippet": "Quickstart\n\npip install browser-agent\n\nUsage example for CLI.",
    }
    repo.update(overrides)
    return repo


class FakeResponse:
    def __init__(self, payload, status_code=200, headers=None, text=""):
        self._payload = payload
        self.status_code = status_code
        self.headers = headers or {}
        self.ok = 200 <= status_code < 400
        self.text = text

    def json(self):
        return self._payload


def github_item(repo_id, full_name, stars=1000, **overrides):
    item = {
        "id": repo_id,
        "full_name": full_name,
        "owner": {"login": full_name.split("/")[0]},
        "description": f"{full_name} description",
        "stargazers_count": stars,
        "forks_count": 10,
        "watchers_count": 5,
        "open_issues_count": 1,
        "language": "Python",
        "topics": ["claude-skills"],
        "archived": False,
        "fork": False,
        "is_template": False,
        "disabled": False,
        "html_url": f"https://github.com/{full_name}",
        "pushed_at": "2026-07-02T00:00:00Z",
        "updated_at": "2026-07-02T00:00:00Z",
    }
    item.update(overrides)
    return item


def clear_model_env(monkeypatch):
    for name in (
        "MODEL_PROVIDER",
        "AI_MODEL_PROVIDER",
        "MODEL_API_KEY",
        "MODEL_API_BASE",
        "MODEL_NAME",
        "MODEL",
        "SILICONFLOW_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(radar, "MODEL_PROVIDER", "")
    monkeypatch.setattr(radar, "MODEL_NAME", "")
    monkeypatch.setattr(radar, "MODEL_API_BASE", "")


def test_build_queries_from_config(monkeypatch):
    monkeypatch.setattr(radar, "SKILL_SEARCH_MIN_STARS", 1000)
    monkeypatch.setattr(radar, "AGENT_SEARCH_MIN_STARS", 2000)
    monkeypatch.setattr(radar, "GITHUB_SEARCH_QUALIFIERS", "fork:false archived:false")
    config = {
        "skill": {"topics": ["skill"], "keywords": ["AI skill"]},
        "agent": {"topics": ["ai-agent"], "keywords": ["AI agent"]},
    }
    queries = radar.build_queries(config)
    assert [item["query"] for item in queries] == [
        "topic:skill stars:>1000 fork:false archived:false",
        '"AI skill" stars:>1000 fork:false archived:false',
        "topic:ai-agent stars:>2000 fork:false archived:false",
        '"AI agent" stars:>2000 fork:false archived:false',
    ]


def test_github_token_prefers_personal_access_token(monkeypatch):
    monkeypatch.setenv("PERSONAL_ACCESS_TOKENS", "pat-primary")
    monkeypatch.setenv("PERSONAL_ACCESS_TOKEN", "pat-secondary")
    monkeypatch.setenv("GH_TOKEN", "gh-token")
    assert radar.github_token() == "pat-primary"
    assert radar.github_headers()["Authorization"] == "Bearer pat-primary"


def test_model_api_key_reads_provider_specific_compat_key(monkeypatch):
    clear_model_env(monkeypatch)
    monkeypatch.setenv("MODEL_PROVIDER", "siliconflow")
    monkeypatch.setenv("SILICONFLOW_API_KEY", "sf-key")
    assert radar.model_provider() == "siliconflow"
    assert radar.model_api_key() == "sf-key"


def test_model_api_key_uses_generic_key_for_default_provider(monkeypatch):
    clear_model_env(monkeypatch)
    monkeypatch.setenv("MODEL_API_KEY", "generic-key")
    assert radar.model_provider() == "openai-compatible"
    assert radar.model_api_key() == "generic-key"


def test_model_configured_requires_key_base_and_name(monkeypatch):
    clear_model_env(monkeypatch)
    monkeypatch.setenv("MODEL_API_KEY", "model-key")
    monkeypatch.setenv("MODEL_NAME", "test-model")
    assert radar.model_configured() is False

    monkeypatch.setenv("MODEL_API_BASE", "https://example.test/v1/chat/completions")
    assert radar.model_configured() is True


def test_model_api_base_accepts_compatible_mode_base_url(monkeypatch):
    clear_model_env(monkeypatch)
    monkeypatch.setenv("MODEL_API_BASE", "https://example.test/compatible-mode/v1")
    assert radar.model_api_base() == "https://example.test/compatible-mode/v1/chat/completions"


def test_model_api_key_prefers_generic_key_over_provider_key(monkeypatch):
    monkeypatch.setenv("MODEL_PROVIDER", "siliconflow")
    monkeypatch.setenv("MODEL_API_KEY", "generic-key")
    monkeypatch.setenv("SILICONFLOW_API_KEY", "sf-key")
    assert radar.model_api_key() == "generic-key"


def test_model_config_uses_generic_model_values_with_provider_key(monkeypatch):
    clear_model_env(monkeypatch)
    monkeypatch.setenv("MODEL_PROVIDER", "siliconflow")
    monkeypatch.setenv("SILICONFLOW_API_KEY", "sf-key")
    monkeypatch.setenv("MODEL_NAME", "test-model")
    monkeypatch.setenv("MODEL_API_BASE", "https://example.test/v1/chat/completions")
    assert radar.model_provider() == "siliconflow"
    assert radar.model_api_key() == "sf-key"
    assert radar.model_name() == "test-model"
    assert radar.model_api_base() == "https://example.test/v1/chat/completions"


def test_call_model_sets_output_budget_and_json_only_prompt(monkeypatch):
    clear_model_env(monkeypatch)
    captured = {}

    class ModelResponse:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": '{"items": [{"repo_id": 1, "kind": "Agent"}]}'}}]}

    class FakeSession:
        def post(self, url, headers=None, json=None, timeout=None):
            captured["url"] = url
            captured["headers"] = headers
            captured["json"] = json
            captured["timeout"] = timeout
            return ModelResponse()

    monkeypatch.setenv("MODEL_API_KEY", "model-key")
    monkeypatch.setenv("MODEL_API_BASE", "https://example.test/v1/chat/completions")
    monkeypatch.setenv("MODEL_NAME", "test-model")
    monkeypatch.setattr(radar, "MODEL_MAX_TOKENS", 4096)
    monkeypatch.setattr(radar, "MODEL_MAX_RETRIES", 1)
    monkeypatch.setattr(radar, "MODEL_REQUEST_INTERVAL_SECONDS", 0)
    monkeypatch.setattr(radar, "HTTP_SESSION", FakeSession())

    items = radar.call_model([sample_repo()], sample_taxonomy())

    assert items == [{"repo_id": 1, "kind": "Agent"}]
    assert captured["json"]["max_tokens"] == 4096
    assert captured["json"]["response_format"] == {"type": "json_object"}
    system_prompt = captured["json"]["messages"][0]["content"]
    assert "Do not include reasoning" in system_prompt
    assert "markdown" in system_prompt.lower()


def test_setup_logging_writes_debug_file(tmp_path, monkeypatch):
    log_path = tmp_path / "debug.log"
    monkeypatch.setattr(radar, "DEBUG_LOG_FILE", str(log_path))
    monkeypatch.setattr(radar, "DATA_DIR", tmp_path)
    radar.setup_logging()
    radar.LOGGER.info("hello debug log")
    for handler in radar.LOGGER.handlers:
        handler.flush()
    assert log_path.exists()
    assert "hello debug log" in log_path.read_text(encoding="utf-8")


def test_merge_candidate_preserves_query_and_reason():
    left = sample_repo(matched_queries=["topic:ai-agent"], candidate_reason=["high_popularity"], topics=["ai-agent"])
    right = sample_repo(matched_queries=["keyword:AI agent"], candidate_reason=["installable_signal"], topics=["browser"])
    merged = radar.merge_candidate(left, right)
    assert merged["matched_queries"] == ["keyword:AI agent", "topic:ai-agent"]
    assert merged["candidate_reason"] == ["high_popularity", "installable_signal"]
    assert merged["topics"] == ["ai-agent", "browser"]


def test_merge_candidate_preserves_category_hint():
    left = sample_repo(category_hint="")
    right = sample_repo(category_hint=sample_taxonomy()["skill_categories"][3])
    merged = radar.merge_candidate(left, right)
    assert merged["category_hint"] == sample_taxonomy()["skill_categories"][3]


def test_limit_repos_for_analysis_keeps_seed_repositories(monkeypatch):
    monkeypatch.setattr(radar, "ANALYSIS_REPO_LIMIT", 3)
    repos = [
        sample_repo(repo_id=1, repo_name="owner/top-1", stars=5000, candidate_reason=["high_popularity"]),
        sample_repo(repo_id=2, repo_name="owner/top-2", stars=4000, candidate_reason=["high_popularity"]),
        sample_repo(repo_id=3, repo_name="owner/top-3", stars=3000, candidate_reason=["high_popularity"]),
        sample_repo(repo_id=4, repo_name="owner/seed", stars=10, candidate_reason=["seed_repo"]),
    ]
    report = {"warnings": []}

    limited = radar.limit_repos_for_analysis(repos, report)

    assert len(limited) == 3
    assert "owner/seed" in [repo["repo_name"] for repo in limited]
    assert report["analysis_repo_limit_applied"] is True
    assert report["collected_before_analysis_limit"] == 4


def test_load_seed_repos_supports_string_and_dict(tmp_path, monkeypatch):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    category = sample_taxonomy()["skill_categories"][3]
    (config_dir / "seeds.yaml").write_text(
        f"""
repos:
  - owner/plain-skill
  - repo: geekjourneyx/md2wechat-skill
    kind_hint: Skill
    category_hint: {category}
""",
        encoding="utf-8",
    )
    monkeypatch.setattr(radar, "CONFIG_DIR", config_dir)
    seeds = radar.load_seed_repos()
    assert seeds == [
        {
            "repo_name": "owner/plain-skill",
            "kind_hint": "Skill",
            "label": "seed:owner/plain-skill",
            "category_hint": "",
        },
        {
            "repo_name": "geekjourneyx/md2wechat-skill",
            "kind_hint": "Skill",
            "label": "seed:geekjourneyx/md2wechat-skill",
            "category_hint": category,
        },
    ]


def test_request_json_uses_search_specific_throttle(monkeypatch):
    calls = []

    class FakeSession:
        def get(self, url, params=None, headers=None, timeout=None):
            return FakeResponse({"items": []})

    monkeypatch.setattr(radar, "HTTP_SESSION", FakeSession())
    monkeypatch.setattr(radar, "GITHUB_SEARCH_REQUEST_INTERVAL_SECONDS", 2.2)
    monkeypatch.setattr(radar, "GITHUB_REQUEST_INTERVAL_SECONDS", 0.3)
    monkeypatch.setattr(radar, "throttle_requests", lambda kind, interval: calls.append((kind, interval)))

    radar.request_json(f"{radar.GITHUB_API}/search/repositories", params={"q": "agent"})
    radar.request_json(f"{radar.GITHUB_API}/repos/owner/repo")

    assert calls == [("github_search", 2.2), ("github", 0.3)]


def test_search_repos_fetches_configured_pages(monkeypatch):
    calls = []

    def fake_request_json(url, *, params=None, headers=None):
        calls.append((url, params))
        page = params["page"]
        if page == 1:
            return FakeResponse(
                {
                    "items": [
                        github_item(1, "owner/page-one-a", stars=1200),
                        github_item(2, "owner/page-one-b", stars=1100),
                    ]
                },
                headers={"X-RateLimit-Remaining": "10"},
            )
        return FakeResponse(
            {"items": [github_item(3, "owner/page-two-a", stars=1000)]},
            headers={"X-RateLimit-Remaining": "9"},
        )

    monkeypatch.setattr(radar, "GITHUB_SEARCH_PAGES", 2)
    monkeypatch.setattr(radar, "MAX_RESULTS_PER_QUERY", 2)
    monkeypatch.setattr(radar, "request_json", fake_request_json)
    monkeypatch.setattr(radar, "load_seed_repos", lambda: [])

    repos, report = radar.search_repos([{"kind_hint": "Skill", "label": "topic:claude-skills", "query": "topic:claude-skills"}])

    assert [params["page"] for _, params in calls] == [1, 2]
    assert [repo["repo_name"] for repo in repos] == ["owner/page-one-a", "owner/page-one-b", "owner/page-two-a"]
    assert report["search_pages"] == 2


def test_search_repos_waits_and_retries_on_rate_limit(monkeypatch):
    responses = [
        FakeResponse(
            {"message": "API rate limit exceeded"},
            status_code=403,
            headers={"X-RateLimit-Remaining": "0", "Retry-After": "1"},
        ),
        FakeResponse({"items": [github_item(1, "owner/retried-agent", stars=3000)]}, headers={"X-RateLimit-Remaining": "9"}),
    ]
    sleeps = []

    def fake_request_json(url, *, params=None, headers=None):
        return responses.pop(0)

    monkeypatch.setattr(radar, "GITHUB_RATE_LIMIT_RETRIES", 2)
    monkeypatch.setattr(radar, "GITHUB_WAIT_ON_RATE_LIMIT", True)
    monkeypatch.setattr(radar, "GITHUB_RATE_LIMIT_MAX_WAIT_SECONDS", 10)
    monkeypatch.setattr(radar, "request_json", fake_request_json)
    monkeypatch.setattr(radar.time, "sleep", lambda seconds: sleeps.append(seconds))
    monkeypatch.setattr(radar, "load_seed_repos", lambda: [])

    repos, report = radar.search_repos([{"kind_hint": "Agent", "label": "keyword:AI agent", "query": '"AI agent"'}])

    assert [repo["repo_name"] for repo in repos] == ["owner/retried-agent"]
    assert sleeps == [1.0]
    assert report["github_rate_limit_waits"] == 1
    assert report["github_rate_limited"] is False


def test_candidate_noise_reason_filters_metadata_and_stale_repos(monkeypatch):
    monkeypatch.setattr(radar, "CANDIDATE_MAX_PUSH_AGE_DAYS", 365)
    assert radar.candidate_noise_reason(github_item(1, "owner/archived", archived=True)) == "archived_repo"
    assert radar.candidate_noise_reason(github_item(2, "owner/forked", fork=True)) == "fork_repo"
    assert radar.candidate_noise_reason(github_item(3, "owner/template", is_template=True)) == "template_repo"
    assert radar.candidate_noise_reason(github_item(4, "owner/stale", pushed_at="2024-01-01T00:00:00Z")) == "stale_repo"


def test_candidate_noise_reason_filters_doc_only_repo_names(monkeypatch):
    monkeypatch.setattr(radar, "CANDIDATE_MAX_PUSH_AGE_DAYS", 0)
    assert radar.candidate_noise_reason(github_item(1, "owner/awesome-ai-agents")) == "noise_term:awesome"
    assert radar.candidate_noise_reason(github_item(2, "owner/llm-demo")) == "noise_term:demo"


def test_search_repos_filters_noise_and_reports_reason(monkeypatch):
    def fake_request_json(url, *, params=None, headers=None):
        return FakeResponse(
            {
                "items": [
                    github_item(1, "owner/awesome-ai-agents", stars=5000),
                    github_item(2, "owner/useful-agent", stars=4000),
                ]
            },
            headers={"X-RateLimit-Remaining": "10"},
        )

    monkeypatch.setattr(radar, "GITHUB_SEARCH_PAGES", 1)
    monkeypatch.setattr(radar, "MAX_RESULTS_PER_QUERY", 50)
    monkeypatch.setattr(radar, "CANDIDATE_MAX_PUSH_AGE_DAYS", 0)
    monkeypatch.setattr(radar, "request_json", fake_request_json)
    monkeypatch.setattr(radar, "load_seed_repos", lambda: [])

    repos, report = radar.search_repos([{"kind_hint": "Agent", "label": "keyword:AI agent", "query": '"AI agent"'}])

    assert [repo["repo_name"] for repo in repos] == ["owner/useful-agent"]
    assert report["filtered_candidates"] == 1
    assert report["filter_reasons"] == {"noise_term:awesome": 1}


def test_extract_json_array_from_markdown_fence():
    payload = '```json\n[{"repo_id": 1, "kind": "Agent"}]\n```'
    assert radar.extract_json_array(payload) == [{"repo_id": 1, "kind": "Agent"}]


def test_extract_json_array_from_items_object():
    payload = '{"items": [{"repo_id": 1, "kind": "Agent"}]}'
    assert radar.extract_json_array(payload) == [{"repo_id": 1, "kind": "Agent"}]


def test_iter_model_batches_respects_count_limit(monkeypatch):
    repos = [sample_repo(repo_id=index, repo_name=f"owner/repo-{index}") for index in range(5)]
    monkeypatch.setattr(radar, "AI_BATCH_SIZE", 2)
    monkeypatch.setattr(radar, "MODEL_INPUT_CHAR_BUDGET", 100000)
    batches = radar.iter_model_batches(repos)
    assert [len(batch) for batch in batches] == [2, 2, 1]


def test_iter_model_batches_respects_char_budget(monkeypatch):
    repos = [
        sample_repo(repo_id=1, repo_name="owner/a", readme_snippet="a" * 80),
        sample_repo(repo_id=2, repo_name="owner/b", readme_snippet="b" * 80),
    ]
    monkeypatch.setattr(radar, "AI_BATCH_SIZE", 10)
    monkeypatch.setattr(radar, "MODEL_INPUT_CHAR_BUDGET", radar.estimate_repo_payload_chars(repos[0]) + 10)
    batches = radar.iter_model_batches(repos)
    assert [len(batch) for batch in batches] == [1, 1]


def test_retryable_model_error_detects_bigmodel_rate_code():
    response = requests.Response()
    response.status_code = 429
    response._content = b'{"error":{"code":"1302","message":"rate limit"}}'
    exc = requests.HTTPError(response=response)
    retryable, parsed_response, code = radar.is_retryable_model_error(exc)
    assert retryable is True
    assert parsed_response is response
    assert code == "1302"


def test_fallback_analysis_identifies_agent_and_install_methods():
    analysis = radar.fallback_analysis(sample_repo(), sample_taxonomy())
    assert analysis["kind"] == "Agent"
    assert analysis["category"] == "自动化运营"
    assert "pypi" in analysis["install_methods"]
    assert "heuristic_fallback" in analysis["usability_flags"]


def test_fallback_analysis_uses_valid_category_hint():
    taxonomy = sample_taxonomy()
    category = taxonomy["skill_categories"][3]
    repo = sample_repo(initial_kind="Skill", category_hint=category, topics=["claude-skills"], description="Markdown to WeChat")
    analysis = radar.fallback_analysis(repo, taxonomy)
    assert analysis["kind"] == "Skill"
    assert analysis["category"] == category


def test_validate_analysis_uses_category_hint_when_ai_category_invalid():
    taxonomy = sample_taxonomy()
    category = taxonomy["skill_categories"][3]
    repo = sample_repo(initial_kind="Skill", category_hint=category, topics=["claude-skills"], description="Markdown to WeChat")
    analysis = radar.validate_analysis(
        {
            "kind": "Skill",
            "kind_confidence": 0.95,
            "category": "not-in-taxonomy",
            "summary": "Markdown publishing helper",
            "use_case": "Publish markdown to WeChat.",
            "solves": ["publishing"],
            "install_methods": ["cli"],
            "usability_flags": [],
        },
        repo,
        taxonomy,
    )
    assert analysis["category"] == category


def test_score_repo_calculates_recommendation_score():
    repo = sample_repo()
    repo.update(
        {
            "kind": "Agent",
            "kind_confidence": 0.9,
            "category": "软件开发",
            "summary": "Browser automation agent.",
            "use_case": "Automate browser workflows.",
            "solves": ["浏览器任务执行"],
            "install_methods": ["pypi", "cli"],
            "usability_flags": [],
        }
    )
    scored = radar.score_repo(repo)
    assert scored["usability_score"] >= 90
    assert scored["maintenance_score"] == 100
    assert scored["recommendation_score"] >= 70
    assert radar.has_cjk_text(scored["description"])
    assert "readme_snippet" not in scored


def test_analyze_repos_opens_circuit_breaker_after_model_timeouts(monkeypatch):
    clear_model_env(monkeypatch)
    monkeypatch.setenv("MODEL_API_KEY", "model-key")
    monkeypatch.setenv("MODEL_API_BASE", "https://example.test/v1/chat/completions")
    monkeypatch.setenv("MODEL_NAME", "test-model")
    monkeypatch.setattr(radar, "AI_BATCH_SIZE", 1)
    monkeypatch.setattr(radar, "MODEL_INPUT_CHAR_BUDGET", 100000)
    monkeypatch.setattr(radar, "MODEL_FAILURE_CIRCUIT_BREAKER", 2)
    calls = {"count": 0}

    def fail_model(batch, taxonomy):
        calls["count"] += 1
        raise requests.ReadTimeout("read timed out")

    monkeypatch.setattr(radar, "call_model", fail_model)
    repos = [sample_repo(repo_id=index, repo_name=f"owner/repo-{index}") for index in range(4)]
    report = {"warnings": []}

    analyzed = radar.analyze_repos(repos, sample_taxonomy(), report)

    assert len(analyzed) == 4
    assert calls["count"] == 2
    assert report["model_circuit_breaker_tripped"] is True
    assert report["ai_fallback_count"] == 4


def test_build_brief_filters_low_scores_and_demo_only():
    good = radar.score_repo(
        sample_repo(
            kind="Agent",
            kind_confidence=0.9,
            category="软件开发",
            summary="Good project",
            use_case="Use it",
            solves=["x"],
            install_methods=["pypi"],
            usability_flags=[],
        )
    )
    low = dict(good, repo_id=2, repo_name="owner/low", recommendation_score=10)
    demo = dict(good, repo_id=3, repo_name="owner/demo", usability_flags=["demo_only"])
    brief = radar.build_brief([good, low, demo], [], "2026-07-02T00:00:00Z")
    assert [item["repo_name"] for item in brief["top_picks"]] == [good["repo_name"]]
    assert brief["agent_top"][0]["repo_name"] == good["repo_name"]


def test_export_sync_writes_expected_files(tmp_path, monkeypatch):
    monkeypatch.setattr(radar, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(radar, "DOCS_DATA_DIR", tmp_path / "docs" / "data")
    repo = radar.score_repo(
        sample_repo(
            kind="Agent",
            kind_confidence=0.9,
            category="软件开发",
            summary="Good project",
            use_case="Use it",
            solves=["x"],
            install_methods=["pypi"],
            usability_flags=[],
        )
    )
    report = {"warnings": [], "failed_queries": [], "github_rate_limited": False, "ai_fallback_count": 0, "query_count": 1}
    radar.export_sync([repo], report, collected_count=1, synced_at="2026-07-02T00:00:00Z")
    assert (tmp_path / "data" / "radar.json").exists()
    assert (tmp_path / "docs" / "data" / "brief.json").exists()
    assert (tmp_path / "docs" / "data" / "status.json").exists()


def test_export_sync_refuses_empty_export(tmp_path, monkeypatch):
    monkeypatch.setattr(radar, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(radar, "DOCS_DATA_DIR", tmp_path / "docs" / "data")
    monkeypatch.delenv("ALLOW_EMPTY_EXPORT", raising=False)
    with pytest.raises(SystemExit):
        radar.export_sync([], {"warnings": []}, collected_count=0, synced_at="2026-07-02T00:00:00Z")
