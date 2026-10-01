import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "check-lanes.py"


def load_checker():
    spec = importlib.util.spec_from_file_location("check_lanes", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def lane(**overrides):
    base = {
        "id": "api", "repo": "python-services", "pr": 1, "base": "main",
        "parents": [], "worktree": "repo/.worktrees/a", "local_branch": "a",
        "fork_branch": "a", "compose": {"api": "."},
    }
    base.update(overrides)
    return base


class LaneMapTest(unittest.TestCase):
    def setUp(self):
        self.checker = load_checker()
        self.lab = Path("/lab")

    def write(self, lanes):
        handle = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
        json.dump({"lanes": lanes}, handle)
        handle.close()
        self.addCleanup(Path(handle.name).unlink)
        return handle.name

    def test_repeated_id_is_rejected(self):
        with self.assertRaises(ValueError):
            self.checker.load_lanes(self.write([lane(), lane()]))

    def test_unknown_parent_is_rejected(self):
        with self.assertRaises(ValueError):
            self.checker.load_lanes(self.write([lane(parents=["missing"])]))

    def test_compose_on_other_source_is_reported(self):
        source = "/lab/repo/.worktrees/old"
        services = {"api": {"build": {"context": source}, "volumes": [{"source": source}]}}
        found = self.checker.compose_problems([lane()], services, self.lab)
        self.assertEqual(2, len(found))

    def test_compose_on_lane_source_passes(self):
        source = "/lab/repo/.worktrees/a"
        services = {"api": {"build": {"context": source}, "volumes": [{"source": source}]}}
        self.assertEqual([], self.checker.compose_problems([lane()], services, self.lab))

    def test_runtests_default_must_match_e2e_lane(self):
        e2e = lane(id="e2e", repo="supreme-test-framework", worktree=".worktrees/e2e", compose={})
        ok = 'X="${E2E_FRAMEWORK_DIR:-$LAB/.worktrees/e2e}"'
        bad = 'X="${E2E_FRAMEWORK_DIR:-$LAB/.worktrees/old}"'
        self.assertEqual([], self.checker.runtests_problems([e2e], ok))
        self.assertEqual(1, len(self.checker.runtests_problems([e2e], bad)))


class RepositoryLanesTest(unittest.TestCase):
    def test_run_tests_uses_the_declared_e2e_lane(self):
        checker = load_checker()
        lanes = checker.load_lanes()["lanes"]
        self.assertEqual([], checker.runtests_problems(lanes, (ROOT / "run-tests.sh").read_text()))


if __name__ == "__main__":
    unittest.main()
