# Claude Code adapter

Adapter schema: `research-agent-adapter-v3`

Claude Code reads the shared root `CLAUDE.md`/`AGENTS.md` instructions and the
provider mechanics in this directory. Project agents use replaceable model
family aliases rather than generation-pinned IDs.

## Activation

1. Start Claude Code from the project root and approve project configuration.
2. Run `/status` to confirm `.claude/settings.json` loaded, then `/hooks` to
   inspect the active project hooks.
3. Run `python3 tools/research.py doctor --runtime claude` before autonomous
   write work.
4. Invoke the named definitions under `.claude/agents/`. They deliberately omit
   the `isolation` and `memory` frontmatter fields.

Unset `CLAUDE_CODE_SUBAGENT_MODEL` and `CLAUDE_CODE_EFFORT_LEVEL` when exact
semantic-profile resolution matters: current Claude Code gives those
environment variables precedence over subagent frontmatter. Organization
model allowlists can also substitute a blocked family alias. Any warning or
substitution must appear in the task receipt, and `deep`/`pivotal` work stops
instead of silently downgrading.

The optional `writer` definition uses `substantive` effort for user-requested
writing; it loads the writing guide and orientation on demand.

## Safety behavior

- `autoMemoryEnabled` and `CLAUDE_CODE_DISABLE_AUTO_MEMORY` disable provider
  auto-memory. Durable research state remains in `STATE.md` and linked files.
- Native permission rules deny ordinary Git binaries and `.git` file access.
  A synchronous Python hook detects path-qualified, compound, and common
  Bash/PowerShell-wrapped Git commands plus explicit `.git` edit/write targets.
- A separate global hook protects existing experiment inputs/executions and
  published milestone reports while permitting creation of new append-only
  evidence paths.
- A global safety hook prevents every agent role from rewriting `.codex/`,
  `.claude/`, `runtime/`, `AGENTS.md`, `CLAUDE.md`, `tools/research.py`, or
  `tools/guards/`. Adapter changes are a human or trusted-external operation
  followed by `doctor` and hook re-approval.
- A second hook rejects `Agent` calls with `isolation: worktree`, the native
  `EnterWorktree` tool, and CLI attempts to start Claude/Codex worktrees. All agent files omit worktree
  isolation; parallel work uses unique run/task paths in the shared checkout.
- Focused-agent hooks protect central integration files. The coordinator is the
  sole adapter role without that guard and may update them only when acting as
  the current integration authority. Focused hooks also block `research.py`
  actions other than `check` and `doctor`, preventing indirect registry or
  adapter mutation. The verifier hook additionally makes all target claim
  files read-only. Protected-path PowerShell commands fail conservatively; use
  ordinary file-read tools for authoritative inputs.
- Default permission mode is retained. Background tasks cannot surface a new
  approval; a gated action fails and must be reported to the coordinator.

## Effort availability

Claude Code currently accepts `low`, `medium`, `high`, `xhigh`, and `max` in
subagent frontmatter, subject to model/account support. `max` is session-only at
top level but valid for a subagent definition. The pivotal agent requests
`opus`/`max` and explicitly fails if the runtime reports a different resolved
tier. Do not replace this with the `ultracode` session workflow: it is not a
subagent frontmatter effort and could introduce a dynamic topology the core
method does not require.

## Limits

Repository hooks and deny rules are not an operating-system security boundary.
An authorized user can alter/disable them, and arbitrary code can conceal an
indirect process launch. High-assurance use requires a sandbox/container that
omits Git and denies `.git` independently. The Python hook commands rely on the
documented `CLAUDE_PROJECT_DIR` environment variable and a Python 3 executable;
Windows installations that expose only `py -3` need a machine-local command
substitution followed by hook verification.
