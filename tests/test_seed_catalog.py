import os
import subprocess
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "seed-catalog.sh"


class SeedCatalogSafetyTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.archive = self.root / "seed.archive.gz"
        self.archive.touch()
        self.calls = self.root / "calls.log"

        self.command("mongosh", '''#!/bin/sh
echo "mongosh $*" >> "$CALL_LOG"
case "$*" in
  *"updateOne"*) echo "seed local concluído" ;;
  *) echo "$MOCK_CATALOG_COUNT" ;;
esac
''')
        self.command("mongorestore", '''#!/bin/sh
echo "mongorestore $*" >> "$CALL_LOG"
''')
        self.command("tar", '''#!/bin/sh
echo "tar $*" >> "$CALL_LOG"
mkdir -p "$4/mongo-backups/scripts/scripts"
''')

    def tearDown(self):
        self.temp.cleanup()

    def command(self, name, contents):
        path = self.bin / name
        path.write_text(contents)
        path.chmod(0o755)

    def run_seed(self, catalog_count):
        env = os.environ.copy()
        env.update(
            PATH=f"{self.bin}:{env['PATH']}",
            CALL_LOG=str(self.calls),
            MOCK_CATALOG_COUNT=str(catalog_count),
            SEED_ARCHIVE=str(self.archive),
        )
        return subprocess.run(
            ["bash", str(SCRIPT)],
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_existing_catalog_never_runs_destructive_restore(self):
        result = self.run_seed(7)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Seed automático ignorado", result.stdout)
        calls = self.calls.read_text()
        self.assertNotIn("mongorestore", calls)
        self.assertNotIn("tar ", calls)

    def test_empty_catalog_loads_development_seed(self):
        result = self.run_seed(0)

        self.assertEqual(result.returncode, 0, result.stderr)
        calls = self.calls.read_text()
        self.assertIn("tar ", calls)
        self.assertIn("mongorestore", calls)
        self.assertIn("updateOne", calls)


if __name__ == "__main__":
    unittest.main()
