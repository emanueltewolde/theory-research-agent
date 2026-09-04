# Human-directed manuscript writing

Load this guidance only for a separate top-level writing session that the
human explicitly authorized to edit `manuscript-human/`. Ordinary proof,
counterexample, experiment, literature, and integration work should not load
the polished manuscript or this guide unless it is directly relevant to the
assigned task.

## Before editing

1. Read the current user request and treat it as the exact authorization
   boundary. A request to inspect, review, or plan does not authorize edits.
2. Confirm that the human has copied the official venue template into
   `manuscript-human/` and that its unchanged entry point has compiled.
3. Read `PROJECT.md`, the relevant validated claims and passing reviews,
   `manuscript-ai/`, `manuscript-human/PROVENANCE.md`, and only the additional
   evidence or literature needed for the approved sections.
4. Do not run Git, access `.git`, push to GitHub, or synchronize Overleaf.

## Writing standard

- Write for researchers in algorithmic game theory, AI decision making,
  theoretical computer science, optimization, reinforcement learning, and/or AI
  safety, explaining terminology when conventions differ across communities.
- Aim for exposition that is easy to understand, elegant, and concise without
  sacrificing precise statements, explicit assumptions, economical notation,
  or a visible chain from motivation to contribution.
- Preserve the venue template, class, required metadata, anonymity rules,
  page constraints, and bibliography conventions unless the human approves a
  change.
- Prefer a coherent selective argument over copying every research result.
  Keep qualifications and negative evidence that materially delimit the
  contribution.
- Do not promote empirical support, intuition, or an unreviewed argument into
  a theorem. Established theorem-like content must remain linked through the
  manuscript provenance map to a validated claim and current passing review.
- Treat the polished manuscript as exposition, not research authority. Never
  rewrite a claim, review, experiment, or the project contract merely to make
  the story cleaner.
- Keep all TeX inputs, figures, bibliography entries, and style dependencies
  inside `manuscript-human/` so the manuscript-only repository compiles on
  Overleaf.

## Closing report

Use the existing task output or run handoff; do not create a new artifact
type. In addition to the normal changed-file and validation summary, include:

```markdown
## Research implications

- Proposed notation changes:
- Missing claims, proofs, experiments, or citations:
- Tensions with the current formal model or scope:
- Possible changes to the paper's central story:
- Suggested PROJECT.md changes requiring human approval:
```

Write `None.` when there are no implications. This report is a proposal for
the integration context and human; it does not itself authorize changes to
`PROJECT.md` or other research records.
