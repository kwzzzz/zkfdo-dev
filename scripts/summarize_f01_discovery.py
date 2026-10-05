#!/usr/bin/env python3
"""F-01 summary: C-03 discovery/preparation (before) against compiler instance capture (after).

Reads only measurement records, discovery/prepared reports and capture JSON under
runs/f01-2026-10-03 and the C-03 records they reference. The output JSON carries statuses,
counts, instance keys (template parameters; arrays as hashes), paths, hashes and timings; no
source text, witness or candidate value.
"""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import re
import statistics
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import measure_f01_discovery as f01  # noqa: E402

ROOT = f01.ROOT
RUN = f01.RUN
C03_RESULTS = f01.C03_RESULTS
STATUSES = ("success", "partial", "unsupported", "failed", "not_started", "unknown")


SUPPLEMENT = "supplement-var-scope"


def load_results(base=RUN):
    results = {}
    for path in sorted(base.glob("measurements/*/result.json")):
        result = json.loads(path.read_text())
        results[result["identifier"]] = result
    return results


def counts(values):
    counter = Counter(values)
    return {status: counter[status] for status in STATUSES if counter[status]} | {
        key: value for key, value in sorted(counter.items()) if key not in STATUSES}


def transitions(rows, before, after):
    return dict(sorted(Counter(f"{row[before]} -> {row[after]}" for row in rows).items()))


def timing(values):
    values = sorted(value for value in values if isinstance(value, (int, float)))
    if not values:
        return {"n": 0}
    quantile = lambda q: values[min(len(values) - 1, int(q * len(values)))]  # noqa: E731
    return {"n": len(values), "total": round(sum(values), 3), "median": round(statistics.median(values), 3),
            "p90": round(quantile(0.9), 3), "max": round(values[-1], 3)}


def capture_category(result):
    instance = result.get("instance_discovery") or {}
    if result["discovery"].get("status") != "success":
        return "discovery_" + str(result["discovery"].get("status"))
    if instance.get("selected") == "compiler":
        return "compiler_complete" if instance.get("compiler_complete") else "compiler_partial"
    return "capture_" + str(instance.get("capture_status"))


def failure_reason(text):
    """First line of a capture failure with absolute paths reduced to file names, for grouping."""
    if not text:
        return None
    line = text.strip().splitlines()[0]
    return re.sub(r"/[^\s:'\"]*/([^/\s:'\"]+)", r"\1", line)[:200]


def remaining_reasons(result):
    """Why an entrypoint is not fully prepared after F-01, as reason codes and capture failures."""
    instance = result.get("instance_discovery") or {}
    reasons = []
    if result["discovery"].get("status") != "success":
        reasons.append("discovery_" + str(result["discovery"].get("status")))
    elif instance.get("selected") != "compiler":
        reasons.append("capture_" + str(instance.get("capture_status")) + ": "
                       + str(failure_reason(instance.get("capture_failure"))))
    reasons.extend(sorted({row["reason"] for row in result["discovery"].get("unsupported", [])}))
    reasons.extend(code for code in result["preparation"].get("failure_types", []) if code not in reasons)
    return reasons


WRAPPER_ERRORS = {"T2051": "main_component_tagged_inputs", "T2021": "template_file_lacks_include",
                  "TAC01": "template_file_lacks_include",
                  "P1014": "include_not_found"}


def wrapper_failures(result):
    """Failed wrapper compile units by circom error code (from the units' stderr logs)."""
    report = (result.get("discovery") or {}).get("report")
    if not report:
        return {}
    discovery = json.loads((ROOT / report["path"]).read_text())
    codes = Counter()
    for unit in discovery.get("compile_units", []):
        if unit["wrapper_status"] == "compile_succeeded":
            continue
        if unit["wrapper_status"] == "compile_timed_out":
            codes["wrapper_compile_timeout"] += 1
            continue
        path = (unit.get("compile") or {}).get("stderr_path")
        text = Path(path).read_text(errors="replace") if path and Path(path).is_file() else ""
        found = sorted(set(re.findall(r"error\[(\w+)\]", re.sub(r"\x1b\[[0-9;]*m", "", text))))
        codes[WRAPPER_ERRORS.get(found[0], found[0]) if found else unit["wrapper_status"]] += 1
    return dict(codes)


def large_rows(results):
    document = json.loads(C03_RESULTS.read_text())
    rows = []
    for entry in document["production_large_entrypoints"]:
        identifier = entry["record"]["path"].split("/")[4]
        result = results.get(identifier)
        c03 = json.loads((ROOT / entry["record"]["path"]).read_text())
        row = {"identifier": identifier, "repository": entry["repository"], "path": entry["path"],
               "constraints": entry["constraints"], "c03_status": entry["component_preparation_status"],
               "c03_failure_types": entry.get("failure_types", []),
               "c03_callsites": c03["discovery"].get("callsites"),
               "c03_units": c03["discovery"].get("unique_compile_units"),
               "c03_eligible": c03["preparation"].get("eligible"),
               "c03_expected": c03["preparation"].get("expected_targets"),
               "c03_discovery_seconds": c03["discovery"].get("elapsed_seconds"),
               "c03_preparation_seconds": c03["preparation"].get("elapsed_seconds")}
        if result is None:
            row["f01_status"] = "missing"
        else:
            instance = result.get("instance_discovery") or {}
            row.update(f01_status=result["f01_component_status"], capture=capture_category(result),
                       capture_failure=failure_reason(instance.get("capture_failure")),
                       interpreter_targets=instance.get("interpreter_targets"),
                       compiler_targets=instance.get("compiler_targets"),
                       f01_callsites=result["discovery"].get("callsites"),
                       f01_units=result["discovery"].get("unique_compile_units"),
                       f01_eligible=result["preparation"].get("eligible"),
                       f01_expected=result["preparation"].get("expected_targets"),
                       capture_compile_seconds=instance.get("capture_compile_seconds"),
                       capture_read_seconds=instance.get("capture_read_seconds"),
                       capture_assemble_seconds=instance.get("capture_assemble_seconds"),
                       f01_discovery_seconds=result["discovery"].get("elapsed_seconds"),
                       f01_preparation_seconds=result["preparation"].get("elapsed_seconds"),
                       wrapper_failures=wrapper_failures(result),
                       remaining=remaining_reasons(result) if result["f01_component_status"] != "success" else [])
        rows.append(row)
    return rows


def captured_arguments(result, keys):
    """Captured arguments of instance keys, from the run's instance-args.json (arrays by hash)."""
    report = (result.get("discovery") or {}).get("report")
    if not report or not keys:
        return {}
    discovery = json.loads((ROOT / report["path"]).read_text())
    path = (discovery.get("instance_discovery") or {}).get("instance_args_path")
    if not path:
        return {}
    document = json.loads(Path(path).read_text())
    rows = {}
    for key in keys:
        entry = document["instances"].get(key)
        if entry is None:
            rows[key] = None
            continue
        arguments = []
        for value in entry["arguments"]:
            if value["kind"] == "array_ref":
                array = document["arrays"][value["sha256"]]
                arguments.append({"kind": "array", "sha256": value["sha256"], "dims": array["dims"]})
            else:
                arguments.append(value)
        rows[key] = arguments
    return rows


def regression(results, population):
    rows = [results[item["identifier"]] for item in population if item["regression"] and item["identifier"] in results]
    mismatches, summary = [], Counter()
    for result in rows:
        comparison = result.get("regression")
        if comparison is None:
            summary["not_compared"] += 1
            mismatches.append({"identifier": result["identifier"], "repository": result["repository"],
                               "entrypoint_key": result["entrypoint_key"], "kind": "not_compared",
                               "capture": capture_category(result)})
            continue
        differences = comparison["slot_differences"]
        units_equal = not comparison["compile_unit_instance_keys_only_c03"] and \
            not comparison["compile_unit_instance_keys_only_f01"]
        identical = comparison["root_equal"] and not differences and units_equal
        summary["identical" if identical else "different"] += 1
        summary["selected_" + str((result.get("instance_discovery") or {}).get("selected"))] += 1
        summary["f01_status_" + result["f01_component_status"]] += 1
        if not identical:
            kinds = Counter("both" if row["c03"] and row["f01"] else "c03_only" if row["c03"] else "f01_only"
                            for row in differences)
            keys = sorted({key for row in differences for key in row["f01"]})
            mismatches.append({"identifier": result["identifier"], "repository": result["repository"],
                               "entrypoint_key": result["entrypoint_key"], "kind": "different",
                               "f01_captured_arguments": captured_arguments(result, keys),
                               "capture": capture_category(result), "root_equal": comparison["root_equal"],
                               "c03_root_instance_key": comparison["c03_root_instance_key"],
                               "f01_root_instance_key": comparison["f01_root_instance_key"],
                               "slot_difference_kinds": dict(kinds), "slot_differences": differences,
                               "compile_unit_instance_keys_only_c03": comparison["compile_unit_instance_keys_only_c03"],
                               "compile_unit_instance_keys_only_f01": comparison["compile_unit_instance_keys_only_f01"]})
    return {"records": len(rows), "summary": dict(sorted(summary.items())), "mismatches": mismatches}


def supplement(results):
    """Entries rerun with the fixed binary (separate lock); main-run values kept alongside."""
    base = RUN / SUPPLEMENT
    if not base.is_dir():
        return None
    rows = []
    for identifier, result in load_results(base).items():
        main = results.get(identifier, {})
        instance = result.get("instance_discovery") or {}
        comparison = result.get("regression") or {}
        rows.append({"identifier": identifier, "repository": result["repository"],
                     "entrypoint_key": result["entrypoint_key"], "role": result["role"],
                     "main_capture": capture_category(main) if main else None,
                     "main_capture_failure": failure_reason((main.get("instance_discovery") or {})
                                                            .get("capture_failure")),
                     "supplement_capture": capture_category(result),
                     "compiler_targets": instance.get("compiler_targets"),
                     "c03_status": result["c03_component_status"],
                     "main_status": main.get("f01_component_status"),
                     "supplement_status": result["f01_component_status"],
                     "regression_identical": bool(comparison) and comparison["root_equal"]
                     and not comparison["slot_differences"]
                     and not comparison["compile_unit_instance_keys_only_c03"]
                     and not comparison["compile_unit_instance_keys_only_f01"]})
    return {"tool_lock": json.loads((base / "tools/tool-lock.json").read_text()), "entries": rows}


def summarize():
    results = load_results()
    population = f01.population()
    by_id = {item["identifier"]: item for item in population}
    missing = sorted(set(by_id) - set(results))
    production = [results[i] for i in by_id if by_id[i]["production"] and i in results]
    compiled = [row for row in production if row["compile_status"] == "success"]
    measured = list(results.values())
    instance_rows = [row.get("instance_discovery") or {} for row in measured]
    return {
        "schema_version": 1, "task": "F-01",
        "tool_lock": json.loads((RUN / "tools/tool-lock.json").read_text()),
        "population": {"total": len(population), "production": sum(i["production"] for i in population),
                       "regression": sum(i["regression"] for i in population),
                       "both": sum(i["production"] and i["regression"] for i in population),
                       "measured": len(results), "missing": missing},
        "zkfuzz_executions": sum(row.get("zkfuzz_executions", 0) for row in measured),
        "production": {
            "entrypoints": len(production), "compile_success": len(compiled),
            "automatic_before": counts(row["c03_automatic_status"] for row in production),
            "automatic_after": counts(row["f01_automatic_status"] for row in production),
            "compiled_component_before": counts(row["c03_component_status"] for row in compiled),
            "compiled_component_after": counts(row["f01_component_status"] for row in compiled),
            "compiled_transitions": transitions(compiled, "c03_component_status", "f01_component_status"),
            "all_component_before": counts(row["c03_component_status"] for row in production),
            "all_component_after": counts(row["f01_component_status"] for row in production),
            "compiled_capture": counts(capture_category(row) for row in compiled),
            "all_capture": counts(capture_category(row) for row in production),
            "compiled_failure_types_after": dict(Counter(code for row in compiled
                                                         for code in row["preparation"].get("failure_types", []))
                                                 .most_common()),
            "compiled_capture_failures": dict(Counter(
                failure_reason((row.get("instance_discovery") or {}).get("capture_failure"))
                for row in compiled if capture_category(row).startswith("capture_")).most_common()),
            "compiled_wrapper_failures": dict(sum((Counter(wrapper_failures(row)) for row in compiled), Counter())),
            "compiled_entrypoints_with_wrapper_failures": dict(Counter(
                code for row in compiled for code in wrapper_failures(row))),
            "compiled_compiler_unsupported_reasons": dict(Counter(
                case["reason"] for row in compiled if (row.get("instance_discovery") or {}).get("selected") == "compiler"
                for case in row["discovery"].get("unsupported", [])).most_common()),
        },
        "large_entrypoints": large_rows(results),
        "supplement": supplement(results),
        "regression": regression(results, population),
        "cost": {
            "capture_compile_seconds": timing(row.get("capture_compile_seconds") for row in instance_rows),
            "capture_compile_attempts": dict(sorted(Counter(row.get("capture_compile_attempts")
                                                            for row in instance_rows).items(), key=str)),
            "capture_read_seconds": timing(row.get("capture_read_seconds") for row in instance_rows),
            "capture_assemble_seconds": timing(row.get("capture_assemble_seconds") for row in instance_rows),
            "capture_scan_seconds": timing(row.get("capture_scan_seconds") for row in instance_rows),
            "capture_constraints": timing(row.get("capture_constraints") for row in instance_rows),
            "f01_discovery_seconds": timing(row["discovery"].get("elapsed_seconds") for row in measured),
            "f01_discovery_over_c03_cap_300": sum((row["discovery"].get("elapsed_seconds") or 0) > 300
                                                  for row in measured),
            "f01_preparation_seconds": timing(row["preparation"].get("elapsed_seconds") for row in measured),
            "f01_preparation_timeouts": sum(row["preparation"].get("reported_status") == "timeout"
                                            for row in measured),
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    summary = summarize()
    text = json.dumps(summary, indent=2, ensure_ascii=False).replace(str(ROOT) + "/", "")
    arguments.output.write_text(text + "\n")
    print(json.dumps({key: summary[key] for key in ("population", "zkfuzz_executions")}, indent=2))


if __name__ == "__main__":
    main()
