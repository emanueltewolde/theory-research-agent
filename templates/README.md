# Record Templates

These annotated blanks define the stable Markdown interfaces used by `tools/research.py`. They contain no live research results.

## CLI placeholders

The allocator may replace these tokens:

| Token | Meaning |
|---|---|
| `{{ID}}` | Newly allocated durable artifact ID |
| `{{TITLE}}` | Human-readable title supplied at creation |
| `{{DATE}}` | Creation date in `YYYY-MM-DD` form |
| `{{CONTRACT_REVISION}}` | Current project contract revision |
| `{{STATE_REVISION}}` | Current authoritative state revision |
| `{{CLAIM_ID}}` | Review target claim ID |
| `{{CLAIM_REVISION}}` | Review target claim revision |
| `{{CLAIM_DIGEST}}` | Review target normalized statement digest |
| `{{EVIDENCE_REVISION}}` | Review target evidence/proof revision |
| `{{EVIDENCE_DIGEST}}` | Review target normalized dependencies/evidence/proof digest |

Bracketed instructions such as `[State the question.]`, `pending`, and HTML comments require human or integrating-agent completion. The CLI must not invent research content merely to fill a field.

## Mapping

| Kind | Template | Destination behavior |
|---|---|---|
| `run` | [`run.md`](run.md) | Create `runs/RUN-####/RUN.md` and `tasks/` |
| `direction` | [`direction.md`](direction.md) | Append one level-two block to `research/DIRECTIONS.md` |
| `claim` | [`claim.md`](claim.md) | Create `research/claims/CLM-####.md` |
| `attempt` | [`attempt.md`](attempt.md) | Create `research/attempts/ATT-####.md` |
| `review` | [`review.md`](review.md) | Create `research/reviews/REV-####.md` |
| `literature` | [`literature.md`](literature.md) | Create `literature/notes/LIT-####.md` |
| `experiment` | [`experiment.md`](experiment.md) | Create `experiments/EXP-####/README.md` |
| execution completion | [`execution.md`](execution.md) | Create immutable `experiments/EXP-####/executions/EXP-####-E###/COMPLETED.md` after outputs are final |
| `inbox` | [`inbox.md`](inbox.md) | Append one level-two block to `research/INBOX.md` |
| `report` | [`report.md`](report.md) | Create `reports/RPT-####.md` |

[`search.md`](search.md) is the alternative `LIT` record created by
`python3 tools/research.py new literature --search`. [`task.md`](task.md),
[`output.md`](output.md), and [`receipt.md`](receipt.md) are copied into
run-local task directories and use run-local IDs rather than central
allocation. A review is created with `new review --claim CLM-####` so its
statement and evidence revisions/digests are bound before fresh verification begins.

Keep all fixed headings and bold labels. Explicitly write `none`, `pending`, `not applicable`, or `unknown` when a field has no substantive value yet.
