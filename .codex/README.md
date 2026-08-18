# Codex adapter

Adapter schema: `research-agent-adapter-v1`

This directory contains only runtime mechanics. The research method and source
of truth remain in the root instructions and research artifacts.

## Activation

1. Start Codex from the project root in the local checkout.
2. Trust the project so Codex loads `.codex/config.toml`, project agents,
   project rules, and `.codex/hooks.json`.
3. Open `/hooks`, review the exact project hook definitions, and trust them.
   Changed hooks are skipped until their new hash is trusted.
4. Run `python3 tools/research.py doctor --runtime codex` before autonomous
   write work.
5. Use named agents from `.codex/agents/`; do not override a `deep` or
   `pivotal` model/effort unless the task is explicitly being reclassified.

Hook commands use paths relative to the session working directory. The normal
workflow therefore starts at the project root, as required by the template. If
a host routinely starts Codex in subdirectories, render these commands to
absolute paths as a machine-local adapter step and re-trust the changed hooks.

## Safety behavior

- Workspace writes use the normal Codex sandbox; shell network access is off
  and out-of-workspace, destructive, or external actions remain approval-gated.
- Automatic Codex memory generation and injection are disabled. `STATE.md` and
  linked artifacts are the portable resume mechanism.
- Native exec-policy rules forbid ordinary and common path-qualified Git
  commands. A synchronous hook covers common wrappers and explicit `.git`
  targets in Bash, patch, edit, and write tools.
- A separate global hook protects existing experiment inputs/executions and
  published milestone reports while permitting creation of new append-only
  evidence paths.
- A global safety hook prevents every agent role from rewriting `.codex/`,
  `.claude/`, `runtime/`, `AGENTS.md`, `CLAUDE.md`, `tools/research.py`, or
  `tools/guards/`. Adapter changes are a human or trusted-external operation
  followed by `doctor` and hook re-approval.
- Bare interactive shells and stdin interpreters are denied because later
  `write_stdin` traffic to an existing process does not receive another
  pre-tool guard check. Use complete non-interactive commands.
- Focused agent files install an additional hook that protects integration-owned
  records. The same guard permits focused `research.py check` and `doctor` but
  denies `init`, `new`, `adapters`, and future non-read-only actions that could
  mutate shared indexes or runtime files without naming them in the shell
  command. In the verifier configuration it also makes target claim files
  read-only. The coordinator intentionally does not install that focused guard;
  it remains subject to the global runtime-safety and evidence guards.
- Do not start the desktop chat as **Worktree**, use Handoff to a worktree, or
  enable any worktree feature. Those surfaces perform Git operations outside
  the model's ordinary command tool and cannot be disabled by a documented
  project `config.toml` key.

`pivotal.toml` requests Codex `ultra` on `gpt-5.6-sol`, as exposed by current
local-agent documentation. If the installed client/account does not support
that setting, the pivotal agent must stop and report a runtime failure; it must
not silently run as `xhigh` or `max`. The API's `max` effort is a separate
surface and should not be substituted into this file without validating the
Codex client.

## Limits

Project hooks and rules are defense in depth, not an OS security boundary.
They can be absent in an untrusted project, disabled by an authorized user, or
bypassed by arbitrary code, a provider-specific read/MCP surface not matched by
the hook, or an indirect executable launch. Absolute
no-Git enforcement requires an environment that omits Git and hides/denies
`.git` at the operating-system or container boundary. Codex's standard
workspace sandbox protects `.git` and `.codex` from writes, but a higher-access
runtime override can weaken that protection.
