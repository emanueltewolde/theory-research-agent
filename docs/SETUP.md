# Start and maintain a research project

This guide is for setup and occasional updates, not routine research. All Git
commands below are for the human's own terminal, never for an agent to execute.

## Create a project with an update path

Preserve the template's Git history if you want to merge future improvements.
Choose according to the privacy of your research:

- **Public project:** fork the public template on GitHub, then clone your fork.
- **Private project, or unable to fork:** clone the template and connect the
  clone to a new, independent private repository. This retains shared ancestry
  without being a GitHub fork. Public-repository forks are public;
  [GitHub documents the visibility rules](https://docs.github.com/en/pull-requests/reference/forks).

In the commands below, replace `TEMPLATE_OWNER/TEMPLATE_REPO` with the public
template's location and `YOUR_ACCOUNT/YOUR_PROJECT` with your destination.
Use your usual SSH URLs instead if preferred. Commands assume the template's
default branch is `main` and the local folder `my-research` does not yet exist.

### Public fork

Create the fork on GitHub, then run:

```sh
git clone https://github.com/YOUR_ACCOUNT/YOUR_PROJECT.git my-research
cd my-research
git remote add upstream https://github.com/TEMPLATE_OWNER/TEMPLATE_REPO.git
git switch -c research
git push -u origin research
```

### Independent private repository

Create an **empty private repository** on GitHub first: do not initialize it
with a README, license, or ignore file. Then run:

```sh
git clone https://github.com/TEMPLATE_OWNER/TEMPLATE_REPO.git my-research
cd my-research
git remote rename origin upstream
git remote add origin https://github.com/YOUR_ACCOUNT/YOUR_PROJECT.git
git push -u origin main
git switch -c research
git push -u origin research
```

In either route, `origin` is your project and `upstream` is the template.
Keep `main` as the uncustomized template version you have adopted; initialize
and do research on `research`. Push research only to your own `origin`.
An agent must work in this local checkout, not create a worktree.

GitHub's **Use this template** button or a downloaded copy is also fine for an
independent snapshot, but it does not preserve the upstream history for this
merge workflow. It is not the recommended route when future merges matter.

## Initialize the project together

Follow the [README prerequisites and runtime activation](../README.md#quick-start)
first. In your new project, give the agent this prompt:

> Help me set up this research project; do not begin research yet. Read
> `AGENTS.md`, `STATE.md`, `PROJECT.md`, and the initialization checklist in
> `docs/SETUP.md`. If this is already an initialized project, stop and ask what
> I want to revise instead of resetting anything. Ask a few high-value questions
> at a time to clarify my objective, whether it is definite or exploratory,
> the model and assumptions, success criteria (including disproof), available
> background, privacy constraints, and budget for focused agents. Offer options
> where useful, and record unresolved choices with safe provisional scope.
> Draft `PROJECT.md` with me, but keep it unaccepted until I explicitly approve
> the proposed contract. After approval, prepare the initial overview and control
> records using the checklist below, update `STATE.md` last, and run validation.
> Summarize what I approved, what remains unresolved, and the first proposed
> research action. Do not run Git, install anything, edit runtime configuration,
> or launch research tasks. Wait for my request to start research.

The human chooses the objective and acceptable assumptions; the agent can do
the drafting and bookkeeping. An exploratory project need not prejudge its
answer, but its permitted scope and uncertainty boundaries must be explicit.
Questions already answered by the human need not be asked again.

### Initialization checklist

1. Run `python3 tools/research.py init` from the project root. It only creates
   missing scaffold structure; it does not accept a contract or erase work.
2. Draft all `PROJECT.md` sections. Use concrete values or `None.` where
   appropriate, not bracketed prompts. Record consequential uncertainties,
   provisional assumptions, and safe continuation horizons. Agree on the
   focused-agent cost envelope and check the available runtime profiles.
3. After explicit human approval, set `Contract status` to `accepted`,
   `Contract revision` to `1`, and `Revision date` to the actual approval date.
   Append a revision-1 row recording that human decision in the revision log;
   keep the revision-0 row.
4. Set `Contract revision` to `1` in `research/DIRECTIONS.md` and
   `research/INBOX.md`. Leave their empty registries and `ARTIFACT_INDEX.md`
   intact; setup must not fabricate research results or completed runs.
5. Initialize `OVERVIEW.md`: set `Overview status` to `current`, both covered
   revisions to `1`, and `Last refreshed` to today's date. Summarize the approved
   objective and real remaining decisions, while explicitly noting that research
   has not begun. Keep a concrete `Next refresh trigger`. The status
   `initial blank template` is not valid once the contract is accepted.
6. Update `STATE.md` last: set state and contract revisions to `1`, retain
   `clean` integration and `none` for active/last integrated runs, and replace
   initialization prose with the accepted objective, current questions, empty
   results/portfolio/in-flight work, useful alternatives, and a concrete first
   research action. Record meaningful strategic-review and overview-refresh
   triggers. No result should be called validated before it exists and is reviewed.
7. Run `python3 tools/research.py check` and `doctor --runtime codex` or
   `doctor --runtime claude` through the same script. Resolve errors and explain
   remaining warnings; do not rewrite the scientific contract to satisfy a check.
   Report any runtime change needed for the human to make outside the agent.

The human can then checkpoint the setup. Begin research only when asked, for
example with “Continue the research.” The curated manuscript can remain unset.

## Adopt framework updates when you choose

Pause agents, checkpoint your work, and start with a clean working tree.
Read upstream release notes and inspect the incoming changes yourself before
merging. These commands assume the branch layout above and that `main` has no
project-specific commits:

```sh
git fetch upstream
git switch main
git merge --ff-only upstream/main
```

If the fast-forward fails, stop and inspect the divergence; do not reset or
force-push to make it fit. Run the [full template checks](../CONTRIBUTING.md#checks)
here on the still-blank `main` branch. Once they pass, continue:

```sh
git push origin main
git switch research
git merge --no-commit --no-ff main
```

This updates **remote `origin/main` too**, then stages adoption on `research`
for your review. Resolve any merge conflicts before running checks. If there
were no new changes, there is nothing to commit.

Review even a conflict-free merge: preserve the project's contract, state,
evidence, manuscript content, and approved local runtime settings. Template
changes to populated records need deliberate adaptation, not wholesale
replacement. Retain historical adapter mappings needed by existing receipts.
Now run `check`, both adapter checks, and your runtime's `doctor` on the
populated research branch. The full test suite belongs on the blank template
branch, not your live research records. Re-review changed hooks and confirm
runtime behavior before resuming agents.

When satisfied, the human completes the pending merge and publishes it:

```sh
git commit
git push origin research
```

To decline a pending merge, the human may use `git merge --abort` before
committing. Do not begin unrelated edits while that merge is pending. No
automatic framework updater runs in research sessions.
