---
description: Keep the roadmap moving - start the next task whenever the owner has merged, and answer their review comments
argument-hint: "[how many PRs may be open at once, default 3]"
---

One pass of the loop. The owner starts it with `/loop /autopilot` and then only reviews and merges on GitHub. Each pass looks at the state of the repository, does the one thing that is due, and ends.

Open PRs allowed at once: $ARGUMENTS (if empty, 3; never more than 3).

The rules in `CLAUDE.md` apply. Above all: never merge. The owner's merge is what moves the work forward.

## 1. Look

- `git switch main`, `git pull --ff-only`, then `python3 .github/scripts/sync_board.py`.
- `gh pr list --state open --json number,title,isDraft,mergeable,labels`. A PR whose `mergeable` is `CONFLICTING` conflicts with `main`.
- For each open PR that has the `ready-for-final-review` label, read what has been said on it since the handover: `gh pr view <pr> --json comments,reviews` and `gh api --paginate repos/{owner}/{repo}/pulls/<pr>/comments`. The owner and you post from the same account, so tell the two apart by the marker in `CLAUDE.md`: a comment that ends with `<!-- claude -->` is yours, and one without it, other than a bare `@codex review`, is the owner's. An owner's comment or thread reply with nothing of yours after it is unanswered.

## 2. Do the first of these that applies

1. **An open PR has comments from the owner that you have not answered.** Follow `/address-review` for that PR. End the pass.
2. **An open PR conflicts with `main`.** Resolve it as `/address-review` describes. End the pass.
3. **Every task in the roadmap is ticked.** Say so and stop the loop.
4. **Fewer PRs are open than allowed, and a task is ready.** Take the first ready task.
   - If it would be the first task of its milestone (no task of that milestone is ticked or has an open PR), the milestone is only now starting. Tell the owner the milestone before it is finished and what its "At the end you can show" says. Then follow `/plan-milestone` for the new milestone before any of its tasks is built. If the roadmap needs changes, they need the owner's agreement, so describe them and stop the loop. If it needs none, carry on.
   - Follow `/next-task` for the task, through to the handover. End the pass.
5. **Nothing is due.** Say in one line what is being waited for: the owner's review of a named PR, or a named owner item. End the pass.

## 3. Pace

When waiting on the owner, check again in about five minutes. Do not start a second piece of work in the same pass.

## When to stop the loop and ask

- A task is over the size limit and needs splitting.
- A task needs a design change or a decision that `plan.md` does not settle.
- The same step has failed twice in a row, such as CI that will not go green.
- A command needs a permission that is not granted.

In each case, say what happened and what you need from the owner.
