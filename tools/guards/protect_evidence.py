#!/usr/bin/env python3
"""Protect write-once research evidence and immutable milestone reports.

The hook permits creation of a new input or execution path, then rejects
ordinary attempts to overwrite, patch, rename, truncate, or delete it. It also
rejects edits to published milestone reports. This is defense in
depth, not an OS boundary: code can conceal indirect writes, so high-assurance
runs should additionally use read-only mounts or filesystem permissions.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
from pathlib import Path, PurePosixPath
import re
import shlex
import sys
import tempfile
from collections.abc import Sequence


ADAPTER_SCHEMA = "research-agent-adapter-v1"
BLOCK_EXIT = 2
_PATCH_TARGET = re.compile(
    r"^\*\*\* (Add|Update|Delete) File:\s*(.+?)\s*$", re.MULTILINE
)
_PATCH_MOVE = re.compile(r"^\*\*\* Move to:\s*(.+?)\s*$", re.MULTILINE)
_EXPLICIT_PATH = re.compile(
    r"(?P<path>(?:(?:\.\./)+|\./|(?:[A-Za-z]:)?/[^\s;&|<>\"']*?/)?"
    r"(?:experiments/EXP-\d{4,}/(?:inputs|executions)(?:/[^\s;&|<>\"']*)?"
    r"|reports/RPT-\d{4,}\.md))",
    re.IGNORECASE,
)
_TREE_DESTRUCTIVE = re.compile(
    r"(?i)(?:^|[\s'\";&|/\\])"
    r"(?:move-item|mv|remove-item|rename-item|rm|rmdir|unlink)\b"
)


def _looks_like_project_root(path: Path) -> bool:
    return (path / "ARTIFACT_INDEX.md").exists() and (path / "AGENTS.md").exists()


def _project_root(cwd: str, target: Path | None = None) -> Path:
    configured = os.environ.get("CLAUDE_PROJECT_DIR") or os.environ.get("RESEARCH_PROJECT_ROOT")
    starts = [Path(configured)] if configured else []
    starts.append(Path(cwd))
    if target is not None:
        starts.append(target.parent if target.suffix else target)
    for start in starts:
        resolved = start.resolve(strict=False)
        for candidate in (resolved, *resolved.parents):
            if _looks_like_project_root(candidate):
                return candidate
    return Path(cwd).resolve(strict=False)


def _normalize(path: str, cwd: str) -> tuple[str, Path]:
    raw = path.strip().strip("'\"").replace("\\", "/")
    candidate = Path(raw).expanduser()
    absolute = candidate if candidate.is_absolute() else Path(cwd) / candidate
    resolved = absolute.resolve(strict=False)
    root = _project_root(cwd, resolved)
    try:
        relative = resolved.relative_to(root)
        normalized = relative.as_posix()
    except ValueError:
        normalized = PurePosixPath(raw).as_posix().removeprefix("./")
    return normalized, resolved


def _append_only_area(normalized: str) -> bool:
    parts = PurePosixPath(normalized).parts
    return (
        len(parts) >= 3
        and parts[0].casefold() == "experiments"
        and re.fullmatch(r"EXP-\d{4,}", parts[1], re.IGNORECASE) is not None
        and parts[2].casefold() in {"inputs", "executions"}
    )


def _published_report(normalized: str, absolute: Path) -> bool:
    if re.fullmatch(r"reports/RPT-\d{4,}\.md", normalized, re.IGNORECASE) is None:
        return False
    try:
        text = absolute.read_text(encoding="utf-8")
    except OSError:
        return False
    preamble = text.split("\n## ", 1)[0]
    match = re.search(r"(?m)^- \*\*Status:\*\*\s*(\S.*?)\s*$", preamble)
    return bool(match and match.group(1).casefold() == "published")


def _completed_execution(normalized: str, cwd: str, absolute: Path) -> bool:
    """Recognize a visible immutable manifest as a directory-wide freeze."""

    parts = PurePosixPath(normalized).parts
    if (
        len(parts) < 4
        or parts[0].casefold() != "experiments"
        or re.fullmatch(r"EXP-\d{4,}", parts[1], re.IGNORECASE) is None
        or parts[2].casefold() != "executions"
        or re.fullmatch(rf"{re.escape(parts[1])}-E\d{{3,}}", parts[3], re.IGNORECASE) is None
    ):
        return False
    marker = (
        _project_root(cwd, absolute)
        / "experiments" / parts[1] / "executions" / parts[3] / "COMPLETED.md"
    )
    try:
        text = marker.read_text(encoding="utf-8")
    except OSError:
        return False
    heading = re.search(r"(?m)^#\s+(EXP-\d{4,}-E\d{3,})\b", text)
    labels = {
        key.casefold(): value.strip()
        for key, value in re.findall(r"(?m)^- \*\*([^*]+):\*\*\s*(.*?)\s*$", text)
    }
    execution_id = parts[3].casefold()
    if heading is None or heading.group(1).casefold() != execution_id:
        return False
    if labels.get("execution id", "").casefold() != execution_id:
        return False
    required = ("completed", "command/config", "inputs", "outputs", "output digest", "result")
    return all(
        labels.get(key, "").casefold() not in {"", "pending", "[pending]", "not recorded"}
        for key in required
    )


def _write_once_target(path: str, cwd: str) -> str | None:
    normalized, absolute = _normalize(path, cwd)
    if _completed_execution(normalized, cwd, absolute):
        return normalized
    if absolute.name.casefold() == "completed.md" and _append_only_area(normalized):
        # A partially written commit marker must remain repairable.  Once its
        # minimal completion contract is valid, the branch above freezes it
        # and the entire execution directory.
        return None
    if _append_only_area(normalized) and os.path.lexists(absolute) and not absolute.is_dir():
        return normalized
    if _published_report(normalized, absolute):
        return normalized
    return None


def _repairable_completion_marker(path: str, cwd: str) -> bool:
    normalized, absolute = _normalize(path, cwd)
    return (
        absolute.name.casefold() == "completed.md"
        and _append_only_area(normalized)
        and not _completed_execution(normalized, cwd, absolute)
    )


def _future_immutable_anchor(path: str, cwd: str) -> str | None:
    """Return lifecycle files that must never acquire a mutable hard-link alias."""

    normalized, _ = _normalize(path, cwd)
    if re.fullmatch(r"reports/RPT-\d{4,}\.md", normalized, re.IGNORECASE):
        return normalized
    if re.fullmatch(
        r"experiments/(EXP-\d{4,})/executions/\1-E\d{3,}/COMPLETED\.md",
        normalized,
        re.IGNORECASE,
    ):
        return normalized
    return None


def _protected_descendant(path: str, cwd: str) -> str | None:
    """Protect scoped parent operations that would remove durable evidence."""

    normalized, absolute = _normalize(path, cwd)
    root = _project_root(cwd, absolute)
    try:
        absolute.relative_to(root)
    except ValueError:
        return None

    protected: list[Path] = []
    for pattern in ("experiments/EXP-*/inputs", "experiments/EXP-*/executions"):
        for base in root.glob(pattern):
            if not base.exists():
                continue
            protected.extend(item for item in base.rglob("*") if item.is_file() or item.is_symlink())
    reports = root / "reports"
    if reports.exists():
        for report in reports.glob("RPT-*.md"):
            report_normalized = report.relative_to(root).as_posix()
            if _published_report(report_normalized, report):
                protected.append(report)
    for durable in protected:
        # Preserve the lexical in-project location as well as the resolved
        # target.  Resolving a symlink must not make a parent operation such
        # as ``rm -r experiments/EXP-0001`` appear unrelated to the evidence
        # entry stored beneath that parent.
        lexical = Path(os.path.abspath(durable))
        resolved = durable.resolve(strict=False)
        for candidate in (lexical, resolved):
            if absolute == candidate or absolute in candidate.parents:
                return normalized
    return None


def _tar_extracts(arguments: Sequence[str]) -> bool:
    for index, value in enumerate(arguments):
        lowered = value.casefold()
        if lowered in {"--extract", "--get"}:
            return True
        if value.startswith("-") and not value.startswith("--") and "x" in lowered[1:]:
            return True
        if index == 0 and not value.startswith("-") and re.fullmatch(r"[a-z]+", lowered) and "x" in lowered:
            return True
    return False


def _tree_mutation_command(command: str) -> bool:
    for executable, arguments in _effective_commands(command):
        if executable in {"del", "erase", "move-item", "mv", "remove-item", "rename-item", "rm", "rmdir", "unlink"}:
            return True
        if executable == "find" and any(
            argument.casefold() in {"-delete", "-exec", "-execdir", "-ok", "-okdir"}
            for argument in arguments
        ):
            return True
        if executable in {"rsync", "rsync.exe"} and any(
            value in arguments for value in {"--delete", "--remove-source-files"}
        ):
            return True
        if executable in {"tar", "unzip"} and (
            executable == "unzip"
            or _tar_extracts(arguments)
            or "--remove-files" in arguments
        ):
            return True
        if executable == "expand-archive":
            return True
    return False


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
        break
    return tokens


def _effective_commands(command: str, depth: int = 0) -> list[tuple[str, list[str]]]:
    if depth > 3:
        return []
    commands: list[tuple[str, list[str]]] = []
    shells = {"bash", "cmd", "cmd.exe", "fish", "powershell", "powershell.exe", "pwsh", "pwsh.exe", "sh", "zsh"}
    for segment in _top_level_segments(command):
        try:
            tokens = _unwrap_command_tokens(shlex.split(segment.replace("\\", "/"), posix=True))
        except ValueError:
            continue
        if not tokens:
            continue
        executable = tokens[0].replace("\\", "/").rsplit("/", 1)[-1].casefold()
        arguments = tokens[1:]
        if executable in shells:
            for index, argument in enumerate(arguments):
                lowered = argument.casefold()
                if lowered in {"-c", "-lc", "-command", "/c"} or (
                    lowered.startswith("-") and not lowered.startswith("--") and "c" in lowered[1:]
                ):
                    if index + 1 < len(arguments):
                        commands.extend(_effective_commands(" ".join(arguments[index + 1:]), depth + 1))
                    break
            continue
        if executable in {"busybox", "busybox.exe"} and arguments:
            executable = arguments[0].replace("\\", "/").rsplit("/", 1)[-1].casefold()
            arguments = arguments[1:]
        commands.append((executable, arguments))
    return commands


def _brace_variants(value: str) -> list[str]:
    match = re.search(r"\{([^{}]+)\}", value)
    if match is None:
        return [value]
    choices = match.group(1).split(",")
    if len(choices) < 2 or len(choices) > 16:
        return [value]
    return [value[:match.start()] + choice + value[match.end():] for choice in choices]


def _leading_cd(command: str, cwd: str) -> tuple[str, str] | None:
    match = re.match(
        r"^\s*cd\s+(?P<directory>'[^']*'|\"[^\"]*\"|[^\s;&|]+)\s*(?:&&|;)\s*(?P<rest>.+)$",
        command,
        re.DOTALL,
    )
    if match is None:
        return None
    directory = Path(match.group("directory").strip("'\"")).expanduser()
    if not directory.is_absolute():
        directory = Path(cwd) / directory
    return str(directory.resolve(strict=False)), match.group("rest")


def _command_path_candidates(command: str, cwd: str, depth: int = 0) -> list[str]:
    candidates: list[str] = []
    try:
        tokens = shlex.split(command, posix=True)
    except ValueError:
        tokens = re.split(r"\s+", command)
    for token in tokens:
        raw = token.strip("'\"`()[],:;|<>")
        for candidate in _brace_variants(raw):
            candidate = candidate.strip("{}")
            if not candidate:
                continue
            if candidate.casefold().startswith("of="):
                candidate = candidate[3:].strip("'\"")
            if any(character in candidate for character in "*?["):
                path = Path(candidate).expanduser()
                pattern = str(path if path.is_absolute() else Path(cwd) / path)
                matches = glob.glob(pattern)
                candidates.extend(matches or [candidate])
            else:
                candidates.append(candidate)
    candidates.extend(
        match.group(0).strip()
        for match in re.finditer(
            r"(?i)(?:[A-Za-z]:)?[A-Za-z0-9_./\\ -]+\.(?:bib|csv|json|md|tex|toml|yaml|yml)",
            command,
        )
        if match.group(0).strip()
    )
    candidates.extend(
        match.group(1)
        for match in re.finditer(r"(?is)(?:open|path)\s*\(\s*['\"]([^'\"]+)['\"]", command)
    )
    candidates.extend(match.group("path") for match in _EXPLICIT_PATH.finditer(command.replace("\\", "/")))
    if depth < 2:
        for token in tokens:
            if any(character.isspace() for character in token):
                candidates.extend(_command_path_candidates(token, cwd, depth + 1))
    return candidates


def _command_mutates_path(command: str, path_text: str, cwd: str) -> bool:
    normalized = command.replace("\\", "/")
    escaped = re.escape(path_text.replace("\\", "/").strip("'\""))
    target = _normalize(path_text, cwd)[0].casefold().rstrip("/")

    def same(value: str) -> bool:
        return _normalize(value, cwd)[0].casefold().rstrip("/") == target

    for executable, arguments in _effective_commands(command):
        ordinary_arguments = [value for value in arguments if not value.startswith("-")]
        any_target = any(same(value) for value in ordinary_arguments)
        if executable in {
            "add-content", "chmod", "chown", "clear-content", "del", "erase",
            "move", "move-item", "mv", "out-file", "remove-item", "rename-item",
            "rm", "rmdir", "set-content", "tee", "tee-object", "touch", "truncate",
            "unlink",
        } and any_target:
            return True
        if executable.startswith("export-") and any_target:
            return True
        if executable == "sed" and any_target and any(
            value.casefold().startswith("--in-place")
            or (value.startswith("-") and not value.startswith("--") and "i" in value[1:])
            for value in arguments
        ):
            return True
        if executable in {"perl", "perl.exe", "ruby", "ruby.exe"} and any_target and any(
            value.casefold() == "--in-place"
            or (value.startswith("-") and not value.startswith("--") and "i" in value[1:].casefold())
            for value in arguments
        ):
            return True
        if executable in {"cp", "install", "copy", "copy-item", "rsync", "rsync.exe"}:
            if any(same(destination) for destination in _effective_destinations(command, cwd)):
                return True
        if executable == "dd" and any(
            value.casefold().startswith("of=") and same(value[3:]) for value in arguments
        ):
            return True
        if executable == "find":
            for index, value in enumerate(arguments[:-1]):
                if value.casefold() in {"-fprint", "-fprint0", "-fprintf", "-fls"} and same(arguments[index + 1]):
                    return True
            if any(value.casefold() in {"-delete", "-exec", "-execdir", "-ok", "-okdir"} for value in arguments) and any_target:
                return True
        if executable == "tar" and _tar_extracts(arguments):
            for index, value in enumerate(arguments[:-1]):
                if value in {"-C", "--directory"} and same(arguments[index + 1]):
                    return True
        if executable in {"link", "link.exe"} and any_target:
            return True
        if executable == "ln" and any_target and not any(
            value.casefold() in {"-s", "--symbolic"} for value in arguments
        ):
            return True
        if executable == "sort" and any_target and any(
            value == "-o" or value.casefold().startswith("--output=") for value in arguments
        ):
            return True
        if executable == "compress-archive":
            for index, value in enumerate(arguments[:-1]):
                if value.casefold() in {"-destinationpath", "-destination"} and same(arguments[index + 1]):
                    return True
            continue
        safe_when_source_only = {
            "cat", "cmp", "copy", "copy-item", "cp", "diff", "echo", "file", "find", "get-content",
            "get-filehash", "get-item", "grep", "head", "install", "jq", "less", "ln", "ls", "md5sum",
            "more", "node", "perl", "printf", "python", "python3", "readlink",
            "rg", "rsync", "rsync.exe", "ruby", "sed", "sha256sum", "shasum",
            "sort", "stat", "tail", "tar", "test-path", "wc",
        }
        if any_target and executable not in safe_when_source_only:
            # Existing evidence is fail-closed for an unclassified executable.
            # Pure readers and source-only copy operations are enumerated above;
            # arbitrary-code interpreters remain the documented OS-boundary case.
            return True
    if re.search(rf">+(?:[|!])?\s*['\"]?{escaped}(?:['\"\s;&|]|$)", normalized):
        return True
    if re.search(
        rf"(?is)(?:open|path)\s*\(\s*['\"]{escaped}['\"][^)]*['\"][wax+][^'\"]*['\"]",
        normalized,
    ) or re.search(rf"(?is)['\"]{escaped}['\"][^\n;]{{0,80}}\.write_(?:text|bytes)\s*\(", normalized):
        return True
    return False


def _effective_destinations(command: str, cwd: str) -> list[str]:
    destinations: list[str] = []
    for executable, arguments in _effective_commands(command):
        if executable == "expand-archive":
            for index, value in enumerate(arguments[:-1]):
                if value.casefold() in {"-destinationpath", "-destination"}:
                    destinations.append(arguments[index + 1])
            continue
        if executable in {"tar", "unzip"}:
            for index, value in enumerate(arguments):
                lowered = value.casefold()
                if (
                    value == "-C"
                    or lowered == "--directory"
                    or (executable == "unzip" and lowered == "-d")
                ) and index + 1 < len(arguments):
                    destinations.append(arguments[index + 1])
                elif lowered.startswith("--directory="):
                    destinations.append(value.split("=", 1)[1])
                elif lowered.startswith("-c") and len(value) > 2:
                    destinations.append(value[2:])
                elif executable == "unzip" and lowered.startswith("-d") and len(value) > 2:
                    destinations.append(value[2:])
            continue
        if executable in {"copy-item", "move-item"}:
            named: dict[str, str] = {}
            for index, value in enumerate(arguments[:-1]):
                if value.casefold() in {"-path", "-literalpath", "-destination"}:
                    named[value.casefold()] = arguments[index + 1]
            source = named.get("-path") or named.get("-literalpath")
            destination = named.get("-destination")
            if source is not None and destination is not None:
                _, absolute_destination = _normalize(destination, cwd)
                if absolute_destination.is_dir():
                    destination = str(absolute_destination / Path(source.rstrip("/\\")).name)
                destinations.append(destination)
                continue
        if executable not in {"cp", "install", "copy", "copy-item", "move", "move-item", "mv", "rsync", "rsync.exe"}:
            continue
        target_directory: str | None = None
        skipped: set[int] = set()
        for index, value in enumerate(arguments):
            lowered = value.casefold()
            if lowered in {"-t", "--target-directory"} and index + 1 < len(arguments):
                target_directory = arguments[index + 1]
                skipped.update({index, index + 1})
            elif lowered.startswith("--target-directory="):
                target_directory = value.split("=", 1)[1]
                skipped.add(index)
        operands = [
            value for index, value in enumerate(arguments)
            if index not in skipped and not value.startswith("-")
        ]
        if target_directory is not None:
            _, absolute_directory = _normalize(target_directory, cwd)
            destinations.extend(
                str(absolute_directory / Path(source.rstrip("/\\")).name)
                for source in operands
            )
            continue
        if len(operands) < 2:
            continue
        source, destination = operands[-2], operands[-1]
        _, absolute_destination = _normalize(destination, cwd)
        if absolute_destination.is_dir():
            destination = str(absolute_destination / Path(source.rstrip("/\\")).name)
        destinations.append(destination)
    return destinations


def _tree_merge_destinations(command: str, cwd: str) -> list[str]:
    """Return existing directory destinations for ambiguous recursive/merge copies."""

    destinations: list[str] = []
    for executable, arguments in _effective_commands(command):
        if executable not in {"cp", "copy", "copy-item", "rsync", "rsync.exe"}:
            continue
        source_values: list[str] = []
        destination: str | None = None
        if executable == "copy-item":
            named: dict[str, str] = {}
            for index, value in enumerate(arguments[:-1]):
                if value.casefold() in {"-path", "-literalpath", "-destination"}:
                    named[value.casefold()] = arguments[index + 1]
            source = named.get("-path") or named.get("-literalpath")
            destination = named.get("-destination")
            source_values = [source] if source is not None else []
        else:
            skipped: set[int] = set()
            target_directory: str | None = None
            for index, value in enumerate(arguments):
                lowered = value.casefold()
                if lowered in {"-t", "--target-directory"} and index + 1 < len(arguments):
                    target_directory = arguments[index + 1]
                    skipped.update({index, index + 1})
                elif lowered.startswith("--target-directory="):
                    target_directory = value.split("=", 1)[1]
                    skipped.add(index)
            operands = [
                value for index, value in enumerate(arguments)
                if index not in skipped and not value.startswith("-")
            ]
            if target_directory is not None:
                destination = target_directory
                source_values = operands
            elif len(operands) >= 2:
                source_values, destination = operands[:-1], operands[-1]
        if destination is None or not source_values:
            continue
        _, absolute_destination = _normalize(destination, cwd)
        if not absolute_destination.is_dir():
            continue
        recursive_flag = any(
            value.casefold() in {"-a", "-r", "--archive", "--recursive", "-recurse"}
            or (
                executable != "copy-item"
                and
                value.startswith("-")
                and not value.startswith("--")
                and any(flag in value[1:].casefold() for flag in ("a", "r"))
            )
            for value in arguments
        )
        ambiguous_source = any(
            value.rstrip().endswith(("/", "/."))
            or any(character in value for character in "*?[")
            or _normalize(value, cwd)[1].is_dir()
            for value in source_values
        )
        if recursive_flag or ambiguous_source:
            destinations.append(destination)
    return destinations


def _link_destination(command: str, cwd: str) -> str | None:
    for executable, arguments in _effective_commands(command):
        sources: list[str] = []
        destinations: list[str] = []

        def operands_and_target_directory() -> tuple[list[str], str | None]:
            target_directory: str | None = None
            skipped: set[int] = set()
            for index, value in enumerate(arguments):
                lowered = value.casefold()
                if lowered in {"-t", "--target-directory"} and index + 1 < len(arguments):
                    target_directory = arguments[index + 1]
                    skipped.update({index, index + 1})
                elif lowered.startswith("--target-directory="):
                    target_directory = value.split("=", 1)[1]
                    skipped.add(index)
            operands = [
                value for index, value in enumerate(arguments)
                if index not in skipped and not value.startswith("-")
            ]
            return operands, target_directory

        if executable == "ln":
            symbolic = any(
                value.casefold().startswith("--symbolic")
                or (
                    value.startswith("-")
                    and not value.startswith("--")
                    and "s" in value[1:].casefold()
                )
                for value in arguments
            )
            if symbolic:
                continue
            operands, target_directory = operands_and_target_directory()
            if target_directory is not None:
                sources = operands
                _, absolute_directory = _normalize(target_directory, cwd)
                destinations = [
                    str(absolute_directory / Path(source.rstrip("/\\")).name)
                    for source in sources
                ]
            elif len(operands) >= 2:
                sources, destinations = operands[:-1], [operands[-1]]
        elif executable in {"link", "link.exe"}:
            operands = [value for value in arguments if not value.startswith("-")]
            if len(operands) >= 2:
                sources, destinations = operands[:-1], [operands[-1]]
        elif executable in {"cp", "copy-item"}:
            link_mode = any(
                value.casefold().startswith("--link")
                or (
                    value.startswith("-")
                    and not value.startswith("--")
                    and "l" in value[1:].casefold()
                )
                for value in arguments
            )
            if not link_mode:
                continue
            operands, target_directory = operands_and_target_directory()
            if target_directory is not None:
                sources = operands
                _, absolute_directory = _normalize(target_directory, cwd)
                destinations = [
                    str(absolute_directory / Path(source.rstrip("/\\")).name)
                    for source in sources
                ]
            elif len(operands) >= 2:
                sources, destinations = operands[:-1], [operands[-1]]
        elif executable in {"new-item", "ni"} and any(
            "hardlink" in value.casefold() for value in arguments
        ):
            named: dict[str, str] = {}
            for index, value in enumerate(arguments[:-1]):
                if value.casefold() in {"-path", "-literalpath", "-target", "-value"}:
                    named[value.casefold()] = arguments[index + 1]
            destination = named.get("-path") or named.get("-literalpath")
            source = named.get("-target") or named.get("-value")
            sources = [source] if source is not None else []
            destinations = [destination] if destination is not None else []
        elif executable == "mklink" and any(value.casefold() == "/h" for value in arguments):
            operands = [value for value in arguments if not value.startswith("/")][-2:]
            if len(operands) == 2:
                destinations, sources = [operands[0]], [operands[1]]
        elif executable in {"fsutil", "fsutil.exe"} and len(arguments) >= 4 and [
            value.casefold() for value in arguments[:2]
        ] == ["hardlink", "create"]:
            destinations, sources = [arguments[2]], [arguments[3]]
        if not sources or not destinations:
            continue
        for value in [*sources, *destinations]:
            anchor = _future_immutable_anchor(value, cwd)
            if anchor is not None:
                return anchor
            target = _write_once_target(value, cwd)
            if target is not None:
                return target
        for destination in destinations:
            normalized, _ = _normalize(destination, cwd)
            if _append_only_area(normalized):
                return normalized
    return None


def protected_target(payload: dict[str, object]) -> str | None:
    tool_name = str(payload.get("tool_name", "")).casefold()
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        return None
    cwd_value = payload.get("cwd")
    cwd = (
        cwd_value if isinstance(cwd_value, str) and cwd_value
        else os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    )
    workdir = tool_input.get("workdir")
    if isinstance(workdir, str) and workdir:
        workdir_path = Path(workdir).expanduser()
        if not workdir_path.is_absolute():
            workdir_path = Path(cwd) / workdir_path
        cwd = str(workdir_path.resolve(strict=False))

    if tool_name in {"edit", "write", "multiedit", "notebookedit"}:
        for key in ("file_path", "path", "target_path", "notebook_path"):
            value = tool_input.get(key)
            if isinstance(value, str):
                if _repairable_completion_marker(value, cwd):
                    continue
                target = _write_once_target(value, cwd)
                if target is not None:
                    return target
                target = _protected_descendant(value, cwd)
                if target is not None:
                    return target

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
    if tool_name == "apply_patch":
        for path in _PATCH_MOVE.findall(command):
            if _repairable_completion_marker(path, cwd):
                continue
            target = _write_once_target(path, cwd)
            if target is not None:
                return target
            target = _protected_descendant(path, cwd)
            if target is not None:
                return target
        for action, path in _PATCH_TARGET.findall(command):
            if _repairable_completion_marker(path, cwd):
                continue
            normalized, absolute = _normalize(path, cwd)
            if _published_report(normalized, absolute):
                return normalized
            if _completed_execution(normalized, cwd, absolute):
                return normalized
            if action != "Add":
                target = _protected_descendant(path, cwd)
                if target is not None:
                    return target
            if _append_only_area(normalized) and (
                action != "Add" or os.path.lexists(absolute)
            ):
                return normalized
        return None
    if tool_name not in {"bash", "powershell", "monitor"}:
        return None
    linked = _link_destination(command, cwd)
    if linked is not None:
        return linked
    for destination in _tree_merge_destinations(command, cwd):
        target = _protected_descendant(destination, cwd)
        if target is not None:
            return target
    for destination in _effective_destinations(command, cwd):
        target = _write_once_target(destination, cwd)
        if target is not None:
            return target
        if _tree_mutation_command(command):
            target = _protected_descendant(destination, cwd)
            if target is not None:
                return target
    candidates = _command_path_candidates(command, cwd)
    if _tree_mutation_command(command):
        for candidate in candidates:
            target = _protected_descendant(candidate, cwd)
            if target is not None:
                return target
    for candidate in candidates:
        target = _write_once_target(candidate, cwd)
        if target is not None and _command_mutates_path(command, candidate, cwd):
            return target
        candidate_normalized, _ = _normalize(candidate, cwd)
        if not _append_only_area(candidate_normalized):
            target = _protected_descendant(candidate, cwd)
            if target is not None and _command_mutates_path(command, candidate, cwd):
                return target
    for match in _EXPLICIT_PATH.finditer(command.replace("\\", "/")):
        explicit = match.group("path").rstrip(".,:)")
        target = _write_once_target(explicit, cwd)
        if target is not None and _command_mutates_path(command, explicit, cwd):
            return target
    return None


def _self_test() -> int:
    failures: list[str] = []
    with tempfile.TemporaryDirectory(prefix="research-evidence-guard-") as temporary:
        root = Path(temporary)
        (root / "ARTIFACT_INDEX.md").write_text("# index\n", encoding="utf-8")
        (root / "AGENTS.md").write_text("# instructions\n", encoding="utf-8")
        existing_input = root / "experiments/EXP-0001/inputs/source.csv"
        spaced_input = root / "experiments/EXP-0001/inputs/source data.csv"
        dashed_input = root / "experiments/EXP-0001/inputs/-raw.csv"
        extensionless_input = root / "experiments/EXP-0001/inputs/blob"
        existing_output = root / "experiments/EXP-0001/executions/EXP-0001-E001/result.json"
        published = root / "reports/RPT-0001.md"
        draft = root / "reports/RPT-0002.md"
        for path in (existing_input, spaced_input, dashed_input, extensionless_input, existing_output, published, draft):
            path.parent.mkdir(parents=True, exist_ok=True)
        existing_input.write_text("source", encoding="utf-8")
        spaced_input.write_text("source", encoding="utf-8")
        dashed_input.write_text("source", encoding="utf-8")
        extensionless_input.write_text("source", encoding="utf-8")
        existing_output.write_text("result", encoding="utf-8")
        published.write_text("# RPT-0001 — x\n\n- **Status:** published\n", encoding="utf-8")
        draft.write_text("# RPT-0002 — x\n\n- **Status:** draft\n", encoding="utf-8")
        experiment_readme = root / "experiments/EXP-0001/README.md"
        experiment_readme.write_text(
            "# EXP-0001 — x\n\n## Executions\n\n"
            "| Execution ID | Date | Command/config | Inputs | Seed | Outputs | Output digest | Result | Notes |\n"
            "|---|---|---|---|---|---|---|---|---|\n"
            "| EXP-0001-E001 | 2026-08-17 | run | inputs/a | none | executions/EXP-0001-E001 | abc | success | none |\n",
            encoding="utf-8",
        )
        completion_marker = existing_output.parent / "COMPLETED.md"
        completion_marker.write_text(
            "# EXP-0001-E001 — Completed execution\n\n"
            "- **Execution ID:** EXP-0001-E001\n"
            "- **Completed:** 2026-08-17\n"
            "- **Command/config:** run\n"
            "- **Inputs:** inputs/a\n"
            "- **Outputs:** result.json\n"
            "- **Output digest:** abc\n"
            "- **Result:** success\n",
            encoding="utf-8",
        )
        symlink_source = root / "runs/symlink-source.csv"
        symlink_source.parent.mkdir(parents=True, exist_ok=True)
        symlink_source.write_text("source", encoding="utf-8")
        symlink_input = root / "experiments/EXP-0002/inputs/link.csv"
        symlink_input.parent.mkdir(parents=True, exist_ok=True)
        symlink_input.symlink_to(symlink_source)
        incomplete_marker = root / "experiments/EXP-0003/executions/EXP-0003-E001/COMPLETED.md"
        incomplete_marker.parent.mkdir(parents=True, exist_ok=True)
        incomplete_marker.write_text(
            "# EXP-0003-E001 — Completed execution\n\n- **Execution ID:** EXP-0003-E001\n- **Completed:** pending\n",
            encoding="utf-8",
        )
        task_cwd = root / "runs/RUN-0001/tasks/T01"
        task_cwd.mkdir(parents=True)

        blocked = (
            {"tool_name": "Write", "cwd": temporary, "tool_input": {"file_path": "experiments/EXP-0001/inputs/source.csv"}},
            {"tool_name": "Edit", "cwd": temporary, "tool_input": {"path": "experiments/EXP-0001/executions/EXP-0001-E001/result.json"}},
            {"tool_name": "Bash", "cwd": temporary, "tool_input": {"command": "rm experiments/EXP-0001/inputs/source.csv"}},
            {"tool_name": "Write", "cwd": str(task_cwd), "tool_input": {"file_path": "../../../../experiments/EXP-0001/inputs/source.csv"}},
            {"tool_name": "Edit", "cwd": str(task_cwd), "tool_input": {"file_path": str(existing_output)}},
            {"tool_name": "Bash", "cwd": str(task_cwd), "tool_input": {"command": "rm ../../../../experiments/EXP-0001/inputs/source.csv"}},
            {"tool_name": "apply_patch", "cwd": temporary, "tool_input": {"command": "*** Begin Patch\n*** Update File: reports/RPT-0001.md\n*** End Patch"}},
            {"tool_name": "apply_patch", "cwd": temporary, "tool_input": {"command": "*** Begin Patch\n*** Update File: reports/RPT-0002.md\n*** Move to: reports/RPT-0001.md\n*** End Patch"}},
            {"tool_name": "apply_patch", "cwd": temporary, "tool_input": {"command": "*** Begin Patch\n*** Update File: runs/draft.md\n*** Move to: experiments/EXP-0001/inputs/source.csv\n*** End Patch"}},
            {"tool_name": "Write", "cwd": temporary, "tool_input": {"file_path": "experiments/EXP-0001/executions/EXP-0001-E001/late.json"}},
            {"tool_name": "Edit", "cwd": temporary, "tool_input": {"file_path": "experiments/EXP-0001/executions/EXP-0001-E001/COMPLETED.md"}},
            {"tool_name": "Bash", "cwd": temporary, "tool_input": {"command": "rm -r experiments/EXP-0001"}},
            {"tool_name": "Bash", "cwd": temporary, "tool_input": {"command": "mv experiments/EXP-0001 experiments/EXP-0001-old"}},
            {"tool_name": "Bash", "cwd": temporary, "tool_input": {"command": "rm -r reports"}},
            {"tool_name": "Bash", "cwd": str(existing_input.parent), "tool_input": {"command": "rm source.csv"}},
            {"tool_name": "Bash", "cwd": str(existing_output.parent), "tool_input": {"command": "printf x > result.json"}},
            {"tool_name": "Bash", "cwd": str(published.parent), "tool_input": {"command": "rm RPT-0001.md"}},
            {"tool_name": "Bash", "cwd": temporary, "tool_input": {"command": "rm reports/*.md"}},
            {"tool_name": "Bash", "cwd": temporary, "tool_input": {"command": "python3 -c \"open('experiments/EXP-0001/inputs/source.csv','w').write('x')\""}},
            {"tool_name": "Bash", "cwd": str(existing_input.parent), "tool_input": {"command": "dd if=/dev/null of=source.csv"}},
            {"tool_name": "Bash", "cwd": temporary, "tool_input": {"command": "rm \"experiments/EXP-0001/inputs/source data.csv\""}},
            {"tool_name": "Bash", "cwd": temporary, "tool_input": {"command": "printf x > 'experiments/EXP-0001/inputs/source data.csv'"}},
            {"tool_name": "Bash", "cwd": str(spaced_input.parent), "tool_input": {"command": "dd if=/dev/null of=\"source data.csv\""}},
            {"tool_name": "Bash", "cwd": str(dashed_input.parent), "tool_input": {"command": "rm -- -raw.csv"}},
            {"tool_name": "Bash", "cwd": str(dashed_input.parent), "tool_input": {"command": "printf x > -raw.csv"}},
            {"tool_name": "Bash", "cwd": temporary, "tool_input": {"command": "ln runs/mutable.csv experiments/EXP-0001/inputs/linked.csv"}},
            {"tool_name": "Bash", "cwd": temporary, "tool_input": {"command": "ln experiments/EXP-0001/inputs/source.csv runs/source-alias.csv"}},
            {"tool_name": "Bash", "cwd": temporary, "tool_input": {"command": "cp -l runs/mutable.csv experiments/EXP-0001/inputs/hard.csv"}},
            {"tool_name": "Bash", "cwd": temporary, "tool_input": {"command": "cp --link runs/mutable.csv experiments/EXP-0001/inputs/hard2.csv"}},
            {"tool_name": "PowerShell", "cwd": temporary, "tool_input": {"command": "New-Item -ItemType HardLink -Path experiments/EXP-0001/inputs/hard3.csv -Target runs/mutable.csv"}},
            {"tool_name": "PowerShell", "cwd": str(existing_input.parent), "tool_input": {"command": "'x' | Out-File source.csv"}},
            {"tool_name": "PowerShell", "cwd": str(existing_input.parent), "tool_input": {"command": "Copy-Item ../../../runs/new.csv source.csv"}},
            {"tool_name": "PowerShell", "cwd": str(existing_input.parent), "tool_input": {"command": "Export-Csv -Path source.csv"}},
            {"tool_name": "Bash", "cwd": str(existing_input.parent), "tool_input": {"command": "python3 -c \"open('source.csv','w').write('x')\""}},
            {"tool_name": "Bash", "cwd": str(published.parent), "tool_input": {"command": "python3 -c \"open('RPT-0001.md','w').write('x')\""}},
            {"tool_name": "Bash", "cwd": str(extensionless_input.parent), "tool_input": {"command": "python3 -c \"open('blob','wb').write(b'x')\""}},
            {"tool_name": "Bash", "cwd": temporary, "tool_input": {"command": "rm -r experiments/EXP-0002"}},
            {"tool_name": "Bash", "cwd": temporary, "tool_input": {"command": "cat /dev/null >| experiments/EXP-0001/inputs/source.csv"}},
            {"tool_name": "Bash", "cwd": temporary, "tool_input": {"command": "cat /dev/null >! experiments/EXP-0001/inputs/source.csv"}},
            {"tool_name": "Bash", "cwd": temporary, "tool_input": {"command": "command rm experiments/EXP-0001/inputs/source.csv"}},
            {"tool_name": "Bash", "cwd": temporary, "tool_input": {"command": "env rm -r experiments/EXP-0001"}},
            {"tool_name": "Bash", "cwd": temporary, "tool_input": {"command": "/bin/rm experiments/EXP-0001/inputs/source.csv"}},
            {"tool_name": "Bash", "cwd": temporary, "tool_input": {"command": "bash -lc 'rm experiments/EXP-0001/inputs/source.csv'"}},
            {"tool_name": "Bash", "cwd": temporary, "tool_input": {"command": "perl -pi -e s/x/y/ experiments/EXP-0001/inputs/source.csv"}},
            {"tool_name": "Bash", "cwd": temporary, "tool_input": {"command": "ruby -pi -e s/x/y/ experiments/EXP-0001/inputs/source.csv"}},
            {"tool_name": "Bash", "cwd": temporary, "tool_input": {"command": "rsync runs/mutable.csv experiments/EXP-0001/inputs/source.csv"}},
            {"tool_name": "Bash", "cwd": temporary, "tool_input": {"command": "rsync --delete runs/source/ experiments/EXP-0001/inputs/"}},
            {"tool_name": "Bash", "cwd": temporary, "tool_input": {"command": "rsync --remove-source-files experiments/EXP-0001/inputs/source.csv runs/"}},
            {"tool_name": "Bash", "cwd": temporary, "tool_input": {"command": "rsync -a --remove-source-files experiments/EXP-0001/inputs/ runs/copy/"}},
            {"tool_name": "Bash", "cwd": temporary, "tool_input": {"command": "tar -cf runs/archive.tar --remove-files experiments/EXP-0001/inputs/source.csv"}},
            {"tool_name": "Bash", "cwd": temporary, "tool_input": {"workdir": str(existing_input.parent), "command": "rm source.csv"}},
            {"tool_name": "Bash", "cwd": temporary, "tool_input": {"command": "cd experiments/EXP-0001/inputs && rm source.csv"}},
            {"tool_name": "Bash", "cwd": temporary, "tool_input": {"command": "rm experiments/EXP-0001/inputs/{source,other}.csv"}},
            {"tool_name": "Bash", "cwd": temporary, "tool_input": {"command": "find experiments/EXP-0001/inputs -type f -delete"}},
            {"tool_name": "Bash", "cwd": temporary, "tool_input": {"command": "find runs -fprint experiments/EXP-0001/inputs/source.csv"}},
            {"tool_name": "Bash", "cwd": temporary, "tool_input": {"command": "sed -i.bak s/x/y/ experiments/EXP-0001/inputs/source.csv"}},
            {"tool_name": "PowerShell", "cwd": temporary, "tool_input": {"command": "cmd /c \"del experiments\\EXP-0001\\inputs\\source.csv\""}},
            {"tool_name": "Bash", "cwd": temporary, "tool_input": {"command": "tar -xf runs/archive.tar -C experiments/EXP-0001/executions/EXP-0001-E001"}},
            {"tool_name": "Bash", "cwd": temporary, "tool_input": {"command": "link experiments/EXP-0001/inputs/source.csv runs/alias.csv"}},
            {"tool_name": "Bash", "cwd": temporary, "tool_input": {"command": "busybox ln experiments/EXP-0001/inputs/source.csv runs/alias2.csv"}},
            {"tool_name": "Bash", "cwd": temporary, "tool_input": {"command": "ln reports/RPT-0002.md runs/report-alias.md"}},
            {"tool_name": "Bash", "cwd": temporary, "tool_input": {"command": "command ln reports/RPT-0002.md runs/report-alias-command.md"}},
            {"tool_name": "Bash", "cwd": temporary, "tool_input": {"command": "busybox ln reports/RPT-0002.md runs/report-alias-busybox.md"}},
            {"tool_name": "Bash", "cwd": temporary, "tool_input": {"command": "cp -l reports/RPT-0002.md runs/report-alias-2.md"}},
            {"tool_name": "Bash", "cwd": temporary, "tool_input": {"command": "cp -al reports/RPT-0002.md runs/report-alias-3.md"}},
            {"tool_name": "Bash", "cwd": temporary, "tool_input": {"command": "cp --link=always experiments/EXP-0001/inputs/source.csv runs/input-alias.md"}},
            {"tool_name": "PowerShell", "cwd": temporary, "tool_input": {"command": "New-Item -ItemType HardLink -Path runs/report-alias-ps.md -Target reports/RPT-0002.md"}},
            {"tool_name": "PowerShell", "cwd": temporary, "tool_input": {"command": "cmd /c mklink /H runs/report-alias-cmd.md reports/RPT-0002.md"}},
            {"tool_name": "PowerShell", "cwd": temporary, "tool_input": {"command": "fsutil hardlink create runs/report-alias-fs.md reports/RPT-0002.md"}},
            {"tool_name": "Bash", "cwd": temporary, "tool_input": {"command": "ln experiments/EXP-0003/executions/EXP-0003-E001/COMPLETED.md runs/marker-alias.md"}},
            {"tool_name": "Bash", "cwd": temporary, "tool_input": {"command": "sort -o experiments/EXP-0001/inputs/source.csv experiments/EXP-0001/inputs/source.csv"}},
            {"tool_name": "Bash", "cwd": temporary, "tool_input": {"command": "sponge experiments/EXP-0001/inputs/source.csv"}},
            {"tool_name": "Bash", "cwd": temporary, "tool_input": {"command": "sqlite3 experiments/EXP-0001/inputs/source.csv vacuum"}},
            {"tool_name": "Bash", "cwd": temporary, "tool_input": {"command": "cp /tmp/RPT-0001.md reports/"}},
            {"tool_name": "Bash", "cwd": temporary, "tool_input": {"command": "tar -xf runs/archive.tar -C reports"}},
            {"tool_name": "Bash", "cwd": temporary, "tool_input": {"command": "tar -xf runs/archive.tar --directory=reports"}},
            {"tool_name": "Bash", "cwd": temporary, "tool_input": {"command": "tar xf runs/archive.tar -C reports"}},
            {"tool_name": "Bash", "cwd": temporary, "tool_input": {"command": "unzip -o runs/archive.zip -dreports"}},
            {"tool_name": "Bash", "cwd": temporary, "tool_input": {"command": "cp -t reports /tmp/RPT-0001.md"}},
            {"tool_name": "Bash", "cwd": temporary, "tool_input": {"command": "install --target-directory=experiments/EXP-0001/inputs /tmp/source.csv"}},
            {"tool_name": "PowerShell", "cwd": temporary, "tool_input": {"command": "Copy-Item -Destination reports -Path /tmp/RPT-0001.md"}},
            {"tool_name": "PowerShell", "cwd": temporary, "tool_input": {"command": "Expand-Archive -Path runs/archive.zip -DestinationPath experiments/EXP-0001/inputs"}},
            {"tool_name": "Bash", "cwd": temporary, "tool_input": {"command": "rsync -a runs/source/ experiments/EXP-0001/inputs/"}},
            {"tool_name": "Bash", "cwd": temporary, "tool_input": {"command": "cp -R runs/source/. experiments/EXP-0001/inputs/"}},
            {"tool_name": "Bash", "cwd": temporary, "tool_input": {"command": "cp runs/source/* experiments/EXP-0001/inputs/"}},
            {"tool_name": "PowerShell", "cwd": temporary, "tool_input": {"command": "Copy-Item -Recurse -Path runs/source -Destination experiments/EXP-0001/inputs"}},
            {"tool_name": "Bash", "cwd": temporary, "tool_input": {"command": "printf v2 > runs/symlink-source.csv"}},
            {"tool_name": "Bash", "cwd": temporary, "tool_input": {"command": "sed -i.bak s/x/y/ runs/symlink-source.csv"}},
        )
        allowed = (
            {"tool_name": "Write", "cwd": temporary, "tool_input": {"file_path": "experiments/EXP-0001/inputs/new.csv"}},
            {"tool_name": "Write", "cwd": temporary, "tool_input": {"file_path": "experiments/EXP-0001/executions/EXP-0001-E002/result.json"}},
            {"tool_name": "Bash", "cwd": temporary, "tool_input": {"command": "cat experiments/EXP-0001/inputs/source.csv"}},
            {"tool_name": "Edit", "cwd": temporary, "tool_input": {"file_path": "reports/RPT-0002.md"}},
            {"tool_name": "Bash", "cwd": temporary, "tool_input": {"command": "cat experiments/EXP-0001/inputs/source.csv > runs/copy.csv"}},
            {"tool_name": "Bash", "cwd": temporary, "tool_input": {"command": "cd experiments"}},
            {"tool_name": "Bash", "cwd": temporary, "tool_input": {"command": "echo 'rm experiments/EXP-0001/inputs/source.csv'"}},
            {"tool_name": "Bash", "cwd": temporary, "tool_input": {"command": "printf '%s' 'rm experiments/EXP-0001/inputs/source.csv'"}},
            {"tool_name": "Bash", "cwd": temporary, "tool_input": {"command": "python3 -c \"print('rm experiments/EXP-0001/inputs/source.csv')\""}},
            {"tool_name": "Bash", "cwd": temporary, "tool_input": {"command": "rg rm experiments/EXP-0001/inputs/source.csv"}},
            {"tool_name": "Bash", "cwd": temporary, "tool_input": {"command": "ln -s experiments/EXP-0001/inputs/source.csv runs/source-link.csv"}},
            {"tool_name": "Edit", "cwd": temporary, "tool_input": {"file_path": "experiments/EXP-0003/executions/EXP-0003-E001/COMPLETED.md"}},
            {"tool_name": "Bash", "cwd": temporary, "tool_input": {"command": "cp /tmp/new.csv experiments/EXP-0001/inputs/"}},
            {"tool_name": "Bash", "cwd": temporary, "tool_input": {"command": "sort experiments/EXP-0001/inputs/source.csv"}},
            {"tool_name": "Bash", "cwd": temporary, "tool_input": {"command": "jq . experiments/EXP-0001/inputs/source.csv"}},
            {"tool_name": "Bash", "cwd": temporary, "tool_input": {"command": "cat experiments/EXP-0001/inputs/source.csv | tee runs/copy.csv"}},
            {"tool_name": "Bash", "cwd": temporary, "tool_input": {"command": "tar -cf /tmp/archive.tar --exclude '*.aux' reports"}},
            {"tool_name": "Bash", "cwd": temporary, "tool_input": {"command": "cp -t runs experiments/EXP-0001/inputs/source.csv"}},
            {"tool_name": "Bash", "cwd": temporary, "tool_input": {"command": "install --target-directory=runs experiments/EXP-0001/inputs/source.csv"}},
            {"tool_name": "PowerShell", "cwd": temporary, "tool_input": {"command": "Copy-Item -Destination runs -Path experiments/EXP-0001/inputs/source.csv"}},
        )
        failures.extend(f"missed blocked case: {case}" for case in blocked if protected_target(case) is None)
        failures.extend(f"blocked append/read case: {case}" for case in allowed if protected_target(case) is not None)
    if failures:
        print("\n".join(failures), file=sys.stderr)
        return 1
    print(f"protect_evidence.py self-test passed ({len(blocked) + len(allowed)} cases; {ADAPTER_SCHEMA})")
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
    except (json.JSONDecodeError, OSError) as exc:
        print(f"Evidence guard could not parse hook input: {exc}", file=sys.stderr)
        return BLOCK_EXIT
    if not isinstance(payload, dict):
        print("Evidence guard expected a JSON object.", file=sys.stderr)
        return BLOCK_EXIT
    target = protected_target(payload)
    if target is not None:
        print(
            f"Blocked by immutable-evidence policy: {target} already contains write-once evidence "
            "or a published milestone. Append a new execution/artifact instead of altering it.",
            file=sys.stderr,
        )
        return BLOCK_EXIT
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
