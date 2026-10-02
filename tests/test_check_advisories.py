import importlib.util
import io
import unittest
from contextlib import redirect_stdout
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "check-advisories.py"

POETRY_LOCK = '''
[[package]]
name = "Werkzeug"
version = "3.1.3"

[[package]]
name = "urllib3"
version = "2.8.0"
'''

YARN_LOCK = '''# yarn lockfile v1


"@babel/core@^7.29.7":
  version "7.29.7"
  resolved "https://registry.yarnpkg.com/@babel/core/-/core-7.29.7.tgz"

js-tokens@^4.0.0, "js-tokens@^3.0.0 || ^4.0.0":
  version "4.0.0"
'''


def load():
    spec = importlib.util.spec_from_file_location("check_advisories", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def lane(id, repo, compose, parents=()):
    return {"id": id, "repo": repo, "compose": compose, "parents": list(parents)}


class ParseTest(unittest.TestCase):
    def setUp(self):
        self.ca = load()

    def test_poetry_lock_names_are_normalized(self):
        self.assertEqual({("PyPI", "werkzeug", "3.1.3"), ("PyPI", "urllib3", "2.8.0")},
                         self.ca.parse_poetry_lock(POETRY_LOCK))

    def test_yarn_lock_keeps_scoped_names_and_multi_range_entries(self):
        self.assertEqual({("npm", "@babel/core", "7.29.7"), ("npm", "js-tokens", "4.0.0")},
                         self.ca.parse_yarn_lock(YARN_LOCK))


class OwnedLocksTest(unittest.TestCase):
    def setUp(self):
        self.ca = load()
        self.lanes = [
            lane("api", "python-services", {"api": "."}),
            lane("api-runtime", "python-services", {}, ["api"]),
            lane("catalog", "shared-resources", {"internal": "internal_apis"}),
            lane("auth", "shared-resources", {"auth": "auth_service"}),
            lane("auth-runtime", "shared-resources", {}, ["auth"]),
            lane("web", "interfaces-usuario", {"reservas": "reservas"}, ["catalog", "auth"]),
            lane("e2e", "supreme-test-framework", {}, ["web"]),
        ]
        self.by_id = {item["id"]: item for item in self.lanes}

    def owned(self, id):
        return self.ca.owned_locks(self.by_id[id], self.lanes)

    def test_shared_repo_lane_skips_the_sibling_service_lock(self):
        self.assertEqual(["auth_service/poetry.lock", "auth_service/yarn.lock"], self.owned("auth"))
        self.assertNotIn("internal_apis/poetry.lock", self.owned("auth"))

    def test_lane_outside_compose_inherits_its_same_repo_parent(self):
        self.assertEqual(self.owned("auth"), self.owned("auth-runtime"))
        self.assertEqual(["poetry.lock", "yarn.lock"], self.owned("api-runtime"))

    def test_parent_in_another_repo_is_not_inherited(self):
        self.assertEqual(["poetry.lock", "yarn.lock"], self.owned("e2e"))


class FindingsTest(unittest.TestCase):
    def setUp(self):
        self.ca = load()

    def test_known_vulnerable_pin_is_reported(self):
        fake = lambda packages: [["GHSA-x"] if name == "jinja2" else [] for _, name, _ in packages]
        hits = self.ca.findings({("PyPI", "jinja2", "2.10"), ("PyPI", "flask", "3.1.3")}, fake)
        self.assertEqual([(("PyPI", "jinja2", "2.10"), ["GHSA-x"])], hits)

    def test_self_test_fails_when_osv_misses_known_pins(self):
        with redirect_stdout(io.StringIO()) as out:
            self.assertEqual(2, self.ca.main(["--self-test"], query=lambda packages: [[] for _ in packages]))
        self.assertIn("SELF-TEST FAIL", out.getvalue())

    def test_query_error_is_not_reported_as_clean(self):
        def broken(packages):
            raise OSError("sem rede")
        with redirect_stdout(io.StringIO()) as out:
            self.assertEqual(2, self.ca.main([], query=broken))
        self.assertIn("ERRO", out.getvalue())

    def test_repository_lanes_pass_with_clean_osv_and_fail_with_one_hit(self):
        clean = lambda packages: [[] for _ in packages]
        with redirect_stdout(io.StringIO()):
            self.assertEqual(0, self.ca.main([], query=clean))
        one = lambda packages: [["GHSA-y"] if i == 0 else [] for i, _ in enumerate(packages)]
        with redirect_stdout(io.StringIO()) as out:
            self.assertEqual(1, self.ca.main([], query=one))
        self.assertIn("FAIL (1)", out.getvalue())


if __name__ == "__main__":
    unittest.main()
