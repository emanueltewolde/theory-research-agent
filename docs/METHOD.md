# Research Method

This workspace supports long-running theoretical computer-science research with ordinary files as the durable coordination medium. It specifies what must remain true across sessions, while leaving proof strategy, task decomposition, and the use of focused agents to the acting model.

The method is runtime-neutral. Provider chat history, memory, and native subagents may be useful conveniences, but a fresh session must be able to resume from the repository alone.

## Governing invariants

1. **Human intent is authoritative.** The objective, formal model, permitted assumptions, scope, and success criteria live in [`PROJECT.md`](../PROJECT.md). A consequential change requires an explicit human decision and a new contract revision.
2. **There is one resume point.** Operational resumption always begins with [`STATE.md`](../STATE.md). Reports, run logs, and the manuscript never compete with it.
3. **Each fact has one authoritative home.** Dashboards and reports link to detailed claims and evidence instead of copying their derivations.
4. **Knowledge survives context loss.** Material findings are checkpointed in durable artifacts during a run, then summarized in its handoff.
5. **Negative knowledge is durable.** Failed approaches, counterexamples, rejected claims, and closed directions remain indexed and explain when reconsideration would make sense.
6. **Important claims receive fresh review.** A review binds to the exact claim and evidence revisions and both statement/evidence digests, checks correctness, and separately checks claim fidelity.
7. **Evidence stays honest.** Literature and experiments retain provenance. Empirical or computational support is never silently presented as a mathematical proof.
8. **Parallel work has bounded writes.** One integration authority updates shared control records and the manuscript. Focused work writes only to its task directory and explicitly assigned artifacts.
9. **The runtime is replaceable.** Research tasks request semantic effort profiles; provider-specific model names and invocation syntax belong in adapters.
10. **Research agents do not use Git.** Humans or trusted external automation own version control. Epistemic corrections are still recorded through status, supersession, and revision links.

## Information layers

The workspace deliberately separates four kinds of information.

| Layer | Purpose | Principal artifacts |
|---|---|---|
| Control | Current intent and action selection | [`PROJECT.md`](../PROJECT.md), [`STATE.md`](../STATE.md), [`ARTIFACT_INDEX.md`](../ARTIFACT_INDEX.md), [`DIRECTIONS.md`](../research/DIRECTIONS.md), [`INBOX.md`](../research/INBOX.md) |
| Durable knowledge | Exact results and evidence | Claims, attempts, reviews, literature notes, and experiments |
| History | What happened in each substantial session | [`runs/`](../runs/) |
| Synthesis | Curated communication, not operational truth | [`OVERVIEW.md`](../OVERVIEW.md), [`reports/`](../reports/), and the paper |

When information appears in more than one layer, one location is authoritative and every other occurrence must be a short linked description. See [`ARTIFACTS.md`](ARTIFACTS.md) for the source-of-truth table.

## Responsibilities, not a fixed topology

The method distinguishes responsibilities without requiring permanent agent roles:

- **Broad-context integration** understands the project as a whole, selects valuable work, allocates effort, triages findings, and updates shared records.
- **Focused research** tackles a bounded proof, counterexample, experiment, literature synthesis, or other difficult question using only relevant context.
- **Independent verification** examines an exact claim and evidence packet in a fresh critical context. It does not edit the target claim.
- **Paper synthesis** turns validated results into coherent exposition under serialized integration.

One context may perform several responsibilities sequentially. Focused delegation is optional. Independent verification must nevertheless be fresh: when native delegation is unavailable, prepare a task packet for a separate session.

## Human initialization

1. Run `python3 tools/research.py init` to complete missing scaffold structure,
   then fill [`PROJECT.md`](../PROJECT.md). In a copied template, the scaffold
   is already present and `init` makes no research-content changes.
2. Specify whether the project seeks a definite answer, exploratory findings, or both.
3. Define the objective, formal model, central terminology, permitted assumptions, exclusions, success criteria, deliverable, and operational constraints.
4. Record consequential ambiguities rather than hiding them inside prose.
5. Review and explicitly accept contract revision 1.
6. Select provider mappings for the semantic profiles described in [`RUNTIMES.md`](RUNTIMES.md).
7. Run `python3 tools/research.py doctor --runtime codex` or `--runtime claude`.
8. Start the chosen runtime in the project root and ask it to “continue the research.”

Initialization must not install dependencies, initialize version control, or overwrite an initialized project without explicit human confirmation.

## Resume protocol

A new broad-context session should recover deliberately and cheaply:

1. Read [`STATE.md`](../STATE.md).
2. Confirm its referenced contract revision against [`PROJECT.md`](../PROJECT.md).
3. Inspect the last integrated run and any newer active, interrupted, or completed-but-unintegrated run.
4. Follow only links needed for the active objective, strongest relevant results, blockers, open human questions, and likely next action.
5. Reconcile unfinished or unintegrated work before starting a duplicate effort.
6. Select useful reversible work, subject to the alignment rules below.

Native conversation resume may accelerate these steps, but it cannot substitute for them. If state claims the workspace is clean while a newer run is not integrated, treat recovery as required.

## Opening a substantial run

Open a [`RUN`](../templates/run.md) record before expensive work:

- allocate a monotonic run ID;
- record the base state revision and contract revision;
- state the run objective and integration authority;
- mark the run active;
- reserve durable artifact IDs when known;
- create bounded task packets for focused work.

A task packet specifies the question, successful outcomes, authoritative inputs, allowed assumptions, write boundary, requested semantic profile, and return contract. It does not prescribe how the agent must reason.

Material results should be checkpointed when discovered or before context pressure becomes risky. Do not rely on graceful shutdown or private conversation history to preserve important work.

## Focused work and parallelism

The integration authority chooses whether to work directly, launch focused contexts, or prepare work for later sessions. Base this choice on expected leverage, difficulty, uncertainty, consequence, prior failure, and coordination cost—not fixed attempt counts or a mandatory worker topology.

Parallel tasks should normally write under unique directories such as:

```text
runs/RUN-0007/tasks/T01/
runs/RUN-0007/tasks/T02/
```

Each task directory contains `TASK.md`, `OUTPUT.md`, and `RECEIPT.md`. A focused context may also write a preallocated attempt, experiment, or literature artifact if the packet explicitly grants that path. It must not update `PROJECT.md`, `STATE.md`, shared indexes, the direction portfolio, the overview, completed raw evidence, another task, or the manuscript.

## Integration and clean close

The integration authority reconciles focused outputs rather than copying them uncritically:

1. Classify each output as supported, refuted, inconclusive, blocked, requiring verification, or a runtime failure.
2. Promote exact supported conclusions into claims; do not treat an attempt or task output as the final epistemic record.
3. Preserve failed mechanisms, counterexamples, and abandoned approaches in attempt and direction records.
4. Triage deferred ideas and alignment questions.
5. Update direction assessments and revival conditions.
6. Create fresh verification tasks for important candidates.
7. Promote material into the paper only through the validation gate.
8. Complete the run handoff and task receipts.
9. Update the artifact index, portfolio, and human overview when triggered.
10. Update `STATE.md` last, advancing its revision and naming the integrated run.

Updating state last is the integration marker. If a session stops after producing evidence but before publishing state, the next session can find and reconcile the newer run.

Every substantial run handoff must record:

- what was attempted;
- the most important findings and their evidence links;
- changed artifacts;
- negative results;
- provisional assumptions and remaining uncertainty;
- human questions;
- recommended next actions;
- whether strategic review or a human-facing milestone refresh is due.

The runtime's final response to the human mirrors this handoff concisely:
strongest result, informative failure or uncertainty, consequential questions,
and recommended next action. When an overview trigger fires, it also links the
refreshed overview, immutable milestone report, and latest paper PDF when the
local LaTeX environment produced one (otherwise the paper source and build
blocker).

## Claim and verification discipline

Claims move through the lifecycle defined in [`ARTIFACTS.md`](ARTIFACTS.md). The exact statement, assumptions, quantifiers, scope, and exceptional cases belong in the claim record. A verifier receives those materials plus definitions, dependencies, and evidence—not the producer’s conversation transcript or a suggested verdict.

A review answers two questions independently:

1. Is the proof or evidence correct?
2. Does it establish exactly the recorded statement and answer the intended project question at that scope?

A correct proof of a narrower statement does not pass the broader claim. Create or revise a candidate claim, recompute its digest, and review it afresh. A valid counterexample or impossibility result is a successful resolution when it answers the assigned question.

The integrating context records each candidate's required semantic review
profile. Ordinary important claims default to `substantive`; subtle central
claims may require `deep`, and claimed breakthroughs or project-shaping claims
require `pivotal`. The requirement is part of the claim rather than an
unstated memory, so unavailable capability remains visible as verification
debt.

## Evidence discipline

### Literature

Record only literature that becomes relevant. A note must preserve the precise source location, source assumptions, project-facing paraphrase, any nontrivial translation of models or notation, limitations, and links to the questions it informs. Consequential searches additionally record search locations, queries, dates, selection logic, and known gaps.

### Experiments

An experiment states in advance what its outcomes would and would not establish. Record code entry points, commands, dependencies, input provenance, parameters, seeds, hardware when relevant, and immutable execution outputs. A rerun appends a new execution ID instead of overwriting old evidence.

Computational discovery may suggest a mathematical claim. It does not validate that claim as a proof; a computationally found counterexample must receive an independent mathematical check before becoming a validated mathematical counterexample.

## Consequential uncertainty and human alignment

Classify unresolved uncertainty by consequence:

| Class | Response |
|---|---|
| Safe provisional | Continue reversible work and record the assumption |
| Consequential but deferrable | Continue only to an explicit safe horizon |
| Dangerous now | Pause the affected branch and work elsewhere |
| Project-blocking | Ask immediately because no valuable independent branch remains |

Each alignment item records the question, why it matters, the provisional assumption, dependent artifacts, safe continuation horizon, affected branch, and human answer. Questions are normally surfaced in the run handoff. Do not silently change the formal model, allowed assumptions, target scope, or success criterion.

An accepted contract change must:

1. increment the contract revision;
2. record the explicit human decision;
3. identify affected claims, experiments, directions, and manuscript locations;
4. mark anything requiring revalidation.

## Strategic and trajectory review

At every run close, check whether the qualitative trigger stored in `STATE.md` has occurred. A review is warranted when, for example:

- a central proof, disproof, or failed verification changes the trajectory;
- local results no longer compose toward the objective;
- a direction consumes effort after its rationale weakens;
- verification or manuscript debt becomes strategically important;
- literature changes the apparent novelty or feasibility;
- a human decision or research milestone is reached.

Assess goal composition, sunk-cost behavior, direction balance, verification debt, missing theorem links, literature gaps, and whether the manuscript reflects the actual strongest contribution. Update the portfolio, next action, and next qualitative trigger. Do not introduce fixed attempt thresholds or numerical direction rankings.

## Human overview and paper synthesis

[`OVERVIEW.md`](../OVERVIEW.md) is a concise, non-authoritative navigation page. Refresh it by the cadence in the project contract—initially every two to three substantial runs—and immediately after a major theorem, counterexample, central failed review, strategic pivot, or dangerous alignment question. A milestone may also receive an immutable report in [`reports/`](../reports/).

The manuscript contains mature definitions, theorem statements, derivations, counterexamples, empirical findings, related literature, limitations, and supported conclusions. Established theorem-like content requires a validated claim and a passing independent review. Manuscript labels link back to their evidence and reviews through the paper provenance map. Open conjectures must be visibly labeled and cannot support established conclusions.

## Short illustrative snippets

These are non-live examples of the intended level of precision; they are not a
worked research project and do not allocate IDs.

An objective can explicitly make disproof a successful outcome:

```markdown
## Research mode

Definite existence question with an exploratory boundary-characterization
fallback. A valid counterexample resolves the primary conjecture.

## Objective and intended contribution

Determine whether every finite instance of model M admits an epsilon-stable
allocation with welfare at least alpha times optimum, or characterize the
minimal obstruction.
```

A resume recommendation should name the exact leverage and verification risk:

```markdown
## Recommended next action

Freshly verify the candidate lower bound, concentrating on the conditioning
step, quantifier order, and whether it covers the original model rather than
only the independent-valuation restriction.
```

A consequential ambiguity records how far reversible work may continue:

```markdown
- **Finding or question:** Does equilibrium permit mixed strategies?
- **Why it matters:** The candidate lower bound fails for pure strategies.
- **Provisional assumption:** Finite mixed Nash equilibrium is permitted.
- **Dependent artifacts:** the lower-bound claim and equilibrium direction
- **Safe continuation horizon:** literature search and small-instance tests only
- **Affected branch:** central proof paused after that horizon; other directions continue
- **Human answer:** pending
```

A negative attempt preserves the mechanism, not just the verdict:

```markdown
## Exact failure point or obstruction

The induction deletes a zero-probability action, but the next step conditions
on that action. The conditional distribution is therefore undefined; retry
only if the argument is reformulated without that conditioning operation.
```

## Method boundaries

This template intentionally does not prescribe a proof procedure, fixed agent count, fixed research queue, attempt threshold, database, vector memory, dispatcher service, automated literature-ingestion pipeline, or numerical direction score. Add procedural machinery only when it protects a demonstrated invariant and remains simpler than the failure it prevents.
