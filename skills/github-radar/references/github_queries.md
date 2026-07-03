# GitHub Query Reference

The default MVP query set is loaded from `config/queries.yaml`.

Skill topics:

- `skill`
- `agent-skill`
- `claude-skill`
- `agent-skills`

Agent topics:

- `ai-agent`
- `llm-agent`
- `autonomous-agent`
- `agent-framework`
- `mcp`

Keyword searches:

- `"AI skill" stars:>300`
- `"agent skill" stars:>300`
- `"AI agent" stars:>1000`
- `"agent framework" stars:>1000`

Candidate reasons should preserve why a repository entered the radar:

- `high_popularity`: stars meet the mature Agent/framework threshold.
- `usable_tool_signal`: stars meet the Skill/tool threshold.
- `installable_topic_signal`: topics suggest CLI or MCP usage.
- `installable_signal`: README includes install or usage signals.

Keep each query capped by `MAX_RESULTS_PER_QUERY` to control GitHub API load and AI cost.
