# Runtime guards

Adapter schema: `research-agent-adapter-v1`

These dependency-free Python programs are synchronous pre-tool guards shared
by the Codex and Claude Code adapters:

- `no_git.py` rejects direct, path-qualified, compound, and common
  shell-wrapped Git invocations, plus explicit `.git` targets in ordinary
  shell, patch, edit, and write hook payloads. It also rejects common
  project-root recursive readers that would implicitly descend into `.git`
  unless the command explicitly prunes/excludes that directory.
- `no_worktree.py` rejects runtime requests for Git worktree isolation.
- `protect_evidence.py` permits append-only creation but rejects ordinary
  overwrite/delete attempts against existing experiment inputs and execution
  evidence, and rejects edits to published milestone reports.
- `protect_runtime.py` prevents every in-runtime role, including the
  coordinator, from editing the common operating contract, runtime adapters,
  semantic profiles, validator, guards, or runtime-native instruction override
  files (including `.agents/` skills and nested `AGENTS*` and `CLAUDE*`
  instructions). Humans or
  trusted external automation make those changes outside the agent runtime. It also
  blocks common interactive shell/interpreter stdin transports because later
  writes to an existing process do not receive a fresh pre-tool hook check.
- `protect_shared.py` keeps focused roles from changing integration-owned
  records. It also denies focused use of mutating `research.py` actions because
  `init`, `new`, and future non-read-only actions can update shared indexes or
  adapters without naming their targets in the command. `check` and `doctor`
  remain allowed. For the verifier role it additionally makes every target
  under `research/claims/` read-only, while leaving the assigned review path
  writable. The guard is deliberately not installed for the coordinator.

Both runtimes pass JSON on standard input. A safe request exits `0`; a blocked
request explains the policy on standard error and exits `2`, which both current
hook systems treat as a denial. The scripts do not write files or invoke Git.

Run their built-in canaries from the project root:

```text
python3 tools/guards/no_git.py --self-test
python3 tools/guards/no_worktree.py --self-test
python3 tools/guards/protect_evidence.py --self-test
python3 tools/guards/protect_runtime.py --self-test
python3 tools/guards/protect_shared.py --self-test
```

## Security boundary

These guards complement native sandbox and permission rules. They cannot prove
that arbitrary code will not indirectly spawn Git, encode a forbidden path, or
use an unrecognized tool surface such as a provider-specific read or MCP tool.
Hooks can also be disabled by a sufficiently
privileged user or ignored when a project has not been trusted. High-assurance
operation therefore requires an operating-system/container boundary that omits
Git and denies access to `.git`, plus administrator-managed hooks or policies.

The shared-record guard examines explicit paths in normal file tools,
`apply_patch`, and shell commands. It permits familiar read-only inspection of
protected records while rejecting direct file-tool writes, patches, likely
shell mutators, and redirection into those paths. It does not replace serialized
integration, task-scoped write boundaries, or human review.

The evidence guard is state-aware for explicit file, patch, and ordinary shell
targets: a new input/execution path may be created once, after which normal
mutation is denied. A complete, valid visible `COMPLETED.md` execution manifest
freezes its whole execution directory, including filenames that did not
previously exist; an incomplete marker remains repairable while validation
reports it. Its
canary uses only a temporary directory. Code that
conceals an indirect write remains outside a text-inspection hook's guarantee;
read-only mounts or filesystem permissions are required for absolute evidence
immutability.

Codex does not re-run `PreToolUse` when bytes are sent to an already-running
unified-exec session. The runtime guard therefore rejects bare interactive
shells and stdin interpreters such as `bash` and `python3 -`; use a complete,
non-interactive command instead. Arbitrary long-running programs may expose
other command channels, so OS-level process and filesystem policy remains the
high-assurance boundary.

PowerShell and provider monitor tools are included in the relevant hook
matchers. Git, worktree, and `research.py` policy checks inspect their normal
command payloads. Common read-only inspection and copying *out of* protected
records are allowed; writes, ambiguous mutators, and copying *into* protected
paths fail closed. Use the runtime's file-read tool or a focused task packet's
supplied input when a provider command cannot be classified safely.
