#!/usr/bin/env python3
"""Synthetic runner tests and isolated repository gates; no A J execution."""
import importlib.util
import argparse
from pathlib import Path
import json
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4
import j_boost_measure_20261027 as m
OUT = None  # Optional CLI receipt destination; unittest uses per-test tempdirs.

def r1cs(path, force=False):
    # F17, c.in = unrelated main u; optionally c.in = 0.
    def lc(pairs):
        return struct.pack("<I", len(pairs)) + b"".join(struct.pack("<IB", w, c) for w, c in pairs)
    body = lc([(1, 1)]) + lc([(0, 1)]) + lc([(2, 1)])
    if force:
        body += lc([(1, 1)]) + lc([(0, 1)]) + lc([])
    header = struct.pack("<I", 1) + b"\x11" + struct.pack("<IIIIQI", 3, 0, 0, 1, 3, 2 if force else 1)
    path.write_bytes(b"r1cs" + struct.pack("<II", 1, 2) +
                     struct.pack("<IQ", 1, len(header)) + header +
                     struct.pack("<IQ", 2, len(body)) + body)
    path.with_suffix(".sym").write_text("1,1,0,main.c.in\n2,2,0,main.u\n")

class Tests(unittest.TestCase):
    def setUp(self):
        if OUT is None:
            temporary = tempfile.TemporaryDirectory(prefix="zkfdo-j-boost-test-")
            self.addCleanup(temporary.cleanup)
            self.folder = Path(temporary.name).resolve()
        else:
            self.folder = OUT / self._testMethodName
            self.folder.mkdir(parents=True)

    def query(self, force=False, candidate=None):
        p = self.folder / "original.r1cs"
        r1cs(p, force)
        q = self.folder / "query.smt2"
        scope = m.make_recheck_query(p, p.with_suffix(".sym"), candidate or {"main.in": 1},
                                    "main.c", q, 0, 5, m.sha(p))
        result = subprocess.run([shutil.which("z3"), "-smt2", str(q)], text=True,
                                capture_output=True, timeout=8, check=True)
        m.fresh(self.folder / "receipt.json", {"scope": scope, "stdout": result.stdout})
        return q, result.stdout.strip()

    def test_freed_main_input_sat(self):
        q, outcome = self.query()
        self.assertEqual(outcome, "sat")
        old = self.folder / "old.smt2"
        old.write_text(q.read_text().replace("(check-sat)", "(assert (= w2 0))\n(check-sat)"))
        result = subprocess.run([shutil.which("z3"), "-smt2", str(old)], capture_output=True,
                                text=True, timeout=8, check=True)
        self.assertEqual(result.stdout.strip(), "unsat")

    def test_original_still_unsat(self):
        self.assertEqual(self.query(force=True)[1], "unsat")

    def test_missing_mapping(self):
        with self.assertRaisesRegex(m.Stop, "main.c.absent"):
            self.query(candidate={"main.absent": 1})

    def test_hash_binding(self):
        p = self.folder / "original.r1cs"
        r1cs(p)
        with self.assertRaises(m.Stop) as error:
            m.make_recheck_query(p, p.with_suffix(".sym"), {"main.in": 1}, "main.c",
                                self.folder / "query.smt2", 0, 5, "wrong")
        self.assertEqual(error.exception.kind, "recheck_original_r1cs_hash")

    def test_process_titles_are_not_scripts(self):
        def row(pid, command):
            return {"pid": pid, "ppid": 1, "pgid": pid, "rss": 1, "command": command}
        rows = [row(1, "/Applications/kitty.app/Contents/MacOS/kitty --hold --title compact-v3"),
                row(2, "/bin/zsh ./watch.sh"),
                row(3, "python3 scripts/n6_a_remeasure_aq_execute_v3_2.py"),
                row(4, "/bin/zsh ./auto-compact-v3.sh"),
                row(5, "python3 scripts/j_boost_measure_20261027.py pilot")]
        self.assertEqual({r["pid"] for r in m.process_gate(rows, 5)[0]}, {2, 3, 4})

    def test_external_source_rejected(self):
        project = self.folder / "project"
        project.mkdir()
        entry, wrapper = project / "main.circom", self.folder / "target.circom"
        entry.write_text('include "/forbidden/library.circom";')
        wrapper.write_text("pragma circom 2.1.6;")
        with self.assertRaises(m.Stop) as error:
            m.source_closure({"project": str(project), "wrapper_copy": str(wrapper),
                              "entrypoint": str(entry), "library_paths": []})
        self.assertEqual(error.exception.kind, "source_dependency_outside_scope_or_missing")

    def test_source_staging_resume(self):
        project = self.folder / "project"
        project.mkdir()
        entry, dep, wrapper = project / "main.circom", project / "dep.circom", self.folder / "target.circom"
        entry.write_text('include "dep.circom"; component main=C();')
        dep.write_text("template C(){signal input a; signal output b; b <== a;}")
        wrapper.write_text(f'include "{dep}"; component main=C();')
        request = self.folder / "old-request.json"
        m.fresh(request, {"candidate": {"path": "old"}})
        row = {"key": "synthetic-request", "project": str(project), "entrypoint": str(entry),
               "wrapper_copy": str(wrapper), "library_paths": [], "request_copy": str(request),
               "base_input_copy": "base.json", "candidate_copy": "candidate.json"}
        row["source_sha256"] = {str(p): m.sha(p) for p in m.source_closure(row)[0]}
        with patch.object(m, "IMAGE", self.folder / "owned"):
            saved = m.stage_request({}, row)
            self.assertEqual(saved, m.stage_request({}, row))
            self.assertEqual((Path(saved["source_root"]) / "project/dep.circom").read_text(), dep.read_text())
            manifest = Path(saved["source_root"]).parent / "source-manifest.json"
            manifest.unlink()
            (Path(saved["source_root"]) / "project/dep.circom").write_text("interrupted copy")
            recovered = m.stage_request({}, row)
            self.assertEqual(recovered["original_source_sha256"], row["source_sha256"])
            self.assertEqual((Path(saved["source_root"]) / "project/dep.circom").read_text(), dep.read_text())
            Path(saved["request"]).write_text("{}")
            with self.assertRaises(m.Stop):
                m.stage_request({}, row)

    def test_direct_does_not_override_verdict(self):
        c = {"representative": "main.c", "verdict": "excluded_in_context", "reason": "local_constraint_refutation"}
        result = {"classes": [c], "costs": {"steps": []}}
        row = {"cases": [{"id": "case", "group": "local_refutation", "representative": "main.c", "legacy": c}]}
        direct = {"method": "constraint_witness", "site": "main.c", "status": "reached",
                  "rust": "correct", "snarkjs": "correct", "witness_sha256": "hash", "l1": False}
        good = m.comparison(result, {"records": [direct]}, row)[0]
        self.assertTrue(good["verdict_conflict"])
        self.assertFalse(good["direct_l1"])
        self.assertEqual(good["legacy_result"]["verdict"], "excluded_in_context")
        direct["snarkjs"] = "missing"
        self.assertFalse(m.comparison(result, {"records": [direct]}, row)[0]["direct_verified_reach"])

    def test_rss_reparented(self):
        rows = [{"pid": 8, "ppid": 1, "pgid": 8, "rss": 10},
                {"pid": 9, "ppid": 1, "pgid": 8, "rss": 20},
                {"pid": 10, "ppid": 1, "pgid": 10, "rss": 99}]
        self.assertEqual(m.tree_rss(rows, 8), 30 * 1024)

    def test_child_output_directory_is_not_precreated(self):
        job = self.folder / "job"
        output = job / "judgment"
        program = "import pathlib,sys; p=pathlib.Path(sys.argv[1]); assert not p.exists(); p.mkdir(); (p/'result.json').write_text('{}')"
        with patch.object(m, "free", return_value=1000*m.GIB):
            r=m.execute_process([sys.executable, "-c", program, str(output)], job, 5,
                                lambda x:None, external=False)
        self.assertEqual(r["status"], "completed")
        self.assertTrue((output/'result.json').exists())

    def test_wall_cap(self):
        with patch.object(m, "free", return_value=1000 * m.GIB):
            result = m.execute_process([sys.executable, "-c", "import time;time.sleep(20)"],
                                       self.folder / "job", 0.2, lambda x: None, external=False)
        self.assertEqual(result["status"], "wall_cap")
        self.assertLess(result["wall_seconds"], 5)
        m.fresh(self.folder / "receipt.json", result)

    def test_scoped_cleanup(self):
        owned = self.folder / "owned"
        work = owned / "request/work/default/attempt-0001"
        work.mkdir(parents=True)
        (work / "large.tmp").write_bytes(b"x" * 16384)
        sibling = owned / "other.txt"
        sibling.write_text("untouched")
        evidence = owned / "request/evidence/default/witness.wtns"
        evidence.parent.mkdir(parents=True)
        evidence.write_bytes(b"synthetic evidence")
        metrics = self.folder / "metrics.json"
        m.fresh(metrics, {"status": "completed"})
        attempt = {"number": 1, "workspace": str(work), "metrics_path": str(metrics)}
        state = {"arms": {"default": [attempt]}}
        with patch.object(m, "IMAGE", owned):
            receipts = m.cleanup_request({"key": "request"}, state, self.folder / "records")
        self.assertEqual(receipts[0]["status"], "deleted")
        self.assertFalse(work.exists())
        self.assertEqual(sibling.read_text(), "untouched")
        self.assertTrue(evidence.exists())

    def test_revision_peak_and_cache_estimate(self):
        rev = sorted(m.REVISIONS)[0]
        state = {"engines": {"v2.2": {"requests": {"1": {"revision": rev,
            "disk_before": {"external_free_bytes": 1000, "deferred_cache_store_bytes": 17},
            "judging_free_bytes_at_finish": 900}}}}}
        r = m.revision_space(state)[rev]
        self.assertEqual(r["workspace_peak_bytes"], 100)
        self.assertEqual(r["required_bytes"], 217)
        self.assertEqual(m.revision_space({})[rev]["workspace_peak_bytes"], m.math.ceil(399.7*m.GIB))

    def test_arm_collects_before_cleanup(self):
        c = {"representative":"main.c","verdict":"unknown","reason":"budget_exhausted","evidence":{}}
        result = {"request_id":"r","preparation":{"status":"ok"},"classes":[c],
                  "entrypoint":{"r1cs_sha256":"a","sym_sha256":"b","o0_r1cs_sha256":"c","public_outputs":0},
                  "costs":{"steps":[],"by_stage":{}}}
        original=self.folder/"original.json";m.fresh(original,result)
        engine=self.folder/"fake-engine"
        engine.write_text("#!"+sys.executable+"\nimport sys,pathlib,json\np=pathlib.Path(sys.argv[sys.argv.index('--output')+1]); assert not p.exists(); p.mkdir(); (p/'result.json').write_text("+repr(json.dumps(result))+")\n")
        engine.chmod(0o755)
        row={"key":"r","request_id":"r","wall_cap_seconds":5,"class_count":1,
             "expected_entrypoint":result["entrypoint"],"cases":[],"result_copy":str(original)}
        x=object.__new__(m.Execution);x.plan={"tools":{k:str(engine) for k in ['circom','node','snarkjs']},"physical_backing":{}}
        x.directory=self.folder/"records";x.directory.mkdir();x.retry_failed=False
        req={};x.state={"requests":{"r":req},"observed_request_peak_bytes":0,"current":{}};x.save=lambda *args,**kwargs:None;x.callback=lambda detail:None
        disk={"available_min_bytes":1000*m.GIB}
        with patch.object(m,'IMAGE',self.folder/'owned'), patch.object(m,'ENGINE',engine), \
             patch.object(m,'image_gate',return_value=disk), patch.object(m,'space_snapshot',return_value=disk), \
             patch.object(m,'physical_backing',return_value={}), patch.object(m,'free',return_value=1000*m.GIB):
            x.arm(row,'default',{'request':'unused'},req)
        a=req['arms']['default'][-1]
        self.assertTrue(a['validated']);self.assertTrue(a['cleaned'])
        self.assertFalse(Path(a['workspace']).exists())
        self.assertTrue((Path(a['metrics_path']).parent/'all-classes.json').exists())

    def test_two_pilot_gate(self):
        pilot = {"cleanup_completed": True, "arms": {
            a: [{"status": "completed", "validated": True, "cleaned": True}] for a in m.ARMS}}
        m.assert_pilot_passed(pilot)
        pilot["arms"]["direct"][-1]["cleaned"] = False
        with self.assertRaises(m.Stop): m.assert_pilot_passed(pilot)

    def test_recovery(self):
        x = object.__new__(m.Execution)
        metrics = self.folder / "metrics.json"
        attempt = {"status": "running", "child_pid": 888888, "metrics_path": str(metrics)}
        x.state = {"requests": {"q": {"arms": {"default": [attempt]}}}}
        x.save = lambda **kwargs: None
        with patch.object(m, "process_rows", return_value=[]):
            x.recover()
        self.assertEqual(attempt["status"], "interrupted_unreaped")
        self.assertTrue(m.read(metrics)["incomplete_measurement"])

    def test_image_space_no_wait(self):
        backing = {"x9_volume": "X9", "image_path": "image"}
        plan = {"aq_state_sha256": "h", "physical_backing": backing,
            "revision_space": {"r": {"required_bytes": 200*m.GIB,
                "workspace_peak_bytes": 90*m.GIB, "new_cache_estimate_bytes": 20*m.GIB}}}
        with patch.object(m, "start_gate", return_value=({"passed": True, "state_sha256": "h"}, {})), \
             patch.object(m, "physical_backing", return_value=backing), \
             patch.object(m, "space_snapshot", return_value={"internal_free_bytes": 35*m.GIB,
                 "image_free_bytes": 500*m.GIB, "x9_actual_free_bytes": 99*m.GIB,
                 "available_min_bytes": 99*m.GIB}):
            with self.assertRaises(m.Stop) as error:
                m.image_gate(plan, {}, {"revision":"r"})
            self.assertEqual(error.exception.kind, "image_space")

    def test_runtime_physical_floor(self):
        backing = {"x9_volume":"X9"}
        with patch.object(m, "free", return_value=1000*m.GIB), \
             patch.object(m, "physical_backing", return_value=backing), \
             patch.object(m, "space_snapshot", return_value={"available_min_bytes":99*m.GIB}):
            r=m.execute_process([sys.executable, "-c", "import time;time.sleep(20)"],
                                self.folder/"job", 10, lambda x:None)
        self.assertEqual(r["status"], "image_emergency_stop")
        self.assertLess(r["wall_seconds"], 5)


def cargo_gates():
    spec = importlib.util.spec_from_file_location("jmonitor", m.ROOT / "scripts/j_boost_monitor_20261027.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monitor = module.m
    import n6_a_remeasure_aq_cleanup_v2_1 as cleanup
    # No du command; metadata inventory only of this task's dedicated target.
    monitor.target_size = lambda: cleanup.scan_stats(m.RUN / "cargo-target")["du_bytes"]
    skip = m.read(m.ROOT / "runs/s-inspection-improve-2026-10-27/cargo-command-reference.json")["skipped_J_tests"]
    if len(skip) != 24 or len(set(skip)) != 24:
        raise RuntimeError("invalid dedicated J-test inventory")
    tag = uuid4().hex[:8]
    commands = [
        (f"step4-fmt-{tag}", ["cargo", "fmt", "--check"], False, 300),
        (f"step4-clippy-{tag}", ["cargo", "clippy", "--offline", "-j", "1", "--all-targets", "--all-features", "--", "-D", "warnings"], True, 3600),
        (f"step4-test-{tag}", ["cargo", "test", "--offline", "-j", "1", "--", "--test-threads=1",
                        *(x for n in skip for x in ("--skip", n))], True, 10800)]
    receipts = []
    for label, cmd, cargo, timeout in commands:
        result = monitor.run(cmd, label, timeout, cargo)
        receipts.append(result)
        print(json.dumps({"label": label, "status": result["status"], "returncode": result["returncode"]}), flush=True)
        if result["status"] != "completed":
            raise SystemExit(2)
    m.fresh(m.LOCAL / f"cargo-gates-{tag}.json", {"receipts": receipts, "J24": "separate release binary harness required"})

if __name__ == "__main__":
    if "--cargo-gates" in sys.argv:
        cargo_gates()
    else:
        parser = argparse.ArgumentParser(description=__doc__)
        parser.add_argument("--output", type=Path, help="optional new directory for retained synthetic receipts")
        args = parser.parse_args()
        if args.output is not None:
            OUT = args.output.resolve()
            OUT.mkdir(parents=True, exist_ok=False)
        result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(Tests))
        summary = {"at": m.now(), "tests": result.testsRun, "failures": len(result.failures),
                   "errors": len(result.errors), "test_sha256": m.sha(__file__),
                   "runner_sha256": m.sha(m.__file__)}
        if OUT is not None:
            m.fresh(OUT / "tests.json", summary)
            print("receipts:", OUT)
        else:
            print(json.dumps(summary))
        raise SystemExit(not result.wasSuccessful())

