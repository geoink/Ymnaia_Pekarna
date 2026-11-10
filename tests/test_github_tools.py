import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load_script(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


tasks_module = load_script("github_tasks")
publisher = load_script("publish_github")
release_module = load_script("release_presentation")


def test_backlog_is_complete_and_topologically_ordered():
    tasks = tasks_module.load_tasks()
    assert len(tasks) == 18
    assert sum(t["estimate_person_days"] for t in tasks) == 50
    for task in tasks:
        assert task["acceptance"] and task["artifacts"]
        assert task["status"] == "proposed"


def test_issue_preview_does_not_call_github(monkeypatch, capsys):
    def forbidden(*args, **kwargs):
        pytest.fail("Preview must not call GitHub")
    monkeypatch.setattr(tasks_module, "run", forbidden)
    tasks_module.import_tasks("owner/bakery")
    assert "18 proposed tasks" in capsys.readouterr().out


def test_closed_issues_are_kept_and_new_issues_link_dependencies(tmp_path, monkeypatch):
    folder = tmp_path / "docs/ml_team"
    (folder / "tasks").mkdir(parents=True)
    tasks = [{"id": "ML-001", "title": "One", "priority": "P0", "release": "R1", "depends_on": []},
             {"id": "ML-002", "title": "Two", "priority": "P1", "release": "R2", "depends_on": ["ML-001"]}]
    (folder / "tasks.json").write_text(json.dumps(tasks))
    for task in tasks:
        (folder / "tasks" / f"{task['id']}.md").write_text("First line\nSecond line\n")
    calls, bodies = [], []

    def fake_run(*args, **kwargs):
        calls.append(args)
        if args[1:3] == ("api", "repos/owner/bakery/issues?state=all&per_page=100"):
            return json.dumps([[{"body": "<!-- bakery-task:ML-001 -->", "state": "closed",
                                 "html_url": "https://github.com/owner/bakery/issues/7"}]])
        if args[1:3] == ("api", "repos/owner/bakery/labels?per_page=100"):
            return "ml-task\npriority:P0\npriority:P1\nrelease:R1\nrelease:R2"
        if args[1:3] == ("issue", "create"):
            bodies.append(Path(args[args.index("--body-file") + 1]).read_text())
            return "https://github.com/owner/bakery/issues/8"
        pytest.fail(f"Unexpected command: {args}")

    monkeypatch.setattr(tasks_module, "run", fake_run)
    tasks_module.import_tasks("owner/bakery", apply=True, root=tmp_path)
    assert len(bodies) == 1
    assert "First line\nSecond line" in bodies[0]
    assert "<!-- bakery-task:ML-002 -->" in bodies[0]
    assert "https://github.com/owner/bakery/issues/7" in bodies[0]
    assert "[ML-002] Two" in calls[-1]


@pytest.mark.parametrize("existing", [False, True])
def test_publisher_uses_local_git_and_only_delivery_files(tmp_path, monkeypatch, existing):
    (tmp_path / "README.md").write_text("Delivery")
    (tmp_path / "private.csv").write_text("must not be staged")
    (tmp_path / "MANIFEST.sha256").write_text("unused-hash  README.md\n")
    monkeypatch.setattr(publisher, "ROOT", tmp_path)
    monkeypatch.setattr(publisher, "delivery_files", lambda: ["README.md", "MANIFEST.sha256"])
    monkeypatch.setattr(publisher.shutil, "which", lambda name: "/fake/" + name)
    original_subprocess = subprocess.run
    gh_calls, pushes = [], []

    def fake_subprocess(args, **kwargs):
        if args[0] == "gh":
            # Simulate a repository that does not exist yet.
            return subprocess.CompletedProcess(args, 1, "", "not found")
        return original_subprocess(args, **kwargs)

    def run_with_fake_github(*args, **kwargs):
        if args[0] == "gh":
            gh_calls.append(args)
            if args[1:3] == ("repo", "view"):
                return json.dumps({"isEmpty": True, "isPrivate": False})
            return json.dumps({"login": "student", "id": 123}) if args[1:3] == ("api", "user") else ""
        if args[:2] == ("git", "push"):
            pushes.append(args)
            return ""  # No live network in tests.
        return original_subprocess(args, cwd=tmp_path, check=True, text=True, capture_output=True).stdout.strip()

    monkeypatch.setattr(publisher.subprocess, "run", fake_subprocess)
    monkeypatch.setattr(publisher, "run", run_with_fake_github)
    publisher.publish("bakery", "public", use_existing=existing)
    tracked = run_with_fake_github("git", "ls-files").splitlines()
    assert tracked == ["MANIFEST.sha256", "README.md"]
    assert run_with_fake_github("git", "branch", "--show-current") == "main"
    creates = [call for call in gh_calls if call[:3] == ("gh", "repo", "create")]
    if existing:
        assert not creates
        assert pushes == [("git", "push", "-u", "origin", "main")]
        assert run_with_fake_github("git", "remote", "get-url", "origin") == "https://github.com/student/bakery.git"
    else:
        assert creates[0][3] == "student/bakery"
        assert "--push" in creates[0]


def test_unlinked_nonempty_repository_is_not_overwritten(tmp_path, monkeypatch):
    monkeypatch.setattr(publisher, "ROOT", tmp_path)
    monkeypatch.setattr(publisher, "delivery_files", lambda: [])
    monkeypatch.setattr(publisher.shutil, "which", lambda _: "/fake")
    commands = {
        ("gh", "auth", "status", "--hostname", "github.com"): "",
        ("gh", "api", "user"): '{"login":"student","id":123}',
        ("git", "init", "-b", "main"): "",
        ("git", "rev-parse", "--show-toplevel"): str(tmp_path),
        ("git", "branch", "--show-current"): "main",
        ("git", "remote"): "",
        ("gh", "repo", "view", "student/bakery", "--json", "isEmpty,isPrivate"): '{"isEmpty":false,"isPrivate":false}',
    }
    monkeypatch.setattr(publisher, "run", lambda *args: commands[args])
    with pytest.raises(ValueError, match="contains commits"):
        publisher.publish("bakery", "public", use_existing=True)


def test_decoration_sets_only_description_topics_and_issues(monkeypatch):
    calls = []
    monkeypatch.setattr(publisher, "run", lambda *args: calls.append(args))
    publisher.decorate_repository("geoink/Ymnaia_Pekarna")
    command = calls[0]
    assert command[:4] == ("gh", "repo", "edit", "geoink/Ymnaia_Pekarna")
    assert "--description" in command and "--enable-issues" in command
    assert command.count("--add-topic") == 9
    assert "--visibility" not in command


def test_publisher_rejects_mismatched_origin_before_staging(tmp_path, monkeypatch):
    (tmp_path / ".git").mkdir()
    monkeypatch.setattr(publisher, "ROOT", tmp_path)
    monkeypatch.setattr(publisher, "delivery_files", lambda: [])
    monkeypatch.setattr(publisher.shutil, "which", lambda _: "/fake")
    commands = {
        ("gh", "auth", "status", "--hostname", "github.com"): "",
        ("gh", "api", "user"): '{"login":"student","id":123}',
        ("git", "rev-parse", "--show-toplevel"): str(tmp_path),
        ("git", "branch", "--show-current"): "main",
        ("git", "remote"): "origin",
        ("git", "remote", "get-url", "origin"): "https://github.com/another/unrelated.git",
    }
    monkeypatch.setattr(publisher, "run", lambda *args: commands[args])
    with pytest.raises(ValueError, match="origin does not match"):
        publisher.publish("bakery", "public")


@pytest.mark.parametrize("repo", ["--evil", "owner/name;cmd", "owner/../name", "owner/name/extra"])
def test_invalid_issue_repository_is_rejected(repo):
    with pytest.raises(ValueError, match="OWNER/NAME"):
        tasks_module.import_tasks(repo)


def test_manifest_cannot_escape_delivery(tmp_path):
    (tmp_path / "MANIFEST.sha256").write_text("hash  ../other.txt\n")
    with pytest.raises(ValueError, match="Unsafe delivery path"):
        publisher.delivery_files(tmp_path)


def release_fixture(tmp_path, monkeypatch):
    monkeypatch.setattr(release_module, "ROOT", tmp_path)
    for name in release_module.ASSETS + [release_module.NOTES]:
        p = tmp_path / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("release content", encoding="utf-8")


def test_release_preview_is_offline(tmp_path, monkeypatch, capsys):
    release_fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(release_module, "run", lambda *args: pytest.fail("Preview called a command"))
    release_module.publish_release("owner/bakery")
    assert "presentation.pptx" in capsys.readouterr().out


def test_release_refuses_unpushed_commit(tmp_path, monkeypatch):
    release_fixture(tmp_path, monkeypatch)
    def fake_run(*args):
        if args[:3] == ("git", "rev-parse", "HEAD"):
            return "local-sha"
        if args[0] == "gh":
            return "different-remote-sha"
        return ""
    monkeypatch.setattr(release_module, "run", fake_run)
    with pytest.raises(ValueError, match="differs from GitHub"):
        release_module.publish_release("owner/bakery", apply=True)


@pytest.mark.parametrize("already_exists", [False, True])
def test_release_creates_or_completes_assets_without_overwriting(tmp_path, monkeypatch, already_exists):
    release_fixture(tmp_path, monkeypatch)
    calls = []
    first_asset = {"name": "presentation.pptx", "size": (tmp_path / release_module.ASSETS[0]).stat().st_size}
    existing = {"url": "https://github.com/owner/bakery/releases/tag/coursework-v2", "assets": [first_asset]}
    def fake_subprocess(args, **kwargs):
        return subprocess.CompletedProcess(args, 0 if already_exists else 1, json.dumps(existing), "")
    def fake_run(*args):
        calls.append(args)
        if args[:3] == ("git", "rev-parse", "HEAD") or args[:2] == ("gh", "api"):
            return "same-sha"
        if args[:3] == ("gh", "release", "view"):
            return json.dumps({"url": existing["url"], "assets": [
                {"name": (tmp_path / x).name, "size": (tmp_path / x).stat().st_size}
                for x in release_module.ASSETS]})
        return ""
    monkeypatch.setattr(release_module.subprocess, "run", fake_subprocess)
    monkeypatch.setattr(release_module, "run", fake_run)
    release_module.publish_release("owner/bakery", apply=True)
    mutations = [c for c in calls if c[:3] in [("gh", "release", "create"), ("gh", "release", "upload")]]
    assert len(mutations) == 1
    assert "--clobber" not in mutations[0]
    if already_exists:
        assert mutations[0][2] == "upload"
        assert str(tmp_path / "docs/presentation.pptx") not in mutations[0]
    else:
        assert mutations[0][2] == "create"
        assert mutations[0][mutations[0].index("--target") + 1] == "same-sha"
