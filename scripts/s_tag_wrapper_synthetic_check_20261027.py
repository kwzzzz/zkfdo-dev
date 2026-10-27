#!/usr/bin/env python3
"""Bounded synthetic R1CS comparison; no judging, witness generation, or fuzzing."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import time

from s_tag_wrapper_run_20261027 import ROOT, OUT, gate, now, record

COMPILER = ROOT / "runs/c02-corpus-2026-10-02/tools/circom"
COMPILER_SHA = "8991887889c2a74d6fc704d5689ada4cc76fba004e866c987de6cbf3b3db6227"
PRIME = 21888242871839275222246405745257275088548364400416034343698204186575808495617
MAX_ARTIFACT = 64 * 1024**2
MAX_LOG = 1024**2


def digest(data):
    return hashlib.sha256(data).hexdigest()


def path_in_output(value):
    path = Path(value).resolve()
    if not path.is_relative_to(OUT) or path == OUT:
        raise ValueError("synthetic files must be inside the new output directory")
    return path


def read_ref(reference):
    gate()
    path = path_in_output(reference["path"])
    raw = path.read_bytes()
    if digest(raw) != reference["sha256"]:
        raise ValueError(f"synthetic input SHA mismatch: {path}")
    return raw


def write_new(path, value):
    path = path_in_output(path)
    raw = (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()
    if len(raw) > 1024**2:
        raise ValueError("synthetic receipt exceeds one MiB")
    with path.open("xb") as stream:
        stream.write(raw)
    return {"path": str(path), "sha256": digest(raw), "bytes": len(raw)}


def exact(stream, length):
    value = stream.read(length)
    if len(value) != length:
        raise ValueError("truncated R1CS")
    return value


def uint(stream, width=4):
    return int.from_bytes(exact(stream, width), "little")


def parse_r1cs(raw):
    if len(raw) > MAX_ARTIFACT:
        raise ValueError("synthetic R1CS too large")
    stream = io.BytesIO(raw)
    if exact(stream, 4) != b"r1cs" or uint(stream) != 1:
        raise ValueError("unsupported R1CS format")
    count = uint(stream)
    if count > 16:
        raise ValueError("too many R1CS sections")
    sections = {}
    for _ in range(count):
        kind, length = uint(stream), uint(stream, 8)
        if kind in sections or length > MAX_ARTIFACT:
            raise ValueError("duplicate or oversized R1CS section")
        sections[kind] = exact(stream, length)
    if stream.read(1) or 1 not in sections or 2 not in sections or 3 not in sections:
        raise ValueError("trailing data or missing R1CS section")
    header = io.BytesIO(sections[1])
    width = uint(header)
    if width != 32 or uint(header, width) != PRIME:
        raise ValueError("expected the bn128 field")
    shape = dict(zip(("wires", "public_outputs", "public_inputs", "private_inputs"),
                     (uint(header) for _ in range(4))))
    shape.update(labels=uint(header, 8), constraints=uint(header))
    if header.read(1) or not 1 <= shape["wires"] <= 100000 or shape["constraints"] > 10000:
        raise ValueError("invalid or oversized synthetic header")
    if 1 + shape["public_outputs"] + shape["public_inputs"] + shape["private_inputs"] > shape["wires"]:
        raise ValueError("invalid IO wire layout")
    if len(sections[3]) != shape["wires"] * 8:
        raise ValueError("wire-label section size mismatch")
    labels = [int.from_bytes(sections[3][i:i+8], "little") for i in range(0, len(sections[3]), 8)]
    if any(label >= shape["labels"] for label in labels):
        raise ValueError("wire label out of range")
    constraints = []
    body = io.BytesIO(sections[2])
    for _ in range(shape["constraints"]):
        triple = []
        for _ in range(3):
            terms = uint(body)
            if terms > 10000:
                raise ValueError("oversized synthetic linear combination")
            lc = {}
            for _ in range(terms):
                wire, value = uint(body), uint(body, width)
                if wire >= shape["wires"] or value >= PRIME:
                    raise ValueError("invalid R1CS term")
                lc[wire] = (lc.get(wire, 0) + value) % PRIME
            triple.append({wire: value for wire, value in lc.items() if value})
        constraints.append(triple)
    if body.read(1):
        raise ValueError("constraint section has trailing data")
    return {"shape": shape, "constraints": constraints, "wire_labels": labels}


def parse_symbols(raw, r1cs):
    if len(raw) > 4 * 1024**2:
        raise ValueError("synthetic symbol file too large")
    names, label_wires = {}, dict(zip(r1cs["wire_labels"], range(r1cs["shape"]["wires"])))
    for line in raw.decode().splitlines():
        fields = line.split(",")
        if len(fields) != 4:
            raise ValueError("invalid symbol row")
        label, wire, component = map(int, fields[:3])
        name = fields[3]
        if not name or name in names or component < 0 or not 0 <= label < r1cs["shape"]["labels"]:
            raise ValueError("invalid or duplicate symbol")
        if wire < -1 or wire >= r1cs["shape"]["wires"]:
            raise ValueError("symbol wire out of range")
        if label in label_wires and label_wires[label] != wire:
            raise ValueError("symbol label has conflicting wire mappings")
        label_wires[label] = wire
        names[name] = wire
    return names


def linear_constraint(triple):
    a, b, c = triple
    if not a or not b:
        linear = {wire: -value % PRIME for wire, value in c.items()}
    elif set(a) <= {0}:
        linear = {wire: a.get(0, 0) * value % PRIME for wire, value in b.items()}
        for wire, value in c.items():
            linear[wire] = (linear.get(wire, 0) - value) % PRIME
    elif set(b) <= {0}:
        linear = {wire: b.get(0, 0) * value % PRIME for wire, value in a.items()}
        for wire, value in c.items():
            linear[wire] = (linear.get(wire, 0) - value) % PRIME
    else:
        return None
    return {wire: value for wire, value in linear.items() if value}


def normalized(r1cs, symbols, project_equalities):
    """Exact polynomial view; only a*x-a*y=0 relations may identify wires."""
    shape = r1cs["shape"]
    parent = list(range(shape["wires"]))

    def root(wire):
        while parent[wire] != wire:
            parent[wire] = parent[parent[wire]]
            wire = parent[wire]
        return wire

    removed = 0
    if project_equalities:
        for triple in r1cs["constraints"]:
            linear = linear_constraint(triple)
            if linear is not None and len(linear) == 2 and 0 not in linear:
                (a, x), (b, y) = linear.items()
                if (x + y) % PRIME == 0:
                    parent[root(b)] = root(a)
                    removed += 1
    io_names = {}
    role_names = {"public_outputs": [], "public_inputs": [], "private_inputs": []}
    first = 1
    for role in role_names:
        for wire in range(first, first + shape[role]):
            direct = [name for name, position in symbols.items()
                      if position == wire and name.startswith("main.") and "." not in name[5:]]
            if len(direct) != 1:
                raise ValueError("each IO wire must have exactly one direct-main symbol")
            name = direct[0]
            role_names[role].append(name)
            io_names.setdefault(root(wire), []).append(name)
        first += shape[role]
    canonical = {root(0): "$one"}
    aliases = []
    for wire, names in io_names.items():
        names.sort()
        if wire == root(0):
            raise ValueError("constant and IO cannot be merged")
        canonical[wire] = names[0]
        aliases.append(names)
    unknown = sorted({root(wire) for wire in range(shape["wires"])} - set(canonical))
    if unknown:
        raise ValueError("unsupported internal wire remains after equality projection")
    polynomials = []
    for a, b, c in r1cs["constraints"]:
        if len(a) * len(b) > 1000000:
            raise ValueError("synthetic polynomial expansion bound exceeded")
        polynomial = {}
        for wa, va in a.items():
            for wb, vb in b.items():
                variables = tuple(sorted(name for name in (canonical[root(wa)], canonical[root(wb)]) if name != "$one"))
                polynomial[variables] = (polynomial.get(variables, 0) + va * vb) % PRIME
        for wire, value in c.items():
            name = canonical[root(wire)]
            variables = () if name == "$one" else (name,)
            polynomial[variables] = (polynomial.get(variables, 0) - value) % PRIME
        polynomial = {key: value for key, value in polynomial.items() if value}
        if not polynomial:
            continue
        terms = sorted(polynomial.items())
        scale = pow(terms[0][1], -1, PRIME)
        polynomials.append(tuple((key, value * scale % PRIME) for key, value in terms))
    polynomials.sort()
    return {"io_roles": {key: sorted(value) for key, value in role_names.items()},
            "io_alias_classes": sorted(aliases), "polynomials": polynomials,
            "projected_equality_constraints": removed,
            "nonzero_polynomial_count": len(polynomials)}


def comparable(view):
    return {key: view[key] for key in ("io_roles", "io_alias_classes", "polynomials")}


def nonbinary_fixture_satisfies(view):
    # Deliberately outside the declaration's binary domain; no witness execution.
    values = {"main.x[0]": 2, "main.x[1]": 3, "main.y[0]": 11, "main.y[1]": 16}
    if set(sum(view["io_roles"].values(), [])) != set(values):
        raise ValueError("unexpected synthetic fixture IO")
    for names in view["io_alias_classes"]:
        if len({values[name] for name in names}) != 1:
            return False
    for polynomial in view["polynomials"]:
        total = 0
        for variables, coefficient in polynomial:
            term = coefficient
            for name in variables:
                term = term * values[name] % PRIME
            total += term
        if total % PRIME:
            return False
    return True


def compile_one(label, source, output, optimization, timeout):
    free = gate()
    folder = output / label
    folder.mkdir()
    argv = [str(COMPILER), str(source), "--r1cs", "--sym", "--prime", "bn128",
            "--" + optimization, "--output", str(folder)]
    stdout, stderr = folder / "stdout.log", folder / "stderr.log"
    rpath, spath = folder / (source.stem + ".r1cs"), folder / (source.stem + ".sym")
    receipt = {"kind": "synthetic_circom", "label": label, "argv": argv,
               "source_sha256": digest(source.read_bytes()), "compiler_sha256": COMPILER_SHA,
               "start_utc": now(), "cpu_contention": True, "nice": 19,
               "free_bytes_start": free, "timeout_seconds": timeout, "returncode": None, "error": None}
    process, started = None, time.monotonic()
    try:
        with stdout.open("xb") as out, stderr.open("xb") as err:
            # Remain in the recorder's new session, so outer cancellation also owns this child.
            process = subprocess.Popen(argv, cwd=ROOT, stdout=out, stderr=err,
                                       env=dict(os.environ, RAYON_NUM_THREADS="1", OMP_NUM_THREADS="1"))
            while process.poll() is None:
                if time.monotonic() - started >= timeout:
                    raise TimeoutError("synthetic compile timeout")
                if any(path.exists() and path.stat().st_size > MAX_ARTIFACT for path in (rpath, spath)):
                    raise RuntimeError("synthetic artifact size limit")
                if stdout.stat().st_size + stderr.stat().st_size > MAX_LOG:
                    raise RuntimeError("synthetic log size limit")
                time.sleep(0.1)
    except KeyboardInterrupt:
        receipt["error"] = "interrupted"
    except (OSError, RuntimeError, TimeoutError) as error:
        receipt["error"] = f"{type(error).__name__}: {error}"
    finally:
        if process is not None:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
            receipt["returncode"] = process.wait()
        receipt.update(end_utc=now(), elapsed_seconds=time.monotonic() - started,
                       free_bytes_end=shutil.disk_usage(ROOT).free)
    receipt["artifacts"] = []
    parsed = None
    try:
        raw_r1cs = rpath.read_bytes() if rpath.is_file() else None
        raw_sym = spath.read_bytes() if spath.is_file() else None
        for path, raw in ((rpath, raw_r1cs), (spath, raw_sym)):
            if raw is not None:
                receipt["artifacts"].append({"path": str(path), "sha256": digest(raw), "bytes": len(raw),
                                             "removed_after_validation_read": True})
        if receipt["returncode"] == 0 and not receipt["error"]:
            if raw_r1cs is None or raw_sym is None:
                raise ValueError("successful compiler omitted R1CS or symbols")
            r1cs = parse_r1cs(raw_r1cs)
            parsed = (r1cs, parse_symbols(raw_sym, r1cs))
            receipt["r1cs_header"] = r1cs["shape"]
    except (OSError, ValueError, UnicodeError) as error:
        receipt["error"] = f"artifact validation: {error}"
    finally:
        for path in (rpath, spath):
            if path.exists():
                if path.is_symlink() or path.parent != folder:
                    raise ValueError("refuse non-owned artifact cleanup")
                path.unlink()
    logs = {}
    for name, path in (("stdout", stdout), ("stderr", stderr)):
        raw = path.read_bytes() if path.exists() else b""
        receipt[name] = {"path": str(path), "sha256": digest(raw), "bytes": len(raw)}
        logs[name] = raw.decode(errors="replace")
    receipt["diagnostic"] = (logs["stderr"] + "\n" + logs["stdout"]).strip()[:16000]
    reference = write_new(folder / "result.json", receipt)
    record("records", {"record_path": reference["path"], "record_sha256": reference["sha256"],
                       **{key: receipt[key] for key in ("kind", "label", "argv", "start_utc", "end_utc",
                                                      "cpu_contention", "nice", "returncode", "elapsed_seconds")}})
    return receipt, reference, parsed


def run(args):
    gate()
    if not 1 <= args.timeout <= 120:
        raise ValueError("compile timeout must be 1..120 seconds")
    plan_path = path_in_output(args.fixture_plan)
    plan_bytes = plan_path.read_bytes()
    plan = json.loads(plan_bytes)
    source_bytes = {key: read_ref(plan[key]) for key in
                    ("tagged_source", "reference_source", "direct_tagged", "reference_main", "bridge_main")}
    if source_bytes["tagged_source"].count(b"signal input {binary}") != 1:
        raise ValueError("expected exactly one declaration-only binary tag in this synthetic fixture")
    if source_bytes["tagged_source"].replace(b"signal input {binary}", b"signal input") != source_bytes["reference_source"]:
        raise ValueError("reference changes more than the declaration tag")
    if digest(COMPILER.read_bytes()) != COMPILER_SHA:
        raise ValueError("frozen Circom SHA mismatch")
    output = path_in_output(args.output)
    output.mkdir(parents=True, exist_ok=False)
    report = {"schema_version": 1, "kind": "synthetic_tag_bridge_constraint_comparison", "start_utc": now(),
              "fixture_plan": {"path": str(plan_path), "sha256": digest(plan_bytes)}, "cpu_contention": True,
              "source_body_preserved_except_reference_declaration_tag": True,
              "compiles": [], "comparisons": {}, "passed": False, "error": None,
              "method": "Full R1CS polynomials over the bn128 field, with direct-main IO names from .sym. O0 removes only nonconstant a*x-a*y=0 equalities and records IO alias relations. No hidden internal-wire inference.",
              "limits": "This proves the stated synthetic fixture only; it does not certify arbitrary project wrappers or J integration."}
    artifacts = {}
    try:
        jobs = [("direct-tagged-o1", "direct_tagged", "O1"), ("reference-o1", "reference_main", "O1"),
                ("bridge-o1", "bridge_main", "O1"), ("reference-o0", "reference_main", "O0"),
                ("bridge-o0", "bridge_main", "O0")]
        for label, key, optimization in jobs:
            row, reference, parsed = compile_one(label, path_in_output(plan[key]["path"]), output, optimization, args.timeout)
            report["compiles"].append({"label": label, "result": reference, "returncode": row["returncode"], "error": row["error"]})
            if row["error"]:
                raise RuntimeError(row["error"])
            if label == "direct-tagged-o1":
                report["negative_control_T2051"] = row["returncode"] != 0 and "T2051" in row["diagnostic"]
                if not report["negative_control_T2051"]:
                    raise ValueError("direct tagged main did not produce the expected T2051")
            elif row["returncode"] != 0 or parsed is None:
                raise ValueError(f"{label} failed to compile or parse")
            else:
                artifacts[label] = parsed
        views = {}
        for optimization, project in (("o1", False), ("o0", True)):
            reference = normalized(*artifacts["reference-" + optimization], project)
            bridge = normalized(*artifacts["bridge-" + optimization], project)
            equal = comparable(reference) == comparable(bridge)
            nonbinary = nonbinary_fixture_satisfies(reference) and nonbinary_fixture_satisfies(bridge)
            report["comparisons"][optimization] = {"full_constraints_equal": equal, "nonbinary_input_satisfies_both": nonbinary,
                "reference": reference, "bridge": bridge}
            views[optimization] = reference
            if not equal or not nonbinary:
                raise ValueError(f"{optimization} full constraint comparison or nonbinary control failed")
        report["o0_o1_reference_equal"] = comparable(views["o0"]) == comparable(views["o1"])
        if not report["o0_o1_reference_equal"]:
            raise ValueError("reference O0/O1 projected constraints differ")
        report["passed"] = True
    except (OSError, ValueError, RuntimeError) as error:
        report["error"] = f"{type(error).__name__}: {error}"
    except KeyboardInterrupt:
        report["error"] = "interrupted"
    report["end_utc"] = now()
    reference = write_new(output / "summary.json", report)
    print(json.dumps({"summary": reference, "passed": report["passed"], "error": report["error"]}, ensure_ascii=False))
    if not report["passed"]:
        raise SystemExit(2)


def self_test():
    import unittest

    class Checks(unittest.TestCase):
        def example(self, bridge=False, binary=False):
            # out = in*in+7; bridge adds a distinct forwarding wire.
            constraints = [[{2: 1}, {2: 1}, {1: 1, 0: PRIME-7}]]
            if bridge:
                constraints = [[{3: 1}, {3: 1}, {1: 1, 0: PRIME-7}], [{2: 1, 3: PRIME-1}, {0: 1}, {}]]
            if binary:
                constraints.append([{2: 1}, {2: 1, 0: PRIME-1}, {}])
            shape = {"wires": 4 if bridge else 3, "public_outputs": 1, "public_inputs": 0,
                     "private_inputs": 1, "constraints": len(constraints), "labels": 4 if bridge else 3}
            return {"shape": shape, "constraints": constraints}, {"main.y": 1, "main.x": 2}

        def test_forwarding_projection(self):
            self.assertEqual(comparable(normalized(*self.example(), True)), comparable(normalized(*self.example(True), True)))

        def test_unprojected_hidden_wire_refused(self):
            with self.assertRaisesRegex(ValueError, "internal wire"):
                normalized(*self.example(True), False)

        def test_added_boolean_constraint_detected(self):
            self.assertNotEqual(comparable(normalized(*self.example(), True)), comparable(normalized(*self.example(binary=True), True)))

        def test_io_alias_relation_preserved(self):
            data, symbols = self.example()
            data["constraints"] = [[{1: 1, 2: PRIME-1}, {0: 1}, {}]]
            self.assertEqual(normalized(data, symbols, True)["io_alias_classes"], [["main.x", "main.y"]])

        def test_polynomial_scaling_and_commutation(self):
            data, symbols = self.example()
            other = {**data, "constraints": [[{2: 3}, {2: 2}, {1: 6, 0: PRIME-42}]]}
            self.assertEqual(comparable(normalized(data, symbols, False)), comparable(normalized(other, symbols, False)))

        def test_truncated_r1cs_rejected(self):
            with self.assertRaises(ValueError):
                parse_r1cs(b"r1cs" + struct.pack("<II", 1, 3))

        def test_duplicate_symbol_rejected(self):
            data, _ = self.example()
            data["wire_labels"] = [0, 1, 2]
            with self.assertRaises(ValueError):
                parse_symbols(b"1,1,0,main.y\n2,2,0,main.y\n", data)

    outcome = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(Checks))
    if not outcome.wasSuccessful():
        raise SystemExit(1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    run_parser = sub.add_parser("run")
    run_parser.add_argument("--fixture-plan", required=True)
    run_parser.add_argument("--output", required=True)
    run_parser.add_argument("--timeout", type=int, default=60)
    sub.add_parser("self-test")
    args = parser.parse_args()
    if args.action == "self-test":
        if os.getpriority(os.PRIO_PROCESS, 0) < 19 or shutil.disk_usage(ROOT).free < 15 * 2**30:
            raise SystemExit("nice 19 and at least 15 GiB free required")
        self_test()
    else:
        run(args)


if __name__ == "__main__":
    main()
