---
name: github-radar
description: Build, consume, and operate a simplified GitHub Skill/Agent Radar. Use when Codex needs to read radar JSON and recommend open-source AI Skill or Agent projects, run collect-only or sync for the radar pipeline, maintain the GitHub Actions/GitHub Pages data flow, classify repositories with a configurable OpenAI-compatible model fallback behavior, or explain the generated data files and scoring model.
---

# GitHub Radar

Use this skill for the GitHub Skill / Agent Radar project. It covers three workflows:

1. Read existing radar JSON and produce a concise project brief.
2. Run or maintain the local pipeline with `python src/main.py collect-only` or `python src/main.py sync`.
3. Help users fork and operate the radar safely with GitHub Actions and GitHub Pages.

## Read Radar

Prefer `docs/data/brief.json` for fast recommendations. If it is missing or empty, fall back to `docs/data/radar.json`.

For local reads, use the bundled helper:

```bash
python skills/github-radar/scripts/radar_cli.py read-radar --root .
```

For a public GitHub Pages deployment:

```bash
python skills/github-radar/scripts/radar_cli.py read-radar --base-url https://OWNER.github.io/REPO
```

When answering users, mention project name, kind, category, recommendation score, why it was picked, and GitHub URL. Do not pretend the list is exhaustive; it is the latest generated radar snapshot.

## Operate Pipeline

Use these commands from the repository root:

```bash
python src/main.py collect-only
python src/main.py sync
```

`collect-only` writes `data/collected_repos.json` and does not require a model API key.

`sync` collects repositories, fetches README snippets, analyzes kind/category/usability, scores projects, and writes:

- `data/radar.json`
- `data/run-report.json`
- `docs/data/radar.json`
- `docs/data/brief.json`
- `docs/data/metadata.json`
- `docs/data/status.json`

Required environment variables:

- `PERSONAL_ACCESS_TOKENS` or `PERSONAL_ACCESS_TOKEN`: recommended GitHub personal access token for API rate limits and Actions checkout/push.
- `GH_TOKEN` or `GITHUB_TOKEN`: supported fallback names.
- `MODEL_PROVIDER`: optional provider label for logs. Defaults are project-level, not skill-level.
- `MODEL_API_KEY`: required for live model analysis.
- `MODEL_API_BASE`: OpenAI-compatible chat-completions endpoint.
- `MODEL_NAME`: chat model name.
- `LOG_LEVEL`: optional logging level. Use `DEBUG` for detailed pipeline traces.
- `DEBUG_LOG_FILE`: optional log file path. Defaults to `data/debug.log`.
- `AI_BATCH_SIZE`: maximum repositories per model batch.
- `MODEL_INPUT_CHAR_BUDGET`: approximate per-batch input character budget to stay below model context limits.
- `MODEL_REQUEST_INTERVAL_SECONDS`: delay between model requests.
- `MODEL_MAX_RETRIES`: retry attempts for rate limits or transient model API failures.
- `GITHUB_REQUEST_INTERVAL_SECONDS`: delay between GitHub API requests.
- `SKILL_SEARCH_MIN_STARS`: minimum stars for Skill search queries. Defaults to `1000`.
- `AGENT_SEARCH_MIN_STARS`: minimum stars for Agent search queries. Defaults to `2000`.
- `GITHUB_SEARCH_QUALIFIERS`: extra GitHub Search qualifiers. Defaults to `fork:false archived:false`.
- `GITHUB_SEARCH_PAGES`: number of GitHub Search result pages to fetch for each query.
- `ENABLE_GITHUB_TRENDING`: fetch GitHub Trending as a growth-signal supplement. Defaults to enabled.
- `GITHUB_TRENDING_PERIODS`: comma-separated Trending windows, such as `daily,weekly`.
- `GITHUB_TRENDING_FETCH_LIMIT`: maximum Trending repositories to inspect per window.
- `CANDIDATE_MAX_PUSH_AGE_DAYS`: filter repositories whose latest push is older than this many days; `0` disables it.
- `CANDIDATE_NOISE_TERMS`: comma-separated repository-name/topic terms to filter before analysis.
- `README_FETCH_LIMIT`: maximum README snippets to fetch per run; `0` means unlimited.

For local development, copy `.env.example` to `.env` in the repository root and fill in the token values. `src/main.py` loads `.env` automatically.

Debug logs are written to `data/debug.log` by default and should not be committed.

For model rate limits, first increase `MODEL_REQUEST_INTERVAL_SECONDS`, then reduce `AI_BATCH_SIZE` or `MODEL_INPUT_CHAR_BUDGET`. For GitHub performance, reduce `MAX_RESULTS_PER_QUERY`, reduce `GITHUB_SEARCH_PAGES`, reduce `GITHUB_TRENDING_FETCH_LIMIT`, or set `README_FETCH_LIMIT`.

Candidate noise filters run before README/model analysis. They filter archived/fork/template/disabled repositories, stale repositories by `pushed_at`, and obvious doc-only names such as awesome lists, paper lists, datasets, demos, and tutorials. Seed repositories in `config/seeds.yaml` are fetched directly and kept as a must-include backstop.

Never write API keys, private tokens, cookies, private repository data, or private user information into the repository or generated JSON.

## Maintenance Guidance

Configuration lives in:

- `config/queries.yaml`: GitHub topics and keyword searches.
- `config/seeds.yaml`: must-include repositories fetched directly by `owner/repo`.
- `config/taxonomy.yaml`: allowed categories and install method signals.

Core implementation lives in `src/main.py`. Keep the MVP constraints unless the user asks for expansion: no database, no trend history, no package download counts, no complex frontend framework.

If changing prompts or classification rules, read `references/classification_prompt.md`.

If changing candidate discovery, read `references/github_queries.md`.

If changing scores or brief generation, read `references/scoring_formula.md`.

## Failure Handling

Treat these as expected degraded states:

- GitHub README 404: continue with repository metadata.
- GitHub rate limit: stop remaining queries and keep already collected repositories.
- Model timeout or invalid JSON: retry, then use local heuristic fallback.
- Empty export: do not overwrite frontend data unless `ALLOW_EMPTY_EXPORT=1`.
- Empty brief: page and Agent responses should fall back to the full radar list.
