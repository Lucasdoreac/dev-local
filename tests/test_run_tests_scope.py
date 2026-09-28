import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "run-tests.sh"
LAB = ROOT.parent


class RunTestsScopeTest(unittest.TestCase):
    def test_framework_unit_tests_are_optional_for_clean_heads_without_tests_dir(self):
        script = SCRIPT.read_text()
        self.assertRegex(
            script,
            r"if \[ -d tests \]; then\s+"
            r"python -m unittest discover -s tests -v\s+fi",
        )

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
            for key in (
                "PYTHON_SERVICES_DIR",
                "INTERNAL_APIS_DIR",
                "AUTH_SERVICE_DIR",
                "E2E_FRAMEWORK_DIR",
                "PYTHON_SERVICES_TEST_IMAGE",
                "INTERNAL_APIS_TEST_IMAGE",
                "AUTH_SERVICE_TEST_IMAGE",
                "BASELINE_PYTHON_TEST_IMAGE",
            ):
                env.pop(key, None)
            env.update(
                PATH=f"{fake_bin}:{env['PATH']}",
                DOCKER_LOG=str(command_log),
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
            test_dockerfile = (ROOT / "dockerfiles/Dockerfile.test-python").read_text()
            self.assertIn("labtech-dev-runner-python:3.14.7", docker_calls)
            self.assertNotIn("python:3.12-slim", docker_calls)
            self.assertIn(":/root/.cache/pypoetry", docker_calls)
            self.assertIn(":/root/.cache/pip", docker_calls)
            self.assertNotIn('poetry=="$POETRY_VERSION"', docker_calls)
            self.assertIn("ARG POETRY_VERSION=2.4.1", test_dockerfile)
            self.assertIn('poetry==${POETRY_VERSION}', test_dockerfile)
            self.assertIn("python-logger-ci-focused", docker_calls)
            self.assertNotIn("python-deps-on-gate", docker_calls)
            self.assertIn("catalog-deps-on-gate", docker_calls)
            self.assertIn("e2e-dependencies-focused", result.stdout)
            self.assertIn("build --quiet", docker_calls)
            self.assertIn("pytest -q", docker_calls)
            self.assertIn("behave --dry-run --no-color", docker_calls)
            self.assertIn("auth-dependencies-focused", docker_calls)
            self.assertNotIn("--network host", docker_calls)


if __name__ == "__main__":
    unittest.main()
