import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import e01_environment as environment


class E01EnvironmentTest(unittest.TestCase):
    def test_yarn_berry_plan_uses_declared_version(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "package.json").write_text(json.dumps({"packageManager": "yarn@4.3.1"}))
            (root / "yarn.lock").write_text("__metadata:\n  version: 8\n")
            plan = environment.plan_installations(root, [root])[0]
            self.assertEqual(plan["manager"], "yarn_berry")
            self.assertEqual(plan["tool_key"], "yarn@4.3.1")

    def test_pnpm_plan_uses_declared_version(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "package.json").write_text(json.dumps({"packageManager": "pnpm@11.12.0"}))
            (root / "pnpm-lock.yaml").write_text("lockfileVersion: '9.0'\n")
            plan = environment.plan_installations(root, [root])[0]
            self.assertEqual(plan["tool_key"], "pnpm@11.12.0")

    def test_https_rewrite_does_not_modify_gitmodules(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = '[submodule "x"]\n path = x\n url = git@github.com:owner/repo.git\n'
            (root / ".gitmodules").write_text(source)
            self.assertEqual(environment._https_rewrites(root), [{
                "original": "git@github.com:owner/repo.git",
                "https": "https://github.com/owner/repo.git",
            }])
            self.assertEqual((root / ".gitmodules").read_text(), source)


if __name__ == "__main__":
    unittest.main()
