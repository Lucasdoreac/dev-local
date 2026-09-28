import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "run-tests.sh"
LAB = ROOT.parent


class RunTestsScopeTest(unittest.TestCase):
    def test_all_targets_four_review_heads_without_live_e2e_or_allocation(self):
        with tempfile.TemporaryDirectory() as temp:
            temp_path = Path(temp)
            fake_bin = temp_path / "bin"
            fake_bin.mkdir()
            command_log = temp_path / "docker.log"
            fake_docker = fake_bin / "docker"
            fake_docker.write_text(
                """#!/bin/sh
echo "$*" >> "$DOCKER_LOG"
case "$1" in
  network|stop) exit 0 ;;
  exec) echo PONG; exit 0 ;;
  run) if [ "${2:-}" = "-d" ]; then echo fake-redis-id; fi; exit 0 ;;
  *) exit 0 ;;
esac
"""
            )
            fake_docker.chmod(0o755)
            env = os.environ.copy()
            env.update(
                PATH=f"{fake_bin}:{env['PATH']}",
                DOCKER_LOG=str(command_log),
                PYTHON_SERVICES_DIR=str(
                    LAB / "python-services/.worktrees/python-logger-ci-focused"
                ),
                INTERNAL_APIS_DIR=str(
                    LAB / "shared-resources/.worktrees/internal-api-gate-focused/internal_apis"
                ),
                AUTH_SERVICE_DIR=str(
                    LAB / "shared-resources/.worktrees/auth-dependencies-focused/auth_service"
                ),
                E2E_FRAMEWORK_DIR=str(LAB / "supreme-test-framework"),
            )
            result = subprocess.run(
                ["bash", str(SCRIPT), "all"],
                cwd=ROOT,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("python-services", result.stdout)
            self.assertIn("internal_apis", result.stdout)
            self.assertIn("auth_service", result.stdout)
            self.assertIn("supreme-test-framework", result.stdout)
            self.assertNotIn("teachers-allocation", result.stdout)

            docker_calls = command_log.read_text()
            self.assertNotIn("docker build", docker_calls)
            self.assertIn("pytest -q", docker_calls)
            self.assertIn("behave --dry-run --no-color", docker_calls)
            self.assertIn("python-logger-ci-focused", docker_calls)
            self.assertIn("internal-api-gate-focused", docker_calls)
            self.assertIn("auth-dependencies-focused", docker_calls)
            self.assertNotIn("--network host", docker_calls)


if __name__ == "__main__":
    unittest.main()
