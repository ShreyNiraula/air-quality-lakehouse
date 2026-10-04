"""Tests for sync_board.py, run against a stand-in for GitHub.

  python3 .github/scripts/test_sync_board.py
"""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import sync_board  # noqa: E402

ROADMAP = """
## Milestone 0: Checks

- [ ] **Owner A: Get a key.**
  Register first.

- [ ] **0.1 Skeleton.** Layout and one test.
  Needs: nothing. Done when: tests pass.

- [ ] **0.2 Lakehouse check.** Start the catalog.
  Needs: 0.1. Done when: one command prints pass.

- [ ] **0.3 City list.** Print candidates.
  Needs: 0.1, Owner A. Done when: a table prints.

## Milestone 1: One source

- [ ] **1.1 Model PM2.5 contract.** The format.
  Needs: 0.2. Done when: tests load it.
"""


class FakeGitHub:
    """Answers the gh commands sync_board.py uses, and records the ones that change something."""

    def __init__(self):
        self.issues, self.labels_defined, self.writes = [], [], []

    def __call__(self, *args):
        if args[:2] == ("repo", "view"):
            return "owner/repo"
        if args[:2] == ("issue", "list"):
            return json.dumps(self.issues)
        if args[0] == "api":
            return json.dumps([{"title": "0: Checks"}, {"title": "1: One source"}])
        if args[:2] == ("label", "list"):
            return json.dumps(self.labels_defined)
        self.writes.append(args)
        if args[:2] == ("label", "create"):
            self.labels_defined = [label for label in self.labels_defined if label["name"] != args[2]]
            self.labels_defined.append({"name": args[2], "color": args[args.index("--color") + 1],
                                        "description": args[args.index("--description") + 1]})
            return ""
        if args[:2] == ("issue", "create"):
            number = len(self.issues) + 1
            labels = [{"name": args[i + 1]} for i, arg in enumerate(args) if arg == "--label"]
            self.issues.append({"number": number, "state": "OPEN", "labels": labels,
                                "title": args[args.index("--title") + 1], "body": args[args.index("--body") + 1]})
            return f"https://github.com/owner/repo/issues/{number}"
        issue = next(i for i in self.issues if str(i["number"]) == args[2])
        if args[:2] == ("issue", "edit"):
            for i, arg in enumerate(args):
                if arg == "--add-label":
                    issue["labels"].append({"name": args[i + 1]})
                if arg == "--remove-label":
                    issue["labels"] = [label for label in issue["labels"] if label["name"] != args[i + 1]]
        if args[:2] == ("issue", "close"):
            issue["state"] = "CLOSED"
        if args[:2] == ("issue", "reopen"):
            issue["state"] = "OPEN"
        return ""

    def issue(self, item_id):
        return next(i for i in self.issues if i["title"].startswith(f"[{item_id}]"))

    def labels(self, item_id):
        return sorted(label["name"] for label in self.issue(item_id)["labels"])


class SyncBoardTest(unittest.TestCase):
    def setUp(self):
        self.github = FakeGitHub()
        self.items = sync_board.parse_roadmap(ROADMAP)
        originals = (sync_board.gh, sync_board.time.sleep, sync_board.read_roadmap, sys.stdout)
        self.addCleanup(lambda: (setattr(sync_board, "gh", originals[0]), setattr(sync_board.time, "sleep", originals[1]),
                                 setattr(sync_board, "read_roadmap", originals[2]), setattr(sys, "stdout", originals[3])))
        sync_board.gh = self.github
        sync_board.time.sleep = lambda seconds: None
        sync_board.read_roadmap = lambda ref: self.items
        sys.stdout = open("/dev/null", "w")
        self.addCleanup(lambda: sys.stdout.close())

    def tick(self, item_id):
        next(i for i in self.items if i["id"] == item_id)["done"] = True

    def test_parse_reads_ids_names_needs_and_milestones(self):
        by_id = {i["id"]: i for i in self.items}
        self.assertEqual(list(by_id), ["Owner A", "0.1", "0.2", "0.3", "1.1"])
        self.assertEqual(by_id["1.1"]["name"], "Model PM2.5 contract")
        self.assertEqual(by_id["0.3"]["needs"], {"0.1", "Owner A"})
        self.assertEqual(by_id["0.1"]["needs"], set())
        self.assertEqual(by_id["1.1"]["milestone"], "1")

    def test_stage_follows_needs_and_the_current_milestone(self):
        stage = lambda item_id: sync_board.stage_from_roadmap(next(i for i in self.items if i["id"] == item_id), self.items)
        self.assertEqual([stage(i) for i in ("Owner A", "0.1", "0.2", "1.1")], ["Ready", "Ready", "Waiting", "Waiting"])
        self.tick("0.1")
        self.tick("0.2")
        self.assertEqual(stage("0.2"), "Done")
        self.assertEqual(stage("0.3"), "Waiting", "still needs Owner A")
        self.assertEqual(stage("1.1"), "Waiting", "its needs are met but milestone 0 is not finished")

    def test_first_sync_creates_every_issue_and_labels_the_ready_ones(self):
        sync_board.sync(self.items)
        self.assertEqual(sorted(label["name"] for label in self.github.labels_defined), ["in progress", "ready", "your review"])
        self.assertEqual(len(self.github.issues), 5)
        self.assertEqual(self.github.labels("0.1"), ["ready"])
        self.assertEqual(self.github.labels("0.2"), [])
        self.assertEqual(self.github.labels("Owner A"), ["owner", "ready"])

    def test_second_sync_changes_nothing(self):
        sync_board.sync(self.items)
        self.github.writes.clear()
        sync_board.sync(self.items)
        self.assertEqual(self.github.writes, [])

    def test_sync_repairs_a_stage_label_that_was_edited(self):
        sync_board.sync(self.items)
        next(label for label in self.github.labels_defined if label["name"] == "ready")["color"] = "000000"
        self.github.writes.clear()
        sync_board.sync(self.items)
        self.assertEqual([write[:3] for write in self.github.writes], [("label", "create", "ready")])

    def test_sync_leaves_a_task_that_is_in_progress(self):
        sync_board.sync(self.items)
        sync_board.main(["--set", "0.1", "In progress"])
        sync_board.sync(self.items)
        self.assertEqual(self.github.labels("0.1"), ["in progress"])

    def test_ticking_a_task_closes_it_and_readies_what_needed_it(self):
        sync_board.sync(self.items)
        sync_board.main(["--set", "0.1", "Your review"])
        self.tick("0.1")
        sync_board.sync(self.items)
        self.assertEqual(self.github.issue("0.1")["state"], "CLOSED")
        self.assertEqual(self.github.labels("0.1"), [])
        self.assertEqual(self.github.labels("0.2"), ["ready"])
        self.assertEqual(self.github.labels("0.3"), [], "still needs Owner A")

    def test_set_refuses_done_and_refuses_a_closed_issue(self):
        sync_board.sync(self.items)
        with self.assertRaises(SystemExit):
            sync_board.main(["--set", "0.1", "Done"])
        self.assertEqual(self.github.issue("0.1")["state"], "OPEN")
        self.tick("0.1")
        sync_board.sync(self.items)
        with self.assertRaises(SystemExit):
            sync_board.main(["--set", "0.1", "In progress"])
        self.assertEqual(self.github.labels("0.1"), [])

    def test_sync_reopens_an_issue_closed_without_its_task_being_ticked(self):
        sync_board.sync(self.items)
        self.github.issue("0.2")["state"] = "CLOSED"
        sync_board.sync(self.items)
        self.assertEqual(self.github.issue("0.2")["state"], "OPEN")


if __name__ == "__main__":
    unittest.main()
