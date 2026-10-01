import importlib.util
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "notebook-sync.py"


def load():
    spec = importlib.util.spec_from_file_location("notebook_sync", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def lane(id, repo, compose, pr=1):
    return {"id": id, "repo": repo, "pr": pr, "local_branch": f"local-{id}",
            "fork_branch": f"fork-{id}", "compose": compose}


class LaneSourcesTest(unittest.TestCase):
    def setUp(self):
        self.sync = load()

    def test_every_notebook_lane_is_a_source(self):
        lanes = self.sync.json.loads(self.sync.LANES_FILE.read_text())["lanes"]
        expected = [l["id"] for l in lanes if l.get("notebook", True)]
        self.assertEqual(expected, [s["lane"] for s in self.sync.SOURCES])

    def test_lane_excluded_from_notebook_does_not_split_its_repo(self):
        sources = self.sync.lane_sources([
            lane("api", "python-services", {"api": "."}),
            dict(lane("api-runtime", "python-services", {}), notebook=False),
        ])
        self.assertEqual(["api"], [s["lane"] for s in sources])
        self.assertIsNone(sources[0]["paths"])

    def test_single_lane_repo_uploads_whole_tree(self):
        (source,) = self.sync.lane_sources([lane("api", "python-services", {"api": "."})])
        self.assertIsNone(source["paths"])
        self.assertEqual("local-api", source["ref"])

    def test_shared_repo_limits_each_lane_to_its_service(self):
        sources = self.sync.lane_sources([
            lane("catalog", "shared-resources", {"internal": "internal_apis"}),
            lane("auth", "shared-resources", {"auth": "auth_service"}),
        ])
        self.assertEqual([("internal_apis/", ".github/"), ("auth_service/", ".github/")],
                         [s["paths"] for s in sources])
        self.assertTrue(self.sync.skip("auth_service/main.py", "shared-resources", sources[0]["paths"]))
        self.assertFalse(self.sync.skip("internal_apis/main.py", "shared-resources", sources[0]["paths"]))
        self.assertFalse(self.sync.skip("README.md", "shared-resources", sources[0]["paths"]))

    def test_lane_prune_keeps_the_other_lane_of_the_repo(self):
        sources = self.sync.lane_sources([
            lane("catalog", "shared-resources", {"internal": "internal_apis"}, pr=30),
            lane("auth", "shared-resources", {"auth": "auth_service"}, pr=31),
        ])
        existing = [
            {"id": "old-auth", "title": self.sync.title_prefix(sources[1]) + "aaaaaaa"},
            {"id": "catalog", "title": self.sync.title_prefix(sources[0]) + "bbbbbbb"},
            {"id": "legacy", "title": "LabTech código: shared-resources @ chore/dependency-refresh ccccccc"},
        ]
        lane_only = self.sync.old_versions(existing, [self.sync.title_prefix(sources[1])], {"new"})
        self.assertEqual(["old-auth"], [s["id"] for s in lane_only])
        full = self.sync.old_versions(existing, [self.sync.title_prefix(repo="shared-resources")],
                                      {"catalog", "new"})
        self.assertEqual(["old-auth", "legacy"], [s["id"] for s in full])


class SecretScanTest(unittest.TestCase):
    def setUp(self):
        self.sync = load()

    def test_reserved_example_host_is_a_fixture(self):
        line = '        "mongodb+srv://atlas-user:atlas-password@cluster.example.mongodb.net/"'
        self.assertFalse(self.sync.looks_like_secret(line))

    def test_credentials_on_a_real_host_still_abort(self):
        line = '        "mongodb+srv://reservas:S3nhaForte2026@reservas.ab1cd.mongodb.net/"'
        self.assertTrue(self.sync.looks_like_secret(line))


if __name__ == "__main__":
    unittest.main()
