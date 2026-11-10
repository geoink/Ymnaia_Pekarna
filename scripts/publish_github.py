#!/usr/bin/env python3
"""Publish this delivery to GitHub; requires git and authenticated gh."""

import argparse
import json
from pathlib import Path
import re
import shutil
import subprocess

from github_tasks import ROOT, import_tasks, run


def delivery_files(root=ROOT):
    paths = []
    for line in (root / "MANIFEST.sha256").read_text(encoding="utf-8").splitlines():
        _, name = line.split("  ", 1)
        path = Path(name)
        if path.is_absolute() or ".." in path.parts or (root / path).resolve().is_relative_to(root) is False:
            raise ValueError(f"Unsafe delivery path: {name}")
        if not (root / path).is_file():
            raise ValueError(f"Missing delivery file: {name}")
        paths.append(name)
    return paths + ["MANIFEST.sha256"]


def decorate_repository(repo):
    metadata = json.loads((ROOT / "docs/github_metadata.json").read_text(encoding="utf-8"))
    args = ["gh", "repo", "edit", repo, "--description", metadata["description"], "--enable-issues"]
    for topic in metadata["topics"]:
        args.extend(["--add-topic", topic])
    run(*args)
    print("Updated repository description and topics.")


def publish(repo, visibility, with_issues=False, dry_run=False, use_existing=False, decorate=False, presentation_release=False):
    if not re.fullmatch(r"[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)?", repo) or any(
        part in {".", ".."} for part in repo.split("/")
    ):
        raise ValueError("Use repository name or OWNER/NAME")
    paths = delivery_files()
    if dry_run:
        print(f"Preview: {len(paths)} delivery files → {repo} ({visibility}).")
        action = "connect existing repository" if use_existing else "create GitHub repository"
        print(f"Would initialize local main, commit delivery, {action} and push.")
        print("Only MANIFEST-listed files are staged; raw data and local models are excluded.")
        if decorate:
            print("Would update the About description and topics from docs/github_metadata.json.")
        if with_issues:
            import_tasks(repo if "/" in repo else f"AUTHENTICATED_USER/{repo}")
        if presentation_release:
            from release_presentation import publish_release
            publish_release(repo if "/" in repo else f"AUTHENTICATED_USER/{repo}")
        return
    for executable in ("git", "gh"):
        if not shutil.which(executable):
            raise ValueError(f"Missing {executable}. See docs/github_publish.md")
    run("gh", "auth", "status", "--hostname", "github.com")
    user = json.loads(run("gh", "api", "user"))
    full_repo = repo if "/" in repo else f"{user['login']}/{repo}"
    target_url = f"https://github.com/{full_repo}.git"
    # Never commit into an inherited parent repository.
    if not (ROOT / ".git").exists():
        run("git", "init", "-b", "main")
    if Path(run("git", "rev-parse", "--show-toplevel")).resolve() != ROOT:
        raise ValueError("Git root differs from this delivery directory")
    if run("git", "branch", "--show-current") != "main":
        raise ValueError("Expected branch main; switch explicitly before publishing")
    remotes = run("git", "remote").splitlines()
    exists = "origin" in remotes
    if exists:
        origin = run("git", "remote", "get-url", "origin")
        expected = {target_url, target_url.removesuffix(".git"), f"git@github.com:{full_repo}.git"}
        if origin not in expected:
            raise ValueError(f"origin does not match {full_repo}; no remote was changed")
        visibility_now = json.loads(run("gh", "repo", "view", full_repo, "--json", "isPrivate"))["isPrivate"]
        if visibility_now != (visibility == "private"):
            raise ValueError("Existing repository visibility differs; change it manually if intended")
    elif use_existing:
        # An empty remote can be connected without rewriting or merging history.
        info = json.loads(run("gh", "repo", "view", full_repo, "--json", "isEmpty,isPrivate"))
        if info["isPrivate"] != (visibility == "private"):
            raise ValueError("Existing repository visibility differs; no visibility was changed")
        if not info["isEmpty"]:
            raise ValueError("Existing repository contains commits. Clone it and integrate the delivery first; see docs/github_publish.md")
        run("git", "remote", "add", "origin", target_url)
        exists = True
    else:
        # A pre-existing remote repository needs an explicit manual clone/integration.
        check = subprocess.run(["gh", "repo", "view", full_repo, "--json", "name"],
                               cwd=ROOT, text=True, capture_output=True)
        if check.returncode == 0:
            raise ValueError(f"{full_repo} already exists. See the existing-repository instructions")
    # Do not include unrelated files the user may already have staged.
    staged = set(run("git", "diff", "--cached", "--name-only").splitlines())
    if staged - set(paths):
        raise ValueError("Unrelated staged files found; review them before publishing")
    for key, value in (("user.name", user["login"]),
                       ("user.email", f"{user['id']}+{user['login']}@users.noreply.github.com")):
        current = subprocess.run(["git", "config", "--get", key], cwd=ROOT, capture_output=True, text=True)
        if current.returncode != 0 or not current.stdout.strip():
            run("git", "config", "--local", key, value)
    run("git", "add", "--", *paths)
    if run("git", "diff", "--cached", "--name-only"):
        message = ("Update coursework presentation and defense materials" if presentation_release
                   else "Add bakery forecasting research and ML delivery plan")
        run("git", "commit", "-m", message)
    if exists:
        run("git", "push", "-u", "origin", "main")
    else:
        run("gh", "repo", "create", full_repo, f"--{visibility}", "--source", str(ROOT),
            "--remote", "origin", "--push", "--description", "Bakery sales forecasting: coursework, research and ML backlog")
    print(f"Published: https://github.com/{full_repo}")
    if decorate:
        decorate_repository(full_repo)
    if with_issues:
        import_tasks(full_repo, apply=True)
    if presentation_release:
        from release_presentation import publish_release
        publish_release(full_repo, apply=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default="bakery-forecast")
    visibility = parser.add_mutually_exclusive_group(required=True)
    visibility.add_argument("--public", dest="visibility", action="store_const", const="public")
    visibility.add_argument("--private", dest="visibility", action="store_const", const="private")
    parser.add_argument("--with-issues", action="store_true")
    parser.add_argument("--existing", action="store_true", help="Connect an existing empty repository, or push an already linked one")
    parser.add_argument("--decorate", action="store_true", help="Set About description, add topics and enable Issues")
    parser.add_argument("--presentation-release", action="store_true", help="Attach PPTX, PDF and defense materials as release coursework-v2")
    parser.add_argument("--dry-run", action="store_true", help="Local preview; no Git/GitHub changes")
    args = parser.parse_args()
    try:
        publish(args.repo, args.visibility, args.with_issues, args.dry_run, args.existing, args.decorate, args.presentation_release)
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        parser.exit(1, f"Error: {getattr(exc, 'stderr', None) or exc}\n")


if __name__ == "__main__":
    main()
