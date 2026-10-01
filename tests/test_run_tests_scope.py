import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "run-tests.sh"
LAB = ROOT.parent


class RunTestsScopeTest(unittest.TestCase):
    def test_python_sources_are_derived_from_resolved_compose(self):
        script = SCRIPT.read_text()
        self.assertIn('docker compose config --format json', script)
        for variable in ("PYTHON_SERVICES_DIR", "AUTH_SERVICE_DIR", "INTERNAL_APIS_DIR"):
            self.assertIn(f'export {variable}="$', script)

    def test_runner_rejects_platforms_not_pinned_by_the_harness(self):
        script = SCRIPT.read_text()
        self.assertIn('if [[ "$DOCKER_PLATFORM" != "linux/amd64" ]]', script)

    def test_all_runs_the_web_build_and_suite_from_the_compose_mount(self):
        script = SCRIPT.read_text()
        self.assertIn('docker compose exec -T reservas sh -ec \'cd /app && yarn build && yarn test\'', script)
        self.assertIn("run_frontend || status=1", script[script.index("  all)"):])

    def test_framework_unit_tests_are_optional_for_clean_heads_without_tests_dir(self):
        script = SCRIPT.read_text()
        self.assertRegex(
            script,
            r"if \[ -d tests \]; then\s+"
            r"poetry run python -m unittest discover -s tests -v\s+fi",
        )

    def test_all_targets_review_heads_and_web_without_live_e2e_or_allocation(self):
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
  compose)
    root="$(cd .. && pwd)"
    printf '{"services":{"api":{"build":{"context":"%s/python-services/.worktrees/approval-security-hardening"}},"auth":{"build":{"context":"%s/shared-resources/.worktrees/auth-email-logo/auth_service"}},"internal":{"build":{"context":"%s/shared-resources/.worktrees/pr30-without-weekdays/internal_apis"}}}}' "$root" "$root" "$root"
    exit 0
    ;;
  network|stop) exit 0 ;;
  image) if [ "${2:-}" = "inspect" ]; then echo linux/amd64; fi; exit 0 ;;
  exec) echo PONG; exit 0 ;;
  run) if [ "${2:-}" = "-d" ]; then echo fake-redis-id; fi; exit 0 ;;
  *) exit 0 ;;
esac
"""
            )
            fake_docker.chmod(0o755)
            fake_git = fake_bin / "git"
            fake_git.write_text(
                """#!/bin/sh
source="$2"
case "${3:-}" in
  branch)
    case "$source" in
      *e2e-pr3-without-offers*) echo clean/pr3-without-offers ;;
      *pr30-without-weekdays*) echo clean/pr30-without-weekdays ;;
      *auth-email-logo*) echo feat/auth-email-logo ;;
      *approval-security-hardening*) echo fix/approval-security-hardening ;;
      *) echo main ;;
    esac
    ;;
  rev-parse) echo 1234567 ;;
  *) exit 1 ;;
esac
"""
            )
            fake_git.chmod(0o755)
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
            self.assertIn("interfaces-usuario/reservas", result.stdout)
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
            self.assertIn("approval-security-hardening", docker_calls)
            self.assertNotIn("python-deps-on-gate", docker_calls)
            self.assertIn("pr30-without-weekdays", docker_calls)
            self.assertNotIn("catalog-deps-on-gate", docker_calls)
            self.assertIn("clean/pr3-without-offers", result.stdout)
            self.assertIn("e2e-pr3-without-offers", docker_calls)
            self.assertNotIn("e2e-dependencies-focused", docker_calls)
            self.assertIn("build --quiet", docker_calls)
            self.assertIn("pytest -q", docker_calls)
            self.assertIn("behave --dry-run --no-color", docker_calls)
            self.assertIn("compose exec -T reservas", docker_calls)
            self.assertIn("yarn build && yarn test", docker_calls)
            self.assertIn("auth-email-logo", docker_calls)
            self.assertNotIn("--network host", docker_calls)
            self.assertIn("poetry install --no-interaction --no-ansi --no-root", docker_calls)
            self.assertNotIn("requirements.txt", docker_calls)

    def test_framework_uses_pyproject_and_lock_instead_of_requirements(self):
        script = SCRIPT.read_text()
        self.assertIn('"$FRAMEWORK_SOURCE/pyproject.toml" && -f "$FRAMEWORK_SOURCE/poetry.lock"', script)
        self.assertIn("poetry install --no-interaction --no-ansi --no-root", script)
        self.assertNotIn('"$FRAMEWORK_SOURCE/requirements.txt"', script)


if __name__ == "__main__":
    unittest.main()
