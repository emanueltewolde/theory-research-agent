# Semantic runtime profiles

Adapter schema: `research-agent-adapter-v2`

Research artifacts request semantic profiles. Provider names, model aliases,
effort controls, permissions, and invocation syntax belong only in this file
and the `.codex/` and `.claude/` adapters. A model rename must not require a
research-artifact migration.

Compatibility baseline: this adapter was parse-checked on 2026-08-17 with
Codex CLI `0.148.0-alpha.9` and Claude Code `2.1.139`. These are observed
baselines, not promises that every later build preserves the schemas. Support
is capability-based: `doctor` checks the static project wiring and canaries;
the runtime's hook/status inspector and a harmless task receipt must confirm
that hooks, custom agents, requested model/effort values, memory controls, and
permissions actually resolved on the installed runtime.

## Profile contract

| Profile | Use | Codex mapping | Claude Code mapping |
|---|---|---|---|
| `maintenance` | Link repair, formatting, registry assistance, and routine summaries | `gpt-6-luna`, `medium` | `haiku`, `medium` |
| `coordinator` | Broad-context selection, integration, triage, and strategy | `gpt-6-sol`, `high` | `opus`, `high` |
| `substantive` | Default proof attempts, counterexample search, experimental design, literature synthesis, and ordinary verification | `gpt-6-sol`, `high` | `opus`, `high` |
| `deep` | Subtle central claims, difficult verification, or work following a serious failed substantive attempt | `gpt-6-astra`, `xhigh` | `opus`, `xhigh` |
| `pivotal` | Important main-theorem bottlenecks, claimed breakthroughs, skeptical central review, or project-shaping forks | `gpt-6-astra`, `max` | `opus`, `max` |

## Adapter mapping history

This table is append-only. Every completed receipt records the runtime-resolved
model and effort. The mapping history records the requested model or family
alias; a family alias accepts a concrete resolved model from that family. When any mapping
changes, assign a new adapter version throughout the runtime adapter, append a
complete set of rows for that version, and retain every older row so historical
receipts and reviews remain auditable without artifact migration.

| Adapter version | Runtime | Profile | Model | Effort |
|---|---|---|---|---|
| `research-agent-adapter-v1` | `codex` | `maintenance` | `gpt-5.6-terra` | `medium` |
| `research-agent-adapter-v1` | `codex` | `coordinator` | `gpt-5.6-sol` | `high` |
| `research-agent-adapter-v1` | `codex` | `substantive` | `gpt-5.6-sol` | `high` |
| `research-agent-adapter-v1` | `codex` | `deep` | `gpt-5.6-sol` | `xhigh` |
| `research-agent-adapter-v1` | `codex` | `pivotal` | `gpt-5.6-sol` | `ultra` |
| `research-agent-adapter-v1` | `claude` | `maintenance` | `haiku` | `medium` |
| `research-agent-adapter-v1` | `claude` | `coordinator` | `opus` | `high` |
| `research-agent-adapter-v1` | `claude` | `substantive` | `opus` | `high` |
| `research-agent-adapter-v1` | `claude` | `deep` | `opus` | `xhigh` |
| `research-agent-adapter-v1` | `claude` | `pivotal` | `opus` | `max` |
| `research-agent-adapter-v2` | `codex` | `maintenance` | `gpt-6-luna` | `medium` |
| `research-agent-adapter-v2` | `codex` | `coordinator` | `gpt-6-sol` | `high` |
| `research-agent-adapter-v2` | `codex` | `substantive` | `gpt-6-sol` | `high` |
| `research-agent-adapter-v2` | `codex` | `deep` | `gpt-6-astra` | `xhigh` |
| `research-agent-adapter-v2` | `codex` | `pivotal` | `gpt-6-astra` | `max` |

`verifier`, `verifier_deep`, and `verifier_pivotal` are fresh-context
responsibility definitions mapped to `substantive`, `deep`, and `pivotal`,
respectively. Each installs the verifier write boundary, so stronger review
never gains permission to rewrite the target claim. Select verifier effort
independently: a pivotal producer does not automatically require a pivotal
verifier, which is reserved for unusually complex or consequential central
claims.

The names describe intended research effort, not identical computation across
providers. GPT-6 Astra is used for the highest-effort Codex profiles. Claude
uses the rolling `opus` and `haiku` family aliases, so Claude Code may resolve
them to newer releases over time; receipts retain the concrete resolved model.
Claude Code
supports `max` in subagent frontmatter even though `max` is not accepted as a
persistent top-level `effortLevel` setting. Confirm runtime resolution before
relying on any requested model or effort.

## Resolution rules

1. The task packet records the requested semantic profile.
2. The runtime adapter resolves the profile using the corresponding agent
   definition and records provider, actual model, actual effort, adapter
   schema, and runtime version in `RECEIPT.md`.
3. Environment, account policy, or a runtime flag may override a provider
   configuration. Any model/effort warning or substitution is recorded.
4. `deep` and `pivotal` never downgrade silently. If the requested tier is
   unavailable, stop the focused task, preserve any already-created output,
   and return a visible runtime-failure receipt. Lower-tier exploratory work is
   allowed only when explicitly labeled provisional; the requested review
   remains pending.
5. A `pivotal` task must confirm the resolved tier before treating any result
   as satisfying the assignment. Unsupported `ultra`/`max` is a runtime
   failure, not a research conclusion.

## Responsibility and write boundaries

- The `coordinator` is the only adapter role permitted to integrate
  `PROJECT.md`, `STATE.md`, `ARTIFACT_INDEX.md`, `OVERVIEW.md`, the direction
  portfolio, the inbox, or `manuscript-ai/`. `manuscript-human/` follows its
  separate human-directed boundary. Consequential contract edits still require
  an explicit human decision.
- Focused agents write only their assigned run/task directory and explicitly
  preallocated artifact paths. Provider hooks mechanically protect central
  records, and their instructions require a handoff to the coordinator.
- A verifier writes its assigned review/output only and never edits the target
  claim. Verification must use a fresh context packet rather than the
  producer's conversational reasoning.
- No role invokes Git, requests worktree isolation, or synchronizes Overleaf.

## Changing mappings

To replace a model or effort setting:

1. Confirm the candidate value in the provider's current official docs and on
   the intended account/runtime.
2. Update this table and the matching files under `.codex/agents/` and
   `.claude/agents/`.
3. Assign a new adapter version in every adapter file for any mapping,
   contract, or file-shape change. Append a complete mapping-history block for
   the new version and never remove the older rows.
4. Run `python3 tools/research.py doctor --runtime codex|claude` and all guard
   self-tests.
5. Execute one harmless focused-task canary and confirm the receipt reports the
   requested model and effort. Do not infer capability merely because a config
   file parses.

## Runtime caveats

- Project adapters load only after the workspace/configuration is trusted.
- Provider-native chat history, auto-memory, and subagent memory are
  non-authoritative. Both adapters disable automatic memory where the current
  runtimes provide a documented project setting.
- Provider or organization policy can block a model. Claude Code may substitute
  an allowed model and warns interactively; Codex availability also depends on
  account and client support. The receipt and `doctor` checks make this visible.
- Exact cost and usage fields are recorded when the runtime exposes them; their
  absence is recorded as unavailable rather than estimated.

Current configuration references:

- [Codex subagents](https://learn.chatgpt.com/docs/agent-configuration/subagents)
- [Codex hooks](https://learn.chatgpt.com/docs/hooks)
- [OpenAI GPT-6 models](https://developers.openai.com/api/docs/models)
- [Claude Code subagents](https://code.claude.com/docs/en/subagents)
- [Claude Code model configuration](https://code.claude.com/docs/en/model-config)
- [Claude Code CLI model aliases](https://code.claude.com/docs/en/cli-usage)
- [Anthropic Claude Opus 5.5 announcement](https://www.anthropic.com/claude-opus-5-5)
- [Anthropic Claude Sonnet 5 announcement](https://www.anthropic.com/news/claude-sonnet-5)
- [Anthropic model deprecations and current Haiku availability](https://docs.anthropic.com/en/docs/about-claude/model-deprecations)
