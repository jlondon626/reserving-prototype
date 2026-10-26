"""Select development deployment steps since the last successful release."""

import itertools
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen


PROJECT_ROOT = Path(__file__).resolve().parents[1]
API_FILES = {"main.py", "requirements.txt", "scripts/deploy-api.ps1"}
PLANNER_FILE = "scripts/get-deployment-plan.py"
RELEASE_EVENTS = {"push", "workflow_dispatch"}


def require_sha(value):
    if not isinstance(value, str) or not re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", value):
        raise RuntimeError("GitHub returned an invalid commit SHA.")
    return value


class GitHubAPI:
    def __init__(self, repository, token, api_url="https://api.github.com"):
        self.base_url = f"{api_url.rstrip('/')}/repos/{repository}"
        self.token = token

    def get(self, path):
        request = Request(
            self.base_url + path,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        try:
            with urlopen(request, timeout=30) as response:
                return json.load(response)
        except HTTPError as error:
            raise RuntimeError(f"GitHub API request failed: HTTP {error.code} ({error.reason}).") from error
        except (URLError, TimeoutError, ValueError) as error:
            raise RuntimeError(f"Could not read the GitHub deployment baseline: {error}.") from error


def workflow_filename(workflow_ref):
    try:
        name = workflow_ref.split("/.github/workflows/", 1)[1].split("@", 1)[0]
    except IndexError as error:
        raise RuntimeError("GITHUB_WORKFLOW_REF must identify the calling workflow file.") from error
    if not name or "/" in name:
        raise RuntimeError("GITHUB_WORKFLOW_REF contains an invalid workflow filename.")
    return name


def successful_baseline(api, workflow_file, current_run_id):
    for page in itertools.count(1):
        query = urlencode({"branch": "main", "status": "success", "per_page": 100, "page": page})
        payload = api.get(f"/actions/workflows/{quote(workflow_file, safe='')}/runs?{query}")
        runs = payload.get("workflow_runs")
        if not isinstance(runs, list):
            raise RuntimeError("GitHub returned an invalid workflow-run list.")
        for run in runs:
            if (
                str(run.get("id")) != str(current_run_id)
                and run.get("event") in RELEASE_EVENTS
                and run.get("head_branch") == "main"
                and run.get("status") == "completed"
                and run.get("conclusion") == "success"
            ):
                return require_sha(run.get("head_sha"))
        if len(runs) < 100:
            return None


def git_command(arguments, cwd):
    return subprocess.run(["git", *arguments], cwd=cwd, capture_output=True, check=False)


def changed_paths(base_sha, head_sha, cwd=PROJECT_ROOT):
    """Return None for an unavailable/diverged baseline, otherwise changed paths."""
    exists = git_command(["rev-parse", "--verify", "--quiet", f"{base_sha}^{{commit}}"], cwd)
    if exists.returncode == 1:
        return None
    if exists.returncode:
        raise RuntimeError("Could not inspect the deployment baseline in Git.")
    ancestor = git_command(["merge-base", "--is-ancestor", base_sha, head_sha], cwd)
    if ancestor.returncode == 1:
        return None
    if ancestor.returncode:
        raise RuntimeError("Could not compare deployment revisions in Git.")
    diff = git_command(["diff", "--name-only", "-z", "--no-renames", base_sha, head_sha, "--"], cwd)
    if diff.returncode:
        raise RuntimeError("Could not read changed files from Git.")
    return {path for path in diff.stdout.decode("utf-8", errors="surrogateescape").split("\0") if path}


def classify_changes(paths):
    workflow_changed = any(path.startswith(".github/workflows/") or path == PLANNER_FILE for path in paths)
    infra_changed = workflow_changed or any(
        path.startswith("infrastructure/")
        and path != "infrastructure/parameters/prod.bicepparam"
        and not path.lower().endswith(".md")
        and PurePosixPath(path).name.lower() not in {"readme", "readme.txt"}
        for path in paths
    )
    # Hosting/runtime changes can require code on a new or updated web app.
    api_changed = infra_changed or bool(API_FILES.intersection(paths))
    return infra_changed, api_changed


def build_plan(environment, api=None, cwd=PROJECT_ROOT):
    required = ["GITHUB_TOKEN", "GITHUB_REPOSITORY", "GITHUB_SHA", "GITHUB_RUN_ID", "GITHUB_WORKFLOW_REF"]
    missing = [name for name in required if not environment.get(name)]
    if missing:
        raise RuntimeError("Missing required workflow environment: " + ", ".join(missing))
    head_sha = require_sha(environment["GITHUB_SHA"])
    api = api or GitHubAPI(
        environment["GITHUB_REPOSITORY"], environment["GITHUB_TOKEN"],
        environment.get("GITHUB_API_URL", "https://api.github.com"),
    )
    current_head = require_sha(api.get("/commits/main").get("sha"))
    if current_head != head_sha:
        raise RuntimeError("Refusing to deploy a stale revision. Run the workflow for the current main commit.")
    if environment.get("FORCE_ALL", "false").lower() == "true":
        return {"infra": True, "api": True, "base_sha": ""}
    baseline = successful_baseline(
        api, workflow_filename(environment["GITHUB_WORKFLOW_REF"]), environment["GITHUB_RUN_ID"],
    )
    paths = changed_paths(baseline, head_sha, cwd) if baseline else None
    infra, api_changed = (True, True) if paths is None else classify_changes(paths)
    return {"infra": infra, "api": api_changed, "base_sha": baseline or ""}


def write_plan(plan, output_path=None):
    values = {key: str(value).lower() if isinstance(value, bool) else value for key, value in plan.items()}
    if output_path:
        with Path(output_path).open("a", encoding="utf-8") as output:
            for key, value in values.items():
                output.write(f"{key}={value}\n")
    print(f"Deployment plan: infrastructure={values['infra']}, API={values['api']}, "
          f"baseline={values['base_sha'] or 'full deployment'}")


def main():
    try:
        write_plan(build_plan(os.environ), os.environ.get("GITHUB_OUTPUT"))
    except (RuntimeError, OSError) as error:
        print(f"Deployment planning failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
