@AGENTS.md

# Claude Code adapter notes

- Project artifacts, not Claude auto-memory or conversation history, are the
  authoritative cross-session state.
- Use project subagents only when focused context is valuable. Do not use Git
  worktree isolation.
- Obey the project permission and no-Git guard configuration in `.claude/`.
- If an adapter capability or requested effort profile is unavailable, record
  the limitation rather than silently substituting a weaker configuration.

