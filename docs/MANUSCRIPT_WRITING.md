# Manuscript writing guide

Read this guide only for an explicitly requested writing task, whether in the
current session, a separate writing session, or an optional `writer` subagent.
Ordinary research does not need this guide or the curated manuscript.

## Orientation and scope

Read [the user-filled writing orientation](../curated_manuscript/WRITING_ORIENTATION.md)
alongside this guide. It governs the paper's story, contributions, selection,
project-specific conventions, and protected sections; `PROJECT.md` remains
authoritative for research scope and assumptions. Read both once, then follow
only the sources needed for the assigned sections.

The current user request sets the write boundary. Check
[manuscript setup](../curated_manuscript/README.md) before first drafting.
If essential editorial choices remain blank, ask or propose options in the
report; do not silently choose a new paper story. The orientation is
human-maintained: propose changes rather than editing it without authorization.
Preserve known or reasonably inferable recent edits by another user; flag a
conflict before overwriting them.

## Shared fidelity standard

- Work from exact claims, current passing reviews, and relevant literature
  notes. Neither LaTeX document is evidence or authority for the other.
- Preserve assumptions, quantifiers, scope, exceptions, evidence class, and
  attribution. Clearly distinguish project contributions, imported results,
  empirical observations, and open questions.
- Keep each included result traceable through `PROVENANCE.md`, using the
  [provenance contract](ARTIFACTS.md#reports-and-manuscript-provenance).
  Grouping claims does not authorize strengthening them. New combinations or
  adaptations that need an argument go back to research and verification.
- Exposition changes never authorize changes to claims, reviews, evidence,
  `PROJECT.md`, or shared control records. Report a discovered gap rather than
  repairing the research silently.

## Document purposes

`results_overview/` is a broad, structured collection of mature findings with
explanation and provenance, without full proofs. Its maintenance guidance is in
[METHOD.md](METHOD.md#human-overview-and-manuscript-synthesis); ordinary refreshes
need not load this writing guide.

`curated_manuscript/` is selective: organize the main body around the central
takeaways and important results, with necessary proofs and supporting detail
placed according to the orientation and venue constraints. Omitting other
project results is intentional, but do not omit qualifications that change
the meaning of a contribution. Preserve the venue's formatting, anonymity,
bibliography, and other requirements. Keep TeX inputs, figures, bibliography,
and style dependencies inside its directory.

## General writing principles

For papers with a theory component, write for the relevant audience in AI,
game theory and economics, and theoretical computer science. Aim for exposition that is
easy to understand, elegant, and concise. The main body builds understanding
of the contribution; the appendix makes its supporting arguments and details
easy to examine. Both deserve the same correctness and clarity. These paper
standards apply to `curated_manuscript/`; the results overview retains its
lighter collection-and-explanation purpose.

### Shared standards for exposition

- **Reduce reconstruction work.** Concision means less reader effort, not
  fewer words at any cost. Prefer familiar nouns, direct verbs, and standard
  terminology to invented labels or metaphors that replace explanation.
  Explain unfamiliar conventions when writing across communities.
- **Make notation earn its place.** Introduce symbols with their roles and
  use them consistently across statements, proofs, and appendices. Keep
  proof-local notation local and use existing macros. Plain prose must still
  identify precise objects: a few local symbols can clarify comparisons that
  ambiguous pronouns or repeated descriptions obscure. Avoid unnecessary
  aliases and names for one-off observations.
- **Give presentation a purpose.** Each paragraph should advance an idea,
  argument, or contrast. Use informative headings and result titles. Display
  equations when they expose structure or support later reference, and explain
  important terms. Choose examples and figures that reveal the question or
  mechanism, not merely the smallest example or an attractive picture. Give
  each a distinct explanatory job. Identify what is compared and distinguish
  guarantees, observations, and limiting values.
- **Explain why the proof works.** State the goal and decisive mechanism
  before details whose purpose is not apparent. Identify what is given, what
  is constructed, and what must be checked. Mark changes of argument and
  which objects, distributions, or assumptions remain active. Expose the
  logical bridge at consequential steps; neither intuition nor correct
  calculations alone suffice. Keep routine steps and transparent short proofs
  brief, without boilerplate roadmaps or summaries.
- **Reuse reasoning without hiding it.** Extract shared lemmas when they
  expose a recurring mechanism and reduce reader effort, not merely similar
  algebra. Introduce substantial shared reasoning before relying on it; do
  not bury it in one proof and ask readers to reconstruct an adaptation later.
  References should identify the exact conclusion used and any substitutions
  or changed hypotheses. For imported results, state what they supply and why
  they apply; retain the reasoning needed for an adaptation.

### Main body

Organize around the reader's questions, not discovery order: why the problem
matters, what was unresolved, what is established, and what makes the result
possible or difficult. Give central contributions, supporting observations,
and extensions distinct prominence. Keep preliminaries lean and introduce
specialized machinery when its purpose is apparent. The orientation and venue
guide emphasis; these questions do not prescribe a fixed section order.

In the introduction, start from a concrete problem or tension and motivate
the requirements before formalizing them. Let each major contribution answer
a question the reader now understands and cares about. Explain what a
technical connection enables and its tradeoffs, rather than merely announcing
the connection. Build an argument, not an inventory of results.

Provide several levels of access. The abstract and introduction communicate
the question and takeaway, precise statements specify the guarantees, and
proof discussion exposes the mechanism. Keep these layers consistent without
repeating identical prose. Do not turn the main body into theorem statements
followed only by appendix pointers: explain important proof ideas, or give a
short complete proof when that is clearer. Not every result needs a sketch.

Separate motivation, formal model, and justified implication. Explain what
the model captures and where it stops. Behavioral or informational assumptions
are not established properties of deployed agents. Interpret important
assumptions and bounds: what they mean, when guarantees are informative, and
what remains unproved. Distinguish an assumption used by the proof from one
proved necessary. Essential restrictions and limitations must be visible in
the main account, not deferred to rescue an overbroad headline.

Position contributions through specific, fair contrasts with the closest
prior approaches. Identify the improvement
and its tradeoffs in assumptions, guarantees, computation, information, or
applicability. Explain relationships among results, including counterexamples
that delimit their meaning. Do not call incomparable guarantees stronger or
infer novelty from new terminology; keep broader implications distinct from
established conclusions.

When experiments are present, explain whether they illustrate a mechanism,
probe behavior beyond the theorem's assumptions, assess practical relevance,
or support a separate empirical claim. Empirical agreement is not proof, and
a theorem about an idealized model does not validate an implementation.
Experiments are not required merely because the paper concerns AI.

### Appendix

Make supporting material easy to find and verify. Organize around identifiable
results and logical obligations, generally following the main text unless
another arrangement is clearer. State or restate the result before its proof,
preferably from a shared statement source or automatic restatement to avoid drift.
Use proof environments and purposeful intermediate lemmas or headings for
longer arguments, making clear which theorem parts are established.

Be locally readable, not a second paper. Recall essential definitions and
active assumptions when this saves repeated searching, and give precise
references for established setup. Do not repeat the introduction or all
preliminaries. Readers should be able to tell what is being proved and why
each substantial step helps without reconstructing the surrounding context.

Supply complete supporting arguments, with imported results precisely
identified. Completeness does not require every algebraic rearrangement, but
difficult steps still need explanation. Moving a proof to the appendix is no
reason to replace explanatory prose with dense equations or leave gaps behind
"clearly." Extra generality should serve a useful purpose, not add avoidable
notation and dependencies.

Remain selective. Include extensions, robustness analyses, examples, and
technical or experimental details that substantiate the paper. Experimental
detail should support interpretation and reproducibility rather than collect
raw output. The appendix is not an inventory of everything omitted from the
main body. Keep other mature results in the results overview and preserve
failed approaches in research records rather than adding them for completeness.

## Delivery

Check source fidelity, protected sections, references, and provenance; compile
when the environment permits and report any build limitation. Update only the
authorized document's coverage note; do not synchronize the other document.
No agent runs Git or synchronizes Overleaf.

Use the existing task output or run handoff. Report changed sections, validation
performed, unresolved editorial decisions, and a brief **Research implications**
section: missing claims/proofs/evidence/citations, notation or scope tensions,
and proposed contract/story changes (or `None.`). Research implications are
proposals for integration, not a second handoff artifact or permission to
change research records.

If new labels need claim-record backlinks, list those exact additions in the
output for the integration authority. They remain pending validation until
integrated; a writer does not gain permission to edit claims.
