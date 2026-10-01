import importlib.util
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "check-compose.py"
DIGEST = "sha256:" + "a" * 64


def load_checker():
    spec = importlib.util.spec_from_file_location("check_compose", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RedisPinTest(unittest.TestCase):
    def test_digest_pinned_expected_redis_is_accepted(self):
        checker = load_checker()
        image = f"{checker.EXPECTED_REDIS_IMAGE}@{DIGEST}"
        self.assertEqual([], checker.problems({"redis": {"image": image}}))

    def test_other_redis_version_is_rejected(self):
        checker = load_checker()
        found = checker.problems({"redis": {"image": f"redis:8.2@{DIGEST}"}})
        self.assertTrue(any("expected" in item for item in found))


if __name__ == "__main__":
    unittest.main()
