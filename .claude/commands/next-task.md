---
description: Take one ready task from code to a Codex-reviewed pull request handed to the owner
argument-hint: "[task id]"
---

Take one task through steps 1 to 4 in `CLAUDE.md`: code, draft pull request, Codex review, handover. The owner merges; you never do. The rules in `CLAUDE.md` apply throughout.

Task asked for: $ARGUMENTS (if empty, the first ready task in `ROADMAP.md`).

## 1. Check the starting point

- `git switch main` and `git pull --ff-only`. The working tree must be clean.
- `gh pr list --state open`. A PR title starts with its task id in square brackets, so this shows which tasks are in progress. If three are open, stop: the owner has reviews waiting.
- `python3 .github/scripts/sync_board.py`, so the issues match the roadmap on `main`.

## 2. Pick the task

Work out which tasks are ready, as `CLAUDE.md` defines it.

- If a task id was given and it is not ready, say what it is waiting for and stop.
- If nothing is ready because of an owner item, say which item and stop.
- If the milestone has no unticked task left, tell the owner it is finished and what its "At the end you can show" says. Then stop.

## 3. Build it

- Read the task's lines in `ROADMAP.md` and the parts of `plan.md` it touches.
- Create the branch `task/<task id>-<short-name>`, for example `task/0.2-lakehouse-check`.
- `python3 .github/scripts/sync_board.py --set <task id> "In progress"`.
- Write the code and its tests. Build what the task says and nothing that belongs to another task.
- Tick the task in `ROADMAP.md`: change `[ ]` to `[x]` on its line. Tick any owner item it relied on that the owner has completed.
- Run the linter and the tests locally.
- Run `.github/scripts/pr-size.sh`. If it reports over the limit, do not open the PR: propose how to split the task in two, with the roadmap changes that go with it, and stop for the owner's answer.

## 4. Open the pull request as a draft

- Commit, then `git push -u origin <branch>`.
- `gh pr create --draft`, titled `[<task id>] <task name>`, attached to the task's GitHub milestone, with no label. Fill in every section of `.github/pull_request_template.md`. End "What this does" with `Closes #<issue number>`, using the number from `python3 .github/scripts/sync_board.py --issue <task id>`, so that merging closes the issue. Write "Read the files in this order" for someone who has not seen the code.
- Wait for CI with `gh pr checks <pr> --watch` and fix failures until it is green.

## 5. Review rounds with Codex: aim for two, three at most

Each round:

1. Run `.claude/scripts/codex-review.sh <pr>` in the background. It asks for the review and returns when Codex has responded, usually within five minutes.
2. Act on how it ended:
   - **Thumbs-up:** Codex has nothing to report. Go to the handover.
   - **Review or comments:** if the only new comment says Codex found no major issues, that is also nothing to report. Otherwise read them with `gh pr view <pr> --json reviews,comments` and `gh api --paginate repos/{owner}/{repo}/pulls/<pr>/comments`.
   - **No response in time (exit 2):** run `codex review --base origin/main` locally and post its output as a PR comment headed "Codex review (run locally)". Treat its findings the same way.
3. For every finding, check it against the code and `plan.md`.
   - If it is right, fix it and add a test where one would have caught it. Look for the same mistake elsewhere in the PR and fix that too, so the next round does not find it.
   - If it is wrong, out of scope, or a matter of taste, do not change the code.
   - Either way, reply in the thread with what you did or why not:
     `gh api repos/{owner}/{repo}/pulls/<pr>/comments/<comment id>/replies -f body="..."`
4. Fix everything from the round in one push. Then wait for CI to be green, check the size again, and start the next round.

Stop the rounds when Codex reports nothing new, when a round ends with no code change, or after the third round. After the third round, hand over even if Codex still has points: list them for the owner.

## 6. Hand over to the owner

Do these in order. The label goes on last, because it is what emails the owner.

- `gh pr ready <pr>`
- `python3 .github/scripts/sync_board.py --set <task id> "Your review"`
- Post one comment covering, in plain language:
  - what to look at first, and the command to run;
  - what Codex raised in each round, and what was fixed;
  - what was not changed, and why;
  - anything Codex and you still disagree on, stated fairly for both sides, for the owner to decide.
- `gh pr edit <pr> --add-assignee @me --add-label ready-for-final-review`

Then say in the terminal that the PR is ready, with its link, and which tasks become ready once it is merged. Stop here.
