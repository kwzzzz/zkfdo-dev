"""Synthetic, value-free checks for the B6e request index release path."""

from __future__ import annotations

from contextlib import ExitStack
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import n6_b6e_b_requests as subject  # noqa: E402


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_json(path: Path, value: object) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")
    return subject.sha256_file(path)


def pair_orders(pair_number: int) -> list[int]:
    if pair_number < 3:
        return list(range(pair_number * 3, (pair_number + 1) * 3))
    start = 9 + (pair_number - 3) * 7
    return list(range(start, start + 7))


class B6eIndexIndependentTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.out = self.root / "fresh-output"
        self.paths = {
            "OUT": self.out,
            "E2_AUDIT": self.out / "e2.json",
            "GATE": self.out / "gate.json",
            "PLAN": self.out / "plan.json",
            "INDEX_V1": self.out / "index-v1.json",
            "INDEX_V22": self.out / "index-v22.json",
            "REQUESTS": self.out / "requests",
            "SELECTION": self.out / "selection.json",
            "CHANGE_AUDIT": self.out / "changes.json",
        }
        self.base_path = self.root / "base-index.json"
        base = {"revisions": {
            revision: {"base_input_path": f"/missing/base/{revision}.json",
                       "base_input_sha256": digest(revision.encode())}
            for revision in ("anon", "other")}}
        self.base_sha = write_json(self.base_path, base)
        self.pairs = []
        for number in range(17):
            pair_id = f"pair-{number:02d}"
            revision = "anon" if number < 3 else "other"
            self.pairs.append({
                "pair_id": pair_id, "revision_id": revision,
                "queue_orders": pair_orders(number),
                "source_root": f"/synthetic-unit/{pair_id}",
                "entrypoint": f"/synthetic-unit/{pair_id}/project/main.circom",
                "wrapper": f"/synthetic-unit/{pair_id}/preparation/wrapper.circom",
                "wrapper_sha256": digest(f"new-{pair_id}".encode()),
                "original_wrapper_sha256": digest(f"old-{pair_id}".encode()),
                "library_paths": [f"/synthetic-unit/{pair_id}/project/lib"],
                "original_library_paths": [f"/old-clone/{pair_id}/lib"],
            })
        by_order = {order: pair for pair in self.pairs
                    for order in pair["queue_orders"]}
        self.source_rows = []
        self.source_plans = []
        self.old_requests = []
        for order in range(107):
            pair = by_order[order]
            request_id = f"request-{order:03d}"
            candidate_path = f"/does-not-exist/candidate-{order:03d}.json"
            old = {
                "id": request_id,
                "candidate": {"path": candidate_path,
                              "sha256": digest(request_id.encode())},
                "base_input": base["revisions"][pair["revision_id"]]
                              ["base_input_path"],
                "source_root": f"/old-clone/{pair['pair_id']}",
                "component_wrapper": f"/old-clone/{pair['pair_id']}/wrapper.circom",
                "entrypoint": f"/old-clone/{pair['pair_id']}/main.circom",
                "library_paths": pair["original_library_paths"],
            }
            path = self.root / "old-requests" / f"{request_id}.json"
            old_sha = write_json(path, old)
            self.old_requests.append(old)
            self.source_plans.append({
                "request": str(path), "candidate_path": candidate_path,
                "source_root": old["source_root"],
                "component_wrapper": old["component_wrapper"],
                "entrypoint": old["entrypoint"],
                "library_paths": old["library_paths"],
            })
            self.source_rows.append({
                "queue_order": order, "scope": "main",
                "revision_id": pair["revision_id"],
                "request": str(path), "request_sha256": old_sha,
                "candidate_sha256": digest(f"candidate-{order}".encode()),
                "component_wrapper_sha256":
                    pair["original_wrapper_sha256"],
                "preparation_failure": None,
            })
        self.source_plan = {"request_count": 107,
                            "requests": self.source_plans}
        self.source_index = {
            "request_count": 107, "requests": self.source_rows,
            "base_index": str(self.base_path),
            "base_index_sha256": self.base_sha,
            "engine": "/fixed/v1", "engine_sha256": digest(b"v1"),
        }
        self.source_plan_path = self.root / "source-plan.json"
        self.source_index_path = self.root / "source-index.json"
        self.source_v22_path = self.root / "source-index-v22.json"
        write_json(self.source_plan_path, self.source_plan)
        self.source_index_sha = write_json(self.source_index_path,
                                           self.source_index)
        self.source_v22_sha = write_json(
            self.source_v22_path,
            {**self.source_index, "engine": "/fixed/v22",
             "engine_sha256": digest(b"v22")})
        self.manifest = {"source_index_sha256": self.source_index_sha,
                         "pairs": self.pairs}
        self.revised = {
            "a": {"pairs": []},
            "b": {"pairs": [
                {"pair_id": pair["pair_id"],
                 "original_duplicate": number < 3}
                for number, pair in enumerate(self.pairs)]},
        }

    def patches(self) -> ExitStack:
        stack = ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(patch.multiple(subject, **self.paths))
        stack.enter_context(patch.multiple(
            subject.b6d,
            SOURCE_PLAN=self.source_plan_path,
            SOURCE_INDEX=self.source_index_path,
            SOURCE_INDEX_SHA=self.source_index_sha,
            SOURCE_INDEX_V22=self.source_v22_path,
            SOURCE_INDEX_V22_SHA=self.source_v22_sha,
            MANIFEST=self.root / "manifest.json"))
        stack.enter_context(patch.object(subject, "checked_gate",
                                         return_value=(self.manifest,
                                                       self.revised)))
        stack.enter_context(patch.object(
            subject.b6d, "source_rows",
            return_value=(self.source_plan, self.source_index,
                          self.source_plans)))
        stack.enter_context(patch.object(
            subject.selection, "select_requests",
            side_effect=lambda index, _base:
                [index["requests"][9], index["requests"][25]]))
        return stack

    def test_index_preserves_identity_and_candidate_hash_without_candidate_file(self) -> None:
        self.patches()
        gate_sha = write_json(self.paths["GATE"], {"status": "passed"})
        write_json(self.paths["E2_AUDIT"], {"status": "pass"})
        index = subject.make_index()
        self.assertEqual(index["request_count"], 107)
        self.assertEqual(index["equivalence_gate_sha256"], gate_sha)
        self.assertEqual(len(index["requests"]), 107)
        self.assertEqual({row["queue_order"] for row in index["requests"]},
                         set(range(107)))
        self.assertEqual([row["original_template_duplicate"]
                          for row in index["requests"]],
                         [order < 9 for order in range(107)])
        for order, row in enumerate(index["requests"]):
            original = self.source_rows[order]
            self.assertEqual(row["candidate_sha256"],
                             original["candidate_sha256"])
            self.assertEqual(row["original_request_sha256"],
                             original["request_sha256"])
            request = subject.read_object(Path(row["request"]))
            self.assertEqual(request["id"], self.old_requests[order]["id"])
            self.assertEqual(request["candidate"],
                             self.old_requests[order]["candidate"])
            self.assertEqual(request["base_input"],
                             self.old_requests[order]["base_input"])
            self.assertEqual(set(request).difference(self.old_requests[order]),
                             set())
            self.assertNotIn("original_template_duplicate", request)
            self.assertEqual(row["request_sha256"],
                             subject.sha256_file(Path(row["request"])))
        self.assertEqual(subject.read_object(self.paths["SELECTION"])
                         ["requests"][0]["queue_order"], 9)
        self.assertEqual(subject.read_object(self.paths["SELECTION"])
                         ["requests"][1]["queue_order"], 25)

    def test_existing_output_is_not_overwritten(self) -> None:
        self.patches()
        self.paths["INDEX_V1"].parent.mkdir(parents=True)
        self.paths["INDEX_V1"].write_bytes(b"do not overwrite")
        with self.assertRaisesRegex(ValueError, "already exists"):
            subject.make_index()
        self.assertEqual(self.paths["INDEX_V1"].read_bytes(),
                         b"do not overwrite")
        self.assertFalse(self.paths["REQUESTS"].exists())

    def evidence_fixture(self) -> tuple[ExitStack, dict[str, object]]:
        manifest_path = self.root / "manifest.json"
        manifest_sha = write_json(manifest_path, self.manifest)
        old_b = {
            "staging_manifest_sha256": manifest_sha,
            "original_b_index": str(self.source_index_path),
            "original_b_index_sha256": self.source_index_sha,
            "b": {
                "e1": {"status": "pass"}, "e2": {"status": "fail"},
                "request_count": 107, "pair_count": 17,
                "pairs": [
                    {"pair_id": pair["pair_id"],
                     "revision_id": pair["revision_id"],
                     "queue_orders": pair["queue_orders"],
                     "original_main_template_file_count":
                         2 if number < 3 else 1,
                     "staged_main_template_file_count":
                         2 if number < 3 else 1}
                    for number, pair in enumerate(self.pairs)],
            },
        }
        old_a = {"a": {"status": "pass", "request_count": 2926,
                       "revision_count": 26}}
        r1cs = {"e3_passed": True, "e4_passed": True,
                "pair_count": 17, "request_count": 107,
                "unit_manifest_sha256": manifest_sha}
        old_b_path = self.root / "old-b-audit.json"
        old_a_path = self.root / "old-a-audit.json"
        r1cs_path = self.root / "r1cs.json"
        old_b_sha = write_json(old_b_path, old_b)
        old_a_sha = write_json(old_a_path, old_a)
        r1cs_sha = write_json(r1cs_path, r1cs)
        revised = {
            "schema_version": 2, "status": "pass",
            "b6d_b_audit_sha256": old_b_sha,
            "b6d_a_audit_sha256": old_a_sha,
            "b_original_index_sha256": self.source_index_sha,
            "b": {
                "status": "pass", "request_count": 107, "pair_count": 17,
                "original_duplicate_request_count": 9,
                "pairs": [
                    {"pair_id": pair["pair_id"], "status": "pass",
                     "revision_id": pair["revision_id"],
                     "queue_orders": pair["queue_orders"],
                     "original_duplicate": number < 3}
                    for number, pair in enumerate(self.pairs)],
            },
            "a": {"status": "pass", "request_count": 2926,
                  "revision_count": 26, "pairs": []},
        }
        write_json(self.paths["E2_AUDIT"], revised)
        instruction_path = self.root / "instruction.md"
        instruction_path.write_text("synthetic instruction\n", encoding="utf-8")
        stack = ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(patch.multiple(subject, **self.paths))
        stack.enter_context(patch.multiple(
            subject, INSTRUCTION=instruction_path,
            INSTRUCTION_SHA=subject.sha256_file(instruction_path),
            B6D_MANIFEST_SHA=manifest_sha,
            B6D_B_AUDIT_SHA=old_b_sha,
            B6D_A_AUDIT_SHA=old_a_sha,
            B6D_R1CS_SHA=r1cs_sha,
            B6_ORIGINAL_INDEX_SHA=self.source_index_sha))
        stack.enter_context(patch.multiple(
            subject.b6d, MANIFEST=manifest_path, B_CLOSURE=old_b_path,
            A_CLOSURE=old_a_path, R1CS_EVIDENCE=r1cs_path,
            SOURCE_INDEX_SHA=self.source_index_sha))
        stack.enter_context(patch.object(
            subject.b6d, "verify_stage",
            return_value={"e4_passed": True, "project_file_count": 3872}))
        return stack, revised

    def test_revised_e2_accepts_only_matching_original_duplicate(self) -> None:
        _stack, revised = self.evidence_fixture()
        manifest, checked, _stage = subject.evidence()
        self.assertEqual(manifest, self.manifest)
        self.assertEqual(checked, revised)
        gate = subject.make_gate()
        self.assertEqual(gate["original_template_duplicate_queue_orders"],
                         list(range(9)))
        self.assertEqual(subject.checked_gate()[0], self.manifest)
        revised["b"]["pairs"][0]["original_duplicate"] = False
        write_json(self.paths["E2_AUDIT"], revised)
        with self.assertRaisesRegex(ValueError,
                                    "unmarked main template is not unique"):
            subject.evidence()

    def test_missing_e1_blocks_gate_creation(self) -> None:
        _stack, _revised = self.evidence_fixture()
        old_b_path = subject.b6d.B_CLOSURE
        old_b = subject.read_object(old_b_path)
        old_b["b"]["e1"]["status"] = "fail"
        write_json(old_b_path, old_b)
        with self.assertRaisesRegex(ValueError, "input SHA-256 differs"):
            subject.make_gate()
        self.assertFalse(self.paths["GATE"].exists())


if __name__ == "__main__":
    unittest.main()
