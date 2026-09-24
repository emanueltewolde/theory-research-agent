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

## General writing principles — to be discussed

The shared aspiration is exposition that is easy to understand, elegant, and
concise for the relevant communities: algorithmic game theory, AI decision
making, theoretical computer science, optimization, reinforcement learning,
and AI safety. Detailed general writing principles are deliberately pending
discussion with the human; this scaffold does not prescribe them.

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
