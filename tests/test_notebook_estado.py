import importlib.util
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


if __name__ == "__main__":
    unittest.main()
