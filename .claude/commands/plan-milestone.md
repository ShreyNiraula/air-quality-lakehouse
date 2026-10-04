---
description: Re-check a milestone's tasks in ROADMAP.md before the milestone starts
argument-hint: "[milestone number]"
---

`ROADMAP.md` already lists every task. The tasks of later milestones were written before the earlier ones were built, so they are re-checked against what was learned before a milestone starts.

Milestone to check: $ARGUMENTS (if empty, the earliest milestone with unticked tasks).

1. **Read first.** In `plan.md`, read the stage this milestone covers in Part 1 and every rule in Part 2 that applies to it. Read the milestone's section of `ROADMAP.md`. Look at what is merged on `main`, including the recorded results of earlier checks.

2. **Look for what no longer fits.** For each task ask:
   - Does it still match the code and the check results? A check may have forced a fallback or dropped a source.
   - Will it fit the size rule in `CLAUDE.md` with room to spare, since review fixes add lines? If not, split it.
   - Is its "Needs" line still right, and could it need less, so more tasks can run side by side?
   - Is anything missing that the plan requires in this milestone?
   - Does it wait on something only the owner can do? That is an owner item.

3. **Show the changes and wait.** If nothing needs changing, say so and stop. Otherwise present the proposed changes in plain language: what changes, why, and the new order of work. Do not edit anything until the owner agrees. Removing or shrinking a task is a scope change and needs their explicit yes.

4. **Change the roadmap in a pull request.** On a branch `roadmap/milestone-<number>`, update the task lines, the "Needs" lines, the diagram and the "Order of work" line together, so they agree. A split task keeps its number with a letter, for example 1.6a and 1.6b, so other numbers do not move. Open the PR, assign it to the owner and add the label `ready-for-final-review`. A roadmap change has no code, so it skips the Codex review.

5. **Finish.** Tell the owner the PR is ready and stop. Do not start a task; the owner starts one with `/next-task` after merging.
