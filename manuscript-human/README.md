# Human-directed manuscript setup

This directory is reserved for the polished, venue-facing manuscript. It is
deliberately not initialized with a generic LaTeX article: the human should
first copy the official TeX template for the intended conference or journal
into this directory, preserving its class, bibliography style, sample source,
and license or attribution files.

Before authorizing an agent to edit this manuscript:

1. obtain the template from the venue's official source;
2. copy the template files into this directory;
3. expose the template's build entry point as `main.tex` (rename the sample
   entry point without otherwise editing it, or add a minimal `main.tex`
   wrapper if the venue permits one), choose it as Overleaf's main document,
   and verify that the untouched template compiles;
4. make the directory self-contained, including bibliography, figures, style
   files, and other local inputs;
5. connect only the manuscript-only GitHub repository to Overleaf; and
6. explicitly tell a separate writing session which manuscript changes it may
   make.

Ordinary research and proof sessions should not load or edit this directory.
Research agents never run Git or synchronize Overleaf. A human or trusted
external automation imports and exports this directory. Keep
[`PROVENANCE.md`](PROVENANCE.md) synchronized with established theorem-like,
figure, and table labels after substantive content is added.

When the venue template is replaced or upgraded, compile it before resuming
agent writing and record the change in the writing task's report.
