#!/usr/bin/env python3
"""Deny agent-side mutation of project runtime safety configuration.

Humans or trusted external automation may edit these files outside the agent
runtime.  This synchronous hook keeps every in-runtime role, including the
coordinator, from weakening its own hooks, permissions, profiles, or guards.
It is defense in depth rather than an operating-system security boundary.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
from pathlib import Path, PurePath
import re
import shlex
import sys
from collections.abc import Iterable, Sequence


ADAPTER_SCHEMA = "research-agent-adapter-v2"
BLOCK_EXIT = 2
_PROTECTED_PREFIXES = (".agents/", ".claude/", ".codex/", "runtime/", "tools/guards/")
_PROTECTED_EXACT = (".mcp.json", "AGENTS.md", "CLAUDE.md", "tools/research.py")
_INSTRUCTION_BASENAMES = {
    "agents.md", "agents.override.md", "claude.md", "claude.local.md",
}
_PATCH_PATH = re.compile(r"^\*\*\* (?:Add|Update|Delete) File:\s*(.+?)\s*$", re.MULTILINE)
_READ_ONLY = {
    "cat", "cmp", "diff", "echo", "file", "find", "get-content", "get-item", "head",
    "jq", "less", "ls", "md5sum", "more", "printf", "readlink", "rg", "sed",
    "select-string", "sha256sum", "shasum", "stat", "tail", "wc",
}
_INTERACTIVE_SHELLS = {"bash", "cmd", "cmd.exe", "fish", "powershell", "powershell.exe", "pwsh", "pwsh.exe", "sh", "zsh"}
_INTERACTIVE_INTERPRETERS = {"node", "node.exe", "perl", "perl.exe", "python", "python.exe", "python3", "py", "ruby", "ruby.exe"}


def _looks_like_root(path: Path) -> bool:
    return (path / "ARTIFACT_INDEX.md").exists() and (path / "AGENTS.md").exists()


def _project_root(cwd: str | None, target: Path | None = None) -> Path:
    configured = os.environ.get("CLAUDE_PROJECT_DIR") or os.environ.get("RESEARCH_PROJECT_ROOT")
    starts = [Path(configured)] if configured else []
    starts.append(Path(cwd or os.getcwd()))
    if target is not None:
        starts.append(target.parent if target.suffix else target)
    for start in starts:
        resolved = start.resolve(strict=False)
        for candidate in (resolved, *resolved.parents):
            if _looks_like_root(candidate):
                return candidate
    return Path(cwd or os.getcwd()).resolve(strict=False)


def _canonical(path: str, cwd: str | None) -> str:
    value = path.strip().strip("'\"")
    base = Path(cwd or os.getcwd()).resolve(strict=False)
    candidate = Path(value).expanduser()
    absolute = Path(os.path.abspath(candidate if candidate.is_absolute() else base / candidate))
    root = _project_root(cwd)
    try:
        return absolute.relative_to(root).as_posix()
    except ValueError:
        return absolute.as_posix()


def _resolved_canonical(path: str, cwd: str | None) -> str:
    value = path.strip().strip("'\"")
    base = Path(cwd or os.getcwd()).resolve(strict=False)
    candidate = Path(value).expanduser()
    absolute = (candidate if candidate.is_absolute() else base / candidate).resolve(strict=False)
    root = _project_root(cwd)
    try:
        return absolute.relative_to(root).as_posix()
    except ValueError:
        return absolute.as_posix()


def _protected_symlink_target(path: str, cwd: str | None) -> bool:
    base = Path(cwd or os.getcwd()).resolve(strict=False)
    candidate = Path(path.strip().strip("'\"")).expanduser()
    absolute = (candidate if candidate.is_absolute() else base / candidate).resolve(strict=False)
    root = _project_root(cwd)
    links: list[Path] = []
    for exact in _PROTECTED_EXACT:
        item = root / exact
        if item.is_symlink():
            links.append(item)
    for prefix in _PROTECTED_PREFIXES:
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


def is_protected(path: str, cwd: str | None = None) -> bool:
    for normalized in {_canonical(path, cwd), _resolved_canonical(path, cwd)}:
        folded = normalized.casefold()
        if PurePath(normalized).name.casefold() in _INSTRUCTION_BASENAMES:
            return True
        if folded in {value.casefold() for value in _PROTECTED_EXACT}:
            return True
        if any(
            folded == prefix.casefold().rstrip("/") or folded.startswith(prefix.casefold())
            for prefix in _PROTECTED_PREFIXES
        ):
            return True
    return _protected_symlink_target(path, cwd)


def _is_protected_ancestor(path: str, cwd: str | None) -> bool:
    normalized = _canonical(path, cwd).casefold().rstrip("/")
    targets = {value.casefold() for value in _PROTECTED_EXACT}
    targets.update(prefix.casefold().rstrip("/") for prefix in _PROTECTED_PREFIXES)
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
        match.group(0).strip()
        for match in re.finditer(
            r"(?i)(?:[A-Za-z]:)?[A-Za-z0-9_./\\ -]+\.(?:bib|csv|json|md|py|tex|toml|yaml|yml)",
            command,
        )
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


def _patch_paths(command: str) -> Iterable[str]:
    yield from _PATCH_PATH.findall(command)


def _mentioned_path(command: str, cwd: str | None) -> str | None:
    # Tokenization is deliberately conservative for safety paths.  Strip
    # ordinary shell punctuation, then normalize relative/absolute tokens.
    for candidate in _command_path_candidates(command, cwd):
        if is_protected(candidate, cwd):
            return _canonical(candidate, cwd)
    normalized = command.replace("\\", "/")
    for prefix in _PROTECTED_PREFIXES:
        if re.search(rf"(?<![A-Za-z0-9_.-])(?:\.\./|\./)*{re.escape(prefix)}", normalized):
            return prefix.rstrip("/")
    return None


def _top_level_segments(command: str) -> list[str]:
    """Split shell control segments without treating quoted text as syntax."""

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
            index += 1
            continue
        if character == "\\" and quote != "'":
            current.append(character)
            escaped = True
            index += 1
            continue
        if quote is not None:
            current.append(character)
            if character == quote:
                quote = None
            index += 1
            continue
        if character in {"'", '"'}:
            quote = character
            current.append(character)
            index += 1
            continue
        if character in {";", "|", "&", "\n"}:
            value = "".join(current).strip()
            if value:
                segments.append(value)
            current = []
            if character in {"|", "&"} and index + 1 < len(command) and command[index + 1] == character:
                index += 1
            index += 1
            continue
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
                    index += 1  # lock file
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
        if executable in _INTERACTIVE_SHELLS:
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
                lowered = token.casefold()
                if lowered == "-m" and index + 1 < len(tokens):
                    if tokens[index + 1].casefold() == "tools.research":
                        arguments = tokens[index + 2:]
                    break
                if lowered == "-mtools.research":
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


def _nested_runtime_launch(command: str, depth: int = 0) -> str | None:
    if depth > 3:
        return None
    start_match = re.search(
        r"(?i)(?:^|[;&|]\s*)start\s+['\"][^'\"]*['\"]\s+"
        r"(?P<runtime>(?:[^\s;&|]*[/\\])?(?:claude|codex)(?:\.exe)?)\b",
        command,
    )
    if start_match is not None:
        return start_match.group("runtime").replace("\\", "/").rsplit("/", 1)[-1].casefold()
    for segment in _top_level_segments(command):
        try:
            raw_tokens = shlex.split(segment, posix=True)
        except ValueError:
            continue
        if raw_tokens:
            raw_executable = raw_tokens[0].replace("\\", "/").rsplit("/", 1)[-1].casefold()
            lowered = [value.casefold() for value in raw_tokens]
            if raw_executable == "env":
                for option in ("-s", "--split-string"):
                    if option in lowered[1:]:
                        position = lowered.index(option)
                        nested = _nested_runtime_launch(raw_tokens[position + 1], depth + 1) if position + 1 < len(raw_tokens) else None
                        if nested is not None:
                            return nested
                        raw_tokens = []
                        break
            elif raw_executable == "flock" and any(option in lowered[1:] for option in ("-c", "--command")):
                option = "-c" if "-c" in lowered else "--command"
                position = lowered.index(option)
                nested = _nested_runtime_launch(raw_tokens[position + 1], depth + 1) if position + 1 < len(raw_tokens) else None
                if nested is not None:
                    return nested
                raw_tokens = []
            if raw_tokens and raw_executable == "flock":
                arguments = raw_tokens[1:]
                index = 0
                while index < len(arguments) and arguments[index].startswith("-"):
                    index += 1
                if index < len(arguments):
                    index += 1
                nested = _nested_runtime_launch(" ".join(arguments[index:]), depth + 1)
                if nested is not None:
                    return nested
                raw_tokens = []
            elif raw_tokens and raw_executable in {"eval", "xargs", "watch"}:
                arguments = raw_tokens[1:]
                while arguments and arguments[0].startswith("-"):
                    arguments.pop(0)
                nested = _nested_runtime_launch(" ".join(arguments), depth + 1)
                if nested is not None:
                    return nested
                raw_tokens = []
            elif raw_tokens and raw_executable in {"saps", "start-process"}:
                arguments = raw_tokens[1:]
                program = arguments[0] if arguments else ""
                for position, value in enumerate(arguments[:-1]):
                    if value.casefold() == "-filepath":
                        program = arguments[position + 1]
                        break
                arg_position = next((position for position, value in enumerate(arguments) if value.casefold() == "-argumentlist"), None)
                invocation_args = arguments[arg_position + 1:] if arg_position is not None else arguments[1:]
                nested = _nested_runtime_launch(program + " " + " ".join(invocation_args).replace(",", " "), depth + 1)
                if nested is not None:
                    return nested
                raw_tokens = []
        tokens = _unwrap_command_tokens(raw_tokens)
        if not tokens:
            continue
        executable = tokens[0].replace("\\", "/").rsplit("/", 1)[-1].casefold()
        arguments = tokens[1:]
        if executable in _INTERACTIVE_SHELLS:
            for index, argument in enumerate(arguments):
                lowered = argument.casefold()
                if lowered in {"-c", "-lc", "-command", "/c"} or (
                    lowered.startswith("-") and not lowered.startswith("--") and "c" in lowered[1:]
                ):
                    if index + 1 < len(arguments):
                        nested = _nested_runtime_launch(" ".join(arguments[index + 1:]), depth + 1)
                        if nested is not None:
                            return nested
                    break
            continue
        if executable not in {"claude", "claude.exe", "codex", "codex.exe"}:
            continue
        normalized = [value.casefold() for value in arguments]
        if normalized in (["--version"], ["-v"], ["version"], ["--help"], ["-h"], ["help"]):
            continue
        return executable
    return None


def _mutating_adapter_action(command: str, cwd: str | None = None) -> bool:
    for action, arguments in _research_cli_invocations(command, cwd=cwd):
        if action == "adapters" and "--check" not in arguments:
            return True
    return False


def _safe_research_diagnostic(command: str, cwd: str | None = None) -> bool:
    invocations = _research_cli_invocations(command, cwd=cwd)
    if len(invocations) != 1 or len(_top_level_segments(command)) != 1:
        return False
    action, arguments = invocations[0]
    return action in {"check", "doctor"} or (action == "adapters" and "--check" in arguments)


def _opens_unchecked_stdin_transport(command: str) -> bool:
    """Block common command transports whose later stdin bypasses pre-tool hooks."""

    for segment in _top_level_segments(command):
        try:
            tokens = shlex.split(segment, posix=True)
        except ValueError:
            return True
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
            break
        if not tokens:
            continue
        executable = tokens[0].replace("\\", "/").rsplit("/", 1)[-1].casefold()
        arguments = tokens[1:]
        if executable in _INTERACTIVE_SHELLS:
            has_command = any(arg.casefold() in {"-c", "-lc", "-command", "/c"} for arg in arguments)
            has_script = any(not arg.startswith("-") for arg in arguments)
            if not has_command and (not has_script or any(arg.casefold() in {"-i", "-s"} for arg in arguments)):
                return True
        if executable in _INTERACTIVE_INTERPRETERS:
            if not arguments or "-" in arguments or any(arg == "-i" or arg.casefold() == "--interactive" for arg in arguments):
                return True
    return False


def _shell_may_modify(command: str, path: str, cwd: str | None) -> bool:
    if _safe_research_diagnostic(command, cwd):
        return False
    if _mutating_adapter_action(command, cwd):
        return True
    target = _canonical(path, cwd).casefold().rstrip("/")
    for segment in _top_level_segments(command):
        candidates = _command_path_candidates(segment, cwd)
        touches = any(_canonical(value, cwd).casefold().rstrip("/") == target for value in candidates)
        literal = re.escape(path.replace("\\", "/").rstrip("/"))
        normalized = segment.replace("\\", "/")
        if re.search(rf"(?is)(?:open|path)\s*\(\s*['\"]?{literal}['\"]?[^)]*['\"][wax+][^'\"]*['\"]", normalized):
            return True
        if not touches:
            continue
        for destination in re.findall(r">+(?:[|!])?\s*(?:['\"]([^'\"]+)['\"]|([^\s;&|]+))", segment):
            value = destination[0] or destination[1]
            if _canonical(value, cwd).casefold().rstrip("/") == target:
                return True
        if re.search(r"(?i)\bsed\b[^;&|\n]*(?:\s-[A-Za-z]*i(?:[A-Za-z.]*)?(?:\s|$)|--in-place(?:=|\s|$))", normalized):
            return True
        try:
            tokens = _unwrap_command_tokens(shlex.split(segment, posix=True))
        except ValueError:
            return True
        if not tokens:
            continue
        executable = tokens[0].replace("\\", "/").rsplit("/", 1)[-1].casefold()
        if executable in _INTERACTIVE_SHELLS:
            command_body: str | None = None
            for index, argument in enumerate(tokens[1:]):
                lowered = argument.casefold()
                if (lowered in {"-c", "-lc", "-command", "/c"} or (
                    lowered.startswith("-") and not lowered.startswith("--") and "c" in lowered[1:]
                )) and index + 2 <= len(tokens) - 1:
                    command_body = " ".join(tokens[index + 2:])
                    break
            if command_body is not None:
                if _shell_may_modify(command_body, path, cwd):
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
            values = [token[3:] for token in tokens[1:] if token.casefold().startswith("of=")]
            if any(_canonical(value, cwd).casefold().rstrip("/") == target for value in values):
                return True
            continue
        if executable in {"perl", "perl.exe", "ruby", "ruby.exe"}:
            if any(
                token.casefold() == "--in-place"
                or (
                    token.startswith("-")
                    and not token.startswith("--")
                    and "i" in token[1:].casefold()
                )
                for token in tokens[1:]
            ):
                return True
            continue
        if executable in {"python", "python3", "node"}:
            continue
        if executable not in _READ_ONLY:
            return True
    return False


def protected_target(payload: dict[str, object]) -> str | None:
    tool_name = str(payload.get("tool_name", "")).casefold()
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

    for key in ("file_path", "path", "target_path", "notebook_path"):
        value = tool_input.get(key)
        if isinstance(value, str) and is_protected(value, cwd):
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
        return protected_target(nested_payload)
    if re.fullmatch(r"\s*cd(?:\s+[^;&|]+)?\s*", command):
        return None
    if tool_name in {"bash", "powershell", "monitor"} and _opens_unchecked_stdin_transport(command):
        return "interactive stdin command transport"
    nested_runtime = _nested_runtime_launch(command)
    if tool_name in {"bash", "powershell", "monitor"} and nested_runtime is not None:
        return f"nested {nested_runtime} runtime launch"
    if _mutating_adapter_action(command, cwd):
        return "tools/research.py adapters"
    if tool_name in {"apply_patch", "edit", "write", "multiedit", "notebookedit"}:
        for path in _patch_paths(command):
            if is_protected(path, cwd):
                return _canonical(path, cwd)
    shell_tool = tool_name in {"bash", "powershell", "monitor"}
    if shell_tool:
        for candidate in _command_path_candidates(command, cwd):
            if is_protected(candidate, cwd) or _is_protected_ancestor(candidate, cwd):
                normalized = _canonical(candidate, cwd)
                if not _shell_may_modify(command, candidate, cwd):
                    continue
                return normalized
    mentioned = _mentioned_path(command, cwd)
    if mentioned is None:
        return None
    if tool_name in {"bash", "powershell", "monitor"} and not _shell_may_modify(command, mentioned, cwd):
        return None
    return mentioned


def _self_test() -> int:
    root = _project_root(os.getcwd())
    nested = root / "runs/RUN-0001/tasks/T01"
    blocked = [
        {"tool_name": "Write", "tool_input": {"file_path": ".claude/settings.json"}},
        {"tool_name": "Write", "tool_input": {"file_path": "AGENTS.md"}},
        {"tool_name": "Write", "tool_input": {"file_path": "CLAUDE.md"}},
        {"tool_name": "Write", "tool_input": {"file_path": "tools/research.py"}},
        {"tool_name": "Write", "tool_input": {"file_path": ".mcp.json"}},
        {"tool_name": "Write", "tool_input": {"file_path": "AGENTS.override.md"}},
        {"tool_name": "Write", "tool_input": {"file_path": "CLAUDE.local.md"}},
        {"tool_name": "Write", "tool_input": {"file_path": "runs/RUN-0001/tasks/T01/AGENTS.md"}},
        {"tool_name": "Write", "tool_input": {"file_path": "research/CLAUDE.md"}},
        {"tool_name": "Write", "tool_input": {"file_path": ".CoDeX/hooks.json"}},
        {"tool_name": "Edit", "tool_input": {"path": str(root / ".codex/config.toml")}},
        {"tool_name": "Write", "cwd": str(nested), "tool_input": {"file_path": "../../../../runtime/PROFILES.md"}},
        {"tool_name": "apply_patch", "tool_input": {"command": "*** Begin Patch\n*** Update File: tools/guards/no_git.py\n*** End Patch"}},
        {"tool_name": "Bash", "tool_input": {"command": "sed -i x .codex/config.toml"}},
        {"tool_name": "PowerShell", "tool_input": {"command": "Set-Content .claude/settings.json stale"}},
        {"tool_name": "Bash", "tool_input": {"command": "python3 tools/research.py adapters --runtime codex"}},
        {"tool_name": "Bash", "tool_input": {"command": "python3 -m tools.research adapters --runtime claude"}},
        {"tool_name": "Bash", "tool_input": {"command": "python3 tools/research.py --root . adapters --runtime codex"}},
        {"tool_name": "Bash", "tool_input": {"command": "python3 -B tools/research.py adapters --runtime codex"}},
        {"tool_name": "Bash", "tool_input": {"command": "python3 -O -m tools.research adapters --runtime codex"}},
        {"tool_name": "Bash", "tool_input": {"command": "python3 -mtools.research adapters --runtime codex"}},
        {"tool_name": "Bash", "tool_input": {"command": "python3 -X dev tools/research.py adapters --runtime codex"}},
        {"tool_name": "Bash", "tool_input": {"command": "python3 -W ignore tools/research.py adapters --runtime codex"}},
        {"tool_name": "Bash", "tool_input": {"command": "claude mcp add-json x '{}' --scope project"}},
        {"tool_name": "Bash", "tool_input": {"command": "claude --dangerously-skip-permissions -p unsafe"}},
        {"tool_name": "Bash", "tool_input": {"command": "codex -c features.hooks=false exec unsafe"}},
        {"tool_name": "Bash", "tool_input": {"command": "timeout 5 python3 -m tools.research adapters --runtime codex"}},
        {"tool_name": "Bash", "tool_input": {"command": "env -S 'python3 -m tools.research adapters --runtime codex'"}},
        {"tool_name": "Bash", "tool_input": {"command": "flock -c 'python3 -m tools.research adapters --runtime codex' /tmp/l"}},
        {"tool_name": "Bash", "tool_input": {"command": "flock /tmp/l python3 -m tools.research adapters --runtime codex"}},
        {"tool_name": "Bash", "tool_input": {"command": "xargs python3 -m tools.research adapters --runtime codex"}},
        {"tool_name": "Bash", "tool_input": {"command": "eval 'python3 -m tools.research adapters --runtime codex'"}},
        {"tool_name": "Bash", "tool_input": {"command": "watch python3 -m tools.research adapters --runtime codex"}},
        {"tool_name": "PowerShell", "tool_input": {"command": "Start-Process python3 -ArgumentList -m,tools.research,adapters,--runtime,codex"}},
        {"tool_name": "Bash", "tool_input": {"command": "flock /tmp/l claude --dangerously-skip-permissions -p x"}},
        {"tool_name": "Bash", "tool_input": {"command": "xargs claude --dangerously-skip-permissions -p x"}},
        {"tool_name": "Bash", "tool_input": {"command": "watch codex exec x"}},
        {"tool_name": "Bash", "tool_input": {"command": "eval 'claude --dangerously-skip-permissions -p x'"}},
        {"tool_name": "Bash", "tool_input": {"command": "start \"title\" claude --dangerously-skip-permissions -p x"}},
        {"tool_name": "PowerShell", "tool_input": {"command": "Start-Process claude -ArgumentList --dangerously-skip-permissions,-p,x"}},
        {"tool_name": "Bash", "cwd": str(root), "tool_input": {"workdir": str(root / "runs"), "command": "rm ../.codex/hooks.json"}},
        {"tool_name": "Bash", "cwd": str(root), "tool_input": {"command": "cd runs && rm ../.codex/hooks.json"}},
        {"tool_name": "Bash", "tool_input": {"command": "rm {AGENTS,foo}.md"}},
        {"tool_name": "Bash", "tool_input": {"command": "rm AGENTS.{md,bak}"}},
        {"tool_name": "Bash", "tool_input": {"command": "find . -name AGENTS.md -delete"}},
        {"tool_name": "Bash", "tool_input": {"command": "find runs -fprint AGENTS.md"}},
        {"tool_name": "Bash", "tool_input": {"command": "sed -i.bak s/x/y/ AGENTS.md"}},
        {"tool_name": "Bash", "tool_input": {"command": "cp -l AGENTS.md runs/alias.md"}},
        {"tool_name": "Bash", "tool_input": {"command": "rm -r tools"}},
        {"tool_name": "Bash", "tool_input": {"command": "bash"}},
        {"tool_name": "Bash", "tool_input": {"command": "python3 -"}},
        {"tool_name": "PowerShell", "tool_input": {"command": "pwsh"}},
        {"tool_name": "Bash", "tool_input": {"command": "bash && printf later"}},
        {"tool_name": "Bash", "tool_input": {"command": "python3 -; printf later"}},
        {"tool_name": "Bash", "tool_input": {"command": "env -i bash"}},
        {"tool_name": "Bash", "tool_input": {"command": "/usr/bin/env bash"}},
        {"tool_name": "Bash", "tool_input": {"command": "command bash"}},
        {"tool_name": "Bash", "tool_input": {"command": "exec bash"}},
        {"tool_name": "Bash", "tool_input": {"command": "nice bash"}},
        {"tool_name": "Bash", "tool_input": {"command": "time bash"}},
        {"tool_name": "Bash", "tool_input": {"command": "sudo bash"}},
        {"tool_name": "Bash", "tool_input": {"command": "setsid bash"}},
        {"tool_name": "Bash", "tool_input": {"command": "stdbuf -oL bash"}},
        {"tool_name": "Bash", "tool_input": {"command": "env -C /tmp bash"}},
        {"tool_name": "Bash", "tool_input": {"command": "env --chdir /tmp bash"}},
        {"tool_name": "Bash", "tool_input": {"command": "dd if=/dev/null of=AGENTS.md"}},
        {"tool_name": "Bash", "tool_input": {"command": "python3 -c \"open('CLAUDE.md','w').write('x')\""}},
        {"tool_name": "Bash", "tool_input": {"command": "printf x > research/CLAUDE.md"}},
        {"tool_name": "Bash", "tool_input": {"command": "perl -pi -e s/x/y/ AGENTS.md"}},
        {"tool_name": "Bash", "tool_input": {"command": "ruby -pi -e 'gsub(/x/,\"y\")' CLAUDE.md"}},
        {"tool_name": "Bash", "tool_input": {"command": "cat /dev/null >! AGENTS.md"}},
        {"tool_name": "Bash", "tool_input": {"command": "bash -lc 'rm AGENTS.md'"}},
    ]
    allowed = [
        {"tool_name": "Bash", "tool_input": {"command": "cat runtime/PROFILES.md"}},
        {"tool_name": "Bash", "tool_input": {"command": "sed -n '1,20p' .codex/config.toml"}},
        {"tool_name": "Write", "tool_input": {"file_path": "runs/RUN-0001/tasks/T01/OUTPUT.md"}},
        {"tool_name": "Bash", "tool_input": {"command": "python3 tools/research.py check"}},
        {"tool_name": "Bash", "tool_input": {"command": "python3 tools/research.py adapters --runtime codex --check"}},
        {"tool_name": "Bash", "tool_input": {"command": "cat runtime/PROFILES.md > /tmp/profiles-copy.md"}},
        {"tool_name": "Bash", "tool_input": {"command": "bash -lc 'printf safe'"}},
        {"tool_name": "Bash", "tool_input": {"command": "python3 tools/example.py"}},
        {"tool_name": "PowerShell", "tool_input": {"command": "Get-Content runtime/PROFILES.md"}},
        {"tool_name": "Monitor", "tool_input": {"command": "cat runtime/PROFILES.md"}},
        {"tool_name": "Bash", "tool_input": {"command": "cp runtime/PROFILES.md runs/profiles-copy.md"}},
        {"tool_name": "Bash", "tool_input": {"command": "python3 -c \"a=1; print(a)\""}},
        {"tool_name": "Bash", "tool_input": {"command": "bash -lc \"echo a; echo b\""}},
        {"tool_name": "Bash", "tool_input": {"command": "bash -lc 'cat AGENTS.md'"}},
        {"tool_name": "Bash", "tool_input": {"command": "echo AGENTS.md"}},
        {"tool_name": "Bash", "tool_input": {"command": "printf '%s\\n' AGENTS.md"}},
        {"tool_name": "Bash", "tool_input": {"command": "sha256sum AGENTS.md"}},
        {"tool_name": "Bash", "tool_input": {"command": "echo 'python3 tools/research.py adapters --runtime codex'"}},
        {"tool_name": "Bash", "tool_input": {"command": "python3 -c \"print('python3 tools/research.py adapters --runtime codex')\""}},
        {"tool_name": "Bash", "tool_input": {"command": "python3 tools/research.py --root . adapters --runtime codex --check"}},
        {"tool_name": "Bash", "tool_input": {"command": "cd runtime"}},
        {"tool_name": "Bash", "tool_input": {"command": "command cat AGENTS.md"}},
        {"tool_name": "Bash", "tool_input": {"command": "env LC_ALL=C rg Runtime AGENTS.md"}},
        {"tool_name": "Bash", "tool_input": {"command": "stdbuf -oL cat AGENTS.md"}},
        {"tool_name": "Bash", "tool_input": {"command": "jq . .codex/hooks.json"}},
        {"tool_name": "Bash", "tool_input": {"command": "ln -s AGENTS.md runs/agents-link.md"}},
        {"tool_name": "Bash", "tool_input": {"command": "python3 -I -B tools/research.py check"}},
        {"tool_name": "Bash", "tool_input": {"command": "codex --version"}},
        {"tool_name": "Bash", "tool_input": {"command": "claude --help"}},
        {"tool_name": "Bash", "tool_input": {"command": "echo 'codex exec unsafe'"}},
    ]
    failures = [case for case in blocked if protected_target(case) is None]
    failures.extend(case for case in allowed if protected_target(case) is not None)
    if failures:
        print(f"protect_runtime.py self-test failures: {failures!r}", file=sys.stderr)
        return 1
    print(f"protect_runtime.py self-test passed ({len(blocked) + len(allowed)} cases; {ADAPTER_SCHEMA})")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hook", choices=("auto", "codex", "claude"), default="auto")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args(argv)
    if args.self_test:
        return _self_test()
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, OSError) as error:
        print(f"runtime safety guard could not parse hook payload: {error}", file=sys.stderr)
        return BLOCK_EXIT
    if not isinstance(payload, dict):
        print("runtime safety guard expected a JSON object", file=sys.stderr)
        return BLOCK_EXIT
    target = protected_target(payload)
    if target is None:
        return 0
    print(
        f"Blocked agent-side mutation of runtime safety configuration: {target}. "
        "Use a human or trusted external process to change adapters, profiles, or guards.",
        file=sys.stderr,
    )
    return BLOCK_EXIT


if __name__ == "__main__":
    raise SystemExit(main())
