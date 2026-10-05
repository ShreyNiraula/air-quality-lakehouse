"""The skeleton does what task 0.1 promises: the package installs, and the commit hook lints."""

import os
import subprocess
from pathlib import Path

import airquality

REPO = Path(__file__).resolve().parents[1]


def git(repo, *args):
    """Run git in `repo` only. Inside a hook, git's own variables would point at this repository."""
    env = {name: value for name, value in os.environ.items() if not name.startswith("GIT_")}
    identity = ["-c", "user.name=test", "-c", "user.email=test@example.com"]
    return subprocess.run(
        ["git", *identity, "-c", "commit.gpgsign=false", *args],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
    )


def commit(repo, name, source):
    (repo / name).write_text(source)
    git(repo, "add", name)
    return git(repo, "commit", "-m", f"add {name}")


def test_package_is_installed_from_src():
    assert Path(airquality.__file__).resolve() == REPO / "src" / "airquality" / "__init__.py"


def test_commit_with_a_lint_error_is_refused(tmp_path):
    git(tmp_path, "init")
    git(tmp_path, "config", "core.hooksPath", str(REPO / ".githooks"))

    accepted = commit(tmp_path, "clean.py", 'print("ok")\n')
    assert accepted.returncode == 0, accepted.stdout + accepted.stderr

    refused = commit(tmp_path, "unused_import.py", "import os\n")
    assert refused.returncode != 0
    assert "F401" in refused.stdout + refused.stderr
    assert git(tmp_path, "rev-list", "--count", "HEAD").stdout.strip() == "1"
