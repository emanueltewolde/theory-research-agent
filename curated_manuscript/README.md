# Curated manuscript setup

This is the selective, venue-facing paper, worked on when the user requests
writing. Research can begin without it.

Before the first writing task:

1. Download the intended conference or journal's official LaTeX template and
   copy its files here, preserving styles, licenses, and required metadata.
2. Expose the build entry point as `main.tex` (rename the sample entry point or
   use a minimal wrapper if the venue permits), and verify that the otherwise
   untouched template compiles. Select that main document in Overleaf.
3. Fill [WRITING_ORIENTATION.md](WRITING_ORIENTATION.md), especially the story,
   central contributions, selection policy, and any protected sections.
4. Request a bounded writing task, using the
   [general writing guide](../docs/MANUSCRIPT_WRITING.md). A separate writing
   session or the optional writer subagent can do it.

Keep this directory self-contained: include its TeX inputs, bibliography,
figures, and style files. GitHub/Overleaf connection is optional and managed
only by the human; see the [main README](../README.md#human-owned-overleaf-sync).
When replacing the venue template, compile before resuming writing.

[PROVENANCE.md](PROVENANCE.md) records source support and the scope of the last
refresh. This paper may deliberately omit results and lag behind research.
