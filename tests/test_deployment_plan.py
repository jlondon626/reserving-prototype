"""Change-selection and release-baseline checks without GitHub or Azure access."""

import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError, URLError


SPEC = importlib.util.spec_from_file_location(
    "deployment_plan", Path(__file__).resolve().parents[1] / "scripts/get-deployment-plan.py",
)
planner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(planner)
HEAD = "a" * 40
BASE = "b" * 40
ENVIRONMENT = {
    "GITHUB_TOKEN": "unit-test-token",
    "GITHUB_REPOSITORY": "owner/repository",
    "GITHUB_SHA": HEAD,
    "GITHUB_RUN_ID": "123",
    "GITHUB_WORKFLOW_REF": "owner/repository/.github/workflows/ci-deploy.yml@refs/heads/main",
}


def release_run(**overrides):
    result = {
        "id": 100, "event": "push", "head_branch": "main", "status": "completed",
        "conclusion": "success", "head_sha": BASE,
    }
    result.update(overrides)
    return result


class ChangeSelectionTests(unittest.TestCase):
    def test_deployment_units(self):
        cases = [
            ({"main.py"}, (False, True)),
            ({"requirements.txt", "scripts/deploy-api.ps1"}, (False, True)),
            ({"infrastructure/modules/app-service.bicep"}, (True, True)),
            ({"infrastructure/modules/sql.bicep"}, (True, True)),
            ({"infrastructure/parameters/dev.bicepparam"}, (True, True)),
            ({"infrastructure/bicepconfig.json", "main.py"}, (True, True)),
            ({".github/workflows/ci-deploy.yml"}, (True, True)),
            ({"scripts/get-deployment-plan.py"}, (True, True)),
            ({"README.md", "infrastructure/README.md"}, (False, False)),
            ({"infrastructure/parameters/prod.bicepparam"}, (False, False)),
            ({"tests/test_api.py", "requirements-dev.txt"}, (False, False)),
            ({"validation/core/engine.py"}, (False, False)),
            (set(), (False, False)),
        ]
        for paths, expected in cases:
            with self.subTest(paths=paths):
                self.assertEqual(planner.classify_changes(paths), expected)

    def test_git_includes_deleted_and_both_sides_of_renames(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            def git(*arguments):
                return subprocess.check_output(["git", *arguments], cwd=root, text=True).strip()
            git("init", "--quiet")
            git("config", "user.name", "Workflow tests")
            git("config", "user.email", "workflow-tests@example.invalid")
            (root / "main.py").write_text("original app\n", encoding="utf-8")
            (root / "requirements.txt").write_text("dependency\n", encoding="utf-8")
            git("add", ".")
            git("commit", "--quiet", "-m", "baseline")
            baseline = git("rev-parse", "HEAD")
            git("mv", "main.py", "renamed.py")
            git("rm", "--quiet", "requirements.txt")
            git("commit", "--quiet", "-m", "rename and delete")
            paths = planner.changed_paths(baseline, git("rev-parse", "HEAD"), root)
            self.assertEqual(paths, {"main.py", "renamed.py", "requirements.txt"})
            self.assertEqual(planner.classify_changes(paths), (False, True))
            self.assertIsNone(planner.changed_paths("f" * 40, git("rev-parse", "HEAD"), root))

    def test_diverged_baseline_requires_full_release(self):
        with patch.object(planner, "git_command") as git:
            git.side_effect = [Mock(returncode=0), Mock(returncode=1)]
            self.assertIsNone(planner.changed_paths(BASE, HEAD))
            self.assertEqual(git.call_count, 2)

    def test_sql_only_changes_select_infrastructure_and_api(self):
        self.assertEqual(
            planner.classify_changes({"infrastructure/modules/sql.bicep", "infrastructure/parameters/dev.bicepparam"}),
            (True, True),
        )

    def test_git_errors_fail_instead_of_assuming_no_changes(self):
        with patch.object(planner, "git_command", return_value=Mock(returncode=128)):
            with self.assertRaisesRegex(RuntimeError, "inspect"):
                planner.changed_paths(BASE, HEAD)


class BaselineTests(unittest.TestCase):
    def test_ignores_pr_current_and_unsuccessful_runs(self):
        api = Mock()
        api.get.return_value = {"workflow_runs": [
            release_run(event="pull_request"), release_run(id=123),
            release_run(head_branch="feature"), release_run(status="in_progress"),
            release_run(conclusion="failure"), release_run(event="workflow_dispatch"),
        ]}
        self.assertEqual(planner.successful_baseline(api, "ci-deploy.yml", "123"), BASE)
        self.assertIn("branch=main", api.get.call_args.args[0])

    def test_searches_next_page_instead_of_ignoring_older_release(self):
        api = Mock()
        api.get.side_effect = [
            {"workflow_runs": [release_run(event="pull_request")] * 100},
            {"workflow_runs": [release_run()]},
        ]
        self.assertEqual(planner.successful_baseline(api, "ci-deploy.yml", "123"), BASE)
        self.assertIn("page=2", api.get.call_args.args[0])

    def test_first_release_has_no_baseline(self):
        api = Mock()
        api.get.return_value = {"workflow_runs": []}
        self.assertIsNone(planner.successful_baseline(api, "ci-deploy.yml", "123"))

    def test_invalid_api_data_is_rejected(self):
        api = Mock()
        api.get.return_value = {"workflow_runs": None}
        with self.assertRaisesRegex(RuntimeError, "invalid workflow-run"):
            planner.successful_baseline(api, "ci-deploy.yml", "123")

    def test_api_errors_do_not_leak_credentials(self):
        api = planner.GitHubAPI("owner/repository", "secret-token")
        for error in [HTTPError("url", 403, "Forbidden", {}, None), URLError("unavailable")]:
            with self.subTest(error=error), patch.object(planner, "urlopen", side_effect=error):
                with self.assertRaises(RuntimeError) as result:
                    api.get("/commits/main")
                self.assertNotIn("secret-token", str(result.exception))


class PlanTests(unittest.TestCase):
    def test_first_release_deploys_both(self):
        api = Mock()
        api.get.side_effect = [{"sha": HEAD}, {"workflow_runs": []}]
        self.assertEqual(planner.build_plan(ENVIRONMENT, api), {"infra": True, "api": True, "base_sha": ""})

    def test_stale_commit_fails_even_when_forcing_deployment(self):
        api = Mock()
        api.get.return_value = {"sha": BASE}
        with self.assertRaisesRegex(RuntimeError, "stale revision"):
            planner.build_plan({**ENVIRONMENT, "FORCE_ALL": "true"}, api)

    def test_force_all_bypasses_baseline_lookup(self):
        api = Mock()
        api.get.return_value = {"sha": HEAD}
        self.assertTrue(planner.build_plan({**ENVIRONMENT, "FORCE_ALL": "true"}, api)["infra"])
        api.get.assert_called_once_with("/commits/main")

    def test_api_only_release_uses_successful_baseline(self):
        api = Mock()
        api.get.side_effect = [{"sha": HEAD}, {"workflow_runs": [release_run()]}]
        with patch.object(planner, "changed_paths", return_value={"main.py"}) as diff:
            self.assertEqual(planner.build_plan(ENVIRONMENT, api), {"infra": False, "api": True, "base_sha": BASE})
            self.assertEqual(diff.call_args.args[:2], (BASE, HEAD))

    def test_missing_or_diverged_baseline_deploys_both(self):
        api = Mock()
        api.get.side_effect = [{"sha": HEAD}, {"workflow_runs": [release_run()]}]
        with patch.object(planner, "changed_paths", return_value=None):
            self.assertEqual(planner.build_plan(ENVIRONMENT, api), {"infra": True, "api": True, "base_sha": BASE})

    def test_environment_and_workflow_ref_are_required(self):
        with self.assertRaisesRegex(RuntimeError, "Missing required"):
            planner.build_plan({})
        with self.assertRaisesRegex(RuntimeError, "GITHUB_WORKFLOW_REF"):
            planner.workflow_filename("missing-path")

    def test_outputs_use_github_boolean_format_and_preserve_existing_lines(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "outputs"
            output.write_text("existing=value\n", encoding="utf-8")
            planner.write_plan({"infra": False, "api": True, "base_sha": BASE}, output)
            self.assertEqual(output.read_text(encoding="utf-8"),
                             f"existing=value\ninfra=false\napi=true\nbase_sha={BASE}\n")


if __name__ == "__main__":
    unittest.main()
