import json
import os
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXPECTED = {
    "api": "python-services/.worktrees/approval-security-hardening",
    "auth": "shared-resources/.worktrees/auth-email-logo/auth_service",
    "internal": "shared-resources/.worktrees/pr30-without-weekdays/internal_apis",
}

WEB = ".worktrees/web-email-logo/reservas"  # PR #41 head (3b74b64)


class ComposeReviewSourcesTest(unittest.TestCase):
    def configuration(self, *args, env=None):
        command_env = os.environ.copy()
        if env:
            command_env.update(env)
        result = subprocess.run(
            ["docker", "compose", *args, "config", "--format", "json"],
            cwd=ROOT, env=command_env, capture_output=True, text=True, check=True,
        )
        return json.loads(result.stdout)["services"]

    def test_default_compose_builds_the_reviewed_sources(self):
        services = self.configuration()
        for service, relative in EXPECTED.items():
            expected = str((ROOT.parent / relative).resolve())
            self.assertEqual(services[service]["build"]["context"], expected)
            self.assertTrue(any(volume.get("source") == expected
                                for volume in services[service]["volumes"]))

    def test_web_mounts_the_clean_pr41_head_and_keeps_its_node_modules_volume(self):
        volumes = self.configuration()["reservas"]["volumes"]
        app = [v for v in volumes if v.get("target") == "/app"]
        self.assertEqual([v["source"] for v in app], [str((ROOT.parent / WEB).resolve())])
        self.assertTrue(any(v.get("target") == "/app/node_modules" for v in volumes))

    def test_old_base_alone_does_not_prove_reviewed_sources(self):
        services = self.configuration("-f", "compose.yaml")
        for service, relative in EXPECTED.items():
            expected = str((ROOT.parent / relative).resolve())
            self.assertNotEqual(services[service]["build"]["context"], expected)

    def test_source_overrides_select_the_same_build_context_and_mount(self):
        sources = {
            "api": ("PYTHON_SERVICES_DIR", ROOT.parent / "python-services"),
            "auth": ("AUTH_SERVICE_DIR", ROOT.parent / "shared-resources/auth_service"),
            "internal": ("INTERNAL_APIS_DIR", ROOT.parent / "shared-resources/internal_apis"),
        }
        env = {name: str(path.resolve()) for name, path in sources.values()}
        services = self.configuration(env=env)
        for service, (name, path) in sources.items():
            expected = str(path.resolve())
            self.assertEqual(services[service]["build"]["context"], expected)
            self.assertTrue(any(volume.get("source") == expected
                                for volume in services[service]["volumes"]))


if __name__ == "__main__":
    unittest.main()
