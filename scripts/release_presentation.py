#!/usr/bin/env python3
"""Publish presentation assets from a clean, pushed commit as a GitHub Release."""

import argparse
import json
import re
import subprocess

from github_tasks import ROOT, REPO_PATTERN, run

ASSETS = ["docs/presentation.pptx", "docs/presentation.pdf", "docs/presentation.md",
          "docs/requirements_checklist.md"]
NOTES = "docs/release_notes.md"


def publish_release(repo, tag="coursework-v2", apply=False):
    if not REPO_PATTERN.fullmatch(repo) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", tag):
        raise ValueError("Use OWNER/NAME and an alphanumeric release tag")
    for name in ASSETS + [NOTES]:
        if not (ROOT / name).is_file():
            raise ValueError(f"Missing release file: {name}")
    if not apply:
        print(f"Preview release {tag} in {repo}:")
        for name in ASSETS:
            print(f"  {name}")
        print("No GitHub changes. Use --apply after committing and pushing these files.")
        return
    run("git", "ls-files", "--error-unmatch", "--", *ASSETS, NOTES)
    if run("git", "diff", "HEAD", "--name-only", "--", *ASSETS, NOTES):
        raise ValueError("Commit and push the presentation files before creating a release")
    head = run("git", "rev-parse", "HEAD")
    remote = run("gh", "api", f"repos/{repo}/commits/main", "--jq", ".sha")
    if head != remote:
        raise ValueError("Local HEAD differs from GitHub main. Push/integrate before releasing")
    existing = subprocess.run(["gh", "release", "view", tag, "--repo", repo, "--json", "url,assets"],
                              cwd=ROOT, text=True, capture_output=True)
    if existing.returncode == 0:
        release = json.loads(existing.stdout)
        release_commit = run("gh", "api", f"repos/{repo}/commits/{tag}", "--jq", ".sha")
        if release_commit != head:
            raise ValueError(f"Release {tag} belongs to another commit. Choose a new --tag")
        uploaded = {item["name"] for item in release["assets"]}
        missing = [str(ROOT / x) for x in ASSETS if (ROOT / x).name not in uploaded]
        if missing:
            run("gh", "release", "upload", tag, *missing, "--repo", repo)
    else:
        run("gh", "release", "create", tag, *(str(ROOT / x) for x in ASSETS),
            "--repo", repo, "--target", head, "--title", "Умная пекарня: презентация и материалы защиты",
            "--notes-file", str(ROOT / NOTES))
    verified = json.loads(run("gh", "release", "view", tag, "--repo", repo, "--json", "url,assets"))
    uploaded = {x["name"]: x["size"] for x in verified["assets"]}
    if any(uploaded.get((ROOT / x).name) != (ROOT / x).stat().st_size for x in ASSETS):
        raise ValueError("Release asset list/sizes differ from local files. Review the release")
    print(f"Presentation release: {verified['url']}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default="geoink/Ymnaia_Pekarna")
    parser.add_argument("--tag", default="coursework-v2")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    try:
        publish_release(args.repo, args.tag, args.apply)
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        parser.exit(1, f"Error: {getattr(exc, 'stderr', None) or exc}\n")


if __name__ == "__main__":
    main()
