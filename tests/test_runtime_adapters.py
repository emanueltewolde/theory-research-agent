"""Conformance tests for runtime adapters and their dependency-free guards.

The tests treat the project checkout as read-only.  Hook subprocesses run with
an isolated temporary working directory, receive only synthetic JSON payloads,
and use ``-B`` so their execution cannot create bytecode beside the checked-in
guard modules.  No test invokes a version-control executable.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

try:  # Python 3.11+; TOML parsing is skipped, not reimplemented, on 3.10.
    import tomllib
except ImportError:  # pragma: no cover - exercised by the supported 3.10 CLI.
    tomllib = None  # type: ignore[assignment]


ROOT = Path(__file__).resolve().parents[1]
GUARD_DIR = ROOT / "tools" / "guards"
SCHEMA = "research-agent-adapter-v3"
FOCUSED_ROLES = (
    "maintenance", "substantive", "deep", "pivotal",
    "verifier", "verifier_deep", "verifier_pivotal", "writer",
)
ALL_ROLES = ("maintenance", "coordinator", *FOCUSED_ROLES)


def _load_module(name: str, path: Path):
    """Load one checked-in module without making its directory importable."""

    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not construct a module spec for {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


NO_GIT = _load_module("_test_no_git_guard", GUARD_DIR / "no_git.py")
NO_WORKTREE = _load_module("_test_no_worktree_guard", GUARD_DIR / "no_worktree.py")
PROTECT_EVIDENCE = _load_module("_test_protect_evidence_guard", GUARD_DIR / "protect_evidence.py")
PROTECT_RUNTIME = _load_module("_test_protect_runtime_guard", GUARD_DIR / "protect_runtime.py")
PROTECT_SHARED = _load_module("_test_protect_shared_guard", GUARD_DIR / "protect_shared.py")


def _invoke_guard(filename: str, payload: object, *arguments: str) -> subprocess.CompletedProcess[str]:
    """Invoke a hook exactly as a runtime would, but from a temporary cwd."""

    with tempfile.TemporaryDirectory(prefix="research-guard-test-") as temporary:
        return subprocess.run(
            [sys.executable, "-B", str(GUARD_DIR / filename), *arguments],
            cwd=temporary,
            input=json.dumps(payload),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=10,
        )


def _claude_frontmatter(path: Path) -> dict[str, str]:
    """Read the scalar fields used by the checked-in Claude agent files."""

    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        raise AssertionError(f"{path} has no opening frontmatter delimiter")
    try:
        header = text.split("---\n", 2)[1]
    except IndexError as error:
        raise AssertionError(f"{path} has no closing frontmatter delimiter") from error
    values: dict[str, str] = {}
    for line in header.splitlines():
        match = re.match(r"^([A-Za-z][A-Za-z0-9_-]*):\s*([^#]*?)\s*$", line)
        if match:
            values[match.group(1)] = match.group(2).strip("'\"")
    return values


def _profile_mappings() -> dict[str, dict[str, tuple[str, str]]]:
    """Extract the two provider columns from the public Markdown profile table."""

    text = (ROOT / "runtime" / "PROFILES.md").read_text(encoding="utf-8")
    mappings: dict[str, dict[str, tuple[str, str]]] = {}
    for line in text.splitlines():
        if not line.startswith("| `"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) < 4:
            continue
        profile = cells[0].strip("`")
        codex_values = re.findall(r"`([^`]+)`", cells[2])
        claude_values = re.findall(r"`([^`]+)`", cells[3])
        if len(codex_values) >= 2 and len(claude_values) >= 2:
            mappings[profile] = {
                "codex": (codex_values[0], codex_values[1]),
                "claude": (claude_values[0], claude_values[1]),
            }
    return mappings


def _hook_commands(document: dict[str, object]) -> list[str]:
    commands: list[str] = []
    hooks = document.get("hooks")
    if not isinstance(hooks, dict):
        return commands
    groups = hooks.get("PreToolUse")
    if not isinstance(groups, list):
        return commands
    for group in groups:
        if not isinstance(group, dict):
            continue
        entries = group.get("hooks")
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if isinstance(entry, dict) and isinstance(entry.get("command"), str):
                commands.append(entry["command"])
    return commands


class NoGitGuardTests(unittest.TestCase):
    def test_direct_path_qualified_wrapped_and_powershell_commands_are_blocked(self) -> None:
        blocked = (
            "git status",
            "/usr/bin/git diff --stat",
            "/opt/homebrew/bin/git log -1",
            r'"C:\Program Files\Git\bin\git.exe" status',
            "env LC_ALL=C git status",
            "bash -lc 'git status'",
            "echo ready && command git status",
            "/usr/bin/g?t status",
            "find . -exec /usr/bin/git status ;",
            "echo $(git status)",
            r'''powershell -Command "& 'C:\Program Files\Git\bin\git.exe' status"''',
            r'& "C:\Program Files\Git\bin\git.exe" status',
        )
        missed = [command for command in blocked if not NO_GIT.contains_git_invocation(command)]
        self.assertEqual([], missed)

    def test_benign_uses_of_the_word_git_are_allowed(self) -> None:
        allowed = (
            "echo git",
            "printf 'digital research'",
            "python3 -c \"print('git')\"",
            "rg --files research",
            "python3 tools/research.py check",
        )
        false_positives = [command for command in allowed if NO_GIT.contains_git_invocation(command)]
        self.assertEqual([], false_positives)

    def test_git_metadata_edit_write_and_patch_payloads_are_blocked(self) -> None:
        blocked = (
            {"tool_name": "Edit", "tool_input": {"file_path": ".git/config"}},
            {"tool_name": "Write", "tool_input": {"path": "/workspace/.git/HEAD"}},
            {"tool_name": "Write", "tool_input": {"target_path": r".git\index"}},
            {
                "tool_name": "apply_patch",
                "tool_input": {
                    "command": "*** Begin Patch\n*** Update File: .git/config\n@@\n-old\n+new\n*** End Patch"
                },
            },
            {
                "tool_name": "PowerShell",
                "tool_input": {"command": r'& "C:\Program Files\Git\bin\git.exe" status'},
            },
        )
        missed = [payload for payload in blocked if not NO_GIT.payload_accesses_git(payload)]
        self.assertEqual([], missed)

        safe = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "runs/RUN-0001/RUN.md",
                "content": "The human owns Git; agents do not use it.",
            },
        }
        self.assertFalse(NO_GIT.payload_accesses_git(safe))

    def test_hook_subprocess_fails_closed_for_blocked_payload_and_allows_safe_payload(self) -> None:
        blocked = _invoke_guard(
            "no_git.py",
            {"tool_name": "Bash", "tool_input": {"command": "echo ok && /usr/bin/git status"}},
            "--hook",
            "codex",
        )
        self.assertEqual(NO_GIT.BLOCK_EXIT, blocked.returncode, blocked.stderr)
        self.assertIn("Blocked by research workspace policy", blocked.stderr)

        safe = _invoke_guard(
            "no_git.py",
            {"tool_name": "Bash", "tool_input": {"command": "python3 tools/research.py check"}},
            "--hook",
            "claude",
        )
        self.assertEqual(0, safe.returncode, safe.stderr)


class NoWorktreeGuardTests(unittest.TestCase):
    def test_native_and_cli_worktree_requests_are_blocked(self) -> None:
        blocked = (
            {"tool_input": {"isolation": "worktree"}},
            {"tool_input": {"command": "claude --worktree proof-a"}},
            {"tool_input": {"command": "codex -w verifier"}},
            {"tool_input": {"command": "echo ready && codex --worktree=proof-b"}},
            {"tool_input": {"command": "\"/usr/local/bin/codex\" --worktree proof-q"}},
            {"tool_input": {"command": "env codex -w proof-env"}},
            {"tool_name": "PowerShell", "tool_input": {"command": "claude -w proof-c"}},
            {"tool_name": "EnterWorktree", "tool_input": {}},
        )
        missed = [payload for payload in blocked if not NO_WORKTREE.requests_worktree(payload)]
        self.assertEqual([], missed)

        allowed = (
            {"tool_input": {"isolation": "none"}},
            {"tool_input": {"command": "printf 'worktree policy documented'"}},
            {"tool_input": {"command": "python3 tools/research.py check"}},
        )
        false_positives = [payload for payload in allowed if NO_WORKTREE.requests_worktree(payload)]
        self.assertEqual([], false_positives)

    def test_hook_subprocess_blocks_worktree_isolation(self) -> None:
        blocked = _invoke_guard(
            "no_worktree.py",
            {"tool_name": "Agent", "tool_input": {"isolation": "worktree"}},
            "--hook",
            "claude",
        )
        self.assertEqual(NO_WORKTREE.BLOCK_EXIT, blocked.returncode, blocked.stderr)
        self.assertIn("worktree isolation", blocked.stderr)

        safe = _invoke_guard(
            "no_worktree.py",
            {"tool_name": "Agent", "tool_input": {"isolation": "none"}},
            "--hook",
            "codex",
        )
        self.assertEqual(0, safe.returncode, safe.stderr)


class ImmutableEvidenceGuardTests(unittest.TestCase):
    def test_existing_evidence_and_published_reports_are_protected(self) -> None:
        with tempfile.TemporaryDirectory(prefix="research-evidence-test-") as temporary:
            root = Path(temporary)
            evidence = root / "experiments/EXP-0001/executions/EXP-0001-E001/result.json"
            report = root / "reports/RPT-0001.md"
            evidence.parent.mkdir(parents=True)
            report.parent.mkdir(parents=True)
            evidence.write_text("result", encoding="utf-8")
            marker = evidence.parent / "COMPLETED.md"
            marker.write_text(
                "# EXP-0001-E001 — Completed execution\n\n"
                "- **Execution ID:** EXP-0001-E001\n"
                "- **Completed:** 2026-08-17\n"
                "- **Command/config:** run\n"
                "- **Inputs:** inputs/a\n"
                "- **Outputs:** result.json\n"
                "- **Output digest:** sha256:test\n"
                "- **Result:** success\n",
                encoding="utf-8",
            )
            report.write_text("# RPT-0001 — x\n\n- **Status:** published\n", encoding="utf-8")

            blocked = (
                {"tool_name": "Write", "cwd": temporary, "tool_input": {"file_path": str(evidence)}},
                {"tool_name": "Edit", "cwd": temporary, "tool_input": {"file_path": str(report)}},
                {"tool_name": "Bash", "cwd": temporary, "tool_input": {"command": "rm experiments/EXP-0001/executions/EXP-0001-E001/result.json"}},
                {"tool_name": "Write", "cwd": temporary, "tool_input": {"file_path": str(evidence.parent / "late.json")}},
            )
            for payload in blocked:
                with self.subTest(payload=payload):
                    self.assertIsNotNone(PROTECT_EVIDENCE.protected_target(payload))

            append = {
                "tool_name": "Write",
                "cwd": temporary,
                "tool_input": {"file_path": "experiments/EXP-0001/executions/EXP-0001-E002/result.json"},
            }
            self.assertIsNone(PROTECT_EVIDENCE.protected_target(append))

    def test_evidence_guard_subprocess_self_test_passes(self) -> None:
        result = subprocess.run(
            [sys.executable, "-B", str(GUARD_DIR / "protect_evidence.py"), "--self-test"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=10,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("self-test passed", result.stdout)


class ProtectedSharedRecordGuardTests(unittest.TestCase):
    def test_writer_can_edit_curated_content_and_task_output_but_not_research(self) -> None:
        for path in ("curated_manuscript/main.tex", "curated_manuscript/PROVENANCE.md",
                     "curated_manuscript/sections/results.tex", "runs/RUN-0001/tasks/T01/OUTPUT.md"):
            with self.subTest(path=path):
                payload = {"tool_name": "Edit", "tool_input": {"file_path": path}}
                self.assertIsNone(PROTECT_SHARED.protected_target(payload, "writer"))
        for path in ("curated_manuscript/WRITING_ORIENTATION.md", "results_overview/main.tex",
                     "research/claims/CLM-0001.md", "research/reviews/REV-0001.md",
                     "literature/references.bib", "experiments/new.py", "STATE.md",
                     "runs/RUN-0001/RUN.md", "runs/RUN-0001/tasks/T01/TASK.md"):
            with self.subTest(path=path):
                for payload in (
                    {"tool_name": "Edit", "tool_input": {"file_path": path}},
                    {"tool_name": "Bash", "tool_input": {"command": f"printf changed > {path}"}},
                    {"tool_name": "apply_patch", "tool_input": {"command": f"*** Begin Patch\n*** Update File: {path}\n*** End Patch"}},
                ):
                    self.assertIsNotNone(PROTECT_SHARED.protected_target(payload, "writer"))

    def test_writer_shell_reads_builds_and_bound_writes_remain_usable(self) -> None:
        for command in (
            "cat research/claims/CLM-0001.md",
            "sed -n '1,30p' curated_manuscript/WRITING_ORIENTATION.md",
            "printf updated > curated_manuscript/main.tex",
            "latexmk -pdf -cd curated_manuscript/main.tex",
            "cd curated_manuscript && latexmk -pdf main.tex",
            "python3 tools/research.py check",
        ):
            with self.subTest(command=command):
                payload = {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": str(ROOT)}
                self.assertIsNone(PROTECT_SHARED.protected_target(payload, "writer"))
        move = {"tool_name": "apply_patch", "tool_input": {"command":
                "*** Begin Patch\n*** Update File: curated_manuscript/main.tex\n"
                "*** Move to: research/claims/CLM-0001.md\n*** End Patch"}}
        self.assertIsNotNone(PROTECT_SHARED.protected_target(move, "writer"))
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "AGENTS.md").touch()
            (root / "ARTIFACT_INDEX.md").touch()
            (root / "curated_manuscript").mkdir()
            (root / "research").mkdir()
            (root / "curated_manuscript/alias.tex").symlink_to(root / "research/claim.md")
            payload = {"cwd": temp, "tool_name": "Write", "tool_input": {"file_path": "curated_manuscript/alias.tex"}}
            self.assertIsNotNone(PROTECT_SHARED.protected_target(payload, "writer"))

    def test_focused_writes_to_integration_owned_records_are_blocked(self) -> None:
        blocked = (
            {"tool_name": "Write", "tool_input": {"file_path": "STATE.md"}},
            {"tool_name": "Edit", "tool_input": {"file_path": "results_overview/main.tex"}},
            {"tool_name": "Edit", "tool_input": {"file_path": "curated_manuscript/main.tex"}},
            {"tool_name": "Write", "tool_input": {"path": ".codex/config.toml"}},
            {
                "tool_name": "apply_patch",
                "tool_input": {
                    "command": "*** Begin Patch\n*** Update File: research/DIRECTIONS.md\n*** End Patch"
                },
            },
            {"tool_name": "Bash", "tool_input": {"command": "sed -i x PROJECT.md"}},
            {"tool_name": "Bash", "tool_input": {"command": "printf stale > STATE.md"}},
            {"tool_name": "PowerShell", "tool_input": {"command": "Set-Content OVERVIEW.md stale"}},
            {"tool_name": "Bash", "tool_input": {"command": "rm -r research"}},
        )
        missed = [payload for payload in blocked if PROTECT_SHARED.protected_target(payload) is None]
        self.assertEqual([], missed)

    def test_focused_reads_and_bounded_writes_are_allowed(self) -> None:
        allowed = (
            {"tool_name": "Bash", "tool_input": {"command": "sed -n '1,80p' PROJECT.md"}},
            {"tool_name": "Bash", "tool_input": {"command": "rg -n Objective PROJECT.md"}},
            {"tool_name": "Bash", "tool_input": {"command": "cat STATE.md"}},
            {"tool_name": "Bash", "tool_input": {"command": "cat PROJECT.md > runs/project-copy.md"}},
            {"tool_name": "PowerShell", "tool_input": {"command": "Get-Content STATE.md"}},
            {"tool_name": "Monitor", "tool_input": {"command": "cat STATE.md"}},
            {
                "tool_name": "Write",
                "tool_input": {"file_path": "runs/RUN-0001/tasks/T01/OUTPUT.md"},
            },
            {"tool_name": "Write", "tool_input": {"file_path": "research/attempts/ATT-0001.md"}},
        )
        false_positives = [payload for payload in allowed if PROTECT_SHARED.protected_target(payload) is not None]
        self.assertEqual([], false_positives)

    def test_verifier_cannot_modify_target_claims_but_can_read_them(self) -> None:
        claim = "research/claims/CLM-0001.md"
        blocked = (
            {"tool_name": "Write", "tool_input": {"file_path": claim}},
            {"tool_name": "Edit", "tool_input": {"path": claim}},
            {
                "tool_name": "apply_patch",
                "tool_input": {
                    "command": f"*** Begin Patch\n*** Update File: {claim}\n*** End Patch"
                },
            },
            {"tool_name": "Bash", "tool_input": {"command": f"sed -i x {claim}"}},
        )
        for payload in blocked:
            with self.subTest(payload=payload):
                self.assertIsNotNone(PROTECT_SHARED.protected_target(payload, "verifier"))

        read_payload = {"tool_name": "Bash", "tool_input": {"command": f"cat {claim}"}}
        self.assertIsNone(PROTECT_SHARED.protected_target(read_payload, "verifier"))
        # Ordinary focused researchers may still write a preallocated claim.
        self.assertIsNone(PROTECT_SHARED.protected_target(blocked[0], "substantive"))

    def test_focused_research_cli_mutations_are_blocked_but_diagnostics_are_allowed(self) -> None:
        blocked_commands = (
            "python3 tools/research.py init",
            "python3 tools/research.py new claim",
            "python3 tools/research.py adapters --runtime codex",
            "python3 -m tools.research new experiment",
            "python3 tools/research.py check && python3 tools/research.py new review",
            r"python tools\research.py new literature",
        )
        for command in blocked_commands:
            with self.subTest(command=command):
                payload = {"tool_name": "Bash", "tool_input": {"command": command}}
                self.assertIsNotNone(PROTECT_SHARED.protected_target(payload))

        allowed_commands = (
            "python3 tools/research.py check",
            "python3 tools/research.py doctor --runtime codex",
            r"python tools\research.py doctor --runtime claude",
        )
        for command in allowed_commands:
            with self.subTest(command=command):
                payload = {"tool_name": "Bash", "tool_input": {"command": command}}
                self.assertIsNone(PROTECT_SHARED.protected_target(payload))

    def test_focused_guard_subprocess_blocks_mutation_and_allows_read(self) -> None:
        blocked = _invoke_guard(
            "protect_shared.py",
            {"tool_name": "Bash", "tool_input": {"command": "python3 tools/research.py new claim"}},
            "--role",
            "substantive",
            "--hook",
            "codex",
        )
        self.assertEqual(PROTECT_SHARED.BLOCK_EXIT, blocked.returncode, blocked.stderr)
        self.assertIn("integration-owned", blocked.stderr)

        safe = _invoke_guard(
            "protect_shared.py",
            {"tool_name": "Bash", "tool_input": {"command": "sed -n '1,20p' STATE.md"}},
            "--role",
            "verifier",
            "--hook",
            "claude",
        )
        self.assertEqual(0, safe.returncode, safe.stderr)


class RuntimeSafetyGuardTests(unittest.TestCase):
    def test_every_role_is_prevented_from_rewriting_runtime_safety_files(self) -> None:
        blocked = (
            {"tool_name": "Write", "tool_input": {"file_path": ".claude/settings.json"}},
            {"tool_name": "Edit", "tool_input": {"path": ".codex/config.toml"}},
            {
                "tool_name": "apply_patch",
                "tool_input": {
                    "command": "*** Begin Patch\n*** Update File: tools/guards/no_git.py\n*** End Patch"
                },
            },
            {"tool_name": "Bash", "tool_input": {"command": "sed -i x runtime/PROFILES.md"}},
            {"tool_name": "Write", "tool_input": {"file_path": "AGENTS.md"}},
            {"tool_name": "Write", "tool_input": {"file_path": "tools/research.py"}},
            {"tool_name": "Bash", "tool_input": {"command": "bash"}},
            {
                "tool_name": "Bash",
                "tool_input": {"command": "python3 tools/research.py adapters --runtime codex"},
            },
        )
        for payload in blocked:
            with self.subTest(payload=payload):
                self.assertIsNotNone(PROTECT_RUNTIME.protected_target(payload))

        read = {"tool_name": "Bash", "tool_input": {"command": "cat runtime/PROFILES.md"}}
        self.assertIsNone(PROTECT_RUNTIME.protected_target(read))
        adapter_check = {"tool_name": "Bash", "tool_input": {"command": "python3 tools/research.py adapters --runtime codex --check"}}
        self.assertIsNone(PROTECT_RUNTIME.protected_target(adapter_check))

    def test_runtime_guard_subprocess_self_test_passes(self) -> None:
        result = subprocess.run(
            [sys.executable, "-B", str(GUARD_DIR / "protect_runtime.py"), "--self-test"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=10,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("self-test passed", result.stdout)


class AdapterConfigurationTests(unittest.TestCase):
    @unittest.skipUnless(tomllib is not None, "stdlib tomllib requires Python 3.11+")
    def test_codex_toml_files_parse_with_the_standard_library(self) -> None:
        paths = [ROOT / ".codex" / "config.toml", *(ROOT / ".codex" / "agents").glob("*.toml")]
        self.assertEqual(1 + len(set(ALL_ROLES)), len(paths))
        for path in paths:
            with self.subTest(path=path.relative_to(ROOT)):
                parsed = tomllib.loads(path.read_text(encoding="utf-8"))
                self.assertIsInstance(parsed, dict)

    def test_runtime_json_files_parse_with_the_standard_library(self) -> None:
        for relative in (".codex/hooks.json", ".claude/settings.json"):
            with self.subTest(path=relative):
                parsed = json.loads((ROOT / relative).read_text(encoding="utf-8"))
                self.assertIsInstance(parsed, dict)

    def test_common_instruction_wiring_is_explicit(self) -> None:
        common = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
        claude = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")
        codex_readme = (ROOT / ".codex" / "README.md").read_text(encoding="utf-8")

        self.assertIn("# Research Agent Operating Contract", common)
        self.assertRegex(common, r"(?i)never run any Git command")
        self.assertEqual("@AGENTS.md", next(line for line in claude.splitlines() if line.strip()).strip())
        self.assertIn("root instructions", codex_readme)

    def test_semantic_profile_table_agrees_with_native_agent_definitions(self) -> None:
        mappings = _profile_mappings()
        self.assertEqual({"maintenance", "coordinator", "substantive", "deep", "pivotal"}, set(mappings))

        for role in ALL_ROLES:
            profile = {
                "verifier": "substantive",
                "verifier_deep": "deep",
                "verifier_pivotal": "pivotal",
                "writer": "substantive",
            }.get(role, role)
            codex_text = (ROOT / ".codex" / "agents" / f"{role}.toml").read_text(encoding="utf-8")
            model_match = re.search(r'(?m)^model\s*=\s*["\']([^"\']+)["\']', codex_text)
            effort_match = re.search(r'(?m)^model_reasoning_effort\s*=\s*["\']([^"\']+)["\']', codex_text)
            self.assertIsNotNone(model_match, role)
            self.assertIsNotNone(effort_match, role)
            self.assertEqual(mappings[profile]["codex"], (model_match.group(1), effort_match.group(1)))

            claude_fields = _claude_frontmatter(ROOT / ".claude" / "agents" / f"{role}.md")
            self.assertEqual(mappings[profile]["claude"], (claude_fields.get("model"), claude_fields.get("effort")))

    def test_codex_focused_guard_covers_every_native_write_surface(self) -> None:
        required = {"Bash", "apply_patch", "Edit", "Write"}
        for role in FOCUSED_ROLES:
            with self.subTest(role=role):
                text = (ROOT / ".codex" / "agents" / f"{role}.toml").read_text(encoding="utf-8")
                matcher = re.search(r'(?m)^matcher\s*=\s*["\']([^"\']+)["\']', text)
                self.assertIsNotNone(matcher)
                for tool in required:
                    self.assertIn(tool, matcher.group(1))
                self.assertIn("protect_shared.py", text)
                if role.startswith("verifier"):
                    self.assertIn("--role verifier", text)

    def test_production_adapter_check_helpers_report_no_profile_drift(self) -> None:
        try:
            research = _load_module("_test_research_adapter_helpers", ROOT / "tools" / "research.py")
        except (ImportError, RuntimeError, SyntaxError) as error:
            self.skipTest(f"production adapter helpers are not importable: {error}")

        for runtime in ("codex", "claude"):
            with self.subTest(runtime=runtime):
                report = research.check_adapters(ROOT, runtime)
                rendered = [diagnostic.render(ROOT) for diagnostic in report.errors]
                self.assertEqual([], rendered)

    @unittest.skipUnless(tomllib is not None, "stdlib tomllib requires Python 3.11+")
    def test_codex_memory_hooks_and_focused_boundaries_are_configured(self) -> None:
        config = tomllib.loads((ROOT / ".codex" / "config.toml").read_text(encoding="utf-8"))
        self.assertIs(config["memories"]["generate_memories"], False)
        self.assertIs(config["memories"]["use_memories"], False)
        self.assertIs(config["features"]["hooks"], True)
        self.assertEqual("on-request", config["approval_policy"])
        self.assertEqual("workspace-write", config["sandbox_mode"])
        self.assertIs(config["sandbox_workspace_write"]["network_access"], False)

        hook_document = json.loads((ROOT / ".codex" / "hooks.json").read_text(encoding="utf-8"))
        commands = "\n".join(_hook_commands(hook_document))
        self.assertIn("tools/guards/no_git.py", commands)
        self.assertIn("tools/guards/no_worktree.py", commands)
        self.assertIn("tools/guards/protect_evidence.py", commands)
        self.assertIn("tools/guards/protect_runtime.py", commands)

        native_rules = (ROOT / ".codex" / "rules" / "no-git.rules").read_text(encoding="utf-8")
        self.assertIn('decision = "forbidden"', native_rules)
        self.assertIn('pattern = ["git"]', native_rules)
        self.assertIn("/usr/bin/git", native_rules)

        coordinator = tomllib.loads((ROOT / ".codex" / "agents" / "coordinator.toml").read_text(encoding="utf-8"))
        self.assertNotIn("hooks", coordinator)
        for role in FOCUSED_ROLES:
            with self.subTest(role=role):
                path = ROOT / ".codex" / "agents" / f"{role}.toml"
                document = tomllib.loads(path.read_text(encoding="utf-8"))
                commands = str(document.get("hooks", {}))
                self.assertIn("protect_shared.py", commands)
                self.assertNotEqual("worktree", document.get("isolation"))

    def test_claude_memory_permissions_hooks_and_focused_boundaries_are_configured(self) -> None:
        settings = json.loads((ROOT / ".claude" / "settings.json").read_text(encoding="utf-8"))
        self.assertIs(settings["autoMemoryEnabled"], False)
        self.assertIs(settings["disableAllHooks"], False)
        self.assertIs(settings["enableAllProjectMcpServers"], False)
        self.assertEqual("1", settings["env"]["CLAUDE_CODE_DISABLE_AUTO_MEMORY"])
        self.assertEqual(SCHEMA, settings["env"]["RESEARCH_AGENT_ADAPTER_SCHEMA"])
        self.assertEqual("default", settings["permissions"]["defaultMode"])

        denies = settings["permissions"]["deny"]
        self.assertTrue(any(rule.startswith("Bash(git") for rule in denies))
        self.assertTrue(any("/usr/bin/git" in rule for rule in denies))
        self.assertIn("Read(/.git/**)", denies)
        self.assertIn("Edit(/.git/**)", denies)
        for protected in (".agents", ".claude", ".codex", "runtime", "tools/guards"):
            self.assertIn(f"Edit(/{protected}/**)", denies)
        self.assertTrue(any("--worktree" in rule for rule in denies))
        self.assertIn("EnterWorktree", denies)
        self.assertIn("Agent(isolation:worktree)", denies)

        commands = "\n".join(_hook_commands(settings))
        self.assertIn("tools/guards/no_git.py", commands)
        self.assertIn("tools/guards/no_worktree.py", commands)
        self.assertIn("tools/guards/protect_evidence.py", commands)
        self.assertIn("tools/guards/protect_runtime.py", commands)
        read_entries = [
            entry for entry in settings["hooks"]["PreToolUse"]
            if entry.get("matcher") == "Read|Glob|Grep"
        ]
        self.assertEqual(1, len(read_entries))
        self.assertIn("tools/guards/no_git.py", str(read_entries[0]))

        coordinator = (ROOT / ".claude" / "agents" / "coordinator.md").read_text(encoding="utf-8")
        self.assertNotIn("protect_shared.py", coordinator)
        for role in FOCUSED_ROLES:
            with self.subTest(role=role):
                path = ROOT / ".claude" / "agents" / f"{role}.md"
                text = path.read_text(encoding="utf-8")
                fields = _claude_frontmatter(path)
                self.assertIn("protect_shared.py", text)
                if role.startswith("verifier"):
                    self.assertIn("--role verifier", text)
                for surface in ("Bash", "PowerShell", "Monitor", "Edit", "Write", "NotebookEdit"):
                    self.assertIn(surface, text)
                self.assertNotIn("isolation", fields)
                self.assertNotIn("memory", fields)


if __name__ == "__main__":
    unittest.main()
