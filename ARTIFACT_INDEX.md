# Artifact Index

This file is the authoritative allocator and registry for durable artifact
IDs. Counters store the last allocated integer. Allocation is monotonic within
each prefix; allocated IDs are never reused, even if work is abandoned.

Only the current integration authority or `tools/research.py new` should
modify this file.

## Allocation counters

| Prefix | Meaning | Last allocated |
|---|---|---:|
| RUN | Substantial research run | 0 |
| DIR | Research direction | 0 |
| CLM | Claim, theorem, counterexample, impossibility, or empirical proposition | 0 |
| ATT | Proof, derivation, search, or exploratory attempt | 0 |
| REV | Independent verification | 0 |
| LIT | Literature note or consequential search record | 0 |
| EXP | Experiment | 0 |
| INB | Deferred idea, question, blocker, or alignment item | 0 |
| RPT | Human milestone report | 0 |

## Artifact registry

| ID | Kind | Title | Status | Path | Created in | Superseded by |
|---|---|---|---|---|---|---|

<!-- Abandoned reservations remain as rows with Status `abandoned`. -->

