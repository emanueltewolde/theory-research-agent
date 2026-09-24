from __future__ import annotations

import hashlib
import importlib.util
import io
import contextlib
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
import unittest
from unittest import mock


REPOSITORY = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("research_cli", REPOSITORY / "tools/research.py")
assert SPEC and SPEC.loader
research = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = research
SPEC.loader.exec_module(research)


def diagnostic_codes(report):
    return {item.code for item in report.diagnostics}


class ProjectFixture(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="research-cli-test-")
        self.root = Path(self.temporary.name) / "project"
        shutil.copytree(
            REPOSITORY,
            self.root,
            ignore=shutil.ignore_patterns(".git", "__pycache__", "*.pyc", ".research-id-allocation.lock"),
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def accept_contract(self) -> None:
        project = self.root / "PROJECT.md"
        text = project.read_text(encoding="utf-8")
        text = text.replace("- **Contract revision:** 0", "- **Contract revision:** 1", 1)
        text = text.replace("- **Contract status:** uninitialized", "- **Contract status:** accepted", 1)
        text = re.sub(r"(?m)^- \*\*Project title:\*\*.*$", "- **Project title:** Synthetic finite-model project", text)
        text = re.sub(r"(?m)^- \*\*Research mode:\*\*.*$", "- **Research mode:** definite", text)
        section_values = {
            "Objective and intended contribution": "Prove or disprove the stated finite-model conjecture.",
            "Formal model": "Finite sets, total functions, and explicit quantifiers.",
            "Central definitions": "All objects use the approved finite model.",
            "Permitted assumptions": "Classical finite mathematics.",
            "Prohibited shortcuts": "None beyond the approved model.",
            "Scope and exclusions": "Only the stated finite model is in scope.",
            "Relevant background": "None beyond the approved synthetic fixture.",
            "Success criteria": "A fresh independently reviewed proof or counterexample.",
            "Expected deliverable": "A provenance-backed mathematical note.",
            "Operational constraints": (
                "- **Data and privacy:** synthetic fixture data only\n"
                "- **External actions:** require human approval\n"
                "- **Dependencies:** standard library only\n"
                "- **Focused-agent cost envelope:** no live model calls\n"
                "- **Runtime constraints:** filesystem-only validation\n"
                "- **Human overview cadence:** every two to three substantial runs"
            ),
            "Human-alignment triggers": "Any change to quantifier order requires a human decision.",
            "Initially unresolved questions": "None.",
        }
        for heading, body in section_values.items():
            text = re.sub(
                rf"(?ms)^## {re.escape(heading)}\s*\n.*?(?=^## |\Z)",
                f"## {heading}\n\n{body}\n\n", text, count=1,
            )
        revision_separator = "|---:|---|---|---|"
        text = text.replace(
            revision_separator,
            revision_separator + "\n| 1 | 2026-08-17 | Synthetic contract explicitly accepted by the human | None |",
            1,
        )
        project.write_text(text, encoding="utf-8")
        for relative in ("STATE.md", "research/DIRECTIONS.md", "research/INBOX.md"):
            path = self.root / relative
            content = path.read_text(encoding="utf-8")
            content = content.replace("- **Contract revision:** 0", "- **Contract revision:** 1", 1)
            if relative == "STATE.md":
                content = content.replace("- **State revision:** 0", "- **State revision:** 1", 1)
                content = re.sub(
                    r"(?ms)^## Active objective\s*\n.*?(?=^## |\Z)",
                    "## Active objective\n\nResolve the approved finite-model conjecture.\n\n",
                    content, count=1,
                )
                content = re.sub(
                    r"(?ms)^## Strongest validated results\s*\n.*?(?=^## |\Z)",
                    "## Strongest validated results\n\nNone.\n\n",
                    content, count=1,
                )
                content = re.sub(
                    r"(?ms)^## Blockers and unresolved human questions\s*\n.*?(?=^## |\Z)",
                    "## Blockers and unresolved human questions\n\nNone.\n\n",
                    content, count=1,
                )
                content = re.sub(
                    r"(?ms)^## Recommended next action\s*\n.*?(?=^## |\Z)",
                    "## Recommended next action\n\nBegin a bounded proof or counterexample search for the approved conjecture.\n\n",
                    content, count=1,
                )
            path.write_text(content, encoding="utf-8")
        overview = self.root / "OVERVIEW.md"
        overview_text = overview.read_text()
        overview_text = overview_text.replace("- **Overview status:** initial blank template", "- **Overview status:** stale", 1)
        overview_text = overview_text.replace("- **Contract revision covered:** 0", "- **Contract revision covered:** 1", 1)
        overview_text = overview_text.replace("- **State revision covered:** 0", "- **State revision covered:** 1", 1)
        overview.write_text(overview_text)

    def set_label(self, relative: str, label: str, value: str) -> None:
        path = self.root / relative
        text = path.read_text(encoding="utf-8")
        text, count = re.subn(
            rf"(?m)^- \*\*{re.escape(label)}:\*\*\s*.*$",
            f"- **{label}:** {value}", text, count=1,
        )
        self.assertEqual(count, 1, (relative, label))
        path.write_text(text, encoding="utf-8")

    def set_registry_status(self, ident: str, status: str) -> None:
        path = self.root / "ARTIFACT_INDEX.md"
        lines = path.read_text(encoding="utf-8").splitlines()
        header = next(research._split_table_row(line) for line in lines if line.startswith("| ID |"))
        status_column = [research._normal_header(cell) for cell in header].index("status")
        for index, line in enumerate(lines):
            cells = research._split_table_row(line)
            if cells and cells[0] == ident:
                cells[status_column] = status
                lines[index] = "| " + " | ".join(cells) + " |"
                path.write_text("\n".join(lines) + "\n", encoding="utf-8")
                return
        self.fail(f"missing registry row {ident}")

    def make_review_ready_claim(self, title: str = "Review-ready target"):
        claim_id, relative = research.create_artifact(self.root, "claim", title)
        path = self.root / relative
        text = path.read_text()
        text = text.replace("- **Status:** draft", "- **Status:** candidate", 1)
        text = text.replace(
            "[theorem | lemma | counterexample | impossibility | empirical observation | literature-derived proposition]",
            "theorem", 1,
        )
        text = text.replace("- **Evidence class:** pending", "- **Evidence class:** mathematical proof", 1)
        sections = {
            "Exact statement": "Every approved finite instance has nonnegative value.",
            "Assumptions, quantifiers, scope, and exceptions": (
                "- **Model and domain:** the approved finite model\n"
                "- **Permitted assumptions used:** finiteness only\n"
                "- **Quantifier order:** for every approved finite instance\n"
                "- **Scope limitations:** none\n"
                "- **Exceptional cases:** none"
            ),
            "Relationship to the project question": "This candidate would resolve the approved synthetic objective.",
            "Dependencies": "None.",
            "Evidence": (
                "- **Primary evidence:** direct mathematical derivation\n"
                "- **Evidence location:** the proof section below\n"
                "- **What the evidence establishes:** the exact recorded statement"
            ),
            "Proof or derivation": "The value is a finite sum of nonnegative terms.",
            "Known limitations and open issues": "None.",
        }
        for heading, body in sections.items():
            text = re.sub(
                rf"(?ms)^## {re.escape(heading)}\s*\n.*?(?=^## |\Z)",
                f"## {heading}\n\n{body}\n\n", text, count=1,
            )
        path.write_text(text)
        self.set_registry_status(claim_id, "candidate")
        return claim_id, relative

    def make_validated_claim(self, run_id=None):
        if run_id is None:
            self.accept_contract()
            run_id, run_relative = research.create_artifact(self.root, "run", "Verification run")
        else:
            run_relative = Path("runs") / run_id / "RUN.md"
        tasks = (self.root / run_relative).parent / "tasks"
        task_code = f"T{len(list(tasks.glob('T*'))) + 1:02d}"
        task_id = f"{run_id}-{task_code}"
        task_dir = tasks / task_code
        task_dir.mkdir()
        for filename in ("TASK.md", "OUTPUT.md", "RECEIPT.md"):
            source = (self.root / "templates" / filename.lower()).read_text()
            source = source.replace("RUN-####-T##", task_id).replace("RUN-####", run_id)
            if filename == "TASK.md":
                source = source.replace("- **Contract revision:** pending", "- **Contract revision:** 1")
                source = source.replace("- **Base state revision:** pending", "- **Base state revision:** 1")
            elif filename == "RECEIPT.md":
                values = {
                    "Resolved provider": "OpenAI Codex",
                    "Resolved model": research._expected_runtime_mapping(self.root, "codex", "substantive")[0],
                    "Resolved effort": research._expected_runtime_mapping(self.root, "codex", "substantive")[1],
                    "Runtime mode": "focused",
                    "Runtime version": "codex-cli test",
                    "Adapter version": research.ADAPTER_SCHEMA, "Fresh context": "yes",
                    "Status": "completed", "Started": "2026-08-17T00:00:00Z",
                    "Ended": "2026-08-17T00:01:00Z",
                }
                for label, value in values.items():
                    source = re.sub(
                        rf"(?m)^- \*\*{re.escape(label)}:\*\*\s*.*$",
                        f"- **{label}:** {value}", source, count=1,
                    )
                receipt_sections = {
                    "Authoritative inputs received": "- The exact task packet and linked artifacts.",
                    "Permitted write boundary": "- This task directory and its preallocated review only.",
                    "Invocation summary": "Fresh focused verification using the requested profile.",
                    "Failure or substitution details": "None.",
                }
                for heading, body in receipt_sections.items():
                    source = re.sub(
                        rf"(?ms)^## {re.escape(heading)}\s*\n.*?(?=^## |\Z)",
                        f"## {heading}\n\n{body}\n\n", source, count=1,
                    )
                for label in ("Stayed within write boundary", "No target claim edited during verification", "No completed evidence overwritten", "No Git operation performed"):
                    source = re.sub(
                        rf"(?m)^- \*\*{re.escape(label)}:\*\*\s*.*$",
                        f"- **{label}:** yes", source, count=1,
                    )
            (task_dir / filename).write_text(source)
        claim_id, claim_relative = research.create_artifact(self.root, "claim", "A useful theorem")
        claim_path = self.root / claim_relative
        text = claim_path.read_text(encoding="utf-8")
        text = text.replace(
            "[theorem | lemma | counterexample | impossibility | empirical observation | literature-derived proposition]",
            "theorem",
        )
        text = text.replace("- **Evidence class:** pending", "- **Evidence class:** mathematical proof")
        text = text.replace("[Write the complete proposition. Include all quantifiers needed to read it without inference from the title.]", "For every finite instance, the value is nonnegative.")
        text = re.sub(
            r"(?ms)^## Assumptions, quantifiers, scope, and exceptions\s*\n.*?(?=^## |\Z)",
            "## Assumptions, quantifiers, scope, and exceptions\n\n- **Model and domain:** the approved finite model.\n- **Permitted assumptions used:** finiteness only.\n- **Quantifier order:** for every finite instance.\n- **Scope restrictions:** none.\n- **Exceptional cases:** none.\n\n",
            text, count=1,
        )
        text = text.replace("- **Status:** draft", "- **Status:** under review", 1)
        text = text.replace("- **Created in:** pending", f"- **Created in:** [{run_id}](../../runs/{run_id}/RUN.md)")
        text = text.replace("- **Last updated in:** pending", f"- **Last updated in:** [{run_id}](../../runs/{run_id}/RUN.md)")
        finalized_sections = {
            "Relationship to the project question": "This resolves the synthetic objective at the stated scope.",
            "Dependencies": "None.",
            "Evidence": f"- **Primary evidence:** mathematical proof\n- **Evidence location:** [task output](../../runs/{run_id}/tasks/{task_code}/OUTPUT.md)\n- **What the evidence establishes:** the exact statement.",
            "Proof or derivation": "Nonnegativity follows directly from the finite-model definition.",
            "Known limitations and open issues": "None.",
        }
        for heading, body in finalized_sections.items():
            text = re.sub(rf"(?ms)^## {re.escape(heading)}\s*\n.*?(?=^## |\Z)", f"## {heading}\n\n{body}\n\n", text, count=1)
        text = re.sub(
            r"(?m)^- \*\*Revision 1:\*\* \d{4}-\d{2}-\d{2} — Initial draft\.$",
            "- **Revision 1:** 2026-08-17 — Initial claim statement.\n"
            "- **Evidence revision 1:** 2026-08-17 — Initial proof and dependency packet.",
            text, count=1,
        )
        claim_path.write_text(text, encoding="utf-8")
        self.set_registry_status(claim_id, "under review")

        review_id, review_relative = research.create_artifact(
            self.root, "review", "Independent review", claim_id=claim_id
        )
        review_path = self.root / review_relative
        task_path = task_dir / "TASK.md"
        task_text = task_path.read_text()
        claim_labels = research._metadata(claim_path.read_text())
        digest = claim_labels["statement digest"]
        evidence_revision = claim_labels["evidence revision"]
        evidence_bound_digest = claim_labels["evidence digest"]
        receipt_path = task_dir / "RECEIPT.md"
        receipt_text = receipt_path.read_text()
        receipt_text = re.sub(
            r"(?ms)^## Authoritative inputs received\s*\n.*?(?=^## |\Z)",
            "## Authoritative inputs received\n\n"
            f"- [PROJECT.md](../../../../PROJECT.md), contract revision 1.\n"
            f"- [{claim_id}](../../../../{claim_relative.as_posix()}), the exact reviewed claim and evidence packet.\n\n",
            receipt_text, count=1,
        )
        receipt_path.write_text(receipt_text)
        task_text = re.sub(r"(?m)^- \*\*Status:\*\*.*$", "- **Status:** completed", task_text, count=1)
        task_text = re.sub(r"(?m)^- \*\*Fresh context required:\*\*.*$", "- **Fresh context required:** yes", task_text, count=1)
        task_text = re.sub(r"(?m)^- \*\*Assigned context:\*\*.*$", "- **Assigned context:** fresh synthetic verifier", task_text, count=1)
        task_text = re.sub(r"(?m)^- \*\*Created:\*\*.*$", "- **Created:** 2026-08-17", task_text, count=1)
        task_text = re.sub(
            r"(?m)^- \*\*Preallocated artifacts:\*\*.*$",
            f"- **Preallocated artifacts:** [{review_id}](../../../../{review_relative.as_posix()})", task_text, count=1,
        )
        task_text = re.sub(
            r"(?ms)^## Authoritative inputs\s*\n.*?(?=^## |\Z)",
            f"## Authoritative inputs\n\n- [PROJECT.md](../../../../PROJECT.md), contract revision: 1.\n"
            f"- Target [{claim_id}](../../../../{claim_relative.as_posix()}); claim revision: 1; statement digest: {digest}; "
            f"evidence revision: {evidence_revision}; evidence digest: {evidence_bound_digest}.\n\n",
            task_text, count=1,
        )
        for heading, body in {
            "Question": "Does the exact target claim follow under its recorded assumptions?",
            "Successful outcomes": "A pass, refutation, or precisely narrowed obstruction.",
            "Permitted and provisional assumptions": "Only the accepted finite-model assumptions; no provisional assumptions.",
            "Context packet": (
                f"Fresh verification packet for [{claim_id}](../../../../{claim_relative.as_posix()}), "
                f"claim revision 1, statement digest {digest}, evidence revision {evidence_revision}, "
                f"evidence digest {evidence_bound_digest}, and review "
                f"[{review_id}](../../../../{review_relative.as_posix()})."
            ),
        }.items():
            task_text = re.sub(
                rf"(?ms)^## {re.escape(heading)}\s*\n.*?(?=^## |\Z)",
                f"## {heading}\n\n{body}\n\n", task_text, count=1,
            )
        task_path.write_text(task_text)
        output_path = task_dir / "OUTPUT.md"
        output = output_path.read_text()
        output = re.sub(r"(?m)^- \*\*Status:\*\*.*$", "- **Status:** completed", output, count=1)
        output = re.sub(r"(?m)^- \*\*Outcome classification:\*\*.*$", "- **Outcome classification:** supported", output, count=1)
        output = re.sub(r"(?m)^- \*\*Completed:\*\*.*$", "- **Completed:** 2026-08-17", output, count=1)
        output_sections = {
            "Exact supported conclusions": "The exact target statement is supported.",
            "Evidence or derivation": "A reviewable finite-model derivation.",
            "Assumptions, scope, and exceptional cases": "Finiteness only; no exceptional cases.",
            "Counterexamples and disproofs": "None.",
            "Negative findings": "None.",
            "Uncertainties and verification needs": "Independent verification supplied by this task.",
            "Deferred findings": "None.",
            "Artifacts written": f"The assigned [{review_id}](../../../../{review_relative.as_posix()}) review only.",
            "Recommended next action": "Integrate the reviewed claim.",
        }
        for heading, body in output_sections.items():
            output = re.sub(rf"(?ms)^## {re.escape(heading)}\s*\n.*?(?=^## |\Z)", f"## {heading}\n\n{body}\n\n", output, count=1)
        output_path.write_text(output)
        review = review_path.read_text(encoding="utf-8")
        replacements = {
            "Status": "completed",
            "Verdict": "pass",
            "Task receipt": f"[receipt](../../runs/{run_id}/tasks/{task_code}/RECEIPT.md)",
            "Created in": f"[{run_id}](../../runs/{run_id}/RUN.md)",
            "Last updated in": f"[{run_id}](../../runs/{run_id}/RUN.md)",
            "Evidence or proof correct": "yes",
            "Establishes exact recorded statement": "yes",
            "Addresses intended project question at stated scope": "yes",
            "Assumptions accounted for": "yes",
            "Quantifier order checked": "yes",
            "Scope restrictions checked": "yes",
            "Exceptional cases checked": "yes",
        }
        for label, value in replacements.items():
            review, count = re.subn(
                rf"(?m)^- \*\*{re.escape(label)}:\*\*\s*.*$",
                f"- **{label}:** {value}", review, count=1,
            )
            self.assertEqual(count, 1, label)
        review = re.sub(
            r"(?ms)^## Materials supplied\s*\n.*?(?=^## |\Z)",
            f"## Materials supplied\n\n- [{claim_id}](../claims/{claim_id}.md), its exact definitions, dependencies, and evidence.\n\n",
            review, count=1,
        )
        review = re.sub(
            r"(?ms)^## Verdict rationale\s*\n.*?(?=^## |\Z)",
            "## Verdict rationale\n\nThe derivation is correct and matches the exact recorded claim.\n\n",
            review, count=1,
        )
        review = review.replace("[Explain defects or why the argument closes.]", "The argument closes under the recorded assumptions.")
        review = review.replace("[Check that the supported result is neither narrower nor differently quantified.]", "The statement, quantifiers, and project scope match exactly.")
        review = review.replace(
            "[List issues or write `none`.]",
            "No assumption, quantifier, scope, or exceptional-case defects were found.",
        )
        review_sections = {
            "Independence statement": "The verifier received a fresh exact packet without an expected verdict.",
            "Verification approach": "Reconstructed the finite derivation and checked each quantified case.",
            "Falsification and counterexample attempts": "Searched the finite boundary cases; none refuted the statement.",
            "Reproduction or source checks": "Not applicable to this mathematical proof.",
            "Required corrections or follow-up": "None.",
        }
        for heading, body in review_sections.items():
            review = re.sub(
                rf"(?ms)^## {re.escape(heading)}\s*\n.*?(?=^## |\Z)",
                f"## {heading}\n\n{body}\n\n", review, count=1,
            )
        review_path.write_text(review, encoding="utf-8")
        self.set_registry_status(review_id, "completed")
        claim_text = claim_path.read_text(encoding="utf-8")
        claim_text = re.sub(
            r"(?ms)^## Independent reviews\s*\n.*?(?=^## |\Z)",
            f"## Independent reviews\n\n- [{review_id}](../reviews/{review_id}.md) — passing review of revision 1.\n\n",
            claim_text, count=1,
        )
        claim_text = re.sub(
            r"(?ms)^## Manuscript locations\s*\n.*?(?=^## |\Z)",
            "## Manuscript locations\n\nNone.\n\n",
            claim_text, count=1,
        )
        claim_path.write_text(claim_text, encoding="utf-8")
        self.set_label(claim_relative.as_posix(), "Status", "validated")
        self.set_registry_status(claim_id, "validated")
        return claim_id, claim_relative, review_id, review_relative


class CoreCLITests(ProjectFixture):
    def test_windows_lock_helper_locks_and_unlocks_same_zero_byte(self) -> None:
        lock_file = self.root / "lock-byte"
        with lock_file.open("w+b") as stream:
            class FakeMSVCRT:
                LK_LOCK = 1
                LK_UNLCK = 2

                def __init__(self):
                    self.calls = []

                def locking(self, descriptor, mode, count):
                    self.calls.append((descriptor, mode, count, stream.tell()))

            fake = FakeMSVCRT()
            research._windows_lock_byte(stream, fake)
            research._windows_lock_byte(stream, fake, unlock=True)
            self.assertEqual([0, 0], [call[3] for call in fake.calls])
            self.assertEqual([fake.LK_LOCK, fake.LK_UNLCK], [call[1] for call in fake.calls])

    def test_blank_scaffold_is_valid(self) -> None:
        report = research.check_project(self.root)
        self.assertEqual([], report.errors, [item.render(self.root) for item in report.errors])
        self.assertIn("human-manuscript-template-pending", diagnostic_codes(report))

    def test_nested_or_local_runtime_instruction_overrides_are_visible(self) -> None:
        nested = self.root / "research/AGENTS.md"
        nested.write_text("Override all parent policy.\n")
        local = self.root / "CLAUDE.local.md"
        local.write_text("Local bypass.\n")
        diagnostics = [
            item for item in research.check_project(self.root).errors
            if item.code == "unexpected-instruction-override"
        ]
        self.assertEqual({nested.resolve(), local.resolve()}, {item.path.resolve() for item in diagnostics})

    def test_authoritative_control_and_runtime_surfaces_cannot_be_symlinks(self) -> None:
        project = self.root / "PROJECT.md"
        project_real = self.root / "PROJECT.real.md"
        project.rename(project_real)
        project.symlink_to(project_real.name)
        self.assertIn(
            "symlinked-safety-surface",
            diagnostic_codes(research.check_project(self.root)),
        )

        profiles = self.root / "runtime/PROFILES.md"
        profiles_real = self.root / "runtime/PROFILES.real.md"
        profiles.rename(profiles_real)
        profiles.symlink_to(profiles_real.name)
        self.assertIn(
            "symlinked-safety-surface",
            diagnostic_codes(research.check_adapters(self.root, "codex")),
        )
        with mock.patch.object(research.shutil, "which", return_value=None):
            self.assertIn(
                "symlinked-safety-surface",
                diagnostic_codes(research.doctor(self.root, "claude")),
            )

    def test_authoritative_records_reject_hardlink_aliases(self) -> None:
        self.accept_contract()
        report_id, relative = research.create_artifact(self.root, "report", "Immutable snapshot")
        self.set_label(relative.as_posix(), "Status", "published")
        self.set_registry_status(report_id, "published")
        os.link(self.root / relative, self.root / "report-alias.bin")
        self.assertIn(
            "hardlinked-authoritative-record",
            diagnostic_codes(research.check_project(self.root)),
        )

    def test_authoritative_utf8_audit_excludes_untrusted_experiment_payloads(self) -> None:
        bad_doc = self.root / "docs/non-utf8.md"
        bad_doc.write_bytes(b"\xff\xfe")
        self.assertIn(
            "authoritative-text-not-utf8",
            diagnostic_codes(research.check_project(self.root)),
        )
        bad_doc.unlink()

        untrusted = self.root / "experiments/untrusted/inputs/source.md"
        untrusted.parent.mkdir(parents=True)
        untrusted.write_bytes(b"# CLM-9999 - untrusted\n\xff")
        report = research.check_project(self.root)
        self.assertNotIn("authoritative-text-not-utf8", diagnostic_codes(report))
        self.assertNotIn("unregistered-artifact", diagnostic_codes(report))

    def test_validator_prunes_git_metadata_before_descent(self) -> None:
        metadata = self.root / ".git"
        metadata.mkdir()
        sentinel = metadata / "AGENTS.override.md"
        sentinel.write_text("This must never be inspected.\n")
        report = research.check_project(self.root)
        self.assertFalse(any(
            item.path is not None and ".git" in item.path.parts
            for item in report.diagnostics
        ))
        self.assertNotIn("unexpected-instruction-override", diagnostic_codes(report))

    def test_mathematical_brackets_are_not_template_prompts(self) -> None:
        self.accept_contract()
        project = self.root / "PROJECT.md"
        text = project.read_text().replace(
            "Finite sets, total functions, and explicit quantifiers.",
            "Let [n] = {1, ..., n}; valuations lie in [0,1].",
        )
        project.write_text(text)
        state = self.root / "STATE.md"
        state.write_text(state.read_text().replace(
            "Resolve the approved finite-model conjecture.",
            "Initialize weights over [n] and prove the stated bound.",
        ))
        self.assertFalse(research._contains_template_prompt("For every i in [n], x[i] lies in [0,1]."))
        ident, _ = research.create_artifact(self.root, "claim", "Bracket-safe claim")
        self.assertEqual("CLM-0001", ident)

    def test_accepted_contract_requires_current_human_revision_log_row(self) -> None:
        self.accept_contract()
        project = self.root / "PROJECT.md"
        project.write_text(project.read_text().replace(
            "| 1 | 2026-08-17 | Synthetic contract explicitly accepted by the human | None |\n",
            "",
            1,
        ))
        self.assertIn("invalid-contract-revision-log", diagnostic_codes(research.check_project(self.root)))
        before = (self.root / "ARTIFACT_INDEX.md").read_text()
        with self.assertRaises(research.ResearchError):
            research.create_artifact(self.root, "claim", "Blocked by missing decision")
        self.assertEqual(before, (self.root / "ARTIFACT_INDEX.md").read_text())

    def test_contract_revision_log_retains_contiguous_accepted_history(self) -> None:
        self.accept_contract()
        project = self.root / "PROJECT.md"
        text = project.read_text().replace(
            "- **Contract revision:** 1", "- **Contract revision:** 3", 1,
        ).replace(
            "| 1 | 2026-08-17 | Synthetic contract explicitly accepted by the human | None |",
            "| 3 | 2026-08-17 | Third revision accepted by the human | None |",
            1,
        )
        project.write_text(text)
        for relative in ("STATE.md", "research/DIRECTIONS.md", "research/INBOX.md"):
            path = self.root / relative
            path.write_text(path.read_text().replace(
                "- **Contract revision:** 1", "- **Contract revision:** 3", 1,
            ))
        report = research.check_project(self.root)
        self.assertIn("invalid-contract-revision-log", diagnostic_codes(report))
        messages = "\n".join(item.message for item in report.errors)
        self.assertIn("accepted revision 1", messages)
        self.assertIn("accepted revision 2", messages)

    def test_required_control_labels_must_be_in_the_preamble(self) -> None:
        state = self.root / "STATE.md"
        text = state.read_text().replace("- **State revision:** 0\n", "", 1)
        text += "\n## Decoy\n\n- **State revision:** 0\n"
        state.write_text(text)
        codes = diagnostic_codes(research.check_project(self.root))
        self.assertIn("missing-control-label", codes)
        self.assertIn("missing-revision", codes)

    def test_unaccepted_contract_blocks_allocation_without_advancing_counter(self) -> None:
        before = (self.root / "ARTIFACT_INDEX.md").read_text(encoding="utf-8")
        with self.assertRaises(research.ResearchError):
            research.create_artifact(self.root, "claim", "No authority yet")
        self.assertEqual(before, (self.root / "ARTIFACT_INDEX.md").read_text(encoding="utf-8"))

    def test_title_injection_is_rejected_without_allocation(self) -> None:
        self.accept_contract()
        before = research.ArtifactIndex((self.root / "ARTIFACT_INDEX.md").read_text()).counters()
        for title in ("bad\n## CLM-9999", "bad | injected | row", "{{ID}} confusion"):
            with self.assertRaises(research.ResearchError):
                research.create_artifact(self.root, "claim", title)
        after = research.ArtifactIndex((self.root / "ARTIFACT_INDEX.md").read_text()).counters()
        self.assertEqual(before, after)

    def test_missing_template_fails_closed_without_allocation(self) -> None:
        self.accept_contract()
        (self.root / "templates/claim.md").unlink()
        before = (self.root / "ARTIFACT_INDEX.md").read_text()
        with self.assertRaises(research.ResearchError):
            research.create_artifact(self.root, "claim", "Cannot render")
        self.assertEqual(before, (self.root / "ARTIFACT_INDEX.md").read_text())
        self.assertFalse((self.root / "research/claims/CLM-0001.md").exists())

    def test_invalid_template_contract_fails_check_and_preallocation(self) -> None:
        self.accept_contract()
        template = self.root / "templates/claim.md"
        template.write_text(template.read_text().replace("## Evidence\n", "## Broken evidence heading\n", 1))
        self.assertIn("invalid-template-contract", diagnostic_codes(research.check_project(self.root)))
        before = (self.root / "ARTIFACT_INDEX.md").read_text()
        with self.assertRaises(research.ResearchError):
            research.create_artifact(self.root, "claim", "Must not allocate")
        self.assertEqual(before, (self.root / "ARTIFACT_INDEX.md").read_text())
        self.assertFalse((self.root / "research/claims/CLM-0001.md").exists())

    def test_template_with_second_top_level_record_fails_before_allocation(self) -> None:
        self.accept_contract()
        template = self.root / "templates/claim.md"
        template.write_text(template.read_text() + "\n# {{ID}} — hidden duplicate record\n")
        self.assertIn("invalid-template-contract", diagnostic_codes(research.check_project(self.root)))
        before = (self.root / "ARTIFACT_INDEX.md").read_text()
        with self.assertRaises(research.ResearchError):
            research.create_artifact(self.root, "claim", "Duplicate-template canary")
        self.assertEqual(before, (self.root / "ARTIFACT_INDEX.md").read_text())

    def test_rendered_template_is_rechecked_against_concurrent_drift(self) -> None:
        self.accept_contract()
        before = (self.root / "ARTIFACT_INDEX.md").read_text()
        original = research._render_template
        claim_renders = 0

        def drifting_render(root, kind, values):
            nonlocal claim_renders
            rendered = original(root, kind, values)
            if kind == "claim":
                claim_renders += 1
                if claim_renders >= 2:
                    return rendered.replace("## Evidence\n", "## Drifted evidence\n", 1)
            return rendered

        with mock.patch.object(research, "_render_template", side_effect=drifting_render):
            with self.assertRaises(research.ResearchError):
                research.create_artifact(self.root, "claim", "Concurrent drift")
        self.assertEqual(before, (self.root / "ARTIFACT_INDEX.md").read_text())
        self.assertFalse((self.root / "research/claims/CLM-0001.md").exists())

    def test_every_public_template_requires_its_canonical_id_heading(self) -> None:
        for kind in (*research.ARTIFACT_SPECS, "search", "execution", "task", "output", "receipt"):
            with self.subTest(kind=kind):
                template = self.root / "templates" / f"{kind}.md"
                original = template.read_text()
                lines = original.splitlines()
                lines[0] = "# BROKEN-9999 — wrong ID"
                template.write_text("\n".join(lines) + ("\n" if original.endswith("\n") else ""))
                self.assertTrue(research._template_contract_errors(self.root, kind))
                template.write_text(original)

    def test_concurrent_allocations_are_distinct_and_monotonic(self) -> None:
        self.accept_contract()
        with ThreadPoolExecutor(max_workers=6) as executor:
            results = list(executor.map(
                lambda number: research.create_artifact(self.root, "claim", f"Concurrent {number}")[0],
                range(12),
            ))
        self.assertEqual([f"CLM-{number:04d}" for number in range(1, 13)], sorted(results))
        index = research.ArtifactIndex((self.root / "ARTIFACT_INDEX.md").read_text())
        self.assertEqual(12, index.counters()["CLM"])
        self.assertEqual(12, len([entry for entry in index.registry() if entry.ident.startswith("CLM-")]))

    def test_index_publish_failure_leaves_recoverable_unregistered_artifact(self) -> None:
        self.accept_contract()
        index_path = self.root / "ARTIFACT_INDEX.md"
        before = index_path.read_text()
        original = research._atomic_write

        def fail_index(path, text):
            if path == index_path:
                raise OSError("synthetic index publication failure")
            return original(path, text)

        with mock.patch.object(research, "_atomic_write", side_effect=fail_index):
            with self.assertRaises(research.ResearchError):
                research.create_artifact(self.root, "claim", "Recoverable")
        self.assertEqual(before, index_path.read_text())
        self.assertTrue((self.root / "research/claims/CLM-0001.md").exists())
        self.assertIn("unregistered-artifact", diagnostic_codes(research.check_project(self.root)))

    def test_new_run_refuses_pending_recovery_without_mutation(self) -> None:
        self.accept_contract()
        run_id, run_path = research.create_artifact(self.root, "run", "First run")
        self.set_label(run_path.as_posix(), "Status", "completed")
        self.set_registry_status(run_id, "completed")
        self.set_label("STATE.md", "Integration condition", "recovery required")
        self.set_label("STATE.md", "Active run", "none")
        before = (self.root / "ARTIFACT_INDEX.md").read_text()
        with self.assertRaises(research.ResearchError):
            research.create_artifact(self.root, "run", "Must wait")
        self.assertEqual(before, (self.root / "ARTIFACT_INDEX.md").read_text())

    def test_every_allocation_refuses_a_contradictory_clean_run_state(self) -> None:
        self.accept_contract()
        research.create_artifact(self.root, "run", "Active integration")
        self.set_label("STATE.md", "Integration condition", "clean")
        self.set_label("STATE.md", "Active run", "none")
        before = (self.root / "ARTIFACT_INDEX.md").read_text()
        with self.assertRaises(research.ResearchError):
            research.create_artifact(self.root, "claim", "Must reconcile first")
        self.assertEqual(before, (self.root / "ARTIFACT_INDEX.md").read_text())

    def test_cli_main_returns_documented_exit_codes(self) -> None:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(0, research.main(["--root", str(self.root), "check"]))
            self.assertEqual(2, research.main(["--root", str(self.root), "new", "claim"]))

    def test_direction_and_inbox_append_to_shared_ledgers(self) -> None:
        self.accept_contract()
        direction, direction_path = research.create_artifact(self.root, "direction", "Boundary cases")
        inbox, inbox_path = research.create_artifact(self.root, "inbox", "Check mixed strategies")
        self.assertEqual(Path("research/DIRECTIONS.md"), direction_path)
        self.assertEqual(Path("research/INBOX.md"), inbox_path)
        self.assertIn(f"## {direction} — Boundary cases", (self.root / direction_path).read_text())
        self.assertIn(f"## {inbox} — Check mixed strategies", (self.root / inbox_path).read_text())

    def test_parked_direction_and_new_inbox_are_immediately_triageable(self) -> None:
        self.accept_contract()
        direction_id, _ = research.create_artifact(self.root, "direction", "Boundary cases")
        inbox_id, _ = research.create_artifact(self.root, "inbox", "Deferred observation")
        codes = diagnostic_codes(research.check_project(self.root))
        self.assertIn("mature-direction-incomplete", codes)
        self.assertIn("inbox-core-incomplete", codes)

        replacements = {
            direction_id: {
                "Research question": "Does the bound hold on every boundary instance?",
                "Why it matters": "It discriminates the main conjecture from a strict interior variant.",
                "Current obstacle": "The boundary characterization is unknown.",
                "Next discriminating action": "Analyze the smallest nontrivial boundary instance.",
                "Stop condition": "Stop if a validated counterexample resolves the direction.",
                "Revival condition": "Revive after a stronger structural lemma.",
            },
            inbox_id: {
                "Source": "Human initialization discussion.",
                "Finding or question": "Check whether the boundary case changes the quantifier order.",
                "Why it matters": "It may narrow the primary theorem statement.",
            },
        }
        for ident, values in replacements.items():
            ledger = self.root / ("research/DIRECTIONS.md" if ident.startswith("DIR-") else "research/INBOX.md")
            text = ledger.read_text()
            block = research._embedded_block(text, ident)
            updated = block
            for label, value in values.items():
                updated, count = re.subn(
                    rf"(?m)^- \*\*{re.escape(label)}:\*\*.*$",
                    f"- **{label}:** {value}", updated, count=1,
                )
                self.assertEqual(1, count)
            ledger.write_text(text.replace(block, updated, 1))
        codes = diagnostic_codes(research.check_project(self.root))
        self.assertNotIn("mature-direction-incomplete", codes)
        self.assertNotIn("inbox-core-incomplete", codes)

    def test_dashboard_and_artifact_durable_ids_must_be_canonical_links(self) -> None:
        self.accept_contract()
        first_id, first_relative = research.create_artifact(self.root, "claim", "First draft")
        second_id, second_relative = research.create_artifact(self.root, "claim", "Second draft")
        state = self.root / "STATE.md"
        state.write_text(re.sub(
            r"(?ms)^## Recommended next action\s*\n.*?(?=^## |\Z)",
            f"## Recommended next action\n\nCompare {second_id} with the active objective.\n\n",
            state.read_text(), count=1,
        ))
        self.set_label(first_relative.as_posix(), "Related artifacts", second_id)
        self.assertIn(
            "bare-durable-cross-reference",
            diagnostic_codes(research.check_project(self.root)),
        )

        state.write_text(state.read_text().replace(
            second_id,
            f"[{second_id}]({second_relative.as_posix()})",
            1,
        ))
        self.set_label(
            first_relative.as_posix(), "Related artifacts",
            f"[{second_id}]({second_id}.md)",
        )
        self.assertNotIn(
            "bare-durable-cross-reference",
            diagnostic_codes(research.check_project(self.root)),
        )
        report = research.check_project(self.root)
        self.assertEqual([], report.errors, [item.render(self.root) for item in report.errors])

    def test_overview_and_task_records_reject_bare_durable_cross_references(self) -> None:
        self.accept_contract()
        claim_id, _ = research.create_artifact(self.root, "claim", "Cross-reference target")
        overview = self.root / "OVERVIEW.md"
        overview.write_text(re.sub(
            r"(?ms)^## Important open claims\s*\n.*?(?=^## |\Z)",
            f"## Important open claims\n\nInvestigate {claim_id}.\n\n",
            overview.read_text(), count=1,
        ))
        run_id, run_relative = research.create_artifact(self.root, "run", "Task link audit")
        task_dir = (self.root / run_relative).parent / "tasks/T01"
        task_dir.mkdir(parents=True)
        task = (self.root / "templates/task.md").read_text()
        task = task.replace("RUN-####-T##", f"{run_id}-T01").replace("RUN-####", run_id)
        task = task.replace("- **Related artifacts:** none", f"- **Related artifacts:** {claim_id}", 1)
        (task_dir / "TASK.md").write_text(task)
        diagnostics = [
            item for item in research.check_project(self.root).errors
            if item.code == "bare-durable-cross-reference"
        ]
        paths = {item.path.resolve().relative_to(self.root.resolve()).as_posix() for item in diagnostics}
        self.assertIn("OVERVIEW.md", paths)
        self.assertIn(f"runs/{run_id}/tasks/T01/TASK.md", paths)

    def test_dangerous_alignment_item_requires_affected_direction_pause(self) -> None:
        self.accept_contract()
        direction_id, _ = research.create_artifact(self.root, "direction", "Affected branch")
        inbox_id, _ = research.create_artifact(self.root, "inbox", "Consequential ambiguity")
        directions = self.root / "research/DIRECTIONS.md"
        directions.write_text(directions.read_text().replace(
            f"## {direction_id} — Affected branch\n\n- **Activity:** parked",
            f"## {direction_id} — Affected branch\n\n- **Activity:** active",
            1,
        ))
        inbox = self.root / "research/INBOX.md"
        text = inbox.read_text()
        replacements = {
            "Kind": "human alignment",
            "Uncertainty class": "dangerous now",
            "Why it matters": "The model choice changes the theorem.",
            "Provisional assumption": "Use the narrower model temporarily.",
            "Dependent artifacts": "none yet",
            "Safe continuation horizon": "No further work on this branch.",
            "Affected branch": f"[{direction_id}](DIRECTIONS.md#{direction_id.casefold()}--affected-branch)",
            "Human answer": "pending",
        }
        block = research._embedded_block(text, inbox_id)
        for label, value in replacements.items():
            block = re.sub(
                rf"(?m)^- \*\*{re.escape(label)}:\*\*.*$",
                f"- **{label}:** {value}", block, count=1,
            )
        inbox.write_text(text.replace(research._embedded_block(text, inbox_id), block, 1))
        self.assertIn(
            "dangerous-alignment-branch-unpaused",
            diagnostic_codes(research.check_project(self.root)),
        )

    def test_literature_search_uses_search_template_and_path(self) -> None:
        self.accept_contract()
        ident, path = research.create_artifact(
            self.root, "literature", "Equilibrium lower bounds", literature_search=True
        )
        self.assertEqual(Path(f"literature/searches/{ident}.md"), path)
        self.assertIn("consequential literature search", (self.root / path).read_text())
        self.assertNotIn("missing-artifact-heading", diagnostic_codes(research.check_project(self.root)))

    def test_literature_record_kind_is_closed_vocabulary(self) -> None:
        self.accept_contract()
        _, relative = research.create_artifact(self.root, "literature", "Unknown form")
        self.set_label(relative.as_posix(), "Record kind", "mystery ingestion")
        self.assertIn(
            "invalid-literature-record-kind",
            diagnostic_codes(research.check_project(self.root)),
        )

    def test_bibliography_keys_are_unique_case_insensitively(self) -> None:
        bibliography = self.root / "literature/references.bib"
        bibliography.write_text(
            "@article{UniqueKey, title={One}}\n"
            "@inproceedings{uniquekey, title={Two}}\n"
        )
        self.assertIn(
            "duplicate-bibtex-key",
            diagnostic_codes(research.check_project(self.root)),
        )

    def test_execution_rows_and_completion_manifests_are_bijective(self) -> None:
        self.accept_contract()
        experiment_id, relative = research.create_artifact(self.root, "experiment", "Manifest canary")
        readme = self.root / relative
        execution_id = f"{experiment_id}-E001"
        text = readme.read_text().replace(
            "| pending | pending | pending | pending | pending | pending | pending | pending | pending |",
            f"| [{execution_id}](executions/{execution_id}/COMPLETED.md) | 2026-08-17 | run --fixed | input.dat | 7 | result.json | sha256:abc | success | none |",
            1,
        )
        readme.write_text(text)
        execution_dir = readme.parent / "executions" / execution_id
        execution_dir.mkdir()
        self.assertIn("execution-manifest-missing", diagnostic_codes(research.check_project(self.root)))
        (execution_dir / "COMPLETED.md").write_text(
            f"# {execution_id} — Completed execution manifest\n\n"
            f"- **Execution ID:** {execution_id}\n"
            "- **Completed:** 2026-08-17T00:00:00Z\n"
            "- **Command/config:** run --fixed\n"
            "- **Inputs:** input.dat\n"
            "- **Outputs:** result.json\n"
            "- **Output digest:** sha256:abc\n"
            "- **Result:** success\n"
        )
        codes = diagnostic_codes(research.check_project(self.root))
        self.assertNotIn("execution-manifest-missing", codes)
        self.assertNotIn("invalid-execution-manifest", codes)
        readme.write_text(readme.read_text().replace("run --fixed", "run --changed", 1))
        self.assertIn(
            "execution-manifest-row-mismatch",
            diagnostic_codes(research.check_project(self.root)),
        )
        os.link(execution_dir / "COMPLETED.md", self.root / "execution-manifest-alias")
        focused = research.CheckReport()
        research._check_experiments(self.root, focused)
        self.assertIn("execution-manifest-hardlinked", diagnostic_codes(focused))

    def test_terminal_attempt_literature_and_experiment_finalize_nested_fields(self) -> None:
        self.accept_contract()
        attempt_id, attempt_relative = research.create_artifact(self.root, "attempt", "Incomplete failure")
        self.set_label(attempt_relative.as_posix(), "Status", "completed")
        self.set_label(attempt_relative.as_posix(), "Outcome", "failed")
        self.set_label(attempt_relative.as_posix(), "Assigned question", "Why did the approach fail?")
        self.set_registry_status(attempt_id, "completed")

        literature_id, literature_relative = research.create_artifact(self.root, "literature", "Incomplete source")
        self.set_label(literature_relative.as_posix(), "Status", "completed")
        self.set_label(literature_relative.as_posix(), "BibTeX key", "missing-key")
        self.set_label(literature_relative.as_posix(), "Stable locator", "https://example.invalid/paper")
        self.set_registry_status(literature_id, "completed")

        experiment_id, experiment_relative = research.create_artifact(self.root, "experiment", "Incomplete protocol")
        self.set_label(experiment_relative.as_posix(), "Status", "completed")
        self.set_registry_status(experiment_id, "completed")

        report = research.check_project(self.root)
        messages = "\n".join(item.message for item in report.errors)
        self.assertIn("`## Assumptions used`", messages)
        self.assertIn("bibliographic field `authors`", messages)
        self.assertIn("`dependency manifest`", messages)

    def test_new_report_stays_draft_in_record_and_registry(self) -> None:
        self.accept_contract()
        ident, path = research.create_artifact(self.root, "report", "First milestone")
        self.assertEqual("draft", research._metadata((self.root / path).read_text())["status"])
        entry = next(e for e in research.ArtifactIndex((self.root / "ARTIFACT_INDEX.md").read_text()).registry() if e.ident == ident)
        self.assertEqual("draft", entry.status)
        self.assertNotIn("registry-status-mismatch", diagnostic_codes(research.check_project(self.root)))

    def test_human_trust_surfaces_reject_draft_strongest_results(self) -> None:
        self.accept_contract()
        claim_id, claim_relative = research.create_artifact(self.root, "claim", "Still only a draft")
        report_id, report_relative = research.create_artifact(self.root, "report", "Unsafe milestone")
        for relative, target in (
            ("STATE.md", claim_relative.as_posix()),
            ("OVERVIEW.md", claim_relative.as_posix()),
        ):
            path = self.root / relative
            text = re.sub(
                r"(?ms)^## Strongest validated results\s*\n.*?(?=^## |\Z)",
                f"## Strongest validated results\n\n- [{claim_id}]({target}) — not actually validated.\n\n",
                path.read_text(), count=1,
            )
            path.write_text(text)
        self.set_label(report_relative.as_posix(), "Status", "published")
        self.set_registry_status(report_id, "published")
        report_path = self.root / report_relative
        report_path.write_text(re.sub(
            r"(?ms)^## Strongest validated results\s*\n.*?(?=^## |\Z)",
            f"## Strongest validated results\n\n- [{claim_id}](../{claim_relative.as_posix()})\n\n",
            report_path.read_text(), count=1,
        ))
        diagnostics = [
            item for item in research.check_project(self.root).errors
            if item.code == "trusted-result-not-validated"
        ]
        self.assertEqual(3, len(diagnostics))
        self.assertEqual(
            {"STATE.md", "OVERVIEW.md", report_relative.as_posix()},
            {item.path.resolve().relative_to(self.root.resolve()).as_posix() for item in diagnostics},
        )

    def test_trusted_result_surfaces_require_explicit_none_or_canonical_claims(self) -> None:
        self.accept_contract()
        for relative in ("STATE.md", "OVERVIEW.md"):
            path = self.root / relative
            path.write_text(re.sub(
                r"(?ms)^## Strongest validated results\s*\n.*?(?=^## |\Z)",
                "## Strongest validated results\n\nA theorem has been established, but no artifact is linked.\n\n",
                path.read_text(), count=1,
            ))
        diagnostics = [
            item for item in research.check_project(self.root).errors
            if item.code == "trusted-result-surface-unstructured"
        ]
        self.assertEqual(2, len(diagnostics))
        self.assertFalse(research._contract_mature(self.root))
        before = (self.root / "ARTIFACT_INDEX.md").read_text()
        with self.assertRaises(research.ResearchError):
            research.create_artifact(self.root, "claim", "Blocked by unstructured resume state")
        self.assertEqual(before, (self.root / "ARTIFACT_INDEX.md").read_text())

    def test_published_report_requires_canonical_run_links(self) -> None:
        self.accept_contract()
        report_id, relative = research.create_artifact(self.root, "report", "Untraceable")
        self.set_label(relative.as_posix(), "Status", "published")
        self.set_label(relative.as_posix(), "Runs covered", "RUN-9999")
        self.set_label(relative.as_posix(), "Prepared in", "manual narrative")
        self.set_registry_status(report_id, "published")
        self.assertIn(
            "published-report-run-links-invalid",
            diagnostic_codes(research.check_project(self.root)),
        )

    def test_published_report_requires_date_state_revision_and_canonical_supersession(self) -> None:
        self.accept_contract()
        report_id, relative = research.create_artifact(self.root, "report", "Bad snapshot metadata")
        self.set_label(relative.as_posix(), "Status", "published")
        self.set_label(relative.as_posix(), "Report date", "someday")
        self.set_label(relative.as_posix(), "State revision", "999")
        self.set_label(relative.as_posix(), "Supersedes", "RPT-9999")
        self.set_registry_status(report_id, "published")
        codes = diagnostic_codes(research.check_project(self.root))
        self.assertIn("published-report-date-invalid", codes)
        self.assertIn("published-report-state-revision-invalid", codes)
        self.assertIn("published-report-supersedes-invalid", codes)

    def test_published_report_cannot_cover_an_unintegrated_run(self) -> None:
        self.accept_contract()
        run_id, _ = research.create_artifact(self.root, "run", "Still active")
        report_id, relative = research.create_artifact(self.root, "report", "Premature snapshot")
        self.set_label(relative.as_posix(), "Status", "published")
        run_link = f"[{run_id}](../runs/{run_id}/RUN.md)"
        self.set_label(relative.as_posix(), "Runs covered", run_link)
        self.set_label(relative.as_posix(), "Prepared in", run_link)
        self.set_registry_status(report_id, "published")
        self.assertIn(
            "published-report-run-not-integrated",
            diagnostic_codes(research.check_project(self.root)),
        )

    def test_accepted_contract_and_state_require_operational_and_resume_fields(self) -> None:
        self.accept_contract()
        project = self.root / "PROJECT.md"
        project_original = project.read_text()
        project.write_text(re.sub(
            r"(?m)^- \*\*Data and privacy:\*\*.*\n", "", project_original, count=1,
        ))
        self.assertFalse(research._contract_mature(self.root))
        before = (self.root / "ARTIFACT_INDEX.md").read_text()
        with self.assertRaises(research.ResearchError):
            research.create_artifact(self.root, "claim", "Blocked by incomplete operations")
        self.assertEqual(before, (self.root / "ARTIFACT_INDEX.md").read_text())
        project.write_text(project_original)

        state = self.root / "STATE.md"
        state.write_text(re.sub(
            r"(?ms)^## Recommended next action\s*\n.*?(?=^## |\Z)",
            "## Recommended next action\n\nNone.\n\n",
            state.read_text(), count=1,
        ))
        codes = diagnostic_codes(research.check_project(self.root))
        self.assertIn("state-next-action-missing", codes)
        self.assertFalse(research._contract_mature(self.root))
        with self.assertRaises(research.ResearchError):
            research.create_artifact(self.root, "claim", "Blocked by immature resume state")
        self.assertEqual(before, (self.root / "ARTIFACT_INDEX.md").read_text())

    def test_terminal_punctuation_cannot_disguise_missing_substantive_content(self) -> None:
        self.accept_contract()
        project = self.root / "PROJECT.md"
        mature_project = project.read_text()
        project.write_text(re.sub(
            r"(?ms)^## Formal model\s*\n.*?(?=^## |\Z)",
            "## Formal model\n\nNone.\n\n", mature_project, count=1,
        ))
        self.assertFalse(research._contract_mature(self.root))
        with self.assertRaises(research.ResearchError):
            research.create_artifact(self.root, "claim", "No model")

        # Restore a mature contract, then prove the same normalization is used
        # at the review-allocation boundary.
        project.write_text(mature_project)
        claim_id, claim_relative = self.make_review_ready_claim("None canary")
        claim = self.root / claim_relative
        claim.write_text(re.sub(
            r"(?ms)^## Exact statement\s*\n.*?(?=^## |\Z)",
            "## Exact statement\n\nNone.\n\n", claim.read_text(), count=1,
        ))
        before = (self.root / "ARTIFACT_INDEX.md").read_text()
        with self.assertRaises(research.ResearchError):
            research.create_artifact(self.root, "review", "Must not allocate", claim_id=claim_id)
        self.assertEqual(before, (self.root / "ARTIFACT_INDEX.md").read_text())

    def test_new_run_publishes_active_state_last(self) -> None:
        self.accept_contract()
        ident, _ = research.create_artifact(self.root, "run", "Explore the main conjecture")
        labels = research._metadata((self.root / "STATE.md").read_text())
        self.assertEqual(2, research._integer_in(labels["state revision"]))
        self.assertEqual("active run", labels["integration condition"])
        self.assertIn(ident, labels["active run"])
        report = research.check_project(self.root)
        self.assertEqual([], report.errors, [item.render(self.root) for item in report.errors])

    def test_integrated_run_requires_a_newer_published_state_revision(self) -> None:
        self.accept_contract()
        run_id, run_relative = research.create_artifact(self.root, "run", "Integration revision canary")
        run_path = self.root / run_relative
        text = run_path.read_text()
        text = text.replace("- **Status:** active", "- **Status:** completed", 1)
        text = text.replace("- **Integration status:** not integrated", "- **Integration status:** integrated", 1)
        for label in (
            "Outputs reconciled", "Durable findings promoted", "Portfolio and inbox updated",
            "Artifact index updated", "Manuscript provenance checked", "State published last",
        ):
            text = re.sub(
                rf"(?m)^- \*\*{re.escape(label)}:\*\*.*$",
                f"- **{label}:** yes", text, count=1,
            )
        text = text.replace(
            "- **Final integration note:** [Complete before changing Integration status to `integrated`.]",
            "- **Final integration note:** Integrated into the published resume state.",
            1,
        )
        run_path.write_text(text)
        self.set_registry_status(run_id, "completed")
        self.set_label("STATE.md", "Last integrated run", f"[{run_id}](runs/{run_id}/RUN.md)")
        self.set_label("STATE.md", "Integration condition", "clean")
        self.set_label("STATE.md", "Active run", "none")
        # Opening the run moved STATE 1 -> 2; integration must move it again.
        self.assertEqual(2, research._state_revision(self.root))
        self.assertIn(
            "integrated-run-state-not-advanced",
            diagnostic_codes(research.check_project(self.root)),
        )

    def test_integrated_run_task_ids_must_appear_in_the_task_column(self) -> None:
        self.make_validated_claim()
        run_path = next(self.root.glob("runs/RUN-*/RUN.md"))
        run_id = run_path.parent.name
        text = run_path.read_text().replace(
            "| pending | pending | pending | pending | pending | pending |",
            f"| none | Mentions {run_id}-T01 only here | substantive | completed | "
            f"[output](tasks/T01/OUTPUT.md) | [receipt](tasks/T01/RECEIPT.md) |",
            1,
        )
        run_path.write_text(text)
        focused = research.CheckReport()
        research._check_integrated_run_tasks(self.root, run_id, run_path, focused)
        self.assertIn("run-task-table-mismatch", diagnostic_codes(focused))

    def test_review_requires_target_and_populates_exact_digest(self) -> None:
        self.accept_contract()
        with self.assertRaises(research.ResearchError):
            research.create_artifact(self.root, "review", "Unbound review")
        claim_id, claim_path = self.make_review_ready_claim("Target")
        review_id, review_path = research.create_artifact(
            self.root, "review", "Review target", claim_id=claim_id
        )
        claim_labels = research._metadata((self.root / claim_path).read_text())
        review_labels = research._metadata((self.root / review_path).read_text())
        self.assertRegex(claim_labels["statement digest"], r"^sha256:[0-9a-f]{64}$")
        self.assertEqual(claim_labels["statement digest"], review_labels["target statement digest"])
        self.assertRegex(claim_labels["evidence digest"], r"^sha256:[0-9a-f]{64}$")
        self.assertEqual(claim_labels["evidence revision"], review_labels["target evidence revision"])
        self.assertEqual(claim_labels["evidence digest"], review_labels["target evidence digest"])
        self.assertEqual(review_id, research._canonical_artifact(self.root / review_path)[0])
        self.assertNotIn("stale-review-digest", diagnostic_codes(research.check_project(self.root)))

    def test_review_allocation_requires_current_contract_target(self) -> None:
        self.accept_contract()
        claim_id, claim_relative = self.make_review_ready_claim("Old-contract target")
        self.set_label(claim_relative.as_posix(), "Contract revision", "0")
        before = (self.root / "ARTIFACT_INDEX.md").read_text()
        with self.assertRaises(research.ResearchError):
            research.create_artifact(self.root, "review", "Stale review", claim_id=claim_id)
        self.assertEqual(before, (self.root / "ARTIFACT_INDEX.md").read_text())

    def test_review_allocation_requires_all_fixed_assumption_fields(self) -> None:
        self.accept_contract()
        claim_id, claim_relative = self.make_review_ready_claim("Incomplete scope packet")
        claim = self.root / claim_relative
        claim.write_text(re.sub(
            r"(?m)^- \*\*Quantifier order:\*\*.*$",
            "- **Quantifier order:** pending.", claim.read_text(), count=1,
        ))
        before = (self.root / "ARTIFACT_INDEX.md").read_text()
        with self.assertRaises(research.ResearchError):
            research.create_artifact(self.root, "review", "Unready packet", claim_id=claim_id)
        self.assertEqual(before, (self.root / "ARTIFACT_INDEX.md").read_text())

    def test_claim_digest_follows_documented_whitespace_rule(self) -> None:
        text = (
            "# CLM-0001 — x\r\n\r\n## Exact statement\r\n\r\n  keep leading  \r\nsecond\t \r\n\r\n"
            "## Assumptions, quantifiers, scope, and exceptions\r\n\r\nA  \r\n  B\r\n\r\n## Next\r\nignored\r\n"
        )
        payload = "EXACT STATEMENT\n  keep leading\nsecond\nASSUMPTIONS, QUANTIFIERS, SCOPE, AND EXCEPTIONS\nA\n  B"
        expected = "sha256:" + hashlib.sha256(payload.encode()).hexdigest()
        self.assertEqual(expected, research.claim_digest(text))

    def test_evidence_digest_follows_documented_fixed_vector(self) -> None:
        text = (
            "# CLM-0001 — Vector\r\n\r\n"
            "- **Claim kind:** theorem\r\n"
            "- **Evidence class:** mathematical proof\r\n\r\n"
            "## Relationship to the project question\r\n\r\nResolves it.\r\n\r\n"
            "## Dependencies\r\n\r\n- CLM-0000   \r\n\r\n"
            "## Evidence\r\n\r\n- witness table   \r\n\r\n"
            "## Proof or derivation\r\n\r\nLine one.   \r\nLine two.\r\n\r\n"
            "## Known limitations and open issues\r\n\r\nNone.\r\n"
        )
        payload = (
            "DEPENDENCIES\n- CLM-0000\n"
            "EVIDENCE\n- witness table\n"
            "PROOF OR DERIVATION\nLine one.\nLine two.\n"
            "CLAIM KIND\ntheorem\n"
            "EVIDENCE CLASS\nmathematical proof\n"
            "RELATIONSHIP TO THE PROJECT QUESTION\nResolves it.\n"
            "KNOWN LIMITATIONS AND OPEN ISSUES\nNone."
        )
        expected = "sha256:" + hashlib.sha256(payload.encode()).hexdigest()
        self.assertEqual(expected, research.evidence_digest(text))

    def test_dependency_cycle_detector_finds_validated_multi_claim_cycle(self) -> None:
        cycles = research._dependency_cycle_members({
            "CLM-0001": {"CLM-0002"},
            "CLM-0002": {"CLM-0003"},
            "CLM-0003": {"CLM-0001"},
            "CLM-0004": set(),
        })
        self.assertEqual([frozenset({"CLM-0001", "CLM-0002", "CLM-0003"})], cycles)

    def test_id_gap_requires_registry_reservation(self) -> None:
        self.accept_contract()
        index = self.root / "ARTIFACT_INDEX.md"
        text = index.read_text().replace("| CLM | Claim, theorem, counterexample, impossibility, or empirical proposition | 0 |", "| CLM | Claim, theorem, counterexample, impossibility, or empirical proposition | 2 |")
        index.write_text(text)
        self.assertIn("unaccounted-id", diagnostic_codes(research.check_project(self.root)))

    def test_numeric_control_and_counter_fields_reject_mixed_text(self) -> None:
        self.accept_contract()
        self.set_label("STATE.md", "State revision", "1 and 999")
        self.assertIn("missing-revision", diagnostic_codes(research.check_project(self.root)))

        self.set_label("STATE.md", "State revision", "1")
        index = self.root / "ARTIFACT_INDEX.md"
        index.write_text(re.sub(
            r"(?m)^\| RUN \|([^|]*)\| 0 \|$",
            r"| RUN |\1| 0 and 999 |", index.read_text(), count=1,
        ))
        self.assertIn("missing-counter", diagnostic_codes(research.check_project(self.root)))

    def test_zero_durable_ids_and_t00_are_never_valid_allocations(self) -> None:
        self.accept_contract()
        zero_claim = self.root / "research/claims/CLM-0000.md"
        zero_claim.write_text(research._render_template(
            self.root, "claim", {
                "ID": "CLM-0000", "TITLE": "Invalid zero claim",
                "DATE": "2026-08-17", "CONTRACT_REVISION": "1",
            },
        ))
        index = self.root / "ARTIFACT_INDEX.md"
        marker = "|---|---|---|---|---|---|---|"
        index.write_text(index.read_text().replace(
            marker,
            marker
            + "\n| CLM-0000 | claim | Invalid zero claim | draft | "
            "[research/claims/CLM-0000.md](research/claims/CLM-0000.md) | none | none |",
            1,
        ))
        self.assertIn("zero-artifact-id", diagnostic_codes(research.check_project(self.root)))

        run_id, run_relative = research.create_artifact(self.root, "run", "Task zero canary")
        task_zero = (self.root / run_relative).parent / "tasks/T00"
        task_zero.mkdir()
        codes = diagnostic_codes(research.check_project(self.root))
        self.assertIn("invalid-task-path", codes)
        self.assertTrue(run_id.startswith("RUN-0001"))

    def test_real_artifact_cannot_remain_reserved_or_abandoned(self) -> None:
        self.accept_contract()
        ident, _ = research.create_artifact(self.root, "claim", "Real claim")
        for status in ("reserved", "abandoned"):
            self.set_registry_status(ident, status)
        self.assertIn("realized-reservation-status", diagnostic_codes(research.check_project(self.root)))

    def test_supersession_and_terminal_negative_records_keep_typed_traceability(self) -> None:
        self.accept_contract()
        first_id, _ = research.create_artifact(self.root, "claim", "Earlier claim")
        second_id, second_relative = research.create_artifact(self.root, "claim", "Refuted successor")
        literature_id, literature_relative = research.create_artifact(self.root, "literature", "Wrong kind")
        self.set_label(
            second_relative.as_posix(), "Supersedes",
            f"[{literature_id}](../../{literature_relative.as_posix()})",
        )
        self.set_label(second_relative.as_posix(), "Status", "refuted")
        self.set_registry_status(second_id, "refuted")

        experiment_id, experiment_relative = research.create_artifact(self.root, "experiment", "Blocked setup")
        self.set_label(experiment_relative.as_posix(), "Status", "blocked")
        self.set_registry_status(experiment_id, "blocked")
        codes = diagnostic_codes(research.check_project(self.root))
        self.assertIn("invalid-supersedes-link", codes)
        self.assertIn("terminal-claim-traceability", codes)
        self.assertIn("blocked-experiment-traceability", codes)
        self.assertIn("blocked-experiment-incomplete", codes)
        self.assertTrue(first_id.startswith("CLM-"))

    def test_dedicated_artifact_must_use_stable_canonical_path(self) -> None:
        self.accept_contract()
        ident, relative = research.create_artifact(self.root, "claim", "Misplaced")
        source = self.root / relative
        destination = self.root / "research/misplaced" / f"{ident}.md"
        destination.parent.mkdir()
        source.rename(destination)
        index = self.root / "ARTIFACT_INDEX.md"
        index.write_text(index.read_text().replace(relative.as_posix(), destination.relative_to(self.root).as_posix()))
        self.assertIn("noncanonical-artifact-path", diagnostic_codes(research.check_project(self.root)))

    def test_broken_link_and_large_state_are_diagnosed(self) -> None:
        readme = self.root / "README.md"
        readme.write_text(readme.read_text() + "\n[missing](not-here.md)\n")
        state = self.root / "STATE.md"
        state.write_text(state.read_text() + ("\nextra" * 4000))
        codes = diagnostic_codes(research.check_project(self.root))
        self.assertIn("broken-link", codes)
        self.assertIn("state-too-large", codes)

    def test_duplicate_required_sections_and_top_level_artifact_heading_are_rejected(self) -> None:
        self.accept_contract()
        _, relative = research.create_artifact(self.root, "claim", "Schema integrity")
        path = self.root / relative
        original = path.read_text()
        path.write_text(original + "\n## Evidence\n\nA hidden duplicate.\n")
        self.assertIn("duplicate-artifact-heading", diagnostic_codes(research.check_project(self.root)))
        path.write_text(original + "\n# CLM-9999 — Hidden second record\n")
        self.assertIn("invalid-artifact-h1-count", diagnostic_codes(research.check_project(self.root)))

    def test_duplicate_machine_sections_and_normalized_table_headers_fail_closed(self) -> None:
        index = self.root / "ARTIFACT_INDEX.md"
        original = index.read_text()
        index.write_text(
            original + "\n## Artifact registry\n\n| ID | Kind | Status | Path | Created |\n|---|---|---|---|---|\n"
        )
        self.assertIn("invalid-index", diagnostic_codes(research.check_project(self.root)))
        index.write_text(original.replace(
            "| Prefix | Meaning | Last allocated |",
            "| Prefix | Prefix | Last allocated |",
            1,
        ))
        self.assertIn("invalid-index", diagnostic_codes(research.check_project(self.root)))

        index.write_text(original)
        provenance = self.root / "results_overview/PROVENANCE.md"
        provenance.write_text(
            provenance.read_text()
            + "\n## Stale items requiring revision\n\n| LaTeX label | Reason stale | Former source | Required action |\n|---|---|---|---|\n"
        )
        self.assertIn(
            "invalid-provenance-section-count",
            diagnostic_codes(research.check_project(self.root)),
        )

    def test_manuscript_input_cannot_escape_its_tree(self) -> None:
        main = self.root / "results_overview/main.tex"
        main.write_text(main.read_text() + "\n\\input{../../outside-secret}\n")
        self.assertIn("manuscript-input-escape", diagnostic_codes(research.check_project(self.root)))
        main.write_text(main.read_text() + "\n\\input ../../unbraced-secret.tex\n")
        self.assertIn("manuscript-input-escape", diagnostic_codes(research.check_project(self.root)))

    def test_installed_human_template_requires_main_entry_point(self) -> None:
        sample = self.root / "curated_manuscript/conference-template.tex"
        sample.write_text("\\documentclass{article}\n\\begin{document}Template\\end{document}\n")
        self.assertIn(
            "human-manuscript-main-missing",
            diagnostic_codes(research.check_project(self.root)),
        )

    def test_unused_venue_sample_tex_is_not_treated_as_manuscript_content(self) -> None:
        main = self.root / "curated_manuscript/main.tex"
        main.write_text("\\documentclass{article}\n\\begin{document}Paper\\end{document}\n")
        sample = self.root / "curated_manuscript/sample-from-venue.tex"
        sample.write_text(
            "\\begin{theorem}Example only.\\label{thm:venue-sample}\\end{theorem}\n"
        )
        codes = diagnostic_codes(research.check_project(self.root))
        self.assertNotIn("unprovenanced-manuscript-item", codes)
        self.assertNotIn("thm:venue-sample", research._tex_labels(self.root, "curated_manuscript"))

    def test_human_manuscript_is_self_contained_and_citations_resolve(self) -> None:
        main = self.root / "curated_manuscript/main.tex"
        main.write_text(
            "\\documentclass{article}\n"
            "\\begin{document}\\cite{missing-key}\\end{document}\n"
            "\\bibliography{../literature/references}\n"
        )
        codes = diagnostic_codes(research.check_project(self.root))
        self.assertIn("human-bibliography-escape", codes)
        self.assertIn("human-citation-key-missing", codes)

        main.write_text(
            "\\documentclass{article}\n"
            "\\begin{document}\\cite{local-key}\\end{document}\n"
            "\\bibliography{references}\n"
        )
        bibliography = self.root / "curated_manuscript/references.bib"
        bibliography.write_text("@article{local-key, title={Local source}}\n")
        codes = diagnostic_codes(research.check_project(self.root))
        self.assertNotIn("human-bibliography-escape", codes)
        self.assertNotIn("human-bibliography-missing", codes)
        self.assertNotIn("human-citation-key-missing", codes)

    def test_unrelated_tex_commands_are_not_misparsed_as_input(self) -> None:
        main = self.root / "results_overview/main.tex"
        main.write_text(
            main.read_text()
            + "\n\\includegraphics{../../outside-figure.png}\n"
            + "\\inputencoding{utf8}\n"
        )
        codes = diagnostic_codes(research.check_project(self.root))
        self.assertNotIn("manuscript-input-escape", codes)
        self.assertNotIn("manuscript-input-missing", codes)

    def test_commented_tex_claims_and_inputs_are_ignored_but_escaped_percent_is_content(self) -> None:
        main = self.root / "results_overview/main.tex"
        main.write_text(main.read_text() + "\n% \\input{../../commented-outside}\n")
        results = self.root / "results_overview/sections/results.tex"
        results.write_text(
            "% \\begin{theorem}\n"
            "% \\label{thm:commented}\n"
            "% Commented theorem.\n"
            "% \\end{theorem}\n"
        )
        report = research.check_project(self.root)
        codes = diagnostic_codes(report)
        self.assertNotIn("manuscript-input-escape", codes)
        self.assertNotIn("unprovenanced-manuscript-item", codes)
        self.assertNotIn("thm:commented", research._tex_labels(self.root))

        results.write_text(
            results.read_text()
            + r"\% active content \begin{theorem}\label{thm:escaped-percent}Live.\end{theorem}"
            + "\n"
        )
        self.assertIn(
            "unprovenanced-manuscript-item",
            diagnostic_codes(research.check_project(self.root)),
        )

    def test_durable_and_review_revisions_must_be_positive(self) -> None:
        self.accept_contract()
        claim_id, claim_relative = self.make_review_ready_claim("Revision canary")
        self.set_label(claim_relative.as_posix(), "Contract revision", "0")
        self.set_label(claim_relative.as_posix(), "Claim revision", "0")
        codes = diagnostic_codes(research.check_project(self.root))
        self.assertIn("invalid-artifact-revision", codes)
        self.assertIn("invalid-claim-revision", codes)

        self.set_label(claim_relative.as_posix(), "Contract revision", "1")
        self.set_label(claim_relative.as_posix(), "Claim revision", "1")
        _, review_relative = research.create_artifact(
            self.root, "review", "Invalid revision binding", claim_id=claim_id,
        )
        self.set_label(review_relative.as_posix(), "Target claim revision", "0")
        self.set_label(review_relative.as_posix(), "Target evidence revision", "0")
        codes = diagnostic_codes(research.check_project(self.root))
        self.assertIn("invalid-review-target-revision", codes)
        self.assertIn("invalid-review-target-evidence-revision", codes)

    def test_state_run_links_require_matching_canonical_label_and_destination(self) -> None:
        self.accept_contract()
        run_id, _ = research.create_artifact(self.root, "run", "Link fidelity")
        state = self.root / "STATE.md"
        state.write_text(state.read_text().replace(
            f"[{run_id}](runs/{run_id}/RUN.md)",
            f"[{run_id}](PROJECT.md)",
            1,
        ))
        codes = diagnostic_codes(research.check_project(self.root))
        self.assertIn("active-run-link-invalid", codes)
        self.assertIn("canonical-link-target-mismatch", codes)

    def test_task_parent_run_link_must_be_canonical(self) -> None:
        self.accept_contract()
        run_id, run_relative = research.create_artifact(self.root, "run", "Task parent")
        task_dir = (self.root / run_relative).parent / "tasks/T01"
        task_dir.mkdir()
        for filename in ("TASK.md", "OUTPUT.md", "RECEIPT.md"):
            source = (self.root / "templates" / filename.lower()).read_text()
            source = source.replace("RUN-####-T##", f"{run_id}-T01").replace("RUN-####", run_id)
            (task_dir / filename).write_text(source)
        task = task_dir / "TASK.md"
        task.write_text(re.sub(
            rf"(?m)^- \*\*Parent run:\*\*.*$",
            f"- **Parent run:** [{run_id}](../../../../STATE.md)",
            task.read_text(), count=1,
        ))
        self.assertIn("task-parent-mismatch", diagnostic_codes(research.check_project(self.root)))

    def test_active_task_requires_concrete_packet_and_canonical_inputs(self) -> None:
        self.accept_contract()
        run_id, run_relative = research.create_artifact(self.root, "run", "Incomplete task")
        task_dir = (self.root / run_relative).parent / "tasks/T01"
        task_dir.mkdir()
        for filename in ("TASK.md", "OUTPUT.md", "RECEIPT.md"):
            source = (self.root / "templates" / filename.lower()).read_text()
            source = source.replace("RUN-####-T##", f"{run_id}-T01").replace("RUN-####", run_id)
            if filename == "TASK.md":
                source = source.replace("- **Status:** planned", "- **Status:** active")
                source = source.replace("- **Contract revision:** pending", "- **Contract revision:** 1")
                source = source.replace("- **Base state revision:** pending", "- **Base state revision:** 1")
            (task_dir / filename).write_text(source)
        codes = diagnostic_codes(research.check_project(self.root))
        self.assertIn("active-task-incomplete", codes)
        self.assertIn("task-input-links-invalid", codes)


class EpistemicGateTests(ProjectFixture):
    def test_validated_claim_needs_completed_fresh_substantive_review(self) -> None:
        claim_id, claim_path, review_id, review_path = self.make_validated_claim()
        report = research.check_project(self.root)
        self.assertEqual([], report.errors, [item.render(self.root) for item in report.errors])
        self.assertNotIn("validated-without-review", diagnostic_codes(report), [item.render(self.root) for item in report.errors])
        claim_file = self.root / claim_path
        original_claim = claim_file.read_text()
        claim_file.write_text(original_claim.replace(
            f"[{review_id}](../reviews/{review_id}.md)",
            f"[{review_id}](../reviews/REV-9999.md)",
            1,
        ))
        self.assertIn("validated-claim-review-index-incomplete", diagnostic_codes(research.check_project(self.root)))
        claim_file.write_text(original_claim)
        self.set_label(review_path.as_posix(), "Fresh context", "no")
        codes = diagnostic_codes(research.check_project(self.root))
        self.assertIn("nonfresh-passing-review", codes)
        self.assertIn("validated-without-review", codes)
        self.assertTrue(claim_id.startswith("CLM-") and review_id.startswith("REV-"))

    def test_review_target_label_and_destination_must_name_the_same_claim(self) -> None:
        self.accept_contract()
        first_id, _ = self.make_review_ready_claim("First target")
        second_id, _ = self.make_review_ready_claim("Second target")
        _, review_relative = research.create_artifact(
            self.root, "review", "Ambiguous target", claim_id=first_id,
        )
        review = self.root / review_relative
        review.write_text(review.read_text().replace(
            f"[{first_id}](../claims/{first_id}.md)",
            f"[{first_id}](../claims/{second_id}.md)",
            1,
        ))
        codes = diagnostic_codes(research.check_project(self.root))
        self.assertIn("review-target-missing", codes)
        self.assertIn("canonical-link-target-mismatch", codes)

    def test_validated_claim_run_traceability_binds_label_to_destination(self) -> None:
        _, claim_relative, _, _ = self.make_validated_claim()
        claim = self.root / claim_relative
        claim.write_text(re.sub(
            r"(?m)^- \*\*Created in:\*\*.*$",
            "- **Created in:** [RUN-0001](../../STATE.md)",
            claim.read_text(), count=1,
        ))
        self.assertIn(
            "validated-claim-traceability",
            diagnostic_codes(research.check_project(self.root)),
        )

    def test_reviewed_claim_finalizes_dependencies_limitations_and_evidence_meaning(self) -> None:
        _, claim_relative, _, _ = self.make_validated_claim()
        claim = self.root / claim_relative
        text = claim.read_text()
        text = re.sub(
            r"(?ms)^## Dependencies\s*\n.*?(?=^## |\Z)",
            "## Dependencies\n\n[Link dependencies or write none.]\n\n", text, count=1,
        )
        text = re.sub(
            r"(?ms)^## Known limitations and open issues\s*\n.*?(?=^## |\Z)",
            "## Known limitations and open issues\n\n[List limitations or write none.]\n\n", text, count=1,
        )
        text = re.sub(
            r"(?m)^- \*\*What the evidence establishes:\*\*.*$",
            "- **What the evidence establishes:** pending", text, count=1,
        )
        text = re.sub(
            r"(?ms)^## Proof or derivation\s*\n.*?(?=^## |\Z)",
            "## Proof or derivation\n\n[Give the inferential chain.]\n\n", text, count=1,
        )
        claim.write_text(text)
        self.assertIn("mature-claim-incomplete", diagnostic_codes(research.check_project(self.root)))

    def test_completed_task_output_and_receipt_keep_exact_task_links_and_negative_handoff(self) -> None:
        self.make_validated_claim()
        output = next(self.root.glob("runs/RUN-*/tasks/T01/OUTPUT.md"))
        receipt = output.with_name("RECEIPT.md")
        output.write_text(output.read_text().replace(
            "[RUN-0001-T01](TASK.md)", "[wrong task](TASK.md)", 1,
        ))
        receipt.write_text(receipt.read_text().replace(
            "[RUN-0001-T01](TASK.md)", "[RUN-0001-T01](OUTPUT.md)", 1,
        ))
        codes = diagnostic_codes(research.check_project(self.root))
        self.assertIn("output-task-link-invalid", codes)
        self.assertIn("receipt-task-link-invalid", codes)

        output.write_text(output.read_text().replace(
            "## Counterexamples and disproofs\n\nNone.",
            "## Counterexamples and disproofs\n\n[Record a counterexample or write none.]",
            1,
        ))
        self.assertIn(
            "completed-output-incomplete",
            diagnostic_codes(research.check_project(self.root)),
        )

    def test_historical_review_is_retained_without_covering_new_revision(self) -> None:
        claim_id, claim_path, _, _ = self.make_validated_claim()
        path = self.root / claim_path
        text = path.read_text()
        text = text.replace("- **Claim revision:** 1", "- **Claim revision:** 2")
        text = text.replace("- **Status:** validated", "- **Status:** candidate")
        text = text.replace("For every finite instance, the value is nonnegative.", "For every nonempty finite instance, the value is nonnegative.")
        digest = research.claim_digest(text)
        text = re.sub(r"(?m)^- \*\*Statement digest:\*\*.*$", f"- **Statement digest:** {digest}", text)
        path.write_text(text)
        self.set_registry_status(claim_id, "candidate")
        codes = diagnostic_codes(research.check_project(self.root))
        self.assertNotIn("stale-review-digest", codes)
        self.assertNotIn("future-review-revision", codes)

    def test_evidence_or_proof_rewrite_invalidates_passing_review(self) -> None:
        claim_id, claim_path, _, _ = self.make_validated_claim()
        path = self.root / claim_path
        path.write_text(path.read_text().replace(
            "Nonnegativity follows directly from the finite-model definition.",
            "This proof text was rewritten after review.",
            1,
        ))
        codes = diagnostic_codes(research.check_project(self.root))
        self.assertIn("stale-claim-evidence-digest", codes)
        self.assertIn("stale-review-evidence-digest", codes)
        self.assertIn("validated-without-review", codes)
        self.assertTrue(claim_id.startswith("CLM-"))

    def test_epistemic_relabeling_invalidates_review_coverage(self) -> None:
        _, claim_path, _, _ = self.make_validated_claim()
        path = self.root / claim_path
        text = path.read_text()
        text = text.replace("- **Claim kind:** theorem", "- **Claim kind:** empirical observation", 1)
        text = text.replace(
            "- **Evidence class:** mathematical proof",
            "- **Evidence class:** empirical observation",
            1,
        )
        path.write_text(text)
        codes = diagnostic_codes(research.check_project(self.root))
        self.assertIn("stale-claim-evidence-digest", codes)
        self.assertIn("validated-without-review", codes)

    def test_mathematical_claim_requires_affirmative_mathematical_evidence(self) -> None:
        _, claim_path, _, _ = self.make_validated_claim()
        for evidence_class in ("sampled finite cases", "numerical tests", "brute-force enumeration"):
            with self.subTest(evidence_class=evidence_class):
                self.set_label(claim_path.as_posix(), "Evidence class", evidence_class)
                self.assertIn(
                    "empirical-proof-promotion",
                    diagnostic_codes(research.check_project(self.root)),
                )

    def test_review_contract_must_match_target_claim_contract(self) -> None:
        _, claim_path, _, _ = self.make_validated_claim()
        self.set_label(claim_path.as_posix(), "Contract revision", "2")
        codes = diagnostic_codes(research.check_project(self.root))
        self.assertIn("review-claim-contract-mismatch", codes)
        self.assertIn("validated-without-review", codes)

    def test_historical_review_survives_current_model_alias_change(self) -> None:
        self.make_validated_claim()
        profiles = self.root / "runtime/PROFILES.md"
        lines = profiles.read_text().splitlines()
        for index, line in enumerate(lines):
            if line.startswith("| `substantive` |"):
                model = research._expected_runtime_mapping(self.root, "codex", "substantive")[0]
                lines[index] = line.replace(f"`{model}`", "`gpt-future`", 1)
                break
        else:
            self.fail("missing substantive profile row")
        profiles.write_text("\n".join(lines) + "\n")
        report = research.check_project(self.root)
        codes = diagnostic_codes(report)
        self.assertNotIn("validated-without-review", codes)
        self.assertNotIn("completed-review-receipt-missing", codes)
        self.assertNotIn("silent-profile-downgrade", codes)
        self.assertIn("historical-profile-mapping", codes)

    def test_forged_historical_mapping_cannot_validate_a_review(self) -> None:
        self.make_validated_claim()
        receipt = next(self.root.glob("runs/RUN-*/tasks/T01/RECEIPT.md"))
        receipt.write_text(
            receipt.read_text()
            .replace(research._expected_runtime_mapping(self.root, "codex", "substantive")[0], "gpt-fake-low", 1)
            .replace("- **Resolved effort:** high", "- **Resolved effort:** low", 1)
        )
        codes = diagnostic_codes(research.check_project(self.root))
        self.assertIn("silent-profile-downgrade", codes)
        self.assertIn("validated-without-review", codes)

    def test_review_task_contract_must_match_review_and_project_packet(self) -> None:
        self.make_validated_claim()
        task = next(self.root.glob("runs/RUN-*/tasks/T01/TASK.md"))
        task.write_text(task.read_text().replace(
            "- **Contract revision:** 1", "- **Contract revision:** 0", 1,
        ).replace(
            "[PROJECT.md](../../../../PROJECT.md), contract revision: 1.",
            "contract revision: 0.",
            1,
        ))
        codes = diagnostic_codes(research.check_project(self.root))
        self.assertIn("completed-review-receipt-missing", codes)
        self.assertIn("validated-without-review", codes)

    def test_review_packet_requires_canonical_project_claim_and_material_links(self) -> None:
        claim_id, claim_relative, _, review_relative = self.make_validated_claim()
        task = next(self.root.glob("runs/RUN-*/tasks/T01/TASK.md"))
        original_task = task.read_text()
        task.write_text(re.sub(
            rf"\[{re.escape(claim_id)}\]\([^)]*{re.escape(claim_relative.as_posix())}\)",
            claim_id,
            original_task,
        ))
        self.assertIn("validated-without-review", diagnostic_codes(research.check_project(self.root)))
        task.write_text(original_task)

        review = self.root / review_relative
        review_text = review.read_text()
        materials_start = review_text.index("## Materials supplied")
        review.write_text(
            review_text[:materials_start]
            + review_text[materials_start:].replace(
                f"[{claim_id}](../claims/{claim_id}.md)", claim_id, 1,
            )
        )
        codes = diagnostic_codes(research.check_project(self.root))
        self.assertIn("completed-review-materials-invalid", codes)
        self.assertIn("validated-without-review", codes)

    def test_validated_claim_cannot_depend_on_draft_claim(self) -> None:
        claim_id, claim_relative, review_id, review_relative = self.make_validated_claim()
        dependency_id, dependency_relative = research.create_artifact(
            self.root, "claim", "Unvalidated dependency",
        )
        claim = self.root / claim_relative
        claim.write_text(re.sub(
            r"(?ms)^## Dependencies\s*\n.*?(?=^## |\Z)",
            f"## Dependencies\n\n- [{dependency_id}]({dependency_id}.md)\n\n",
            claim.read_text(), count=1,
        ))
        new_digest = research.evidence_digest(claim.read_text())
        self.set_label(claim_relative.as_posix(), "Evidence digest", new_digest)
        self.set_label(review_relative.as_posix(), "Target evidence digest", new_digest)
        task = next(self.root.glob("runs/RUN-*/tasks/T01/TASK.md"))
        task_text = task.read_text()
        task_text = re.sub(
            r"evidence digest:\s*sha256:[0-9a-f]{64}",
            f"evidence digest: {new_digest}", task_text, count=1,
        )
        task.write_text(task_text)
        codes = diagnostic_codes(research.check_project(self.root))
        self.assertIn("unvalidated-claim-dependency", codes)
        self.assertNotIn("validated-without-review", codes)
        self.assertTrue((self.root / dependency_relative).exists())
        self.assertTrue(review_id.startswith("REV-") and claim_id.startswith("CLM-"))

    def test_bare_claim_dependency_cannot_evade_dependency_validation(self) -> None:
        _, claim_relative, _, _ = self.make_validated_claim()
        claim = self.root / claim_relative
        claim.write_text(re.sub(
            r"(?ms)^## Dependencies\s*\n.*?(?=^## |\Z)",
            "## Dependencies\n\nCLM-9999\n\n",
            claim.read_text(), count=1,
        ))
        self.assertIn(
            "noncanonical-claim-dependency",
            diagnostic_codes(research.check_project(self.root)),
        )

    def test_validated_claim_cannot_depend_on_itself(self) -> None:
        claim_id, claim_relative, _, review_relative = self.make_validated_claim()
        claim = self.root / claim_relative
        claim.write_text(re.sub(
            r"(?ms)^## Dependencies\s*\n.*?(?=^## |\Z)",
            f"## Dependencies\n\n- [{claim_id}]({claim_id}.md)\n\n",
            claim.read_text(), count=1,
        ))
        new_digest = research.evidence_digest(claim.read_text())
        self.set_label(claim_relative.as_posix(), "Evidence digest", new_digest)
        self.set_label(review_relative.as_posix(), "Target evidence digest", new_digest)
        task = next(self.root.glob("runs/RUN-*/tasks/T01/TASK.md"))
        task.write_text(re.sub(
            r"evidence digest:\s*sha256:[0-9a-f]{64}",
            f"evidence digest: {new_digest}", task.read_text(), count=1,
        ))
        codes = diagnostic_codes(research.check_project(self.root))
        self.assertIn("claim-self-dependency", codes)
        self.assertNotIn("validated-without-review", codes)

    def test_completed_nonpass_review_still_requires_and_accepts_bound_fresh_receipt(self) -> None:
        claim_id, claim_path, _, review_path = self.make_validated_claim()
        self.set_label(claim_path.as_posix(), "Status", "candidate")
        self.set_registry_status(claim_id, "candidate")
        self.set_label(review_path.as_posix(), "Verdict", "fail")
        self.set_label(review_path.as_posix(), "Evidence or proof correct", "no")
        self.set_label(review_path.as_posix(), "Establishes exact recorded statement", "no")
        output = next(self.root.glob("runs/RUN-*/tasks/T01/OUTPUT.md"))
        text = re.sub(r"(?m)^- \*\*Outcome classification:\*\*.*$", "- **Outcome classification:** refuted", output.read_text(), count=1)
        output.write_text(text)
        report = research.check_project(self.root)
        codes = diagnostic_codes(report)
        self.assertNotIn("completed-review-receipt-missing", codes, [item.render(self.root) for item in report.errors])
        self.assertNotIn("completed-review-assessment-incomplete", codes, [item.render(self.root) for item in report.errors])
        receipt = next(self.root.glob("runs/RUN-*/tasks/T01/RECEIPT.md"))
        receipt.write_text(receipt.read_text().replace("- **Fresh context:** yes", "- **Fresh context:** no", 1))
        self.assertIn("completed-review-receipt-missing", diagnostic_codes(research.check_project(self.root)))
        self.set_label(review_path.as_posix(), "Fresh context", "no")
        self.assertIn("nonfresh-completed-review", diagnostic_codes(research.check_project(self.root)))

    def test_passing_review_requires_substantive_skeptical_work_and_output_evidence(self) -> None:
        self.make_validated_claim()
        review = next(self.root.glob("research/reviews/REV-*.md"))
        text = review.read_text()
        for heading in (
            "Independence statement", "Verification approach",
            "Falsification and counterexample attempts", "Verdict rationale",
        ):
            text = re.sub(
                rf"(?ms)^## {re.escape(heading)}\s*\n.*?(?=^## |\Z)",
                f"## {heading}\n\nNone.\n\n", text, count=1,
            )
        text = re.sub(r"(?m)^- \*\*Correctness rationale:\*\*.*$", "- **Correctness rationale:** None.", text)
        text = re.sub(r"(?m)^- \*\*Fidelity rationale:\*\*.*$", "- **Fidelity rationale:** None.", text)
        text = re.sub(r"(?m)^- \*\*Findings:\*\*.*$", "- **Findings:** None.", text)
        review.write_text(text)
        codes = diagnostic_codes(research.check_project(self.root))
        self.assertIn("completed-review-assessment-incomplete", codes)
        self.assertIn("validated-without-review", codes)

        output = next(self.root.glob("runs/RUN-*/tasks/T01/OUTPUT.md"))
        output.write_text(re.sub(
            r"(?ms)^## Evidence or derivation\s*\n.*?(?=^## |\Z)",
            "## Evidence or derivation\n\nNone.\n\n", output.read_text(), count=1,
        ))
        self.assertIn("completed-review-receipt-missing", diagnostic_codes(research.check_project(self.root)))

    def test_paper_requires_current_passing_review_and_provenance(self) -> None:
        claim_id, claim_path, review_id, review_path = self.make_validated_claim()
        results = self.root / "results_overview/sections/results.tex"
        results.write_text("\\begin{theorem}\\label{thm:main} Result.\\end{theorem}\n")
        claim_file = self.root / claim_path
        claim_text = re.sub(
            r"(?ms)^## Manuscript locations\s*\n.*?(?=^## |\Z)",
            "## Manuscript locations\n\n- `thm:main` in [results.tex](../../results_overview/sections/results.tex).\n\n",
            claim_file.read_text(), count=1,
        )
        claim_file.write_text(claim_text)
        provenance = self.root / "results_overview/PROVENANCE.md"
        text = provenance.read_text()
        row = (
            f"| `thm:main` | theorem | [{claim_id}](../{claim_path.as_posix()}) | "
            f"[claim evidence](../{claim_path.as_posix()}) | "
            f"[{review_id}](../{review_path.as_posix()}) | established |"
        )
        marker = "|---|---|---|---|---|---|"
        text = text.replace(marker, marker + "\n" + row, 1)
        provenance.write_text(text)
        report = research.check_project(self.root)
        self.assertNotIn("provenance-review-not-passing", diagnostic_codes(report), [item.render(self.root) for item in report.errors])
        other_claim_id, other_claim_path = research.create_artifact(
            self.root, "claim", "Unrelated draft claim",
        )
        claim_cell = f"[{claim_id}](../{claim_path.as_posix()})"
        extra_claim_cell = (
            claim_cell
            + f"; [{other_claim_id}](../{other_claim_path.as_posix()})"
        )
        provenance.write_text(text.replace(claim_cell, extra_claim_cell, 1))
        self.assertIn(
            "stale-provenance",
            diagnostic_codes(research.check_project(self.root)),
        )
        provenance.write_text(text)
        provenance.write_text(text.replace("| established |", "| current |", 1))
        self.assertIn(
            "invalid-established-provenance-status",
            diagnostic_codes(research.check_project(self.root)),
        )
        provenance.write_text(text)
        provenance.write_text(text.replace(row, row + "\n" + row, 1))
        self.assertIn("duplicate-provenance-label", diagnostic_codes(research.check_project(self.root)))
        provenance.write_text(text)
        changed_evidence = claim_file.read_text().replace(
            "Nonnegativity follows directly from the finite-model definition.",
            "Post-review proof rewrite.",
            1,
        )
        claim_file.write_text(changed_evidence)
        self.assertIn("provenance-review-not-passing", diagnostic_codes(research.check_project(self.root)))
        claim_file.write_text(claim_text)
        missing_reverse = re.sub(
            r"(?ms)^## Manuscript locations\s*\n.*?(?=^## |\Z)",
            "## Manuscript locations\n\nNone.\n\n", claim_file.read_text(), count=1,
        )
        claim_file.write_text(missing_reverse)
        self.assertIn("provenance-reverse-location-missing", diagnostic_codes(research.check_project(self.root)))
        claim_file.write_text(claim_text)
        self.set_label(claim_path.as_posix(), "Evidence class", "empirical observation")
        self.assertIn(
            "manuscript-mathematical-role-invalid",
            diagnostic_codes(research.check_project(self.root)),
        )
        self.set_label(claim_path.as_posix(), "Evidence class", "mathematical proof")
        self.set_label(review_path.as_posix(), "Verdict", "fail")
        self.assertIn("provenance-review-not-passing", diagnostic_codes(research.check_project(self.root)))

    def test_grouped_result_requires_current_review_for_every_claim(self) -> None:
        first = self.make_validated_claim()
        run_id = next(self.root.glob("runs/RUN-*/RUN.md")).parent.name
        second = self.make_validated_claim(run_id=run_id)
        for manuscript in research.MANUSCRIPT_ROOTS:
            with self.subTest(manuscript=manuscript):
                main = self.root / manuscript / "main.tex"
                main.write_text("\\begin{theorem}\\label{thm:grouped}Together.\\end{theorem}\n")
                for claim_id, claim_path, _, _ in (first, second):
                    path = self.root / claim_path
                    text = path.read_text().replace(
                        "## Manuscript locations\n",
                        f"## Manuscript locations\n\n- [thm:grouped](../../{manuscript}/PROVENANCE.md)\n",
                    )
                    path.write_text(text)
                claims = "; ".join(f"[{c}](../{p})" for c, p, _, _ in (first, second))
                reviews = "; ".join(f"[{r}](../{p})" for _, _, r, p in (first, second))
                provenance = self.root / manuscript / "PROVENANCE.md"
                row = f"| thm:grouped | theorem | {claims} | {claims} | {reviews} | established |"
                original = provenance.read_text()
                populated = original.replace("|---|---|---|---|---|---|", "|---|---|---|---|---|---|\n" + row, 1)
                provenance.write_text(populated)
                report = research.check_project(self.root)
                self.assertEqual([], report.errors, [d.render(self.root) for d in report.errors])
                # One good review must not cover the other source claim.
                provenance.write_text(populated.replace(f"[{second[2]}](../{second[3]})", "", 1))
                self.assertIn("provenance-review-not-passing", diagnostic_codes(research.check_project(self.root)))
                provenance.write_text(populated)
                self.set_label(second[1].as_posix(), "Status", "superseded")
                self.assertIn("stale-provenance", diagnostic_codes(research.check_project(self.root)))
                self.set_label(second[1].as_posix(), "Status", "validated")

    def test_imported_literature_needs_precise_current_source_not_project_claim(self) -> None:
        self.accept_contract()
        note_id, relative = research.create_artifact(self.root, "literature", "Synthetic source")
        note = self.root / relative
        self.set_label(relative.as_posix(), "Status", "completed")
        # Test this boundary alone; a complete LIT schema is checked independently.
        canonical = {note_id: note}
        for manuscript in research.MANUSCRIPT_ROOTS:
            (self.root / manuscript / "main.tex").write_text(
                "\\begin{theorem}\\label{thm:imported}Imported result.\\end{theorem}\n"
            )
            provenance = self.root / manuscript / "PROVENANCE.md"
            original = provenance.read_text()
            row = (f"| thm:imported | theorem | [{note_id}](../{relative}) | "
                   "Theorem 2, page 4 | Same finite model; rename x to y only. | imported |")
            populated = original
            position = populated.index("## Open or explicitly provisional items")
            populated = populated[:position].rstrip() + "\n" + row + "\n\n" + populated[position:]
            provenance.write_text(populated)
            def check():
                report = research.CheckReport()
                research._check_provenance(self.root, report, canonical, manuscript)
                return report
            self.assertEqual([], check().errors)
            provenance.write_text(populated.replace("Theorem 2, page 4", "pending"))
            self.assertIn("imported-literature-detail-missing", diagnostic_codes(check()))
            provenance.write_text(populated)
            self.set_label(relative.as_posix(), "Status", "superseded")
            self.assertIn("stale-provenance", diagnostic_codes(check()))
            self.set_label(relative.as_posix(), "Status", "completed")
            provenance.write_text(populated.replace(f"[{note_id}](../{relative})", f"[{note_id}](../PROJECT.md)"))
            self.assertIn("imported-literature-source-invalid", diagnostic_codes(check()))

    def test_curated_setup_is_optional_and_bibliography_name_is_venue_defined(self) -> None:
        report = research.check_project(self.root)
        self.assertEqual([], report.errors)
        self.assertFalse((self.root / "curated_manuscript/main.tex").exists())
        main = self.root / "curated_manuscript/main.tex"
        main.write_text("\\documentclass{article}\\begin{document}Text.\\end{document}\n")
        self.assertEqual([], research.check_project(self.root).errors)
        main.write_text(main.read_text() + "\\bibliography{venue-refs}\n")
        self.assertIn("human-bibliography-missing", diagnostic_codes(research.check_project(self.root)))
        (main.parent / "venue-refs.bib").write_text("@article{key, title={Synthetic}}\n")
        self.assertEqual([], research.check_project(self.root).errors)

    def test_conjecture_requires_labeled_open_provenance_and_limitation(self) -> None:
        self.accept_contract()
        claim_id, claim_relative = research.create_artifact(self.root, "claim", "Open conjecture source")
        results = self.root / "results_overview/sections/results.tex"
        results.write_text(
            "\\begin{conjecture}\\label{conj:boundary} Boundary claim.\\end{conjecture}\n"
        )
        provenance = self.root / "results_overview/PROVENANCE.md"
        marker = "|---|---|---|---|---|"
        row = (
            f"| `conj:boundary` | conjecture | [{claim_id}](../{claim_relative.as_posix()}) | "
            "No proof is known beyond finite instances of size three. | open |"
        )
        provenance_text = provenance.read_text()
        open_section = provenance_text.index("## Open or explicitly provisional items")
        marker_index = provenance_text.index(marker, open_section)
        provenance.write_text(
            provenance_text[:marker_index]
            + marker + "\n" + row
            + provenance_text[marker_index + len(marker):]
        )
        codes = diagnostic_codes(research.check_project(self.root))
        self.assertNotIn("unprovenanced-provisional-item", codes)
        provenance.write_text(provenance.read_text().replace(
            "No proof is known beyond finite instances of size three.", "pending", 1,
        ))
        self.assertIn("provisional-limitation-missing", diagnostic_codes(research.check_project(self.root)))

        results.write_text("\\begin{conjecture}Unlabeled.\\end{conjecture}\n")
        self.assertIn("unlabeled-manuscript-item", diagnostic_codes(research.check_project(self.root)))

    def test_unprovenanced_theorem_is_rejected(self) -> None:
        results = self.root / "results_overview/sections/results.tex"
        results.write_text(
            "\\begin{theorem}\\label{thm:orphan} Result.\\end{theorem}\n"
            "\\begin{lemma}\\label{thm:orphan} Duplicate.\\end{lemma}\n"
        )
        codes = diagnostic_codes(research.check_project(self.root))
        self.assertIn("unprovenanced-manuscript-item", codes)
        self.assertIn("duplicate-latex-label", codes)

    def test_incomplete_task_packet_and_profile_downgrade_are_rejected(self) -> None:
        self.accept_contract()
        run_id, run_path = research.create_artifact(self.root, "run", "Delegation")
        task_dir = (self.root / run_path).parent / "tasks/T01"
        task_dir.mkdir()
        for name in ("TASK.md", "OUTPUT.md", "RECEIPT.md"):
            source = (self.root / "templates" / name.lower()).read_text()
            source = source.replace("RUN-####-T##", f"{run_id}-T01").replace("RUN-####", run_id)
            source = source.replace("- **Requested profile:** substantive", "- **Requested profile:** deep")
            if name == "RECEIPT.md":
                source = source.replace("- **Status:** not started", "- **Status:** completed")
                source = source.replace("- **Resolved provider:** pending", "- **Resolved provider:** codex")
                source = source.replace("- **Resolved model:** pending", "- **Resolved model:** model")
                source = source.replace("- **Resolved effort:** pending", "- **Resolved effort:** medium")
                source = source.replace("- **Runtime mode:** pending", "- **Runtime mode:** focused")
                source = source.replace("- **Adapter version:** pending", f"- **Adapter version:** {research.ADAPTER_SCHEMA}")
            (task_dir / name).write_text(source)
        codes = diagnostic_codes(research.check_project(self.root))
        self.assertIn("silent-profile-downgrade", codes)
        self.assertNotIn("duplicate-id", codes)
        receipt = task_dir / "RECEIPT.md"
        receipt.write_text(receipt.read_text().replace(
            "- **Substitution:** none",
            "- **Substitution:** substantive fallback explicitly substituted",
            1,
        ))
        output = task_dir / "OUTPUT.md"
        output_text = output.read_text().replace(
            "- **Outcome classification:** pending",
            "- **Outcome classification:** requiring verification",
            1,
        )
        output_text = re.sub(
            r"(?ms)^## Uncertainties and verification needs\s*\n.*?(?=^## |\Z)",
            "## Uncertainties and verification needs\n\nPending deep verification remains required.\n\n",
            output_text, count=1,
        )
        output_text = re.sub(
            r"(?ms)^## Recommended next action\s*\n.*?(?=^## |\Z)",
            "## Recommended next action\n\nRerun with the configured deep profile.\n\n",
            output_text, count=1,
        )
        output.write_text(output_text)
        report = research.check_project(self.root)
        substitutions = [item for item in report.diagnostics if item.code == "runtime-profile-substitution"]
        self.assertTrue(substitutions)
        self.assertTrue(all(item.severity == "warning" for item in substitutions))
        self.assertNotIn("profile-debt-not-visible", diagnostic_codes(report))


class AdapterTests(ProjectFixture):
    def test_mapping_history_is_complete_unique_and_matches_current_schema(self) -> None:
        profiles = self.root / "runtime/PROFILES.md"
        original = profiles.read_text()
        row = next(line for line in original.splitlines() if line.startswith(
            "| `research-agent-adapter-v1` | `codex` | `substantive` |"
        ))
        profiles.write_text(original.replace(row, row + "\n" + row, 1))
        self.assertIn(
            "mapping-history-duplicate",
            diagnostic_codes(research.check_adapters(self.root, "codex")),
        )

        profiles.write_text(original.replace(row + "\n", "", 1))
        self.assertIn(
            "mapping-history-incomplete",
            diagnostic_codes(research.check_adapters(self.root, "codex")),
        )

        contract_row = next(line for line in original.splitlines() if line.startswith("| `substantive` |"))
        model = research._expected_runtime_mapping(self.root, "codex", "substantive")[0]
        drifted_row = contract_row.replace(f"`{model}`", "`gpt-future`", 1)
        profiles.write_text(original.replace(contract_row, drifted_row, 1))
        self.assertIn(
            "mapping-history-current-drift",
            diagnostic_codes(research.check_adapters(self.root, "codex")),
        )
        adapter = self.root / ".codex/agents/substantive.toml"
        before = adapter.read_text()
        self.assertTrue(research.adapters(self.root, "codex", check_only=False).errors)
        self.assertEqual(before, adapter.read_text())

    def test_hook_topology_and_project_permission_escalations_are_closed(self) -> None:
        hooks = self.root / ".codex/hooks.json"
        codex = __import__("json").loads(hooks.read_text())
        codex["hooks"]["PreToolUse"][0]["hooks"].append({
            "type": "command", "command": "echo unchecked", "timeout": 10,
            "commandWindows": "echo unchecked",
        })
        codex["hooks"]["PreToolUse"][0]["hooks"][0]["disabled"] = False
        hooks.write_text(__import__("json").dumps(codex))
        self.assertIn(
            "native-hook-topology-invalid",
            diagnostic_codes(research.check_adapters(self.root, "codex")),
        )

        settings = self.root / ".claude/settings.json"
        claude = __import__("json").loads(settings.read_text())
        claude["permissions"]["allow"] = ["Bash(*)"]
        claude["permissions"]["ask"] = ["Edit(**)"]
        settings.write_text(__import__("json").dumps(claude))
        self.assertIn(
            "claude-permission-escalation",
            diagnostic_codes(research.check_adapters(self.root, "claude")),
        )

    def test_runtime_adapter_inventory_is_recursively_closed(self) -> None:
        additions = (
            ("codex", ".codex/commands/unsafe.md"),
            ("codex", ".codex/rules/extra.rules"),
            ("claude", ".claude/commands/unsafe.md"),
            ("claude", ".claude/rules/extra.md"),
        )
        for runtime, relative in additions:
            with self.subTest(runtime=runtime, relative=relative):
                path = self.root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("unsafe extension\n")
                codes = diagnostic_codes(research.check_adapters(self.root, runtime))
                self.assertTrue(
                    {"unexpected-runtime-adapter-file", "unexpected-runtime-rule"}.intersection(codes),
                    codes,
                )
                path.unlink()
                if not any(path.parent.iterdir()):
                    path.parent.rmdir()

    def test_unexpected_loadable_agent_definitions_are_rejected(self) -> None:
        for runtime, relative in (
            ("codex", ".codex/agents/unsafe.toml"),
            ("claude", ".claude/agents/unsafe.md"),
        ):
            with self.subTest(runtime=runtime):
                path = self.root / relative
                path.write_text("model = 'unreviewed'\n" if runtime == "codex" else "---\nmodel: unreviewed\n---\n")
                self.assertIn(
                    "unexpected-agent-adapter",
                    diagnostic_codes(research.check_adapters(self.root, runtime)),
                )
                path.unlink()

    def test_claude_local_settings_override_is_rejected(self) -> None:
        local = self.root / ".claude/settings.local.json"
        local.write_text('{"permissions": {"defaultMode": "bypassPermissions"}}\n')
        self.assertIn(
            "unexpected-runtime-local-override",
            diagnostic_codes(research.check_project(self.root)),
        )
        self.assertIn(
            "unexpected-runtime-local-override",
            diagnostic_codes(research.check_adapters(self.root, "claude")),
        )

    def test_project_mcp_autoenable_and_local_mcp_config_are_rejected(self) -> None:
        (self.root / ".mcp.json").write_text("{}\n")
        self.assertIn(
            "unexpected-project-mcp-config",
            diagnostic_codes(research.check_project(self.root)),
        )
        settings = self.root / ".claude/settings.json"
        payload = __import__("json").loads(settings.read_text())
        payload["enableAllProjectMcpServers"] = True
        settings.write_text(__import__("json").dumps(payload))
        self.assertIn(
            "claude-project-mcp-autoenable",
            diagnostic_codes(research.check_adapters(self.root, "claude")),
        )

    def test_doctor_warns_when_detected_runtime_differs_from_tested_baseline(self) -> None:
        def fake_which(name):
            return "/fake/codex" if name == "codex" else None

        def fake_run(command, **kwargs):
            if command[0] == "/fake/codex":
                return __import__("subprocess").CompletedProcess(command, 0, stdout="setup noise\ncodex-cli 9.9.9\n", stderr="")
            return __import__("subprocess").CompletedProcess(command, 0, stdout="guard passed\n", stderr="")

        with mock.patch.object(research.shutil, "which", side_effect=fake_which), mock.patch.object(research.subprocess, "run", side_effect=fake_run):
            report = research.doctor(self.root, "codex")
        self.assertIn("runtime-version-baseline-mismatch", diagnostic_codes(report))
        self.assertIn("runtime-live-confirmation-required", diagnostic_codes(report))

    def test_profile_drift_is_detected_and_sync_repairs_only_mapping(self) -> None:
        path = self.root / ".codex/agents/deep.toml"
        original = path.read_text()
        path.write_text(original.replace('model_reasoning_effort = "xhigh"', 'model_reasoning_effort = "medium"'))
        self.assertIn("adapter-profile-drift", diagnostic_codes(research.check_adapters(self.root, "codex")))
        report = research.adapters(self.root, "codex", check_only=False)
        self.assertEqual([], report.errors, [item.render(self.root) for item in report.errors])
        self.assertIn('model_reasoning_effort = "xhigh"', path.read_text())
        self.assertIn("protect_shared.py", path.read_text())

    def test_adapter_sync_preflights_all_files_before_writing(self) -> None:
        first = self.root / ".codex/agents/maintenance.toml"
        model = research._expected_runtime_mapping(self.root, "codex", "maintenance")[0]
        first.write_text(first.read_text().replace(f'model = "{model}"', 'model = "drift"'))
        missing = self.root / ".codex/agents/pivotal.toml"
        missing.unlink()
        before = first.read_text()
        report = research.adapters(self.root, "codex", check_only=False)
        self.assertTrue(report.errors)
        self.assertEqual(before, first.read_text())

    def test_duplicate_semantic_profile_rows_fail_check_and_sync(self) -> None:
        profiles = self.root / "runtime/PROFILES.md"
        text = profiles.read_text()
        row = next(line for line in text.splitlines() if line.startswith("| `maintenance` |"))
        profiles.write_text(text.replace(row, row + "\n" + row, 1))
        self.assertIn("duplicate-profile-mapping", diagnostic_codes(research.check_adapters(self.root, "codex")))
        adapter = self.root / ".codex/agents/maintenance.toml"
        before = adapter.read_text()
        report = research.adapters(self.root, "codex", check_only=False)
        self.assertTrue(report.errors)
        self.assertEqual(before, adapter.read_text())

    def test_native_hook_wiring_is_parsed_not_inferred_from_readmes(self) -> None:
        codex_hooks = self.root / ".codex/hooks.json"
        payload = __import__("json").loads(codex_hooks.read_text())
        payload["hooks"]["PreToolUse"][0]["hooks"] = [
            hook for hook in payload["hooks"]["PreToolUse"][0]["hooks"]
            if "no_git.py" not in hook.get("command", "")
        ]
        codex_hooks.write_text(__import__("json").dumps(payload))
        codex_report = research.check_adapters(self.root, "codex")
        self.assertIn("native-guard-not-wired", diagnostic_codes(codex_report))
        self.assertTrue(any("no_git.py" in item.message for item in codex_report.errors))

        claude_settings = self.root / ".claude/settings.json"
        payload = __import__("json").loads(claude_settings.read_text())
        payload["permissions"]["deny"] = [value for value in payload["permissions"]["deny"] if value != "Read(/.git/**)"]
        claude_settings.write_text(__import__("json").dumps(payload))
        self.assertIn("native-no-git-deny-missing", diagnostic_codes(research.check_adapters(self.root, "claude")))

    def test_claude_read_surface_has_exact_no_git_hook(self) -> None:
        settings = self.root / ".claude/settings.json"
        payload = __import__("json").loads(settings.read_text())
        payload["hooks"]["PreToolUse"] = [
            entry for entry in payload["hooks"]["PreToolUse"]
            if entry.get("matcher") != "Read|Glob|Grep"
        ]
        settings.write_text(__import__("json").dumps(payload))
        self.assertIn(
            "native-read-guard-missing",
            diagnostic_codes(research.check_adapters(self.root, "claude")),
        )

    def test_evidence_runtime_hooks_and_codex_native_safety_cannot_drift(self) -> None:
        hooks = self.root / ".codex/hooks.json"
        payload = __import__("json").loads(hooks.read_text())
        payload["hooks"]["PreToolUse"][0]["hooks"] = [
            hook for hook in payload["hooks"]["PreToolUse"][0]["hooks"]
            if not any(name in hook.get("command", "") for name in ("protect_evidence.py", "protect_runtime.py"))
        ]
        hooks.write_text(__import__("json").dumps(payload))
        report = research.check_adapters(self.root, "codex")
        messages = "\n".join(item.message for item in report.errors)
        self.assertIn("protect_evidence.py", messages)
        self.assertIn("protect_runtime.py", messages)

        config = self.root / ".codex/config.toml"
        config.write_text(config.read_text().replace("network_access = false", "network_access = true", 1))
        self.assertIn("codex-native-safety-drift", diagnostic_codes(research.check_adapters(self.root, "codex")))

    def test_fake_async_guard_name_and_claude_hook_disable_do_not_pass(self) -> None:
        hooks = self.root / ".codex/hooks.json"
        payload = __import__("json").loads(hooks.read_text())
        handler = next(
            hook for hook in payload["hooks"]["PreToolUse"][0]["hooks"]
            if "no_git.py" in hook.get("command", "")
        )
        handler["command"] = "echo no_git.py --hook codex"
        handler["async"] = True
        hooks.write_text(__import__("json").dumps(payload))
        self.assertIn("native-guard-not-wired", diagnostic_codes(research.check_adapters(self.root, "codex")))

        settings = self.root / ".claude/settings.json"
        payload = __import__("json").loads(settings.read_text())
        payload["disableAllHooks"] = True
        settings.write_text(__import__("json").dumps(payload))
        self.assertIn("claude-hooks-disabled", diagnostic_codes(research.check_adapters(self.root, "claude")))

    def test_matchers_require_exact_literal_tool_alternatives(self) -> None:
        codex_hooks = self.root / ".codex/hooks.json"
        codex = __import__("json").loads(codex_hooks.read_text())
        codex["hooks"]["PreToolUse"][0]["matcher"] = "BashEditWriteapply_patch"
        codex["hooks"]["PreToolUse"][1]["matcher"] = "NotAnAgentspawn_agent"
        codex_hooks.write_text(__import__("json").dumps(codex))
        codes = diagnostic_codes(research.check_adapters(self.root, "codex"))
        self.assertIn("native-hook-matcher-invalid", codes)
        self.assertIn("native-agent-matcher-invalid", codes)

        claude_settings = self.root / ".claude/settings.json"
        claude = __import__("json").loads(claude_settings.read_text())
        claude["hooks"]["PreToolUse"][0]["matcher"] = (
            "BashPowerShellMonitorEditWriteNotebookEditEnterWorktree"
        )
        next(
            entry for entry in claude["hooks"]["PreToolUse"]
            if entry.get("matcher") == "Agent"
        )["matcher"] = "NotAnAgent"
        claude_settings.write_text(__import__("json").dumps(claude))
        codes = diagnostic_codes(research.check_adapters(self.root, "claude"))
        self.assertIn("native-hook-matcher-invalid", codes)
        self.assertIn("native-agent-matcher-invalid", codes)
        self.assertIn("native-worktree-entry-guard-missing", codes)

        focused = self.root / ".claude/agents/substantive.md"
        focused.write_text(focused.read_text().replace(
            'matcher: "Bash|PowerShell|Monitor|Edit|Write|NotebookEdit"',
            'matcher: "BashPowerShellMonitorEditWriteNotebookEdit"',
            1,
        ))
        self.assertIn(
            "focused-hook-surface-missing",
            diagnostic_codes(research.check_adapters(self.root, "claude")),
        )

    def test_focused_guard_fields_must_live_in_native_hook_structure(self) -> None:
        codex = self.root / ".codex/agents/substantive.toml"
        codex.write_text(
            codex.read_text()
            .replace("[[hooks.PreToolUse]]", "# removed hook table", 1)
            .replace("[[hooks.PreToolUse.hooks]]", "# removed handler table", 1)
        )
        self.assertIn(
            "focused-hook-handler-invalid",
            diagnostic_codes(research.check_adapters(self.root, "codex")),
        )

        claude = self.root / ".claude/agents/substantive.md"
        text = claude.read_text()
        lines = text.splitlines()
        closing = next(index for index, line in enumerate(lines[1:], 1) if line == "---")
        hook_start = lines.index("hooks:", 1, closing)
        hook_block = "\n".join(lines[hook_start:closing])
        rewritten = lines[:hook_start] + lines[closing:]
        claude.write_text("\n".join(rewritten) + f"\n```yaml\n{hook_block}\n```\n")
        self.assertIn(
            "focused-hook-handler-invalid",
            diagnostic_codes(research.check_adapters(self.root, "claude")),
        )

    def test_root_and_role_permissions_cannot_weaken_runtime_safety(self) -> None:
        config = self.root / ".codex/config.toml"
        config.write_text(config.read_text().replace(
            'approvals_reviewer = "user"', 'approvals_reviewer = "auto"', 1,
        ))
        self.assertIn(
            "codex-native-safety-drift",
            diagnostic_codes(research.check_adapters(self.root, "codex")),
        )

        coordinator = self.root / ".codex/agents/coordinator.toml"
        coordinator.write_text(coordinator.read_text().replace(
            'sandbox_mode = "workspace-write"',
            'sandbox_mode = "danger-full-access"\napproval_policy = "never"\n\n[features]\nhooks = false',
            1,
        ))
        self.assertIn(
            "agent-native-safety-drift",
            diagnostic_codes(research.check_adapters(self.root, "codex")),
        )

        claude_role = self.root / ".claude/agents/coordinator.md"
        claude_role.write_text(claude_role.read_text().replace(
            "permissionMode: default", "permissionMode: bypassPermissions", 1,
        ))
        self.assertIn(
            "agent-native-safety-drift",
            diagnostic_codes(research.check_adapters(self.root, "claude")),
        )

        settings = self.root / ".claude/settings.json"
        payload = __import__("json").loads(settings.read_text())
        payload["permissions"]["defaultMode"] = "dontAsk"
        settings.write_text(__import__("json").dumps(payload))
        self.assertIn(
            "claude-permission-default-unsafe",
            diagnostic_codes(research.check_adapters(self.root, "claude")),
        )

    def test_codex_native_forbidden_rule_must_bind_to_git_pattern(self) -> None:
        rules = self.root / ".codex/rules/no-git.rules"
        rules.write_text(
            '# Git is mentioned only in this comment.\n'
            'prefix_rule(\n'
            '    pattern = ["rm"],\n'
            '    decision = "forbidden",\n'
            ')\n'
        )
        self.assertIn(
            "native-no-git-deny-missing",
            diagnostic_codes(research.check_adapters(self.root, "codex")),
        )

    def test_malformed_native_config_fails_closed_on_python_310(self) -> None:
        config = self.root / ".codex/config.toml"
        config.write_text(config.read_text() + "\ninvalid = [\n")
        self.assertIn(
            "adapter-native-syntax-invalid",
            diagnostic_codes(research.check_adapters(self.root, "codex")),
        )

        agent = self.root / ".claude/agents/coordinator.md"
        agent.write_text(agent.read_text().replace(
            "permissionMode: default\n---",
            "permissionMode: default\ninvalid: [\n---",
            1,
        ))
        self.assertIn(
            "adapter-native-syntax-invalid",
            diagnostic_codes(research.check_adapters(self.root, "claude")),
        )


if __name__ == "__main__":
    unittest.main()
