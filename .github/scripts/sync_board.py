#!/usr/bin/env python3
"""Keep the GitHub issues in step with ROADMAP.md, so the project board can show them.

  sync_board.py                          one issue per roadmap item, each with the right stage
  sync_board.py --ref HEAD               read the roadmap from another git ref (default: origin/main)
  sync_board.py --dry-run                print each item's stage without touching GitHub
  sync_board.py --set 0.2 "In progress"  set one open item's stage (any stage except Done)
  sync_board.py --issue 0.2              print one item's issue number

The roadmap is the source of truth. A stage is shown as a label on the issue:
Waiting has no label, Done is a closed issue. The script only touches issues in
this repository; the board itself adds new issues and moves closed ones to Done.
A sync never takes an item out of "In progress" or "Your review" unless its task is ticked.
"""
import json
import re
import subprocess
import sys
import time

# Stage -> (label, colour, description). Waiting and Done have no label.
STAGES = {
    "Waiting": None,
    "Ready": ("ready", "1D76DB", "Everything this task needs is merged"),
    "In progress": ("in progress", "FBCA04", "Being built"),
    "Your review": ("your review", "D93F0B", "Waiting for the owner's review and merge"),
    "Done": None,
}
HELD = ("In progress", "Your review")
ITEM = re.compile(r"- \[([ x])\] \*\*(\d\.\d+[a-z]?|Owner [A-Z]):? (.+?)\.?\*\*\s*(.*)")


def gh(*args):
    result = subprocess.run(["gh", *args], capture_output=True, text=True)
    if result.returncode:
        sys.exit(f"gh {' '.join(args[:3])} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def gh_json(*args):
    return json.loads(gh(*args) or "null")


def read_roadmap(ref):
    shown = subprocess.run(["git", "show", f"{ref}:ROADMAP.md"], capture_output=True, text=True)
    if shown.returncode:
        sys.exit(f"No ROADMAP.md at {ref}: {shown.stderr.strip()}")
    return parse_roadmap(shown.stdout)


def parse_roadmap(text):
    lines = text.split("\n")
    items, milestone = [], None
    for i, line in enumerate(lines):
        heading = re.match(r"## Milestone (\d+):", line)
        if heading:
            milestone = heading.group(1)
            continue
        found = ITEM.match(line)
        if not found:
            continue
        detail = lines[i + 1].strip()
        needs = detail.split("Needs:")[1].split("Done when")[0] if "Needs:" in detail else ""
        items.append({
            "id": found.group(2), "name": found.group(3), "text": found.group(4), "detail": detail,
            "done": found.group(1) == "x", "milestone": milestone,
            "needs": set(re.findall(r"\d\.\d+[a-z]?|Owner [A-Z]", needs)),
        })
    return items


def is_owner(item):
    return item["id"].startswith("Owner")


def stage_from_roadmap(item, items):
    """Done if ticked; Ready if everything it needs is ticked and its milestone has started; else Waiting."""
    if item["done"]:
        return "Done"
    ticked = {i["id"] for i in items if i["done"]}
    open_milestones = [i["milestone"] for i in items if not i["done"] and not is_owner(i)]
    started = is_owner(item) or item["milestone"] == min(open_milestones, key=int)
    return "Ready" if item["needs"] <= ticked and started else "Waiting"


def title_of(item):
    return f"[{item['id']}] {item['name']}"


def body_of(item, repo):
    parts = [item["text"], item["detail"],
             f"Milestone {item['milestone']} in [ROADMAP.md](https://github.com/{repo}/blob/main/ROADMAP.md). "
             "The roadmap is the source of truth; this issue is its card on the project board."]
    return "\n\n".join(p for p in parts if p)


def load_issues():
    """Roadmap id -> issue, for every issue whose title starts with an id in square brackets."""
    issues = {}
    for issue in gh_json("issue", "list", "--state", "all", "--limit", "500", "--json", "number,title,state,body,labels"):
        tagged = re.match(r"\[(.+?)\]", issue["title"])
        if tagged:
            issue["labels"] = {label["name"] for label in issue["labels"]}
            issues[tagged.group(1)] = issue
    return issues


def stage_of(issue):
    for stage, label in STAGES.items():
        if label and label[0] in issue["labels"]:
            return stage
    return "Waiting"


def set_stage(issue, to):
    """Swap the issue's stage label. Returns True if anything changed. It does not open or close the issue."""
    stage_labels = {label[0] for label in STAGES.values() if label}
    wanted = {STAGES[to][0]} if STAGES[to] else set()
    remove, add = (issue["labels"] & stage_labels) - wanted, wanted - issue["labels"]
    if not remove and not add:
        return False
    args = ["issue", "edit", str(issue["number"])]
    for label in sorted(remove):
        args += ["--remove-label", label]
    for label in sorted(add):
        args += ["--add-label", label]
    gh(*args)
    issue["labels"] = (issue["labels"] - remove) | add
    return True


def sync(items):
    repo = gh("repo", "view", "--json", "nameWithOwner", "--jq", ".nameWithOwner")
    labels = {label["name"]: label for label in gh_json("label", "list", "--limit", "200", "--json", "name,color,description")}
    for name, colour, description in filter(None, STAGES.values()):
        have = labels.get(name)
        if not have or have["color"].lower() != colour.lower() or have["description"] != description:
            gh("label", "create", name, "--color", colour, "--description", description, "--force")
    milestones = {m["title"].split(":")[0]: m["title"] for m in gh_json("api", f"repos/{repo}/milestones?state=all")}
    issues = load_issues()
    created = edited = moved = 0
    for item in items:
        title, body = title_of(item), body_of(item, repo)
        issue = issues.get(item["id"])
        if not issue:
            args = ["issue", "create", "--title", title, "--body", body, "--milestone", milestones[item["milestone"]]]
            url = gh(*args, *(["--label", "owner"] if is_owner(item) else []))
            issue = {"number": int(url.rsplit("/", 1)[1]), "state": "OPEN", "labels": set()}
            created += 1
            time.sleep(1)  # stay under GitHub's limit on how fast content may be created
        elif issue["title"] != title or issue["body"].replace("\r", "").strip() != body:
            gh("issue", "edit", str(issue["number"]), "--title", title, "--body", body)
            edited += 1
        want = stage_from_roadmap(item, items)
        if want == "Done" and issue["state"] == "OPEN":
            gh("issue", "close", str(issue["number"]))
            issue["state"] = "CLOSED"
        elif want != "Done" and issue["state"] != "OPEN":
            gh("issue", "reopen", str(issue["number"]))
            issue["state"] = "OPEN"
        if stage_of(issue) in HELD and want != "Done":
            continue
        moved += set_stage(issue, want)
    print(f"{len(items)} roadmap items: {created} issues created, {edited} updated, {moved} stages changed.")


def main(argv):
    ref = argv[argv.index("--ref") + 1] if "--ref" in argv else "origin/main"
    if "--set" in argv:
        at = argv.index("--set")
        item_id, to = argv[at + 1], argv[at + 2]
        if to not in STAGES:
            sys.exit(f"Unknown stage {to!r}. Stages: {', '.join(STAGES)}")
        if to == "Done":
            sys.exit("Done cannot be set by hand: tick the task in ROADMAP.md, and the sync after the merge closes its issue.")
        issues = load_issues()
        if item_id not in issues:
            sys.exit(f"No issue for {item_id}. Run a sync first.")
        if issues[item_id]["state"] != "OPEN":
            sys.exit(f"The issue for {item_id} is closed, so it has no stage to set.")
        set_stage(issues[item_id], to)
        print(f"{item_id}: {to}")
    elif "--issue" in argv:
        item_id = argv[argv.index("--issue") + 1]
        issues = load_issues()
        if item_id not in issues:
            sys.exit(f"No issue for {item_id}. Run a sync first.")
        print(issues[item_id]["number"])
    else:
        items = read_roadmap(ref)
        if "--dry-run" in argv:
            for item in items:
                print(f"{stage_from_roadmap(item, items):8}  {title_of(item)}")
        else:
            sync(items)


if __name__ == "__main__":
    main(sys.argv[1:])
