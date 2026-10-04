---
description: Answer the review comments on an open pull request, fixing what is right
argument-hint: "[PR number]"
---

Work through the review comments on a pull request. Use this after the owner has left comments in their own review.

Pull request: $ARGUMENTS (if empty, the one open PR; if there is more than one, ask which).

1. Check out the PR's branch and pull. Remove the label while you work, because the PR is no longer waiting on the owner: `gh pr edit <pr> --remove-label ready-for-final-review`.
2. If GitHub reports a conflict with `main`, which happens when a side-by-side task was merged first, merge `main` into the branch and resolve it. In `ROADMAP.md`, keep both ticks. Do not rebase: the branch is never force-pushed.
3. Read every comment that has no reply from you yet: `gh pr view <pr> --json reviews,comments` and `gh api --paginate repos/{owner}/{repo}/pulls/<pr>/comments`.
4. For each one, check it against the code and `plan.md`.
   - The owner's comments are decisions: make the change. If one conflicts with `plan.md` or would break something, say so in the thread and wait for their answer instead of guessing.
   - Codex's comments are input to verify: fix what is right, and explain what is not.
   - Reply in every thread with what you did or why not:
     `gh api repos/{owner}/{repo}/pulls/<pr>/comments/<comment id>/replies -f body="..."`
5. Run the linter, the tests and `.github/scripts/pr-size.sh`. If the PR is now over the size limit, tell the owner and propose moving part of it to a new task.
6. Commit, push, and wait for CI to be green with `gh pr checks <pr> --watch`.
7. If the fixes changed behaviour, and not only wording or naming, run one more Codex round as in step 5 of `/next-task`.
8. Post one PR comment listing what changed and what did not. Then put the label back, which emails the owner that it is their turn again: `gh pr edit <pr> --add-label ready-for-final-review`. Say the same in the terminal with the PR link. Stop. Do not merge.
