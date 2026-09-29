import json
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXPECTED = {
    "api": "python-services/.worktrees/python-logger-ci-focused",
    "auth": "shared-resources/.worktrees/auth-dependencies-focused/auth_service",
    "internal": "shared-resources/.worktrees/internal-api-gate-focused/internal_apis",
}


class ComposeReviewSourcesTest(unittest.TestCase):
    def configuration(self, *args):
        result = subprocess.run(
            ["docker", "compose", *args, "config", "--format", "json"],
            cwd=ROOT, capture_output=True, text=True, check=True,
        )
        return json.loads(result.stdout)["services"]

    def test_default_compose_builds_the_reviewed_sources(self):
        services = self.configuration()
        for service, relative in EXPECTED.items():
            expected = str((ROOT.parent / relative).resolve())
            self.assertEqual(services[service]["build"]["context"], expected)
            self.assertTrue(any(volume.get("source") == expected
                                for volume in services[service]["volumes"]))

    def test_old_base_alone_does_not_prove_reviewed_sources(self):
        services = self.configuration("-f", "compose.yaml")
        for service, relative in EXPECTED.items():
            expected = str((ROOT.parent / relative).resolve())
            self.assertNotEqual(services[service]["build"]["context"], expected)


if __name__ == "__main__":
    unittest.main()
