#!/usr/bin/env python3
"""Block Git commands in Codex and Claude Code pre-tool hooks.

The guard is intentionally dependency-free.  Both runtimes send hook input as
JSON on stdin and treat exit status 2 as a denial.  It can also be exercised
directly with ``--check-command`` or ``--self-test``.

This is a strong guard for direct, path-qualified, compound, and common
shell-wrapped Git commands.  It is not an operating-system security boundary:
arbitrary programs can spawn other programs in ways that static command-text
inspection cannot prove safe.  See tools/guards/README.md.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import shlex
import sys
from collections.abc import Iterable, Sequence


ADAPTER_SCHEMA = "research-agent-adapter-v3"
BLOCK_EXIT = 2

_SHELLS = {
    "bash",
    "cmd",
    "cmd.exe",
    "dash",
    "fish",
    "ksh",
    "powershell",
    "powershell.exe",
    "pwsh",
    "pwsh.exe",
    "sh",
    "zsh",
}
_WRAPPERS = {
    "builtin",
    "command",
    "env",
    "exec",
    "flock",
    "ionice",
    "nice",
    "nohup",
    "parallel",
    "setsid",
    "start",
    "start-process",
    "stdbuf",
    "strace",
    "sudo",
    "time",
    "timeout",
    "watch",
    "xargs",
}
_SEPARATORS = {";", "&", "&&", "|", "||", "(", ")", "<", ">", "\n"}
_ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
_DIRECT_FALLBACK = re.compile(
    r"(?i)(?:^|[;&|\n`]\s*)"
    r"(?:(?:command|builtin|exec|env|sudo|nohup|nice|time)\s+)*"
    r"(?:['\"]?[^\s;&|]*[\\/])?git(?:\.exe)?"
    r"(?=$|[\s;&|<>'\"])",
)
_WINDOWS_GIT_FALLBACK = re.compile(
    r"(?i)(?:^|[;&|\n]\s*)['\"]?[A-Za-z]:[\\/]"
    r"[^\r\n;&|]*?[\\/]git(?:\.exe)?['\"]?(?=$|[\s;&|<>'\"])",
)
_CODEX_GIT_APPLY = re.compile(
    r"(?i)(?<![A-Za-z0-9_.-])['\"]?(?:[^\s;&|\"']+[/\\])?"
    r"codex(?:\.exe)?['\"]?\s+apply(?:\s|$|[;&|])"
)


def _basename(token: str) -> str:
    cleaned = token.strip().strip("'\"`").replace("\\", "/").rstrip("/")
    return cleaned.rsplit("/", 1)[-1].lower()


def _is_git_executable(token: str) -> bool:
    executable = _basename(token)
    if executable in {"git", "git.exe"} or executable.startswith("git-"):
        return True
    if any(character in executable for character in "*?["):
        return fnmatch.fnmatchcase("git", executable) or fnmatch.fnmatchcase("git.exe", executable)
    return False


def _mentions_git_metadata(token: str) -> bool:
    """Return true for a literal path into a .git directory or file."""

    cleaned = token.strip().strip("'\"`").replace("\\", "/")
    if not cleaned:
        return False
    variants = [cleaned]
    brace = re.search(r"\{([^{}]+)\}", cleaned)
    if brace is not None:
        choices = brace.group(1).split(",")
        if 1 < len(choices) <= 16:
            variants.extend(cleaned[:brace.start()] + choice + cleaned[brace.end():] for choice in choices)
    for variant in variants:
        parts = [part.lower() for part in variant.split("/") if part not in {"", "."}]
        for part in parts:
            if part == ".git" or fnmatch.fnmatchcase(".git", part):
                return True
            if any(character in part for character in "*?["):
                stripped = re.sub(r"[?*\[\]!]", "", part)
                if stripped == ".git":
                    return True
    return False


def _lex(command: str) -> list[str]:
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|()<>\n")
        lexer.whitespace_split = True
        lexer.commenters = ""
        return list(lexer)
    except (TypeError, ValueError):
        # A malformed command should not make the hook fail open.  The fallback
        # retains punctuation as separators and is deliberately conservative.
        return re.findall(r"&&|\|\||[;&|()<>\n]|[^\s;&|()<>]+", command)


def _segments(tokens: Sequence[str]) -> Iterable[list[str]]:
    current: list[str] = []
    for token in tokens:
        if token in _SEPARATORS or set(token) <= {";", "&", "|", "(", ")", "<", ">"}:
            if current:
                yield current
                current = []
            continue
        current.append(token)
    if current:
        yield current


def _first_command_index(tokens: Sequence[str]) -> int | None:
    for index, token in enumerate(tokens):
        if token in {"!", "{"} or _ASSIGNMENT.match(token):
            continue
        return index
    return None


def _skip_options(tokens: Sequence[str], index: int, value_options: set[str]) -> int:
    folded_value_options = {value.casefold() for value in value_options}
    while index < len(tokens):
        token = tokens[index]
        if token == "--":
            return index + 1
        if not token.startswith("-") or token == "-":
            return index
        index += 1
        if token.casefold() in folded_value_options and index < len(tokens):
            index += 1
    return index


def _unwrap_execution(tokens: Sequence[str], start: int) -> Sequence[str]:
    """Return the actual command suffix for common, explicitly parsed wrappers."""

    suffix = list(tokens[start:])
    while suffix:
        while suffix and _ASSIGNMENT.match(suffix[0]):
            suffix.pop(0)
        if not suffix:
            return ()
        executable = _basename(suffix[0])
        if executable not in _WRAPPERS:
            return suffix
        arguments = suffix[1:]
        if executable in {"builtin", "command", "exec", "nohup", "setsid"}:
            index = _skip_options(arguments, 0, set())
        elif executable == "env":
            index = 0
            value_options = {"-c", "--chdir", "-u", "--unset", "-s", "--split-string"}
            while index < len(arguments) and (arguments[index].startswith("-") or _ASSIGNMENT.match(arguments[index])):
                option = arguments[index].casefold()
                index += 1
                if option in value_options and index < len(arguments):
                    index += 1
        elif executable == "sudo":
            index = _skip_options(
                arguments, 0,
                {"-c", "--close-from", "-g", "--group", "-h", "--host", "-p", "--prompt", "-u", "--user"},
            )
        elif executable == "nice":
            index = _skip_options(arguments, 0, {"-n", "--adjustment"})
        elif executable == "time":
            index = _skip_options(arguments, 0, {"-f", "--format", "-o", "--output"})
        elif executable == "stdbuf":
            index = _skip_options(arguments, 0, {"-i", "-o", "-e"})
        elif executable == "timeout":
            index = _skip_options(arguments, 0, {"-k", "--kill-after", "-s", "--signal"})
            if index < len(arguments):
                index += 1  # duration
        elif executable == "flock":
            index = _skip_options(arguments, 0, {"-E", "--conflict-exit-code", "-w", "--wait"})
            if index < len(arguments):
                index += 1  # lock file or descriptor
        elif executable == "ionice":
            index = _skip_options(arguments, 0, {"-c", "--class", "-n", "--classdata", "-p", "--pid", "-P", "--pgid", "-u", "--uid"})
        elif executable in {"watch", "strace"}:
            index = _skip_options(arguments, 0, {"-d", "--differences", "-n", "--interval", "-o", "--output", "-p", "--attach", "-e"})
        elif executable in {"xargs", "parallel"}:
            index = _skip_options(arguments, 0, {"-a", "--arg-file", "-d", "--delimiter", "-E", "--eof", "-I", "--replace", "-j", "--jobs", "-L", "--max-lines", "-n", "--max-args", "-P", "--max-procs"})
        elif executable in {"start", "start-process"}:
            index = _skip_options(arguments, 0, {"-argumentlist", "-filepath", "-workingdirectory"})
        else:
            return suffix
        suffix = arguments[index:]
    return ()


def _path_accesses_git(path: str, cwd: str | None) -> bool:
    if _mentions_git_metadata(path):
        return True
    candidate = os.path.expanduser(path.strip().strip("'\"`"))
    if not candidate:
        return False
    absolute = candidate if os.path.isabs(candidate) else os.path.join(cwd or os.getcwd(), candidate)
    normalized = os.path.normpath(absolute)
    if _mentions_git_metadata(normalized):
        return True
    try:
        resolved = os.path.realpath(normalized)
    except OSError:
        return False
    return _mentions_git_metadata(resolved)


def _workspace_root(cwd: str | None) -> str:
    current = os.path.realpath(cwd or os.getcwd())
    while True:
        if os.path.isfile(os.path.join(current, "ARTIFACT_INDEX.md")) and os.path.isfile(
            os.path.join(current, "AGENTS.md")
        ):
            return current
        parent = os.path.dirname(current)
        if parent == current:
            return os.path.realpath(cwd or os.getcwd())
        current = parent


def _scope_reaches_workspace_root(path: str, cwd: str | None) -> bool:
    candidate = os.path.expanduser(path.strip().strip("'\"`"))
    if not candidate or re.match(r"(?i)^[a-z][a-z0-9+.-]*://", candidate):
        return False
    absolute = candidate if os.path.isabs(candidate) else os.path.join(cwd or os.getcwd(), candidate)
    scope = os.path.realpath(os.path.normpath(absolute))
    root = _workspace_root(cwd)
    try:
        return os.path.commonpath([scope, root]) == scope
    except ValueError:
        return False


def _metadata_access(executable: str, arguments: Sequence[str], cwd: str | None) -> bool:
    if executable in {"echo", "printf", "write-host", "write-output"}:
        return False
    path_value_options = {
        "curl": {"-K", "--config"},
        "rsync": {"--exclude-from", "--include-from"},
        "sqlite3": {"-init", "--init"},
        "tar": {"-T", "--files-from", "-X", "--exclude-from"},
    }.get(executable, set())
    for index, token in enumerate(arguments):
        if token in path_value_options and index + 1 < len(arguments) and _path_accesses_git(arguments[index + 1], cwd):
            return True
        for option in path_value_options:
            if token.casefold().startswith(option.casefold() + "=") and _path_accesses_git(token.split("=", 1)[1], cwd):
                return True
    if executable == "dd" and any(
        token.casefold().startswith("if=") and _path_accesses_git(token[3:], cwd)
        for token in arguments
    ):
        return True
    if executable in {"jq", "sed", "awk", "gawk", "mawk"}:
        path_options = (
            {"-f", "--from-file", "-L", "--library-path"}
            if executable == "jq"
            else {"-f", "--file"}
        )
        skip: set[int] = set()
        if executable == "jq":
            for index, token in enumerate(arguments):
                lowered = token.casefold()
                if lowered in {"--arg", "--argjson"} and index + 2 < len(arguments):
                    skip.update({index, index + 1, index + 2})
                if lowered in {"--rawfile", "--slurpfile"} and index + 2 < len(arguments):
                    skip.update({index, index + 1, index + 2})
                    if _path_accesses_git(arguments[index + 2], cwd):
                        return True
        for index, token in enumerate(arguments):
            lowered = token.casefold()
            if lowered in {value.casefold() for value in path_options} and index + 1 < len(arguments):
                skip.update({index, index + 1})
                if _path_accesses_git(arguments[index + 1], cwd):
                    return True
            for option in path_options:
                if lowered.startswith(option.casefold() + "=") and _path_accesses_git(token.split("=", 1)[1], cwd):
                    return True
        operands = [
            token for index, token in enumerate(arguments)
            if index not in skip and not token.startswith("-")
        ]
        return any(_path_accesses_git(token, cwd) for token in operands[1:])
    if executable in {"rg", "ripgrep", "grep", "egrep", "fgrep"}:
        path_options = {
            "-f", "--file", "--ignore-file", "--pre", "--exclude-from"
        }
        for index, token in enumerate(arguments):
            lowered = token.casefold()
            if lowered in path_options and index + 1 < len(arguments) and _path_accesses_git(arguments[index + 1], cwd):
                return True
            for option in path_options:
                if lowered.startswith(option + "=") and _path_accesses_git(token.split("=", 1)[1], cwd):
                    return True
        skipped: set[int] = set()
        globs: list[str] = []
        for index, token in enumerate(arguments):
            lowered = token.casefold()
            if lowered in {"-g", "--glob", "--iglob"} and index + 1 < len(arguments):
                skipped.update({index, index + 1})
                globs.append(arguments[index + 1])
            elif any(lowered.startswith(option + "=") for option in ("--glob", "--iglob")):
                skipped.add(index)
                globs.append(token.split("=", 1)[1])
        if any(not value.startswith("!") and _mentions_git_metadata(value) for value in globs):
            return True
        operands = [
            token for index, token in enumerate(arguments)
            if index not in skipped and not token.startswith("-")
        ]
        paths = operands if any(token.casefold() == "--files" for token in arguments) else operands[1:]
        excludes_git = any(value.startswith("!") and _mentions_git_metadata(value[1:]) for value in globs)
        if executable in {"rg", "ripgrep"} and "--hidden" in [value.casefold() for value in arguments] and not excludes_git:
            scan_paths = paths or ["."]
            if any(_scope_reaches_workspace_root(value, cwd) for value in scan_paths):
                return True
        recursive = any(
            value.casefold() == "--recursive"
            or (
                value.startswith("-")
                and not value.startswith("--")
                and "r" in value[1:].casefold()
            )
            for value in arguments
        )
        excludes_git_dir = any(
            value.casefold() == "--exclude-dir=.git"
            or (
                value.casefold() == "--exclude-dir"
                and index + 1 < len(arguments)
                and arguments[index + 1].casefold() == ".git"
            )
            for index, value in enumerate(arguments)
        )
        if executable in {"grep", "egrep", "fgrep"} and recursive and not excludes_git_dir:
            scan_paths = paths or ["."]
            if any(_scope_reaches_workspace_root(value, cwd) for value in scan_paths):
                return True
        return any(_path_accesses_git(token, cwd) for token in paths)
    if executable == "find":
        paths: list[str] = []
        for token in arguments:
            if token in {"-H", "-L", "-P"} and not paths:
                continue
            if token.startswith("-") or token in {"!", "("}:
                break
            paths.append(token)
        if any(_path_accesses_git(token, cwd) for token in paths):
            return True
        prunes_git = "-prune" in [value.casefold() for value in arguments] and any(
            _mentions_git_metadata(value) for value in arguments
        )
        if not prunes_git and any(_scope_reaches_workspace_root(value, cwd) for value in (paths or ["."])):
            return True
        path_predicates = {
            "-anewer", "-cnewer", "-files0-from", "-newer", "-samefile"
        }
        for index, token in enumerate(arguments[:-1]):
            lowered = token.casefold()
            if (
                lowered in path_predicates
                or re.fullmatch(r"-newer[a-z]{2}", lowered) is not None
            ) and _path_accesses_git(arguments[index + 1], cwd):
                return True
        return False
    if executable in {"ls", "ls.exe"}:
        recursive = any(
            value.casefold() == "--recursive"
            or (value.startswith("-") and not value.startswith("--") and "r" in value[1:].casefold())
            for value in arguments
        )
        includes_hidden = any(
            value.casefold() in {"--all", "--almost-all"}
            or (value.startswith("-") and not value.startswith("--") and "a" in value[1:].casefold())
            for value in arguments
        )
        paths = [value for value in arguments if not value.startswith("-")] or ["."]
        if recursive and includes_hidden and any(_scope_reaches_workspace_root(value, cwd) for value in paths):
            return True
    metadata_arguments = list(arguments)
    if executable == "tar":
        skip: set[int] = set()
        for index, token in enumerate(arguments):
            lowered = token.casefold()
            if lowered in {"--transform", "--xform", "--exclude"} and index + 1 < len(arguments):
                skip.update({index, index + 1})
            elif any(lowered.startswith(prefix) for prefix in ("--transform=", "--xform=", "--exclude=")):
                skip.add(index)
        metadata_arguments = [token for index, token in enumerate(arguments) if index not in skip]
    elif executable in {"curl", "curl.exe"}:
        skip = set()
        inert_value_options = {"--data", "--data-ascii", "--data-binary", "--data-raw", "--url"}
        for index, token in enumerate(arguments):
            lowered = token.casefold()
            if lowered in inert_value_options and index + 1 < len(arguments):
                value = arguments[index + 1]
                if not value.casefold().startswith("file:"):
                    skip.update({index, index + 1})
            elif any(lowered.startswith(option + "=") for option in inert_value_options):
                value = token.split("=", 1)[1]
                if not value.casefold().startswith("file:"):
                    skip.add(index)
            elif re.match(r"(?i)^https?://", token):
                skip.add(index)
        metadata_arguments = [token for index, token in enumerate(arguments) if index not in skip]
    return any(_path_accesses_git(token, cwd) for token in metadata_arguments)


def _segment_invokes_git(tokens: Sequence[str], depth: int, cwd: str | None) -> bool:
    index = _first_command_index(tokens)
    if index is None:
        return False

    original_executable = _basename(tokens[index])
    original_arguments = list(tokens[index + 1:])
    if original_executable == "env":
        for pos, token in enumerate(original_arguments[:-1]):
            if token.casefold() in {"-s", "--split-string"}:
                return contains_git_invocation(original_arguments[pos + 1], depth + 1, cwd)
    if original_executable == "flock":
        for pos, token in enumerate(original_arguments[:-1]):
            if token.casefold() in {"-c", "--command"}:
                return contains_git_invocation(original_arguments[pos + 1], depth + 1, cwd)
    if original_executable in {"saps", "start-process"}:
        for pos, token in enumerate(original_arguments[:-1]):
            if token.casefold() == "-filepath" and _is_git_executable(original_arguments[pos + 1]):
                return True
        if original_arguments and _is_git_executable(original_arguments[0]):
            return True
    effective = _unwrap_execution(tokens, index)
    if not effective:
        return False
    executable = _basename(effective[0])
    arguments = list(effective[1:])
    if _is_git_executable(effective[0]):
        return True
    if executable in {"codex", "codex.exe"} and arguments and arguments[0].casefold() in {"a", "apply", "review"}:
        return True
    if executable in {"eval", "iex", "invoke-expression"} and arguments:
        return contains_git_invocation(" ".join(arguments), depth + 1, cwd)
    if executable in {"start-job", "foreach-object", "%"} and arguments:
        start = 0
        for pos, token in enumerate(arguments):
            if token.casefold() in {"-scriptblock", "-process", "-begin", "-end"}:
                start = pos + 1
                break
        return contains_git_invocation(" ".join(arguments[start:]), depth + 1, cwd)
    if executable in {"saps", "start-process"}:
        for pos, token in enumerate(arguments[:-1]):
            if token.casefold() == "-filepath" and _is_git_executable(arguments[pos + 1]):
                return True
        if arguments and _is_git_executable(arguments[0]):
            return True
    if executable == "." and arguments and _is_git_executable(arguments[0]):
        return True

    if executable in _SHELLS and depth < 4:
        for pos, option_token in enumerate(arguments):
            option = option_token.lower()
            if option in {"-c", "-lc", "-cl", "/c", "-command", "-encodedcommand"}:
                if pos + 1 < len(arguments):
                    return contains_git_invocation(" ".join(arguments[pos + 1 :]), depth + 1, cwd)
        # PowerShell's call operator may provide the command without -Command.
        if any(_is_git_executable(token) for token in arguments):
            return True

    # find(1) and similar tools may launch an executable supplied after -exec.
    for pos, token in enumerate(arguments[:-1]):
        if token.lower() in {"-exec", "-execdir", "-ok", "-okdir", "/c", "-command"}:
            terminator = next(
                (end for end in range(pos + 1, len(arguments)) if arguments[end] in {";", "+"}),
                len(arguments),
            )
            launched = arguments[pos + 1:terminator]
            if launched and _segment_invokes_git(launched, depth + 1, cwd):
                return True
    return _metadata_access(executable, arguments, cwd)


def contains_git_invocation(command: str, depth: int = 0, cwd: str | None = None) -> bool:
    """Detect Git execution or direct access to Git metadata."""

    if not command.strip():
        return False

    command = command.replace("\\\n", "")
    if re.search(
        r"(?i)(?:^|[;&|]\s*)start(?:\s+/[a-z]+)*\s+['\"][^'\"]*['\"]"
        r"(?:\s+/[a-z]+)*\s+(?:[^\s;&|]*[/\\])?git(?:\.exe)?(?:\s|$)",
        command,
    ):
        return True
    tokens = _lex(command)
    if any(_segment_invokes_git(segment, depth, cwd) for segment in _segments(tokens)):
        return True

    # shlex intentionally treats quoted fragments as opaque.  Recurse through
    # backtick command substitutions, a common legacy shell wrapper.
    if depth < 4:
        for inner in re.findall(r"`([^`]*)`", command):
            if contains_git_invocation(inner, depth + 1, cwd):
                return True

    return bool(
        _DIRECT_FALLBACK.search(command)
        or _WINDOWS_GIT_FALLBACK.search(command)
    )


def _read_hook_payload() -> dict[str, object]:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, OSError) as exc:
        print(f"No-Git guard could not parse hook input: {exc}", file=sys.stderr)
        raise SystemExit(BLOCK_EXIT) from exc
    if not isinstance(payload, dict):
        print("No-Git guard expected a JSON object from the hook runtime.", file=sys.stderr)
        raise SystemExit(BLOCK_EXIT)
    return payload


def payload_accesses_git(payload: dict[str, object]) -> bool:
    """Inspect documented shell and file-tool fields in a hook payload."""

    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        return False
    cwd_value = payload.get("cwd")
    cwd = cwd_value if isinstance(cwd_value, str) and cwd_value else os.getcwd()
    workdir = tool_input.get("workdir")
    if isinstance(workdir, str) and workdir:
        cwd = workdir if os.path.isabs(workdir) else os.path.join(cwd, workdir)
    cwd = os.path.normpath(os.path.expanduser(cwd))
    if _path_accesses_git(cwd, None):
        return True
    command = tool_input.get("command")
    if isinstance(command, str) and contains_git_invocation(command, cwd=cwd):
        return True
    tool_name = str(payload.get("tool_name", "")).casefold()
    path_keys = ["file_path", "path", "target_path", "notebook_path"]
    if tool_name == "glob":
        path_keys.append("pattern")
    if tool_name == "grep":
        path_keys.append("glob")
    for key in path_keys:
        value = tool_input.get(key)
        if isinstance(value, str) and _path_accesses_git(value, cwd):
            return True
    return False


def _self_test() -> int:
    blocked = [
        "git status",
        "/usr/bin/git diff --stat",
        "/usr/bin/g?t status",
        "env LC_ALL=C git log -1",
        "bash -lc 'git status'",
        "echo ready && git status",
        "cmd /c git status",
        "find . -exec git status ;",
        "echo $(git status)",
        "ls .git/config",
        "ls .g?it/config",
        r'"C:\Program Files\Git\bin\git.exe" status',
        "git-upload-pack repository",
        "codex apply",
        "/usr/local/bin/codex apply",
        "timeout 5 git status",
        "setsid git status",
        "stdbuf -oL git status",
        "flock /tmp/research.lock git status",
        "ionice git status",
        "watch git status",
        "parallel git ::: status",
        "strace git status",
        "start git status",
        "powershell -Command \"Start-Process git -ArgumentList status\"",
        "powershell -Command \"Start-Process -FilePath git -ArgumentList status\"",
        "env -S 'git status'",
        "flock -c 'git status' /tmp/research.lock",
        "rg --files .git",
        "rg -f .git/config docs",
        "rg --ignore-file .git/info/exclude pattern docs",
        "grep --exclude-from=.git/list pattern docs",
        "jq -f .git/filter config.json",
        "sed --file=.git/script docs",
        "awk -f .git/script docs",
        "find -L .git -type f",
        "find . -newer .git/HEAD",
        "find . -samefile .git/index",
        "rg --hidden needle .",
        "rg --hidden -g '.git/**' needle .",
        "grep -R needle .",
        "find . -type f",
        "ls -Ra .",
        "find . -exec sh -c 'git status' ';'",
        "tar --files-from=.git/list -cf /tmp/archive.tar",
        "curl --config=.git/config https://example.invalid",
        "dd if=.git/config of=/tmp/copy",
        "eval 'git status'",
        "Invoke-Expression 'git status'",
        "iex 'git status'",
        "Start-Job -ScriptBlock { git status }",
        "ForEach-Object { git status }",
        ". git status",
        "codex a",
        "cat .g{it,xx}/config",
        "cat .g\\\nit/config",
        "start \"title\" git status",
        "start /b \"\" git status",
        "parallel -j 2 git status",
        "xargs -d '\\n' git status",
        "powershell -Command \"saps git -ArgumentList status\"",
    ]
    allowed = [
        "echo git",
        "printf 'digital research'",
        "python3 -c \"print('git')\"",
        "rg --files research",
        "python3 tools/research.py check",
        "env echo git",
        "sudo echo git",
        "time echo git",
        "nice echo git",
        "nohup echo git",
        "xargs echo git",
        "command echo git",
        "sudo printf git",
        "echo .git/config",
        "printf '%s' .git/config",
        "rg '.git' docs",
        "rg -n '\\.git' docs",
        "grep .git AGENTS.md",
        "find . -path './.git' -prune",
        "rg --hidden -g '!.git/**' needle .",
        "rg --hidden needle docs",
        "grep -R --exclude-dir=.git needle .",
        "ls -Ra docs",
        "echo codex apply",
        "claude -p 'review CLM-0001 independently'",
        "claude --print 'Write a literature review'",
        "jq '.git' config.json",
        "sed -n '/.git/p' docs/RUNTIMES.md",
        "awk '/.git/' AGENTS.md",
        "powershell -Command \"Write-Output '.git/config'\"",
        "sed --expression='s/.git/repository/' docs/RUNTIMES.md",
        "tar --transform='s/.git/repository/' -cf /tmp/archive.tar docs",
        "curl --data='.git/config' https://example.invalid",
        "curl --url='https://example.invalid/.git/config'",
        "jq --arg path '.git/config' '{path:$path}'",
    ]

    blocked_payloads = [
        {"tool_name": "Write", "tool_input": {"file_path": ".git/config", "content": "x"}},
        {"tool_name": "Glob", "tool_input": {"pattern": "**/.git/**"}},
        {"tool_name": "Grep", "tool_input": {"pattern": "status", "path": "nested/.git"}},
        {
            "tool_name": "apply_patch",
            "tool_input": {
                "command": "*** Begin Patch\n*** Update File: .git/config\n@@\n-x\n+y\n*** End Patch"
            },
        },
        {
            "tool_name": "PowerShell",
            "tool_input": {"command": r'& "C:\Program Files\Git\bin\git.exe" status'},
        },
        {"tool_name": "Bash", "cwd": "/tmp/project/.git", "tool_input": {"command": "cat config"}},
        {"tool_name": "Bash", "cwd": "/tmp/project", "tool_input": {"workdir": "runs/../.git", "command": "ls"}},
        {"tool_name": "Read", "cwd": "/tmp/project/.git", "tool_input": {"file_path": "config"}},
    ]
    allowed_payloads = [
        {"tool_name": "Write", "tool_input": {"file_path": "runs/RUN-0001/RUN.md", "content": "Git is human-owned."}},
    ]

    failures: list[str] = []
    failures.extend(f"missed blocked case: {case}" for case in blocked if not contains_git_invocation(case))
    failures.extend(f"blocked safe case: {case}" for case in allowed if contains_git_invocation(case))
    failures.extend(f"missed blocked payload: {case}" for case in blocked_payloads if not payload_accesses_git(case))
    failures.extend(f"blocked safe payload: {case}" for case in allowed_payloads if payload_accesses_git(case))
    if failures:
        print("\n".join(failures), file=sys.stderr)
        return 1
    total = len(blocked) + len(allowed) + len(blocked_payloads) + len(allowed_payloads)
    print(f"no_git.py self-test passed ({total} cases; {ADAPTER_SCHEMA})")
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--hook",
        choices=("auto", "codex", "claude"),
        default="auto",
        help="Hook caller; accepted for receipts and future schema differences.",
    )
    parser.add_argument("--check-command", metavar="COMMAND", help="Check one command without reading stdin.")
    parser.add_argument("--self-test", action="store_true", help="Run dependency-free guard canaries.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.self_test:
        return _self_test()

    if args.check_command is not None:
        command = args.check_command
    else:
        payload = _read_hook_payload()
        if payload_accesses_git(payload):
            print(
                "Blocked by research workspace policy: agents must not invoke Git or access .git metadata. "
                "Use research artifacts for epistemic state; leave version control to the human or trusted external automation.",
                file=sys.stderr,
            )
            return BLOCK_EXIT
        return 0

    if contains_git_invocation(command):
        print(
            "Blocked by research workspace policy: agents must not invoke Git or access .git metadata. "
            "Use research artifacts for epistemic state; leave version control to the human or trusted external automation.",
            file=sys.stderr,
        )
        return BLOCK_EXIT
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
