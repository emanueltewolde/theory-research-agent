#!/usr/bin/env python3
"""Protect integration-owned research records from focused subagents.

This guard is installed only in focused-agent configurations.  The coordinator
does not use it because serialized integration is responsible for updating the
protected records.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import re
import shlex
import sys
from collections.abc import Iterable, Sequence
from pathlib import Path


ADAPTER_SCHEMA = "research-agent-adapter-v3"
BLOCK_EXIT = 2

_PROTECTED_EXACT = {
    "ARTIFACT_INDEX.md",
    "literature/references.bib",
    "OVERVIEW.md",
    "PROJECT.md",
    "STATE.md",
    "research/DIRECTIONS.md",
    "research/INBOX.md",
}
_PROTECTED_PREFIXES = (
    ".agents/",
    ".claude/",
    ".codex/",
    "results_overview/",
    "curated_manuscript/",
    "reports/",
    "runtime/",
    "tools/guards/",
)
_PATCH_PATH = re.compile(r"^\*\*\* (?:(?:Add|Update|Delete) File|Move to):\s*(.+?)\s*$", re.MULTILINE)
_READ_ONLY_SHELL_TOOLS = {
    "cat",
    "cmp",
    "diff",
    "echo",
    "file",
    "find",
    "grep",
    "get-content",
    "get-item",
    "head",
    "jq",
    "less",
    "ls",
    "md5sum",
    "more",
    "printf",
    "readlink",
    "rg",
    "sed",
    "select-string",
    "sha256sum",
    "shasum",
    "stat",
    "tail",
    "wc",
}
_FOCUSED_SAFE_RESEARCH_ACTIONS = {"check", "doctor"}


def _protected_paths(role: str) -> tuple[set[str], tuple[str, ...]]:
    exacts = set(_PROTECTED_EXACT)
    prefixes = _PROTECTED_PREFIXES
    if role == "verifier":
        prefixes += ("research/claims/",)
    elif role == "writer":
        exacts.update({"AGENTS.md", "CLAUDE.md", "README.md", "curated_manuscript/WRITING_ORIENTATION.md"})
        prefixes = tuple(p for p in prefixes if p != "curated_manuscript/")
        prefixes += ("research/", "literature/", "experiments/", "docs/", "templates/", "tools/")
    return exacts, prefixes


def _writer_writable(path: str) -> bool:
    # Coarse role boundary only. The task packet further restricts exact files.
    if path.startswith("curated_manuscript/"):
        return path != "curated_manuscript/writing_orientation.md"
    return bool(re.fullmatch(r"runs/run-\d{4,}/tasks/t\d{2,}/(?!task\.md$).+", path))


def _looks_like_project_root(path: Path) -> bool:
    return (path / "ARTIFACT_INDEX.md").exists() and (path / "AGENTS.md").exists()


def _writer_shell_path(path: str, cwd: str | None) -> bool:
    # Token extraction also returns command names and prose, which are not targets.
    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        candidate = Path(cwd or os.getcwd()) / candidate
    return candidate.exists() or (
        not any(c.isspace() for c in path) and any(c in path for c in "/\\.")
    )


def _project_root(cwd: str | None, target: Path | None = None) -> Path:
    configured = os.environ.get("CLAUDE_PROJECT_DIR") or os.environ.get("RESEARCH_PROJECT_ROOT")
    starts = [Path(configured)] if configured else []
    starts.append(Path(cwd or os.getcwd()))
    if target is not None:
        starts.append(target.parent if target.suffix else target)
    for start in starts:
        resolved = start.resolve(strict=False)
        for candidate in (resolved, *resolved.parents):
            if _looks_like_project_root(candidate):
                return candidate
    return Path(cwd or os.getcwd()).resolve(strict=False)


def _canonical(path: str, cwd: str | None = None) -> str:
    value = path.strip().strip("'\"")
    base = Path(cwd or os.getcwd()).resolve(strict=False)
    candidate = Path(value).expanduser()
    absolute = Path(os.path.abspath(candidate if candidate.is_absolute() else base / candidate))
    root = _project_root(cwd)
    try:
        return absolute.relative_to(root).as_posix()
    except ValueError:
        return absolute.as_posix()


def _resolved_canonical(path: str, cwd: str | None = None) -> str:
    value = path.strip().strip("'\"")
    base = Path(cwd or os.getcwd()).resolve(strict=False)
    candidate = Path(value).expanduser()
    absolute = (candidate if candidate.is_absolute() else base / candidate).resolve(strict=False)
    root = _project_root(cwd)
    try:
        return absolute.relative_to(root).as_posix()
    except ValueError:
        return absolute.as_posix()


def _protected_symlink_target(path: str, cwd: str | None, role: str = "focused") -> bool:
    base = Path(cwd or os.getcwd()).resolve(strict=False)
    candidate = Path(path.strip().strip("'\"")).expanduser()
    absolute = (candidate if candidate.is_absolute() else base / candidate).resolve(strict=False)
    root = _project_root(cwd)
    links: list[Path] = []
    exacts, prefixes = _protected_paths(role)
    for exact in exacts:
        item = root / exact
        if item.is_symlink():
            links.append(item)

    for prefix in prefixes:
        directory = root / prefix.rstrip("/")
        if directory.is_symlink():
            links.append(directory)
        elif directory.exists():
            links.extend(item for item in directory.rglob("*") if item.is_symlink())
    return any(
        (resolved := link.resolve(strict=False)) == absolute
        or resolved in absolute.parents
        for link in links
    )


def is_protected(path: str, cwd: str | None = None, role: str = "focused") -> bool:
    exacts, prefixes = _protected_paths(role)
    for normalized in {_canonical(path, cwd), _resolved_canonical(path, cwd)}:
        folded = normalized.casefold()
        if role == "writer" and not _writer_writable(folded):
            return True
        if folded in {value.casefold() for value in exacts}:
            return True
        if any(
            folded == prefix.casefold().rstrip("/") or folded.startswith(prefix.casefold())
            for prefix in prefixes
        ):
            return True
    return _protected_symlink_target(path, cwd, role)


def _is_protected_ancestor(path: str, cwd: str | None, role: str) -> bool:
    normalized = _canonical(path, cwd).casefold().rstrip("/")
    exacts, prefixes = _protected_paths(role)
    if role == "writer" and not _writer_writable(normalized):
        return True
    targets = {value.casefold() for value in exacts}
    targets.update(prefix.casefold().rstrip("/") for prefix in prefixes)
    if role == "verifier":
        targets.add("research/claims")
    if normalized in {"", "."}:
        return True
    return any(target == normalized or target.startswith(normalized + "/") for target in targets)


def _brace_variants(value: str) -> list[str]:
    match = re.search(r"\{([^{}]+)\}", value)
    if match is None:
        return [value]
    choices = match.group(1).split(",")
    if len(choices) < 2 or len(choices) > 16:
        return [value]
    return [value[:match.start()] + choice + value[match.end():] for choice in choices]


def _command_path_candidates(command: str, cwd: str | None, depth: int = 0) -> list[str]:
    candidates: list[str] = []
    base = Path(cwd or os.getcwd())
    try:
        tokens = shlex.split(command, posix=True)
    except ValueError:
        tokens = re.split(r"\s+", command)
    for token in tokens:
        raw = token.strip("'\"`()[],:;|<>")
        for candidate in _brace_variants(raw):
            candidate = candidate.strip("{}")
            if not candidate or candidate.startswith("-"):
                continue
            if candidate.casefold().startswith("of="):
                candidate = candidate[3:].strip("'\"")
            if any(character in candidate for character in "*?["):
                value = Path(candidate).expanduser()
                pattern = str(value if value.is_absolute() else base / value)
                candidates.extend(glob.glob(pattern) or [candidate])
            else:
                candidates.append(candidate)
    candidates.extend(
        match.group(0)
        for match in re.finditer(r"(?i)(?:[A-Za-z]:)?[A-Za-z0-9_./\\ -]+\.(?:bib|csv|json|md|tex|toml|yaml|yml)", command)
        if match.group(0).strip()
    )
    candidates.extend(
        match.group(1)
        for match in re.finditer(r"(?is)(?:open|path)\s*\(\s*['\"]([^'\"]+)['\"]", command)
    )
    if depth < 2:
        for token in tokens:
            if any(character.isspace() for character in token):
                candidates.extend(_command_path_candidates(token, cwd, depth + 1))
    return candidates


def _paths_from_patch(command: str) -> Iterable[str]:
    yield from _PATCH_PATH.findall(command)


def _top_level_segments(command: str) -> list[str]:
    segments: list[str] = []
    current: list[str] = []
    quote: str | None = None
    escaped = False
    index = 0
    while index < len(command):
        character = command[index]
        if escaped:
            current.append(character)
            escaped = False
        elif character == "\\" and quote != "'":
            current.append(character)
            escaped = True
        elif quote is not None:
            current.append(character)
            if character == quote:
                quote = None
        elif character in {"'", '"'}:
            quote = character
            current.append(character)
        elif character in {";", "|", "&", "\n"}:
            value = "".join(current).strip()
            if value:
                segments.append(value)
            current = []
            if character in {"|", "&"} and index + 1 < len(command) and command[index + 1] == character:
                index += 1
        else:
            current.append(character)
        index += 1
    value = "".join(current).strip()
    if value:
        segments.append(value)
    return segments


def _leading_cd(command: str, cwd: str | None) -> tuple[str, str] | None:
    match = re.match(
        r"^\s*cd\s+(?P<directory>'[^']*'|\"[^\"]*\"|[^\s;&|]+)\s*(?:&&|;)\s*(?P<rest>.+)$",
        command,
        re.DOTALL,
    )
    if match is None:
        return None
    directory = match.group("directory").strip("'\"")
    target = Path(directory).expanduser()
    if not target.is_absolute():
        target = Path(cwd or os.getcwd()) / target
    return str(target.resolve(strict=False)), match.group("rest")


def _unwrap_command_tokens(tokens: list[str]) -> list[str]:
    tokens = list(tokens)
    while tokens:
        executable = tokens[0].replace("\\", "/").rsplit("/", 1)[-1].casefold()
        if re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", tokens[0]):
            tokens.pop(0)
            continue
        if executable in {"command", "exec", "nice", "nohup", "setsid", "stdbuf", "sudo", "time"}:
            tokens.pop(0)
            while tokens and tokens[0].startswith("-"):
                option = tokens.pop(0).casefold()
                if option in {"-n", "--adjustment", "-u", "--user", "-g", "--group", "-c", "--close-from", "-o", "-e", "-i"} and tokens:
                    tokens.pop(0)
            continue
        if executable == "env":
            tokens.pop(0)
            while tokens and (tokens[0].startswith("-") or re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", tokens[0])):
                option = tokens.pop(0).casefold()
                if option in {"-c", "--chdir", "-u", "--unset", "-s", "--split-string"} and tokens:
                    tokens.pop(0)
            continue
        if executable == "timeout":
            tokens.pop(0)
            while tokens and tokens[0].startswith("-"):
                option = tokens.pop(0).casefold()
                if option in {"-k", "--kill-after", "-s", "--signal"} and tokens:
                    tokens.pop(0)
            if tokens:
                tokens.pop(0)
            continue
        break
    return tokens


def _research_cli_invocations(
    command: str, depth: int = 0, cwd: str | None = None
) -> list[tuple[str, list[str]]]:
    if depth > 3:
        return []
    found: list[tuple[str, list[str]]] = []
    shells = {"bash", "cmd", "cmd.exe", "fish", "powershell", "powershell.exe", "pwsh", "pwsh.exe", "sh", "zsh"}
    for segment in _top_level_segments(command):
        try:
            raw_tokens = shlex.split(segment.replace("\\", "/"), posix=True)
        except ValueError:
            continue
        if raw_tokens:
            raw_executable = raw_tokens[0].replace("\\", "/").rsplit("/", 1)[-1].casefold()
            for option in ({"-s", "--split-string"} if raw_executable == "env" else {"-c", "--command"} if raw_executable == "flock" else set()):
                if option in [value.casefold() for value in raw_tokens[1:]]:
                    position = [value.casefold() for value in raw_tokens].index(option)
                    if position + 1 < len(raw_tokens):
                        found.extend(_research_cli_invocations(raw_tokens[position + 1], depth + 1, cwd))
                    raw_tokens = []
                    break
            if raw_tokens and raw_executable == "flock":
                arguments = raw_tokens[1:]
                index = 0
                while index < len(arguments) and arguments[index].startswith("-"):
                    index += 1
                if index < len(arguments):
                    index += 1
                found.extend(_research_cli_invocations(" ".join(arguments[index:]), depth + 1, cwd))
                raw_tokens = []
            elif raw_tokens and raw_executable in {"eval", "xargs", "watch"}:
                arguments = raw_tokens[1:]
                while arguments and arguments[0].startswith("-"):
                    arguments.pop(0)
                found.extend(_research_cli_invocations(" ".join(arguments), depth + 1, cwd))
                raw_tokens = []
            elif raw_tokens and raw_executable == "start-process":
                arguments = raw_tokens[1:]
                program = arguments[0] if arguments else ""
                for position, value in enumerate(arguments[:-1]):
                    if value.casefold() == "-filepath":
                        program = arguments[position + 1]
                        break
                arg_position = next((position for position, value in enumerate(arguments) if value.casefold() == "-argumentlist"), None)
                invocation_args = arguments[arg_position + 1:] if arg_position is not None else arguments[1:]
                found.extend(_research_cli_invocations(program + " " + " ".join(invocation_args).replace(",", " "), depth + 1, cwd))
                raw_tokens = []
        tokens = _unwrap_command_tokens(raw_tokens)
        if not tokens:
            continue
        executable = tokens[0].replace("\\", "/").rsplit("/", 1)[-1].casefold()
        if executable in shells:
            arguments = tokens[1:]
            for index, argument in enumerate(arguments):
                lowered = argument.casefold()
                if lowered in {"-c", "-lc", "-command", "/c"} or (
                    lowered.startswith("-") and not lowered.startswith("--") and "c" in lowered[1:]
                ):
                    if index + 1 < len(arguments):
                        found.extend(_research_cli_invocations(" ".join(arguments[index + 1:]), depth + 1, cwd))
                    break
            continue
        arguments: list[str] | None = None
        if re.fullmatch(r"(?:python(?:3(?:\.\d+)*)?|py)(?:\.exe)?", executable):
            index = 1
            while index < len(tokens):
                token = tokens[index]
                if token.casefold() == "-m" and index + 1 < len(tokens):
                    if tokens[index + 1].casefold() == "tools.research":
                        arguments = tokens[index + 2:]
                    break
                if token.casefold() == "-mtools.research":
                    arguments = tokens[index + 1:]
                    break
                normalized = token.replace("\\", "/").casefold()
                script = Path(token).expanduser()
                if not script.is_absolute():
                    script = Path(cwd or os.getcwd()) / script
                canonical_script = (_project_root(cwd) / "tools/research.py").resolve(strict=False)
                if normalized.endswith("tools/research.py") or script.resolve(strict=False) == canonical_script:
                    arguments = tokens[index + 1:]
                    break
                if token.startswith("-"):
                    index += 2 if token in {"-W", "-X", "--check-hash-based"} and index + 1 < len(tokens) else 1
                    continue
                break
        elif tokens[0].replace("\\", "/").casefold().endswith("tools/research.py"):
            arguments = tokens[1:]
        if arguments is None:
            continue
        index = 0
        while index < len(arguments):
            token = arguments[index]
            if token == "--root" and index + 1 < len(arguments):
                index += 2
                continue
            if token.startswith("--root="):
                index += 1
                continue
            if token.startswith("-"):
                index += 1
                continue
            found.append((token.casefold(), arguments[index + 1:]))
            break
    return found


def _explicit_protected_path_in_command(command: str, cwd: str | None = None, role: str = "focused") -> str | None:
    normalized = command.replace("\\", "/")
    for token in re.split(r"\s+", command):
        value = token.strip("'\"`(){}[],:;|<>")
        if role == "writer" and not _writer_shell_path(value, cwd):
            continue
        if value and is_protected(value, cwd, role):
            return _canonical(value, cwd)
    exacts, prefixes = _protected_paths(role)
    candidates = sorted(exacts | set(prefixes), key=len, reverse=True)
    for candidate in candidates:
        pattern = rf"(?<![A-Za-z0-9_.-])(?:\./)?{re.escape(candidate)}"
        if re.search(pattern, normalized, re.IGNORECASE):
            return candidate.rstrip("/")
    return None


def _bash_may_modify(
    command: str, protected_path: str, cwd: str | None, role: str
) -> bool:
    """Associate a protected path with its shell segment before classifying it."""

    target = _canonical(protected_path, cwd).casefold().rstrip("/")
    for segment in _top_level_segments(command):
        if not segment.strip():
            continue
        segment_candidates = _command_path_candidates(segment, cwd)
        touches = any(
            _canonical(candidate, cwd).casefold().rstrip("/") == target
            for candidate in segment_candidates
        )
        escaped_literal = re.escape(protected_path.replace("\\", "/").rstrip("/"))
        embedded_write = bool(
            re.search(
                rf"(?is)(?:open|path)\s*\(\s*['\"]?{escaped_literal}['\"]?[^)]*['\"][wax+][^'\"]*['\"]",
                segment.replace("\\", "/"),
            )
            or re.search(
                rf"(?is)['\"]?{escaped_literal}['\"]?[^\n;]{{0,80}}\.write_(?:text|bytes)\s*\(",
                segment.replace("\\", "/"),
            )
        )
        if embedded_write:
            return True
        if not touches:
            continue
        for destination in re.findall(r">+(?:[|!])?\s*(?:['\"]([^'\"]+)['\"]|([^\s;&|]+))", segment):
            value = destination[0] or destination[1]
            if (
                _canonical(value, cwd).casefold().rstrip("/") == target
                or _is_protected_ancestor(value, cwd, role)
            ):
                return True
        normalized = segment.replace("\\", "/")
        if re.search(r"(?i)\bsed\b[^;&|\n]*(?:\s-[A-Za-z]*i(?:[A-Za-z.]*)?(?:\s|$)|--in-place(?:=|\s|$))", normalized):
            return True
        try:
            tokens = _unwrap_command_tokens(shlex.split(segment, posix=True))
        except ValueError:
            tokens = segment.split()
        while tokens and (re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", tokens[0]) or tokens[0] in {"!", "{"}):
            tokens.pop(0)
        if not tokens:
            continue
        executable = tokens[0].strip("'\"").replace("\\", "/").rsplit("/", 1)[-1].casefold()
        if executable in {"bash", "cmd", "cmd.exe", "fish", "powershell", "powershell.exe", "pwsh", "pwsh.exe", "sh", "zsh"}:
            command_body: str | None = None
            for index, argument in enumerate(tokens[1:]):
                lowered = argument.casefold()
                if (lowered in {"-c", "-lc", "-command", "/c"} or (
                    lowered.startswith("-") and not lowered.startswith("--") and "c" in lowered[1:]
                )) and index + 2 <= len(tokens) - 1:
                    command_body = " ".join(tokens[index + 2:])
                    break
            if command_body is not None:
                if _bash_may_modify(command_body, protected_path, cwd, role):
                    return True
                continue
        if executable in {"cp", "install", "copy-item", "tee", "tee-object", "out-file"}:
            operands = [token for token in tokens[1:] if not token.startswith("-")]
            if executable == "cp" and any(token.casefold() in {"-l", "--link"} or (token.startswith("-") and "l" in token[1:]) for token in tokens[1:]) and any(
                _canonical(value, cwd).casefold().rstrip("/") == target for value in operands
            ):
                return True
            if operands and _canonical(operands[-1], cwd).casefold().rstrip("/") == target:
                return True
            continue
        if executable == "ln":
            if any(token.casefold() in {"-s", "--symbolic"} for token in tokens[1:]):
                continue
            return True
        if executable == "find":
            if any(token.casefold() in {"-delete", "-exec", "-execdir", "-ok", "-okdir", "-fprint", "-fprint0", "-fprintf", "-fls"} for token in tokens[1:]):
                return True
            continue
        if executable == "dd":
            destinations = [token[3:] for token in tokens[1:] if token.casefold().startswith("of=")]
            if any(_canonical(value, cwd).casefold().rstrip("/") == target for value in destinations):
                return True
            continue
        if executable.startswith("export-"):
            return True
        if executable in {"python", "python3", "perl", "ruby", "node"}:
            continue
        if executable not in _READ_ONLY_SHELL_TOOLS:
            return True
    return False


def _mutating_research_action(command: str, cwd: str | None = None) -> str | None:
    """Return a non-read-only research CLI action, including future actions."""

    for action, arguments in _research_cli_invocations(command, cwd=cwd):
        if action not in _FOCUSED_SAFE_RESEARCH_ACTIONS and not (
            action == "adapters" and "--check" in arguments
        ):
            return action
    return None


def protected_target(payload: dict[str, object], role: str = "focused") -> str | None:
    tool_name = str(payload.get("tool_name", ""))
    cwd_value = payload.get("cwd")
    cwd = cwd_value if isinstance(cwd_value, str) else None
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        return None
    workdir = tool_input.get("workdir")
    if isinstance(workdir, str) and workdir:
        workdir_path = Path(workdir).expanduser()
        if not workdir_path.is_absolute():
            workdir_path = Path(cwd or os.getcwd()) / workdir_path
        cwd = str(workdir_path.resolve(strict=False))

    role = role.casefold()

    def protected(path: str) -> bool:
        normalized = _canonical(path, cwd)
        return is_protected(path, cwd, role) or (
            role == "verifier"
            and (
                normalized.casefold() == "research/claims"
                or normalized.casefold().startswith("research/claims/")
            )
        ) or _protected_symlink_target(path, cwd, role)

    for key in ("file_path", "path", "target_path", "notebook_path"):
        value = tool_input.get(key)
        if isinstance(value, str) and protected(value):
            return _canonical(value, cwd)

    command = tool_input.get("command")
    if not isinstance(command, str):
        return None
    changed_directory = _leading_cd(command, cwd)
    if changed_directory is not None:
        nested_cwd, nested_command = changed_directory
        nested_payload = dict(payload)
        nested_input = dict(tool_input)
        nested_input["command"] = nested_command
        nested_input["workdir"] = nested_cwd
        nested_payload["tool_input"] = nested_input
        return protected_target(nested_payload, role)
    if re.fullmatch(r"\s*cd(?:\s+[^;&|]+)?\s*", command):
        return None
    shell_tool = tool_name.lower() in {"bash", "powershell", "monitor"}
    if shell_tool:
        action = _mutating_research_action(command, cwd)
        if action is not None:
            return f"tools/research.py {action}"
    if tool_name.lower() in {"apply_patch", "edit", "write", "multiedit", "notebookedit"}:
        for path in _paths_from_patch(command):
            if protected(path):
                return _canonical(path, cwd)
    if shell_tool:
        for candidate in _command_path_candidates(command, cwd):
            if role == "writer" and not _writer_shell_path(candidate, cwd):
                continue
            if protected(candidate) or _is_protected_ancestor(candidate, cwd, role):
                normalized = _canonical(candidate, cwd)
                if not _bash_may_modify(command, candidate, cwd, role):
                    continue
                return normalized
    explicit = _explicit_protected_path_in_command(command, cwd, role)
    if explicit is None and role == "verifier":
        normalized_command = command.replace("\\", "/")
        if re.search(r"(?<![A-Za-z0-9_.-])(?:\./)?research/claims(?:/|\b)", normalized_command):
            explicit = "research/claims"
    if explicit is None:
        return None
    if shell_tool and not _bash_may_modify(command, explicit, cwd, role):
        return None
    return explicit


def _self_test() -> int:
    blocked = [
        {"tool_name": "Write", "tool_input": {"file_path": "STATE.md"}},
        {"tool_name": "Write", "tool_input": {"target_path": "STATE.md"}},
        {"tool_name": "Write", "tool_input": {"notebook_path": "STATE.md"}},
        {"tool_name": "Write", "tool_input": {"file_path": "state.md"}},
        {
            "tool_name": "Write",
            "cwd": str(Path.cwd() / "runs/RUN-0001/tasks/T01"),
            "tool_input": {"file_path": "../../../../STATE.md"},
        },
        {"tool_name": "Edit", "tool_input": {"file_path": str(Path.cwd() / "STATE.md")}},
        {"tool_name": "Edit", "tool_input": {"file_path": "results_overview/main.tex"}},
        {"tool_name": "Edit", "tool_input": {"file_path": "curated_manuscript/main.tex"}},
        {"tool_name": "Write", "tool_input": {"file_path": "reports/RPT-0001.md"}},
        {"tool_name": "Write", "tool_input": {"file_path": "literature/references.bib"}},
        {
            "tool_name": "apply_patch",
            "tool_input": {"command": "*** Begin Patch\n*** Update File: research/DIRECTIONS.md\n*** End Patch"},
        },
        {"tool_name": "Bash", "tool_input": {"command": "sed -i x PROJECT.md"}},
        {"tool_name": "Bash", "tool_input": {"command": "printf x > STATE.md"}},
        {"tool_name": "Bash", "tool_input": {"command": "cat /dev/null >! STATE.md"}},
        {"tool_name": "Bash", "tool_input": {"command": "bash -lc 'rm STATE.md'"}},
        {
            "tool_name": "Bash",
            "cwd": str(Path.cwd() / "runs/RUN-0001/tasks/T01"),
            "tool_input": {"command": "cat /dev/null > ../../../../STATE.md"},
        },
        {
            "tool_name": "Bash",
            "tool_input": {"command": f"head -n 1 /dev/null > {Path.cwd() / 'STATE.md'}"},
        },
        {"tool_name": "Bash", "tool_input": {"command": "rm STATE.md"}},
        {"tool_name": "Bash", "tool_input": {"command": "mv runs/draft.md STATE.md"}},
        {"tool_name": "Bash", "tool_input": {"command": "rm -r research"}},
        {"tool_name": "Bash", "tool_input": {"command": "rm *.md"}},
        {"tool_name": "Bash", "tool_input": {"command": "cp runs/draft.md PROJECT.md"}},
        {"tool_name": "PowerShell", "tool_input": {"command": "Set-Content STATE.md 'stale'"}},
        {"tool_name": "Bash", "tool_input": {"command": "dd if=/dev/null of=STATE.md"}},
        {"tool_name": "Bash", "tool_input": {"command": "python3 -c \"open('STATE.md','w').write('x')\""}},
        {"tool_name": "Bash", "tool_input": {"command": "python3 tools/research.py init"}},
        {"tool_name": "Bash", "tool_input": {"command": "python3 tools/research.py new claim"}},
        {"tool_name": "Bash", "tool_input": {"command": "python3 tools/research.py adapters --runtime codex"}},
        {"tool_name": "Bash", "tool_input": {"command": "python3 -m tools.research new experiment"}},
        {
            "tool_name": "Bash",
            "tool_input": {"command": "python3 tools/research.py check && python3 tools/research.py new claim"},
        },
        {"tool_name": "PowerShell", "tool_input": {"command": "python tools\\research.py new review"}},
        {"tool_name": "Bash", "tool_input": {"command": "python3 tools/research.py --root . new claim"}},
        {"tool_name": "Bash", "tool_input": {"command": "python3 -O -m tools.research --root=. new report"}},
        {"tool_name": "Bash", "tool_input": {"command": "python3 -mtools.research new claim"}},
        {"tool_name": "Bash", "tool_input": {"command": "python3 -X dev tools/research.py new claim"}},
        {"tool_name": "Bash", "tool_input": {"command": "python3 -W ignore -m tools.research new claim"}},
        {"tool_name": "Bash", "tool_input": {"command": "timeout 5 python3 -m tools.research new claim"}},
        {"tool_name": "Bash", "tool_input": {"command": "env -S 'python3 -m tools.research new claim'"}},
        {"tool_name": "Bash", "tool_input": {"command": "flock -c 'python3 -m tools.research new claim' /tmp/l"}},
        {"tool_name": "Bash", "tool_input": {"command": "flock /tmp/l python3 -m tools.research new claim"}},
        {"tool_name": "Bash", "tool_input": {"command": "xargs python3 -m tools.research new claim"}},
        {"tool_name": "Bash", "tool_input": {"command": "eval 'python3 -m tools.research new claim'"}},
        {"tool_name": "Bash", "tool_input": {"command": "watch python3 -m tools.research new claim"}},
        {"tool_name": "PowerShell", "tool_input": {"command": "Start-Process python3 -ArgumentList -m,tools.research,new,claim"}},
        {"tool_name": "Bash", "cwd": str(Path.cwd()), "tool_input": {"workdir": str(Path.cwd() / "runs"), "command": "rm ../STATE.md"}},
        {"tool_name": "Bash", "cwd": str(Path.cwd()), "tool_input": {"command": "cd runs && rm ../STATE.md"}},
        {"tool_name": "Bash", "tool_input": {"command": "rm {STATE,foo}.md"}},
        {"tool_name": "Bash", "tool_input": {"command": "rm STATE.{md,bak}"}},
        {"tool_name": "Bash", "tool_input": {"command": "find . -name STATE.md -delete"}},
        {"tool_name": "Bash", "tool_input": {"command": "find runs -fprint STATE.md"}},
        {"tool_name": "Bash", "tool_input": {"command": "sed -i.bak s/x/y/ STATE.md"}},
        {"tool_name": "Bash", "tool_input": {"command": "cp --link STATE.md runs/state-alias.md"}},
    ]
    allowed = [
        {"tool_name": "Write", "tool_input": {"file_path": "runs/RUN-0001/tasks/T01/OUTPUT.md"}},
        {"tool_name": "Write", "tool_input": {"file_path": "research/attempts/ATT-0001.md"}},
        {"tool_name": "Bash", "tool_input": {"command": "sed -n '1,80p' PROJECT.md"}},
        {"tool_name": "Bash", "tool_input": {"command": "rg -n Objective PROJECT.md"}},
        {"tool_name": "Bash", "tool_input": {"command": "cat STATE.md"}},
        {"tool_name": "Bash", "tool_input": {"command": "python3 tools/research.py check"}},
        {"tool_name": "PowerShell", "tool_input": {"command": "python tools\\research.py doctor --runtime claude"}},
        {"tool_name": "Bash", "tool_input": {"command": "cp PROJECT.md runs/project-copy.md"}},
        {"tool_name": "Bash", "tool_input": {"command": "cat PROJECT.md > runs/project-copy.md"}},
        {"tool_name": "PowerShell", "tool_input": {"command": "Get-Content STATE.md"}},
        {"tool_name": "Monitor", "tool_input": {"command": "cat STATE.md"}},
        {"tool_name": "Bash", "tool_input": {"command": "bash -lc 'cat STATE.md'"}},
        {"tool_name": "Bash", "tool_input": {"command": "echo STATE.md"}},
        {"tool_name": "Bash", "tool_input": {"command": "printf '%s\\n' STATE.md"}},
        {"tool_name": "Bash", "tool_input": {"command": "shasum STATE.md"}},
        {"tool_name": "Bash", "tool_input": {"command": "echo 'python3 tools/research.py new claim'"}},
        {"tool_name": "Bash", "tool_input": {"command": "python3 -c \"print('python3 tools/research.py new claim')\""}},
        {"tool_name": "Bash", "tool_input": {"command": "python3 tools/research.py adapters --runtime codex --check"}},
        {"tool_name": "Bash", "tool_input": {"command": "python3 -m tools.research --root . adapters --runtime claude --check"}},
        {"tool_name": "Bash", "tool_input": {"command": "cd research"}},
        {"tool_name": "Bash", "tool_input": {"command": "command cat STATE.md"}},
        {"tool_name": "Bash", "tool_input": {"command": "env LC_ALL=C rg State STATE.md"}},
        {"tool_name": "Bash", "tool_input": {"command": "time cat STATE.md"}},
        {"tool_name": "Bash", "tool_input": {"command": "jq . STATE.md"}},
        {"tool_name": "Bash", "tool_input": {"command": "ln -s STATE.md runs/state-link.md"}},
    ]
    verifier_blocked = [
        {"tool_name": "Write", "tool_input": {"file_path": "research/claims/CLM-0001.md"}},
        {
            "tool_name": "apply_patch",
            "tool_input": {
                "command": "*** Begin Patch\n*** Update File: research/claims/CLM-0001.md\n*** End Patch"
            },
        },
        {"tool_name": "Bash", "tool_input": {"command": "sed -i x research/claims/CLM-0001.md"}},
        {
            "tool_name": "Bash",
            "cwd": str(Path.cwd() / "research/claims"),
            "tool_input": {"command": "sed -i x CLM-0001.md"},
        },
    ]
    verifier_allowed = [
        {"tool_name": "Bash", "tool_input": {"command": "cat research/claims/CLM-0001.md"}},
        {"tool_name": "Write", "tool_input": {"file_path": "research/reviews/REV-0001.md"}},
    ]

    failures = [case for case in blocked if protected_target(case) is None]
    failures.extend(case for case in allowed if protected_target(case) is not None)
    failures.extend(case for case in verifier_blocked if protected_target(case, "verifier") is None)
    failures.extend(case for case in verifier_allowed if protected_target(case, "verifier") is not None)
    if failures:
        print(f"protect_shared.py self-test failures: {failures!r}", file=sys.stderr)
        return 1
    total = len(blocked) + len(allowed) + len(verifier_blocked) + len(verifier_allowed)
    print(f"protect_shared.py self-test passed ({total} cases; {ADAPTER_SCHEMA})")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--role", default="focused")
    parser.add_argument("--hook", choices=("auto", "codex", "claude"), default="auto")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args(argv)
    if args.self_test:
        return _self_test()
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, OSError) as exc:
        print(f"Shared-record guard could not parse hook input: {exc}", file=sys.stderr)
        return BLOCK_EXIT
    if not isinstance(payload, dict):
        print("Shared-record guard expected a JSON object.", file=sys.stderr)
        return BLOCK_EXIT
    target = protected_target(payload, args.role)
    if target is not None:
        print(
            f"Blocked for {args.role} role: {target} is integration-owned. "
            "Write findings to the assigned task/artifact path and ask the coordinator to integrate them.",
            file=sys.stderr,
        )
        return BLOCK_EXIT
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
