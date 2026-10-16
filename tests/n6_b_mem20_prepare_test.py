"""Fake-ledger tests for N6-B 20 GiB queue preparation; no B campaign data."""

import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts/n6_b_mem20_prepare.py"
SPEC = importlib.util.spec_from_file_location("n6_b_mem20_prepare_test_module", MODULE_PATH)
prepare_module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = prepare_module
SPEC.loader.exec_module(prepare_module)


class FakeBRun:
    def __init__(self, root: Path):
        self.root = root
        self.main = root / "runs/b-main.noindex"
        self.queue_path = root / "runs/base/queue.json"
        self.output = root / "runs/n6-b2.noindex/mem20"
        self.runner = root / "scripts/run_n6_v4_3_queue.py"
        self.runner.parent.mkdir(parents=True)
        self.runner.write_text("# fake queue runner\n")
        self.units = []
        self.proof_rows = {}
        self.state_units = {}
        self.ledger_paths = {}
        for unit_id in ("u0", "u1", "u2"):
            self._add_unit(unit_id)
        self._write_queue_and_state()

    def relative(self, path: Path) -> str:
        return path.relative_to(self.root).as_posix()

    @staticmethod
    def save(path: Path, value: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")

    def _add_unit(self, unit_id: str) -> None:
        unit = {"unit_id": unit_id, "seed": 2026100601,
                "resource_class": "normal"}
        for method, name in (("W", "whole"), ("S", "split")):
            spec_path = self.root / "runs/base/specs" / f"{unit_id}-{method}.json"
            spec = {"schema_version": 1,
                    "campaign_id": f"N6-B-v4-stage1-{unit_id}-{name}",
                    "memory_cap_bytes": prepare_module.SOURCE_CAP,
                    "total_budget_seconds": 3600,
                    "attempt_cap_seconds": 3600 if method == "W" else 30,
                    "concurrency": 1,
                    "method": name,
                    "targets": [{"target_id": unit_id}],
                    "source_snapshots": [{"id": "sample"}]}
            self.save(spec_path, spec)
            unit[f"{name}_spec"] = self.relative(spec_path)
            unit[f"{name}_spec_sha256"] = prepare_module.sha256(spec_path)

            preflight = self.root / "runs/base/preflight" / unit_id / method / "preflight.json"
            snapshot = preflight.parent / "snapshots/sample"
            snapshot.mkdir(parents=True, exist_ok=True)
            (snapshot / "source.circom").write_text("pragma circom 2.1.0;\n")
            self.save(preflight, {"kind": "policy_a_preflight", "status": "passed",
                                  "spec_sha256": prepare_module.sha256(spec_path),
                                  "source_snapshots": [{"id": "sample",
                                                        "copied_path": "snapshots/sample"}],
                                  "compile": []})
            self.proof_rows[f"{unit_id}:{method}"] = {
                "status": "passed",
                "source_preflight": self.relative(preflight),
                "source_preflight_sha256": prepare_module.sha256(preflight),
                "destination_preflight": self.relative(preflight),
                "destination_preflight_sha256": prepare_module.sha256(preflight),
                "destination_spec": self.relative(spec_path),
                "destination_spec_sha256": prepare_module.sha256(spec_path),
            }
        self.units.append(unit)
        self.set_runs(unit_id, [(False, 0, 0)])

    def set_runs(self, unit_id: str, runs: list[tuple[bool, int, int]]) -> None:
        rows = []
        for number, (pressure, w_count, s_count) in enumerate(runs, start=1):
            kind = "primary" if number == 1 else "pressure_retry"
            methods = {}
            for method, count in (("W", w_count), ("S", s_count)):
                ledger = (self.main / "units" / unit_id / "runs"
                          / f"{number:02d}-{kind}" / method / "campaign/ledger.json")
                unit = next(row for row in self.units if row["unit_id"] == unit_id)
                name = "whole" if method == "W" else "split"
                self.save(ledger, {
                    "spec_sha256": unit[f"{name}_spec_sha256"],
                    "outcome_counts": {"memory_cap": count, "candidate": 99},
                })
                self.ledger_paths[(unit_id, number, method)] = ledger
                methods[method] = {"ledger": self.relative(ledger),
                                   "ledger_sha256": prepare_module.sha256(ledger)}
            rows.append({"run_number": number, "run_kind": kind,
                         "environment": {"environment_pressure": pressure},
                         "methods": methods})
        clean = [row for row in rows if not row["environment"]["environment_pressure"]]
        self.state_units[unit_id] = {"status": "completed_unpressured",
                                     "runs": rows,
                                     "selected_run_number": clean[-1]["run_number"] if clean else None}

    def _write_queue_and_state(self) -> None:
        proof = self.root / "runs/base/preflight-reuse.json"
        self.save(proof, {"status": "passed", "rows": self.proof_rows})
        queue = {"schema_version": 4, "branch": "B", "status": "ready_for_execution",
                 "task": "B", "concurrency": 3, "minimum_free_disk_gib": 35,
                 "unit_count": len(self.units), "spec_count": 2 * len(self.units),
                 "units": self.units, "preflight_reuse": {
                     "path": self.relative(proof), "sha256": prepare_module.sha256(proof)},
                 "budget_policy": {"physical_memory_cap_bytes": prepare_module.SOURCE_CAP}}
        self.save(self.queue_path, queue)
        self.save(self.main / "state.json", {"status": "completed",
                                             "queue_sha256": prepare_module.sha256(self.queue_path),
                                             "units": self.state_units})

    def refresh(self) -> None:
        self._write_queue_and_state()


class N6BMem20PrepareTest(unittest.TestCase):
    def test_last_clean_run_selects_units_in_source_queue_order(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = FakeBRun(Path(temporary))
            fixture.set_runs("u0", [(False, 1, 0)])
            fixture.set_runs("u1", [(True, 2, 0), (False, 0, 0)])
            fixture.set_runs("u2", [(False, 0, 2)])
            fixture.refresh()
            validations = []

            def validate(queue_path, runner):
                validations.append((queue_path, runner))
                return {"status": "valid", "queue_sha256": prepare_module.sha256(queue_path)}

            summary = prepare_module.prepare(
                fixture.main, fixture.queue_path, fixture.output, root=fixture.root,
                queue_runner=fixture.runner, validator=validate)
            self.assertEqual(summary["selected_unit_ids"], ["u0", "u2"])
            self.assertEqual(len(validations), 1)
            result_queue = json.loads((fixture.output / "queue-b-mem20.json").read_text())
            self.assertEqual(result_queue["concurrency"], 1)
            self.assertEqual([unit["unit_id"] for unit in result_queue["units"]],
                             ["u0", "u2"])
            self.assertEqual(result_queue["budget_policy"]["physical_memory_cap_bytes"],
                             prepare_module.SENSITIVITY_CAP)
            for source_unit, result_unit in zip((fixture.units[0], fixture.units[2]),
                                                result_queue["units"]):
                for name in ("whole", "split"):
                    source = json.loads((fixture.root / source_unit[f"{name}_spec"]).read_text())
                    result = json.loads((fixture.root / result_unit[f"{name}_spec"]).read_text())
                    self.assertEqual({key for key in source if source[key] != result[key]},
                                     {"campaign_id", "memory_cap_bytes"})
                    self.assertEqual(result["memory_cap_bytes"],
                                     prepare_module.SENSITIVITY_CAP)
                    self.assertTrue(result["campaign_id"].startswith("N6-B-mem20-"))
            proof = json.loads((fixture.output / "preflight-reuse-b-mem20.json").read_text())
            self.assertEqual(set(proof["rows"]), {"u0:W", "u0:S", "u2:W", "u2:S"})
            for row in proof["rows"].values():
                ledger = fixture.root / row["destination_preflight"]
                self.assertEqual(prepare_module.sha256(ledger),
                                 row["destination_preflight_sha256"])
                self.assertEqual(json.loads(ledger.read_text())["spec_sha256"],
                                 row["destination_spec_sha256"])

    def test_zero_memory_caps_writes_summary_without_queue(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = FakeBRun(Path(temporary))
            result = prepare_module.prepare(
                fixture.main, fixture.queue_path, fixture.output, root=fixture.root,
                queue_runner=fixture.runner,
                validator=lambda *_: self.fail("zero-target case must not validate a queue"))
            self.assertEqual(result["status"], "no_target_units")
            self.assertEqual([path.name for path in fixture.output.iterdir()],
                             ["preparation.json"])

    def test_unit_without_clean_run_is_reported_without_selecting_its_cap(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = FakeBRun(Path(temporary))
            fixture.set_runs("u0", [(True, 4, 0), (True, 0, 0)])
            fixture.refresh()
            result = prepare_module.prepare(
                fixture.main, fixture.queue_path, fixture.output, root=fixture.root,
                queue_runner=fixture.runner,
                validator=lambda *_: self.fail("no queue expected"))
            self.assertEqual(result["status"], "no_target_units")
            self.assertEqual(result["no_clean_run_unit_ids"], ["u0"])

    def test_missing_or_inconsistent_selected_run_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = FakeBRun(Path(temporary))
            fixture.set_runs("u0", [(True, 1, 0), (False, 0, 0)])
            fixture.state_units["u0"]["selected_run_number"] = 1
            fixture.refresh()
            with self.assertRaisesRegex(ValueError, "last clean run"):
                prepare_module.prepare(fixture.main, fixture.queue_path, fixture.output,
                                       root=fixture.root, queue_runner=fixture.runner)


if __name__ == "__main__":
    unittest.main()
