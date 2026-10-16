#!/usr/bin/env python3
"""Mock-only checks for the N6 J sequential runner and selective cache cleanup."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import n6_j1_cache_cleanup as cleanup  # noqa: E402
import run_policy_a_engine as policy  # noqa: E402
import run_n6_j1 as runner  # noqa: E402


def write_json(path: Path, value: dict) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True) + "\n")
    return runner.sha256(path)


class JRunnerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.engine = self.root / "zkfDO"
        self.circom = self.root / "circom"
        self.engine.write_bytes(b"locked fake engine")
        self.circom.write_bytes(b"locked fake circom")
        self.cache = self.root / "external-cache"
        self.cache.mkdir()
        self.output = self.root / "output"
        self.patches = [
            patch.object(runner, "ROOT", self.root),
            patch.object(runner, "ENGINE", self.engine),
            patch.object(runner, "ENGINE_SHA256", runner.sha256(self.engine)),
            patch.object(runner, "CIRCOM", self.circom),
            patch.object(runner, "CIRCOM_SHA256", runner.sha256(self.circom)),
            patch.object(runner, "probe_time_l", return_value={
                "measurement_method": "wait4", "exit_code": 1,
                "max_rss_bytes": None, "time_probe_failure": "mock"}),
        ]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)

    def make_index(self, specs: list[tuple[str, str, str, int, str | None]]) -> tuple[Path, str]:
        rows = []
        inventory_rows = []
        base_rows = {}
        revision_sources = {}
        for revision in {item[1] for item in specs}:
            source_root = self.root / "sources" / revision
            library = source_root / "libraries"
            library.mkdir(parents=True)
            (library / "include.circom").write_text("template Included() {}\n")
            entrypoint = source_root / "main.circom"
            entrypoint.write_text("pragma circom 2.1.0;\n")
            split_wrapper = source_root / "S.circom"
            split_wrapper.write_text("pragma circom 2.1.0;\n")
            snapshot = {"id": "source", "path": str(source_root),
                        "tree_sha256": policy.tree_sha256(source_root)}
            spec_rows = {}
            for method, target_path in (("W", entrypoint), ("S", split_wrapper)):
                target_id = "sha256:" + hashlib.sha256(
                    f"{revision}:{method}".encode()).hexdigest()
                target = {"target_id": target_id, "source_snapshot_id": "source",
                          "entrypoint_relative": target_path.name,
                          "entrypoint_sha256": runner.sha256(target_path),
                          "preflight_compile_command": [
                              "circom", "{workspace}/" + target_path.name,
                              "-l", "{workspace}", "-l", "{workspace}/libraries"]}
                relative = Path("specs") / f"{revision}-{method}.json"
                digest = write_json(self.root / relative, {
                    "method": "whole" if method == "W" else "split",
                    "source_snapshots": [snapshot], "targets": [target]})
                spec_rows[method] = {"relative": str(relative), "sha256": digest,
                                     "target_id": target_id, "path": target_path}
            revision_sources[revision] = {"root": source_root,
                                          "entrypoint": entrypoint,
                                          "specs": spec_rows}
        for order, (scope, revision, method, attempt, failure) in enumerate(specs):
            source = revision_sources[revision]
            source_root = source["root"]
            entrypoint = source["entrypoint"]
            wrapper = source["specs"][method]["path"]
            if revision not in base_rows:
                base_path = self.root / "base-inputs" / revision / "selected.json"
                if failure is None:
                    base_path.parent.mkdir(parents=True)
                    base_path.write_text("{}\n")
                    base_rows[revision] = {"status": "passed", "base_input_path": str(base_path),
                                           "base_input_sha256": runner.sha256(base_path)}
                else:
                    base_rows[revision] = {"status": "base_input_unavailable",
                                           "base_input_path": None,
                                           "base_input_sha256": None}
            candidate = self.root / "candidates" / f"{order:04d}.json"
            candidate.parent.mkdir(exist_ok=True)
            candidate.write_text(f'{{"synthetic_fixture": {order}}}\n')
            request = self.root / "requests" / f"{order:04d}.json"
            request_sha = write_json(request, {
                "schema": "zkfdo-lifting-request-v1", "id": f"request-{order}",
                "source_root": str(source_root),
                "component_wrapper": str(wrapper),
                "entrypoint": str(entrypoint),
                "library_paths": [str(source_root), str(source_root / "libraries")],
                "base_input": base_rows[revision]["base_input_path"] or
                              str(self.root / "unavailable" / f"{revision}.json"),
                "candidate": {"format": "zkfuzz", "path": str(candidate)},
            })
            rows.append({"scope": scope, "revision_id": revision,
                         "unit_id": f"{revision}-seed-2026100601",
                         "queue_order": order, "seed": 2026100601, "method": method,
                         "attempt_number": attempt, "request": str(request),
                         "request_sha256": request_sha,
                         "target_id": source["specs"][method]["target_id"],
                         "component_wrapper_sha256": runner.sha256(wrapper),
                         "entrypoint_sha256": runner.sha256(entrypoint),
                         "candidate_index": 0,
                         "candidate_path": str(candidate),
                         "candidate_sha256": runner.sha256(candidate),
                         "preparation_failure": failure})
            inventory_rows.append({
                "lane": scope, "identifier": revision,
                "unit_id": f"{revision}-seed-2026100601",
                "seed": 2026100601, "method": method,
                "attempt_index": attempt - 1, "candidate_index": 0,
                "candidate_path": str(candidate),
                "candidate_sha256": runner.sha256(candidate),
                "target_index": 0,
                "target_id": source["specs"][method]["target_id"],
                "source_snapshot_id": "source",
                "whole_spec": source["specs"]["W"]["relative"],
                "whole_spec_sha256": source["specs"]["W"]["sha256"],
                "split_spec": source["specs"]["S"]["relative"],
                "split_spec_sha256": source["specs"]["S"]["sha256"],
            })
        inventory = self.root / "inventory.json"
        inventory_sha = write_json(inventory, {
            "status": "verified", "candidate_count": len(inventory_rows),
            "rows": inventory_rows})
        base_index = self.root / "base-index.json"
        base_index_sha = write_json(base_index, {"schema": "n6-j1-base-inputs-v1",
                                                  "revisions": base_rows})
        index = self.root / "index.json"
        digest = write_json(index, {"schema_version": 1, "status": "verified",
                                    "inventory": str(inventory),
                                    "inventory_sha256": inventory_sha,
                                    "base_index": str(base_index),
                                    "base_index_sha256": base_index_sha,
                                    "engine": str(self.engine),
                                    "engine_sha256": runner.ENGINE_SHA256,
                                    "circom": str(self.circom),
                                    "circom_sha256": runner.CIRCOM_SHA256,
                                    "request_count": len(rows), "requests": rows})
        return index, digest

    @staticmethod
    def fake_lift(calls: list, row: dict, output_dir: Path,
                  cache: Path, store: Path, attempt: int,
                  measurement_method: str) -> dict:
        calls.append((row["queue_order"], str(cache), str(store), attempt))
        output_dir.mkdir(parents=True)
        write_json(output_dir / "result.json", {
            "schema": "zkfdo-lifting-result-v1",
            "request_sha256": row["request_sha256"],
            "candidate_sha256": row["candidate_sha256"],
            "preparation": {"status": "ok"},
            "sites_found": 1,
        })
        return {"exit_code": 0, "wall_seconds": 1.25, "max_rss_bytes": 1234,
                "measurement_method": measurement_method,
                "stdout_path": None, "stderr_path": None}

    @staticmethod
    def fake_join(calls: list, paths: list[Path], output: Path,
                  instance_path: Path, measurement_method: str) -> dict:
        calls.append([str(path) for path in paths])
        write_json(instance_path, {"schema": "zkfdo-instance-verdicts-v1",
                                   "results": [str(path.relative_to(output)) for path in paths],
                                   "conflicts": 0})
        return {"exit_code": 0, "wall_seconds": 0.2, "max_rss_bytes": 2000,
                "measurement_method": measurement_method,
                "stdout_path": None, "stderr_path": None}

    def test_order_revision_isolation_and_resume(self) -> None:
        index, digest = self.make_index([
            ("main", "revision-a", "W", 1, None),
            ("main", "revision-a", "S", 1, None),
            ("main", "revision-b", "W", 1, None),
            ("mem20", "revision-a", "S", 1, None),
        ])
        lifts: list = []
        joins: list = []
        with patch.object(runner, "run_lift", side_effect=lambda *args: self.fake_lift(lifts, *args)), \
                patch.object(runner, "join_instances", side_effect=lambda *args: self.fake_join(joins, *args)), \
                patch.object(runner, "disk_free", return_value=100 * 1024**3):
            state = runner.execute(index, digest, self.cache, self.output)
            resumed = runner.execute(index, digest, self.cache, self.output)
        self.assertEqual([row[0] for row in lifts], [0, 1, 2, 3])
        self.assertEqual(len(joins), 3)
        self.assertEqual(len(resumed["requests"]), 4)
        self.assertEqual(state["status"], "completed")
        self.assertEqual({key: row["status"] for key, row in state["revisions"].items()},
                         {"main/0001": "joined", "main/0002": "joined",
                          "mem20/0001": "joined"})
        self.assertEqual(len({row[1] for row in lifts}), 3)
        self.assertEqual(len({row[2] for row in lifts}), 3)
        self.assertTrue(all(Path(row["instances_path"]).exists()
                            for row in state["revisions"].values()))
        self.assertEqual(len((self.output / "attempts.jsonl").read_text().splitlines()), 7)

    def test_preparation_failure_skipped_and_recorded(self) -> None:
        index, digest = self.make_index([
            ("main", "revision-a", "W", 1, "base_input_unavailable"),
            ("main", "revision-b", "S", 1, None),
        ])
        calls: list = []
        with patch.object(runner, "run_lift", side_effect=lambda *args: self.fake_lift(calls, *args)), \
                patch.object(runner, "join_instances", side_effect=lambda *args: self.fake_join([], *args)), \
                patch.object(runner, "disk_free", return_value=100 * 1024**3):
            state = runner.execute(index, digest, self.cache, self.output)
        self.assertEqual([row[0] for row in calls], [1])
        self.assertEqual(state["requests"]["0"]["status"], "preparation_failure")
        self.assertIsNone(state["requests"]["0"]["result_path"])

    def test_disk_guard_stops_before_lift(self) -> None:
        index, digest = self.make_index([("main", "revision-a", "W", 1, None)])
        with patch.object(runner, "disk_free", return_value=39 * 1024**3), \
                patch.object(runner, "run_lift") as lift:
            with self.assertRaises(runner.DiskGuardStop):
                runner.execute(index, digest, self.cache, self.output)
        lift.assert_not_called()
        state = json.loads((self.output / "state.json").read_text())
        self.assertEqual(state["status"], "disk_guard_stopped")
        self.assertEqual(state["next_queue_order"], 0)

    def test_hash_mismatch_rejected_before_output(self) -> None:
        index, digest = self.make_index([("main", "revision-a", "W", 1, None)])
        request = self.root / "requests/0000.json"
        request.write_text(request.read_text() + " ")
        with self.assertRaisesRegex(runner.RunnerError, "SHA-256 mismatch"):
            runner.execute(index, digest, self.cache, self.output)
        self.assertFalse(self.output.exists())

    def test_wrapper_byte_change_rejected_before_output(self) -> None:
        index, digest = self.make_index([("main", "revision-a", "S", 1, None)])
        wrapper = self.root / "sources/revision-a/S.circom"
        wrapper.write_text(wrapper.read_text() + "// changed\n")
        with self.assertRaises(runner.RunnerError):
            runner.execute(index, digest, self.cache, self.output)
        self.assertFalse(self.output.exists())

    def test_included_source_byte_change_rejected_before_output(self) -> None:
        index, digest = self.make_index([("main", "revision-a", "S", 1, None)])
        include = self.root / "sources/revision-a/libraries/include.circom"
        include.write_text(include.read_text() + "// changed\n")
        with self.assertRaises(runner.RunnerError) as raised:
            runner.execute(index, digest, self.cache, self.output)
        self.assertRegex(str(raised.exception).lower(), "snapshot|tree")
        self.assertFalse(self.output.exists())

    def test_library_path_order_change_rejected_before_output(self) -> None:
        index, _ = self.make_index([("main", "revision-a", "S", 1, None)])
        index_json = json.loads(index.read_text())
        request = Path(index_json["requests"][0]["request"])
        request_json = json.loads(request.read_text())
        request_json["library_paths"].reverse()
        index_json["requests"][0]["request_sha256"] = write_json(request, request_json)
        digest = write_json(index, index_json)
        with self.assertRaises(runner.RunnerError) as raised:
            runner.execute(index, digest, self.cache, self.output)
        self.assertIn("library", str(raised.exception).lower())
        self.assertFalse(self.output.exists())

    def test_spec_byte_change_rejected_before_output(self) -> None:
        index, digest = self.make_index([("main", "revision-a", "S", 1, None)])
        spec = self.root / "specs/revision-a-S.json"
        spec.write_text(spec.read_text() + " ")
        with self.assertRaises(runner.RunnerError) as raised:
            runner.execute(index, digest, self.cache, self.output)
        self.assertIn("spec", str(raised.exception).lower())
        self.assertFalse(self.output.exists())

    def test_index_target_id_change_rejected_before_output(self) -> None:
        index, _ = self.make_index([("main", "revision-a", "S", 1, None)])
        index_json = json.loads(index.read_text())
        index_json["requests"][0]["target_id"] = "sha256:" + "0" * 64
        digest = write_json(index, index_json)
        with self.assertRaises(runner.RunnerError) as raised:
            runner.execute(index, digest, self.cache, self.output)
        self.assertIn("candidate binding", str(raised.exception).lower())
        self.assertFalse(self.output.exists())

    def test_inventory_target_id_change_rejected_against_spec(self) -> None:
        index, _ = self.make_index([("main", "revision-a", "S", 1, None)])
        index_json = json.loads(index.read_text())
        inventory = Path(index_json["inventory"])
        inventory_json = json.loads(inventory.read_text())
        wrong_id = "sha256:" + "0" * 64
        inventory_json["rows"][0]["target_id"] = wrong_id
        index_json["inventory_sha256"] = write_json(inventory, inventory_json)
        index_json["requests"][0]["target_id"] = wrong_id
        digest = write_json(index, index_json)
        with self.assertRaises(runner.RunnerError) as raised:
            runner.execute(index, digest, self.cache, self.output)
        self.assertIn("target id", str(raised.exception).lower())
        self.assertFalse(self.output.exists())

    def test_noncontiguous_revision_order_rejected(self) -> None:
        index, digest = self.make_index([
            ("main", "revision-a", "W", 1, None),
            ("main", "revision-b", "W", 1, None),
            ("main", "revision-a", "S", 1, None),
        ])
        with self.assertRaisesRegex(runner.RunnerError, "noncontiguous revision"):
            runner.execute(index, digest, self.cache, self.output)
        self.assertFalse(self.output.exists())

    def test_failed_attempt_result_does_not_count_as_completed(self) -> None:
        index, digest = self.make_index([("main", "revision-a", "W", 1, None)])
        calls: list = []

        def failed_lift(row: dict, output_dir: Path, cache: Path,
                        store: Path, attempt: int, measurement_method: str) -> dict:
            metrics = self.fake_lift(calls, row, output_dir, cache, store, attempt,
                                     measurement_method)
            metrics["exit_code"] = 7
            return metrics

        with patch.object(runner, "run_lift", side_effect=failed_lift), \
                patch.object(runner, "disk_free", return_value=100 * 1024**3):
            with self.assertRaisesRegex(runner.RunnerError, "lift exit 7"):
                runner.execute(index, digest, self.cache, self.output)
        with patch.object(runner, "run_lift", side_effect=lambda *args: self.fake_lift(calls, *args)), \
                patch.object(runner, "join_instances", side_effect=lambda *args: self.fake_join([], *args)), \
                patch.object(runner, "disk_free", return_value=100 * 1024**3):
            state = runner.execute(index, digest, self.cache, self.output)
        self.assertEqual([row[3] for row in calls], [1, 2])
        self.assertEqual(state["requests"]["0"]["status"], "completed")
        self.assertEqual(state["requests"]["0"]["attempt"], 2)

    def test_zero_exit_preparation_failure_is_recorded_and_rejected_on_resume(self) -> None:
        index, digest = self.make_index([("main", "revision-a", "W", 1, None)])
        calls: list = []

        def bad_lift(row, output_dir, cache, store, attempt, measurement_method):
            metrics = self.fake_lift(calls, row, output_dir, cache, store, attempt,
                                     measurement_method)
            result_path = output_dir / "result.json"
            result = json.loads(result_path.read_text())
            result["preparation"] = {"status": "preparation_failure"}
            write_json(result_path, result)
            return metrics

        with patch.object(runner, "run_lift", side_effect=bad_lift), \
                patch.object(runner, "disk_free", return_value=100 * 1024**3):
            with self.assertRaisesRegex(runner.RunnerError, "preparation_not_ok"):
                runner.execute(index, digest, self.cache, self.output)
        state = json.loads((self.output / "state.json").read_text())
        self.assertEqual(state["status"], "result_invalid")
        self.assertEqual(state["requests"]["0"]["status"], "failed")
        self.assertEqual(state["requests"]["0"]["failure_reason"], "preparation_not_ok")
        ledger = [json.loads(line) for line in (self.output / "attempts.jsonl").read_text().splitlines()]
        self.assertEqual(ledger[-1]["failure_reason"], "preparation_not_ok")
        with patch.object(runner, "run_lift") as retry, \
                patch.object(runner, "disk_free", return_value=100 * 1024**3):
            with self.assertRaisesRegex(runner.RunnerError,
                                        "invalid previous zero-exit result"):
                runner.execute(index, digest, self.cache, self.output)
        retry.assert_not_called()
        resumed_state = json.loads((self.output / "state.json").read_text())
        self.assertEqual(resumed_state["status"], "result_invalid")
        self.assertEqual(resumed_state["next_queue_order"], 0)

    def test_zero_exit_w_without_main_site_is_recorded(self) -> None:
        index, digest = self.make_index([("main", "revision-a", "W", 1, None)])

        def bad_lift(row, output_dir, cache, store, attempt, measurement_method):
            metrics = self.fake_lift([], row, output_dir, cache, store, attempt,
                                     measurement_method)
            result_path = output_dir / "result.json"
            result = json.loads(result_path.read_text())
            result["sites_found"] = 0
            write_json(result_path, result)
            return metrics

        with patch.object(runner, "run_lift", side_effect=bad_lift), \
                patch.object(runner, "disk_free", return_value=100 * 1024**3):
            with self.assertRaisesRegex(runner.RunnerError, "w_main_site_missing"):
                runner.execute(index, digest, self.cache, self.output)
        state = json.loads((self.output / "state.json").read_text())
        self.assertEqual(state["requests"]["0"]["status"], "failed")
        self.assertEqual(state["requests"]["0"]["failure_reason"], "w_main_site_missing")

    def test_zero_exit_missing_rss_is_recorded(self) -> None:
        index, digest = self.make_index([("main", "revision-a", "S", 1, None)])

        def bad_lift(row, output_dir, cache, store, attempt, measurement_method):
            metrics = self.fake_lift([], row, output_dir, cache, store, attempt,
                                     measurement_method)
            metrics["max_rss_bytes"] = None
            return metrics

        with patch.object(runner, "run_lift", side_effect=bad_lift), \
                patch.object(runner, "disk_free", return_value=100 * 1024**3):
            with self.assertRaisesRegex(runner.RunnerError, "max_rss_missing_or_invalid"):
                runner.execute(index, digest, self.cache, self.output)
        state = json.loads((self.output / "state.json").read_text())
        self.assertEqual(state["requests"]["0"]["status"], "failed")
        self.assertEqual(state["requests"]["0"]["failure_reason"],
                         "max_rss_missing_or_invalid")

    def test_runner_optional_cleanup_after_join(self) -> None:
        index, digest = self.make_index([("main", "revision-a", "W", 1, None)])
        calls: list = []
        with patch.object(runner, "run_lift", side_effect=lambda *args: self.fake_lift(calls, *args)), \
                patch.object(runner, "join_instances", side_effect=lambda *args: self.fake_join([], *args)), \
                patch.object(runner, "disk_free", return_value=100 * 1024**3):
            state = runner.execute(index, digest, self.cache, self.output,
                                   cleanup_cache_per_revision=True)
        revision = state["revisions"]["main/0001"]
        self.assertEqual(revision["status"], "joined")
        self.assertEqual(revision["cleanup"]["status"], "deleted")
        self.assertTrue(Path(revision["instances_path"]).exists())
        self.assertTrue(Path(revision["cleanup"]["manifest"]).exists())
        self.assertFalse(Path(revision["cache_path"]).exists())

    def test_instance_conflict_is_rejected(self) -> None:
        index, digest = self.make_index([("main", "revision-a", "W", 1, None)])

        def conflicting_join(paths, output, instance_path, measurement_method):
            write_json(instance_path, {
                "schema": "zkfdo-instance-verdicts-v1",
                "results": [str(path.relative_to(output)) for path in paths],
                "conflicts": 1,
            })
            return {"exit_code": 0, "wall_seconds": 0.1,
                    "max_rss_bytes": 100, "measurement_method": measurement_method,
                    "stdout_path": None, "stderr_path": None}

        with patch.object(runner, "run_lift", side_effect=lambda *args: self.fake_lift([], *args)), \
                patch.object(runner, "join_instances", side_effect=conflicting_join), \
                patch.object(runner, "disk_free", return_value=100 * 1024**3):
            with self.assertRaisesRegex(runner.RunnerError, "lift-instances output mismatch"):
                runner.execute(index, digest, self.cache, self.output)
        self.assertFalse((self.output / "main/0001/instances.json").exists())

    def test_cleanup_records_hash_before_selective_delete(self) -> None:
        index_sha = "a" * 64
        first = cleanup.initialize_cache(self.cache, "main", 1, "revision-a", index_sha)
        second = cleanup.initialize_cache(self.cache, "main", 2, "revision-b", index_sha)
        shared_content_key = "b" * 64
        (first / shared_content_key).mkdir()
        (second / shared_content_key).mkdir()
        artifact = first / shared_content_key / "compiled.r1cs"
        artifact.write_bytes(b"synthetic compilation")
        (second / shared_content_key / "compiled.r1cs").write_bytes(b"other revision")
        self.output.mkdir()
        store = self.output / "main/0001/store/saved.json"
        store.parent.mkdir(parents=True)
        store.write_text("saved\n")
        dry = cleanup.cleanup_revision(self.cache, self.output, "main", 1,
                                       "revision-a", index_sha)
        self.assertEqual(dry["status"], "dry_run")
        self.assertTrue(artifact.exists())
        deleted = cleanup.cleanup_revision(self.cache, self.output, "main", 1,
                                           "revision-a", index_sha, delete=True)
        manifest = json.loads(Path(deleted["manifest"]).read_text())
        row = next(row for row in manifest["files"]
                   if row["path"] == f"{shared_content_key}/compiled.r1cs")
        self.assertEqual(row["sha256"], hashlib.sha256(b"synthetic compilation").hexdigest())
        self.assertEqual(row["bytes"], len(b"synthetic compilation"))
        self.assertEqual(manifest["content_keys"], [shared_content_key])
        self.assertEqual(manifest["content_key_namespace"], str(first))
        self.assertFalse(first.exists())
        self.assertTrue((second / shared_content_key / "compiled.r1cs").exists())
        self.assertTrue(store.exists())


if __name__ == "__main__":
    unittest.main()
