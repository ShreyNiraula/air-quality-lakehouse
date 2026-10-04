# Air-quality comparison platform

`plan.md` describes the project. Part 1 is what gets built and in what order. Part 2 holds the design rules the code must follow.

Changes arrive as small pull requests, one task each. `ROADMAP.md` lists the tasks and what each one covers. Every PR names its task and lists what it leaves out. Work listed under "Not in this PR", or that the roadmap gives to another task, is not a defect.

## Code Review Rules

Report only problems that would make a result wrong or the project untrustworthy:

- Code that produces a wrong value, drops or duplicates data, or fails on input the design rules call legitimate (short days, out-of-range readings, re-delivered files, DST days).
- Code that breaks a design rule in Part 2 of `plan.md`. Name the rule.
- Tests that cannot fail, or that do not test what their name says.
- Secrets, API keys or tokens in the diff, and anything taken from a non-public source.
- A claim in the README or PR description that no check in the repository proves.
- A change that goes beyond the task the PR names.

Do not report:

- Naming, formatting, import order, comment wording or docstring style. The linter covers these.
- Alternative designs that are equally correct.
- Missing features that the PR lists under "Not in this PR".
- Performance, unless the code would be unusable at the data sizes in `plan.md`.

For each problem, say what input or situation triggers it and what goes wrong. If there is nothing to report, say so.

Report everything you find in one review. A pull request gets at most three review rounds, so a problem held back for a later round may never be raised.
