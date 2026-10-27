#!/usr/bin/env python3
"""Low-priority offline A fragment inspection and strict preservation comparison."""
from __future__ import annotations
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]
SUMMARY = ROOT / "runs/n6-a1b-2026-10-08/preparation-summary.json"
MAPPING = ROOT / "runs/n6-j1-2026-10-09.noindex/rq-c-instance-map.json"
UNITS = ("aq-024-6f6781246415", "aq-017-9703bbce0c43")
FIELDS = ("definition_sha256", "existing_wrapper_sha256", "rendered_wrapper_sha256", "fragment_spec_sha256", "inspection_sha256", "target_id")


def guard():
    if os.getpriority(os.PRIO_PROCESS, 0) < 19:
        raise RuntimeError("nice 19 is required")
    if shutil.disk_usage(ROOT).free < 15 * 1024**3:
        raise RuntimeError("internal disk below 15 GiB; stopped")


def path(value):
    p = Path(value)
    p = p if p.is_absolute() else ROOT / p
    p = p.resolve()
    if "n6-a-remeasure-2026-10-25.noindex" in p.parts or str(p).startswith("/Volumes/zkfdo-jcache"):
        raise ValueError("forbidden path")
    return p


def sha(p):
    h = hashlib.sha256()
    with path(p).open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def read(p):
    guard()
    return json.loads(path(p).read_text())


def write(p, value):
    guard()
    with path(p).open("x") as f:
        json.dump(value, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write("\n")


def now():
    return datetime.now(timezone.utc).isoformat()


def reason_category(reason):
    prefix = "unsupported inspection: " if reason.startswith("unsupported inspection: ") else ""
    if "unsupported expression token [" in reason:
        core = "unsupported expression token ["
    elif "compile-time variable arrays are unsupported" in reason:
        core = "compile-time variable arrays are unsupported"
    elif "unknown compile-time value " in reason:
        core = "unknown compile-time value " + reason.rsplit("unknown compile-time value ", 1)[1][:80]
    elif "binding/component reassignment affecting target resolution" in reason:
        core = "binding/component reassignment affecting target resolution"
    elif "component is assigned more than once in the concrete expansion" in reason:
        core = "component is assigned more than once in the concrete expansion"
    elif "compile-r1cs failed" in reason:
        core = "compile-r1cs failed"
    elif "unsupported expression " in reason:
        core = "unsupported expression"
    elif reason.startswith("manifest parameters "):
        core = "manifest parameters differ from parsed root"
    elif reason.startswith("manifest template "):
        core = "manifest template differs from parsed root"
    else:
        core = reason.rsplit(": ", 1)[-1]
    value = prefix + core
    return value if len(value) <= 250 else value[:249] + "…"


def reason_counts(row, field):
    counts = row.get(field + "_counts")
    if counts is not None:
        if any(not isinstance(k, str) or len(k) > 250 or type(v) is not int or v < 1 for k, v in counts.items()):
            raise ValueError("invalid compact reason counts")
        return Counter(counts)
    return Counter(reason_category(reason) for reason in row[field])


def compact_rows(rows):
    for row in rows:
        for field in ("reasons", "old_exclusion_reasons"):
            if field + "_counts" in row:
                reason_counts(row, field)
                continue
            raw = row[field]
            counts = reason_counts(row, field)
            row[field + "_sha256"] = hashlib.sha256(json.dumps(raw, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
            row[field + "_total"] = len(raw)
            row[field + "_counts"] = dict(sorted(counts.items()))
            row[field] = sorted(counts)
    return rows


def protected_digest(rows):
    selected = [{key: value for key, value in row.items()
                 if not key.startswith(("reasons", "old_exclusion_reasons"))} for row in rows]
    return hashlib.sha256(json.dumps(selected, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def summarize(result, mapped):
    rows = result["targets"]
    reasons = Counter()
    old_reasons = Counter()
    for row in rows:
        reasons.update(reason_counts(row, "reasons"))
        old_reasons.update(reason_counts(row, "old_exclusion_reasons"))
    def residual(row):
        return [reason for reason in reason_counts(row, "old_exclusion_reasons")
                if not reason.startswith(("unsupported inspection:", "parsed root template is unavailable", "entrypoint inspection is incomplete", "manifest template ", "manifest parameters "))]
    bugs = []
    for item in mapped:
        for template in item["templates"]:
            matching = [row for row in rows if row["template"] == template]
            bugs.append({"item_id": item["item_id"], "template": template, "targets": len(matching),
                         "historically_eligible": sum(row["old_eligible"] for row in matching),
                         "inspection_eligible": sum(row["inspection_eligible"] for row in matching),
                         "eligible_reusing_recorded_noninspection_checks": sum(row["inspection_eligible"] and not residual(row) for row in matching),
                         "remaining_reasons": sorted({r for row in matching for r in reason_counts(row, "reasons")}),
                         "remaining_recorded_noninspection_reasons": sorted({r for row in matching for r in residual(row)})})
    return {"targets": len(rows), "historically_eligible": sum(row["old_eligible"] for row in rows),
            "inspection_eligible": sum(row["inspection_eligible"] for row in rows),
            "eligible_reusing_recorded_noninspection_checks": sum(row["inspection_eligible"] and not residual(row) for row in rows),
            "exclusion_reasons": dict(reasons.most_common()), "historical_exclusion_reasons": dict(old_reasons.most_common()),
            "rq_c_templates": bugs,
            "limitation": "Inspection only; no new compilation. Reused non-inspection checks are historical, not newly validated eligibility."}


def measure(args):
    binary = path(args.binary)
    if binary.name != "s_inspection_audit" or not binary.is_relative_to(ROOT / "target"):
        raise ValueError("only target/.../s_inspection_audit is permitted")
    output = path(args.output)
    output.mkdir(parents=True, exist_ok=False)
    source = read(args.preparation_summary)
    mapping = read(args.mapping)
    by_unit = {row["unit_id"]: row for row in source["units"]}
    by_map = {row["revision_id"]: row for row in mapping["revisions"]}
    receipt = {"schema_version": 1, "started_at": now(), "binary": str(binary), "binary_sha256": sha(binary),
               "preparation_summary": str(path(args.preparation_summary)), "preparation_summary_sha256": sha(args.preparation_summary),
               "mapping": str(path(args.mapping)), "mapping_sha256": sha(args.mapping), "units": []}
    units = (tuple(row["unit_id"] for row in source["units"]
                   if row["unit_id"].startswith("aq-") and row.get("prepared_report")
                   and row.get("eligible_targets", 0) > 0)
             if args.command == "preserve-all" else UNITS)
    receipt["scope"] = "all recorded aq eligible targets" if args.command == "preserve-all" else "two aq units, all targets"
    for unit in units:
        guard()
        prepared = path(by_unit[unit]["prepared_report"]["path"])
        if sha(prepared) != by_unit[unit]["prepared_report"]["sha256"]:
            raise ValueError(f"prepared hash mismatch: {unit}")
        original_prepared = prepared
        if args.command == "preserve-all":
            old = read(prepared)
            retained = [{key: row[key] for key in ("definition", "eligible", "target_id", "exclusion_reasons")}
                        for row in old["targets"] if row["eligible"]]
            if len(retained) != by_unit[unit]["eligible_targets"]:
                raise ValueError(f"eligible denominator mismatch: {unit}")
            del old
            prepared = output / f"{unit}-eligible-input.json"
            write(prepared, {"schema_version": 1, "source": str(original_prepared),
                             "source_sha256": sha(original_prepared), "targets": retained})
        target = output / f"{unit}.json"
        started, tick = now(), time.monotonic()
        command = [str(binary), str(prepared), str(target)]
        completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False)
        ended, elapsed = now(), time.monotonic() - tick
        guard()
        if completed.returncode != 0:
            write(output / f"{unit}-failure.json", {"started_at": started, "finished_at": ended,
                  "exit_code": completed.returncode, "stderr": completed.stderr[-4000:]})
            raise RuntimeError(f"inspection failed: {unit}: {completed.stderr[-1000:]}")
        data = read(target)
        row = {"unit": unit, "command": command, "started_at": started, "finished_at": ended,
               "elapsed_seconds": elapsed, "output": str(target), "sha256": sha(target),
               **summarize(data, by_map.get(unit, {}).get("items", [])),
               "original_prepared": str(original_prepared), "original_prepared_sha256": sha(original_prepared)}
        receipt["units"].append(row)
        print(json.dumps({key: row[key] for key in ["unit", "targets", "historically_eligible", "inspection_eligible", "eligible_reusing_recorded_noninspection_checks", "elapsed_seconds"]}), flush=True)
    receipt["finished_at"] = now()
    write(output / "measurement.json", receipt)


def compare_rows(before, after):
    old = {row["label"]: row for row in before}
    new = {row["label"]: row for row in after}
    failures = []
    if len(old) != len(before) or len(new) != len(after) or set(old) != set(new):
        failures.append({"reason": "duplicate or different target label set"})
    protected = [label for label, row in old.items() if row["inspection_eligible"] or row["old_eligible"]]
    for label in protected:
        a, b = old[label], new.get(label, {})
        if not b.get("inspection_eligible"):
            failures.append({"label": label, "reason": "previously eligible target lost inspection eligibility"})
        for field in FIELDS:
            if a.get(field) is None or a.get(field) != b.get(field):
                failures.append({"label": label, "reason": f"byte/identity difference: {field}"})
        if a["old_eligible"] and "wrappers" in Path(a.get("wrapper_path", "")).parts and not b.get("rendered_matches_existing"):
            failures.append({"label": label, "reason": "shared production formatter differs from original eligible wrapper"})
    return {"status": "failed" if failures else "passed", "protected_targets": len(protected), "failures": failures}


def compare(args):
    before, after = read(args.before), read(args.after)
    rows = []
    for a, b in zip(before["units"], after["units"], strict=True):
        if a["unit"] != b["unit"]:
            raise ValueError("unit order differs")
        for item in [a, b]:
            if sha(item["output"]) != item["sha256"]:
                raise ValueError("measurement output hash mismatch")
        diff = compare_rows(read(a["output"])["targets"], read(b["output"])["targets"])
        rows.append({"unit": a["unit"], "before_inspection_eligible": a["inspection_eligible"],
                     "after_inspection_eligible": b["inspection_eligible"], **diff})
    result = {"schema_version": 1, "before": str(path(args.before)), "before_sha256": sha(args.before),
              "after": str(path(args.after)), "after_sha256": sha(args.after), "created_at": now(), "units": rows,
              "status": "failed" if any(row["status"] != "passed" for row in rows) else "passed"}
    write(args.output, result)
    print(json.dumps(result, ensure_ascii=False))
    if result["status"] != "passed":
        raise SystemExit(1)


def compact_measurement(args):
    measurement_path = path(args.measurement)
    task_root = ROOT / "runs/s-inspection-improve-2026-10-26"
    if measurement_path.parent.name not in {"baseline", "preserve-baseline"} or measurement_path.parent.parent != task_root:
        raise ValueError("compaction restricted to this task's baseline outputs")
    receipt_path = measurement_path.parent / "compaction-receipt.json"
    if receipt_path.exists():
        raise ValueError("compaction already recorded")
    guard()
    before_measurement = sha(measurement_path)
    data = read(measurement_path)
    mapping = read(data["mapping"])
    by_map = {row["revision_id"]: row for row in mapping["revisions"]}
    changes = []
    for item in data["units"]:
        output = path(item["output"])
        if output.parent != measurement_path.parent or sha(output) != item["sha256"]:
            raise ValueError("output outside baseline or SHA mismatch")
        result = read(output)
        before_sha, before_size = sha(output), output.stat().st_size
        before_protected = protected_digest(result["targets"])
        before_counts = (sum(r["old_eligible"] for r in result["targets"]), sum(r["inspection_eligible"] for r in result["targets"]))
        compact_rows(result["targets"])
        if protected_digest(result["targets"]) != before_protected:
            raise ValueError("protected fixture fields changed during compaction")
        summary = summarize(result, by_map.get(item["unit"], {}).get("items", []))
        for key in ("targets", "historically_eligible", "inspection_eligible", "eligible_reusing_recorded_noninspection_checks"):
            if summary[key] != item[key]:
                raise ValueError(f"measurement count changed during compaction: {key}")
        content = json.dumps(result, ensure_ascii=False, separators=(",", ":")) + "\n"
        guard()
        if sha(output) != before_sha:
            raise ValueError("baseline changed concurrently")
        output.write_text(content)
        item.update(summary)
        item["sha256"] = sha(output)
        changes.append({"path": str(output), "before_sha256": before_sha, "after_sha256": item["sha256"],
                        "before_bytes": before_size, "after_bytes": output.stat().st_size,
                        "protected_fixture_sha256": before_protected, "eligibility_counts": before_counts,
                        "protected_fields_unchanged": True})
    guard()
    if sha(measurement_path) != before_measurement:
        raise ValueError("measurement changed concurrently")
    before_size = measurement_path.stat().st_size
    measurement_path.write_text(json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
    changes.append({"path": str(measurement_path), "before_sha256": before_measurement,
                    "after_sha256": sha(measurement_path), "before_bytes": before_size,
                    "after_bytes": measurement_path.stat().st_size, "measurement_counts_unchanged": True})
    receipt = {"created_at": now(), "kind": "bounded_reason_compaction", "changes": changes,
               "source_prepared_files_unchanged": True, "raw_reason_provenance": "prepared_path/prepared_sha256 plus reason-list SHA-256",
               "reason_limit_characters": 250}
    write(receipt_path, receipt)
    print(json.dumps({"receipt": str(receipt_path), "sha256": sha(receipt_path),
                      "before_bytes": sum(row["before_bytes"] for row in changes),
                      "after_bytes": sum(row["after_bytes"] for row in changes), "protected_fields_unchanged": True}))


def self_test():
    import copy
    base = {"label": "x", "wrapper_path": "/wrappers/000/target.circom", "inspection_eligible": True, "old_eligible": True, "rendered_matches_existing": True,
            **{field: "same" for field in FIELDS}}
    assert compare_rows([base], [base])["status"] == "passed"
    for field in FIELDS:
        changed = copy.deepcopy(base)
        changed[field] = "changed"
        assert compare_rows([base], [changed])["status"] == "failed"
    changed = {**base, "inspection_eligible": False}
    assert compare_rows([base], [changed])["status"] == "failed"
    changed = {**base, "rendered_matches_existing": False}
    assert compare_rows([base], [changed])["status"] == "failed"
    assert compare_rows([base], [])["status"] == "failed"
    noneligible = {**base, "label": "new", "old_eligible": False, "inspection_eligible": False}
    assert compare_rows([base, noneligible], [base, {**noneligible, "inspection_eligible": True}])["status"] == "passed"
    long_reason = "unsupported inspection: T([" + "123456789," * 10000 + "]): unsupported expression token ["
    compact = {**base, "reasons": [long_reason, long_reason], "old_exclusion_reasons": []}
    protected = protected_digest([compact])
    compact_rows([compact])
    assert protected_digest([compact]) == protected
    assert compact["reasons_total"] == 2 and sum(compact["reasons_counts"].values()) == 2
    assert len(json.dumps(compact)) < 2000 and len(reason_category("x" * 1000)) <= 250
    assert reason_category("unsupported inspection: huge: unknown compile-time value Active") == "unsupported inspection: unknown compile-time value Active"
    print("15 differential/compaction checks passed")


def main():
    guard()
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("measure", "preserve-all"):
        m = sub.add_parser(command)
        m.add_argument("--binary", required=True)
        m.add_argument("--output", required=True)
        m.add_argument("--preparation-summary", default=str(SUMMARY))
        m.add_argument("--mapping", default=str(MAPPING))
    c = sub.add_parser("compare")
    c.add_argument("--before", required=True)
    c.add_argument("--after", required=True)
    c.add_argument("--output", required=True)
    compact = sub.add_parser("compact-baseline")
    compact.add_argument("--measurement", required=True)
    sub.add_parser("self-test")
    args = parser.parse_args()
    {"measure": measure, "preserve-all": measure, "compare": compare, "compact-baseline": compact_measurement, "self-test": lambda _: self_test()}[args.command](args)


if __name__ == "__main__":
    main()
