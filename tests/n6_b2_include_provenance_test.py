"""Small checks for B include provenance, including absolute Circom includes."""

from pathlib import Path
import tempfile
import unittest

from scripts import n6_b2_include_provenance as provenance


class N6B2IncludeProvenanceTest(unittest.TestCase):
    def test_absolute_include_compares_mirrored_snapshot_copy(self):
        with tempfile.TemporaryDirectory(dir=provenance.ROOT / "runs") as raw:
            base = Path(raw)
            original = base / "source.circom"
            original.write_text("pragma circom 2.2.1;\n")
            workspace = base / "prepared"
            mirror = workspace / original.relative_to(provenance.ROOT / "runs")
            mirror.parent.mkdir(parents=True)
            mirror.write_bytes(original.read_bytes())
            rows = provenance.snapshot_comparisons(
                str(original), original, workspace, []
            )
            self.assertEqual(len(rows), 1)
            self.assertTrue(rows[0]["matches_external"])
            mirror.write_text("pragma circom 2.2.2;\n")
            provenance._HASHES.pop(str(mirror.absolute()), None)
            rows = provenance.snapshot_comparisons(
                str(original), original, workspace, []
            )
            self.assertFalse(rows[0]["matches_external"])

    def test_library_root_compares_flattened_clone_copy(self):
        with tempfile.TemporaryDirectory(dir=provenance.ROOT / "runs") as raw:
            base = Path(raw)
            clone = base / "repositories" / "example" / "clone"
            original = clone / "node_modules" / "lib" / "circuit.circom"
            original.parent.mkdir(parents=True)
            original.write_text("pragma circom 2.2.1;\n")
            workspace = base / "prepared"
            copy = workspace / original.relative_to(clone)
            copy.parent.mkdir(parents=True)
            copy.write_bytes(original.read_bytes())

            rows = provenance.snapshot_comparisons(
                "node_modules/lib/circuit.circom", original, workspace, [clone],
            )
            self.assertEqual([row["path"] for row in rows],
                             [provenance.relative_or_absolute(copy)])
            self.assertTrue(rows[0]["matches_external"])
            # A transitive include reaches the same external file through the
            # including-file directory, without selecting a -l root again.
            transitive = provenance.snapshot_comparisons(
                "circuit.circom", original, workspace, [],
            )
            self.assertEqual(transitive, rows)

            copy.write_text("pragma circom 2.2.2;\n")
            provenance._HASHES.pop(str(copy.absolute()), None)
            rows = provenance.snapshot_comparisons(
                "node_modules/lib/circuit.circom", original, workspace, [clone],
            )
            self.assertFalse(rows[0]["matches_external"])

    def test_corrected_project_root_compares_flattened_snapshot(self):
        with tempfile.TemporaryDirectory(dir=provenance.ROOT / "runs") as raw:
            base = Path(raw)
            project = base / "correction" / "project"
            original = project / "circuits" / "lib.circom"
            original.parent.mkdir(parents=True)
            original.write_text("pragma circom 2.2.1;\n")
            workspace = base / "corrected-snapshot"
            copy = workspace / "circuits" / "lib.circom"
            copy.parent.mkdir(parents=True)
            copy.write_bytes(original.read_bytes())
            rows = provenance.snapshot_comparisons(
                "lib.circom", original, workspace, [project],
            )
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["path"], provenance.relative_or_absolute(copy))
            self.assertTrue(rows[0]["matches_external"])

    def test_corrected_project_root_compares_nested_clone_snapshot(self):
        with tempfile.TemporaryDirectory(dir=provenance.ROOT / "runs") as raw:
            base = Path(raw)
            project = base / "correction" / "project"
            original = project / "circuits" / "lib.circom"
            original.parent.mkdir(parents=True)
            original.write_text("pragma circom 2.2.1;\n")
            workspace = base / "corrected-snapshot"
            clone = workspace / "repositories" / "example" / "clone"
            copy = clone / "circuits" / "lib.circom"
            copy.parent.mkdir(parents=True)
            copy.write_bytes(original.read_bytes())
            rows = provenance.snapshot_comparisons(
                "lib.circom", original, workspace, [clone, project],
            )
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["path"], provenance.relative_or_absolute(copy))
            self.assertTrue(rows[0]["matches_external"])

    def test_external_unique_file_keeps_copies_from_all_closures(self):
        files = {}
        empty = {"path": "runs/example.circom", "sha256": "a" * 64,
                 "include": "example.circom", "snapshot_copies": []}
        with_copy = {**empty, "snapshot_copies": [
            {"path": "runs/snapshot/example.circom", "sha256": "a" * 64,
             "matches_external": True},
        ]}
        provenance.add_external_file(files, empty)
        provenance.add_external_file(files, with_copy)
        self.assertEqual(len(files), 1)
        row = next(iter(files.values()))
        self.assertEqual(row["reference_count"], 2)
        self.assertEqual(row["snapshot_copies"], with_copy["snapshot_copies"])


if __name__ == "__main__":
    unittest.main()
