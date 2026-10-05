import importlib.util
import json
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "notebook-estado.py"


def load():
    spec = importlib.util.spec_from_file_location("notebook_estado", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class GitHubDiagnosticsTest(unittest.TestCase):
    def setUp(self):
        self.estado = load()

    @patch("subprocess.run")
    def test_retries_transient_tls_failure_and_reports_recovery(self, run):
        failure = subprocess.CompletedProcess([], 1, "", "Post https://api.github.com/graphql: TLS handshake timeout")
        success = subprocess.CompletedProcess([], 0, '[{"number": 12}]', "")
        run.side_effect = [failure, success]

        with patch("builtins.print") as output:
            result = self.estado.gh_json("listar PRs", ["gh", "pr", "list"], sleep=lambda _: None)

        self.assertEqual([{"number": 12}], result)
        self.assertEqual(2, run.call_count)
        self.assertIn("Nova tentativa", output.call_args_list[0].args[0])
        self.assertIn("respondeu", output.call_args_list[1].args[0])

    @patch("subprocess.run")
    def test_non_transient_auth_error_is_not_retried(self, run):
        run.return_value = subprocess.CompletedProcess([], 1, "", "HTTP 401: Bad credentials")

        with self.assertRaisesRegex(RuntimeError, "gh auth status"):
            self.estado.gh_json("listar PRs", ["gh", "pr", "list"], sleep=lambda _: None)

        self.assertEqual(1, run.call_count)

    @patch("subprocess.run")
    def test_redacts_token_from_logged_error(self, run):
        run.return_value = subprocess.CompletedProcess([], 1, "", "failed ghp_abcdefghijklmnopqrstuvwxyz123456")

        with self.assertRaises(RuntimeError) as raised:
            self.estado.gh_json("listar PRs", ["gh", "pr", "list"], max_attempts=1, sleep=lambda _: None)

        self.assertIn("[REDACTED]", str(raised.exception))
        self.assertNotIn("ghp_", str(raised.exception))


class RenderSnapshotTest(unittest.TestCase):
    def setUp(self):
        self.estado = load()

    def test_reports_current_live_shas_and_auto_deploy_for_all_services(self):
        services = []
        deploys = {}
        for i, (environment, name, _) in enumerate(self.estado.RENDER_TARGETS):
            service_id = f"service-{i}"
            services.append({"service": {"id": service_id, "name": name,
                                          "branch": f"branch-{i}", "autoDeploy": "no"},
                             "environment": {"name": environment}})
            deploys[service_id] = [{"status": "live", "commit": {"id": f"abcdef{i}012345"}}]

        def run(args, **kwargs):
            payload = services if args[1:3] == ["services", "--output"] else deploys[args[3]]
            return subprocess.CompletedProcess(args, 0, json.dumps(payload), "")

        lines = self.estado.render_snapshot(run=run)
        rendered = "\n".join(lines)
        self.assertEqual(8, sum(line.startswith("- ") for line in lines))
        for i, (_, _, label) in enumerate(self.estado.RENDER_TARGETS):
            self.assertIn(f"{label}: live `abcdef{i}`", rendered)
            self.assertIn("auto-deploy desligado", rendered)
        self.assertNotIn("service-0", rendered)

    def test_compares_configured_render_branch_with_pr_head_sha(self):
        services = []
        for i, (environment, name, _) in enumerate(self.estado.RENDER_TARGETS):
            service_id = f"service-{i}"
            services.append({"service": {"id": service_id, "name": name,
                                          "branch": "pr-branch" if i == 0 else f"branch-{i}",
                                          "autoDeploy": "yes"},
                             "environment": {"name": environment}})
        prs = {"PS-1": ("open", 1, "pr-branch", "abcdef0123456789")}

        def run(args, **kwargs):
            payload = services if args[1:3] == ["services", "--output"] else [
                {"status": "live", "commit": {"id": "1234567012345678"}}
            ]
            return subprocess.CompletedProcess(args, 0, json.dumps(payload), "")

        rendered = "\n".join(self.estado.render_snapshot(prs, run=run))
        self.assertIn("head `abcdef0`, diferente do SHA live", rendered)

    def test_missing_render_service_aborts_snapshot(self):
        result = subprocess.CompletedProcess([], 0, "[]", "")
        with self.assertRaisesRegex(RuntimeError, "serviços Reservas ausentes"):
            self.estado.render_snapshot(run=lambda *args, **kwargs: result)

    def test_render_command_error_is_reported_without_partial_snapshot(self):
        failure = subprocess.CompletedProcess([], 1, "", "unauthorized")
        with self.assertRaisesRegex(RuntimeError, "Render: listar serviços falhou"):
            self.estado.render_snapshot(run=lambda *args, **kwargs: failure)


if __name__ == "__main__":
    unittest.main()
