#!/usr/bin/env python3
"""Preview or create the proposed backlog; stdlib only, no people assigned."""

import argparse
import json
from pathlib import Path
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
REPO_PATTERN = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\Z")
MARKER_PATTERN = re.compile(r"<!-- bakery-task:(ML-\d{3}) -->")
LABEL_COLORS = {"ml-task": "895B3D", "priority:P0": "B54747", "priority:P1": "BD761A",
                "release:R1": "3972A8", "release:R2": "8261AD", "release:R3": "24827B",
                "release:R4": "4D7B45"}


def run(*args, cwd=ROOT):
    return subprocess.run(args, cwd=cwd, check=True, text=True, capture_output=True).stdout.strip()


def load_tasks(root=ROOT):
    tasks = json.loads((root / "docs/ml_team/tasks.json").read_text(encoding="utf-8"))
    seen = set()
    for task in tasks:
        key = task["id"]
        if not re.fullmatch(r"ML-\d{3}", key) or key in seen:
            raise ValueError(f"Invalid or duplicate task: {key}")
        if not set(task["depends_on"]).issubset(seen):
            raise ValueError(f"Dependencies must precede {key}")
        if not (root / f"docs/ml_team/tasks/{key}.md").is_file():
            raise ValueError(f"Missing task specification: {key}")
        seen.add(key)
    return tasks


def existing_markers(pages):
    found = {}
    for page in pages:
        for issue in page:
            if "pull_request" in issue:
                continue
            for key in MARKER_PATTERN.findall(issue.get("body") or ""):
                if key in found:
                    raise ValueError(f"Multiple existing issues for {key}; resolve manually")
                found[key] = issue["html_url"]
    return found


def import_tasks(repo, apply=False, root=ROOT):
    if not REPO_PATTERN.fullmatch(repo):
        raise ValueError("Repository must be OWNER/NAME")
    tasks = load_tasks(root)
    if not apply:
        for task in tasks:
            print(f"{task['id']} | {task['priority']} | {task['release']} | {task['role']} | {task['title']}")
        print(f"Preview: {len(tasks)} proposed tasks for {repo}. No GitHub requests. Use --apply to create.")
        return
    # Include CLOSED issues, preventing duplicates after completed tasks are closed.
    pages = json.loads(run("gh", "api", f"repos/{repo}/issues?state=all&per_page=100", "--paginate", "--slurp"))
    existing = existing_markers(pages)
    needed = {"ml-task", *(f"priority:{t['priority']}" for t in tasks),
              *(f"release:{t['release']}" for t in tasks)}
    labels = set(run("gh", "api", f"repos/{repo}/labels?per_page=100", "--paginate", "--jq", ".[].name").splitlines())
    for label in sorted(needed - labels):
        run("gh", "label", "create", label, "--repo", repo, "--color", LABEL_COLORS.get(label, "D4A373"))
    for task in tasks:
        key = task["id"]
        if key in existing:
            print(f"Keep {key}: {existing[key]}")
            continue
        body = (root / f"docs/ml_team/tasks/{key}.md").read_text(encoding="utf-8")
        body += f"\n<!-- bakery-task:{key} -->\n\n"
        body += "Зависимости в GitHub: " + (", ".join(existing[x] for x in task["depends_on"]) or "нет") + "\n"
        body += f"\nПлан поставки: https://github.com/{repo}/blob/main/docs/ml_team/delivery_plan.md\n"
        with tempfile.TemporaryDirectory(prefix="bakery-issue-") as temp:
            path = Path(temp) / "body.md"
            path.write_text(body, encoding="utf-8")
            url = run("gh", "issue", "create", "--repo", repo, "--title", f"[{key}] {task['title']}",
                      "--body-file", str(path), "--label", "ml-task",
                      "--label", f"priority:{task['priority']}", "--label", f"release:{task['release']}")
        existing[key] = url
        print(f"Created {key}: {url}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, help="OWNER/NAME")
    parser.add_argument("--apply", action="store_true", help="Create missing labels and issues")
    args = parser.parse_args()
    try:
        import_tasks(args.repo, args.apply)
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        parser.exit(1, f"Error: {getattr(exc, 'stderr', None) or exc}\n")


if __name__ == "__main__":
    main()
