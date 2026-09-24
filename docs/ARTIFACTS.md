# Artifact Contracts

This document defines the durable record types, their authoritative meanings, identifiers, fixed labels, and lifecycle rules. All core records are ordinary Markdown with predictable headings and bold labels. They do not use YAML frontmatter or hidden metadata.

Use the annotated blanks in [`templates/`](../templates/) rather than copying an existing research record, which may contain stale assumptions.

## Identifier system

[`ARTIFACT_INDEX.md`](../ARTIFACT_INDEX.md) is the authoritative allocator and registry.

| Prefix | Artifact | Normal location | Example |
|---|---|---|---|
| `RUN` | Substantial run | `runs/RUN-####/RUN.md` | `RUN-0007` |
| `DIR` | Research direction | `research/DIRECTIONS.md`, with an optional expanded file | `DIR-0012` |
| `CLM` | Exact claim | `research/claims/CLM-####.md` | `CLM-0024` |
| `ATT` | Proof, derivation, search, or exploratory attempt | `research/attempts/ATT-####.md` | `ATT-0041` |
| `REV` | Independent verification | `research/reviews/REV-####.md` | `REV-0008` |
| `LIT` | Literature note or consequential search record | `literature/notes/` or `literature/searches/` | `LIT-0016` |
| `EXP` | Experiment | `experiments/EXP-####/README.md` | `EXP-0006` |
| `INB` | Deferred finding, blocker, or alignment item | `research/INBOX.md` | `INB-0014` |
| `RPT` | Immutable milestone report | `reports/RPT-####.md` | `RPT-0003` |

Rules:

- Each prefix has its own monotonically increasing counter.
- An ID is never reused, deleted from the registry, or renumbered.
- Abandoned reservations remain registered with status `abandoned` and a reason.
- The integrator allocates durable IDs. Parallel focused work uses run-local IDs such as `RUN-0007-T02` until promotion.
- Dedicated filenames use only the ID. Human-readable titles belong inside the record.
- Cross-references use relative Markdown links, not bare IDs.
- `python3 tools/research.py new <kind>` is the normal allocator. Manually created records must pass `research.py check`.

## Fixed record header

A dedicated artifact begins with one level-one heading followed immediately by fixed bold labels. For example:

```markdown
# CLM-0024 — Counterexample to the naive correlated extension

- **Status:** under review
- **Evidence class:** mathematical counterexample
- **Claim revision:** 2
- **Contract revision:** 3
- **Created in:** linked run record
- **Last updated in:** linked run record
- **Related artifacts:** linked attempt record
- **Supersedes:** none
```

Portfolio and inbox items use the same labels under a level-two item heading because several items share one file. Fixed labels must be retained even when their value is `none`, `pending`, `not applicable`, or `unknown`. Use those explicit values instead of deleting a field.

## Authoritative homes

| Information | Authoritative location |
|---|---|
| Objective, model, permitted assumptions, scope, success criteria | `PROJECT.md` |
| Current objective, strongest results, blockers, next action | `STATE.md` |
| ID allocation and artifact paths | `ARTIFACT_INDEX.md` |
| Direction activity, assessment, and revival conditions | `research/DIRECTIONS.md` |
| Exact claim wording and epistemic status | The relevant claim file |
| What an approach attempted and why it failed | The relevant attempt file |
| Verification verdict | The relevant review file |
| Experimental protocol and raw evidence | The relevant experiment directory |
| Source meaning and translation into project terminology | The relevant literature record |
| Chronological session history | The relevant run record |
| Human navigation | `OVERVIEW.md` and milestone reports |
| Broad, periodically refreshed result collection | `results_overview/`, linked through its provenance map |
| Paper story, selection, and project-specific writing conventions | `curated_manuscript/WRITING_ORIENTATION.md` (human-maintained) |
| Human-directed venue exposition | `curated_manuscript/`, linked through its separate provenance map |

## Operational controlled values

These values are part of the stable text interface and are validated exactly:

| Record or field | Allowed values |
|---|---|
| `STATE.md` integration condition | `clean`, `active run`, `recovery required` |
| Run status | `active`, `interrupted`, `completed` |
| Run integration status | `not integrated`, `partially integrated`, `integrated` |
| Attempt status | `active`, `completed` |
| Review status | `draft`, `active`, `completed` |
| Literature status | `draft`, `active`, `completed`, `superseded` |
| Experiment status | `planned`, `active`, `completed`, `blocked`, `superseded` |
| Report status | `draft`, `published` |
| Focused task status | `planned`, `active`, `completed`, `cancelled` |
| Task output status | `in progress`, `completed`, `failed` |
| Runtime receipt status | `not started`, `running`, `completed`, `failed` |
| Task outcome classification | `pending`, `supported`, `refuted`, `inconclusive`, `blocked`, `requiring verification`, `runtime failure` |

Claim, direction, and inbox lifecycles are described in their dedicated
sections below. Use `none`, `pending`, `not applicable`, and `unknown` only
where a template or lifecycle gate permits them; they are not interchangeable.

## Project contract

[`PROJECT.md`](../PROJECT.md) is compact and human-authoritative. It records its revision and date, research mode, objective, intended contribution, formal model, definitions, assumptions, prohibited shortcuts, scope, exclusions, background, success criteria, deliverable, operational constraints, alignment triggers, report cadence, cost envelope, and semantic revision log.

`Contract status` is `uninitialized` for the blank template and `accepted`
only after an explicit human decision. Substantive runs and artifacts must not
be opened against revision 0 or an unaccepted contract.

Agents may draft proposed edits but must not publish a consequential change without an explicit human decision. An accepted change increments the revision and lists affected artifacts and revalidation needs.

## Resume state

[`STATE.md`](../STATE.md) is a linked dashboard, not a notebook. It records the state revision, contract revision, last integrated run, integration condition, active objective, strongest results, pivotal candidates, active/parked directions, blockers, human questions, in-flight work, recommended next action, useful alternatives, strategic-review trigger, and overview-refresh trigger.

Keep it compact. Detailed proofs, logs, and evidence belong elsewhere. It is updated last during integration.

## Direction portfolio

[`research/DIRECTIONS.md`](../research/DIRECTIONS.md) uses two independent classifications:

- **Activity:** `active`, `parked`, `blocked`, or `closed`.
- **Assessment:** `promising`, `uncertain`, `attempted-unresolved`, `weak`, `succeeded`, or `failed`.

Every direction records its research question, importance, supporting and opposing evidence, obstacle, next discriminating action, stop condition, revival condition, last strategic review, and linked evidence. Closed and failed directions remain visible. If an entry becomes too long, move details to `research/directions/DIR-####.md` while keeping a concise linked portfolio entry.

## Inbox and alignment records

[`research/INBOX.md`](../research/INBOX.md) accepts the following kinds: `idea`, `question`, `lemma`, `experiment`, `literature lead`, `model concern`, `blocker`, `infrastructure`, and `human alignment`.

Disposition is one of `new`, `pursue`, `merged`, `deferred`, `discarded`, or `resolved`. All items record their source, finding or question, importance, relationship, triage reason, and revisit condition.

A human-alignment item additionally records an uncertainty class, provisional assumption, dependent artifacts, safe continuation horizon, affected branch, and human answer. Its uncertainty class is one of `safe provisional`, `consequential but deferrable`, `dangerous now`, or `project-blocking`.

## Claims

Claim kind is one of:

- `theorem`;
- `lemma`;
- `counterexample`;
- `impossibility`;
- `empirical observation`;
- `literature-derived proposition`.

Evidence class describes what actually supports the claim, such as `mathematical proof`, `mathematical counterexample`, `exhaustive computation over stated domain`, `empirical experiment`, or `literature source`. Do not use a stronger class than the evidence warrants.

`Required review profile` is `substantive`, `deep`, or `pivotal`, selected from
the difficulty, centrality, and consequence of verifying the claim. Validation
requires a current, fresh, completed passing review at the recorded profile.
An unavailable high tier leaves review pending rather than silently lowering
this field.

Status lifecycle:

```text
draft -> candidate -> under review -> validated
                              |-----> rejected
                              |-----> refuted
                              |-----> inconclusive

any status -------------------------> superseded
```

Allowed recovery transitions include `rejected`, `refuted`, or `inconclusive` to `candidate` only after a substantive revision that increments the claim revision and invalidates prior review coverage. A validated claim that changes substantively receives a new claim ID with a `Supersedes` link. Typographical corrections may retain the ID and revision if a change note confirms that the normalized statement and assumptions did not change.

“Validated” is relative to the evidence class. A validated empirical observation is still not a theorem. Refuting an original conjecture retains that claim as `refuted` and creates a separate counterexample or impossibility claim that may itself be validated.

### Statement digest

Reviews bind to the exact claim revision and a SHA-256 digest. The digest input is:

1. the content under `## Exact statement` up to the next level-two heading;
2. the content under `## Assumptions, quantifiers, scope, and exceptions` up to the next level-two heading.

Normalize CRLF to LF, remove trailing whitespace from every line, remove leading and trailing blank lines in each section, and compute SHA-256 over this UTF-8 string:

```text
EXACT STATEMENT
<normalized exact-statement content>
ASSUMPTIONS, QUANTIFIERS, SCOPE, AND EXCEPTIONS
<normalized assumptions content>
```

Store the result as `sha256:` followed by the 64 lowercase hexadecimal digest characters. When either normalized section changes, increment `Claim revision`, recompute `Statement digest`, and treat existing reviews as stale. The validator should report stale coverage rather than rewriting the claim.

### Evidence digest

Reviews also bind the material and epistemic classification that support the
statement. Normalize the content under `## Dependencies`, `## Evidence`,
`## Proof or derivation`, `## Relationship to the project question`, and
`## Known limitations and open issues` with the same LF,
trailing-whitespace, and outer-blank-line rules. Normalize the fixed `Claim
kind` and `Evidence class` values in the same way, then compute SHA-256 over
this UTF-8 string in exactly this order:

```text
DEPENDENCIES
<normalized dependencies content>
EVIDENCE
<normalized evidence content>
PROOF OR DERIVATION
<normalized proof-or-derivation content>
CLAIM KIND
<normalized Claim kind value>
EVIDENCE CLASS
<normalized Evidence class value>
RELATIONSHIP TO THE PROJECT QUESTION
<normalized relationship content>
KNOWN LIMITATIONS AND OPEN ISSUES
<normalized limitations content>
```

Store `Evidence revision` and `Evidence digest` on the claim, and bind both as
`Target evidence revision` and `Target evidence digest` on every review. A
change to a dependency, evidence link, proof, derivation, inferential chain,
claim kind, evidence class, project relationship, or limitation increments
the evidence revision, recomputes its digest, and makes earlier review
coverage stale even when the theorem statement is unchanged. Validated claim
dependencies that are themselves claims must be
currently validated; a rejected, refuted, superseded, or otherwise stale
dependency invalidates downstream established use.

## Attempts and negative results

An attempt has operational status `active` or `completed`; its epistemic outcome is `proved`, `disproved`, `failed`, `inconclusive`, or `blocked`. The record explains the approach at a reviewable level, the exact failure point, counterexamples or partial lemmas, reusable observations, and retry conditions.

An attempt is not automatically a claim. Integration promotes a precisely supported conclusion into a claim record. “Did not work” without the failure mechanism is not an adequate durable negative result.

## Independent reviews

A review verdict is `pass`, `fail`, `narrower-than-stated`, or `inconclusive`. It records target claim ID, statement and evidence revisions/digests, supplied materials, fresh-context status, verification approach, falsification attempts, assumption/quantifier/scope audit, exceptional-case audit, reproduction or source checks, and required follow-up.

The verifier writes only the review and its assigned task output. It cannot edit the target claim. `pass` requires both evidence correctness and exact claim fidelity. A narrower valid result becomes a revised or new candidate claim and receives a fresh review.

An established project theorem in either document requires a passing independent review of its current digests at its recorded required profile. Precisely attributed imported literature follows the provenance rule below.

A validated claim's `Independent reviews` table links the passing review at
its canonical path. If either manuscript provenance map cites the claim, the claim's
`Manuscript locations` section links back to that provenance location; these
two-way navigation links must agree with the authoritative review and manuscript
records.

## Literature records

[`literature/references.bib`](../literature/references.bib) is the canonical research bibliography. The self-contained curated manuscript copies only its needed, checked entries into `curated_manuscript/` while preserving keys and metadata. A literature note records its BibTeX key, stable locator, precise theorem/page/section location, source assumptions, careful project-facing paraphrase, translation between source and project terminology, transferable techniques, relationships, contradictions, and limitations.

A consequential search record adds search locations, exact queries, search dates, selection logic, coverage limits, and unresolved gaps. Allocate it with `python3 tools/research.py new literature --search`; ordinary `new literature` creates a source note. Neither record should claim exhaustive coverage unless the recorded protocol warrants it.

## Experiments

An experiment directory contains `README.md`, code/configuration as needed, protected source inputs, and append-only execution outputs. Status is `planned`, `active`, `completed`, `blocked`, or `superseded`.

Executions use experiment-local monotonic IDs such as `EXP-0006-E001`. Create all execution files first, then create the visible immutable `executions/EXP-0006-E001/COMPLETED.md` manifest from [`templates/execution.md`](../templates/execution.md), and append the fully populated execution-table row last. The manifest—not the mutable index row—freezes the whole execution directory. Never reuse, overwrite, or add late files to a completed execution. Corrections and reruns append new executions and explain the relationship. Record commands, dependencies, input provenance, parameters, seeds, relevant hardware, outputs, and digests where practical.

The README explicitly states what an outcome would and would not establish. Experiment code must not contain hidden expected conclusions or silently alter evidence.

## Runs, tasks, outputs, and receipts

A run has status `active`, `interrupted`, or `completed`, and a separate integration status of `not integrated`, `partially integrated`, or `integrated`.

Focused task IDs are run-local: `RUN-####-T01`, `RUN-####-T02`, and so on. Each task directory normally contains:

- `TASK.md`: question, successful outcomes, authoritative inputs, assumptions, write boundary, and requested semantic profile;
- `OUTPUT.md`: exact conclusions, evidence, negative findings, uncertainties, and recommended next action;
- `RECEIPT.md`: requested and resolved runtime/profile, runtime client version, fresh-context status, write scope, usage when available, substitution/failure, and output links.

A runtime failure is not a research conclusion. Partial outputs remain discoverable and the receipt records the failure.

Important findings must be promoted to claims, attempts, experiments, or literature records. A run log or task output cannot be their sole durable home.

## Reports and manuscript provenance

[`OVERVIEW.md`](../OVERVIEW.md) is a mutable navigation page. A report begins as `draft` and becomes an immutable milestone snapshot when its status changes to `published`. A correction creates a new report whose `Supersedes` link names the prior snapshot; the prior report remains unchanged and `published`.

Each document keeps a compact `PROVENANCE.md` with last content refresh and
covered scope. They need not cover the same results or be refreshed together.
Do not put internal run IDs or bookkeeping into the venue-facing paper.

- **Established manuscript items:** each project theorem, proposition, lemma,
  corollary, figure, or table label links to one or more canonical claims,
  evidence, and passing reviews. Every linked claim must be validated with a
  current bound review at its required profile, and link back from its
  `Manuscript locations`. Grouping is for exposition, not a license to infer
  an unreviewed stronger statement.
- **Imported literature items:** optional table for labeled restatements, with
  columns `LaTeX label`, `Manuscript role`, `Literature note`, `Source locator`,
  `Application and scope`, and `Status` (`imported`). Link a completed
  canonical LIT source note, the precise theorem/page/section, and explain
  applicability and any notation translation. Ordinary citations need no
  duplicate claim or provenance row. Nontrivial adaptations and new conclusions
  still require a project claim and independent review.
- **Open or explicitly provisional items:** identify their source and concrete
  limitation, and visibly label them in the text; they cannot support an
  established conclusion.
- **Stale items requiring revision:** record affected labels and needed repairs
  when a source is corrected, rejected, refuted, or superseded. Missing newer
  findings is coverage lag, not invalidation. Research reports curated-paper
  impacts without editing it absent a writing request.

A writing pass checks exact statement fidelity against these sources; a
passing source review is not itself a review of the manuscript's wording.
Validators check links/status/review bindings, not mathematical equivalence.

## Link and placeholder conventions

- Artifact links are relative to the file containing them.
- Use `none` when there is deliberately no related artifact and `pending` when work remains.
- Template tokens use `{{NAME}}`; supported CLI tokens are documented in [`templates/README.md`](../templates/README.md).
- HTML comments in templates are instructions and should be removed when the record is completed.
- Bare example IDs inside fenced examples are illustrative. Live records must link registered IDs.
