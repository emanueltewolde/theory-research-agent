#!/usr/bin/env python3
"""Block agent-created Git worktree isolation in runtime pre-tool hooks."""

from __future__ import annotations

import argparse
import json
import re
import shlex
import sys
from collections.abc import Sequence


ADAPTER_SCHEMA = "research-agent-adapter-v3"
BLOCK_EXIT = 2


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


def _unwrap(tokens: list[str]) -> list[str]:
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
                tokens.pop(0)  # duration
            continue
        if executable == "flock":
            tokens.pop(0)
            while tokens and tokens[0].startswith("-"):
                option = tokens.pop(0).casefold()
                if option in {"-e", "-o", "-s", "-w", "--conflict-exit-code", "--timeout"} and tokens:
                    tokens.pop(0)
            if tokens:
                tokens.pop(0)  # lock file
            continue
        if executable in {"ionice", "strace"}:
            tokens.pop(0)
            value_options = {
                "-c", "--class", "-n", "--classdata", "-p", "--pid",
                "-e", "--event", "-o", "--output", "-u", "--user",
            }
            while tokens and tokens[0].startswith("-"):
                option = tokens.pop(0).casefold()
                if option in value_options and tokens:
                    tokens.pop(0)
            continue
        if executable in {"parallel", "watch"}:
            tokens.pop(0)
            value_options = {
                "-d", "--delay", "-n", "--jobs", "-P", "--max-procs",
                "-t", "--timeout",
            }
            while tokens and tokens[0].startswith("-"):
                option = tokens.pop(0)
                if option in value_options and tokens:
                    tokens.pop(0)
            continue
        break
    return tokens


def _command_requests_worktree(command: str, depth: int = 0) -> bool:
    if depth > 3:
        return False
    if re.search(
        r"(?i)(?:^|[;&|]\s*)start(?:\s+/[a-z]+)*\s+['\"][^'\"]*['\"]"
        r"(?:\s+/[a-z]+)*\s+"
        r"(?:[^\s;&|]*[/\\])?(?:claude|codex)(?:\.exe)?\b[^;&|]*(?:--worktree|-w(?:=|\b))",
        command,
    ):
        return True
    for segment in _top_level_segments(command):
        try:
            raw_tokens = shlex.split(segment, posix=True)
        except ValueError:
            # Malformed quoting is not a valid invocation of either runtime.
            continue
        if raw_tokens:
            raw_executable = raw_tokens[0].replace("\\", "/").rsplit("/", 1)[-1].casefold()
            lowered_tokens = [value.casefold() for value in raw_tokens]
            if raw_executable == "env":
                for option in ("-s", "--split-string"):
                    if option in lowered_tokens[1:]:
                        position = lowered_tokens.index(option)
                        if position + 1 < len(raw_tokens) and _command_requests_worktree(raw_tokens[position + 1], depth + 1):
                            return True
                        raw_tokens = []
                        break
            elif raw_executable == "flock":
                for option in ("-c", "--command"):
                    if option in lowered_tokens[1:]:
                        position = lowered_tokens.index(option)
                        if position + 1 < len(raw_tokens) and _command_requests_worktree(raw_tokens[position + 1], depth + 1):
                            return True
                        raw_tokens = []
                        break
            elif raw_executable in {"parallel", "xargs"} and len(raw_tokens) > 1:
                arguments = raw_tokens[1:]
                value_options = {
                    "-a", "--arg-file", "-d", "--delimiter", "-e", "--eof",
                    "-i", "--replace", "-j", "--jobs", "-l", "--max-lines",
                    "-n", "--max-args", "-p", "--max-procs",
                }
                while arguments and arguments[0].startswith("-"):
                    option = arguments.pop(0).casefold()
                    if option in value_options and arguments:
                        arguments.pop(0)
                if _command_requests_worktree(" ".join(arguments), depth + 1):
                    return True
            elif raw_executable == "find":
                for position, value in enumerate(lowered_tokens[:-1]):
                    if value in {"-exec", "-execdir", "-ok", "-okdir"} and _command_requests_worktree(" ".join(raw_tokens[position + 1:]), depth + 1):
                        return True
            elif raw_executable in {"saps", "start-process"}:
                runtime = None
                for position, value in enumerate(lowered_tokens[:-1]):
                    if value == "-filepath":
                        runtime = raw_tokens[position + 1]
                        break
                runtime = runtime or (raw_tokens[1] if len(raw_tokens) > 1 else "")
                if runtime.replace("\\", "/").rsplit("/", 1)[-1].casefold() in {"claude", "claude.exe", "codex", "codex.exe"} and any(
                    "worktree" in value.casefold() or value.casefold().startswith("-w") for value in raw_tokens[2:]
                ):
                    return True
            elif raw_executable == "start":
                arguments = raw_tokens[1:]
                while arguments and arguments[0].startswith("/"):
                    arguments.pop(0)
                if arguments and arguments[0] == "":
                    arguments.pop(0)
                while arguments and arguments[0].startswith("/"):
                    arguments.pop(0)
                if arguments and arguments[0].replace("\\", "/").rsplit("/", 1)[-1].casefold() in {
                    "claude", "claude.exe", "codex", "codex.exe"
                } and any(
                    value.casefold() in {"--worktree", "-w"}
                    or value.casefold().startswith(("--worktree=", "-w="))
                    or (value.casefold().startswith("-w") and not value.casefold().startswith("--"))
                    for value in arguments[1:]
                ):
                    return True
        tokens = _unwrap(raw_tokens)
        if not tokens:
            continue
        executable = tokens[0].replace("\\", "/").rsplit("/", 1)[-1].casefold()
        arguments = tokens[1:]
        if executable in {"claude", "claude.exe", "codex", "codex.exe"}:
            if any(
                argument.casefold() in {"--worktree", "-w"}
                or argument.casefold().startswith("--worktree=")
                or argument.casefold().startswith("-w=")
                or (argument.casefold().startswith("-w") and not argument.casefold().startswith("--"))
                for argument in arguments
            ):
                return True
            continue
        if executable in {"bash", "fish", "sh", "zsh", "cmd", "cmd.exe", "powershell", "powershell.exe", "pwsh", "pwsh.exe"}:
            for index, argument in enumerate(arguments):
                lowered = argument.casefold()
                is_command_flag = lowered in {"-c", "-lc", "-command", "/c"} or (
                    lowered.startswith("-") and not lowered.startswith("--") and "c" in lowered[1:]
                )
                if is_command_flag and index + 1 < len(arguments):
                    body = " ".join(arguments[index + 1:])
                    if _command_requests_worktree(body, depth + 1):
                        return True
                    break
    return False


def requests_worktree(payload: dict[str, object]) -> bool:
    if str(payload.get("tool_name", "")).casefold() == "enterworktree":
        return True
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        return False
    isolation = tool_input.get("isolation")
    if isinstance(isolation, str) and isolation.lower() == "worktree":
        return True
    command = tool_input.get("command")
    return isinstance(command, str) and _command_requests_worktree(command)


def _self_test() -> int:
    blocked = [
        {"tool_input": {"isolation": "worktree"}},
        {"tool_input": {"command": "claude --worktree proof-a"}},
        {"tool_input": {"command": "echo ok && codex -w verifier"}},
        {"tool_input": {"command": "/usr/local/bin/codex --worktree proof-path"}},
        {"tool_input": {"command": "env codex -w proof-env"}},
        {"tool_input": {"command": "bash -lc \"codex --worktree proof-wrap\""}},
        {"tool_input": {"command": "\"/usr/local/bin/codex\" --worktree proof-quoted"}},
        {"tool_input": {"command": "'codex' -w proof-single-quoted"}},
        {"tool_input": {"command": "claude --worktree"}},
        {"tool_input": {"command": "codex --worktree;"}},
        {"tool_input": {"command": "claude \"--worktree\" proof-quoted-flag"}},
        {"tool_input": {"command": "codex '-w' proof-single-quoted-flag"}},
        {"tool_input": {"command": "timeout 5 claude --worktree proof-timeout"}},
        {"tool_input": {"command": "env -S 'claude --worktree proof-env-s'"}},
        {"tool_input": {"command": "flock -c 'codex -w proof-flock' /tmp/l"}},
        {"tool_input": {"command": "flock /tmp/l codex -w proof-flock-direct"}},
        {"tool_input": {"command": "watch claude --worktree proof-watch"}},
        {"tool_input": {"command": "parallel claude --worktree proof-parallel"}},
        {"tool_input": {"command": "strace codex -w proof-strace"}},
        {"tool_input": {"command": "ionice claude --worktree proof-ionice"}},
        {"tool_input": {"command": "xargs claude --worktree proof-xargs"}},
        {"tool_input": {"command": "xargs -n 1 claude --worktree proof-xargs-options"}},
        {"tool_input": {"command": "parallel -j 2 claude --worktree proof-parallel-options"}},
        {"tool_input": {"command": "find . -exec claude --worktree proof-find ;"}},
        {"tool_input": {"command": "Start-Process -FilePath claude -ArgumentList --worktree,proof"}},
        {"tool_input": {"command": "claude -w=proof"}},
        {"tool_input": {"command": "claude -wproof"}},
        {"tool_input": {"command": "start \"title\" claude --worktree proof-start"}},
        {"tool_input": {"command": "start /b \"\" claude --worktree proof-start-option"}},
        {"tool_input": {"command": "start \"\" /b codex -w proof-start-post-option"}},
        {"tool_input": {"command": "cmd /c start /b \"\" claude --worktree proof-start-nested"}},
        {"tool_input": {"command": "saps claude -ArgumentList --worktree,proof"}},
        {"tool_name": "PowerShell", "tool_input": {"command": "claude --worktree proof-b"}},
        {"tool_name": "EnterWorktree", "tool_input": {}},
    ]
    allowed = [
        {"tool_input": {"isolation": "none"}},
        {"tool_input": {"command": "python3 tools/research.py check"}},
        {"tool_input": {"command": "echo 'codex --worktree proof'"}},
        {"tool_input": {"command": "printf '%s' 'claude -w x'"}},
        {"tool_input": {"command": "python3 -c \"print('codex --worktree x')\""}},
        {"tool_input": {"command": "echo codex --worktree"}},
    ]
    failures = [case for case in blocked if not requests_worktree(case)]
    failures.extend(case for case in allowed if requests_worktree(case))
    if failures:
        print(f"no_worktree.py self-test failures: {failures!r}", file=sys.stderr)
        return 1
    print(f"no_worktree.py self-test passed ({len(blocked) + len(allowed)} cases; {ADAPTER_SCHEMA})")
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
        print(f"No-worktree guard could not parse hook input: {exc}", file=sys.stderr)
        return BLOCK_EXIT
    if not isinstance(payload, dict):
        print("No-worktree guard expected a JSON object.", file=sys.stderr)
        return BLOCK_EXIT
    if requests_worktree(payload):
        print(
            "Blocked by research workspace policy: worktree isolation performs Git operations. "
            "Use unique run/task directories in the shared checkout instead.",
            file=sys.stderr,
        )
        return BLOCK_EXIT
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
