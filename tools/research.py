#!/usr/bin/env python3
"""Small, dependency-free utilities for a text-first research workspace.

The program deliberately does *not* schedule agents, install software, access
the network, or operate version control.  Its stable on-disk interface is
ordinary Markdown.

``ARTIFACT_INDEX.md`` is expected to contain these sections (extra columns are
allowed and the column order is immaterial)::

    ## Allocation counters

    | Prefix | Meaning | Last allocated |
    | --- | --- | ---: |
    | RUN | Substantial research run | 0 |

    ## Artifact registry

    | ID | Status | Path | Created |
    | --- | --- | --- | --- |

Counter headers named ``Counter``, ``Last ID``, or ``Next`` are also
understood.  ``Next`` is interpreted as the next number to allocate; all other
forms store the last allocated number.  Registry paths may be plain paths or
Markdown links.  Allocations use an advisory lock plus atomic replacement.

Templates live at ``templates/<kind>.md`` and may use double-brace tokens such
as ``{{ID}}``, ``{{TITLE}}``, ``{{DATE}}``, ``{{CONTRACT_REVISION}}``,
``{{STATE_REVISION}}``, ``{{CLAIM_ID}}``, ``{{CLAIM_REVISION}}``, and
    ``{{CLAIM_DIGEST}}``, ``{{EVIDENCE_REVISION}}``, and
    ``{{EVIDENCE_DIGEST}}``.  Missing templates fail closed so that allocation cannot
publish a record which is incompatible with the checked artifact contract.
"""

from __future__ import annotations

import argparse
import contextlib
import dataclasses
import datetime as _datetime
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from typing import Callable, Iterable, Iterator, Mapping, Sequence
from urllib.parse import unquote


ADAPTER_SCHEMA = "research-agent-adapter-v1"
# Retain explicitly supported historical schemas here when upgrading, along
# with a version-aware mapping resolver. Unknown versions never bypass gates.
SUPPORTED_ADAPTER_SCHEMAS = frozenset({ADAPTER_SCHEMA})
SEMANTIC_PROFILES: tuple[str, ...] = (
    "maintenance", "coordinator", "substantive", "deep", "pivotal",
)
PREFIXES: tuple[str, ...] = (
    "RUN", "DIR", "CLM", "ATT", "REV", "LIT", "EXP", "INB", "RPT"
)

GUARD_FILENAMES: tuple[str, ...] = (
    "no_git.py", "no_worktree.py", "protect_shared.py", "protect_evidence.py",
    "protect_runtime.py", "README.md",
)

CONTROL_SAFETY_PATHS: tuple[str, ...] = (
    "AGENTS.md", "CLAUDE.md", "PROJECT.md", "STATE.md", "ARTIFACT_INDEX.md",
    "tools/research.py", "runtime", "runtime/PROFILES.md", ".codex", ".claude", "tools/guards",
)


@dataclasses.dataclass(frozen=True)
class ArtifactSpec:
    kind: str
    prefix: str
    relative_path: Callable[[str], Path]


ARTIFACT_SPECS: dict[str, ArtifactSpec] = {
    "run": ArtifactSpec("run", "RUN", lambda ident: Path("runs") / ident / "RUN.md"),
    "direction": ArtifactSpec("direction", "DIR", lambda ident: Path("research/DIRECTIONS.md")),
    "claim": ArtifactSpec(
        "claim", "CLM", lambda ident: Path("research/claims") / f"{ident}.md"
    ),
    "attempt": ArtifactSpec(
        "attempt", "ATT", lambda ident: Path("research/attempts") / f"{ident}.md"
    ),
    "review": ArtifactSpec(
        "review", "REV", lambda ident: Path("research/reviews") / f"{ident}.md"
    ),
    "literature": ArtifactSpec(
        "literature", "LIT", lambda ident: Path("literature/notes") / f"{ident}.md"
    ),
    "experiment": ArtifactSpec(
        "experiment", "EXP", lambda ident: Path("experiments") / ident / "README.md"
    ),
    "inbox": ArtifactSpec("inbox", "INB", lambda ident: Path("research/INBOX.md")),
    "report": ArtifactSpec("report", "RPT", lambda ident: Path("reports") / f"{ident}.md"),
}


ROOT_REQUIRED_HEADINGS: Mapping[str, tuple[str, ...]] = {
    "PROJECT.md": (
        "Objective and intended contribution", "Formal model", "Central definitions",
        "Permitted assumptions", "Prohibited shortcuts", "Scope and exclusions",
        "Relevant background", "Success criteria", "Expected deliverable",
        "Operational constraints", "Human-alignment triggers", "Initially unresolved questions",
        "Revision log",
    ),
    "STATE.md": (
        "Active objective", "Strongest validated results", "Pivotal candidate or open claims",
        "Direction portfolio snapshot", "Blockers and unresolved human questions",
        "In-flight work", "Recommended next action", "Strategic review",
        "Useful alternatives", "Human overview refresh",
    ),
    "OVERVIEW.md": (
        "Executive summary", "Strongest validated results", "Important open claims",
        "Best counterexamples and impossibility results", "Most informative experiments",
        "Central literature", "Direction outlook", "Manuscript progress",
        "Consequential human decisions needed", "Recent milestone reports",
    ),
}


ROOT_REQUIRED_LABELS: Mapping[str, tuple[str, ...]] = {
    "PROJECT.md": (
        "Contract revision", "Revision date", "Contract status", "Project title", "Research mode",
    ),
    "STATE.md": (
        "State revision", "Contract revision", "Last integrated run", "Integration condition", "Active run",
    ),
    "OVERVIEW.md": (
        "Overview status", "Contract revision covered", "State revision covered",
        "Last refreshed", "Next refresh trigger",
    ),
}


ARTIFACT_REQUIRED_HEADINGS: Mapping[str, tuple[str, ...]] = {
    "CLM": ("Exact statement", "Assumptions, quantifiers, scope, and exceptions",
            "Relationship to the project question", "Dependencies", "Evidence", "Proof or derivation",
            "Known limitations and open issues", "Independent reviews", "Manuscript locations", "Change notes"),
    "ATT": ("Assumptions used", "Approach", "Outcome and support", "Exact failure point or obstruction",
            "Counterexamples and partial results", "Reusable observations", "Produced artifacts",
            "Retry and revival conditions"),
    "REV": ("Materials supplied", "Independence statement", "Verification approach",
            "Correctness assessment", "Claim-fidelity assessment", "Assumption, quantifier, and scope audit",
            "Falsification and counterexample attempts", "Reproduction or source checks",
            "Verdict rationale", "Required corrections or follow-up"),
    "LIT": ("Bibliographic record", "Precise source locations", "Source statement and assumptions",
            "Project-facing interpretation", "Translation into project terminology",
            "Techniques that may transfer", "Relationships to active questions", "Contradictions and tensions",
            "Limitations and unresolved interpretation", "Verification notes"),
    "EXP": ("Research question", "Protocol", "Evidentiary meaning", "Entry point and commands",
            "Environment and dependencies", "Input and source-data provenance",
            "Parameters, seeds, and hardware", "Executions", "Interpretation",
            "Limitations and threats to validity", "Mathematical validation needs", "Evidence preservation notes"),
    "RUN": ("Objective", "Starting point", "Task packets and profile receipts", "Work attempted",
            "Most important findings", "Changed artifacts", "Negative results",
            "Provisional assumptions and uncertainties", "Deferred findings and inbox items",
            "Human questions", "Recommended next actions", "Strategic review check",
            "Human overview check", "Integration close"),
    "RPT": ("Executive summary", "Strongest validated results", "Important open claims",
            "Best counterexamples and negative results", "Informative experiments", "Central literature",
            "Direction outlook", "Manuscript progress", "Consequential human decisions",
            "Recommended next actions", "Next milestone trigger"),
}


ARTIFACT_REQUIRED_LABELS: Mapping[str, tuple[str, ...]] = {
    "RUN": ("Status", "Integration status", "Base state revision", "Contract revision", "Opened",
            "Closed", "Integration authority", "Related artifacts"),
    "CLM": ("Status", "Claim kind", "Evidence class", "Claim revision", "Statement digest",
            "Evidence revision", "Evidence digest", "Required review profile", "Contract revision", "Created in", "Last updated in",
            "Related artifacts", "Supersedes"),
    "ATT": ("Status", "Outcome", "Contract revision", "Created in", "Last updated in", "Assigned question",
            "Related direction", "Related claim", "Related artifacts"),
    "REV": ("Status", "Verdict", "Target claim", "Target claim revision", "Target statement digest",
            "Target evidence revision", "Target evidence digest", "Contract revision", "Created in", "Last updated in", "Fresh context", "Requested profile",
            "Task receipt", "Related artifacts"),
    "LIT": ("Status", "Record kind", "BibTeX key", "Stable locator", "Contract revision", "Created in",
            "Last updated in", "Related artifacts", "Supersedes"),
    "EXP": ("Status", "Evidence class", "Contract revision", "Created in", "Last updated in",
            "Related direction", "Related claim", "Created by run", "Related artifacts", "Supersedes"),
    "RPT": ("Status", "Report date", "Contract revision", "State revision", "Runs covered", "Prepared in",
            "Manuscript build", "Supersedes"),
}


VALID_STATUSES: Mapping[str, set[str]] = {
    "CLM": {"draft", "candidate", "under review", "validated", "rejected", "refuted", "inconclusive", "superseded"},
    "ATT": {"active", "completed"},
    "REV": {"draft", "active", "completed"},
    "RUN": {"active", "interrupted", "completed"},
    "DIR": {"active", "parked", "blocked", "closed"},
    "INB": {"new", "pursue", "merged", "deferred", "discarded", "resolved"},
    "LIT": {"draft", "active", "completed", "superseded"},
    "EXP": {"planned", "active", "completed", "blocked", "superseded"},
    "RPT": {"draft", "published"},
}


class ResearchError(RuntimeError):
    """An expected, user-actionable CLI failure."""


@dataclasses.dataclass(frozen=True)
class Diagnostic:
    severity: str
    code: str
    message: str
    path: Path | None = None

    def render(self, root: Path) -> str:
        location = ""
        if self.path is not None:
            try:
                location = f" {self.path.relative_to(root)}:"
            except ValueError:
                location = f" {self.path}:"
        return f"{self.severity.upper()} [{self.code}]{location} {self.message}"


@dataclasses.dataclass
class CheckReport:
    diagnostics: list[Diagnostic] = dataclasses.field(default_factory=list)

    def add(self, severity: str, code: str, message: str, path: Path | None = None) -> None:
        self.diagnostics.append(Diagnostic(severity, code, message, path))

    @property
    def errors(self) -> list[Diagnostic]:
        return [item for item in self.diagnostics if item.severity == "error"]

    @property
    def warnings(self) -> list[Diagnostic]:
        return [item for item in self.diagnostics if item.severity == "warning"]

    def extend(self, other: "CheckReport") -> None:
        self.diagnostics.extend(other.diagnostics)


def _today() -> str:
    return _datetime.date.today().isoformat()


def _now() -> str:
    return _datetime.datetime.now(_datetime.timezone.utc).replace(microsecond=0).isoformat()


def _atomic_write(path: Path, text: str) -> None:
    """Replace *path* atomically, fsyncing the file before publication."""
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = path.stat().st_mode if path.exists() else None
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        if mode is not None:
            os.chmod(temporary, mode)
        os.replace(temporary, path)
        with contextlib.suppress(OSError):
            directory_fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
    finally:
        with contextlib.suppress(FileNotFoundError):
            temporary.unlink()


def _windows_lock_byte(stream, module, unlock: bool = False) -> None:
    """Lock/unlock byte zero; factored for deterministic platform-neutral tests."""
    stream.seek(0)
    if not unlock and not stream.read(1):
        stream.seek(0)
        stream.write(b"0")
        stream.flush()
    stream.seek(0)
    mode = module.LK_UNLCK if unlock else module.LK_LOCK
    module.locking(stream.fileno(), mode, 1)


class _FileLock:
    """Portable-enough advisory lock using only the standard library."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._stream = None

    def __enter__(self) -> "_FileLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._stream = self.path.open("a+b")
        try:
            import fcntl  # type: ignore[import-not-found]
            fcntl.flock(self._stream.fileno(), fcntl.LOCK_EX)
        except ImportError:  # pragma: no cover - exercised on Windows
            import msvcrt  # type: ignore[import-not-found]
            _windows_lock_byte(self._stream, msvcrt)
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        assert self._stream is not None
        try:
            try:
                import fcntl  # type: ignore[import-not-found]
                fcntl.flock(self._stream.fileno(), fcntl.LOCK_UN)
            except ImportError:  # pragma: no cover - exercised on Windows
                import msvcrt  # type: ignore[import-not-found]
                _windows_lock_byte(self._stream, msvcrt, unlock=True)
        finally:
            self._stream.close()


def _split_table_row(line: str) -> list[str] | None:
    stripped = line.strip()
    if not stripped.startswith("|") or not stripped.endswith("|"):
        return None
    return [cell.strip() for cell in stripped[1:-1].split("|")]


def _is_separator_row(cells: Sequence[str]) -> bool:
    return bool(cells) and all(re.fullmatch(r":?-{3,}:?", cell.replace(" ", "")) for cell in cells)


def _normal_header(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


def _section_bounds(lines: Sequence[str], heading: str) -> tuple[int, int]:
    pattern = re.compile(rf"^##\s+{re.escape(heading)}\s*$", re.IGNORECASE)
    matches = [index for index, line in enumerate(lines) if pattern.fullmatch(line.strip())]
    if not matches:
        raise ResearchError(f"missing `## {heading}`")
    if len(matches) != 1:
        raise ResearchError(f"expected exactly one `## {heading}` section; found {len(matches)}")
    start = matches[0]
    end = next(
        (index for index in range(start + 1, len(lines)) if re.match(r"^##\s+", lines[index])),
        len(lines),
    )
    return start, end


@dataclasses.dataclass
class _Table:
    header_line: int
    headers: list[str]
    rows: list[tuple[int, list[str]]]


def _find_table(lines: Sequence[str], start: int, end: int) -> _Table:
    for line_index in range(start + 1, end):
        headers = _split_table_row(lines[line_index])
        if headers is None or _is_separator_row(headers):
            continue
        separator_index = line_index + 1
        while separator_index < end and not lines[separator_index].strip():
            separator_index += 1
        if separator_index >= end:
            continue
        separator = _split_table_row(lines[separator_index])
        if separator is None or not _is_separator_row(separator):
            continue
        normalized_headers = [_normal_header(header) for header in headers]
        duplicates = sorted({header for header in normalized_headers if normalized_headers.count(header) > 1})
        if duplicates:
            raise ResearchError(f"table repeats normalized header(s): {', '.join(duplicates)}")
        rows: list[tuple[int, list[str]]] = []
        for row_index in range(separator_index + 1, end):
            cells = _split_table_row(lines[row_index])
            if cells is None:
                if lines[row_index].strip():
                    break
                continue
            if not _is_separator_row(cells):
                rows.append((row_index, cells))
        return _Table(line_index, headers, rows)
    raise ResearchError("section does not contain a Markdown table")


def _column(headers: Sequence[str], candidates: Iterable[str], contains: Iterable[str] = ()) -> int:
    normalized = [_normal_header(header) for header in headers]
    exact = {_normal_header(candidate) for candidate in candidates}
    for index, header in enumerate(normalized):
        if header in exact:
            return index
    fragments = tuple(_normal_header(fragment) for fragment in contains)
    for index, header in enumerate(normalized):
        if any(fragment in header for fragment in fragments):
            return index
    raise ResearchError(f"table is missing one of the required columns: {', '.join(candidates)}")


def _extract_link_or_text(value: str) -> str:
    match = re.search(r"\[[^\]]*\]\(([^)]+)\)", value)
    if match:
        return match.group(1).strip().strip("<>")
    return value.strip().strip("`")


@dataclasses.dataclass(frozen=True)
class RegistryEntry:
    ident: str
    status: str
    path: str
    row_index: int


class ArtifactIndex:
    """Parser/editor for the two tables in ``ARTIFACT_INDEX.md``."""

    def __init__(self, text: str) -> None:
        self.text = text
        self.lines = text.splitlines()
        self._ends_with_newline = text.endswith("\n")
        counter_start, counter_end = _section_bounds(self.lines, "Allocation counters")
        registry_start, registry_end = _section_bounds(self.lines, "Artifact registry")
        self.counter_table = _find_table(self.lines, counter_start, counter_end)
        self.registry_table = _find_table(self.lines, registry_start, registry_end)
        self.prefix_column = _column(self.counter_table.headers, ("Prefix", "Type", "Kind"))
        self.counter_column = _column(
            self.counter_table.headers,
            ("Last allocated", "Last ID", "Counter", "Next", "Next ID"),
            contains=("last allocated", "counter", "next"),
        )
        counter_header = _normal_header(self.counter_table.headers[self.counter_column])
        self.counter_is_next = counter_header.startswith("next")
        self.registry_id_column = _column(self.registry_table.headers, ("ID", "Artifact ID", "Identifier"))
        self.registry_path_column = _column(self.registry_table.headers, ("Path", "Artifact", "File"))
        try:
            self.registry_status_column = _column(self.registry_table.headers, ("Status", "Disposition"))
        except ResearchError:
            self.registry_status_column = -1

    def counters(self) -> dict[str, int]:
        values: dict[str, int] = {}
        for _, cells in self.counter_table.rows:
            if max(self.prefix_column, self.counter_column) >= len(cells):
                continue
            prefix = cells[self.prefix_column].strip().upper()
            raw = cells[self.counter_column].strip()
            if len(raw) >= 2 and raw.startswith("`") and raw.endswith("`"):
                raw = raw[1:-1].strip()
            if prefix in PREFIXES and re.fullmatch(r"\d+", raw):
                stored = int(raw)
                if not self.counter_is_next or stored >= 1:
                    values[prefix] = stored - 1 if self.counter_is_next else stored
        return values

    def registry(self) -> list[RegistryEntry]:
        entries: list[RegistryEntry] = []
        for row_index, cells in self.registry_table.rows:
            required = max(self.registry_id_column, self.registry_path_column)
            if required >= len(cells):
                continue
            ident_match = re.search(r"\b(?:RUN|DIR|CLM|ATT|REV|LIT|EXP|INB|RPT)-\d{4,}\b", cells[self.registry_id_column])
            if not ident_match:
                continue
            status = ""
            if 0 <= self.registry_status_column < len(cells):
                status = cells[self.registry_status_column].strip().casefold()
            entries.append(RegistryEntry(
                ident_match.group(0), status, _extract_link_or_text(cells[self.registry_path_column]), row_index
            ))
        return entries

    def allocate(self, prefix: str, path: str | Path, status: str = "active", title: str = "Untitled") -> tuple[str, str]:
        counters = self.counters()
        if prefix not in counters:
            raise ResearchError(f"allocation table has no numeric row for prefix {prefix}")
        number = counters[prefix] + 1
        ident = f"{prefix}-{number:04d}"
        if ident in {entry.ident for entry in self.registry()}:
            raise ResearchError(
                f"counter for {prefix} would reuse registered ID {ident}; reconcile ARTIFACT_INDEX.md before allocation"
            )

        counter_row = None
        for row_index, cells in self.counter_table.rows:
            if self.prefix_column < len(cells) and cells[self.prefix_column].strip().upper() == prefix:
                counter_row = (row_index, cells)
                break
        assert counter_row is not None
        row_index, cells = counter_row
        updated_cells = list(cells)
        updated_cells[self.counter_column] = str(number + 1 if self.counter_is_next else number)
        self.lines[row_index] = "| " + " | ".join(updated_cells) + " |"

        registry_headers = [_normal_header(header) for header in self.registry_table.headers]
        new_cells = ["" for _ in registry_headers]
        new_cells[self.registry_id_column] = ident
        path_text = path.as_posix() if isinstance(path, Path) else path
        new_cells[self.registry_path_column] = f"[{path_text}]({path_text})"
        if self.registry_status_column >= 0:
            new_cells[self.registry_status_column] = status
        for index, header in enumerate(registry_headers):
            if header in {"created", "allocated", "date"}:
                new_cells[index] = _today()
            elif header == "created in":
                new_cells[index] = "pending"
            elif header == "title":
                new_cells[index] = title
            elif header == "superseded by":
                new_cells[index] = "none"
            elif header == "kind":
                new_cells[index] = next(spec.kind for spec in ARTIFACT_SPECS.values() if spec.prefix == prefix)

        insert_at = self.registry_table.rows[-1][0] + 1 if self.registry_table.rows else self.registry_table.header_line + 2
        self.lines.insert(insert_at, "| " + " | ".join(new_cells) + " |")
        rendered = "\n".join(self.lines)
        if self._ends_with_newline:
            rendered += "\n"
        return ident, rendered


def _metadata(text: str) -> dict[str, str]:
    result: dict[str, str] = {}
    lines = text.splitlines()
    index = 0
    while index < len(lines):
        match = re.match(r"^-\s*\*\*([^*]+?):\*\*\s*(.*?)\s*$", lines[index])
        if not match:
            index += 1
            continue
        label = _normal_header(match.group(1))
        value_parts = [match.group(2).strip()]
        cursor = index + 1
        while cursor < len(lines) and (lines[cursor].startswith("  ") or lines[cursor].startswith("\t")):
            value_parts.append(lines[cursor].strip())
            cursor += 1
        result.setdefault(label, " ".join(part for part in value_parts if part).strip())
        index = cursor
    return result


def _preamble_metadata(text: str) -> dict[str, str]:
    """Parse only fixed labels between the record heading and first section."""
    cleaned = _strip_non_authoritative_examples(text)
    lines = cleaned.splitlines()
    first_heading = next((index for index, line in enumerate(lines) if re.match(r"^#{1,2}\s+", line)), None)
    if first_heading is None:
        return {}
    end = next(
        (index for index in range(first_heading + 1, len(lines)) if re.match(r"^#{1,6}\s+", lines[index])),
        len(lines),
    )
    return _metadata("\n".join(lines[first_heading + 1:end]))


def _record_metadata(text: str) -> dict[str, str]:
    """All section labels, with authoritative preamble values taking priority."""
    values = _metadata(_strip_non_authoritative_examples(text))
    values.update(_preamble_metadata(text))
    return values


def _integer_in(value: str | None) -> int | None:
    """Parse an exact non-negative integer from a fixed field/cell.

    Markdown backticks are permitted for display, but prose such as
    ``1 and 999`` and signed values are not metadata integers.  Prose packet
    bindings use their own contextual regular expressions instead.
    """
    if value is None:
        return None
    normalized = value.strip()
    if len(normalized) >= 2 and normalized.startswith("`") and normalized.endswith("`"):
        normalized = normalized[1:-1].strip()
    return int(normalized) if re.fullmatch(r"\d+", normalized) else None


def _id_in(value: str | None, prefix: str | None = None) -> str | None:
    if value is None:
        return None
    group = re.escape(prefix) if prefix else r"(?:RUN|DIR|CLM|ATT|REV|LIT|EXP|INB|RPT)"
    # A task ID such as RUN-0001-T01 is not a durable RUN artifact ID.
    for match in re.finditer(rf"\b{group}-(\d{{4,}})(?!-[A-Za-z0-9])\b", value):
        if int(match.group(1)) >= 1:
            return match.group(0)
    return None


def _linked_id_in(value: str | None, prefix: str) -> str | None:
    values = _linked_ids_in(value, prefix)
    return next(iter(values), None)


def _linked_ids_in(value: str | None, prefix: str) -> set[str]:
    values: set[str] = set()
    if not value:
        return values
    for label, destination in re.findall(r"\[([^\]]+)\]\(([^)]+)\)", value):
        ident = _id_in(label + " " + destination, prefix)
        if ident is not None:
            values.add(ident)
    return values


def _canonical_linked_ids(
    source_path: Path, value: str, prefix: str, canonical: Mapping[str, Path],
) -> set[str]:
    """Return IDs whose *label and destination* agree with canonical storage.

    This deliberately does not infer an ID from a destination.  A link such
    as ``[CLM-0001](CLM-0002.md)`` is ambiguous research provenance and must
    not satisfy an epistemic gate merely because one side happens to exist.
    """
    values: set[str] = set()
    for label, destination in re.findall(r"\[([^\]]+)\]\(([^)]+)\)", value):
        ident = _id_in(label, prefix)
        if ident is None or ident not in canonical:
            continue
        if destination.casefold().startswith(("http://", "https://")):
            continue
        file_part, separator, fragment = destination.partition("#")
        raw_path = unquote(file_part).strip("<>")
        resolved = (
            source_path.resolve(strict=False)
            if not raw_path
            else (source_path.parent / raw_path).resolve(strict=False)
        )
        if resolved != canonical[ident].resolve(strict=False):
            continue
        if ident.startswith(("DIR-", "INB-")):
            if not separator or not fragment:
                continue
            try:
                target_text = canonical[ident].read_text(encoding="utf-8")
            except OSError:
                continue
            block_match = re.search(
                rf"(?m)^##\s+{re.escape(ident)}\s+—\s+(.+?)\s*$", target_text,
            )
            if block_match is None:
                continue
            if unquote(fragment).casefold() != _heading_anchor(ident, block_match.group(1)):
                continue
        values.add(ident)
    return values


def _declared_id_links(value: str, prefix: str) -> list[tuple[str, str]]:
    """Return durable IDs declared by Markdown link labels, preserving count."""
    result: list[tuple[str, str]] = []
    for label, destination in re.findall(r"\[([^\]]+)\]\(([^)]+)\)", value or ""):
        ident = _id_in(label, prefix)
        if ident is not None:
            result.append((ident, destination))
    return result


def _exact_canonical_linked_id(
    source_path: Path, value: str, prefix: str, canonical: Mapping[str, Path],
) -> str | None:
    """Return the ID only when exactly one declared link is canonical."""
    declared = _declared_id_links(value, prefix)
    if len(declared) != 1:
        return None
    ident = declared[0][0]
    return ident if _canonical_linked_ids(source_path, value, prefix, canonical) == {ident} else None


def _canonical_link_occurrences(
    source_path: Path, value: str, ident: str, canonical: Mapping[str, Path],
) -> int:
    """Count links labeled with ``ident`` that resolve to that same artifact."""
    prefix = ident.split("-", 1)[0]
    count = 0
    for label, destination in re.findall(r"\[([^\]]+)\]\(([^)]+)\)", value or ""):
        if _id_in(label, prefix) != ident:
            continue
        if ident in _canonical_linked_ids(
            source_path, f"[{label}]({destination})", prefix, canonical,
        ):
            count += 1
    return count


def _markdown_link_paths(source_path: Path, value: str) -> set[Path]:
    targets: set[Path] = set()
    for destination in re.findall(r"\[[^\]]+\]\(([^)]+)\)", value):
        if destination.casefold().startswith(("http://", "https://")) or destination.startswith("#"):
            continue
        raw_path = unquote(destination.split("#", 1)[0]).strip("<>")
        targets.add((source_path.parent / raw_path).resolve(strict=False))
    return targets


def _bare_durable_ids(value: str) -> set[str]:
    """Find durable IDs that are not carried by a Markdown link.

    Run-local task IDs deliberately do not count as durable RUN references.
    Fenced examples and comments are non-authoritative and are removed first.
    """
    cleaned = _strip_non_authoritative_examples(value)
    cleaned = re.sub(r"\[[^\]]+\]\([^)]+\)", "", cleaned)
    values: set[str] = set()
    for match in re.finditer(
        r"\b(?:RUN|DIR|CLM|ATT|REV|LIT|EXP|INB|RPT)-(\d{4,})(?!-[A-Za-z0-9])\b",
        cleaned,
    ):
        if int(match.group(1)) >= 1:
            values.add(match.group(0))
    return values


def _check_cross_reference_links(
    root: Path, report: CheckReport, canonical: Mapping[str, Path],
) -> None:
    """Require durable cross-references to use auditable Markdown links."""
    for relative in ("PROJECT.md", "STATE.md", "OVERVIEW.md"):
        control = root / relative
        if not control.exists():
            continue
        control_text = control.read_text(encoding="utf-8")
        for heading in ROOT_REQUIRED_HEADINGS[relative]:
            bare = _bare_durable_ids(_section(control_text, heading))
            if bare:
                report.add(
                    "error", "bare-durable-cross-reference",
                    f"{relative} section `## {heading}` contains unlinked durable ID(s): {', '.join(sorted(bare))}",
                    control,
                )

    for ident, path in canonical.items():
        prefix = ident.split("-", 1)[0]
        try:
            whole_text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        text = _embedded_block(whole_text, ident) if prefix in {"DIR", "INB"} else whole_text
        # The record's canonical heading declares identity rather than a
        # cross-reference.  Every other durable-ID occurrence is a reference.
        text = re.sub(
            rf"(?m)^#{{1,2}}\s+{re.escape(ident)}(?=\s|$).*?$", "", text, count=1,
        )
        bare = _bare_durable_ids(text)
        if bare:
            report.add(
                "error", "bare-durable-cross-reference",
                f"{ident} contains unlinked durable ID(s): {', '.join(sorted(bare))}",
                path,
            )

    task_names = {"TASK.md", "OUTPUT.md", "RECEIPT.md"}
    runs = root / "runs"
    for path in _authoritative_markdown_paths(root):
        if path.name not in task_names:
            continue
        try:
            relative = path.relative_to(runs)
        except ValueError:
            continue
        if len(relative.parts) != 4 or relative.parts[1] != "tasks":
            continue
        text = path.read_text(encoding="utf-8")
        # RUN-####-T## in the task heading is run-local identity and is already
        # excluded by _bare_durable_ids; strip it for clarity nonetheless.
        text = re.sub(r"(?m)^#\s+RUN-\d{4,}-T\d{2,}.*?$", "", text, count=1)
        bare = _bare_durable_ids(text)
        if bare:
            report.add(
                "error", "bare-durable-cross-reference",
                f"task record contains unlinked durable ID(s): {', '.join(sorted(bare))}",
                path,
            )

    provenance = root / "paper/PROVENANCE.md"
    if provenance.exists():
        bare = _bare_durable_ids(provenance.read_text(encoding="utf-8"))
        if bare:
            report.add(
                "error", "bare-durable-cross-reference",
                f"paper provenance contains unlinked durable ID(s): {', '.join(sorted(bare))}",
                provenance,
            )


def _headings(text: str, level: int = 2) -> list[str]:
    marker = "#" * level
    return [match.group(1).strip() for match in re.finditer(rf"(?m)^{re.escape(marker)}\s+(.+?)\s*$", text)]


def _heading_count(text: str, heading: str, level: int = 2) -> int:
    wanted = _normal_header(heading)
    return sum(_normal_header(value) == wanted for value in _headings(text, level))


def _heading_exists(text: str, required: str) -> bool:
    normalized = {_normal_header(value) for value in _headings(text, 2)}
    wanted = _normal_header(required)
    if wanted in normalized:
        return True
    # A few wording variants remain semantically identical and should not make
    # old projects fail merely because prose was tightened.
    aliases = {
        "formal model and central definitions": {"formal model", "central definitions", "formal model and definitions"},
        "pivotal candidate and open claims": {"pivotal candidate open claims", "pivotal candidate/open claims"},
        "active and parked directions": {"active directions and high value parked directions", "active directions"},
        "task and profile receipts": {"task/profile receipts", "task receipts"},
        "proof or evidence": {"proof evidence", "evidence"},
        "independent reviews": {"review links", "reviews"},
    }
    return bool(normalized.intersection({_normal_header(item) for item in aliases.get(wanted, set())}))


def _section(text: str, heading: str) -> str:
    pattern = re.compile(rf"(?mi)^##\s+{re.escape(heading)}\s*$")
    match = pattern.search(text)
    if not match:
        return ""
    next_heading = re.search(r"(?m)^##\s+", text[match.end():])
    end = match.end() + next_heading.start() if next_heading else len(text)
    return text[match.end():end].strip()


_TEMPLATE_PROMPT_STARTS = (
    "replace ", "state ", "define ", "give ", "list ", "record ", "link ",
    "describe ", "explain ", "name ", "identify ", "map ", "highlight ",
    "confirm ", "justify ", "copy ", "summarize ", "suggest ", "use ",
    "for example", "normally ", "if ", "a theorem", "a counterexample",
    "a boundary", "the evidence", "best next action", "useful independent",
)
_TEMPLATE_PROMPT_EXACT = {
    "constraints", "budget or qualitative authorization",
    "available tools, models, or offline requirements",
    "definite | exploratory | mixed", "theorem | lemma | counterexample | impossibility | empirical observation | literature-derived proposition",
}


def _contains_template_prompt(text: str) -> bool:
    """Recognize shipped human-editing prompts without rejecting TCS notation.

    In particular, ordinary mathematical brackets such as ``[n]``, ``[0,1]``,
    and ``x[i]`` are not placeholders.  The scaffold's prompts are prose in
    brackets beginning with a small, explicit vocabulary of imperative words.
    Markdown links are ignored.
    """
    cleaned = _strip_non_authoritative_examples(text)
    if re.search(r"\{\{[A-Z][A-Z0-9_]*\}\}", cleaned):
        return True
    for match in re.finditer(r"\[([^\]\n]*(?:\n[^\]]*)?)\]", cleaned):
        if match.end() < len(cleaned) and cleaned[match.end()] == "(":
            continue
        value = re.sub(r"\s+", " ", match.group(1)).strip().casefold()
        if value in _TEMPLATE_PROMPT_EXACT or value.startswith(_TEMPLATE_PROMPT_STARTS):
            return True
    return False


def _unfinished_value(value: str, *, allow_none: bool = False) -> bool:
    # Fixed fields commonly use a sentence-like ``None.``.  Normalize only
    # terminal prose punctuation here (not punctuation within a mathematical
    # value) so that adding a full stop cannot turn an unresolved substantive
    # field into an apparently concrete one.
    normalized = value.casefold().strip(" `\t\r\n.!,:;")
    unresolved = {"", "pending", "unknown"}
    if not allow_none:
        unresolved.update(("none", "not applicable"))
    return normalized in unresolved or _contains_template_prompt(value)


def _unfinished_section(value: str) -> bool:
    return not value.strip() or _contains_template_prompt(value) or bool(
        re.search(r"(?mi)^\s*(?:[-*]\s*)?(?:pending|unknown)\s*[.!]?\s*$", value)
        or re.search(r"(?mi)(?:^|\|)\s*(?:pending|unknown)\s*(?:\||$)", value)
    )


def _section_is_explicit_none(value: str) -> bool:
    """Return true only when a section consists of an explicit no-content token."""
    normalized = re.sub(r"\s+", " ", value).casefold().strip(" `\t\r\n-*_.!,:;")
    return normalized in {"none", "not applicable"}


def _unfinished_substantive_section(value: str) -> bool:
    """Reject template/pending content and explicit ``none`` for required prose."""
    return _unfinished_section(value) or _section_is_explicit_none(value)


def _revision_note_concrete(section: str, label: str, revision: int) -> bool:
    label_pattern = r"(?:Claim revision|Revision)" if label.casefold() == "claim revision" else re.escape(label)
    match = re.search(
        rf"(?mi)^\s*[-*]\s+\*\*{label_pattern}\s+{revision}:\*\*\s*(.+?)\s*$",
        section,
    )
    return match is not None and not _unfinished_value(match.group(1))


def _digest_section(text: str, heading: str) -> str:
    normalized_text = text.replace("\r\n", "\n").replace("\r", "\n")
    match = re.search(rf"(?mi)^##\s+{re.escape(heading)}\s*$", normalized_text)
    if not match:
        section = ""
    else:
        next_heading = re.search(r"(?m)^##\s+", normalized_text[match.end():])
        end = match.end() + next_heading.start() if next_heading else len(normalized_text)
        section = normalized_text[match.end():end]
    lines = [line.rstrip() for line in section.split("\n")]
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return "\n".join(lines)


def claim_digest(text: str) -> str:
    """Return the exact digest specified in ``docs/ARTIFACTS.md``."""
    statement = _digest_section(text, "Exact statement")
    assumptions = _digest_section(text, "Assumptions, quantifiers, scope, and exceptions")
    normalized = (
        "EXACT STATEMENT\n" + statement + "\n"
        "ASSUMPTIONS, QUANTIFIERS, SCOPE, AND EXCEPTIONS\n" + assumptions
    )
    return "sha256:" + hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def evidence_digest(text: str) -> str:
    """Bind evidence plus the epistemic classification reviewed with it.

    A proof reviewed while the record is an empirical observation must not
    silently validate the same prose after it is relabeled as a theorem.  The
    relationship and limitation sections are part of claim fidelity for the
    same reason.  Statement text and formal assumptions remain independently
    bound by :func:`claim_digest`.
    """
    labels = _preamble_metadata(text)
    normalized = (
        "DEPENDENCIES\n" + _digest_section(text, "Dependencies") + "\n"
        "EVIDENCE\n" + _digest_section(text, "Evidence") + "\n"
        "PROOF OR DERIVATION\n" + _digest_section(text, "Proof or derivation") + "\n"
        "CLAIM KIND\n" + labels.get("claim kind", "").strip() + "\n"
        "EVIDENCE CLASS\n" + labels.get("evidence class", "").strip() + "\n"
        "RELATIONSHIP TO THE PROJECT QUESTION\n"
        + _digest_section(text, "Relationship to the project question") + "\n"
        "KNOWN LIMITATIONS AND OPEN ISSUES\n"
        + _digest_section(text, "Known limitations and open issues")
    )
    return "sha256:" + hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _claim_assumption_errors(text: str) -> list[str]:
    """Validate the five fixed claim-scope fields used by fresh review packets."""
    values = _metadata(_section(text, "Assumptions, quantifiers, scope, and exceptions"))
    fields: tuple[tuple[tuple[str, ...], bool], ...] = (
        (("model and domain",), False),
        (("permitted assumptions used",), True),
        (("quantifier order",), False),
        (("scope limitations", "scope restrictions"), True),
        (("exceptional cases",), True),
    )
    errors: list[str] = []
    for aliases, allow_none in fields:
        present = [(name, values[name]) for name in aliases if name in values]
        display = aliases[0]
        if len(present) != 1:
            errors.append(f"assumption field `{display}` is missing or ambiguous")
            continue
        _, value = present[0]
        if _unfinished_value(value, allow_none=allow_none):
            errors.append(f"assumption field `{display}` is unfinished")
    return errors


def _review_ready_claim_errors(text: str) -> list[str]:
    labels = _record_metadata(text)
    errors: list[str] = []
    allowed_kinds = {
        "theorem", "lemma", "counterexample", "impossibility",
        "empirical observation", "literature-derived proposition",
    }
    claim_kind = labels.get("claim kind", "").casefold().strip("` ")
    if claim_kind not in allowed_kinds:
        errors.append("Claim kind is not finalized to a supported value")
    if _unfinished_value(labels.get("evidence class", "")):
        errors.append("Evidence class is unfinished")
    for heading in (
        "Exact statement", "Assumptions, quantifiers, scope, and exceptions",
        "Relationship to the project question", "Evidence", "Proof or derivation",
    ):
        if _unfinished_substantive_section(_section(text, heading)):
            errors.append(f"`## {heading}` is unfinished")
    for heading in ("Dependencies", "Known limitations and open issues"):
        if _unfinished_section(_section(text, heading)):
            errors.append(f"`## {heading}` is unfinished")
    for field in ("primary evidence", "evidence location", "what the evidence establishes"):
        if _unfinished_value(labels.get(field, "")):
            errors.append(f"`{field}` is unfinished")
    errors.extend(_claim_assumption_errors(text))
    return errors


def _mathematical_evidence_class(value: str) -> bool:
    """Require an affirmative mathematical support class, not an absence test."""
    normalized = re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()
    return any(
        phrase in normalized
        for phrase in (
            "mathematical proof", "mathematical counterexample", "formal proof",
            "formal verification", "machine checked proof", "computer assisted proof",
            "rigorous derivation",
        )
    )


def _render_template(root: Path, kind: str, values: Mapping[str, str]) -> str:
    template_path = root / "templates" / f"{kind}.md"
    if not template_path.exists():
        raise ResearchError(f"required artifact template is missing: {template_path.relative_to(root)}")
    text = template_path.read_text(encoding="utf-8")
    for key, value in values.items():
        text = text.replace("{{" + key + "}}", value)
    # Known context-dependent placeholders are intentionally explicit rather
    # than silently fabricated.
    defaults = {
        "CLAIM_ID": "pending", "CLAIM_REVISION": "pending", "CLAIM_DIGEST": "pending",
        "EVIDENCE_REVISION": "pending", "EVIDENCE_DIGEST": "pending",
        "RUN_ID": "pending", "SOURCE_RUN": "none", "RELATED_ARTIFACTS": "none",
    }
    for key, value in defaults.items():
        text = text.replace("{{" + key + "}}", value)
    unresolved = sorted(set(re.findall(r"\{\{([A-Z][A-Z0-9_]*)\}\}", text)))
    if unresolved:
        raise ResearchError(
            f"template {template_path.relative_to(root)} has unresolved placeholders: {', '.join(unresolved)}"
        )
    return text if text.endswith("\n") else text + "\n"


def _project_revision(root: Path) -> int:
    path = root / "PROJECT.md"
    if not path.exists():
        return 0
    labels = _preamble_metadata(path.read_text(encoding="utf-8"))
    return _integer_in(labels.get("contract revision")) or 0


def _contract_accepted(root: Path) -> bool:
    path = root / "PROJECT.md"
    if not path.exists():
        return False
    labels = _preamble_metadata(path.read_text(encoding="utf-8"))
    revision = _integer_in(labels.get("contract revision")) or 0
    return revision >= 1 and labels.get("contract status", "").casefold() == "accepted"


def _contract_revision_log_errors(root: Path) -> list[str]:
    path = root / "PROJECT.md"
    if not path.exists():
        return ["PROJECT.md is missing"]
    text = path.read_text(encoding="utf-8")
    revision = _integer_in(_preamble_metadata(text).get("contract revision"))
    if revision is None:
        return ["Contract revision is not numeric"]
    lines = text.splitlines()
    try:
        start, end = _section_bounds(lines, "Revision log")
        table = _find_table(lines, start, end)
        revision_column = _column(table.headers, ("Revision",))
        date_column = _column(table.headers, ("Date",))
        decision_column = _column(table.headers, ("Human decision or change", "Decision or change"))
        affected_column = _column(table.headers, ("Affected artifacts requiring review", "Affected artifacts", "Revalidation assessment"))
    except ResearchError as error:
        return [str(error)]
    errors: list[str] = []
    rows_by_revision: dict[int, list[list[str]]] = {}
    for _, cells in table.rows:
        if revision_column >= len(cells):
            errors.append("Revision log row has no revision cell")
            continue
        row_revision = _integer_in(cells[revision_column])
        if row_revision is None:
            errors.append(f"Revision log contains a non-numeric revision `{cells[revision_column]}`")
            continue
        rows_by_revision.setdefault(row_revision, []).append(cells)
    for required_revision in range(1, revision + 1):
        count = len(rows_by_revision.get(required_revision, ()))
        if count != 1:
            errors.append(
                f"Revision log must retain exactly one row for accepted revision {required_revision}; found {count}"
            )
    for logged_revision, rows in sorted(rows_by_revision.items()):
        if logged_revision > revision:
            errors.append(f"Revision log contains future revision {logged_revision} beyond current revision {revision}")
        if len(rows) != 1:
            errors.append(f"Revision log contains {len(rows)} rows for revision {logged_revision}")
            continue
        row = rows[0]
        if max(date_column, decision_column, affected_column) >= len(row):
            errors.append(f"Revision {logged_revision} row has too few columns")
            continue
        row_date = row[date_column].strip()
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", row_date) is None:
            errors.append(f"Revision {logged_revision} has no concrete YYYY-MM-DD date")
        if _unfinished_value(row[decision_column]):
            errors.append(f"Revision {logged_revision} has no concrete human decision or change")
        if _unfinished_value(row[affected_column], allow_none=True):
            errors.append(f"Revision {logged_revision} has no affected-artifact/revalidation assessment")
    header_date = _preamble_metadata(text).get("revision date", "").strip()
    current_rows = rows_by_revision.get(revision, ())
    if header_date and len(current_rows) == 1 and date_column < len(current_rows[0]):
        current_date = current_rows[0][date_column].strip()
        if current_date != header_date:
            errors.append(f"Revision {revision} log date `{current_date}` does not match Revision date `{header_date}`")
    return errors


def _contract_mature(root: Path) -> bool:
    if not _contract_accepted(root):
        return False
    project_text = (root / "PROJECT.md").read_text(encoding="utf-8")
    if _contract_revision_log_errors(root):
        return False
    labels = _preamble_metadata(project_text)
    for label in ("project title", "research mode"):
        value = labels.get(label, "").strip()
        if _unfinished_value(value):
            return False
    substantive_project_sections = (
        "Objective and intended contribution", "Formal model", "Central definitions",
        "Scope and exclusions", "Success criteria", "Expected deliverable",
        "Operational constraints",
    )
    optional_none_project_sections = (
        "Permitted assumptions", "Prohibited shortcuts", "Relevant background",
        "Human-alignment triggers", "Initially unresolved questions",
    )
    for heading in substantive_project_sections:
        value = _section(project_text, heading).strip()
        if _unfinished_substantive_section(value):
            return False
    for heading in optional_none_project_sections:
        value = _section(project_text, heading).strip()
        if _unfinished_section(value):
            return False
    operational = _metadata(_section(project_text, "Operational constraints"))
    for label in (
        "data and privacy", "external actions", "dependencies",
        "focused agent cost envelope", "runtime constraints", "human overview cadence",
    ):
        if label not in operational or _unfinished_value(operational.get(label, ""), allow_none=True):
            return False
    state_path = root / "STATE.md"
    if not state_path.exists():
        return False
    state_text = state_path.read_text(encoding="utf-8")
    if _state_revision(root) < 1:
        return False
    if any(
        _unfinished_section(_section(state_text, heading))
        for heading in ROOT_REQUIRED_HEADINGS["STATE.md"]
    ):
        return False
    strongest = _section(state_text, "Strongest validated results")
    strongest_normalized = re.sub(r"\s+", " ", strongest).casefold().strip(" `-*\n.!:")
    if strongest_normalized != "none":
        canonical: dict[str, Path] = {}
        for artifact_path in _artifact_record_markdown_paths(root):
            for ident, _ in _canonical_artifacts(artifact_path, root):
                if ident not in canonical:
                    canonical[ident] = artifact_path
        linked_claims = _linked_claim_destinations(state_path, strongest, canonical)
        if not linked_claims or any(
            not _current_passing_review_ids(root, claim_id, canonical[claim_id], canonical)
            for claim_id in linked_claims
        ):
            return False
    next_action = _section(state_text, "Recommended next action")
    if _unfinished_substantive_section(next_action):
        return False
    for heading, fields in (
        ("Strategic review", ("last strategic review", "next strategic review trigger")),
        ("Human overview refresh", ("last overview refresh", "next overview refresh trigger")),
    ):
        values = _metadata(_section(state_text, heading))
        if any(field not in values or _unfinished_value(values.get(field, "")) for field in fields):
            return False
    normalized_state = re.sub(r"\s+", " ", state_text).casefold()
    initial_state_sentinels = (
        r"initialize and approve.*project\.md.*contract revision 1",
        r"project is uninitialized",
        r"objective, formal model, permitted assumptions, scope, and success criteria have not yet been supplied",
        r"research\.py init.*fill.*project\.md.*approve contract revision 1",
    )
    if any(re.search(pattern, normalized_state) for pattern in initial_state_sentinels):
        return False
    active_objective = _section(state_text, "Active objective")
    normalized_objective = re.sub(r"[`\[\]()]", "", active_objective).casefold()
    return (
        bool(active_objective.strip())
        and re.search(r"initialize and approve.*project\.md.*contract revision 1", normalized_objective) is None
        and not _unfinished_substantive_section(active_objective)
    )


def _state_revision(root: Path) -> int:
    path = root / "STATE.md"
    if not path.exists():
        return 0
    labels = _preamble_metadata(path.read_text(encoding="utf-8"))
    return _integer_in(labels.get("state revision")) or 0


def _publish_active_run(root: Path, ident: str, relative_path: Path) -> None:
    state_path = root / "STATE.md"
    if not state_path.exists():
        raise ResearchError("cannot publish active run because STATE.md is missing")
    text = state_path.read_text(encoding="utf-8")
    labels = _preamble_metadata(text)
    active = labels.get("active run", "none").strip().casefold()
    if active not in {"none", "pending", ""}:
        raise ResearchError(f"STATE.md already names an active run: {labels.get('active run')}")
    revision = _integer_in(labels.get("state revision"))
    if revision is None:
        raise ResearchError("STATE.md has no numeric State revision")
    replacements = (
        (r"(?m)^- \*\*State revision:\*\*\s*.*$", f"- **State revision:** {revision + 1}"),
        (r"(?m)^- \*\*Integration condition:\*\*\s*.*$", "- **Integration condition:** active run"),
        (r"(?m)^- \*\*Active run:\*\*\s*.*$", f"- **Active run:** [{ident}]({relative_path.as_posix()})"),
    )
    for pattern, replacement in replacements:
        text, count = re.subn(pattern, replacement, text, count=1)
        if count != 1:
            raise ResearchError(f"STATE.md is missing a required run-publication label for {ident}")
    _atomic_write(state_path, text)


def _heading_anchor(ident: str, title: str) -> str:
    title_slug = re.sub(r"[^a-z0-9 _-]", "", title.casefold())
    title_slug = re.sub(r"\s", "-", title_slug).strip("-")
    return f"{ident.casefold()}--{title_slug}" if title_slug else ident.casefold()


def _allocation_run_state_error(root: Path, index: ArtifactIndex) -> str | None:
    state_path = root / "STATE.md"
    state_text = state_path.read_text(encoding="utf-8")
    state = _preamble_metadata(state_text)
    condition = state.get("integration condition", "").casefold().strip("` ")
    active_value = state.get("active run", "")
    active_id = _id_in(active_value, "RUN")
    run_targets: dict[str, Path] = {}
    debt: set[str] = set()
    active_or_interrupted: set[str] = set()
    for entry in index.registry():
        if not entry.ident.startswith("RUN-") or entry.status in {"reserved", "abandoned"}:
            continue
        target = _path_from_registry(root, entry)
        if not target.exists() or not target.is_file():
            return f"cannot establish integration state of registered run {entry.ident}"
        run_targets[entry.ident] = target
        labels = _preamble_metadata(target.read_text(encoding="utf-8"))
        status = labels.get("status", "").casefold()
        integration = labels.get("integration status", "").casefold()
        if status in {"active", "interrupted"}:
            active_or_interrupted.add(entry.ident)
            debt.add(entry.ident)
        if integration in {"partially integrated"} or (status == "completed" and integration != "integrated"):
            debt.add(entry.ident)

    active_none = active_value.casefold().strip("` .") == "none"
    if not active_none:
        declared = _declared_id_links(active_value, "RUN")
        if len(declared) != 1 or active_id not in run_targets:
            return "STATE Active run is not one canonical registered RUN link"
        destination = declared[0][1]
        resolved = (state_path.parent / unquote(destination.split("#", 1)[0]).strip("<>")).resolve(strict=False)
        if resolved != run_targets[active_id].resolve(strict=False):
            return "STATE Active run link does not resolve to the named registered RUN"

    if condition == "clean":
        if debt or not active_none:
            return f"STATE says clean while run recovery/integration debt exists: {', '.join(sorted(debt)) or active_id}"
    elif condition == "active run":
        if len(active_or_interrupted) != 1 or active_id not in active_or_interrupted:
            return "STATE active-run condition does not exactly name the one active/interrupted RUN"
    elif condition == "recovery required":
        if not debt:
            return "STATE says recovery required but no registered RUN needs recovery/integration"
        if not active_none and active_id not in debt:
            return "STATE recovery condition names a RUN without recovery/integration debt"
    else:
        return f"STATE has unsupported Integration condition `{condition or 'missing'}`"
    return None


def create_artifact(
    root: Path, kind: str, title: str = "Untitled", claim_id: str | None = None,
    literature_search: bool = False,
) -> tuple[str, Path]:
    if kind not in ARTIFACT_SPECS:
        raise ResearchError(f"unknown artifact kind: {kind}")
    if kind == "review" and not claim_id:
        raise ResearchError("review allocation requires an exact target claim via --claim CLM-####")
    if not title.strip():
        raise ResearchError("artifact title must not be empty")
    if "|" in title or "{{" in title or "}}" in title or any(ord(character) < 32 for character in title):
        raise ResearchError("artifact title contains a newline, control character, table delimiter, or template token")
    if not _contract_accepted(root):
        raise ResearchError(
            "PROJECT.md must have Contract revision >= 1 and Contract status `accepted` before allocating research artifacts"
        )
    if not _contract_mature(root):
        raise ResearchError("accepted PROJECT.md/STATE.md still contains uninitialized objective, model, assumptions, scope, success criteria, or deliverable placeholders")
    state_path = root / "STATE.md"
    if not state_path.exists():
        raise ResearchError("STATE.md must exist before allocating research artifacts")
    state_labels = _preamble_metadata(state_path.read_text(encoding="utf-8"))
    state_contract_revision = _integer_in(
        state_labels.get("current contract revision") or state_labels.get("contract revision")
    )
    if state_contract_revision != _project_revision(root):
        raise ResearchError("STATE.md and PROJECT.md contract revisions must agree before allocation")
    if _integer_in(state_labels.get("state revision")) is None:
        raise ResearchError("STATE.md must have a numeric State revision before allocation")
    template_kind = "search" if kind == "literature" and literature_search else kind
    template_errors = _template_contract_errors(root, template_kind)
    if template_errors:
        raise ResearchError(
            f"templates/{template_kind}.md does not satisfy its public artifact contract: "
            + "; ".join(template_errors)
        )
    spec = ARTIFACT_SPECS[kind]
    index_path = root / "ARTIFACT_INDEX.md"
    if not index_path.exists():
        raise ResearchError("ARTIFACT_INDEX.md does not exist; initialize the project first")

    lock_path = root / ".research-id-allocation.lock"
    with _FileLock(lock_path):
        index = ArtifactIndex(index_path.read_text(encoding="utf-8"))
        run_state_error = _allocation_run_state_error(root, index)
        if run_state_error is not None:
            raise ResearchError(run_state_error)
        last = index.counters().get(spec.prefix)
        if last is None:
            raise ResearchError(f"ARTIFACT_INDEX.md has no counter for {spec.prefix}")
        matching_counter_rows = [
            cells for _, cells in index.counter_table.rows
            if index.prefix_column < len(cells) and cells[index.prefix_column].strip().upper() == spec.prefix
        ]
        if len(matching_counter_rows) != 1:
            raise ResearchError(f"ARTIFACT_INDEX.md must contain exactly one counter row for {spec.prefix}")
        registered_numbers = [
            int(entry.ident.split("-")[1]) for entry in index.registry()
            if entry.ident.startswith(spec.prefix + "-")
        ]
        registered_max = max(registered_numbers, default=0)
        if last != registered_max:
            raise ResearchError(
                f"{spec.prefix} counter is {last} but registry reaches {registered_max}; reconcile gaps/reservations before allocation"
            )
        anticipated_id = f"{spec.prefix}-{last + 1:04d}"
        relative_path = (
            Path("literature/searches") / f"{anticipated_id}.md"
            if kind == "literature" and literature_search else spec.relative_path(anticipated_id)
        )
        target = root / relative_path
        embedded = kind in {"direction", "inbox"}
        if target.exists() and not embedded:
            raise ResearchError(f"refusing to overwrite existing artifact: {relative_path}")
        if embedded and not target.exists():
            raise ResearchError(f"central ledger does not exist: {relative_path}")
        if kind == "run":
            state_path = root / "STATE.md"
            if not state_path.exists():
                raise ResearchError("STATE.md is required before opening a run")
            state_snapshot = state_path.read_text(encoding="utf-8")
            state_snapshot_labels = _preamble_metadata(state_snapshot)
            active_value = state_snapshot_labels.get("active run", "none")
            if active_value.strip().casefold() not in {"none", "pending", ""}:
                raise ResearchError(f"refusing to open a second run while STATE names {active_value}")
            if state_snapshot_labels.get("integration condition", "").casefold() != "clean":
                raise ResearchError("refusing to open a run while STATE integration condition is not `clean`")
            for entry in index.registry():
                if not entry.ident.startswith("RUN-") or entry.status in {"abandoned", "reserved"}:
                    continue
                run_target = _path_from_registry(root, entry)
                if not run_target.exists() or not run_target.is_file():
                    raise ResearchError(f"cannot establish recovery state of registered run {entry.ident}")
                run_labels = _preamble_metadata(run_target.read_text(encoding="utf-8"))
                status = run_labels.get("status", "").casefold()
                integration = run_labels.get("integration status", "").casefold()
                if status in {"active", "interrupted"} or integration != "integrated":
                    raise ResearchError(f"reconcile {entry.ident} before opening another run")

        claim_values = {
            "CLAIM_ID": "pending", "CLAIM_REVISION": "pending", "CLAIM_DIGEST": "pending",
            "EVIDENCE_REVISION": "pending", "EVIDENCE_DIGEST": "pending",
        }
        requested_review_profile = "substantive"
        if kind == "review" and claim_id is not None:
            if not re.fullmatch(r"CLM-\d{4,}", claim_id):
                raise ResearchError("--claim must be a canonical claim ID such as CLM-0001")
            claim_path = root / "research/claims" / f"{claim_id}.md"
            if not claim_path.exists() or _canonical_artifact(claim_path) != (claim_id, "CLM"):
                raise ResearchError(f"review target does not exist as a canonical claim: {claim_id}")
            if claim_id not in {entry.ident for entry in index.registry()}:
                raise ResearchError(f"review target is not registered in ARTIFACT_INDEX.md: {claim_id}")
            claim_text = claim_path.read_text(encoding="utf-8")
            claim_labels = _preamble_metadata(claim_text)
            claim_status = claim_labels.get("status", "").casefold().strip("` ")
            if claim_status not in {"candidate", "under review", "validated"}:
                raise ResearchError(
                    f"review target must be candidate, under review, or validated; {claim_id} is `{claim_status or 'missing'}`"
                )
            review_ready_errors = _review_ready_claim_errors(claim_text)
            if review_ready_errors:
                raise ResearchError(
                    f"review target {claim_id} is not review-ready: " + "; ".join(review_ready_errors)
                )
            claim_contract_revision = _integer_in(claim_labels.get("contract revision"))
            current_contract_revision = _project_revision(root)
            if claim_contract_revision != current_contract_revision:
                raise ResearchError(
                    f"review target {claim_id} records contract revision {claim_contract_revision}; "
                    f"the current project is revision {current_contract_revision}. Assess impact and update/revalidate the claim before allocating a review"
                )
            claim_revision = _integer_in(claim_labels.get("claim revision"))
            if claim_revision is None:
                raise ResearchError(f"review target has no numeric Claim revision: {claim_id}")
            evidence_revision = _integer_in(claim_labels.get("evidence revision"))
            if evidence_revision is None:
                raise ResearchError(f"review target has no numeric Evidence revision: {claim_id}")
            computed_digest = claim_digest(claim_text)
            computed_evidence_digest = evidence_digest(claim_text)
            recorded_digest = claim_labels.get("statement digest", "").casefold()
            recorded_evidence_digest = claim_labels.get("evidence digest", "").casefold()
            requested_review_profile = claim_labels.get("required review profile", "").casefold().strip("` ")
            if requested_review_profile not in {"substantive", "deep", "pivotal"}:
                raise ResearchError(f"review target has invalid Required review profile: {requested_review_profile}")
            claim_changed = False
            if recorded_digest in {"", "pending"}:
                claim_text, replacements = re.subn(
                    r"(?m)^- \*\*Statement digest:\*\*\s*.*$",
                    f"- **Statement digest:** {computed_digest}", claim_text, count=1,
                )
                if replacements != 1:
                    raise ResearchError(f"review target lacks the fixed Statement digest label: {claim_id}")
                claim_changed = True
            elif recorded_digest != computed_digest:
                raise ResearchError(
                    f"review target's recorded Statement digest is stale; expected {computed_digest}"
                )
            if recorded_evidence_digest in {"", "pending"}:
                claim_text, replacements = re.subn(
                    r"(?m)^- \*\*Evidence digest:\*\*\s*.*$",
                    f"- **Evidence digest:** {computed_evidence_digest}", claim_text, count=1,
                )
                if replacements != 1:
                    raise ResearchError(f"review target lacks the fixed Evidence digest label: {claim_id}")
                claim_changed = True
            elif recorded_evidence_digest != computed_evidence_digest:
                raise ResearchError(
                    f"review target's recorded Evidence digest is stale; expected {computed_evidence_digest}"
                )
            if claim_changed:
                _atomic_write(claim_path, claim_text)
            claim_values = {
                "CLAIM_ID": claim_id,
                "CLAIM_REVISION": str(claim_revision),
                "CLAIM_DIGEST": computed_digest,
                "EVIDENCE_REVISION": str(evidence_revision),
                "EVIDENCE_DIGEST": computed_evidence_digest,
            }

        values = {
            "ID": anticipated_id,
            "PREFIX": spec.prefix,
            "NUMBER": str(last + 1),
            "TITLE": title,
            "DATE": _today(),
            "TIMESTAMP": _now(),
            "CONTRACT_REVISION": str(_project_revision(root)),
            "STATE_REVISION": str(_state_revision(root)),
            **claim_values,
        }
        content = _render_template(root, "search" if literature_search else kind, values)
        if kind == "review":
            content, replaced_profile = re.subn(
                r"(?m)^- \*\*Requested profile:\*\*\s*.*$",
                f"- **Requested profile:** {requested_review_profile}", content, count=1,
            )
            if replaced_profile != 1:
                raise ResearchError("review template lacks fixed Requested profile label")
        if kind == "review" and claim_id is None:
            content = content.replace("[pending](../claims/pending.md)", "pending")
        if kind == "run":
            content, authority_count = re.subn(
                r"(?m)^- \*\*Integration authority:\*\*.*$",
                "- **Integration authority:** current broad-context integration session",
                content, count=1,
            )
            content, objective_count = re.subn(
                r"(?ms)^## Objective\s*\n.*?(?=^## |\Z)",
                f"## Objective\n\n{title}\n\n",
                content, count=1,
            )
            content = content.replace(
                "- **Active directions:** [Link only those needed for this run.]",
                "- **Active directions:** none",
                1,
            )
            if authority_count != 1 or objective_count != 1:
                raise ResearchError("run template lacks the fixed integration-authority or objective contract")
        rendered_contract_errors = _rendered_template_contract_errors(
            "search" if literature_search else kind, content, anticipated_id,
        )
        if rendered_contract_errors:
            raise ResearchError(
                f"rendered templates/{'search' if literature_search else kind}.md does not satisfy its public artifact contract: "
                + "; ".join(rendered_contract_errors)
            )
        registry_destination = relative_path.as_posix()
        if embedded:
            registry_destination += "#" + _heading_anchor(anticipated_id, title)
        initial_status = {
            "run": "active", "direction": "parked", "claim": "draft", "attempt": "active",
            "review": "draft", "literature": "draft", "experiment": "planned", "inbox": "new",
            "report": "draft",
        }[kind]
        ident, updated_index = index.allocate(
            spec.prefix, registry_destination, status=initial_status, title=title
        )
        if ident != anticipated_id:
            raise ResearchError("allocation changed unexpectedly while holding the allocation lock")

        # Publish the artifact before its registry row.  A crash can therefore
        # leave an unregistered file (detected by `check`), never a registry
        # entry that falsely claims an artifact exists.
        if embedded:
            existing = target.read_text(encoding="utf-8")
            if re.search(rf"(?m)^##\s+{re.escape(ident)}\b", existing):
                raise ResearchError(f"central ledger already contains {ident}")
            combined = existing.rstrip() + "\n\n" + content.lstrip()
            _atomic_write(target, combined)
        else:
            _atomic_write(target, content)
        if kind == "run":
            (target.parent / "tasks").mkdir(parents=True, exist_ok=True)
        elif kind == "experiment":
            for directory in ("code", "inputs", "executions"):
                (target.parent / directory).mkdir(parents=True, exist_ok=True)
        try:
            _atomic_write(index_path, updated_index)
        except Exception:
            # Preserve the artifact as recoverable evidence.  The validator
            # reports it as unregistered; never delete material automatically.
            raise ResearchError(
                f"created {relative_path}, but failed to publish its registry entry; run `check` and reconcile it"
            )
        if kind == "run":
            _publish_active_run(root, ident, relative_path)
    return ident, relative_path


def _minimal_index() -> str:
    counter_rows = "\n".join(f"| {prefix} | {ARTIFACT_SPECS[next(k for k, s in ARTIFACT_SPECS.items() if s.prefix == prefix)].kind} | 0 |" for prefix in PREFIXES)
    return (
        "# Artifact index\n\n"
        "## Allocation counters\n\n"
        "| Prefix | Meaning | Last allocated |\n| --- | --- | ---: |\n"
        f"{counter_rows}\n\n"
        "## Artifact registry\n\n"
        "| ID | Kind | Status | Path | Created |\n| --- | --- | --- | --- | --- |\n"
    )


def initialize(root: Path) -> list[Path]:
    """Create only missing structural files/directories; never overwrite."""
    root.mkdir(parents=True, exist_ok=True)
    index_path = root / "ARTIFACT_INDEX.md"
    if index_path.exists():
        try:
            index = ArtifactIndex(index_path.read_text(encoding="utf-8"))
            if any(index.counters().values()) or index.registry():
                raise ResearchError("project already contains allocated artifacts; refusing to reinitialize")
        except ResearchError as error:
            if "already contains" in str(error):
                raise
            raise ResearchError(f"existing ARTIFACT_INDEX.md is not initializable: {error}") from error

    directories = (
        "templates", "research/directions", "research/claims", "research/attempts", "research/reviews",
        "literature/notes", "literature/searches", "experiments", "runs", "reports",
        "paper/sections", "paper/figures", "runtime", ".codex", ".claude", "tests/fixtures",
    )
    created: list[Path] = []
    for relative in directories:
        path = root / relative
        if not path.exists():
            path.mkdir(parents=True, exist_ok=True)
            created.append(path)
    if not index_path.exists():
        _atomic_write(index_path, _minimal_index())
        created.append(index_path)
    return created


def _walk_project_files(root: Path, *, prune: Iterable[str] = ()) -> Iterator[Path]:
    """Walk without ever descending into version-control or cache metadata."""
    pruned = {".git", "__pycache__", ".mypy_cache", ".pytest_cache", *prune}
    for directory, child_directories, filenames in os.walk(root, topdown=True, followlinks=False):
        child_directories[:] = [name for name in child_directories if name not in pruned]
        base = Path(directory)
        for filename in filenames:
            yield base / filename


def _artifact_record_markdown_paths(root: Path) -> Iterator[Path]:
    """Yield only Markdown eligible to declare durable artifact identity.

    Experiment inputs, generated outputs, and arbitrary source-data Markdown
    are untrusted evidence, not research records.  In particular, an input
    file whose first line resembles ``# CLM-...`` must never become a claim.
    """
    selected: set[Path] = set()
    for relative in ("research/DIRECTIONS.md", "research/INBOX.md"):
        path = root / relative
        if path.is_file():
            selected.add(path)

    for directory in (
        root / "research/claims", root / "research/attempts",
        root / "research/reviews", root / "research/directions",
        root / "literature/notes", root / "literature/searches", root / "reports",
    ):
        if not directory.exists() or directory.is_symlink():
            continue
        for path in _walk_project_files(directory):
            if path.suffix.casefold() == ".md":
                selected.add(path)

    experiments = root / "experiments"
    if experiments.exists() and not experiments.is_symlink():
        for path in _walk_project_files(experiments):
            try:
                relative = path.relative_to(experiments)
            except ValueError:
                continue
            parts = relative.parts
            if (
                len(parts) == 2
                and re.fullmatch(r"EXP-\d{4,}", parts[0])
                and parts[1] == "README.md"
            ) or (
                len(parts) == 4
                and re.fullmatch(r"EXP-\d{4,}", parts[0])
                and parts[1] == "executions"
                and re.fullmatch(r"EXP-\d{4,}-E\d{3,}", parts[2])
                and parts[3] == "COMPLETED.md"
            ):
                selected.add(path)

    runs = root / "runs"
    if runs.exists() and not runs.is_symlink():
        for path in _walk_project_files(runs):
            try:
                relative = path.relative_to(runs)
            except ValueError:
                continue
            parts = relative.parts
            if (
                len(parts) == 2
                and re.fullmatch(r"RUN-\d{4,}", parts[0])
                and parts[1] == "RUN.md"
            ):
                selected.add(path)
            if (
                len(parts) == 4
                and re.fullmatch(r"RUN-\d{4,}", parts[0])
                and parts[1] == "tasks"
                and re.fullmatch(r"T\d{2,}", parts[2])
                and parts[3] in {"TASK.md", "OUTPUT.md", "RECEIPT.md"}
            ):
                selected.add(path)

    yield from sorted(selected, key=lambda path: path.as_posix())


def _authoritative_markdown_paths(root: Path) -> Iterator[Path]:
    """Yield trusted Markdown for UTF-8 and relative-link validation."""
    selected = set(_artifact_record_markdown_paths(root))
    for relative in (
        "AGENTS.md", "CLAUDE.md", "README.md", "PROJECT.md", "STATE.md",
        "OVERVIEW.md", "ARTIFACT_INDEX.md", "paper/PROVENANCE.md",
        "runtime/PROFILES.md", ".codex/README.md", ".claude/README.md",
        "templates/README.md", "experiments/README.md", "literature/README.md",
        "literature/notes/README.md", "literature/searches/README.md",
        "research/README.md", "research/attempts/README.md",
        "research/claims/README.md", "research/directions/README.md",
        "research/reviews/README.md", "runs/README.md", "reports/README.md",
        "paper/figures/README.md", "tools/guards/README.md",
    ):
        path = root / relative
        if path.is_file():
            selected.add(path)
    docs = root / "docs"
    if docs.exists() and not docs.is_symlink():
        selected.update(
            path for path in _walk_project_files(docs)
            if path.suffix.casefold() == ".md"
        )
    for inventory in ADAPTER_INVENTORY.values():
        for relative in inventory:
            path = root / relative
            if path.suffix.casefold() == ".md" and path.is_file():
                selected.add(path)
    yield from sorted(selected, key=lambda path: path.as_posix())


def _iter_markdown(root: Path) -> Iterator[Path]:
    yield from _authoritative_markdown_paths(root)


def _check_authoritative_utf8(root: Path, report: CheckReport) -> None:
    paths = set(_authoritative_markdown_paths(root))
    paths.update(path for path in (root / "templates").glob("*.md") if path.is_file())
    for relative in ROOT_REQUIRED_HEADINGS:
        path = root / relative
        if path.is_file():
            paths.add(path)
    paper = root / "paper"
    if paper.exists() and not paper.is_symlink():
        paths.update(
            path for path in _walk_project_files(paper)
            if path.suffix.casefold() == ".tex"
        )
    bibliography = root / "literature/references.bib"
    if bibliography.is_file():
        paths.add(bibliography)
    for path in sorted(paths, key=lambda value: value.as_posix()):
        unsafe = _symlink_component(root, path.relative_to(root))
        if unsafe is not None:
            report.add(
                "error", "symlinked-authoritative-record",
                f"authoritative record `{path.relative_to(root).as_posix()}` traverses symlink `{unsafe.relative_to(root).as_posix()}`",
                unsafe,
            )
            continue
        try:
            metadata = path.lstat()
            if not stat.S_ISREG(metadata.st_mode):
                report.add(
                    "error", "authoritative-record-not-regular",
                    "authoritative record must be a regular file",
                    path,
                )
                continue
            if metadata.st_nlink != 1:
                report.add(
                    "error", "hardlinked-authoritative-record",
                    f"authoritative record has {metadata.st_nlink} filesystem links; exactly one is required",
                    path,
                )
            path.read_text(encoding="utf-8")
        except OSError as error:
            report.add(
                "error", "authoritative-record-unreadable",
                f"authoritative record cannot be read: {error}",
                path,
            )
        except UnicodeDecodeError as error:
            report.add(
                "error", "authoritative-text-not-utf8",
                f"authoritative text must be valid UTF-8: {error}",
                path,
            )


def _strip_non_authoritative_examples(text: str) -> str:
    text = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
    text = re.sub(r"~~~.*?~~~", "", text, flags=re.DOTALL)
    text = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)
    return text


def _canonical_artifact(path: Path) -> tuple[str, str] | None:
    try:
        first = path.read_text(encoding="utf-8").splitlines()[0]
    except (OSError, UnicodeDecodeError, IndexError):
        return None
    match = re.match(r"^#\s+((RUN|DIR|CLM|ATT|REV|LIT|EXP|INB|RPT)-\d{4,})(?=\s|$)", first)
    return (match.group(1), match.group(2)) if match else None


def _canonical_artifacts(path: Path, root: Path) -> list[tuple[str, str]]:
    dedicated = _canonical_artifact(path)
    if dedicated is not None:
        return [dedicated]
    try:
        relative = path.relative_to(root).as_posix()
    except ValueError:
        return []
    allowed = "DIR" if relative == "research/DIRECTIONS.md" else "INB" if relative == "research/INBOX.md" else None
    if allowed is None:
        return []
    text = _strip_non_authoritative_examples(path.read_text(encoding="utf-8"))
    return [
        (match.group(1), allowed)
        for match in re.finditer(rf"(?m)^##\s+(({allowed})-\d{{4,}})\b", text)
    ]


def _embedded_block(text: str, ident: str) -> str:
    match = re.search(rf"(?m)^##\s+{re.escape(ident)}\b.*$", text)
    if not match:
        return ""
    next_item = re.search(r"(?m)^##\s+(?:DIR|INB)-\d{4,}\b", text[match.end():])
    end = match.end() + next_item.start() if next_item else len(text)
    return text[match.start():end]


def _template_contract_errors(root: Path, kind: str) -> list[str]:
    """Return structural errors for one shipped public-flow template."""
    path = root / "templates" / f"{kind}.md"
    if not path.exists():
        return [f"required template is missing: templates/{kind}.md"]
    prefix_by_kind = {
        "run": "RUN", "direction": "DIR", "claim": "CLM", "attempt": "ATT",
        "review": "REV", "literature": "LIT", "search": "LIT", "experiment": "EXP", "execution": "EXP",
        "inbox": "INB", "report": "RPT",
    }
    values = {
        "ID": f"{prefix_by_kind.get(kind, 'RUN')}-9999",
        "PREFIX": prefix_by_kind.get(kind, "RUN"), "NUMBER": "9999",
        "TITLE": "Template schema canary", "DATE": "2099-01-01", "TIMESTAMP": "2099-01-01T00:00:00Z",
        "CONTRACT_REVISION": "1", "STATE_REVISION": "1", "CLAIM_ID": "CLM-9998",
        "CLAIM_REVISION": "1", "CLAIM_DIGEST": "sha256:" + "0" * 64,
        "EVIDENCE_REVISION": "1", "EVIDENCE_DIGEST": "sha256:" + "1" * 64,
        "RUN_ID": "RUN-9999", "SOURCE_RUN": "none", "RELATED_ARTIFACTS": "none",
    }
    try:
        rendered = _render_template(root, kind, values)
    except (ResearchError, OSError) as error:
        return [str(error)]
    task_filename = {"task": "TASK.md", "output": "OUTPUT.md", "receipt": "RECEIPT.md"}.get(kind)
    if task_filename:
        rendered = rendered.replace("RUN-####-T##", "RUN-9999-T01").replace("RUN-####", "RUN-9999")
        ident = "RUN-9999-T01"
    elif kind == "execution":
        rendered = rendered.replace("EXP-####-E###", "EXP-9999-E001")
        ident = "EXP-9999-E001"
    else:
        ident = f"{prefix_by_kind[kind]}-9999"
    return _rendered_template_contract_errors(kind, rendered, ident)


def _rendered_template_contract_errors(kind: str, rendered: str, ident: str) -> list[str]:
    prefix_by_kind = {
        "run": "RUN", "direction": "DIR", "claim": "CLM", "attempt": "ATT",
        "review": "REV", "literature": "LIT", "search": "LIT", "experiment": "EXP", "execution": "EXP",
        "inbox": "INB", "report": "RPT",
    }
    task_filename = {"task": "TASK.md", "output": "OUTPUT.md", "receipt": "RECEIPT.md"}.get(kind)
    if task_filename:
        labels_required, headings_required = TASK_FILE_CONTRACTS[task_filename]
        expected_heading = rf"^#\s+{re.escape(ident)}(?=\s|$)"
    else:
        prefix = prefix_by_kind[kind]
        expected_heading = rf"^{'##' if kind in {'direction', 'inbox'} else '#'}\s+{re.escape(ident)}(?=\s|$)"
        if kind == "direction":
            labels_required = (
                "Activity", "Assessment", "Contract revision", "Created in", "Last updated in",
                "Research question", "Why it matters", "Supporting evidence", "Opposing evidence",
                "Current obstacle", "Next discriminating action", "Stop condition", "Revival condition",
                "Last strategic review", "Linked artifacts", "Expanded record",
            )
            headings_required = ()
        elif kind == "inbox":
            labels_required = (
                "Kind", "Disposition", "Uncertainty class", "Contract revision", "Source",
                "Finding or question", "Why it matters", "Related direction or claim", "Provisional assumption",
                "Dependent artifacts", "Safe continuation horizon", "Affected branch", "Human answer",
                "Triage reason", "Revisit condition", "Last triaged in",
            )
            headings_required = ()
        elif kind == "search":
            labels_required = (
                "Status", "Record kind", "Contract revision", "Search dates", "Created in",
                "Last updated in", "Related artifacts", "Supersedes",
            )
            headings_required = (
                "Research questions informed", "Search locations", "Exact queries and filters",
                "Selection and exclusion logic", "Sources retained", "Findings",
                "Coverage limits and known gaps", "Recommended follow-up",
            )
        elif kind == "execution":
            labels_required = (
                "Execution ID", "Completed", "Command/config", "Inputs", "Outputs", "Output digest", "Result",
            )
            headings_required = ()
        else:
            labels_required = ARTIFACT_REQUIRED_LABELS[prefix]
            headings_required = ARTIFACT_REQUIRED_HEADINGS[prefix]
    errors: list[str] = []
    first = rendered.splitlines()[0] if rendered.splitlines() else ""
    if re.match(expected_heading, first) is None:
        errors.append("template does not render the required canonical ID heading")
    top_headings = re.findall(
        r"(?m)^#(?!#)\s+(.+?)\s*$", _strip_non_authoritative_examples(rendered),
    )
    expected_top_count = 0 if kind in {"direction", "inbox"} else 1
    if len(top_headings) != expected_top_count:
        errors.append(
            f"template must render exactly {expected_top_count} top-level heading(s); found {len(top_headings)}"
        )
    header_labels = _preamble_metadata(rendered)
    for label in labels_required:
        if _normal_header(label) not in header_labels:
            errors.append(f"template is missing fixed preamble label `{label}`")
    for heading in headings_required:
        if not _heading_exists(rendered, heading):
            errors.append(f"template is missing fixed heading `## {heading}`")
        elif _heading_count(rendered, heading) != 1:
            errors.append(f"template repeats fixed heading `## {heading}`")
    label_names = [
        _normal_header(value)
        for value in re.findall(r"(?m)^-\s*\*\*([^*]+?):\*\*", _strip_non_authoritative_examples(rendered))
    ]
    for duplicate in sorted({label for label in label_names if label_names.count(label) > 1}):
        errors.append(f"template repeats fixed bold label `{duplicate}`")
    return errors


def _path_from_registry(root: Path, entry: RegistryEntry) -> Path:
    raw = unquote(entry.path.split("#", 1)[0]).strip().strip("<>")
    return (root / raw).resolve(strict=False)


def _canonical_artifact_path(root: Path, ident: str, path: Path) -> bool:
    prefix = ident.split("-", 1)[0]
    relative = path.relative_to(root).as_posix()
    expected = {
        "RUN": f"runs/{ident}/RUN.md",
        "DIR": "research/DIRECTIONS.md",
        "CLM": f"research/claims/{ident}.md",
        "ATT": f"research/attempts/{ident}.md",
        "REV": f"research/reviews/{ident}.md",
        "EXP": f"experiments/{ident}/README.md",
        "INB": "research/INBOX.md",
        "RPT": f"reports/{ident}.md",
    }
    if prefix == "LIT":
        labels = _preamble_metadata(path.read_text(encoding="utf-8"))
        directory = "searches" if labels.get("record kind", "").casefold() == "consequential literature search" else "notes"
        return relative == f"literature/{directory}/{ident}.md"
    return relative == expected.get(prefix)


def _markdown_anchors(text: str) -> set[str]:
    anchors = set(re.findall(r"(?i)<a\s+(?:name|id)=[\"']([^\"']+)[\"']", text))
    for heading in re.findall(r"(?m)^#{1,6}\s+(.+?)\s*#*\s*$", _strip_non_authoritative_examples(text)):
        plain = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", heading)
        plain = re.sub(r"[`*_~]", "", plain).casefold()
        plain = re.sub(r"[^a-z0-9 _-]", "", plain)
        anchors.add(re.sub(r"\s", "-", plain).strip("-"))
    return anchors


def _symlink_component(root: Path, relative: Path) -> Path | None:
    """Return the first symlink in a project-relative safety path.

    Runtime and control records are selected by their lexical project paths.
    Following even an in-project symlink would let a different file inherit
    that authority, while an escaping symlink could move reads or writes
    outside the workspace.  Check every existing component without resolving
    it first; broken links are safety-relevant too.
    """
    current = root
    for component in relative.parts:
        if component in {"", "."}:
            continue
        if component == "..":
            return current / component
        current = current / component
        try:
            if current.is_symlink():
                return current
        except OSError:
            return current
    return None


def _runtime_safety_paths(root: Path) -> set[Path]:
    paths = {Path(value) for value in CONTROL_SAFETY_PATHS}
    for inventory in ADAPTER_INVENTORY.values():
        paths.update(Path(value) for value in inventory)
    paths.update(Path("tools/guards") / name for name in GUARD_FILENAMES)

    # Any additional guard entry is executable policy surface too.  Walk only
    # after checking the lexical guard directory itself and never follow links.
    guards = root / "tools/guards"
    if guards.exists() and not guards.is_symlink():
        for directory, child_directories, filenames in os.walk(guards, topdown=True, followlinks=False):
            base = Path(directory)
            for name in child_directories:
                paths.add((base / name).relative_to(root))
            for name in filenames:
                paths.add((base / name).relative_to(root))
    return paths


def _check_runtime_safety_paths(root: Path, report: CheckReport) -> None:
    for relative in sorted(_runtime_safety_paths(root), key=lambda value: value.as_posix()):
        unsafe = _symlink_component(root, relative)
        if unsafe is not None:
            report.add(
                "error", "symlinked-safety-surface",
                f"authoritative control/runtime safety path `{relative.as_posix()}` traverses symlink `{unsafe.relative_to(root).as_posix()}`",
                unsafe,
            )
            continue
        path = root / relative
        try:
            metadata = path.lstat()
        except OSError:
            continue  # Missing inventory is reported by structural checks.
        if stat.S_ISDIR(metadata.st_mode):
            continue
        if not stat.S_ISREG(metadata.st_mode):
            report.add(
                "error", "unsafe-safety-surface-type",
                f"authoritative control/runtime safety path `{relative.as_posix()}` is not a regular file",
                path,
            )
        elif metadata.st_nlink != 1:
            report.add(
                "error", "hardlinked-safety-surface",
                f"authoritative control/runtime safety file `{relative.as_posix()}` has {metadata.st_nlink} filesystem links; exactly one is required",
                path,
            )


def _check_structure(root: Path, report: CheckReport) -> None:
    _check_runtime_safety_paths(root, report)
    required_files = (
        "README.md", "AGENTS.md", "CLAUDE.md", "PROJECT.md", "STATE.md", "OVERVIEW.md",
        "ARTIFACT_INDEX.md", "research/DIRECTIONS.md", "research/INBOX.md",
        "literature/references.bib", "paper/main.tex", "paper/PROVENANCE.md", "runtime/PROFILES.md",
        "tools/research.py",
    )
    for relative in required_files:
        path = root / relative
        if not path.exists():
            report.add("error", "missing-file", f"required file is missing: {relative}", path)
    agents_surface = root / ".agents"
    if agents_surface.exists() or agents_surface.is_symlink():
        report.add(
            "error", "unexpected-runtime-instruction-surface",
            "unsupported .agents/ project instruction/skill surface exists outside the closed adapter inventory",
            agents_surface,
        )
    instruction_names = {"agents.md", "agents.override.md", "claude.md", "claude.local.md"}
    allowed_instruction_paths = {"AGENTS.md", "CLAUDE.md"}
    for candidate in _walk_project_files(root):
        try:
            relative = candidate.relative_to(root).as_posix()
        except ValueError:
            continue
        if not candidate.is_file():
            continue
        if candidate.name.casefold() in instruction_names and relative not in allowed_instruction_paths:
            report.add(
                "error", "unexpected-instruction-override",
                f"unexpected runtime-native instruction override/local file: {relative}",
                candidate,
            )
        if candidate.name == ".mcp.json":
            report.add(
                "error", "unexpected-project-mcp-config",
                f"unexpected project MCP configuration: {relative}; project MCP servers require explicit human/runtime review",
                candidate,
            )
        if relative.casefold() == ".claude/settings.local.json":
            report.add(
                "error", "unexpected-runtime-local-override",
                "unexpected higher-precedence .claude/settings.local.json; local permission/hook overrides are not supported by this template",
                candidate,
            )
    for kind in (*ARTIFACT_SPECS, "search", "execution", "task", "output", "receipt"):
        template = root / "templates" / f"{kind}.md"
        if not template.exists():
            report.add("error", "missing-template", f"required template is missing: templates/{kind}.md", template)
            continue
        for error in _template_contract_errors(root, kind):
            report.add("error", "invalid-template-contract", error, template)
    for relative, headings in ROOT_REQUIRED_HEADINGS.items():
        path = root / relative
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        header_labels = _preamble_metadata(text)
        label_names = [
            _normal_header(value)
            for value in re.findall(r"(?m)^-\s*\*\*([^*]+?):\*\*", _strip_non_authoritative_examples(text))
        ]
        for duplicate in sorted({label for label in label_names if label_names.count(label) > 1}):
            report.add("error", "duplicate-control-label", f"control record repeats bold label `{duplicate}`", path)
        for heading in headings:
            if not _heading_exists(text, heading):
                report.add("error", "missing-heading", f"missing fixed heading `## {heading}`", path)
            elif _heading_count(text, heading) != 1:
                report.add("error", "duplicate-control-heading", f"fixed heading `## {heading}` appears more than once", path)
        for label in ROOT_REQUIRED_LABELS.get(relative, ()):
            normalized = _normal_header(label)
            if normalized not in header_labels:
                report.add("error", "missing-control-label", f"missing fixed preamble label `{label}`", path)
            elif not header_labels[normalized].strip():
                report.add("error", "blank-control-label", f"fixed preamble label `{label}` is blank", path)
        if relative == "PROJECT.md" and header_labels.get("contract status", "").casefold() == "accepted":
            mode = header_labels.get("research mode", "").casefold().strip("` ")
            if mode not in {"definite", "exploratory", "mixed"}:
                report.add("error", "invalid-research-mode", f"accepted contract has invalid Research mode `{mode}`", path)
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}", header_labels.get("revision date", "").strip()) is None:
                report.add("error", "invalid-contract-revision-date", "accepted contract needs a concrete YYYY-MM-DD Revision date", path)
            for heading in (
                "Objective and intended contribution", "Formal model", "Central definitions",
                "Permitted assumptions", "Prohibited shortcuts", "Scope and exclusions",
                "Relevant background", "Success criteria", "Expected deliverable",
                "Human-alignment triggers", "Initially unresolved questions",
            ):
                if _unfinished_section(_section(text, heading)):
                    report.add(
                        "error", "accepted-project-section-incomplete",
                        f"accepted contract leaves `## {heading}` unfinished",
                        path,
                    )
            operational = _metadata(_section(text, "Operational constraints"))
            for label in (
                "Data and privacy", "External actions", "Dependencies",
                "Focused-agent cost envelope", "Runtime constraints", "Human overview cadence",
            ):
                normalized = _normal_header(label)
                if normalized not in operational:
                    report.add(
                        "error", "missing-operational-constraint",
                        f"accepted contract Operational constraints is missing fixed label `{label}`",
                        path,
                    )
                elif _unfinished_value(operational[normalized], allow_none=True):
                    report.add(
                        "error", "unfinished-operational-constraint",
                        f"accepted contract leaves operational constraint `{label}` unfinished",
                        path,
                    )
        if relative == "PROJECT.md":
            contract_status = header_labels.get("contract status", "").casefold().strip("` ")
            if contract_status not in {"uninitialized", "accepted"}:
                report.add("error", "invalid-contract-status", f"invalid Contract status `{contract_status}`", path)
        if relative == "STATE.md":
            condition = header_labels.get("integration condition", "").casefold().strip("` ")
            if condition not in {"clean", "active run", "recovery required"}:
                report.add("error", "invalid-integration-condition", f"invalid STATE integration condition `{condition}`", path)


def _check_links(root: Path, report: CheckReport, canonical: Mapping[str, Path]) -> None:
    link_pattern = re.compile(r"(?<!!)\[([^\]]*)\]\(([^)]+)\)")
    ignored_schemes = ("http://", "https://", "mailto:", "doi:", "ftp://", "data:")
    for path in _iter_markdown(root):
        text = _strip_non_authoritative_examples(path.read_text(encoding="utf-8"))
        for label, destination in link_pattern.findall(text):
            destination = destination.strip().strip("<>")
            if not destination or destination.casefold().startswith(ignored_schemes):
                # A project-artifact ID may never use an external destination.
                declared = re.findall(r"\b(?:RUN|DIR|CLM|ATT|REV|LIT|EXP|INB|RPT)-\d{4,}(?!-[A-Za-z0-9])\b", label)
                for ident in declared:
                    report.add(
                        "error", "canonical-link-target-mismatch",
                        f"link label declares {ident} but its destination is not that canonical project artifact",
                        path,
                    )
                continue
            if destination.startswith("#"):
                fragment = unquote(destination[1:]).casefold()
                if fragment and fragment not in _markdown_anchors(text):
                    report.add("error", "broken-anchor", f"same-file link fragment does not exist: #{fragment}", path)
                for ident in re.findall(r"\b(?:RUN|DIR|CLM|ATT|REV|LIT|EXP|INB|RPT)-\d{4,}(?!-[A-Za-z0-9])\b", label):
                    prefix = ident.split("-", 1)[0]
                    if ident not in canonical or ident not in _canonical_linked_ids(
                        path, f"[{label}]({destination})", prefix, canonical,
                    ):
                        report.add(
                            "error", "canonical-link-target-mismatch",
                            f"link label declares {ident}, but its fragment is not the canonical entry for that same ID",
                            path,
                        )
                continue
            if "{{" in destination or "<example" in destination.casefold() or destination.casefold().startswith("example:"):
                continue
            # Remove an optional Markdown title after a whitespace boundary.
            destination = re.split(r"\s+[\"']", destination, maxsplit=1)[0]
            file_part = unquote(destination.split("#", 1)[0])
            if not file_part:
                continue
            resolved = (path.parent / file_part).resolve(strict=False)
            try:
                resolved.relative_to(root.resolve())
            except ValueError:
                report.add("error", "link-outside-root", f"relative link escapes the project: {destination}", path)
                continue
            if not resolved.exists():
                report.add("error", "broken-link", f"link target does not exist: {destination}", path)
            elif "#" in destination and resolved.is_file() and resolved.suffix.casefold() == ".md":
                fragment = unquote(destination.split("#", 1)[1]).casefold()
                if fragment and fragment not in _markdown_anchors(resolved.read_text(encoding="utf-8")):
                    report.add("error", "broken-anchor", f"link fragment does not exist: #{fragment}", path)
            for ident in re.findall(r"\b(?:RUN|DIR|CLM|ATT|REV|LIT|EXP|INB|RPT)-\d{4,}(?!-[A-Za-z0-9])\b", label):
                prefix = ident.split("-", 1)[0]
                single_link = f"[{label}]({destination})"
                if ident not in canonical or ident not in _canonical_linked_ids(path, single_link, prefix, canonical):
                    report.add(
                        "error", "canonical-link-target-mismatch",
                        f"link label declares {ident}, but its destination is not the canonical artifact/entry for that same ID",
                        path,
                    )


def _load_index(root: Path, report: CheckReport) -> ArtifactIndex | None:
    path = root / "ARTIFACT_INDEX.md"
    if not path.exists():
        return None
    try:
        return ArtifactIndex(path.read_text(encoding="utf-8"))
    except ResearchError as error:
        report.add("error", "invalid-index", str(error), path)
        return None


def _check_ids(root: Path, report: CheckReport, index: ArtifactIndex | None) -> dict[str, Path]:
    canonical: dict[str, Path] = {}
    for path in _artifact_record_markdown_paths(root):
        for ident, _ in _canonical_artifacts(path, root):
            if int(ident.split("-", 1)[1]) < 1:
                report.add(
                    "error", "zero-artifact-id",
                    f"{ident} is invalid; durable IDs begin at 1 and counter zero means none allocated",
                    path,
                )
            if ident in canonical:
                report.add("error", "duplicate-id", f"{ident} is also the canonical ID of {canonical[ident].relative_to(root)}", path)
            else:
                canonical[ident] = path
    if index is None:
        return canonical

    entries = index.registry()
    registry_by_id: dict[str, RegistryEntry] = {}
    for entry in entries:
        if int(entry.ident.split("-", 1)[1]) < 1:
            report.add(
                "error", "zero-artifact-id",
                f"registry ID {entry.ident} is invalid; durable IDs begin at 1",
                root / "ARTIFACT_INDEX.md",
            )
        if entry.ident in registry_by_id:
            report.add("error", "duplicate-registry-id", f"registry contains {entry.ident} more than once", root / "ARTIFACT_INDEX.md")
        registry_by_id[entry.ident] = entry
        target = _path_from_registry(root, entry)
        if entry.status in {"abandoned", "reserved"}:
            continue
        try:
            target.relative_to(root.resolve())
        except ValueError:
            report.add("error", "registry-path-outside-root", f"registry target for {entry.ident} escapes the project: {entry.path}", root / "ARTIFACT_INDEX.md")
            continue
        if not target.exists():
            report.add("error", "missing-artifact", f"registry target for {entry.ident} does not exist: {entry.path}", root / "ARTIFACT_INDEX.md")
        elif not target.is_file():
            report.add("error", "registry-target-not-file", f"registry target for {entry.ident} is not a file: {entry.path}", root / "ARTIFACT_INDEX.md")
            continue
        if target.exists() and "#" in entry.path:
            fragment = unquote(entry.path.split("#", 1)[1]).casefold()
            if fragment not in _markdown_anchors(target.read_text(encoding="utf-8")):
                report.add("error", "missing-registry-anchor", f"registry fragment for {entry.ident} does not exist: #{fragment}", root / "ARTIFACT_INDEX.md")
        if entry.ident.startswith(("DIR-", "INB-")):
            if "#" not in entry.path:
                report.add("error", "missing-registry-anchor", f"embedded artifact {entry.ident} requires its canonical heading fragment", root / "ARTIFACT_INDEX.md")
            elif target.exists() and target.is_file():
                block_match = re.search(
                    rf"(?m)^##\s+{re.escape(entry.ident)}\s+—\s+(.+?)\s*$",
                    target.read_text(encoding="utf-8"),
                )
                if block_match:
                    expected_fragment = _heading_anchor(entry.ident, block_match.group(1))
                    actual_fragment = unquote(entry.path.split("#", 1)[1]).casefold()
                    if actual_fragment != expected_fragment:
                        report.add("error", "registry-anchor-mismatch", f"registry fragment for {entry.ident} is `{actual_fragment}`, expected `{expected_fragment}`", root / "ARTIFACT_INDEX.md")
        if target.exists() and entry.ident.split("-", 1)[0] not in {"DIR", "INB"}:
            artifact = _canonical_artifact(target)
            if artifact is None:
                report.add("error", "registry-target-not-artifact", f"registry target for {entry.ident} has no canonical artifact heading", target)
            elif artifact[0] != entry.ident:
                report.add("error", "registry-id-mismatch", f"registry says {entry.ident}, target declares {artifact[0]}", target)
            elif not _canonical_artifact_path(root, entry.ident, target):
                report.add(
                    "error", "noncanonical-artifact-path",
                    f"{entry.ident} registry target is outside its stable canonical layout",
                    target,
                )

    for ident, path in canonical.items():
        if not _canonical_artifact_path(root, ident, path):
            report.add("error", "noncanonical-artifact-path", f"{ident} is stored outside its stable canonical layout", path)
        if ident not in registry_by_id:
            report.add("error", "unregistered-artifact", f"canonical artifact {ident} is not in the registry", path)
        else:
            entry = registry_by_id[ident]
            if entry.status in {"abandoned", "reserved"}:
                report.add(
                    "error", "realized-reservation-status",
                    f"{ident} has a real artifact but registry status remains `{entry.status}`; publish its real status/path or remove an invalid abandoned artifact",
                    root / "ARTIFACT_INDEX.md",
                )
            registered_target = _path_from_registry(root, entry)
            if entry.status not in {"abandoned", "reserved"} and registered_target.resolve(strict=False) != path.resolve(strict=False):
                report.add("error", "registry-path-mismatch", f"registry path for {ident} does not point to its canonical artifact", root / "ARTIFACT_INDEX.md")
            prefix = ident.split("-", 1)[0]
            artifact_text = path.read_text(encoding="utf-8")
            if prefix in {"DIR", "INB"}:
                artifact_text = _embedded_block(artifact_text, ident)
            labels = _record_metadata(artifact_text)
            status_label = "activity" if prefix == "DIR" else "disposition" if prefix == "INB" else "status"
            artifact_status = labels.get(status_label, "").casefold().strip("` ")
            registry_status = entry.status.strip("` ")
            if (
                registry_status not in {"", "reserved", "abandoned"}
                and artifact_status
                and registry_status != artifact_status
            ):
                report.add(
                    "error", "registry-status-mismatch",
                    f"registry status `{registry_status}` differs from {ident} {status_label} `{artifact_status}`",
                    root / "ARTIFACT_INDEX.md",
                )

    counters = index.counters()
    for prefix in PREFIXES:
        prefix_rows = [
            cells for _, cells in index.counter_table.rows
            if index.prefix_column < len(cells) and cells[index.prefix_column].strip().upper() == prefix
        ]
        if len(prefix_rows) != 1:
            report.add("error", "duplicate-counter-row", f"expected exactly one allocation counter row for {prefix}, found {len(prefix_rows)}", root / "ARTIFACT_INDEX.md")
        if prefix not in counters:
            report.add("error", "missing-counter", f"allocation counter is missing for {prefix}", root / "ARTIFACT_INDEX.md")
            continue
        seen_numbers = [int(entry.ident.split("-")[1]) for entry in entries if entry.ident.startswith(prefix + "-")]
        canonical_numbers = [int(ident.split("-")[1]) for ident in canonical if ident.startswith(prefix + "-")]
        maximum = max(seen_numbers + canonical_numbers, default=0)
        if counters[prefix] < maximum:
            report.add("error", "counter-behind", f"{prefix} counter {counters[prefix]} is below observed ID {maximum}", root / "ARTIFACT_INDEX.md")
        elif counters[prefix] > max(seen_numbers, default=0):
            report.add("warning", "unrecorded-reservation", f"{prefix} counter is {counters[prefix]} but registry reaches only {max(seen_numbers, default=0)}; record abandoned/reserved IDs", root / "ARTIFACT_INDEX.md")
        missing_numbers = sorted(set(range(1, counters[prefix] + 1)).difference(seen_numbers))
        if missing_numbers:
            rendered = ", ".join(f"{prefix}-{number:04d}" for number in missing_numbers[:12])
            if len(missing_numbers) > 12:
                rendered += f", and {len(missing_numbers) - 12} more"
            report.add(
                "error", "unaccounted-id",
                f"allocated IDs are absent from the registry: {rendered}; add abandoned/reserved rows",
                root / "ARTIFACT_INDEX.md",
            )
    return canonical


def _check_revisions(root: Path, report: CheckReport) -> None:
    project = root / "PROJECT.md"
    state = root / "STATE.md"
    if not project.exists() or not state.exists():
        return
    project_labels = _preamble_metadata(project.read_text(encoding="utf-8"))
    state_labels = _preamble_metadata(state.read_text(encoding="utf-8"))
    contract_revision = _integer_in(project_labels.get("contract revision"))
    state_contract_revision = _integer_in(
        state_labels.get("current contract revision") or state_labels.get("contract revision")
    )
    if contract_revision is None:
        report.add("error", "missing-revision", "missing numeric `Contract revision` label", project)
    if state_contract_revision is None:
        report.add("error", "missing-revision", "missing numeric `Current contract revision` label", state)
    if contract_revision is not None and state_contract_revision is not None and contract_revision != state_contract_revision:
        report.add("error", "contract-revision-mismatch", f"PROJECT is revision {contract_revision}, STATE points to {state_contract_revision}", state)
    if _integer_in(state_labels.get("state revision")) is None:
        report.add("error", "missing-revision", "missing numeric `State revision` label", state)
    elif _contract_accepted(root) and _integer_in(state_labels.get("state revision")) < 1:
        report.add("error", "invalid-state-revision", "accepted project requires STATE revision >= 1", state)
    index = _load_index(root, CheckReport())
    if index is not None and index.registry() and not _contract_accepted(root):
        report.add("error", "unaccepted-contract-artifacts", "research artifacts exist before the human contract is accepted", project)
    if _contract_accepted(root) and not _contract_mature(root):
        report.add("error", "immature-accepted-contract", "accepted contract or active state still contains initialization placeholders", project)
    if _contract_accepted(root):
        for error in _contract_revision_log_errors(root):
            report.add("error", "invalid-contract-revision-log", error, project)
        state_text = state.read_text(encoding="utf-8")
        for heading in ROOT_REQUIRED_HEADINGS["STATE.md"]:
            section = _section(state_text, heading)
            if _unfinished_section(section):
                report.add(
                    "error", "accepted-state-section-incomplete",
                    f"accepted project leaves STATE `## {heading}` unfinished",
                    state,
                )
        next_action = _section(state_text, "Recommended next action")
        if re.sub(r"\s+", " ", next_action).casefold().strip(" `-.\n") in {
            "", "none", "not applicable",
        }:
            report.add(
                "error", "state-next-action-missing",
                "accepted STATE must name a concrete recommended next action",
                state,
            )
        for heading, fields in (
            ("Strategic review", ("last strategic review", "next strategic review trigger")),
            ("Human overview refresh", ("last overview refresh", "next overview refresh trigger")),
        ):
            values = _metadata(_section(state_text, heading))
            for field in fields:
                if field not in values or _unfinished_value(values.get(field, "")):
                    report.add(
                        "error", "state-review-trigger-missing",
                        f"accepted STATE `## {heading}` needs a concrete `{field}` value",
                        state,
                    )
    if contract_revision is not None:
        for relative in ("research/DIRECTIONS.md", "research/INBOX.md"):
            path = root / relative
            if not path.exists():
                continue
            shared_revision = _integer_in(_preamble_metadata(path.read_text(encoding="utf-8")).get("contract revision"))
            if shared_revision != contract_revision:
                report.add("error", "shared-contract-revision-mismatch", f"shared control record covers contract revision {shared_revision}, expected {contract_revision}", path)
    overview = root / "OVERVIEW.md"
    if overview.exists():
        overview_labels = _preamble_metadata(overview.read_text(encoding="utf-8"))
        overview_contract = _integer_in(overview_labels.get("contract revision covered"))
        current_state_revision = _integer_in(state_labels.get("state revision"))
        overview_state = _integer_in(overview_labels.get("state revision covered"))
        if contract_revision is not None and overview_contract is not None and overview_contract > contract_revision:
            report.add("error", "overview-revision-ahead", f"overview claims future contract revision {overview_contract}", overview)
        if current_state_revision is not None and overview_state is not None and overview_state > current_state_revision:
            report.add("error", "overview-revision-ahead", f"overview claims future state revision {overview_state}", overview)
        if _contract_accepted(root):
            if overview_contract is None or overview_state is None:
                report.add("error", "overview-revision-invalid", "accepted project requires exact numeric overview coverage revisions", overview)
            overview_status = overview_labels.get("overview status", "").casefold().strip("` ")
            if overview_status not in {"current", "stale"}:
                report.add(
                    "error", "overview-status-invalid",
                    f"accepted project overview status must be `current` or `stale`, found `{overview_status}`",
                    overview,
                )
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}", overview_labels.get("last refreshed", "").strip()) is None:
                report.add("error", "overview-refresh-date-invalid", "accepted overview needs a concrete YYYY-MM-DD Last refreshed date", overview)
            if _unfinished_value(overview_labels.get("next refresh trigger", "")):
                report.add("error", "overview-refresh-trigger-missing", "accepted overview needs a concrete Next refresh trigger", overview)


def _check_artifact_contracts(root: Path, report: CheckReport, canonical: Mapping[str, Path]) -> None:
    current_contract_revision = _project_revision(root)
    current_state_revision = _state_revision(root)
    for ident, path in canonical.items():
        prefix = ident.split("-", 1)[0]
        whole_text = path.read_text(encoding="utf-8")
        text = _embedded_block(whole_text, ident) if prefix in {"DIR", "INB"} else whole_text
        header_labels = _preamble_metadata(text)
        labels = _record_metadata(text)
        cleaned = _strip_non_authoritative_examples(text)
        label_names = [_normal_header(value) for value in re.findall(r"(?m)^-\s*\*\*([^*]+?):\*\*", cleaned)]
        for duplicate in sorted({label for label in label_names if label_names.count(label) > 1}):
            report.add("error", "duplicate-artifact-label", f"{ident} repeats fixed bold label `{duplicate}`", path)
        headings_required = ARTIFACT_REQUIRED_HEADINGS.get(prefix, ())
        required_labels = ARTIFACT_REQUIRED_LABELS.get(prefix, ())
        if prefix == "LIT" and labels.get("record kind", "").casefold() not in {
            "literature note", "consequential literature search",
        }:
            report.add(
                "error", "invalid-literature-record-kind",
                f"{ident} has unsupported Record kind `{labels.get('record kind', '')}`",
                path,
            )
        if prefix == "LIT" and labels.get("record kind", "").casefold() == "consequential literature search":
            headings_required = (
                "Research questions informed", "Search locations", "Exact queries and filters",
                "Selection and exclusion logic", "Sources retained", "Findings",
                "Coverage limits and known gaps", "Recommended follow-up",
            )
            required_labels = (
                "Status", "Record kind", "Contract revision", "Search dates", "Created in",
                "Last updated in", "Related artifacts", "Supersedes",
            )
        for heading in headings_required:
            if not _heading_exists(text, heading):
                report.add("error", "missing-artifact-heading", f"{ident} is missing `## {heading}`", path)
            elif _heading_count(text, heading) != 1:
                report.add(
                    "error", "duplicate-artifact-heading",
                    f"{ident} must contain exactly one `## {heading}` section",
                    path,
                )
        if prefix not in {"DIR", "INB"}:
            top_headings = re.findall(r"(?m)^#(?!#)\s+(.+?)\s*$", cleaned)
            matching_ids = [
                match.group(1)
                for heading in top_headings
                for match in [re.match(r"((?:RUN|CLM|ATT|REV|LIT|EXP|RPT)-\d{4,})(?=\s|$)", heading)]
                if match is not None
            ]
            if len(top_headings) != 1 or matching_ids != [ident]:
                report.add(
                    "error", "invalid-artifact-h1-count",
                    f"{ident} must have exactly one top-level heading, and it must declare that same canonical ID",
                    path,
                )
        if prefix == "DIR":
            required_labels = (
                "Activity", "Assessment", "Contract revision", "Created in", "Last updated in",
                "Research question", "Why it matters", "Supporting evidence", "Opposing evidence",
                "Current obstacle", "Next discriminating action", "Stop condition", "Revival condition",
                "Last strategic review", "Linked artifacts", "Expanded record",
            )
        elif prefix == "INB":
            required_labels = (
                "Kind", "Disposition", "Uncertainty class", "Contract revision", "Source",
                "Finding or question", "Why it matters", "Related direction or claim", "Provisional assumption",
                "Dependent artifacts", "Safe continuation horizon", "Affected branch", "Human answer",
                "Triage reason", "Revisit condition", "Last triaged in",
            )
        for label in required_labels:
            if _normal_header(label) not in header_labels:
                report.add("error", "missing-artifact-label", f"{ident} is missing fixed label `{label}`", path)
            elif not header_labels[_normal_header(label)].strip():
                report.add("error", "blank-artifact-label", f"{ident} has a blank fixed label `{label}`; use none/pending explicitly", path)
        artifact_contract_revision = _integer_in(labels.get("contract revision"))
        if artifact_contract_revision is None or artifact_contract_revision < 1:
            report.add("error", "invalid-artifact-revision", f"{ident} must record Contract revision in 1..{current_contract_revision}", path)
        elif artifact_contract_revision > current_contract_revision:
            report.add("error", "future-artifact-revision", f"{ident} claims future contract revision {artifact_contract_revision}", path)
        if prefix in {"CLM", "LIT", "EXP"}:
            supersedes = labels.get("supersedes", "")
            if supersedes.casefold().strip("` .") != "none":
                superseded_id = _exact_canonical_linked_id(path, supersedes, prefix, canonical)
                if superseded_id is None or superseded_id == ident:
                    report.add(
                        "error", "invalid-supersedes-link",
                        f"{ident} Supersedes must be `none` or exactly one canonical non-self {prefix} link",
                        path,
                    )
        if prefix == "RUN":
            base_state_revision = _integer_in(labels.get("base state revision"))
            if base_state_revision is None or base_state_revision > current_state_revision:
                report.add("error", "invalid-run-base-revision", f"{ident} has invalid Base state revision `{labels.get('base state revision', '')}`", path)
        if prefix in VALID_STATUSES:
            label = "activity" if prefix == "DIR" else "disposition" if prefix == "INB" else "status"
            value = labels.get(label, "").casefold()
            if value not in VALID_STATUSES[prefix]:
                report.add("error", "invalid-status", f"invalid {label} `{value}` for {prefix}", path)
        if prefix == "ATT":
            outcome = labels.get("outcome", "").casefold()
            if outcome not in {"proved", "disproved", "failed", "inconclusive", "blocked"}:
                report.add("error", "invalid-outcome", f"invalid attempt outcome `{outcome}`", path)
            if labels.get("status", "").casefold() == "completed":
                question = labels.get("assigned question", "").strip()
                if _unfinished_value(question):
                    report.add("error", "completed-attempt-incomplete", f"{ident} has no finalized assigned question", path)
                required_sections = (
                    "Assumptions used", "Approach", "Outcome and support",
                    "Exact failure point or obstruction", "Counterexamples and partial results",
                    "Reusable observations", "Produced artifacts", "Retry and revival conditions",
                )
                substantive_sections = {"Approach", "Outcome and support"}
                if outcome in {"disproved", "failed", "blocked", "inconclusive"}:
                    substantive_sections.add("Exact failure point or obstruction")
                for heading in required_sections:
                    section = _section(text, heading)
                    unfinished = (
                        _unfinished_substantive_section(section)
                        if heading in substantive_sections else _unfinished_section(section)
                    )
                    if unfinished:
                        report.add("error", "completed-attempt-incomplete", f"{ident} has unfinished `## {heading}`", path)
        elif prefix == "CLM":
            claim_revision = _integer_in(labels.get("claim revision"))
            if claim_revision is None or claim_revision < 1:
                report.add("error", "invalid-claim-revision", f"{ident} must record a positive numeric Claim revision", path)
            claim_kind = labels.get("claim kind", "").casefold().strip("[] ")
            allowed = {"theorem", "lemma", "counterexample", "impossibility", "empirical observation", "literature-derived proposition"}
            # Bracketed template guidance is allowed only in draft records.
            if claim_kind not in allowed and not (labels.get("status", "").casefold() == "draft" and " | " in claim_kind):
                report.add("error", "invalid-claim-kind", f"invalid claim kind `{claim_kind}`", path)
            claim_status = labels.get("status", "").casefold()
            evidence_revision = _integer_in(labels.get("evidence revision"))
            if claim_status in {"candidate", "under review", "validated"}:
                for error in _review_ready_claim_errors(text):
                    report.add(
                        "error", "review-ready-claim-incomplete",
                        f"{ident} is not review-ready: {error}",
                        path,
                    )
            if claim_status != "draft":
                if labels.get("evidence class", "").casefold().strip() in {"", "pending", "unknown"}:
                    report.add("error", "mature-claim-incomplete", f"{ident} has no finalized evidence class", path)
                for heading in ("Exact statement", "Assumptions, quantifiers, scope, and exceptions", "Relationship to the project question", "Evidence"):
                    section = _section(text, heading)
                    if _unfinished_section(section):
                        report.add("error", "mature-claim-incomplete", f"{ident} has unfinished `## {heading}`", path)
            if claim_status in {"under review", "validated"}:
                for heading in ("Dependencies", "Known limitations and open issues"):
                    if _unfinished_section(_section(text, heading)):
                        report.add("error", "mature-claim-incomplete", f"{ident} has unfinished `## {heading}`", path)
                for field in ("primary evidence", "evidence location", "what the evidence establishes"):
                    if _unfinished_value(labels.get(field, "")):
                        report.add("error", "mature-claim-incomplete", f"{ident} leaves `{field}` unresolved", path)
                proof = _section(text, "Proof or derivation")
                if _unfinished_section(proof):
                    report.add("error", "mature-claim-incomplete", f"{ident} has unfinished proof or derivation/inferential chain", path)
            if claim_status in {"under review", "validated", "rejected", "refuted", "inconclusive", "superseded"}:
                change_notes = _section(text, "Change notes")
                if claim_revision is None or not _revision_note_concrete(change_notes, "Claim revision", claim_revision):
                    report.add(
                        "error", "claim-revision-note-missing",
                        f"{ident} Change notes lacks a concrete entry for Claim revision {claim_revision or 'missing'}",
                        path,
                    )
                if evidence_revision is None or not _revision_note_concrete(change_notes, "Evidence revision", evidence_revision):
                    report.add(
                        "error", "evidence-revision-note-missing",
                        f"{ident} Change notes lacks a concrete entry for Evidence revision {evidence_revision or 'missing'}",
                        path,
                    )
        elif prefix == "REV":
            verdict = labels.get("verdict", "").casefold()
            if verdict not in {"pass", "fail", "narrower-than-stated", "inconclusive"}:
                report.add("error", "invalid-verdict", f"invalid review verdict `{verdict}`", path)
            requested_profile = labels.get("requested profile", "").casefold().strip("` ")
            if requested_profile not in {"substantive", "deep", "pivotal"}:
                report.add("error", "invalid-review-profile", f"invalid review profile `{requested_profile}`", path)
        elif prefix == "RUN":
            integration = labels.get("integration status", "").casefold()
            if integration not in {"not integrated", "partially integrated", "integrated"}:
                report.add("error", "invalid-integration-status", f"invalid run integration status `{integration}`", path)
        elif prefix == "DIR":
            assessment = labels.get("assessment", "").casefold()
            if assessment not in {"promising", "uncertain", "attempted-unresolved", "weak", "succeeded", "failed"}:
                report.add("error", "invalid-direction-assessment", f"invalid direction assessment `{assessment}`", path)
            for field in ("research question", "why it matters", "current obstacle", "next discriminating action", "stop condition", "revival condition"):
                value = labels.get(field, "").strip()
                optional = field in {"current obstacle", "stop condition", "revival condition"}
                if _unfinished_value(value, allow_none=optional):
                    report.add("error", "mature-direction-incomplete", f"{ident} leaves `{field}` unfinished", path)
        elif prefix == "INB":
            kind = labels.get("kind", "").casefold()
            allowed_kinds = {"idea", "question", "lemma", "experiment", "literature lead", "model concern", "blocker", "infrastructure", "human alignment"}
            if kind not in allowed_kinds:
                report.add("error", "invalid-inbox-kind", f"invalid inbox kind `{kind}`", path)
            uncertainty = labels.get("uncertainty class", "").casefold()
            uncertainty_values = {"safe provisional", "consequential but deferrable", "dangerous now", "project-blocking"}
            if kind == "human alignment" and uncertainty not in uncertainty_values:
                report.add("error", "invalid-uncertainty-class", f"human alignment item has invalid uncertainty class `{uncertainty}`", path)
            if kind != "human alignment" and uncertainty not in {"not applicable", *uncertainty_values}:
                report.add("error", "invalid-uncertainty-class", f"invalid uncertainty class `{uncertainty}`", path)
            if kind == "human alignment":
                for field in ("why it matters", "provisional assumption", "dependent artifacts", "safe continuation horizon", "affected branch"):
                    value = labels.get(field, "").strip()
                    if _unfinished_value(value):
                        report.add("error", "incomplete-alignment-item", f"{ident} leaves consequential field `{field}` unresolved", path)
                pending_answer = labels.get("human answer", "").casefold().strip("` ") in {"", "pending", "unknown"}
                if uncertainty in {"dangerous now", "project-blocking"} and pending_answer:
                    affected_directions = _canonical_linked_ids(
                        path, labels.get("affected branch", ""), "DIR", canonical,
                    )
                    pause_marker = labels.get("no-work pause validated", "").casefold() in {"yes", "true"}
                    if not affected_directions and not pause_marker:
                        report.add(
                            "error", "dangerous-alignment-branch-unpaused",
                            f"{ident} has dangerous pending uncertainty but neither links an affected direction nor records `No-work pause validated: yes`",
                            path,
                        )
                    for direction_id in sorted(affected_directions):
                        direction_block = _embedded_block(canonical[direction_id].read_text(encoding="utf-8"), direction_id)
                        activity = _record_metadata(direction_block).get("activity", "").casefold()
                        if activity not in {"blocked", "parked"}:
                            report.add(
                                "error", "dangerous-alignment-branch-unpaused",
                                f"{ident} is pending with uncertainty `{uncertainty}`, but affected {direction_id} is `{activity or 'missing'}` rather than blocked/parked",
                                path,
                            )
            for field in ("source", "finding or question", "why it matters"):
                if _unfinished_value(labels.get(field, "")):
                    report.add("error", "inbox-core-incomplete", f"{ident} leaves triage-critical field `{field}` unfinished", path)
            if labels.get("disposition", "").casefold() != "new":
                triage_reason = labels.get("triage reason", "")
                if _unfinished_value(triage_reason) or triage_reason.casefold().strip() == "not yet triaged":
                    report.add("error", "triaged-inbox-incomplete", f"{ident} has no concrete triage reason", path)
                if _unfinished_value(labels.get("revisit condition", ""), allow_none=True):
                    report.add("error", "triaged-inbox-incomplete", f"{ident} has no revisit condition or explicit `none`", path)
                if _unfinished_value(labels.get("last triaged in", "")):
                    report.add("error", "triaged-inbox-incomplete", f"{ident} has no Last triaged in record", path)
        status = labels.get("status", "").casefold()
        if prefix == "LIT" and status == "completed":
            record_kind = labels.get("record kind", "").casefold()
            if record_kind == "literature note":
                for field in ("bibtex key", "stable locator"):
                    value = labels.get(field, "").strip()
                    if _unfinished_value(value):
                        report.add("error", "completed-literature-incomplete", f"{ident} leaves `{field}` unresolved", path)
                bibliographic = _metadata(_section(text, "Bibliographic record"))
                for field in ("authors", "title", "venue and year", "doi or stable url"):
                    if _unfinished_value(bibliographic.get(field, "")):
                        report.add(
                            "error", "completed-literature-incomplete",
                            f"{ident} leaves bibliographic field `{field}` unresolved; a justified explanatory value is required when no DOI/URL exists",
                            path,
                        )
                key = labels.get("bibtex key", "").strip()
                bibliography = root / "literature/references.bib"
                if key and bibliography.exists():
                    bibliography_keys = [
                        value.casefold()
                        for value in re.findall(
                            r"(?mi)@\w+\s*\{\s*([^,\s]+)\s*,",
                            bibliography.read_text(encoding="utf-8"),
                        )
                    ]
                    matches = bibliography_keys.count(key.casefold())
                    if matches == 0:
                        report.add("error", "bibtex-key-missing", f"{ident} BibTeX key `{key}` is absent from references.bib", path)
                    elif matches != 1:
                        report.add(
                            "error", "bibtex-key-not-unique",
                            f"{ident} BibTeX key `{key}` resolves to {matches} case-insensitive entries",
                            path,
                        )
                for heading in ARTIFACT_REQUIRED_HEADINGS["LIT"]:
                    section = _section(text, heading)
                    substantive = heading in {
                        "Precise source locations", "Source statement and assumptions",
                        "Project-facing interpretation", "Translation into project terminology",
                        "Relationships to active questions", "Verification notes",
                    }
                    unfinished = (
                        _unfinished_substantive_section(section)
                        if substantive else _unfinished_section(section)
                    )
                    if unfinished:
                        report.add("error", "completed-literature-incomplete", f"{ident} has unfinished `## {heading}`", path)
            elif record_kind == "consequential literature search":
                if labels.get("search dates", "").casefold().strip() in {"", "pending", "unknown"}:
                    report.add("error", "completed-search-incomplete", f"{ident} has no finalized search dates", path)
                for heading in (
                    "Research questions informed", "Search locations", "Exact queries and filters",
                    "Selection and exclusion logic", "Sources retained", "Findings",
                    "Coverage limits and known gaps", "Recommended follow-up",
                ):
                    section = _section(text, heading)
                    substantive = heading in {
                        "Research questions informed", "Search locations",
                        "Exact queries and filters", "Selection and exclusion logic",
                        "Findings", "Coverage limits and known gaps",
                    }
                    unfinished = (
                        _unfinished_substantive_section(section)
                        if substantive else _unfinished_section(section)
                    )
                    if unfinished:
                        report.add("error", "completed-search-incomplete", f"{ident} has unfinished `## {heading}`", path)
                query_section = _section(text, "Exact queries and filters")
                try:
                    query_lines = query_section.splitlines()
                    query_table = _find_table(query_lines, 0, len(query_lines))
                    date_column = _column(query_table.headers, ("Date",))
                    location_column = _column(query_table.headers, ("Location",))
                    query_column = _column(query_table.headers, ("Query",))
                    filter_column = _column(query_table.headers, ("Filters",))
                    concrete_rows = 0
                    for _, cells in query_table.rows:
                        if max(date_column, location_column, query_column, filter_column) >= len(cells):
                            continue
                        if (
                            re.fullmatch(r"\d{4}-\d{2}-\d{2}", cells[date_column].strip())
                            and not _unfinished_value(cells[location_column])
                            and not _unfinished_value(cells[query_column])
                            and not _unfinished_value(cells[filter_column], allow_none=True)
                        ):
                            concrete_rows += 1
                    if concrete_rows == 0:
                        raise ResearchError("no concrete query row")
                except ResearchError as error:
                    report.add(
                        "error", "completed-search-incomplete",
                        f"{ident} Exact queries and filters lacks a concrete dated location/query row: {error}",
                        path,
                    )
        if prefix == "CLM" and status == "validated":
            for field in ("created in", "last updated in"):
                if _exact_canonical_linked_id(path, labels.get(field, ""), "RUN", canonical) is None:
                    report.add("error", "validated-claim-traceability", f"{ident} has no exact canonical RUN link in `{field}`", path)
            for field in ("primary evidence", "evidence location"):
                value = labels.get(field, "").strip()
                if not value or value.casefold() in {"pending", "none", "unknown"}:
                    report.add("error", "validated-claim-traceability", f"{ident} leaves `{field}` unresolved", path)
        if prefix == "CLM" and status in {"rejected", "refuted", "inconclusive", "superseded"}:
            for field in ("created in", "last updated in"):
                if _exact_canonical_linked_id(path, labels.get(field, ""), "RUN", canonical) is None:
                    report.add(
                        "error", "terminal-claim-traceability",
                        f"{ident} has no exact canonical RUN link in `{field}`",
                        path,
                    )
            evidence_rationale = labels.get("what the evidence establishes", "")
            for field in ("primary evidence", "evidence location"):
                value = labels.get(field, "")
                if _unfinished_value(value, allow_none=True):
                    report.add(
                        "error", "terminal-claim-evidence-incomplete",
                        f"{ident} leaves `{field}` unfinished",
                        path,
                    )
                elif value.casefold().strip("` .") in {"none", "not applicable"} and _unfinished_value(evidence_rationale):
                    report.add(
                        "error", "terminal-claim-evidence-incomplete",
                        f"{ident} records `{field}: {value}` without a concrete evidence rationale",
                        path,
                    )
        if prefix == "REV" and status == "completed":
            for field in ("created in", "last updated in"):
                if _exact_canonical_linked_id(path, labels.get(field, ""), "RUN", canonical) is None:
                    report.add("error", "completed-review-traceability", f"{ident} has no exact canonical RUN link in `{field}`", path)
            for heading in ARTIFACT_REQUIRED_HEADINGS["REV"]:
                section = _section(text, heading)
                if _unfinished_section(section):
                    report.add("error", "completed-review-incomplete", f"{ident} has unfinished `## {heading}`", path)
        if prefix == "RPT" and status == "published":
            report_symlink = _symlink_component(root, path.relative_to(root))
            if report_symlink is not None:
                report.add(
                    "error", "published-report-symlinked",
                    f"{ident} traverses symlink `{report_symlink.relative_to(root).as_posix()}`",
                    report_symlink,
                )
            try:
                report_link_count = path.stat().st_nlink
            except OSError:
                report_link_count = 0
            if report_link_count != 1:
                report.add(
                    "error", "published-report-hardlinked",
                    f"{ident} must have exactly one filesystem link so its immutable snapshot identity is enforceable",
                    path,
                )
            report_date = labels.get("report date", "").strip()
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}", report_date) is None:
                report.add(
                    "error", "published-report-date-invalid",
                    f"{ident} needs a concrete YYYY-MM-DD Report date",
                    path,
                )
            report_state_revision = _integer_in(labels.get("state revision"))
            if report_state_revision is None or report_state_revision > current_state_revision:
                report.add(
                    "error", "published-report-state-revision-invalid",
                    f"{ident} State revision must be numeric and no newer than current STATE revision {current_state_revision}",
                    path,
                )
            supersedes_value = labels.get("supersedes", "")
            if supersedes_value.casefold().strip("` .") != "none":
                superseded_id = _exact_canonical_linked_id(
                    path, supersedes_value, "RPT", canonical,
                )
                if superseded_id is None or superseded_id == ident:
                    report.add(
                        "error", "published-report-supersedes-invalid",
                        f"{ident} Supersedes must be `none` or exactly one canonical link to a different report",
                        path,
                    )
            for field in ("runs covered", "prepared in", "manuscript build"):
                value = labels.get(field, "").casefold().strip()
                if value in {"", "pending", "unknown", "unavailable or not attempted"}:
                    report.add("error", "published-report-incomplete", f"{ident} leaves `{field}` unresolved", path)
            for heading in ARTIFACT_REQUIRED_HEADINGS["RPT"]:
                if _unfinished_section(_section(text, heading)):
                    report.add("error", "published-report-incomplete", f"{ident} leaves `## {heading}` unfinished", path)
            covered_runs = _canonical_linked_ids(path, labels.get("runs covered", ""), "RUN", canonical)
            prepared_run = _exact_canonical_linked_id(
                path, labels.get("prepared in", ""), "RUN", canonical,
            )
            if not covered_runs:
                report.add("error", "published-report-run-links-invalid", f"{ident} Runs covered has no canonical RUN link", path)
            if prepared_run is None:
                report.add("error", "published-report-run-links-invalid", f"{ident} Prepared in must link exactly one canonical RUN", path)
            for run_id in sorted(covered_runs.union({prepared_run} if prepared_run else set())):
                run_labels = _record_metadata(canonical[run_id].read_text(encoding="utf-8"))
                if (
                    run_labels.get("status", "").casefold() != "completed"
                    or run_labels.get("integration status", "").casefold() != "integrated"
                ):
                    report.add(
                        "error", "published-report-run-not-integrated",
                        f"{ident} references {run_id}, which is not both completed and integrated",
                        path,
                    )
        if prefix in {"ATT", "LIT", "EXP"} and status == "completed":
            for field in ("created in", "last updated in"):
                if _exact_canonical_linked_id(path, labels.get(field, ""), "RUN", canonical) is None:
                    report.add("error", "terminal-artifact-traceability", f"{ident} has no exact canonical RUN link in `{field}`", path)
        if prefix == "EXP" and status == "blocked":
            for field in ("created in", "last updated in", "created by run"):
                if _exact_canonical_linked_id(path, labels.get(field, ""), "RUN", canonical) is None:
                    report.add(
                        "error", "blocked-experiment-traceability",
                        f"{ident} has no exact canonical RUN link in `{field}`",
                        path,
                    )
            for heading in (
                "Research question", "Protocol", "Interpretation",
                "Limitations and threats to validity",
            ):
                section = _section(text, heading)
                unfinished = (
                    _unfinished_substantive_section(section)
                    if heading in {"Research question", "Protocol", "Interpretation"}
                    else _unfinished_section(section)
                )
                if unfinished:
                    report.add(
                        "error", "blocked-experiment-incomplete",
                        f"{ident} leaves blocked-experiment field `## {heading}` unfinished",
                        path,
                    )


def _check_integrated_run_tasks(root: Path, run_id: str, run_path: Path, report: CheckReport) -> None:
    tasks_root = run_path.parent / "tasks"
    directories = [
        directory for directory in sorted(tasks_root.iterdir())
        if directory.is_dir() and re.fullmatch(r"T\d{2,}", directory.name)
    ] if tasks_root.exists() else []
    task_section = _section(run_path.read_text(encoding="utf-8"), "Task packets and profile receipts")
    actual = {f"{run_id}-{directory.name}" for directory in directories}
    task_rows: dict[str, list[str]] = {}
    table_columns: dict[str, int] = {}
    explicit_no_tasks = _section_is_explicit_none(task_section)
    if task_section.strip() and not explicit_no_tasks:
        try:
            table = _find_table(task_section.splitlines(), 0, len(task_section.splitlines()))
            table_columns = {
                "task": _column(table.headers, ("Task",)),
                "question": _column(table.headers, ("Question",)),
                "profile": _column(table.headers, ("Requested profile", "Profile")),
                "status": _column(table.headers, ("Status",)),
                "output": _column(table.headers, ("Output",)),
                "receipt": _column(table.headers, ("Receipt",)),
            }
            for _, cells in table.rows:
                task_id = re.search(rf"\b{re.escape(run_id)}-T\d{{2,}}\b", cells[table_columns["task"]] if table_columns["task"] < len(cells) else "")
                if task_id is None:
                    continue
                if task_id.group(0) in task_rows:
                    report.add("error", "run-task-table-duplicate", f"{run_id} task table repeats {task_id.group(0)}", run_path)
                task_rows[task_id.group(0)] = cells
        except ResearchError as error:
            report.add("error", "run-task-table-invalid", f"{run_id} task handoff table is invalid: {error}", run_path)
    listed = set(task_rows)
    if listed != actual:
        report.add(
            "error", "run-task-table-mismatch",
            f"{run_id} Task column names {sorted(listed)} but task directories are {sorted(actual)}",
            run_path,
        )
    for directory in directories:
        task_id = f"{run_id}-{directory.name}"
        paths = {name: directory / name for name in ("TASK.md", "OUTPUT.md", "RECEIPT.md")}
        if any(not path.exists() for path in paths.values()):
            report.add("error", "integrated-run-open-task", f"{run_id} is integrated while {task_id} lacks a complete task/output/receipt trio", directory)
            continue
        task = _preamble_metadata(paths["TASK.md"].read_text(encoding="utf-8"))
        output = _preamble_metadata(paths["OUTPUT.md"].read_text(encoding="utf-8"))
        receipt = _preamble_metadata(paths["RECEIPT.md"].read_text(encoding="utf-8"))
        task_status = task.get("status", "").casefold()
        output_status = output.get("status", "").casefold()
        receipt_status = receipt.get("status", "").casefold()
        row = task_rows.get(task_id)
        if row is not None and table_columns and max(table_columns.values()) < len(row):
            expected_targets = {
                "task": paths["TASK.md"], "output": paths["OUTPUT.md"],
                "receipt": paths["RECEIPT.md"],
            }
            for column, target in expected_targets.items():
                links = re.findall(r"\[([^\]]+)\]\(([^)]+)\)", row[table_columns[column]])
                valid = len(links) == 1 and (
                    run_path.parent / unquote(links[0][1].split("#", 1)[0]).strip("<>")
                ).resolve(strict=False) == target.resolve(strict=False)
                if column == "task":
                    valid = valid and re.fullmatch(re.escape(task_id), links[0][0].strip("` ")) is not None
                if not valid:
                    report.add(
                        "error", "run-task-table-link-invalid",
                        f"{run_id} task row for {task_id} needs one exact sibling {column.upper()} link",
                        run_path,
                    )
            if _unfinished_value(row[table_columns["question"]]):
                report.add("error", "run-task-table-incomplete", f"{run_id} task row for {task_id} has no concrete question", run_path)
            row_profile = row[table_columns["profile"]].casefold().strip("` ")
            if row_profile != task.get("requested profile", "").casefold().strip("` "):
                report.add("error", "run-task-table-inconsistent", f"{run_id} task row profile disagrees with {task_id} TASK.md", run_path)
            row_status = row[table_columns["status"]].casefold().strip("` ")
            if row_status != task_status or row_status not in {"completed", "cancelled"}:
                report.add("error", "run-task-table-inconsistent", f"{run_id} task row status is not terminal and consistent with {task_id}", run_path)
        clean_completion = task_status == "completed" and output_status == "completed" and receipt_status == "completed"
        runtime_failure = receipt.get("runtime failure", "").strip()
        preserved_failure = (
            task_status in {"completed", "cancelled"}
            and output_status == "failed"
            and output.get("outcome classification", "").casefold() == "runtime failure"
            and receipt_status == "failed"
            and not _unfinished_value(runtime_failure)
        )
        if not (clean_completion or preserved_failure):
            report.add(
                "error", "integrated-run-open-task",
                f"{run_id} is integrated but {task_id} is not terminal as a completed output or preserved runtime failure",
                directory,
            )


def _check_runs(root: Path, report: CheckReport, canonical: Mapping[str, Path]) -> None:
    state_path = root / "STATE.md"
    if not state_path.exists():
        return
    state_labels = _preamble_metadata(state_path.read_text(encoding="utf-8"))
    last_value = state_labels.get("last integrated run", "")
    declared_last = _id_in(last_value, "RUN")
    last_integrated_id = _exact_canonical_linked_id(
        state_path, last_value, "RUN", canonical,
    )
    last_is_none = last_value.casefold().strip("` ") == "none"
    if (not last_is_none and last_integrated_id is None) or (
        declared_last is not None and last_integrated_id != declared_last
    ):
        report.add(
            "error", "last-integrated-run-link-invalid",
            "STATE Last integrated run must contain exactly one canonical RUN link whose label and destination agree",
            state_path,
        )
    last_number = int(last_integrated_id.split("-")[1]) if last_integrated_id else 0
    condition = state_labels.get("integration condition", "").casefold()
    active_value = state_labels.get("active run", "")
    declared_active = _id_in(active_value, "RUN")
    state_active_id = _exact_canonical_linked_id(
        state_path, active_value, "RUN", canonical,
    )
    active_is_none = active_value.casefold().strip("` ") == "none"
    if (not active_is_none and state_active_id is None) or (
        declared_active is not None and state_active_id != declared_active
    ):
        report.add(
            "error", "active-run-link-invalid",
            "STATE Active run must contain exactly one canonical RUN link whose label and destination agree",
            state_path,
        )
    active_runs: list[str] = []
    run_labels_by_id: dict[str, dict[str, str]] = {}
    for ident, path in canonical.items():
        if not ident.startswith("RUN-"):
            continue
        number = int(ident.split("-")[1])
        labels = _record_metadata(path.read_text(encoding="utf-8"))
        run_labels_by_id[ident] = labels
        status = labels.get("status", "").casefold()
        integration_status = labels.get("integration status", "").casefold()
        if status in {"active", "interrupted"}:
            active_runs.append(ident)
        if integration_status == "integrated" and number > last_number:
            report.add("error", "state-behind-run", f"{ident} is integrated but STATE names only {last_integrated_id or 'no run'}", state_path)
        if integration_status == "integrated" and status != "completed":
            report.add("error", "integrated-run-not-completed", f"{ident} is integrated but Status is `{status}`", path)
        if integration_status == "integrated" and status == "completed":
            base_state_revision = _integer_in(labels.get("base state revision"))
            current_state_revision = _integer_in(state_labels.get("state revision"))
            if (
                base_state_revision is None
                or current_state_revision is None
                or current_state_revision <= base_state_revision + 1
            ):
                report.add(
                    "error", "integrated-run-state-not-advanced",
                    f"{ident} was based on STATE revision {base_state_revision}, but integrated STATE is only revision {current_state_revision}; opening consumes the next revision and integration must publish another newer resume state",
                    state_path,
                )
            close_fields = (
                "outputs reconciled", "durable findings promoted", "portfolio and inbox updated",
                "artifact index updated", "manuscript provenance checked", "state published last",
                "final integration note",
            )
            for field in close_fields:
                value = labels.get(field, "").casefold().strip()
                if value in {"", "pending", "unknown"}:
                    report.add("error", "incomplete-integration-close", f"{ident} integrated with `{field}` still pending", path)
            if labels.get("state published last", "").casefold().strip() not in {"yes", "true"}:
                report.add("error", "state-not-published-last", f"{ident} does not attest that STATE was published last", path)
            _check_integrated_run_tasks(root, ident, path, report)
        if status in {"active", "interrupted"}:
            if _unfinished_value(labels.get("integration authority", "")):
                report.add(
                    "error", "active-run-start-incomplete",
                    f"{ident} has no concrete Integration authority",
                    path,
                )
            run_text = path.read_text(encoding="utf-8")
            for heading in ("Objective", "Starting point"):
                if _unfinished_substantive_section(_section(run_text, heading)):
                    report.add(
                        "error", "active-run-start-incomplete",
                        f"{ident} leaves `## {heading}` unfinished",
                        path,
                    )
        if status == "completed":
            for field in ("closed", "integration authority"):
                if _unfinished_value(labels.get(field, "")):
                    report.add("error", "completed-run-handoff-incomplete", f"{ident} leaves `{field}` unfinished", path)
            run_text = path.read_text(encoding="utf-8")
            handoff_headings = tuple(
                heading for heading in ARTIFACT_REQUIRED_HEADINGS["RUN"]
                if heading != "Integration close"
            )
            for heading in handoff_headings:
                section = _section(run_text, heading)
                unfinished = (
                    _unfinished_substantive_section(section)
                    if heading in {"Objective", "Starting point", "Work attempted"}
                    else _unfinished_section(section)
                )
                if unfinished:
                    report.add("error", "completed-run-handoff-incomplete", f"{ident} leaves `## {heading}` unfinished", path)
        if status == "completed" and integration_status != "integrated":
            report.add("warning", "run-needs-integration", f"{ident} is complete but not fully integrated", path)
            if condition != "recovery required":
                report.add("error", "recovery-condition-missing", f"{ident} needs integration but STATE condition is `{condition}`", state_path)
        if status == "interrupted" or integration_status == "partially integrated":
            report.add("warning", "run-recovery-required", f"{ident} requires recovery/reconciliation", path)
            if not (condition == "active run" and state_active_id == ident) and condition != "recovery required":
                report.add("error", "recovery-condition-missing", f"{ident} needs recovery but STATE condition is `{condition}`", state_path)
    if last_integrated_id and last_integrated_id not in canonical:
        report.add("error", "missing-last-run", f"STATE names absent run {last_integrated_id}", state_path)
    elif last_integrated_id:
        last_labels = run_labels_by_id[last_integrated_id]
        if last_labels.get("status", "").casefold() != "completed" or last_labels.get("integration status", "").casefold() != "integrated":
            report.add("error", "invalid-last-integrated-run", f"STATE's {last_integrated_id} is not completed and integrated", state_path)
    if len(active_runs) > 1:
        report.add("error", "multiple-active-runs", f"multiple active/interrupted runs exist: {', '.join(sorted(active_runs))}", state_path)
    if condition == "clean" and active_runs:
        report.add("error", "unreported-active-run", f"STATE says clean while active/interrupted run(s) exist: {', '.join(active_runs)}", state_path)
    if condition == "active run":
        if len(active_runs) != 1:
            report.add("error", "active-run-condition-mismatch", "STATE says active run but there is not exactly one active/interrupted run", state_path)
        elif state_active_id != active_runs[0]:
            report.add("error", "active-run-link-mismatch", f"STATE Active run names {state_active_id or 'none'}, expected {active_runs[0]}", state_path)
    elif state_active_id is not None:
        report.add("error", "active-run-condition-mismatch", f"STATE names active run {state_active_id} while condition is `{condition}`", state_path)


@dataclasses.dataclass(frozen=True)
class ReviewRecord:
    ident: str
    path: Path
    target: str | None
    revision: int | None
    digest: str
    evidence_revision: int | None
    evidence_digest: str
    verdict: str
    status: str
    fresh_context: str
    task_receipt: str
    requested_profile: str
    receipt_valid: bool
    correctness_yes: bool
    exact_statement_yes: bool
    project_scope_yes: bool
    audit_yes: bool


def _review_fidelity_complete(text: str) -> bool:
    """A terminal review must preserve substantive skeptical work, not `None.`."""
    labels = _record_metadata(text)
    assessment_fields = (
        "evidence or proof correct", "establishes exact recorded statement",
        "addresses intended project question at stated scope", "assumptions accounted for",
        "quantifier order checked", "scope restrictions checked", "exceptional cases checked",
    )
    if any(labels.get(field, "").casefold().strip("` .") not in {"yes", "no", "true", "false"} for field in assessment_fields):
        return False
    if any(
        _unfinished_value(labels.get(field, ""))
        for field in ("correctness rationale", "fidelity rationale", "findings")
    ):
        return False
    substantive_headings = (
        "Materials supplied", "Independence statement", "Verification approach",
        "Correctness assessment", "Claim-fidelity assessment",
        "Assumption, quantifier, and scope audit",
        "Falsification and counterexample attempts", "Verdict rationale",
    )
    if any(_unfinished_substantive_section(_section(text, heading)) for heading in substantive_headings):
        return False
    return all(
        not _unfinished_section(_section(text, heading))
        for heading in ("Reproduction or source checks", "Required corrections or follow-up")
    )


def _review_receipt_path(review_path: Path, labels: Mapping[str, str]) -> Path | None:
    value = labels.get("task receipt", "")
    match = re.search(r"\[[^\]]+\]\(([^)]+RECEIPT\.md)(?:#[^)]*)?\)", value, re.IGNORECASE)
    if not match:
        return None
    receipt_path = (review_path.parent / unquote(match.group(1))).resolve(strict=False)
    if not receipt_path.exists():
        return None
    return receipt_path


def _review_receipt_valid(review_id: str, review_path: Path, labels: Mapping[str, str]) -> bool:
    receipt_path = _review_receipt_path(review_path, labels)
    if receipt_path is None:
        return False
    try:
        root = review_path.parents[2]
        relative = receipt_path.relative_to(root).as_posix()
    except (IndexError, ValueError):
        return False
    path_match = re.fullmatch(r"runs/(RUN-\d{4,})/tasks/(T\d{2,})/RECEIPT\.md", relative)
    if not path_match or int(path_match.group(2)[1:]) < 1:
        return False
    expected_task = f"{path_match.group(1)}-{path_match.group(2)}"
    receipt_text = receipt_path.read_text(encoding="utf-8")
    receipt = _record_metadata(receipt_text)
    header = receipt_text.splitlines()[0]
    required_runtime = ("resolved provider", "resolved model", "resolved effort", "runtime mode", "runtime version", "adapter version")
    task_path = receipt_path.with_name("TASK.md")
    output_path = receipt_path.with_name("OUTPUT.md")
    if not task_path.exists() or not output_path.exists():
        return False
    task_text = task_path.read_text(encoding="utf-8")
    task = _preamble_metadata(task_text)
    output_text = output_path.read_text(encoding="utf-8")
    output = _preamble_metadata(output_text)
    binding_packet = "\n".join(
        (
            task.get("preallocated artifacts", ""),
            _section(task_text, "Authoritative inputs"),
            _section(task_text, "Context packet"),
            _section(task_text, "Write boundary"),
        )
    )
    target_claim = _id_in(labels.get("target claim"), "CLM")
    target_revision = _integer_in(labels.get("target claim revision"))
    target_digest = labels.get("target statement digest", "")
    target_evidence_revision = _integer_in(labels.get("target evidence revision"))
    target_evidence_digest = labels.get("target evidence digest", "")
    requested_profile = labels.get("requested profile", "").casefold().strip("` ")
    review_contract_revision = _integer_in(labels.get("contract revision"))
    task_contract_revision = _integer_in(task.get("contract revision"))
    task_link_targets = _markdown_link_paths(task_path, binding_packet)
    target_claim_path = (root / "research/claims" / f"{target_claim}.md").resolve(strict=False) if target_claim else None
    target_canonical = {target_claim: target_claim_path} if target_claim and target_claim_path else {}
    review_materials = _section(review_path.read_text(encoding="utf-8"), "Materials supplied")
    receipt_inputs = _section(receipt_text, "Authoritative inputs received")
    receipt_input_paths = _markdown_link_paths(receipt_path, receipt_inputs)
    task_binding_valid = (
        target_claim is not None
        and target_revision is not None and target_revision >= 1
        and target_evidence_revision is not None and target_evidence_revision >= 1
        and _exact_canonical_linked_id(
            review_path, labels.get("target claim", ""), "CLM", target_canonical,
        ) == target_claim
        and target_claim in binding_packet
        and _canonical_link_occurrences(task_path, binding_packet, target_claim, target_canonical) >= 1
        and _canonical_link_occurrences(review_path, review_materials, target_claim, target_canonical) == 1
        and re.search(rf"(?i)claim\s+revision\s*[:#]?\s*{target_revision}\b", binding_packet) is not None
        and target_digest in binding_packet
        and re.search(rf"(?i)evidence\s+revision\s*[:#]?\s*{target_evidence_revision}\b", binding_packet) is not None
        and target_evidence_digest in binding_packet
        and review_contract_revision is not None
        and task_contract_revision == review_contract_revision
        and (root / "PROJECT.md").resolve(strict=False) in task_link_targets
        and (root / "PROJECT.md").resolve(strict=False) in receipt_input_paths
        and _canonical_link_occurrences(
            receipt_path, receipt_inputs, target_claim, target_canonical,
        ) == 1
        and re.search(rf"(?i)contract\s+revision\s*[:#]?\s*{review_contract_revision}\b", binding_packet) is not None
        and review_id in binding_packet
        and task.get("fresh context required", "").casefold() in {"yes", "true"}
        and task.get("requested profile", "").casefold().strip("` ") == requested_profile
        and task.get("status", "").casefold() == "completed"
        and output.get("status", "").casefold() == "completed"
        and (
            (labels.get("verdict", "").casefold() in {"pass", "passed"} and output.get("outcome classification", "").casefold() == "supported")
            or (labels.get("verdict", "").casefold() not in {"pass", "passed"} and output.get("outcome classification", "").casefold() in {"supported", "refuted", "inconclusive", "requiring verification"})
        )
    )
    adapter_version = receipt.get("adapter version", "").strip()
    recorded_mapping = _recorded_adapter_mapping(
        root, adapter_version, receipt.get("resolved provider", ""), requested_profile,
    )
    actual_mapping = (
        receipt.get("resolved model", "").casefold().strip("` "),
        receipt.get("resolved effort", "").casefold().strip("` "),
    )
    receipt_sections_final = all(
        not _unfinished_section(_section(receipt_text, heading))
        for heading in ("Authoritative inputs received", "Permitted write boundary", "Invocation summary", "Failure or substitution details", "Integrity attestation")
    )
    receipt_integrity = all(
        receipt.get(field, "").casefold() in {"yes", "true"}
        for field in (
            "stayed within write boundary", "no target claim edited during verification",
            "no completed evidence overwritten", "no git operation performed",
        )
    )
    output_section_names = (
        "Exact supported conclusions", "Evidence or derivation",
        "Assumptions, scope, and exceptional cases", "Uncertainties and verification needs",
        "Artifacts written", "Recommended next action",
    )
    passing_verdict = labels.get("verdict", "").casefold() in {"pass", "passed"}
    output_sections_final = all(
        not (
            _unfinished_substantive_section(_section(output_text, heading))
            if passing_verdict and heading in {"Exact supported conclusions", "Evidence or derivation"}
            else _unfinished_section(_section(output_text, heading))
        )
        for heading in output_section_names
    )
    return (
        bool(re.match(rf"^#\s+{re.escape(expected_task)}\b", header))
        and _exact_task_reference(receipt_path, receipt.get("task", ""), expected_task)
        and _exact_task_reference(output_path, output.get("task", ""), expected_task)
        and receipt.get("status", "").casefold() == "completed"
        and receipt.get("fresh context", "").casefold() in {"yes", "true"}
        and receipt.get("requested profile", "").casefold().strip("` ")
            == labels.get("requested profile", "").casefold().strip("` ")
        and bool(adapter_version)
        and all(receipt.get(field, "").casefold().strip() not in {"", "pending", "unknown"} for field in required_runtime)
        and receipt.get("runtime failure", "").casefold().strip() in {"none", "not applicable"}
        and receipt.get("substitution", "").casefold().strip() in {"none", "not applicable"}
        and recorded_mapping is not None
        and actual_mapping == recorded_mapping
        and task_binding_valid
        and receipt_sections_final
        and receipt_integrity
        and output_sections_final
    )


def _current_passing_review_ids(
    root: Path, claim_id: str, claim_path: Path, canonical: Mapping[str, Path]
) -> set[str]:
    claim_text = claim_path.read_text(encoding="utf-8")
    claim = _record_metadata(claim_text)
    if claim.get("status", "").casefold() != "validated":
        return set()
    revision = _integer_in(claim.get("claim revision"))
    digest = claim_digest(claim_text).casefold()
    current_evidence_revision = _integer_in(claim.get("evidence revision"))
    current_evidence_digest = evidence_digest(claim_text).casefold()
    claim_contract_revision = _integer_in(claim.get("contract revision"))
    required_profile = claim.get("required review profile", "").casefold().strip("` ")
    if (
        revision is None or revision < 1
        or current_evidence_revision is None or current_evidence_revision < 1
        or claim.get("statement digest", "").casefold() != digest
        or claim.get("evidence digest", "").casefold() != current_evidence_digest
    ):
        return set()
    result: set[str] = set()
    for review_id, review_path in canonical.items():
        if not review_id.startswith("REV-"):
            continue
        review_text = review_path.read_text(encoding="utf-8")
        review = _record_metadata(review_text)
        if (
            _exact_canonical_linked_id(
                review_path, review.get("target claim", ""), "CLM", canonical,
            ) == claim_id
            and _integer_in(review.get("target claim revision")) == revision
            and review.get("target statement digest", "").casefold() == digest
            and _integer_in(review.get("target evidence revision")) == current_evidence_revision
            and review.get("target evidence digest", "").casefold() == current_evidence_digest
            and review.get("requested profile", "").casefold().strip("` ") == required_profile
            and _integer_in(review.get("contract revision")) == claim_contract_revision
            and review.get("verdict", "").casefold() in {"pass", "passed"}
            and review.get("status", "").casefold() == "completed"
            and review.get("fresh context", "").casefold() in {"yes", "true"}
            and _review_receipt_valid(review_id, review_path, review)
            and _review_fidelity_complete(review_text)
            and all(
                review.get(field, "").casefold() in {"yes", "true"}
                for field in (
                    "evidence or proof correct", "establishes exact recorded statement",
                    "addresses intended project question at stated scope", "assumptions accounted for",
                    "quantifier order checked", "scope restrictions checked", "exceptional cases checked",
                )
            )
        ):
            result.add(review_id)
    return result


def _linked_claim_destinations(source: Path, value: str, canonical: Mapping[str, Path]) -> set[str]:
    return _canonical_linked_ids(source, value, "CLM", canonical)


def _dependency_cycle_members(graph: Mapping[str, set[str]]) -> list[frozenset[str]]:
    """Return nontrivial strongly connected components of a claim graph."""
    index = 0
    indices: dict[str, int] = {}
    lowlinks: dict[str, int] = {}
    stack: list[str] = []
    on_stack: set[str] = set()
    cycles: list[frozenset[str]] = []

    def connect(node: str) -> None:
        nonlocal index
        indices[node] = lowlinks[node] = index
        index += 1
        stack.append(node)
        on_stack.add(node)
        for successor in graph.get(node, set()):
            if successor not in indices:
                connect(successor)
                lowlinks[node] = min(lowlinks[node], lowlinks[successor])
            elif successor in on_stack:
                lowlinks[node] = min(lowlinks[node], indices[successor])
        if lowlinks[node] != indices[node]:
            return
        component: set[str] = set()
        while stack:
            member = stack.pop()
            on_stack.remove(member)
            component.add(member)
            if member == node:
                break
        if len(component) > 1:
            cycles.append(frozenset(component))

    for node in graph:
        if node not in indices:
            connect(node)
    return cycles


def _check_trusted_result_surfaces(
    root: Path, report: CheckReport, canonical: Mapping[str, Path]
) -> None:
    surfaces: list[tuple[Path, str]] = []
    for relative in ("STATE.md", "OVERVIEW.md"):
        path = root / relative
        if path.exists() and _contract_accepted(root):
            surfaces.append((path, _section(path.read_text(encoding="utf-8"), "Strongest validated results")))
    for ident, path in canonical.items():
        if not ident.startswith("RPT-"):
            continue
        text = path.read_text(encoding="utf-8")
        if _record_metadata(text).get("status", "").casefold() == "published":
            surfaces.append((path, _section(text, "Strongest validated results")))
    for surface, section in surfaces:
        linked_claims = _linked_claim_destinations(surface, section, canonical)
        normalized = re.sub(r"\s+", " ", section).casefold().strip(" `-*\n.!:")
        explicit_none = normalized == "none"
        if not explicit_none and not linked_claims:
            report.add(
                "error", "trusted-result-surface-unstructured",
                "Strongest validated results must say exactly `none` or canonically link at least one current validated CLM artifact",
                surface,
            )
        declared_claims = set(
            re.findall(r"\bCLM-\d{4,}(?!-[A-Za-z0-9])\b", section)
        )
        if declared_claims.difference(linked_claims):
            report.add(
                "error", "trusted-result-surface-unstructured",
                "Strongest validated results contains a bare or noncanonical claim ID",
                surface,
            )
        for claim_id in sorted(linked_claims):
            claim_path = canonical[claim_id]
            if not _current_passing_review_ids(root, claim_id, claim_path, canonical):
                report.add(
                    "error", "trusted-result-not-validated",
                    f"Strongest validated results links {claim_id}, but it is not validated by a current fresh passing review",
                    surface,
                )


def _check_claims_reviews(root: Path, report: CheckReport, canonical: Mapping[str, Path]) -> None:
    claims = {ident: path for ident, path in canonical.items() if ident.startswith("CLM-")}
    reviews: list[ReviewRecord] = []
    for ident, path in canonical.items():
        if not ident.startswith("REV-"):
            continue
        review_text = path.read_text(encoding="utf-8")
        labels = _record_metadata(review_text)
        exact_target = _exact_canonical_linked_id(
            path, labels.get("target claim", ""), "CLM", canonical,
        )
        reviews.append(ReviewRecord(
            ident, path, exact_target,
            _integer_in(labels.get("target claim revision")),
            labels.get("target statement digest", "").casefold(),
            _integer_in(labels.get("target evidence revision")),
            labels.get("target evidence digest", "").casefold(), labels.get("verdict", "").casefold(),
            labels.get("status", "").casefold(), labels.get("fresh context", "").casefold(),
            labels.get("task receipt", "").strip(), labels.get("requested profile", "").casefold().strip("` "),
            _review_receipt_valid(ident, path, labels),
            labels.get("evidence or proof correct", "").casefold() in {"yes", "true"},
            labels.get("establishes exact recorded statement", "").casefold() in {"yes", "true"},
            labels.get("addresses intended project question at stated scope", "").casefold() in {"yes", "true"},
            all(
                labels.get(field, "").casefold() in {"yes", "true"}
                for field in ("assumptions accounted for", "quantifier order checked", "scope restrictions checked", "exceptional cases checked")
            ),
        ))

    valid_reviews: dict[str, list[ReviewRecord]] = {}
    receipt_users: dict[Path, list[str]] = {}
    for review in reviews:
        labels = _record_metadata(review.path.read_text(encoding="utf-8"))
        receipt_path = _review_receipt_path(review.path, labels)
        if receipt_path is not None and review.status == "completed":
            receipt_users.setdefault(receipt_path, []).append(review.ident)
    for receipt_path, users in receipt_users.items():
        if len(users) > 1:
            for review_id in users:
                report.add("error", "review-receipt-reused", f"completed reviews {', '.join(users)} reuse one verification receipt", next(review.path for review in reviews if review.ident == review_id))
    for review in reviews:
        if review.revision is None or review.revision < 1:
            report.add(
                "error", "invalid-review-target-revision",
                f"{review.ident} must record Target claim revision >= 1",
                review.path,
            )
        if review.evidence_revision is None or review.evidence_revision < 1:
            report.add(
                "error", "invalid-review-target-evidence-revision",
                f"{review.ident} must record Target evidence revision >= 1",
                review.path,
            )
        if review.target is None or review.target not in claims:
            report.add(
                "error", "review-target-missing",
                f"{review.ident} must contain exactly one canonical Target claim link whose label and destination name the same existing claim",
                review.path,
            )
            continue
        claim_path = claims[review.target]
        claim_text = claim_path.read_text(encoding="utf-8")
        labels = _record_metadata(claim_text)
        revision = _integer_in(labels.get("claim revision"))
        digest = claim_digest(claim_text)
        current_evidence_revision = _integer_in(labels.get("evidence revision"))
        current_evidence_digest = evidence_digest(claim_text)
        review_labels = _record_metadata(review.path.read_text(encoding="utf-8"))
        claim_contract_revision = _integer_in(labels.get("contract revision"))
        review_contract_revision = _integer_in(review_labels.get("contract revision"))
        if review_contract_revision != claim_contract_revision:
            report.add(
                "error", "review-claim-contract-mismatch",
                f"{review.ident} covers contract revision {review_contract_revision}, but {review.target} records contract revision {claim_contract_revision}",
                review.path,
            )
        receipt_is_real = review.receipt_valid
        if review.status == "completed":
            review_text = review.path.read_text(encoding="utf-8")
            if review.fresh_context not in {"yes", "true"}:
                report.add("error", "nonfresh-completed-review", f"{review.ident} is completed without confirming a fresh context", review.path)
            if not receipt_is_real:
                report.add("error", "completed-review-receipt-missing", f"{review.ident} is completed without a completed fresh matching-profile task receipt", review.path)
            assessment_fields = (
                "evidence or proof correct", "establishes exact recorded statement",
                "addresses intended project question at stated scope", "assumptions accounted for",
                "quantifier order checked", "scope restrictions checked", "exceptional cases checked",
            )
            for field in assessment_fields:
                if review_labels.get(field, "").casefold().strip("` .") not in {"yes", "no", "true", "false"}:
                    report.add("error", "completed-review-assessment-incomplete", f"{review.ident} leaves `{field}` unfinished", review.path)
            for field in ("correctness rationale", "fidelity rationale", "findings"):
                if _unfinished_value(review_labels.get(field, "")):
                    report.add("error", "completed-review-assessment-incomplete", f"{review.ident} leaves substantive `{field}` unfinished", review.path)
            substantive_review_headings = (
                "Materials supplied", "Independence statement", "Verification approach",
                "Correctness assessment", "Claim-fidelity assessment",
                "Assumption, quantifier, and scope audit",
                "Falsification and counterexample attempts", "Verdict rationale",
            )
            for heading in substantive_review_headings:
                if _unfinished_substantive_section(_section(review_text, heading)):
                    report.add("error", "completed-review-assessment-incomplete", f"{review.ident} leaves `## {heading}` unfinished", review.path)
            for heading in ("Reproduction or source checks", "Required corrections or follow-up"):
                if _unfinished_section(_section(review_text, heading)):
                    report.add("error", "completed-review-assessment-incomplete", f"{review.ident} leaves `## {heading}` unfinished", review.path)
            materials = _section(review.path.read_text(encoding="utf-8"), "Materials supplied")
            if _canonical_link_occurrences(
                review.path, materials, review.target, {review.target: claim_path},
            ) != 1:
                report.add(
                    "error", "completed-review-materials-invalid",
                    f"{review.ident} Materials supplied must contain exactly one canonical link labeled {review.target}",
                    review.path,
                )
        historical_statement = review.revision is not None and revision is not None and review.revision < revision
        historical_evidence = (
            review.evidence_revision is not None
            and current_evidence_revision is not None
            and review.evidence_revision < current_evidence_revision
        )
        statement_not_future = review.revision is not None and revision is not None and review.revision <= revision
        evidence_not_future = (
            review.evidence_revision is not None
            and current_evidence_revision is not None
            and review.evidence_revision <= current_evidence_revision
        )
        if (historical_statement or historical_evidence) and statement_not_future and evidence_not_future:
            # Historical reviews remain auditable records but do not cover the
            # current claim/evidence revision.
            continue
        if review.revision != revision:
            report.add("error", "future-review-revision", f"{review.ident} covers revision {review.revision}, but {review.target} is revision {revision}", review.path)
        if review.revision == revision and review.digest != digest.casefold():
            report.add("error", "stale-review-digest", f"{review.ident} digest does not match the current statement and assumptions ({digest})", review.path)
        if review.evidence_revision != current_evidence_revision:
            report.add(
                "error", "future-review-evidence-revision",
                f"{review.ident} covers evidence revision {review.evidence_revision}, but {review.target} is evidence revision {current_evidence_revision}",
                review.path,
            )
        if review.evidence_revision == current_evidence_revision and review.evidence_digest != current_evidence_digest.casefold():
            report.add(
                "error", "stale-review-evidence-digest",
                f"{review.ident} evidence digest does not match the current evidence, derivation, and dependencies ({current_evidence_digest})",
                review.path,
            )
        if review.verdict in {"pass", "passed"} and review.status != "completed":
            report.add("error", "incomplete-passing-review", f"{review.ident} says pass but Status is `{review.status or 'missing'}`", review.path)
        if review.verdict in {"pass", "passed"} and review.fresh_context not in {"yes", "true"}:
            report.add("error", "nonfresh-passing-review", f"{review.ident} says pass without confirming a fresh context", review.path)
        if review.verdict in {"pass", "passed"} and not receipt_is_real:
            report.add("error", "passing-review-receipt-missing", f"{review.ident} says pass without a completed fresh matching-profile task receipt", review.path)
        if review.verdict in {"pass", "passed"} and not (
            review.correctness_yes and review.exact_statement_yes and review.project_scope_yes and review.audit_yes
        ):
            report.add("error", "passing-review-assessment-incomplete", f"{review.ident} says pass without affirmative correctness, fidelity, and assumption/quantifier/scope/exception audits", review.path)
        if (
            review.verdict in {"pass", "passed"}
            and review.status == "completed"
            and review.fresh_context in {"yes", "true"}
            and receipt_is_real
            and review.correctness_yes
            and review.exact_statement_yes
            and review.project_scope_yes
            and review.audit_yes
            and review.revision == revision
            and review.digest == digest.casefold()
            and review.evidence_revision == current_evidence_revision
            and review.evidence_digest == current_evidence_digest.casefold()
            and review_contract_revision == claim_contract_revision
            and _review_fidelity_complete(review_text)
        ):
            valid_reviews.setdefault(review.target, []).append(review)

    for ident, path in claims.items():
        text = path.read_text(encoding="utf-8")
        labels = _record_metadata(text)
        status = labels.get("status", "").casefold()
        kind = labels.get("claim kind", "").casefold()
        evidence = labels.get("evidence class", "").casefold()
        recorded_digest = labels.get("statement digest", "").casefold()
        computed_digest = claim_digest(text).casefold()
        evidence_revision = _integer_in(labels.get("evidence revision"))
        recorded_evidence_digest = labels.get("evidence digest", "").casefold()
        computed_evidence_digest = evidence_digest(text).casefold()
        required_profile = labels.get("required review profile", "").casefold().strip("` ")
        dependency_section = _section(text, "Dependencies")
        declared_dependencies = set(
            re.findall(r"\bCLM-\d{4,}(?!-[A-Za-z0-9])\b", dependency_section)
        )
        linked_dependencies = _linked_claim_destinations(path, dependency_section, canonical)
        for dependency_id in sorted(declared_dependencies.difference(linked_dependencies)):
            report.add(
                "error", "noncanonical-claim-dependency",
                f"{ident} names dependency {dependency_id} without a canonical Markdown link whose label and destination agree",
                path,
            )
        if required_profile not in {"substantive", "deep", "pivotal"}:
            report.add("error", "invalid-required-review-profile", f"{ident} has invalid required review profile `{required_profile}`", path)
        if recorded_digest not in {"", "pending"} and recorded_digest != computed_digest:
            report.add("error", "stale-claim-digest", f"{ident} records a digest that does not match its exact statement and assumptions ({computed_digest})", path)
        if status in {"under review", "validated"} and recorded_digest != computed_digest:
            report.add("error", "missing-claim-digest", f"{ident} must record its current digest before review or validation", path)
        if evidence_revision is None or evidence_revision < 1:
            report.add("error", "invalid-evidence-revision", f"{ident} must record a positive numeric Evidence revision", path)
        if recorded_evidence_digest not in {"", "pending"} and recorded_evidence_digest != computed_evidence_digest:
            report.add(
                "error", "stale-claim-evidence-digest",
                f"{ident} records an Evidence digest that does not match its evidence, derivation, and dependencies ({computed_evidence_digest})",
                path,
            )
        if status in {"under review", "validated"} and recorded_evidence_digest != computed_evidence_digest:
            report.add(
                "error", "missing-claim-evidence-digest",
                f"{ident} must record its current Evidence digest before review or validation",
                path,
            )
        matching_reviews = [review for review in valid_reviews.get(ident, ()) if review.requested_profile == required_profile]
        if status == "validated" and not matching_reviews:
            report.add("error", "validated-without-review", f"{ident} is validated without a fresh completed passing `{required_profile}` review bound to this exact revision and digest", path)
        if status == "validated":
            review_section = _section(text, "Independent reviews")
            manuscript_section = _section(text, "Manuscript locations")
            if _unfinished_section(review_section):
                report.add("error", "validated-claim-review-index-incomplete", f"{ident} leaves its Independent reviews index unfinished", path)
            linked_reviews = _canonical_linked_ids(path, review_section, "REV", canonical)
            valid_review_ids = {review.ident for review in matching_reviews}
            if valid_review_ids and not valid_review_ids.intersection(linked_reviews):
                report.add("error", "validated-claim-review-index-incomplete", f"{ident} does not link a current passing `{required_profile}` review from Independent reviews", path)
            if _unfinished_section(manuscript_section):
                report.add("error", "validated-claim-manuscript-index-incomplete", f"{ident} leaves Manuscript locations as a template prompt; write `none` or link exact locations", path)
            dependencies = linked_dependencies
            for dependency_id in sorted(dependencies):
                if dependency_id == ident:
                    report.add(
                        "error", "claim-self-dependency",
                        f"validated {ident} declares itself as a dependency",
                        path,
                    )
                dependency_path = claims[dependency_id]
                dependency_labels = _record_metadata(dependency_path.read_text(encoding="utf-8"))
                dependency_profile = dependency_labels.get("required review profile", "").casefold().strip("` ")
                dependency_reviews = [
                    review for review in valid_reviews.get(dependency_id, ())
                    if review.requested_profile == dependency_profile
                ]
                if dependency_labels.get("status", "").casefold() != "validated" or not dependency_reviews:
                    report.add(
                        "error", "unvalidated-claim-dependency",
                        f"validated {ident} depends on {dependency_id}, which lacks validated status and a current passing review",
                        path,
                    )
        mathematical_kind = any(token in kind for token in ("theorem", "lemma", "counterexample", "impossibility"))
        if status == "validated" and mathematical_kind and not _mathematical_evidence_class(evidence):
            report.add("error", "empirical-proof-promotion", f"{ident} is a mathematical claim validated only by `{evidence}`", path)

    current_validated: set[str] = set()
    for ident, path in claims.items():
        labels = _record_metadata(path.read_text(encoding="utf-8"))
        profile = labels.get("required review profile", "").casefold().strip("` ")
        if (
            labels.get("status", "").casefold() == "validated"
            and any(review.requested_profile == profile for review in valid_reviews.get(ident, ()))
        ):
            current_validated.add(ident)
    dependency_graph = {
        ident: _linked_claim_destinations(
            path, _section(path.read_text(encoding="utf-8"), "Dependencies"), canonical,
        ).intersection(current_validated)
        for ident, path in claims.items() if ident in current_validated
    }
    for cycle in _dependency_cycle_members(dependency_graph):
        ordered = sorted(cycle)
        report.add(
            "error", "claim-dependency-cycle",
            f"validated claim dependency cycle detected among: {', '.join(ordered)}",
            claims[ordered[0]],
        )


def _check_experiments(root: Path, report: CheckReport) -> None:
    seen: dict[str, Path] = {}
    pattern = re.compile(r"\b(EXP-\d{4,}-E\d{3,})\b")
    for readme in (root / "experiments").glob("EXP-*/README.md") if (root / "experiments").exists() else ():
        for directory_name in ("code", "inputs", "executions"):
            if not (readme.parent / directory_name).is_dir():
                report.add("error", "experiment-directory-missing", f"experiment is missing `{directory_name}/`", readme)
        rows: list[str] = []
        execution_id_cells: dict[str, str] = {}
        execution_rows: dict[str, dict[str, str]] = {}
        execution_headers: list[str] | None = None
        for line in readme.read_text(encoding="utf-8").splitlines():
            cells = _split_table_row(line)
            if cells and any(_normal_header(cell) == "execution id" for cell in cells):
                execution_headers = [_normal_header(cell) for cell in cells]
                continue
            execution_match = pattern.search(cells[0]) if cells else None
            if cells and execution_match:
                execution_id = execution_match.group(1)
                rows.append(execution_id)
                execution_id_cells[execution_id] = cells[0].strip()
                if execution_headers and len(cells) == len(execution_headers):
                    execution_rows[execution_id] = dict(zip(execution_headers, cells))
        local: set[str] = set()
        experiment_id = readme.parent.name
        for execution_id in rows:
            if not execution_id.startswith(experiment_id + "-E"):
                report.add("error", "execution-parent-mismatch", f"execution {execution_id} is listed under {experiment_id}", readme)
            if execution_id in local:
                report.add("error", "duplicate-execution", f"execution table lists {execution_id} more than once", readme)
            local.add(execution_id)
            if execution_id in seen and seen[execution_id] != readme:
                report.add("error", "duplicate-execution", f"execution {execution_id} is also listed in {seen[execution_id].relative_to(root)}", readme)
            seen[execution_id] = readme

        execution_numbers = sorted(int(value.rsplit("E", 1)[1]) for value in local)
        if execution_numbers and execution_numbers != list(range(1, max(execution_numbers) + 1)):
            report.add("error", "execution-id-gap", f"execution IDs are not monotonic/gap-free: {execution_numbers}", readme)

        executions_dir = readme.parent / "executions"
        marker_ids: set[str] = set()
        marker_labels_by_id: dict[str, dict[str, str]] = {}
        if executions_dir.exists():
            disk_ids = [path.name for path in executions_dir.iterdir() if pattern.fullmatch(path.name)]
            for execution_id in disk_ids:
                if execution_id not in local:
                    report.add("warning", "unindexed-execution", f"execution directory {execution_id} is not in the README execution table", readme)
            for marker in executions_dir.glob("*/COMPLETED.md"):
                execution_id = marker.parent.name
                if pattern.fullmatch(execution_id) is None:
                    report.add("error", "invalid-execution-manifest-path", f"completion manifest is under noncanonical execution directory `{execution_id}`", marker)
                    continue
                marker_ids.add(execution_id)
                marker_symlink = _symlink_component(root, marker.relative_to(root))
                if marker_symlink is not None:
                    report.add(
                        "error", "execution-manifest-symlinked",
                        f"{execution_id} completion path traverses symlink `{marker_symlink.relative_to(root).as_posix()}`",
                        marker_symlink,
                    )
                try:
                    marker_link_count = marker.stat().st_nlink
                except OSError:
                    marker_link_count = 0
                if marker_link_count != 1:
                    report.add(
                        "error", "execution-manifest-hardlinked",
                        f"{execution_id} completion manifest must have exactly one filesystem link",
                        marker,
                    )
                marker_text = marker.read_text(encoding="utf-8")
                first = marker_text.splitlines()[0] if marker_text.splitlines() else ""
                if re.match(rf"^#\s+{re.escape(execution_id)}(?=\s|$)", first) is None:
                    report.add("error", "invalid-execution-manifest", f"completion manifest heading does not declare {execution_id}", marker)
                marker_labels = _preamble_metadata(marker_text)
                marker_labels_by_id[execution_id] = marker_labels
                required_manifest_labels = (
                    "Execution ID", "Completed", "Command/config", "Inputs", "Outputs", "Output digest", "Result",
                )
                for field in required_manifest_labels:
                    normalized = _normal_header(field)
                    if normalized not in marker_labels:
                        report.add("error", "invalid-execution-manifest", f"completion manifest lacks `{field}`", marker)
                        continue
                    allow_na = normalized == "output digest"
                    if _unfinished_value(marker_labels[normalized], allow_none=allow_na):
                        report.add("error", "invalid-execution-manifest", f"completion manifest leaves `{field}` unresolved", marker)
                recorded_execution = re.search(r"\bEXP-\d{4,}-E\d{3,}\b", marker_labels.get("execution id", ""))
                if recorded_execution is None or recorded_execution.group(0) != execution_id:
                    report.add("error", "invalid-execution-manifest", f"completion manifest Execution ID does not match directory {execution_id}", marker)
        for execution_id in local.difference(marker_ids):
            report.add("error", "execution-manifest-missing", f"indexed execution {execution_id} has no immutable COMPLETED.md manifest", readme)
        for execution_id in marker_ids.difference(local):
            report.add("error", "execution-manifest-unindexed", f"completion manifest {execution_id} has no execution-table row", readme)
        for execution_id in local:
            manifest = executions_dir / execution_id / "COMPLETED.md"
            links = re.findall(r"\[([^\]]+)\]\(([^)]+)\)", execution_id_cells.get(execution_id, ""))
            link_valid = len(links) == 1 and links[0][0].strip("` ") == execution_id and (
                readme.parent / unquote(links[0][1].split("#", 1)[0]).strip("<>")
            ).resolve(strict=False) == manifest.resolve(strict=False)
            if not link_valid:
                report.add(
                    "error", "execution-manifest-link-invalid",
                    f"{execution_id} execution-table ID must be one canonical link to its COMPLETED.md manifest",
                    readme,
                )
            marker_labels = marker_labels_by_id.get(execution_id)
            row = execution_rows.get(execution_id)
            if marker_labels is None or row is None:
                continue

            def normalized(value: str) -> str:
                plain = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", value)
                return re.sub(r"\s+", " ", plain).casefold().strip(" `")

            bindings = {
                "command config": "command config", "inputs": "inputs",
                "outputs": "outputs", "output digest": "output digest", "result": "result",
            }
            for row_field, manifest_field in bindings.items():
                if normalized(row.get(row_field, "")) != normalized(marker_labels.get(manifest_field, "")):
                    report.add(
                        "error", "execution-manifest-row-mismatch",
                        f"{execution_id} `{row_field}` differs between README row and immutable manifest",
                        readme,
                    )
            row_date = normalized(row.get("date", ""))
            completed = normalized(marker_labels.get("completed", ""))
            if not row_date or not (completed == row_date or completed.startswith(row_date + "t")):
                report.add(
                    "error", "execution-manifest-row-mismatch",
                    f"{execution_id} Date differs from manifest Completed value",
                    readme,
                )
        labels = _record_metadata(readme.read_text(encoding="utf-8"))
        if labels.get("status", "").casefold() == "blocked" and (rows or marker_ids):
            report.add(
                "error", "blocked-experiment-has-executions",
                "blocked experiment must preserve its blocker before any execution is recorded; create a successor experiment to run a revised protocol",
                readme,
            )
        if labels.get("status", "").casefold() == "completed":
            if not rows:
                report.add("error", "completed-experiment-empty", "completed experiment has no execution row", readme)
            readme_text = readme.read_text(encoding="utf-8")
            nested_specs: tuple[tuple[str, tuple[tuple[str, bool], ...]], ...] = (
                ("Evidentiary meaning", (
                    ("a positive outcome would establish", False),
                    ("a positive outcome would not establish", False),
                    ("a negative outcome would establish", False),
                    ("a negative outcome would not establish", False),
                )),
                ("Entry point and commands", (
                    ("entry point", False), ("canonical command", False),
                    ("working directory", False),
                )),
                ("Environment and dependencies", (
                    ("operating system/runtime", False), ("language and version", False),
                    ("dependency manifest", True), ("relevant library versions", True),
                )),
                ("Input and source-data provenance", (
                    ("inputs", False), ("source", False),
                    ("license or access constraints", True),
                    ("integrity digest or version", False),
                    ("protected source-data location", False),
                    ("derived-data location", False),
                )),
                ("Parameters, seeds, and hardware", (
                    ("parameters/configuration", False), ("random seeds", True),
                    ("hardware", True), ("nondeterminism notes", True),
                )),
                ("Evidence preservation notes", (
                    ("completed executions unchanged", False),
                    ("corrections or superseding executions", True),
                    ("hidden expected conclusions absent", False),
                )),
            )
            for heading, fields in nested_specs:
                section_labels = _metadata(_section(readme_text, heading))
                for label, allow_none in fields:
                    if _unfinished_value(section_labels.get(label, ""), allow_none=allow_none):
                        report.add(
                            "error", "completed-experiment-incomplete",
                            f"completed experiment leaves `{label}` unresolved in `## {heading}`",
                            readme,
                        )
            substantive_headings = {
                "Research question", "Protocol", "Evidentiary meaning",
                "Entry point and commands", "Environment and dependencies",
                "Input and source-data provenance", "Parameters, seeds, and hardware",
                "Interpretation", "Evidence preservation notes",
            }
            for heading in ARTIFACT_REQUIRED_HEADINGS["EXP"]:
                section = _section(readme_text, heading)
                unfinished = (
                    _unfinished_substantive_section(section)
                    if heading in substantive_headings else _unfinished_section(section)
                )
                if unfinished:
                    report.add("error", "completed-experiment-incomplete", f"completed experiment has unfinished `## {heading}`", readme)
            for execution_id in rows:
                if execution_id not in execution_rows:
                    report.add("error", "completed-execution-incomplete", f"{execution_id} does not have every execution-table column", readme)
            for execution_id, row in execution_rows.items():
                for column in ("date", "command config", "inputs", "outputs", "output digest", "result"):
                    value = row.get(column, "").casefold().strip()
                    allowed_na = column == "output digest" and value == "not applicable"
                    if not allowed_na and value in {"", "pending", "unknown", "none", "not applicable"}:
                        report.add("error", "completed-execution-incomplete", f"{execution_id} leaves `{column}` unresolved", readme)
                if not (readme.parent / "executions" / execution_id).is_dir():
                    report.add("error", "execution-evidence-missing", f"{execution_id} has no immutable execution directory", readme)
            for field in ("completed executions unchanged", "hidden expected conclusions absent"):
                if labels.get(field, "").casefold() not in {"yes", "true"}:
                    report.add("error", "completed-experiment-incomplete", f"completed experiment does not attest `{field}`", readme)


def _check_bibliography(root: Path, report: CheckReport) -> None:
    bibliography = root / "literature/references.bib"
    if not bibliography.exists():
        return
    keys: dict[str, list[str]] = {}
    for value in re.findall(
        r"(?mi)@\w+\s*\{\s*([^,\s]+)\s*,",
        bibliography.read_text(encoding="utf-8"),
    ):
        keys.setdefault(value.casefold(), []).append(value)
    for normalized, spellings in sorted(keys.items()):
        if len(spellings) > 1:
            report.add(
                "error", "duplicate-bibtex-key",
                f"BibTeX key `{normalized}` occurs {len(spellings)} times case-insensitively: {', '.join(spellings)}",
                bibliography,
            )


def _tex_labels(root: Path) -> set[str]:
    labels: set[str] = set()
    paper = root / "paper"
    if not paper.exists():
        return labels
    for path in _walk_project_files(paper):
        if path.suffix.casefold() == ".tex":
            labels.update(re.findall(r"\\label\{([^}]+)\}", _strip_tex_comments(path.read_text(encoding="utf-8"))))
    return labels


def _strip_tex_comments(text: str) -> str:
    r"""Strip unescaped TeX comments while preserving line structure.

    A percent sign starts a comment when preceded by an even number of
    consecutive backslashes.  Thus ``\%`` is content and ``\\%`` starts a
    comment after a literal backslash.
    """
    rendered: list[str] = []
    for line in text.splitlines(keepends=True):
        cutoff = len(line)
        for index, character in enumerate(line):
            if character != "%":
                continue
            backslashes = 0
            cursor = index - 1
            while cursor >= 0 and line[cursor] == "\\":
                backslashes += 1
                cursor -= 1
            if backslashes % 2 == 0:
                cutoff = index
                break
        prefix = line[:cutoff]
        if cutoff < len(line) and line.endswith("\n"):
            prefix += "\n"
        rendered.append(prefix)
    return "".join(rendered)


def _check_paper_inputs(root: Path, report: CheckReport) -> None:
    """Require static ``input``/``include`` targets to stay inside ``paper/``."""
    paper = root / "paper"
    if not paper.exists():
        return
    paper_resolved = paper.resolve(strict=False)
    for source in _walk_project_files(paper):
        if source.suffix.casefold() != ".tex":
            continue
        text = _strip_tex_comments(source.read_text(encoding="utf-8"))
        for match in re.finditer(
            r"\\(input|include)(?![A-Za-z@])\s*(?:\{([^}]*)\}|([^\s%{}]+))", text,
        ):
            command = match.group(1)
            raw_target = match.group(2) if match.group(2) is not None else match.group(3)
            target_text = raw_target.strip()
            if not target_text or re.search(r"[\\{}$#]", target_text):
                report.add(
                    "error", "paper-input-unresolvable",
                    f"\\{command} target must be a static relative path: `{raw_target}`",
                    source,
                )
                continue
            target = source.parent / target_text
            if target.suffix == "":
                target = target.with_suffix(".tex")
            resolved = target.resolve(strict=False)
            try:
                resolved.relative_to(paper_resolved)
            except ValueError:
                report.add(
                    "error", "paper-input-escape",
                    f"\\{command} target escapes paper/: `{raw_target}`",
                    source,
                )
                continue
            if not resolved.is_file():
                report.add(
                    "error", "paper-input-missing",
                    f"\\{command} target does not resolve to a paper source: `{raw_target}`",
                    source,
                )


def _check_provenance(root: Path, report: CheckReport, canonical: Mapping[str, Path]) -> None:
    provenance = root / "paper/PROVENANCE.md"
    if not provenance.exists():
        return
    provenance_text = provenance.read_text(encoding="utf-8")
    for heading in (
        "Established manuscript items", "Open or explicitly provisional items",
        "Stale items requiring revision",
    ):
        count = _heading_count(provenance_text, heading)
        if count != 1:
            report.add(
                "error", "invalid-provenance-section-count",
                f"paper provenance must contain exactly one `## {heading}` section; found {count}",
                provenance,
            )
    tex_labels = _tex_labels(root)
    tex_occurrences: dict[str, list[Path]] = {}
    tex_environments: dict[str, list[str]] = {}
    paper_root = root / "paper"
    for tex_path in _walk_project_files(paper_root) if paper_root.exists() else ():
        if tex_path.suffix.casefold() != ".tex":
            continue
        tex_source = _strip_tex_comments(tex_path.read_text(encoding="utf-8"))
        for latex_label in re.findall(r"\\label\{([^}]+)\}", tex_source):
            tex_occurrences.setdefault(latex_label, []).append(tex_path)
        for item in re.finditer(
            r"\\begin\{(theorem|lemma|proposition|corollary|conjecture|figure|table)\*?\}(.*?)"
            r"\\end\{\1\*?\}", tex_source, flags=re.DOTALL,
        ):
            for latex_label in re.findall(r"\\label\{([^}]+)\}", item.group(2)):
                tex_environments.setdefault(latex_label, []).append(item.group(1))
    for latex_label, locations in tex_occurrences.items():
        if len(locations) > 1:
            report.add(
                "error", "duplicate-latex-label",
                f"LaTeX label `{latex_label}` occurs {len(locations)} times",
                locations[0],
            )
    lines = provenance_text.splitlines()
    try:
        start, end = _section_bounds(lines, "Established manuscript items")
        table = _find_table(lines, start, end)
        label_column = _column(table.headers, ("LaTeX label", "Label"))
        claim_column = _column(table.headers, ("Claim", "Claim ID"))
        evidence_column = _column(table.headers, ("Evidence", "Evidence artifact"))
        review_column = _column(table.headers, ("Passing review", "Review", "Reviews"))
        role_column = _column(table.headers, ("Manuscript role", "Role"))
        status_column = _column(table.headers, ("Status",))
    except ResearchError as error:
        report.add("error", "invalid-provenance-table", str(error), provenance)
        return
    provisional_labels: set[str] = set()
    try:
        provisional_start, provisional_end = _section_bounds(lines, "Open or explicitly provisional items")
        provisional_table = _find_table(lines, provisional_start, provisional_end)
        provisional_label_column = _column(provisional_table.headers, ("LaTeX label", "Label"))
        provisional_source_column = _column(provisional_table.headers, ("Source artifact", "Source"))
        provisional_limitation_column = _column(provisional_table.headers, ("Limitation", "Limitations"))
        provisional_status_column = _column(provisional_table.headers, ("Status",))
    except ResearchError as error:
        report.add("error", "invalid-provisional-provenance-table", str(error), provenance)
        provisional_table = None
    if provisional_table is not None:
        for _, cells in provisional_table.rows:
            required_columns = (
                provisional_label_column, provisional_source_column,
                provisional_limitation_column, provisional_status_column,
            )
            if max(required_columns) >= len(cells):
                report.add("error", "invalid-provisional-provenance-row", "open/provisional row has too few columns", provenance)
                continue
            provisional_label = cells[provisional_label_column].strip().strip("`")
            if not provisional_label or provisional_label in provisional_labels:
                report.add("error", "duplicate-provisional-label", f"open/provisional provenance repeats or omits label `{provisional_label}`", provenance)
            provisional_labels.add(provisional_label)
            provisional_status = cells[provisional_status_column].casefold().strip("` ")
            if provisional_status not in {"open", "provisional", "explicitly provisional"}:
                report.add("error", "invalid-provisional-status", f"`{provisional_label}` lacks explicit open/provisional status", provenance)
            if _unfinished_value(cells[provisional_limitation_column]):
                report.add("error", "provisional-limitation-missing", f"`{provisional_label}` has no concrete limitation", provenance)
            source_links = re.findall(r"\[[^\]]+\]\(([^)]+)\)", cells[provisional_source_column])
            if not any(
                (provenance.parent / unquote(destination.split("#", 1)[0]).strip("<>")).resolve(strict=False)
                    in {path.resolve(strict=False) for path in canonical.values()}
                for destination in source_links
                if not destination.casefold().startswith(("http://", "https://"))
            ):
                report.add("error", "provisional-source-invalid", f"`{provisional_label}` lacks a resolvable source-artifact link", provenance)

    established_labels: set[str] = set()
    for _, cells in table.rows:
        if max(label_column, role_column, claim_column, evidence_column, review_column, status_column) >= len(cells):
            report.add("error", "invalid-provenance-row", "established-item row has too few columns", provenance)
            continue
        declared_claim_links = _declared_id_links(cells[claim_column], "CLM")
        canonical_claim_id = _exact_canonical_linked_id(
            provenance, cells[claim_column], "CLM", canonical,
        )
        claim_id = canonical_claim_id or _id_in(cells[claim_column], "CLM")
        review_ids = re.findall(r"\bREV-\d{4,}\b", cells[review_column])
        label_match = cells[label_column].strip().strip("`")
        manuscript_role = cells[role_column].casefold().strip("` ")
        if cells[status_column].casefold().strip("` ") != "established":
            report.add(
                "error", "invalid-established-provenance-status",
                f"established provenance row `{label_match}` must have Status `established`",
                provenance,
            )
        if label_match:
            if label_match in established_labels:
                report.add(
                    "error", "duplicate-provenance-label",
                    f"established provenance table repeats LaTeX label `{label_match}`",
                    provenance,
                )
            established_labels.add(label_match)
            if label_match in provisional_labels:
                report.add("error", "conflicting-provenance-status", f"`{label_match}` appears in both established and open/provisional provenance", provenance)
        evidence_value = cells[evidence_column].strip().casefold()
        if evidence_value in {"", "none", "pending", "unknown", "not applicable"}:
            report.add("error", "provenance-evidence-missing", f"established item `{label_match}` has no usable evidence reference", provenance)
        evidence_links = re.findall(r"\[[^\]]+\]\(([^)]+)\)", cells[evidence_column])
        valid_evidence_link = False
        for destination in evidence_links:
            if destination.casefold().startswith(("http://", "https://")):
                continue
            evidence_path = (provenance.parent / unquote(destination.split("#", 1)[0]).strip("<>")).resolve(strict=False)
            if not evidence_path.exists() or not evidence_path.is_file():
                continue
            evidence_artifact = _canonical_artifact(evidence_path)
            if evidence_artifact and evidence_artifact[1] in {"CLM", "ATT", "EXP", "LIT"}:
                valid_evidence_link = True
                break
        if not valid_evidence_link:
            report.add(
                "error", "provenance-evidence-invalid",
                f"established item `{label_match}` needs a resolvable link to a CLM/ATT/EXP/LIT evidence artifact",
                provenance,
            )
        if len(declared_claim_links) != 1 or canonical_claim_id is None:
            report.add(
                "error", "provenance-claim-link-invalid",
                f"claim cell for `{label_match}` must contain exactly one canonical CLM link",
                provenance,
            )
        if claim_id not in canonical:
            report.add("error", "provenance-claim-missing", f"provenance row names absent claim {claim_id}", provenance)
            continue
        claim_text = canonical[claim_id].read_text(encoding="utf-8")
        claim_labels = _record_metadata(claim_text)
        claim_revision = _integer_in(claim_labels.get("claim revision"))
        current_digest = claim_digest(claim_text).casefold()
        current_evidence_revision = _integer_in(claim_labels.get("evidence revision"))
        current_evidence_digest = evidence_digest(claim_text).casefold()
        claim_contract_revision = _integer_in(claim_labels.get("contract revision"))
        required_profile = claim_labels.get("required review profile", "").casefold().strip("` ")
        actual_environments = set(tex_environments.get(label_match, ()))
        if actual_environments and manuscript_role not in actual_environments:
            report.add(
                "error", "manuscript-role-mismatch",
                f"provenance role `{manuscript_role}` for `{label_match}` does not match LaTeX environment(s) {sorted(actual_environments)}",
                provenance,
            )
        theorem_like = bool(actual_environments.intersection({"theorem", "lemma", "proposition", "corollary"}))
        claim_kind = claim_labels.get("claim kind", "").casefold()
        evidence_class = claim_labels.get("evidence class", "").casefold()
        if theorem_like and (
            claim_kind not in {"theorem", "lemma", "counterexample", "impossibility"}
            or not _mathematical_evidence_class(evidence_class)
        ):
            report.add(
                "error", "manuscript-mathematical-role-invalid",
                f"theorem-like manuscript item `{label_match}` requires a mathematical claim kind and non-empirical-only evidence",
                provenance,
            )
        if claim_labels.get("status", "").casefold() != "validated":
            report.add("error", "stale-provenance", f"paper provenance uses {claim_id} with status `{claim_labels.get('status', 'missing')}`", provenance)
        manuscript_section = _section(claim_text, "Manuscript locations")
        reverse_link_valid = False
        for destination in re.findall(r"\[[^\]]+\]\(([^)]+)\)", manuscript_section):
            if destination.casefold().startswith(("http://", "https://")):
                continue
            reverse_path = (canonical[claim_id].parent / unquote(destination.split("#", 1)[0]).strip("<>")).resolve(strict=False)
            try:
                reverse_path.relative_to((root / "paper").resolve())
            except ValueError:
                continue
            if reverse_path.exists() and reverse_path.is_file():
                reverse_link_valid = True
                break
        if not label_match or label_match not in manuscript_section or not reverse_link_valid:
            report.add(
                "error", "provenance-reverse-location-missing",
                f"{claim_id} does not link manuscript label `{label_match or 'missing'}` back to a paper artifact from Manuscript locations",
                canonical[claim_id],
            )
        if not review_ids:
            report.add("error", "provenance-review-missing", f"paper provenance for {claim_id} names no review", provenance)
        passing_bound_review = False
        for review_id in review_ids:
            if review_id not in canonical:
                report.add("error", "provenance-review-missing", f"paper provenance names absent review {review_id}", provenance)
                continue
            review_link_targets = re.findall(r"\[[^\]]+\]\(([^)]+)\)", cells[review_column])
            if not any(
                (provenance.parent / unquote(target.split("#", 1)[0]).strip("<>")).resolve(strict=False)
                    == canonical[review_id].resolve(strict=False)
                for target in review_link_targets
            ):
                report.add("error", "provenance-review-link-invalid", f"review cell for {review_id} is not a resolvable canonical Markdown link", provenance)
            review_labels = _record_metadata(canonical[review_id].read_text(encoding="utf-8"))
            review_text = canonical[review_id].read_text(encoding="utf-8")
            is_bound_pass = (
                review_labels.get("verdict", "").casefold() in {"pass", "passed"}
                and review_labels.get("status", "").casefold() == "completed"
                and review_labels.get("fresh context", "").casefold() in {"yes", "true"}
                and _review_receipt_valid(review_id, canonical[review_id], review_labels)
                and _review_fidelity_complete(review_text)
                and review_labels.get("evidence or proof correct", "").casefold() in {"yes", "true"}
                and review_labels.get("establishes exact recorded statement", "").casefold() in {"yes", "true"}
                and review_labels.get("addresses intended project question at stated scope", "").casefold() in {"yes", "true"}
                and all(
                    review_labels.get(field, "").casefold() in {"yes", "true"}
                    for field in ("assumptions accounted for", "quantifier order checked", "scope restrictions checked", "exceptional cases checked")
                )
                and _id_in(review_labels.get("target claim"), "CLM") == claim_id
                and _integer_in(review_labels.get("target claim revision")) == claim_revision
                and review_labels.get("target statement digest", "").casefold() == current_digest
                and _integer_in(review_labels.get("target evidence revision")) == current_evidence_revision
                and review_labels.get("target evidence digest", "").casefold() == current_evidence_digest
                and review_labels.get("requested profile", "").casefold().strip("` ") == required_profile
                and _integer_in(review_labels.get("contract revision")) == claim_contract_revision
            )
            if is_bound_pass:
                passing_bound_review = True
        if review_ids and not passing_bound_review:
            report.add("error", "provenance-review-not-passing", f"no named review passes the current revision and digest of {claim_id}", provenance)
        if label_match and label_match not in tex_labels and label_match.casefold() not in {"label", "manuscript label"}:
            report.add("error", "provenance-label-missing", f"LaTeX label `{label_match}` is not present in paper sources", provenance)

    tracked_environments = {"theorem", "lemma", "proposition", "corollary", "conjecture", "figure", "table"}
    paper = root / "paper"
    for tex_path in _walk_project_files(paper) if paper.exists() else ():
        if tex_path.suffix.casefold() != ".tex":
            continue
        tex = _strip_tex_comments(tex_path.read_text(encoding="utf-8"))
        for match in re.finditer(
            r"\\begin\{(theorem|lemma|proposition|corollary|conjecture|figure|table)\*?\}(.*?)"
            r"\\end\{\1\*?\}", tex, flags=re.DOTALL,
        ):
            environment = match.group(1)
            if environment not in tracked_environments:
                continue
            labels = re.findall(r"\\label\{([^}]+)\}", match.group(2))
            if not labels:
                report.add("error", "unlabeled-manuscript-item", f"{environment} environment has no LaTeX label", tex_path)
                continue
            for label in labels:
                if environment == "conjecture":
                    if label not in provisional_labels:
                        report.add("error", "unprovenanced-provisional-item", f"conjecture label `{label}` is absent from the open/provisional provenance table", tex_path)
                    if label in established_labels:
                        report.add("error", "conjecture-marked-established", f"conjecture label `{label}` is incorrectly marked established", tex_path)
                elif label not in established_labels:
                    report.add("error", "unprovenanced-manuscript-item", f"established {environment} label `{label}` is absent from the provenance table", tex_path)


def _check_state_size(root: Path, report: CheckReport) -> None:
    path = root / "STATE.md"
    if not path.exists():
        return
    text = path.read_text(encoding="utf-8")
    lines = text.count("\n") + 1
    if len(text.encode("utf-8")) > 16_384 or lines > 300:
        report.add("warning", "state-too-large", f"STATE.md is {len(text.encode('utf-8'))} bytes/{lines} lines; replace detail with links", path)


TASK_FILE_CONTRACTS: Mapping[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "TASK.md": (
        ("Status", "Parent run", "Contract revision", "Base state revision", "Requested profile",
         "Fresh context required", "Assigned context", "Preallocated artifacts", "Created", "Related artifacts"),
        ("Question", "Successful outcomes", "Authoritative inputs", "Permitted and provisional assumptions",
         "Write boundary", "Forbidden changes", "Context packet", "Return contract"),
    ),
    "OUTPUT.md": (
        ("Task", "Status", "Outcome classification", "Completed", "Provisional", "Related artifacts"),
        ("Exact supported conclusions", "Evidence or derivation", "Assumptions, scope, and exceptional cases",
         "Counterexamples and disproofs", "Negative findings", "Uncertainties and verification needs",
         "Deferred findings", "Artifacts written", "Recommended next action"),
    ),
    "RECEIPT.md": (
        ("Task", "Requested profile", "Resolved provider", "Resolved model", "Resolved effort", "Runtime mode",
         "Runtime version", "Adapter version", "Fresh context", "Status", "Started", "Ended", "Usage", "Cost", "Runtime failure",
         "Substitution"),
        ("Authoritative inputs received", "Permitted write boundary", "Invocation summary",
         "Output and partial artifacts", "Failure or substitution details", "Integrity attestation"),
    ),
}


def _runtime_for_provider(provider: str) -> str | None:
    provider_key = provider.casefold()
    return (
        "claude" if "claude" in provider_key or "anthropic" in provider_key
        else "codex" if "codex" in provider_key or "openai" in provider_key
        else None
    )


def _recorded_adapter_mapping(
    root: Path, adapter_version: str, provider: str, profile: str,
) -> tuple[str, str] | None:
    """Resolve an immutable receipt mapping retained in PROFILES history.

    Current aliases are intentionally replaceable.  A completed receipt is
    instead checked against the versioned mapping that existed when it ran;
    deleting that history makes the receipt unverifiable rather than silently
    trusting a self-declared model.
    """
    runtime = _runtime_for_provider(provider)
    profiles_path = root / "runtime/PROFILES.md"
    if runtime is None or not adapter_version.strip() or not profiles_path.exists():
        return None
    mappings, errors = _adapter_mapping_history(profiles_path)
    if errors:
        return None
    return mappings.get((adapter_version.strip().strip("`").casefold(), runtime, profile.casefold().strip("` ")))


def _adapter_mapping_history(
    profiles_path: Path,
) -> tuple[dict[tuple[str, str, str], tuple[str, str]], list[str]]:
    """Parse and validate the append-only receipt mapping ledger."""
    mappings: dict[tuple[str, str, str], tuple[str, str]] = {}
    errors: list[str] = []
    if not profiles_path.exists():
        return mappings, ["runtime/PROFILES.md is missing"]
    lines = profiles_path.read_text(encoding="utf-8").splitlines()
    try:
        start, end = _section_bounds(lines, "Adapter mapping history")
        table = _find_table(lines, start, end)
        version_column = _column(table.headers, ("Adapter version", "Receipt adapter version"))
        runtime_column = _column(table.headers, ("Runtime", "Provider runtime"))
        profile_column = _column(table.headers, ("Profile", "Semantic profile"))
        model_column = _column(table.headers, ("Model",))
        effort_column = _column(table.headers, ("Effort", "Reasoning effort"))
    except ResearchError as error:
        return mappings, [str(error)]
    for _, cells in table.rows:
        if max(version_column, runtime_column, profile_column, model_column, effort_column) >= len(cells):
            errors.append("mapping-history row is missing a required cell")
            continue
        version = cells[version_column].strip().strip("`").casefold()
        row_runtime = cells[runtime_column].strip().strip("`").casefold()
        row_profile = cells[profile_column].strip().strip("`").casefold()
        model = cells[model_column].strip().strip("`").casefold()
        effort = cells[effort_column].strip().strip("`").casefold()
        if not version or row_runtime not in {"codex", "claude"} or row_profile not in SEMANTIC_PROFILES or not model or not effort:
            errors.append(f"invalid mapping-history row for `{version or 'missing version'}`/{row_runtime or 'missing runtime'}/{row_profile or 'missing profile'}`")
            continue
        key = (version, row_runtime, row_profile)
        if key in mappings:
            errors.append(f"duplicate mapping-history row for `{version}`/{row_runtime}/{row_profile}")
            continue
        mappings[key] = (model, effort)
    versions = {key[0] for key in mappings}
    for version in sorted(versions):
        for row_runtime in ("codex", "claude"):
            missing = [profile for profile in SEMANTIC_PROFILES if (version, row_runtime, profile) not in mappings]
            if missing:
                errors.append(f"mapping history for `{version}`/{row_runtime} is incomplete: missing {', '.join(missing)}")
    return mappings, errors


def _expected_runtime_mapping(root: Path, provider: str, profile: str) -> tuple[str, str] | None:
    runtime = _runtime_for_provider(provider)
    profiles_path = root / "runtime/PROFILES.md"
    if runtime is None or not profiles_path.exists():
        return None
    lines = profiles_path.read_text(encoding="utf-8").splitlines()
    try:
        start, end = _section_bounds(lines, "Profile contract")
        table = _find_table(lines, start, end)
        profile_column = _column(table.headers, ("Profile",))
        mapping_column = _column(
            table.headers,
            ("Claude Code mapping", "Claude mapping") if runtime == "claude" else ("Codex mapping",),
        )
    except ResearchError:
        return None
    matches: list[tuple[str, str]] = []
    for _, cells in table.rows:
        if max(profile_column, mapping_column) >= len(cells):
            continue
        if cells[profile_column].strip().strip("`").casefold() != profile:
            continue
        values = re.findall(r"`([^`]+)`", cells[mapping_column])
        if len(values) >= 2:
            matches.append((values[0].casefold(), values[1].casefold()))
    return matches[0] if len(matches) == 1 else None


def _exact_task_reference(source: Path, value: str, expected_task_id: str) -> bool:
    links = re.findall(r"\[([^\]]+)\]\(([^)]+)\)", value or "")
    if len(links) != 1:
        return False
    label, destination = links[0]
    if label.strip() != expected_task_id or destination.casefold().startswith(("http://", "https://")):
        return False
    raw_path = unquote(destination.split("#", 1)[0]).strip("<>")
    return (source.parent / raw_path).resolve(strict=False) == source.with_name("TASK.md").resolve(strict=False)


def _check_tasks(root: Path, report: CheckReport, canonical: Mapping[str, Path]) -> None:
    profiles = {"maintenance", "coordinator", "substantive", "deep", "pivotal"}
    tasks_root = root / "runs"
    if not tasks_root.exists():
        return
    seen_task_ids: set[str] = set()
    for directory in tasks_root.glob("RUN-*/tasks/T*"):
        if not directory.is_dir():
            continue
        parent_run = directory.parents[1].name
        expected_task_id = f"{parent_run}-{directory.name}"
        if (
            not re.fullmatch(r"RUN-\d{4,}-T\d{2,}", expected_task_id)
            or int(directory.name[1:]) < 1
        ):
            report.add("error", "invalid-task-path", f"task directory does not have RUN-####/tasks/T## shape: {directory.relative_to(root)}", directory)
            continue
        if expected_task_id in seen_task_ids:
            report.add("error", "duplicate-task-id", f"task ID appears more than once: {expected_task_id}", directory)
        seen_task_ids.add(expected_task_id)
        loaded: dict[str, tuple[str, dict[str, str]]] = {}
        for filename, (labels_required, headings_required) in TASK_FILE_CONTRACTS.items():
            path = directory / filename
            if not path.exists():
                report.add("error", "missing-task-file", f"{expected_task_id} is missing {filename}", path)
                continue
            text = path.read_text(encoding="utf-8")
            first = text.splitlines()[0] if text.splitlines() else ""
            if not re.match(rf"^#\s+{re.escape(expected_task_id)}\b", first):
                report.add("error", "task-id-mismatch", f"{filename} heading does not declare {expected_task_id}", path)
            top_headings = re.findall(r"(?m)^#(?!#)\s+(.+?)\s*$", _strip_non_authoritative_examples(text))
            if len(top_headings) != 1:
                report.add("error", "invalid-task-h1-count", f"{filename} must contain exactly one top-level task heading", path)
            header_labels = _preamble_metadata(text)
            labels = _record_metadata(text)
            loaded[filename] = (text, labels)
            label_names = [
                _normal_header(value)
                for value in re.findall(r"(?m)^-\s*\*\*([^*]+?):\*\*", _strip_non_authoritative_examples(text))
            ]
            for duplicate in sorted({label for label in label_names if label_names.count(label) > 1}):
                report.add("error", "duplicate-task-label", f"{filename} repeats bold label `{duplicate}`", path)
            for label in labels_required:
                if _normal_header(label) not in header_labels:
                    report.add("error", "missing-task-label", f"{filename} is missing `{label}`", path)
            for heading in headings_required:
                if not _heading_exists(text, heading):
                    report.add("error", "missing-task-heading", f"{filename} is missing `## {heading}`", path)
                elif _heading_count(text, heading) != 1:
                    report.add("error", "duplicate-task-heading", f"{filename} must contain exactly one `## {heading}` section", path)

        if "TASK.md" not in loaded:
            continue
        task_text, task_labels = loaded["TASK.md"]
        parent_link_id = _exact_canonical_linked_id(
            directory / "TASK.md", task_labels.get("parent run", ""), "RUN", canonical,
        )
        if parent_link_id != parent_run:
            report.add("error", "task-parent-mismatch", f"task Parent run does not match {parent_run}", directory / "TASK.md")
        requested = task_labels.get("requested profile", "").casefold().strip("` ")
        if requested not in profiles:
            report.add("error", "invalid-profile", f"task requests unknown semantic profile `{requested}`", directory / "TASK.md")
        if task_labels.get("status", "").casefold() not in {"planned", "active", "completed", "cancelled"}:
            report.add("error", "invalid-task-status", f"invalid task status `{task_labels.get('status', '')}`", directory / "TASK.md")
        if not _section(task_text, "Authoritative inputs").strip():
            report.add("error", "task-inputs-missing", "task has no authoritative input packet", directory / "TASK.md")
        if not _section(task_text, "Write boundary").strip():
            report.add("error", "task-boundary-missing", "task has no write boundary", directory / "TASK.md")
        task_contract_revision = _integer_in(task_labels.get("contract revision"))
        task_state_revision = _integer_in(task_labels.get("base state revision"))
        if task_contract_revision is None or task_contract_revision < 1 or task_contract_revision > _project_revision(root):
            report.add("error", "invalid-task-revision", f"task has invalid Contract revision `{task_labels.get('contract revision', '')}`", directory / "TASK.md")
        if task_state_revision is None or task_state_revision > _state_revision(root):
            report.add("error", "invalid-task-revision", f"task has invalid Base state revision `{task_labels.get('base state revision', '')}`", directory / "TASK.md")
        if task_labels.get("status", "").casefold() in {"active", "completed"}:
            for label in ("assigned context", "created"):
                if _unfinished_value(task_labels.get(label, "")):
                    report.add(
                        "error", "active-task-incomplete",
                        f"active/completed task leaves `{label}` unresolved",
                        directory / "TASK.md",
                    )
            substantive_sections = (
                "Question", "Successful outcomes", "Authoritative inputs",
                "Permitted and provisional assumptions", "Write boundary",
                "Context packet", "Return contract",
            )
            for heading in substantive_sections:
                section = _section(task_text, heading)
                normalized = re.sub(r"\s+", " ", section).casefold().strip(" `-.\n")
                if _unfinished_section(section) or normalized in {"", "none", "not applicable"}:
                    report.add(
                        "error", "active-task-incomplete",
                        f"active/completed task leaves `## {heading}` unfinished",
                        directory / "TASK.md",
                    )
            input_paths = _markdown_link_paths(
                directory / "TASK.md", _section(task_text, "Authoritative inputs"),
            )
            canonical_inputs = {
                (root / "PROJECT.md").resolve(strict=False),
                *(artifact.resolve(strict=False) for artifact in canonical.values()),
            }
            if not input_paths.intersection(canonical_inputs):
                report.add(
                    "error", "task-input-links-invalid",
                    "active/completed task Authoritative inputs must link PROJECT.md or a canonical research artifact",
                    directory / "TASK.md",
                )

        if "RECEIPT.md" not in loaded:
            continue
        _, receipt = loaded["RECEIPT.md"]
        if not _exact_task_reference(
            directory / "RECEIPT.md", receipt.get("task", ""), expected_task_id,
        ):
            report.add(
                "error", "receipt-task-link-invalid",
                "RECEIPT Task must be exactly one sibling TASK.md link labeled with the exact run-local task ID",
                directory / "RECEIPT.md",
            )
        if _id_in(receipt.get("task")) != expected_task_id:
            # _id_in intentionally recognizes only durable IDs; task IDs need
            # their own exact extraction.
            if expected_task_id not in receipt.get("task", ""):
                report.add("error", "receipt-task-mismatch", "receipt points to a different task", directory / "RECEIPT.md")
        receipt_requested = receipt.get("requested profile", "").casefold().strip("` ")
        if receipt_requested != requested:
            report.add("error", "receipt-profile-mismatch", f"receipt requested `{receipt_requested}`, task requested `{requested}`", directory / "RECEIPT.md")
        receipt_status = receipt.get("status", "").casefold()
        if receipt_status not in {"not started", "running", "completed", "failed"}:
            report.add("error", "invalid-receipt-status", f"invalid invocation status `{receipt_status}`", directory / "RECEIPT.md")
        fresh_required = task_labels.get("fresh context required", "").casefold() in {"yes", "true"}
        fresh_received = receipt.get("fresh context", "").casefold() in {"yes", "true"}
        if fresh_required and not fresh_received and receipt_status in {"running", "completed"}:
            report.add("error", "fresh-context-violation", "task required a fresh context but receipt does not confirm one", directory / "RECEIPT.md")
        runtime_failure = receipt.get("runtime failure", "").casefold().strip()
        failure_recorded = runtime_failure not in {"", "none", "pending", "not applicable"}
        if receipt_status == "failed" and not failure_recorded:
            report.add("error", "runtime-failure-unexplained", "failed invocation has no Runtime failure description", directory / "RECEIPT.md")
        if receipt_status == "completed":
            for label in ("resolved provider", "resolved model", "resolved effort", "runtime mode", "runtime version", "adapter version", "started", "ended"):
                if receipt.get(label, "").casefold().strip() in {"", "pending", "unknown"}:
                    report.add("error", "unresolved-runtime", f"completed receipt leaves `{label}` unresolved", directory / "RECEIPT.md")
            if _unfinished_value(receipt.get("substitution", ""), allow_none=True):
                report.add("error", "completed-receipt-incomplete", "completed receipt leaves Substitution unresolved", directory / "RECEIPT.md")
            receipt_text = loaded["RECEIPT.md"][0]
            for heading in ("Authoritative inputs received", "Permitted write boundary", "Invocation summary", "Failure or substitution details", "Integrity attestation"):
                if _unfinished_section(_section(receipt_text, heading)):
                    report.add("error", "completed-receipt-incomplete", f"completed receipt leaves `## {heading}` unfinished", directory / "RECEIPT.md")
            for field in ("stayed within write boundary", "no completed evidence overwritten", "no git operation performed"):
                if receipt.get(field, "").casefold() not in {"yes", "true"}:
                    report.add("error", "completed-receipt-incomplete", f"completed receipt does not affirm `{field}`", directory / "RECEIPT.md")
            expected_mapping = _expected_runtime_mapping(
                root, receipt.get("resolved provider", ""), requested
            )
            actual_mapping = (
                receipt.get("resolved model", "").casefold().strip("` "),
                receipt.get("resolved effort", "").casefold().strip("` "),
            )
            substitution = receipt.get("substitution", "").casefold().strip()
            has_substitution = substitution not in {"", "none", "pending", "not applicable"}
            if expected_mapping is None:
                report.add("error", "runtime-profile-unverifiable", f"cannot resolve {requested} for provider `{receipt.get('resolved provider', '')}` from runtime/PROFILES.md", directory / "RECEIPT.md")
            elif actual_mapping != expected_mapping:
                receipt_path = directory / "RECEIPT.md"
                immutable_review_receipt = any(
                    review_id.startswith("REV-")
                    and _record_metadata(review_path.read_text(encoding="utf-8")).get("status", "").casefold() == "completed"
                    and _review_receipt_path(
                        review_path,
                        _record_metadata(review_path.read_text(encoding="utf-8")),
                    ) == receipt_path.resolve(strict=False)
                    for review_id, review_path in canonical.items()
                )
                recorded_mapping = _recorded_adapter_mapping(
                    root, receipt.get("adapter version", ""),
                    receipt.get("resolved provider", ""), requested,
                )
                if (
                    not has_substitution
                    and immutable_review_receipt
                    and recorded_mapping is not None
                    and actual_mapping == recorded_mapping
                ):
                    report.add(
                        "info", "historical-profile-mapping",
                        f"immutable completed review receipt records {actual_mapping[0]}/{actual_mapping[1]}; current {requested} mapping is {expected_mapping[0]}/{expected_mapping[1]}. Model-alias edits do not retroactively invalidate reviewed evidence",
                        receipt_path,
                    )
                else:
                    severity = "warning" if has_substitution else "error"
                    report.add(
                        severity,
                        "silent-profile-downgrade" if not has_substitution else "runtime-profile-substitution",
                        f"completed {requested} task resolved to {actual_mapping[0]}/{actual_mapping[1]}, expected {expected_mapping[0]}/{expected_mapping[1]}",
                        receipt_path,
                    )
        if "OUTPUT.md" in loaded:
            output_text, output = loaded["OUTPUT.md"]
            if not _exact_task_reference(
                directory / "OUTPUT.md", output.get("task", ""), expected_task_id,
            ):
                report.add(
                    "error", "output-task-link-invalid",
                    "OUTPUT Task must be exactly one sibling TASK.md link labeled with the exact run-local task ID",
                    directory / "OUTPUT.md",
                )
            outcome = output.get("outcome classification", "").casefold()
            allowed_outcomes = {"pending", "supported", "refuted", "inconclusive", "blocked", "requiring verification", "runtime failure"}
            if outcome not in allowed_outcomes:
                report.add("error", "invalid-output-classification", f"unknown output classification `{outcome}`", directory / "OUTPUT.md")
            output_status = output.get("status", "").casefold()
            if output_status not in {"in progress", "completed", "failed"}:
                report.add("error", "invalid-output-status", f"invalid output status `{output_status}`", directory / "OUTPUT.md")
            if output_status == "completed":
                if output.get("completed", "").casefold().strip() in {"", "pending", "unknown"}:
                    report.add("error", "completed-output-incomplete", "completed output has no completion timestamp/date", directory / "OUTPUT.md")
                for heading in (
                    "Exact supported conclusions", "Evidence or derivation",
                    "Assumptions, scope, and exceptional cases", "Counterexamples and disproofs",
                    "Negative findings", "Uncertainties and verification needs", "Deferred findings",
                    "Artifacts written", "Recommended next action",
                ):
                    section = _section(output_text, heading)
                    if _unfinished_section(section):
                        report.add("error", "completed-output-incomplete", f"completed output has unfinished `## {heading}`", directory / "OUTPUT.md")
            if (receipt_status == "failed" or failure_recorded) and outcome not in {"pending", "runtime failure"}:
                report.add("error", "runtime-failure-as-research-result", f"failed runtime is recorded as research outcome `{outcome}`", directory / "OUTPUT.md")
            substitution = receipt.get("substitution", "").casefold().strip()
            if substitution not in {"", "none", "pending", "not applicable"} and requested in {"deep", "pivotal"}:
                if output.get("provisional", "").casefold() not in {"yes", "true"} or outcome != "requiring verification":
                    report.add("error", "profile-debt-not-visible", f"substituted {requested} task must remain provisional and requiring verification", directory / "OUTPUT.md")
                debt_text = "\n".join(
                    (_section(output_text, "Uncertainties and verification needs"), _section(output_text, "Recommended next action"))
                ).casefold()
                if requested not in debt_text or not re.search(r"\b(?:pending|required|verification|verify|rerun)\b", debt_text):
                    report.add(
                        "error", "profile-debt-not-visible",
                        f"substituted {requested} task must record explicit pending required-tier verification debt in its durable output",
                        directory / "OUTPUT.md",
                    )


def check_project(root: Path) -> CheckReport:
    root = root.resolve()
    report = CheckReport()
    _check_runtime_safety_paths(root, report)
    if report.errors:
        return report
    _check_authoritative_utf8(root, report)
    if report.errors:
        return report
    _check_structure(root, report)
    index = _load_index(root, report)
    canonical = _check_ids(root, report, index)
    _check_revisions(root, report)
    _check_artifact_contracts(root, report, canonical)
    _check_links(root, report, canonical)
    _check_cross_reference_links(root, report, canonical)
    _check_runs(root, report, canonical)
    _check_claims_reviews(root, report, canonical)
    _check_trusted_result_surfaces(root, report, canonical)
    _check_bibliography(root, report)
    _check_experiments(root, report)
    _check_paper_inputs(root, report)
    _check_provenance(root, report, canonical)
    _check_tasks(root, report, canonical)
    _check_state_size(root, report)
    return report


ADAPTER_INVENTORY: Mapping[str, tuple[str, ...]] = {
    "codex": (
        ".codex/config.toml", ".codex/hooks.json", ".codex/README.md", ".codex/rules/no-git.rules",
        ".codex/agents/maintenance.toml", ".codex/agents/coordinator.toml",
        ".codex/agents/substantive.toml", ".codex/agents/deep.toml",
        ".codex/agents/pivotal.toml", ".codex/agents/verifier.toml",
        ".codex/agents/verifier_deep.toml", ".codex/agents/verifier_pivotal.toml",
    ),
    "claude": (
        ".claude/settings.json", ".claude/README.md",
        ".claude/agents/maintenance.md", ".claude/agents/coordinator.md",
        ".claude/agents/substantive.md", ".claude/agents/deep.md",
        ".claude/agents/pivotal.md", ".claude/agents/verifier.md",
        ".claude/agents/verifier_deep.md", ".claude/agents/verifier_pivotal.md",
    ),
}


def _hook_commands(entry: object) -> list[str]:
    if not isinstance(entry, dict) or not isinstance(entry.get("hooks"), list):
        return []
    return [
        hook.get("command", "")
        for hook in entry["hooks"]
        if isinstance(hook, dict) and isinstance(hook.get("command"), str)
    ]


def _matcher_alternatives(value: object) -> frozenset[str] | None:
    """Parse the deliberately small matcher grammar used by shipped adapters.

    Runtime matchers are regular expressions, but the template only permits an
    optional anchored/grouped alternation of literal native tool names.  Treating
    matchers as substring bags lets strings such as ``NotAnAgent`` or
    ``BashEditWrite`` satisfy a static audit while matching no protected tool.
    """
    if not isinstance(value, str):
        return None
    matcher = value.strip()
    if matcher.startswith("^") or matcher.endswith("$"):
        if not (matcher.startswith("^") and matcher.endswith("$")):
            return None
        matcher = matcher[1:-1].strip()
    if matcher.startswith("(") or matcher.endswith(")"):
        if not (matcher.startswith("(") and matcher.endswith(")")):
            return None
        matcher = matcher[1:-1].strip()
    parts = [part.strip() for part in matcher.split("|")]
    if not parts or any(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", part) is None for part in parts):
        return None
    if len(parts) != len(set(parts)):
        return None
    return frozenset(parts)


def _matcher_exact(value: object, expected: Iterable[str]) -> bool:
    return _matcher_alternatives(value) == frozenset(expected)


def _toml_scalar_assignments(text: str) -> dict[tuple[str, str], list[str]]:
    """Parse simple scalar assignments by TOML section without third parties."""
    structural = re.sub(r'(?s)""".*?"""', "", text)
    structural = re.sub(r"(?s)'''.*?'''", "", structural)
    section = ""
    result: dict[tuple[str, str], list[str]] = {}
    for raw_line in structural.splitlines():
        line = raw_line.strip()
        table = re.fullmatch(r"\[([^\[\]]+)\]", line)
        array_table = re.fullmatch(r"\[\[([^\[\]]+)\]\]", line)
        if table or array_table:
            section = (table or array_table).group(1).casefold()
            continue
        assignment = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)\s*=\s*([^#]+?)\s*$", line)
        if assignment:
            key = assignment.group(1).casefold()
            value = assignment.group(2).strip().strip("\"'").casefold()
            result.setdefault((section, key), []).append(value)
    return result


def _codex_toml_shape_errors(text: str, *, agent: bool) -> list[str]:
    """Validate the bounded TOML subset used by the checked-in adapters."""
    root_fields = (
        {"name", "description", "model", "model_reasoning_effort", "sandbox_mode", "developer_instructions"}
        if agent else
        {"approval_policy", "approvals_reviewer", "sandbox_mode", "allow_login_shell"}
    )
    section_fields = (
        {
            "hooks.PreToolUse": {"matcher"},
            "hooks.PreToolUse.hooks": {
                "type", "command", "command_windows", "timeout", "statusMessage", "async",
            },
        }
        if agent else
        {
            "sandbox_workspace_write": {"network_access"},
            "features": {"hooks"},
            "agents": {"enabled", "interrupt_message"},
            "memories": {"generate_memories", "use_memories"},
        }
    )
    errors: list[str] = []
    section = ""
    seen_tables: set[str] = set()
    seen_fields: set[tuple[str, str]] = set()
    multiline_quote: str | None = None
    for number, raw in enumerate(text.splitlines(), 1):
        stripped = raw.strip()
        if multiline_quote is not None:
            if multiline_quote in raw:
                _, tail = raw.split(multiline_quote, 1)
                if tail.strip() and not tail.lstrip().startswith("#"):
                    errors.append(f"line {number}: content follows a multiline string terminator")
                multiline_quote = None
            continue
        if not stripped or stripped.startswith("#"):
            continue
        table = re.fullmatch(r"\[([^\[\]]+)\]", stripped)
        array_table = re.fullmatch(r"\[\[([^\[\]]+)\]\]", stripped)
        if table or array_table:
            section = (table or array_table).group(1)
            if section not in section_fields:
                errors.append(f"line {number}: unknown table `{section}`")
            if section in seen_tables:
                errors.append(f"line {number}: duplicate table `{section}`")
            seen_tables.add(section)
            continue
        assignment = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$", stripped)
        if not assignment:
            errors.append(f"line {number}: unsupported or malformed TOML syntax")
            continue
        key, value = assignment.group(1), assignment.group(2).strip()
        allowed = root_fields if section == "" else section_fields.get(section, set())
        if key not in allowed:
            errors.append(f"line {number}: unknown field `{key}` in `{section or 'root'}`")
        location = (section, key)
        if location in seen_fields:
            errors.append(f"line {number}: duplicate field `{key}` in `{section or 'root'}`")
        seen_fields.add(location)
        if value.startswith(('"""', "'''")):
            quote = value[:3]
            remainder = value[3:]
            if quote in remainder:
                _, tail = remainder.split(quote, 1)
                if tail.strip() and not tail.lstrip().startswith("#"):
                    errors.append(f"line {number}: content follows a multiline string")
            else:
                multiline_quote = quote
            continue
        scalar = r'(?:"(?:\\.|[^"\\])*"|\'[^\']*\'|true|false|-?\d+(?:\.\d+)?)'
        if re.fullmatch(scalar + r"\s*(?:#.*)?", value, re.IGNORECASE) is None:
            errors.append(f"line {number}: value for `{key}` is not a supported scalar")
    if multiline_quote is not None:
        errors.append("unterminated multiline string")
    return errors


def _claude_frontmatter(text: str) -> str | None:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    try:
        end = next(index for index, line in enumerate(lines[1:], 1) if line.strip() == "---")
    except StopIteration:
        return None
    return "\n".join(lines[1:end]) + "\n"


def _claude_frontmatter_shape_errors(text: str) -> list[str]:
    frontmatter = _claude_frontmatter(text)
    if frontmatter is None:
        return ["missing or unterminated YAML frontmatter"]
    root_fields = {"name", "description", "model", "effort", "permissionMode"}
    nested_patterns = (
        r"^  PreToolUse:\s*$",
        r"^    - matcher:\s*(['\"]).*\1\s*$",
        r"^      hooks:\s*$",
        r"^        - type:\s*command\s*$",
        r"^          command:\s*(['\"]).*\1\s*$",
        r"^          timeout:\s*\d+\s*$",
        r"^          async:\s*(?:true|false)\s*$",
    )
    errors: list[str] = []
    seen_root: set[str] = set()
    hooks_seen = False
    for number, raw in enumerate(frontmatter.splitlines(), 2):
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        if raw == "hooks:":
            if hooks_seen:
                errors.append(f"line {number}: duplicate `hooks` mapping")
            hooks_seen = True
            continue
        if raw.startswith((" ", "\t")):
            if not hooks_seen or not any(re.fullmatch(pattern, raw) for pattern in nested_patterns):
                errors.append(f"line {number}: unsupported or malformed nested frontmatter syntax")
            continue
        match = re.fullmatch(r"([A-Za-z][A-Za-z0-9]*):\s*(.+)", raw)
        if not match:
            errors.append(f"line {number}: unsupported or malformed frontmatter syntax")
            continue
        key, value = match.group(1), match.group(2).strip()
        if key not in root_fields:
            errors.append(f"line {number}: unknown frontmatter field `{key}`")
        if key in seen_root:
            errors.append(f"line {number}: duplicate frontmatter field `{key}`")
        seen_root.add(key)
        if value.startswith(("[", "{", "&", "*", "!", "|", ">")):
            errors.append(f"line {number}: `{key}` must use the supported scalar form")
        if value.startswith(("'", '"')) and (len(value) < 2 or value[-1] != value[0]):
            errors.append(f"line {number}: unterminated quoted scalar for `{key}`")
    return errors


def _focused_hook_fields(text: str, runtime: str) -> dict[str, object] | None:
    """Extract one focused guard hook only from its native structural location."""
    if runtime == "codex":
        # TOML is not in the Python 3.10 standard library.  This intentionally
        # recognizes only the tiny checked-in hook-table shape and first removes
        # multiline strings so table-looking prose cannot impersonate config.
        structural = re.sub(r'(?s)""".*?"""', "", text)
        structural = re.sub(r"(?s)'''.*?'''", "", structural)
        pretool_headers = list(re.finditer(r"(?m)^\[\[hooks\.PreToolUse\]\]\s*$", structural))
        handler_headers = list(re.finditer(r"(?m)^\[\[hooks\.PreToolUse\.hooks\]\]\s*$", structural))
        if len(pretool_headers) != 1 or len(handler_headers) != 1:
            return None
        pretool_header, handler_header = pretool_headers[0], handler_headers[0]
        if pretool_header.end() >= handler_header.start():
            return None
        entry = structural[pretool_header.end():handler_header.start()]
        next_table = re.search(r"(?m)^\[", structural[handler_header.end():])
        handler_end = handler_header.end() + next_table.start() if next_table else len(structural)
        handler = structural[handler_header.end():handler_end]
        matcher_values = [value for _, value in re.findall(r"(?m)^matcher\s*=\s*(['\"])(.*?)\1\s*$", entry)]
        commands = [value for _, value in re.findall(r"(?m)^command\s*=\s*(['\"])(.*?)\1\s*$", handler)]
        windows_commands = [
            value.replace("\\\\", "\\")
            for _, value in re.findall(r"(?m)^command_windows\s*=\s*(['\"])(.*?)\1\s*$", handler)
        ]
        type_values = re.findall(r'(?m)^type\s*=\s*["\']([^"\']+)["\']\s*$', handler)
        timeout_values = re.findall(r"(?m)^timeout\s*=\s*(\d+)\s*$", handler)
        async_values = re.findall(r"(?mi)^async\s*=\s*(true|false)\s*$", handler)
    else:
        frontmatter = _claude_frontmatter(text)
        if frontmatter is None:
            return None
        hook_headers = list(re.finditer(r"(?m)^hooks:\s*$", frontmatter))
        if len(hook_headers) != 1:
            return None
        start = hook_headers[0].end()
        next_root = re.search(r"(?m)^\S", frontmatter[start:])
        block_end = start + next_root.start() if next_root else len(frontmatter)
        block = frontmatter[start:block_end]
        # Enforce the normalized YAML nesting rather than accepting the same
        # words in a comment, body, fenced example, or unrelated mapping.
        if len(re.findall(r"(?m)^  PreToolUse:\s*$", block)) != 1:
            return None
        if len(re.findall(r"(?m)^      hooks:\s*$", block)) != 1:
            return None
        matcher_values = [
            value for _, value in re.findall(r"(?m)^    - matcher:\s*(['\"])(.*?)\1\s*$", block)
        ]
        commands = [
            value for _, value in re.findall(r"(?m)^          command:\s*(['\"])(.*?)\1\s*$", block)
        ]
        windows_commands = []
        type_values = re.findall(r"(?m)^        - type:\s*([^\s#]+)\s*$", block)
        timeout_values = re.findall(r"(?m)^          timeout:\s*(\d+)\s*$", block)
        async_values = re.findall(r"(?mi)^          async:\s*(true|false)\s*$", block)
    return {
        "matchers": matcher_values,
        "commands": commands,
        "windows_commands": windows_commands,
        "types": type_values,
        "timeouts": timeout_values,
        "async_values": async_values,
    }


def _valid_native_guard_handler(handler: object, runtime: str, guard: str) -> bool:
    if not isinstance(handler, dict) or handler.get("type") != "command":
        return False
    if handler.get("async", False) is not False:
        return False
    timeout = handler.get("timeout")
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not 1 <= timeout <= 30:
        return False
    if runtime == "codex":
        return (
            handler.get("command") == f"python3 tools/guards/{guard} --hook codex"
            and handler.get("commandWindows") == f"py -3 tools\\guards\\{guard} --hook codex"
        )
    return handler.get("command") == f'python3 "$CLAUDE_PROJECT_DIR/tools/guards/{guard}" --hook claude'


def _codex_rules_forbid_git(text: str) -> bool:
    without_comments = re.sub(r"(?m)#.*$", "", text)
    blocks = re.findall(r"(?s)prefix_rule\s*\((.*?)\)\s*,?", without_comments)
    for block in blocks:
        decision = re.search(r'(?m)^\s*decision\s*=\s*["\']([^"\']+)["\']', block)
        pattern = re.search(r"(?ms)^\s*pattern\s*=\s*(\[.*?\])\s*,", block)
        if not decision or decision.group(1).casefold() != "forbidden" or not pattern:
            continue
        tokens = [token.casefold().replace("\\\\", "/") for token in re.findall(r'["\']([^"\']+)["\']', pattern.group(1))]
        if any(token == "git" or token == "git.exe" or token.endswith("/git") for token in tokens):
            return True
    return False


def _check_native_hook_wiring(root: Path, runtime: str, report: CheckReport) -> None:
    relative = ".codex/hooks.json" if runtime == "codex" else ".claude/settings.json"
    path = root / relative
    if not path.exists():
        return
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return  # The primary adapter parser reports the malformed file.
    hooks_mapping = payload.get("hooks", {})
    if not isinstance(hooks_mapping, dict) or set(hooks_mapping) != {"PreToolUse"}:
        report.add(
            "error", "native-hook-topology-invalid",
            f"{runtime} root hooks must contain exactly the checked PreToolUse event",
            path,
        )
        hooks_mapping = hooks_mapping if isinstance(hooks_mapping, dict) else {}
    pre_tool = hooks_mapping.get("PreToolUse", [])
    if not isinstance(pre_tool, list):
        report.add("error", "native-hooks-invalid", "PreToolUse hooks must be a list", path)
        return
    allowed_handler_keys = (
        {"type", "command", "commandWindows", "timeout", "statusMessage", "async"}
        if runtime == "codex" else
        {"type", "command", "timeout", "statusMessage", "async"}
    )
    for entry in pre_tool:
        if not isinstance(entry, dict) or set(entry).difference({"matcher", "hooks"}):
            report.add(
                "error", "native-hook-topology-invalid",
                f"{runtime} hook entries may contain only `matcher` and `hooks`",
                path,
            )
            continue
        handlers = entry.get("hooks")
        if not isinstance(handlers, list):
            report.add("error", "native-hook-topology-invalid", f"{runtime} hook entry has a non-list handler collection", path)
            continue
        for handler in handlers:
            if not isinstance(handler, dict) or set(handler).difference(allowed_handler_keys):
                report.add(
                    "error", "native-hook-topology-invalid",
                    f"{runtime} hook handler contains fields outside the checked schema",
                    path,
                )
    shell_tokens = (
        ("Bash", "Edit", "Write", "apply_patch")
        if runtime == "codex"
        else ("Bash", "PowerShell", "Monitor", "Edit", "Write", "NotebookEdit", "EnterWorktree")
    )
    shell_entries = [
        entry for entry in pre_tool
        if isinstance(entry, dict) and _matcher_exact(entry.get("matcher"), shell_tokens)
    ]
    if len(shell_entries) != 1:
        report.add(
            "error", "native-hook-matcher-invalid",
            f"{runtime} needs exactly one global hook matcher whose alternatives are: {', '.join(shell_tokens)}",
            path,
        )
    allowed_matchers = [
        frozenset(shell_tokens),
        frozenset(("Agent", "spawn_agent") if runtime == "codex" else ("Agent",)),
    ]
    if runtime == "claude":
        allowed_matchers.append(frozenset(("Read", "Glob", "Grep")))
    actual_matchers = [
        _matcher_alternatives(entry.get("matcher")) if isinstance(entry, dict) else None
        for entry in pre_tool
    ]
    if (
        len(pre_tool) != len(allowed_matchers)
        or any(actual is None for actual in actual_matchers)
        or sorted(tuple(sorted(value)) for value in actual_matchers if value is not None)
            != sorted(tuple(sorted(value)) for value in allowed_matchers)
    ):
        report.add(
            "error", "native-hook-topology-invalid",
            f"{runtime} PreToolUse must contain only the checked global, agent, and runtime-specific read matcher entries",
            path,
        )
    shell_handlers = [
        hook for entry in shell_entries
        for hook in (entry.get("hooks", []) if isinstance(entry.get("hooks"), list) else [])
    ]
    if len(shell_handlers) != 4:
        report.add(
            "error", "native-hook-topology-invalid",
            f"{runtime} global matcher must contain exactly four checked guard handlers, found {len(shell_handlers)}",
            path,
        )
    for guard in ("no_git.py", "no_worktree.py", "protect_evidence.py", "protect_runtime.py"):
        candidates = [
            hook for entry in shell_entries for hook in entry.get("hooks", [])
            if isinstance(hook, dict) and guard in (str(hook.get("command", "")) + str(hook.get("commandWindows", "")))
        ]
        if len(candidates) != 1 or not _valid_native_guard_handler(candidates[0], runtime, guard):
            report.add("error", "native-guard-not-wired", f"{runtime} shell/file hooks need exactly one synchronous, bounded, exact {guard} --hook {runtime} command handler", path)
    agent_tokens = ("Agent", "spawn_agent") if runtime == "codex" else ("Agent",)
    agent_entries = [
        entry for entry in pre_tool
        if isinstance(entry, dict) and _matcher_exact(entry.get("matcher"), agent_tokens)
    ]
    if len(agent_entries) != 1:
        report.add(
            "error", "native-agent-matcher-invalid",
            f"{runtime} needs exactly one agent-spawn hook matcher whose alternatives are: {', '.join(agent_tokens)}",
            path,
        )
    agent_worktree = [
        hook for entry in agent_entries for hook in entry.get("hooks", [])
        if isinstance(hook, dict) and "no_worktree.py" in (str(hook.get("command", "")) + str(hook.get("commandWindows", "")))
    ]
    if len(agent_worktree) != 1 or not _valid_native_guard_handler(agent_worktree[0], runtime, "no_worktree.py"):
        report.add("error", "native-worktree-agent-guard-missing", f"{runtime} agent-spawn hooks do not wire no_worktree.py", path)
    agent_handlers = [
        hook for entry in agent_entries
        for hook in (entry.get("hooks", []) if isinstance(entry.get("hooks"), list) else [])
    ]
    if len(agent_handlers) != 1:
        report.add(
            "error", "native-hook-topology-invalid",
            f"{runtime} agent matcher must contain exactly the checked no-worktree handler",
            path,
        )

    if runtime == "claude":
        read_entries = [
            entry for entry in pre_tool
            if isinstance(entry, dict) and _matcher_exact(entry.get("matcher"), ("Read", "Glob", "Grep"))
        ]
        read_handlers = [
            hook for entry in read_entries for hook in entry.get("hooks", [])
            if isinstance(hook, dict) and "no_git.py" in str(hook.get("command", ""))
        ]
        if len(read_entries) != 1 or len(read_handlers) != 1 or not _valid_native_guard_handler(
            read_handlers[0], runtime, "no_git.py",
        ):
            report.add(
                "error", "native-read-guard-missing",
                "Claude needs one exact Read|Glob|Grep matcher with a synchronous bounded no_git.py handler",
                path,
            )
        all_read_handlers = [
            hook for entry in read_entries
            for hook in (entry.get("hooks", []) if isinstance(entry.get("hooks"), list) else [])
        ]
        if len(all_read_handlers) != 1:
            report.add(
                "error", "native-hook-topology-invalid",
                "Claude Read|Glob|Grep matcher must contain exactly the checked no-Git handler",
                path,
            )
        worktree_entries = [
            entry for entry in pre_tool
            if isinstance(entry, dict)
            and _matcher_alternatives(entry.get("matcher")) is not None
            and "EnterWorktree" in _matcher_alternatives(entry.get("matcher"))
            and _matcher_exact(entry.get("matcher"), shell_tokens)
        ]
        worktree_handlers = [
            hook for entry in worktree_entries for hook in entry.get("hooks", [])
            if isinstance(hook, dict) and "no_worktree.py" in str(hook.get("command", ""))
        ]
        if len(worktree_handlers) != 1 or not _valid_native_guard_handler(worktree_handlers[0], runtime, "no_worktree.py"):
            report.add("error", "native-worktree-entry-guard-missing", "Claude EnterWorktree is not denied by an exact synchronous no_worktree handler", path)

    if runtime == "codex":
        rules = root / ".codex/rules/no-git.rules"
        rules_text = rules.read_text(encoding="utf-8", errors="replace") if rules.exists() else ""
        if not _codex_rules_forbid_git(rules_text):
            report.add("error", "native-no-git-deny-missing", "Codex native rule file lacks a forbidden prefix rule bound to a Git executable pattern", rules)
    else:
        denied = payload.get("permissions", {}).get("deny", [])
        denied_values = {str(value).casefold() for value in denied} if isinstance(denied, list) else set()
        required_denies = {
            "bash(git)", "powershell(git)", "read(/.git/**)", "edit(/.git/**)",
            "enterworktree", "agent(isolation:worktree)",
            "edit(/.claude/**)", "edit(/.codex/**)", "edit(/runtime/**)",
            "edit(/tools/guards/**)", "edit(/.agents/**)",
        }
        missing = sorted(required_denies.difference(denied_values))
        if missing:
            report.add("error", "native-no-git-deny-missing", f"Claude permissions omit native Git/.git denies: {', '.join(missing)}", path)
        default_mode = payload.get("permissions", {}).get("defaultMode")
        if default_mode not in {None, "default"}:
            report.add(
                "error", "claude-permission-default-unsafe",
                f"Claude permissions.defaultMode must be absent or `default`, found `{default_mode}`",
                path,
            )
        for permission_class in ("allow", "ask"):
            values = payload.get("permissions", {}).get(permission_class, [])
            if values not in (None, []):
                report.add(
                    "error", "claude-permission-escalation",
                    f"Claude permissions.{permission_class} must be absent or empty; project-level allow/ask additions can bypass the approval boundary",
                    path,
                )


def _check_codex_native_settings(root: Path, report: CheckReport) -> None:
    path = root / ".codex/config.toml"
    if not path.exists():
        return
    text = path.read_text(encoding="utf-8", errors="replace")

    def assignment(section: str | None, key: str) -> str | None:
        body = text
        if section is None:
            body = re.split(r"(?m)^\s*\[", text, maxsplit=1)[0]
        else:
            match = re.search(
                rf"(?ms)^\s*\[{re.escape(section)}\]\s*$\n(.*?)(?=^\s*\[|\Z)", text,
            )
            if not match:
                return None
            body = match.group(1)
        found = re.findall(rf"(?m)^\s*{re.escape(key)}\s*=\s*([^#\n]+?)\s*$", body)
        return found[0].strip().strip("\"'").casefold() if len(found) == 1 else None

    expected = (
        (None, "approval_policy", "on-request"),
        (None, "approvals_reviewer", "user"),
        (None, "sandbox_mode", "workspace-write"),
        (None, "allow_login_shell", "false"),
        ("sandbox_workspace_write", "network_access", "false"),
        ("features", "hooks", "true"),
        ("memories", "generate_memories", "false"),
        ("memories", "use_memories", "false"),
    )
    for section, key, wanted in expected:
        actual = assignment(section, key)
        if actual != wanted:
            location = f"[{section}] " if section else ""
            report.add("error", "codex-native-safety-drift", f"Codex config requires {location}{key}={wanted}, found {actual or 'missing/duplicate'}", path)


def check_adapters(root: Path, runtime: str) -> CheckReport:
    report = CheckReport()
    _check_runtime_safety_paths(root, report)
    if report.errors:
        return report
    adapter_text_paths = {
        root / "runtime/PROFILES.md", root / "tools/research.py",
        *(root / relative for relative in ADAPTER_INVENTORY[runtime]),
        *(root / "tools/guards" / name for name in GUARD_FILENAMES),
    }
    for path in sorted(adapter_text_paths, key=lambda value: value.as_posix()):
        if not path.is_file():
            continue
        try:
            path.read_text(encoding="utf-8")
        except UnicodeDecodeError as error:
            report.add(
                "error", "adapter-text-not-utf8",
                f"adapter/runtime safety text must be valid UTF-8: {error}",
                path,
            )
    if report.errors:
        return report
    if runtime == "claude":
        local_settings = root / ".claude/settings.local.json"
        if local_settings.exists():
            report.add(
                "error", "unexpected-runtime-local-override",
                "higher-precedence .claude/settings.local.json is unsupported and must not override checked adapter safety",
                local_settings,
            )
    runtime_directory = root / f".{runtime}"
    allowed_runtime_files = {
        Path(relative).as_posix()
        for relative in ADAPTER_INVENTORY[runtime]
        if relative.startswith(f".{runtime}/")
    }
    allowed_runtime_directories = {f".{runtime}"}
    for relative in allowed_runtime_files:
        parent = Path(relative).parent
        while parent.as_posix() not in {".", ""}:
            allowed_runtime_directories.add(parent.as_posix())
            parent = parent.parent
    if runtime_directory.exists() and not runtime_directory.is_symlink():
        for directory, child_directories, _ in os.walk(runtime_directory, topdown=True, followlinks=False):
            base = Path(directory)
            for name in child_directories:
                candidate = base / name
                relative = candidate.relative_to(root).as_posix()
                if relative not in allowed_runtime_directories or candidate.is_symlink():
                    report.add(
                        "error", "unexpected-runtime-adapter-file",
                        f"unexpected {runtime} project-runtime directory is outside the closed adapter inventory: {relative}",
                        candidate,
                    )
        for candidate in _walk_project_files(runtime_directory):
            candidate_relative = candidate.relative_to(root).as_posix()
            if candidate_relative not in allowed_runtime_files:
                report.add(
                    "error", "unexpected-runtime-adapter-file",
                    f"unexpected {runtime} project-runtime file is outside the closed adapter inventory: {candidate_relative}",
                    candidate,
                )
    agent_directory = root / (".codex/agents" if runtime == "codex" else ".claude/agents")
    agent_suffix = ".toml" if runtime == "codex" else ".md"
    expected_agent_paths = {
        (root / relative).resolve(strict=False)
        for relative in ADAPTER_INVENTORY[runtime]
        if relative.startswith(f".{runtime}/agents/")
    }
    if agent_directory.exists():
        for candidate in agent_directory.iterdir():
            if (
                candidate.is_file()
                and candidate.suffix.casefold() == agent_suffix
                and candidate.resolve(strict=False) not in expected_agent_paths
            ):
                report.add(
                    "error", "unexpected-agent-adapter",
                    f"unexpected loadable {runtime} agent definition is outside the checked allowlist: {candidate.name}",
                    candidate,
                )
    if runtime == "codex":
        rules_directory = root / ".codex/rules"
        if rules_directory.exists():
            for candidate in rules_directory.iterdir():
                if candidate.name != "no-git.rules":
                    report.add(
                        "error", "unexpected-runtime-rule",
                        f"unexpected Codex project rule is outside the checked allowlist: {candidate.name}",
                        candidate,
                    )
    else:
        rules_directory = root / ".claude/rules"
        if rules_directory.exists():
            for candidate in rules_directory.iterdir():
                report.add(
                    "error", "unexpected-runtime-rule",
                    f"Claude project rule files are unsupported by this adapter: {candidate.name}",
                    candidate,
                )
    profiles = root / "runtime/PROFILES.md"
    if not profiles.exists():
        report.add("error", "adapter-profiles-missing", "runtime/PROFILES.md is missing", profiles)
    elif ADAPTER_SCHEMA not in profiles.read_text(encoding="utf-8"):
        report.add("error", "adapter-schema-missing", f"profile file lacks schema marker `{ADAPTER_SCHEMA}`", profiles)

    expected_mappings: dict[str, tuple[str, str]] = {}
    if profiles.exists():
        profile_lines = profiles.read_text(encoding="utf-8").splitlines()
        try:
            profile_start, profile_end = _section_bounds(profile_lines, "Profile contract")
            profile_table = _find_table(profile_lines, profile_start, profile_end)
            profile_column = _column(profile_table.headers, ("Profile",))
            mapping_column = _column(
                profile_table.headers,
                ("Codex mapping",) if runtime == "codex" else ("Claude Code mapping", "Claude mapping"),
            )
            for _, cells in profile_table.rows:
                if max(profile_column, mapping_column) >= len(cells):
                    continue
                profile_name = cells[profile_column].strip().strip("`").casefold()
                values = re.findall(r"`([^`]+)`", cells[mapping_column])
                if len(values) >= 2:
                    if profile_name in expected_mappings:
                        report.add("error", "duplicate-profile-mapping", f"profile table repeats semantic profile `{profile_name}`", profiles)
                        continue
                    expected_mappings[profile_name] = (values[0].casefold(), values[1].casefold())
        except ResearchError as error:
            report.add("error", "profile-table-invalid", str(error), profiles)

    history_mappings, history_errors = _adapter_mapping_history(profiles)
    for error in history_errors:
        code = "mapping-history-duplicate" if error.startswith("duplicate ") else "mapping-history-incomplete" if "incomplete" in error else "mapping-history-invalid"
        report.add("error", code, error, profiles)
    for profile in SEMANTIC_PROFILES:
        historical = history_mappings.get((ADAPTER_SCHEMA.casefold(), runtime, profile))
        current = expected_mappings.get(profile)
        if current is not None and historical != current:
            report.add(
                "error", "mapping-history-current-drift",
                f"current {runtime}/{profile} mapping {current[0]}/{current[1]} is not the immutable `{ADAPTER_SCHEMA}` history row; assign a new adapter schema and append a complete history block before synchronizing",
                profiles,
            )

    for relative in ADAPTER_INVENTORY[runtime]:
        path = root / relative
        if not path.exists():
            report.add("error", "adapter-file-missing", f"required {runtime} adapter file is missing: {relative}", path)
            continue
        text = path.read_text(encoding="utf-8")
        syntax_errors: list[str] = []
        if runtime == "codex" and path.suffix == ".toml":
            syntax_errors = _codex_toml_shape_errors(text, agent="/.codex/agents/" in "/" + relative)
        elif runtime == "codex" and relative == ".codex/hooks.json":
            try:
                json.loads(text)
            except json.JSONDecodeError as error:
                syntax_errors = [f"invalid JSON: {error}"]
        elif runtime == "claude" and relative.startswith(".claude/agents/"):
            syntax_errors = _claude_frontmatter_shape_errors(text)
        for error in syntax_errors:
            report.add("error", "adapter-native-syntax-invalid", error, path)
        marker_required = not (runtime == "claude" and relative == ".claude/settings.json")
        if marker_required and ADAPTER_SCHEMA not in text:
            report.add("error", "adapter-schema-missing", f"adapter lacks schema marker `{ADAPTER_SCHEMA}`", path)
        if runtime == "claude" and relative == ".claude/settings.json":
            try:
                settings = json.loads(text)
            except json.JSONDecodeError as error:
                report.add("error", "adapter-json-invalid", f"invalid Claude settings JSON: {error}", path)
            else:
                if settings.get("autoMemoryEnabled") is not False:
                    report.add("error", "authoritative-memory-enabled", "Claude automatic memory must be disabled/non-authoritative", path)
                if settings.get("disableAllHooks", False) is not False:
                    report.add("error", "claude-hooks-disabled", "Claude disableAllHooks must be absent or false", path)
                if settings.get("enableAllProjectMcpServers", False) is not False:
                    report.add(
                        "error", "claude-project-mcp-autoenable",
                        "Claude enableAllProjectMcpServers must be absent or false; project MCP servers require explicit human review",
                        path,
                    )
                if settings.get("env", {}).get("RESEARCH_AGENT_ADAPTER_SCHEMA") != ADAPTER_SCHEMA:
                    report.add("error", "adapter-schema-missing", "Claude settings lacks the adapter schema environment marker", path)

    for guard_name in ("no_git.py", "no_worktree.py", "protect_shared.py", "protect_evidence.py", "protect_runtime.py"):
        guard = root / "tools/guards" / guard_name
        if not guard.exists():
            report.add("error", "guard-missing", f"runtime guard is missing: {guard_name}", guard)
        elif "--self-test" not in guard.read_text(encoding="utf-8"):
            report.add("error", "guard-self-test-missing", f"{guard_name} does not expose the required self-test", guard)

    common = root / "AGENTS.md"
    if common.exists():
        common_text = common.read_text(encoding="utf-8").casefold()
        if "git" not in common_text or not any(word in common_text for word in ("never", "prohibit", "forbidden", "do not")):
            report.add("error", "common-no-git-missing", "common instructions do not clearly prohibit Git operations", common)
    if runtime == "claude":
        claude = root / "CLAUDE.md"
        if claude.exists() and "@AGENTS.md" not in claude.read_text(encoding="utf-8"):
            report.add("error", "common-import-missing", "CLAUDE.md does not import @AGENTS.md", claude)

    existing_text = "\n".join(
        (root / relative).read_text(encoding="utf-8", errors="replace")
        for relative in ADAPTER_INVENTORY[runtime] if (root / relative).exists()
    )
    if "worktree" in existing_text.casefold() and "no_worktree.py" not in existing_text:
        report.add("error", "worktree-not-disabled", "adapter mentions worktrees without wiring the worktree-denial guard")
    if "no_git.py" not in existing_text:
        report.add("error", "guard-not-wired", f"{runtime} adapter does not reference tools/guards/no_git.py")
    if runtime == "claude":
        for variable in ("CLAUDE_CODE_SUBAGENT_MODEL", "CLAUDE_CODE_EFFORT_LEVEL"):
            if os.environ.get(variable):
                report.add("warning", "runtime-profile-override", f"environment variable {variable} may override checked-in subagent settings")

    _check_native_hook_wiring(root, runtime, report)
    if runtime == "codex":
        _check_codex_native_settings(root, report)

    role_profiles = {
        "maintenance": "maintenance", "coordinator": "coordinator", "substantive": "substantive",
        "deep": "deep", "pivotal": "pivotal", "verifier": "substantive",
        "verifier_deep": "deep", "verifier_pivotal": "pivotal",
    }
    for role, expected_profile in role_profiles.items():
        if expected_profile not in expected_mappings:
            report.add("error", "profile-mapping-missing", f"semantic mapping is missing for {expected_profile}", profiles)
            continue
        path = root / (f".codex/agents/{role}.toml" if runtime == "codex" else f".claude/agents/{role}.md")
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        if runtime == "codex":
            assignments = _toml_scalar_assignments(text)
            model_matches = assignments.get(("", "model"), [])
            effort_matches = assignments.get(("", "model_reasoning_effort"), [])
            safety_error = assignments.get(("", "sandbox_mode"), []) != ["workspace-write"]
            optional_safe_values = {
                ("", "approval_policy"): "on-request",
                ("", "approvals_reviewer"): "user",
                ("", "allow_login_shell"): "false",
                ("", "dangerously_bypass_approvals_and_sandbox"): "false",
                ("sandbox_workspace_write", "network_access"): "false",
                ("features", "hooks"): "true",
                ("memories", "generate_memories"): "false",
                ("memories", "use_memories"): "false",
            }
            for location, safe_value in optional_safe_values.items():
                values = assignments.get(location, [])
                if values and values != [safe_value]:
                    safety_error = True
            if safety_error:
                report.add(
                    "error", "agent-native-safety-drift",
                    f"Codex role {role} must remain workspace-write and may not weaken inherited hooks, approvals, network, login-shell, or memory policy",
                    path,
                )
        else:
            frontmatter = _claude_frontmatter(text) or ""
            model_matches = re.findall(r"(?m)^model:\s*([^\s#]+)", frontmatter)
            effort_matches = re.findall(r"(?m)^effort:\s*([^\s#]+)", frontmatter)
            permission_modes = re.findall(r"(?m)^permissionMode:\s*([^\s#]+)", frontmatter)
            if [value.casefold().strip("`\"'") for value in permission_modes] != ["default"]:
                report.add(
                    "error", "agent-native-safety-drift",
                    f"Claude role {role} must declare exactly one frontmatter permissionMode: default",
                    path,
                )
        if len(model_matches) != 1 or len(effort_matches) != 1:
            report.add("error", "adapter-field-count", f"{role} must contain exactly one model and one effort field", path)
        actual = (
            model_matches[0].casefold() if len(model_matches) == 1 else "",
            effort_matches[0].casefold() if len(effort_matches) == 1 else "",
        )
        if actual != expected_mappings[expected_profile]:
            report.add(
                "error", "adapter-profile-drift",
                f"{role} resolves to {actual[0] or 'missing'}/{actual[1] or 'missing'}, expected "
                f"{expected_mappings[expected_profile][0]}/{expected_mappings[expected_profile][1]}", path,
            )
        if role != "coordinator" and "protect_shared.py" not in text:
            report.add("error", "shared-protection-missing", f"focused role {role} does not wire protect_shared.py", path)
        if role == "coordinator" and "protect_shared.py" in text:
            report.add("error", "coordinator-overrestricted", "coordinator must not wire the focused shared-record guard", path)
        if role != "coordinator":
            required_surfaces = (
                ("Bash", "Edit", "Write", "apply_patch")
                if runtime == "codex"
                else ("Bash", "PowerShell", "Monitor", "Edit", "Write", "NotebookEdit")
            )
            hook_fields = _focused_hook_fields(text, runtime)
            matcher_values = hook_fields.get("matchers", []) if hook_fields else []
            if len(matcher_values) != 1 or not _matcher_exact(matcher_values[0], required_surfaces):
                report.add("error", "focused-hook-surface-missing", f"focused role {role} does not protect every shell/file write surface", path)
            guard_role = "verifier" if role.startswith("verifier") else role
            commands = hook_fields.get("commands", []) if hook_fields else []
            windows_commands = hook_fields.get("windows_commands", []) if hook_fields else []
            type_values = hook_fields.get("types", []) if hook_fields else []
            timeout_values = hook_fields.get("timeouts", []) if hook_fields else []
            async_values = hook_fields.get("async_values", []) if hook_fields else []
            if runtime == "codex":
                expected_command = f"python3 tools/guards/protect_shared.py --role {guard_role} --hook codex"
                expected_windows = f"py -3 tools\\guards\\protect_shared.py --role {guard_role} --hook codex"
            else:
                expected_command = f'python3 "$CLAUDE_PROJECT_DIR/tools/guards/protect_shared.py" --role {guard_role} --hook claude'
                expected_windows = ""
            type_ok = type_values == ["command"]
            timeout_ok = len(timeout_values) == 1 and 1 <= int(timeout_values[0]) <= 30
            async_ok = not async_values or async_values == ["false"]
            command_ok = commands == [expected_command]
            if runtime == "codex":
                command_ok = command_ok and windows_commands == [expected_windows]
            if not (command_ok and type_ok and timeout_ok and async_ok):
                report.add("error", "focused-hook-handler-invalid", f"focused role {role} needs one exact synchronous bounded protect_shared handler for guard role {guard_role}", path)
        if role.startswith("verifier") and "--role verifier" not in text:
            report.add("error", "verifier-protection-missing", f"verification role {role} does not use the claim-protecting verifier guard role", path)
        if re.search(r"(?mi)(?:worktree|isolation)\s*=\s*[\"']?(?:true|worktree)", text):
            report.add("error", "worktree-enabled", f"{role} enables forbidden worktree isolation", path)
    return report


def doctor(root: Path, runtime: str, build_paper: bool = False) -> CheckReport:
    report = check_project(root)
    report.extend(check_adapters(root, runtime))
    if sys.version_info < (3, 10):
        report.add("error", "python-version", "Python 3.10 or newer is required")
    else:
        report.add("info", "python-version", f"Python {sys.version_info.major}.{sys.version_info.minor} is available")

    runtime_executable = shutil.which("codex") if runtime == "codex" else shutil.which("claude")
    detected_runtime_version: str | None = None
    if runtime_executable:
        try:
            version_result = subprocess.run(
                [runtime_executable, "--version"], cwd=root, text=True,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=15, check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            report.add("warning", "runtime-version-unavailable", f"could not query {runtime} version: {error}")
        else:
            if version_result.returncode:
                report.add("warning", "runtime-version-unavailable", f"{runtime} --version failed: {version_result.stdout.strip()}")
            else:
                version_lines = [line.strip() for line in version_result.stdout.splitlines() if line.strip()]
                detected_runtime_version = version_lines[-1] if version_lines else None
                report.add("info", "runtime-version", detected_runtime_version or f"{runtime} version unavailable")
    else:
        report.add("warning", "runtime-unavailable", f"{runtime} command is not on PATH; desktop/runtime availability may differ")

    profiles = root / "runtime/PROFILES.md"
    baseline: str | None = None
    if profiles.exists():
        profile_text = profiles.read_text(encoding="utf-8", errors="replace")
        pattern = r"Codex CLI\s+`([^`]+)`" if runtime == "codex" else r"Claude Code\s+`([^`]+)`"
        match = re.search(pattern, profile_text)
        baseline = match.group(1) if match else None
    if detected_runtime_version is not None:
        if baseline is None:
            report.add("warning", "runtime-baseline-missing", f"no tested {runtime} version baseline is recorded; capabilities are unconfirmed", profiles)
        elif baseline not in detected_runtime_version:
            report.add(
                "warning", "runtime-version-baseline-mismatch",
                f"detected `{detected_runtime_version}`, while adapters were parse-checked on `{baseline}`; re-run native hook/status and harmless task canaries",
                profiles,
            )
        else:
            report.add("info", "runtime-baseline-match", f"detected runtime matches recorded parse-check baseline `{baseline}`", profiles)
    report.add(
        "info", "runtime-live-confirmation-required",
        "doctor validates static wiring and local guard self-tests only; native hook/status inspection and a harmless task receipt must confirm live model, effort, permission, memory, and hook resolution",
        profiles,
    )

    for guard_name in ("no_git.py", "no_worktree.py", "protect_shared.py", "protect_evidence.py", "protect_runtime.py"):
        guard = root / "tools/guards" / guard_name
        if guard.exists() and "--self-test" in guard.read_text(encoding="utf-8", errors="replace"):
            completed = subprocess.run(
                [sys.executable, str(guard), "--self-test"], cwd=root, text=True,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15, check=False,
            )
            if completed.returncode:
                report.add("error", "guard-self-test-failed", f"{guard_name} self-test failed: {(completed.stderr or completed.stdout).strip()}", guard)

    latexmk = shutil.which("latexmk")
    pdflatex = shutil.which("pdflatex")
    if latexmk or pdflatex:
        report.add("info", "latex-available", f"LaTeX engine detected: {latexmk or pdflatex}")
    else:
        report.add("warning", "latex-unavailable", "no latexmk or pdflatex executable detected; source validation remains available")
    if build_paper:
        engine = latexmk or pdflatex
        if not engine:
            report.add("error", "latex-build-unavailable", "cannot build the paper without latexmk or pdflatex")
        elif (root / "paper/main.tex").exists():
            with tempfile.TemporaryDirectory(prefix="research-paper-build-") as temporary_root_text:
                temporary_root = Path(temporary_root_text)
                temporary_paper = temporary_root / "paper"
                shutil.copytree(root / "paper", temporary_paper)
                temporary_literature = temporary_root / "literature"
                temporary_literature.mkdir()
                references = root / "literature/references.bib"
                if references.exists():
                    shutil.copy2(references, temporary_literature / "references.bib")
                if Path(engine).name == "latexmk":
                    command = [engine, "-pdf", "-interaction=nonstopmode", "-halt-on-error", "main.tex"]
                else:
                    command = [engine, "-interaction=nonstopmode", "-halt-on-error", "main.tex"]
                completed = subprocess.run(command, cwd=temporary_paper, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=120, check=False)
                if completed.returncode:
                    tail = "\n".join(completed.stdout.splitlines()[-12:])
                    report.add("error", "latex-build-failed", f"paper build failed:\n{tail}", root / "paper/main.tex")
                else:
                    report.add("info", "latex-build-passed", "paper built successfully in a temporary directory", root / "paper/main.tex")
    return report


def adapters(root: Path, runtime: str, check_only: bool) -> CheckReport:
    """Synchronize model/effort fields, or validate them with ``--check``.

    Hook, permission, memory, and safety configuration is never generated or
    rewritten here.  The sole mutation is copying reviewed semantic mappings
    from ``runtime/PROFILES.md`` into existing native agent definitions.
    """
    if not check_only:
        profiles = root / "runtime/PROFILES.md"
        if not profiles.exists():
            return CheckReport([Diagnostic("error", "adapter-profiles-missing", "runtime/PROFILES.md is missing", profiles)])
        lines = profiles.read_text(encoding="utf-8").splitlines()
        try:
            start, end = _section_bounds(lines, "Profile contract")
            table = _find_table(lines, start, end)
            profile_column = _column(table.headers, ("Profile",))
            mapping_column = _column(
                table.headers,
                ("Codex mapping",) if runtime == "codex" else ("Claude Code mapping", "Claude mapping"),
            )
            mappings: dict[str, tuple[str, str]] = {}
            for _, cells in table.rows:
                values = re.findall(r"`([^`]+)`", cells[mapping_column]) if mapping_column < len(cells) else []
                if profile_column < len(cells) and len(values) >= 2:
                    profile_name = cells[profile_column].strip().strip("`").casefold()
                    if profile_name in mappings:
                        raise ResearchError(f"profile table repeats semantic profile {profile_name}")
                    mappings[profile_name] = (values[0], values[1])
            history, history_errors = _adapter_mapping_history(profiles)
            if history_errors:
                raise ResearchError("adapter mapping history is invalid: " + "; ".join(history_errors))
            for profile, mapping in mappings.items():
                recorded = history.get((ADAPTER_SCHEMA.casefold(), runtime, profile))
                normalized = (mapping[0].casefold(), mapping[1].casefold())
                if recorded != normalized:
                    raise ResearchError(
                        f"{runtime}/{profile} changed under `{ADAPTER_SCHEMA}`; assign a new adapter schema and append its complete mapping-history rows before synchronization"
                    )
            rendered_updates: list[tuple[Path, str]] = []
            role_profiles = {
                "maintenance": "maintenance", "coordinator": "coordinator", "substantive": "substantive",
                "deep": "deep", "pivotal": "pivotal", "verifier": "substantive",
                "verifier_deep": "deep", "verifier_pivotal": "pivotal",
            }
            for role, profile in role_profiles.items():
                if profile not in mappings:
                    raise ResearchError(f"profile table has no usable mapping for {profile}")
                path = root / (f".codex/agents/{role}.toml" if runtime == "codex" else f".claude/agents/{role}.md")
                if not path.exists():
                    raise ResearchError(f"cannot synchronize missing adapter file: {path.relative_to(root)}")
                text = path.read_text(encoding="utf-8")
                model, effort = mappings[profile]
                if runtime == "codex":
                    model_pattern = r'(?m)^(model\s*=\s*)["\'][^"\']+["\']\s*$'
                    effort_pattern = r'(?m)^(model_reasoning_effort\s*=\s*)["\'][^"\']+["\']\s*$'
                    if len(re.findall(model_pattern, text)) != 1 or len(re.findall(effort_pattern, text)) != 1:
                        raise ResearchError(f"adapter has duplicate or missing model/effort fields: {path.relative_to(root)}")
                    text, model_count = re.subn(
                        model_pattern,
                        lambda match: f'{match.group(1)}"{model}"', text, count=1,
                    )
                    text, effort_count = re.subn(
                        effort_pattern,
                        lambda match: f'{match.group(1)}"{effort}"', text, count=1,
                    )
                else:
                    model_pattern = r"(?m)^(model:\s*)[^\s#]+\s*$"
                    effort_pattern = r"(?m)^(effort:\s*)[^\s#]+\s*$"
                    if len(re.findall(model_pattern, text)) != 1 or len(re.findall(effort_pattern, text)) != 1:
                        raise ResearchError(f"adapter has duplicate or missing model/effort fields: {path.relative_to(root)}")
                    text, model_count = re.subn(
                        model_pattern, lambda match: f"{match.group(1)}{model}", text, count=1,
                    )
                    text, effort_count = re.subn(
                        effort_pattern, lambda match: f"{match.group(1)}{effort}", text, count=1,
                    )
                if model_count != 1 or effort_count != 1:
                    raise ResearchError(f"adapter has no unique model/effort fields: {path.relative_to(root)}")
                rendered_updates.append((path, text))
            for path, text in rendered_updates:
                _atomic_write(path, text)
        except ResearchError as error:
            return CheckReport([Diagnostic("error", "adapter-sync-failed", str(error), profiles)])
    report = check_adapters(root, runtime)
    if not check_only and not report.errors:
        report.add("info", "adapter-current", f"{runtime} model/effort mappings synchronized to {ADAPTER_SCHEMA}")
    return report


def _print_report(report: CheckReport, root: Path) -> None:
    order = {"error": 0, "warning": 1, "info": 2}
    for item in sorted(report.diagnostics, key=lambda item: (order.get(item.severity, 9), item.code, str(item.path or ""))):
        print(item.render(root))
    print(f"Summary: {len(report.errors)} error(s), {len(report.warnings)} warning(s)")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Maintain and validate a text-first research workspace")
    parser.add_argument("--root", type=Path, default=None, help=argparse.SUPPRESS)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("init", help="create missing workspace structure without overwriting research")

    new_parser = subparsers.add_parser("new", help="allocate and create a durable artifact")
    new_parser.add_argument("kind", choices=tuple(ARTIFACT_SPECS))
    new_parser.add_argument("--title", default="Untitled", help="human-readable title")
    new_parser.add_argument("--claim", default=None, help="target CLM-#### when creating a review")
    new_parser.add_argument("--search", action="store_true", help="create a consequential-search LIT record")

    subparsers.add_parser("check", help="validate artifact and epistemic invariants")

    doctor_parser = subparsers.add_parser("doctor", help="check project, adapter, guard, and optional tool readiness")
    doctor_parser.add_argument("--runtime", choices=("codex", "claude"), required=True)
    doctor_parser.add_argument("--build-paper", action="store_true", help="compile the paper into a temporary directory")

    adapter_parser = subparsers.add_parser("adapters", help="synchronize or validate checked-in runtime adapters")
    adapter_parser.add_argument("--runtime", choices=("codex", "claude"), required=True)
    adapter_parser.add_argument("--check", action="store_true", help="read-only adapter drift and conformance check")
    return parser


def _find_root(explicit: Path | None) -> Path:
    if explicit is not None:
        return explicit.resolve()
    configured = os.environ.get("RESEARCH_PROJECT_ROOT")
    if configured:
        return Path(configured).resolve()
    current = Path.cwd().resolve()
    for candidate in (current, *current.parents):
        if (candidate / "ARTIFACT_INDEX.md").exists():
            return candidate
    return current


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    arguments = parser.parse_args(argv)
    root = _find_root(arguments.root)
    try:
        if arguments.command == "init":
            created = initialize(root)
            print(f"Initialized {root}; created {len(created)} missing path(s).")
            print("Review PROJECT.md and explicitly accept contract revision 1 before autonomous research.")
            return 0
        if arguments.command == "new":
            if arguments.claim and arguments.kind != "review":
                raise ResearchError("--claim is valid only with `new review`")
            if arguments.search and arguments.kind != "literature":
                raise ResearchError("--search is valid only with `new literature`")
            if arguments.kind == "review" and not arguments.claim:
                raise ResearchError("`new review` requires --claim CLM-#### to bind an exact revision and digest")
            ident, path = create_artifact(
                root, arguments.kind, arguments.title, arguments.claim, arguments.search
            )
            print(f"Created {ident}: {path.as_posix()}")
            return 0
        if arguments.command == "check":
            report = check_project(root)
        elif arguments.command == "doctor":
            report = doctor(root, arguments.runtime, arguments.build_paper)
        elif arguments.command == "adapters":
            report = adapters(root, arguments.runtime, arguments.check)
        else:  # pragma: no cover - argparse makes this unreachable
            parser.error(f"unknown command {arguments.command}")
            return 2
        _print_report(report, root)
        return 1 if report.errors else 0
    except (ResearchError, OSError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
