# Classification Reference

The configured model should only supply semantic fields that are hard to determine reliably with rules:

- `kind`: `Skill` or `Agent`
- `kind_confidence`: number from 0.0 to 1.0
- `category`: one allowed taxonomy category
- `summary`: one concise Chinese sentence
- `use_case`: Chinese use-case sentence
- `solves`: short pain-point labels
- `install_methods`: allowed install method keys
- `usability_flags`: risk flags such as `no_quickstart`, `no_release`, `inactive_repo`, `demo_only`, `unclear_installation`

Both `skill_categories` and `agent_categories` now use business-scenario labels rather than technical form factors. Prefer:

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

Prompt rules:

- Return JSON only, no Markdown.
- Use only categories from `config/taxonomy.yaml`.
- Prefer AI kind judgement when confidence is at least 0.6.
- Below 0.6, add `kind_uncertain` and fall back to the topic hint.

Fallback rules:

- Skill if topics include `skill`, `agent-skill`, `agent-skills`, or `claude-skill`.
- Skill if the project is primarily an MCP server/tool entry.
- Agent if topics or README emphasize autonomous agents, frameworks, multi-agent orchestration, or vertical Agent applications.
