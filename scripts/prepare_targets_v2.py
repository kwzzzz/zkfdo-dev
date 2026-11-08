#!/usr/bin/env python3
"""Opt-in filtering of already prepared targets for the pinned zkFuzz mutator.

This changes exploration coverage. It proves only a source-level condition:
there is at least one potential hint site, and all potential sites in the
conservative call closure belong to whitelist templates. It does not prove
absence of candidates, runtime hint reachability, or circuit correctness.
No compiler, fuzzer, J, or held-out case is run by this module.
"""
from __future__ import annotations

import argparse
from collections import Counter
import copy
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path

from zkfdo_runtime_v1 import atomic_json


DEFAULT_WHITELIST = ("IsZero", "Num2Bits")
SUPPORTED_METHODS = {"constant", "constant_operator", "constant_operator_add", "constant_operator_delete"}
RISK = ("Exploration coverage changes: whitelist-only hints do not imply zero candidates. "
        "LessThan and explicit assertions, input checks, and runtime input adjustment remain possible. "
        "Hint counts are potential source sites, not a claim that a runtime trace reaches them.")


class Uncertain(ValueError):
    pass


@dataclass(frozen=True)
class Token:
    value: str
    line: int
    kind: str


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def tokenize(source):
    tokens, index, line = [], 0, 1
    while index < len(source):
        char = source[index]
        if char.isspace():
            line += char == "\n"
            index += 1
        elif source.startswith("//", index):
            end = source.find("\n", index)
            index = len(source) if end < 0 else end
        elif source.startswith("/*", index):
            end = source.find("*/", index + 2)
            if end < 0:
                raise Uncertain("unterminated block comment")
            line += source[index:end + 2].count("\n")
            index = end + 2
        elif char == '"':
            start, start_line = index, line
            index += 1
            while index < len(source):
                if source[index] == "\\":
                    index += 2
                elif source[index] == '"':
                    index += 1
                    break
                else:
                    line += source[index] == "\n"
                    index += 1
            else:
                raise Uncertain("unterminated string")
            tokens.append(Token(source[start:index], start_line, "string"))
        elif char.isascii() and (char.isalpha() or char == "_"):
            end = index + 1
            while end < len(source) and source[end].isascii() and (source[end].isalnum() or source[end] == "_"):
                end += 1
            tokens.append(Token(source[index:end], line, "identifier"))
            index = end
        elif char.isdigit():
            end = index + 1
            while end < len(source) and (source[end].isalnum() or source[end] == "_"):
                end += 1
            tokens.append(Token(source[index:end], line, "number"))
            index = end
        elif char in "{}[]();,.?:+-*/%<>=!&|^~\\":
            operator = next((op for op in ("<--", "-->", "<==", "==>", "===", "<<=", ">>=", "**", "<<", ">>", "==", "!=", "<=", ">=", "&&", "||", "++", "--", "+=", "-=", "*=", "/=", "%=", "&=", "|=", "^=") if source.startswith(op, index)), char)
            tokens.append(Token(operator, line, "symbol"))
            index += len(operator)
        else:
            raise Uncertain(f"unsupported lexical character at line {line}")
    return tokens


def paired(tokens):
    stack, result = [], {}
    close = {"}": "{", ")": "(", "]": "["}
    for index, token in enumerate(tokens):
        if token.kind == "string":
            continue
        if token.value in ("{", "(", "["):
            stack.append((index, token.value))
        elif token.value in close:
            if not stack or stack[-1][1] != close[token.value]:
                raise Uncertain("unbalanced delimiters")
            opening, _ = stack.pop()
            result[opening] = index
    if stack:
        raise Uncertain("unbalanced delimiters")
    return result


def definitions(path, source):
    tokens = tokenize(source)
    pairs = paired(tokens)
    found, index = [], 0
    while index < len(tokens):
        token = tokens[index]
        if token.value in ("template", "function"):
            if index + 2 >= len(tokens) or tokens[index + 1].kind != "identifier" or tokens[index + 2].value != "(":
                raise Uncertain("unsupported template/function declaration")
            name = tokens[index + 1].value
            end_parameters = pairs[index + 2]
            opening = end_parameters + 1
            if opening >= len(tokens) or tokens[opening].value != "{":
                raise Uncertain("unsupported declaration body")
            ending = pairs[opening]
            found.append({"name": name, "kind": token.value, "path": str(path), "start_line": token.line,
                          "end_line": tokens[ending].line, "tokens": tokens[opening + 1:ending]})
            index = ending + 1
        elif token.value in ("pragma", "include", "component"):
            # Top-level directives/main belong to the already compiled plan. Do
            # not confuse their calls or strings with a template body.
            while index < len(tokens) and tokens[index].value != ";":
                index += 1
            if index == len(tokens):
                raise Uncertain("unterminated top-level declaration")
            index += 1
        else:
            raise Uncertain(f"unsupported top-level construct: {token.value}")
    return found


def analyze_body(definition):
    tokens = definition["tokens"]
    calls, hints, assertions = [], [], []
    for index, token in enumerate(tokens):
        if token.kind == "identifier" and index + 1 < len(tokens) and tokens[index + 1].value == "(":
            if token.value == "assert":
                assertions.append(token.line)
            elif token.value not in ("if", "for", "while", "log"):
                calls.append((token.value, token.line))
        if token.value not in ("<--", "-->"):
            continue
        if token.value == "<--":
            start, end = index + 1, index + 1
            while end < len(tokens) and tokens[end].value != ";":
                end += 1
            if end == len(tokens):
                raise Uncertain("hint statement lacks terminator")
        else:
            start, end = index - 1, index
            while start >= 0 and tokens[start].value not in (";", "{", "}"):
                start -= 1
            start += 1
        expression = tokens[start:end]
        function_like = any(t.kind == "identifier" and i + 1 < len(expression) and expression[i + 1].value == "(" for i, t in enumerate(expression))
        hints.append({"path": definition["path"], "template": definition["name"], "line": token.line,
                      "operator": token.value, "rhs_contains_call": function_like})
    return calls, hints, assertions


def wrapper_main(source):
    tokens = tokenize(source)
    pairs = paired(tokens)
    calls, index = [], 0
    while index < len(tokens):
        if tokens[index].value == "{" and index in pairs:
            index = pairs[index] + 1
            continue
        if tokens[index].value == "component" and index + 1 < len(tokens) and tokens[index + 1].value == "main":
            cursor = index + 2
            if cursor < len(tokens) and tokens[cursor].value == "{":
                cursor = pairs[cursor] + 1
            if cursor + 3 >= len(tokens) or tokens[cursor].value != "=" or tokens[cursor + 1].kind != "identifier" or tokens[cursor + 2].value != "(":
                raise Uncertain("wrapper_main_is_not_a_direct_call")
            opening, ending = cursor + 2, pairs[cursor + 2]
            if ending + 1 >= len(tokens) or tokens[ending + 1].value != ";":
                raise Uncertain("wrapper_main_has_unsupported_suffix")
            arguments, current, depth = [], [], 0
            for token in tokens[opening + 1:ending]:
                if token.value in ("(", "["):
                    depth += 1
                elif token.value in (")", "]"):
                    depth -= 1
                if token.value == "," and depth == 0:
                    arguments.append("".join(current))
                    current = []
                else:
                    current.append(token.value)
            if current:
                arguments.append("".join(current))
            calls.append((tokens[cursor + 1].value, arguments))
            index = ending + 2
        else:
            index += 1
    if len(calls) != 1:
        raise Uncertain("wrapper_must_declare_one_main")
    return calls[0]


def classify_target(target, *, whitelist=DEFAULT_WHITELIST, trace_mutation_method="constant_operator", search_mode="ga"):
    whitelist = sorted(set(whitelist))
    result = {"target_id": target.get("target_id"), "template": target.get("definition", {}).get("template_name"),
              "parameters": target.get("definition", {}).get("concrete_parameters"), "eligible_for_skip": False,
              "reason": None, "whitelist": whitelist, "trace_mutation_method": trace_mutation_method,
              "search_mode": search_mode, "source_hashes": [], "snapshot_hashes": [], "hint_sites": [],
              "visited_definitions": [], "assertion_sites": [], "less_than_oracle_present": False,
              "hint_count_scope": "potential source sites in a conservative transitive call closure",
              "coverage_risk": RISK}
    try:
        if search_mode != "ga" or trace_mutation_method not in SUPPORTED_METHODS:
            raise Uncertain("unsupported_mutation_configuration")
        inspection = target.get("inspection", {})
        if inspection.get("complete") is not True or inspection.get("unsupported"):
            raise Uncertain("incomplete_inspection")
        root = inspection.get("root")
        if not root or root.get("template_name") != result["template"]:
            raise Uncertain("root_identity_mismatch")
        sources, snapshots = target.get("source_fingerprints"), target.get("snapshot_fingerprints")
        if not sources or not snapshots:
            raise Uncertain("missing_source_fingerprints")
        if Counter(row.get("sha256") for row in sources) != Counter(row.get("sha256") for row in snapshots):
            raise Uncertain("source_snapshot_fingerprints_differ")
        contents = {}
        for rows, key in ((sources, "source_hashes"), (snapshots, "snapshot_hashes")):
            for row in rows:
                path = Path(row["path"])
                if path.is_symlink() or not path.is_file():
                    raise Uncertain("source_missing_or_symlink")
                raw = path.read_bytes()
                actual = hashlib.sha256(raw).hexdigest()
                result[key].append({"path": str(path.resolve()), "sha256": actual})
                if actual != row.get("sha256"):
                    raise Uncertain("source_changed_after_preparation")
                if key == "source_hashes":
                    contents[str(path.resolve())] = raw.decode("utf-8")
        if str(Path(target.get("run_entrypoint", "")).resolve()) not in {r["path"] for r in result["snapshot_hashes"]}:
            raise Uncertain("run_entrypoint_not_fingerprinted")
        main_name, main_arguments = wrapper_main(Path(target["run_entrypoint"]).read_text())
        expected_arguments = ["".join(token.value for token in tokenize(str(argument))) for argument in root.get("concrete_parameters", [])]
        if main_name != root["template_name"] or main_arguments != expected_arguments:
            raise Uncertain("wrapper_main_differs_from_inspected_root")
        if root.get("concrete_parameters", []) != target.get("definition", {}).get("concrete_parameters", []):
            raise Uncertain("root_parameters_differ_from_definition")
        dependencies = {str(Path(path).resolve()) for path in inspection.get("dependency_paths", [])}
        if dependencies != set(contents):
            raise Uncertain("dependency_closure_fingerprints_differ")
        by_name = {}
        for path, source in contents.items():
            for definition in definitions(path, source):
                if definition["name"] in by_name:
                    raise Uncertain("ambiguous_duplicate_definition")
                by_name[definition["name"]] = definition
        root_name = root["template_name"]
        if root_name not in by_name or by_name[root_name]["kind"] != "template" or by_name[root_name]["path"] != str(Path(root["path"]).resolve()):
            raise Uncertain("root_definition_unresolved")
        scopes = inspection.get("scopes", [])
        if not scopes or not inspection.get("instances"):
            raise Uncertain("missing_prepared_scopes")
        scope_ids = {(str(Path(scope["path"]).resolve()), scope["template_name"]) for scope in scopes}
        if any((str(Path(instance["path"]).resolve()), instance["template_name"]) not in scope_ids for instance in inspection["instances"]):
            raise Uncertain("instance_scope_missing")
        for scope in scopes:
            definition = by_name.get(scope["template_name"])
            if definition is None or any(definition[key] != scope[key] for key in ("start_line", "end_line")) or definition["path"] != str(Path(scope["path"]).resolve()):
                raise Uncertain("prepared_scope_mismatch")
        done, active = set(), set()
        def visit(name):
            if name in active:
                raise Uncertain("recursive_call_closure")
            if name in done:
                return
            definition = by_name.get(name)
            if definition is None:
                raise Uncertain("unresolved_call:" + name)
            active.add(name)
            calls, hints, assertions = analyze_body(definition)
            result["visited_definitions"].append({key: definition[key] for key in ("name", "kind", "path", "start_line", "end_line")})
            result["hint_sites"].extend(hints)
            result["assertion_sites"].extend({"template": name, "path": definition["path"], "line": line} for line in assertions)
            result["less_than_oracle_present"] |= definition["kind"] == "template" and name == "LessThan"
            if hints and definition["kind"] == "function":
                raise Uncertain("hint_in_function")
            if any(site["rhs_contains_call"] for site in hints):
                raise Uncertain("function_or_unresolved_call_in_hint_rhs")
            for callee, _line in calls:
                visit(callee)
            active.remove(name)
            done.add(name)
        visit(root_name)
        if not result["hint_sites"]:
            result["reason"] = "no_hint_sites"
        elif any(site["template"] not in whitelist for site in result["hint_sites"]):
            result["reason"] = "non_whitelisted_hint_site"
        else:
            result.update(eligible_for_skip=True, reason="all_transitive_hint_sites_are_whitelisted")
    except (OSError, UnicodeError, ValueError, KeyError, TypeError) as error:
        result.update(reason="uncertain_keep", uncertainty=str(error))
    result["hint_site_count"] = len(result["hint_sites"])
    return result


def resolve_campaign_configs(spec, output, tools_manifest=None):
    """Read effective settings without starting an engine; unknown settings keep targets."""
    import run_policy_a_engine as legacy
    import zkfdo_zkfuzz_config_v1 as configuration
    import zkfdo_tools_v1 as tool_loader
    snapshots = {row["id"]: row for row in spec["source_snapshots"]}
    pins = {str(Path(row["path"]).resolve()): row for row in spec.get("pinned_files", [])}
    tools = {}
    needs_manifest = tools_manifest is not None or "ZKFDO_TOOLS_MANIFEST" in os.environ or any(
        "{zkfuzz}" in argument or "{circom}" in argument for target in spec["targets"] for argument in target["command"])
    manifest = tool_loader.load_manifest(tools_manifest) if needs_manifest else None
    if manifest is not None:
        tools = manifest["tools"]
        for tool in tools.values():
            path = str(Path(tool["path"]).resolve())
            if path in pins and pins[path]["sha256"] != tool["sha256"]:
                raise ValueError("spec and manifest disagree on tool SHA256")
            pins[path] = tool
    result = {}
    for index, target in enumerate(spec["targets"]):
        try:
            workspace = Path(snapshots[target["source_snapshot_id"]]["path"]).resolve()
            transport = spec["seed_transport"]
            if transport.get("kind") != "mutation_settings":
                raise Uncertain("filter requires explicit mutation_settings seed transport")
            argv = legacy.expand_command(target["command"], {**{name: entry["path"] for name, entry in tools.items()}, "workspace": str(workspace),
                    "entrypoint": str(workspace / target["entrypoint_relative"]), "seed": str(spec["initial_seed"])})
            binary = Path(argv[0]).resolve()
            pin = pins.get(str(binary))
            if pin is None:
                raise Uncertain("engine binary has no spec pin")
            tool = {**pin, "path": str(binary), "sha256": pin["sha256"], "cwd": str(workspace)}
            full = configuration.materialize_settings(transport.get("base", {}), spec["initial_seed"], tool)
            settings_path = output / "configuration-checks" / f"{index:04d}-settings.json"
            atomic_json(settings_path, full)
            if transport["argument"] in argv:
                raise Uncertain("duplicate mutation settings argument")
            argv.extend([transport["argument"], str(settings_path)])
            receipt = configuration.resolve_configuration(argv, tool)
            receipt_path = output / "configuration-checks" / f"{index:04d}-receipt.json"
            atomic_json(receipt_path, receipt)
            result[target["target_id"]] = {"receipt": receipt, "path": str(receipt_path), "sha256": sha(receipt_path),
                "manifest": {"path": manifest["manifest_path"], "sha256": manifest["manifest_sha256"]} if manifest else None}
        except (OSError, ValueError, KeyError, TypeError) as error:
            result[target["target_id"]] = {"error": f"{type(error).__name__}: {error}"}
    return result


def prepare_plan(plan_path, output, *, skip_unmutable_wrappers=False, whitelist=DEFAULT_WHITELIST,
                 trace_mutation_method="constant_operator", search_mode="ga", campaign_spec=None, tools_manifest=None):
    plan_path, output = Path(plan_path).resolve(), Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    plan = json.loads(plan_path.read_text())
    ids = [row["target_id"] for row in plan["targets"]]
    if len(set(ids)) != len(ids):
        raise ValueError("prepared plan target IDs must be unique")
    configurations = {}
    spec = None
    if campaign_spec is not None:
        spec = json.loads(Path(campaign_spec).read_text())
        if len({t["target_id"] for t in spec["targets"]}) != len(spec["targets"]):
            raise ValueError("campaign target IDs must be unique")
        if {t["target_id"] for t in spec["targets"]} != {t["target_id"] for t in plan["targets"]}:
            raise ValueError("campaign target IDs differ from the prepared plan")
        by_id = {row["target_id"]: row for row in plan["targets"]}
        snapshots = {row["id"]: row for row in spec["source_snapshots"]}
        for target in spec["targets"]:
            snapshot = snapshots[target["source_snapshot_id"]]
            entrypoint = (Path(snapshot["path"]) / target["entrypoint_relative"]).resolve()
            expected = Path(by_id[target["target_id"]]["run_entrypoint"]).resolve()
            if entrypoint != expected or sha(entrypoint) != target["entrypoint_sha256"]:
                raise ValueError("campaign executable wrapper differs from prepared plan")
        configurations = resolve_campaign_configs(spec, output, tools_manifest)
    rows = []
    for target in plan["targets"]:
        config = configurations.get(target["target_id"], {})
        effective = config.get("receipt")
        settings = {"whitelist": whitelist, "trace_mutation_method": trace_mutation_method, "search_mode": search_mode}
        if effective:
            settings = {"whitelist": effective["semantic_settings"]["whitelist"],
                        "trace_mutation_method": effective["mutation_config"]["trace_mutation_method"],
                        "search_mode": effective["semantic_settings"]["search_mode"]}
        row = classify_target(target, **settings)
        if "error" in config:
            row.update(eligible_for_skip=False, reason="uncertain_keep", uncertainty="effective_configuration_unknown: " + config["error"])
        row["configuration_source"] = ({"path": config["path"], "sha256": config["sha256"]} if effective else
                                       {"scope": "recorded filter assumptions, not an observed engine execution"})
        row["binary_sha256"] = effective["binary_sha256"] if effective else None
        rows.append(row)
    skipped = {row["target_id"] for row in rows if skip_unmutable_wrappers and row["eligible_for_skip"]}
    report = {"schema": "zkfdo-wrapper-filter-v2", "input_plan": str(plan_path), "input_plan_sha256": sha(plan_path),
              "enabled": skip_unmutable_wrappers, "coverage_changed": bool(skipped), "coverage_risk": RISK,
              "whitelist": sorted(set(whitelist)), "trace_mutation_method": trace_mutation_method, "search_mode": search_mode,
              "original_target_count": len(rows), "kept_target_count": len(rows) - len(skipped),
              "skipped_target_ids": sorted(skipped), "targets": rows,
              "campaign_spec": str(Path(campaign_spec).resolve()) if campaign_spec else None,
              "campaign_spec_sha256": sha(campaign_spec) if campaign_spec else None,
              "preparation_savings_claimed": False, "scope": "already prepared plan; potential savings concern subsequent S execution only"}
    atomic_json(output / "filter-report.json", report)
    filtered = copy.deepcopy(plan)
    filtered["targets"] = [row for row in plan["targets"] if row["target_id"] not in skipped]
    if spec is not None:
        order = {row["target_id"]: index for index, row in enumerate(spec["targets"])}
        filtered["targets"].sort(key=lambda row: order[row["target_id"]])
    filtered.update(plan_path=str(output / "filtered-plan.json"), plan_id="wrapper-filter-v2-" + sha(output / "filter-report.json")[:16],
                    created_at=datetime.now(timezone.utc).isoformat())
    if skipped:
        filtered["original_comparison_target_set"] = filtered.get("comparison_target_set")
        filtered["comparison_target_set"] = "wrapper_filtered_subset"
    filtered["wrapper_filter"] = {"report_path": str(output / "filter-report.json"), "report_sha256": sha(output / "filter-report.json"),
                                   "enabled": skip_unmutable_wrappers, "coverage_changed": bool(skipped)}
    atomic_json(output / "filtered-plan.json", filtered)
    if spec is not None:
        spec["targets"] = [row for row in spec["targets"] if row["target_id"] not in skipped]
        spec["wrapper_filter"] = {**filtered["wrapper_filter"], "whitelist": sorted(set(whitelist)),
                                   "trace_mutation_method": trace_mutation_method, "search_mode": search_mode,
                                   "configuration_by_target": {row["target_id"]: {key: row[key] for key in
                                       ("whitelist", "trace_mutation_method", "search_mode", "binary_sha256")} for row in rows}}
        for pin in spec.get("pinned_files", []):
            if pin.get("label") == "plan":
                pin.update(path=str(output / "filtered-plan.json"), sha256=sha(output / "filtered-plan.json"))
        atomic_json(output / "campaign-spec.json", spec)
    return report


def analyze_cold(root):
    root = Path(root)
    reports = []
    for seed in (2026100601, 2026100602, 2026100603):
        directory = root / str(seed)
        plan_path, ledger_path = directory / "split-plan.json", directory / "campaign/ledger.json"
        plan, ledger = json.loads(plan_path.read_text()), json.loads(ledger_path.read_text())
        spec_path = directory / "campaign-spec.json"
        spec = json.loads(spec_path.read_text())
        order = {target["target_id"]: index for index, target in enumerate(spec["targets"])}
        rows = []
        for target in sorted(plan["targets"], key=lambda value: order[value["target_id"]]):
            row = classify_target(target)
            attempts = [attempt for attempt in ledger["attempts"] if attempt["target_id"] == target["target_id"]]
            row["historical_attempts"] = [{"attempt_index": attempt["attempt_index"], "outcome": attempt["outcome"],
                "process_wall_seconds": attempt["process_wall_seconds"], "cpu_seconds": attempt.get("resource", {}).get("cpu_seconds")}
                for attempt in attempts]
            row["historical_attempt_count"] = len(attempts)
            row["observed_s_wall_seconds"] = sum(attempt["process_wall_seconds"] for attempt in attempts)
            row["observed_s_cpu_seconds"] = sum(attempt.get("resource", {}).get("cpu_seconds") or 0 for attempt in attempts)
            row["unattempted_cost_assigned_zero"] = not attempts
            rows.append(row)
        skipped = [row for row in rows if row["eligible_for_skip"]]
        reports.append({"seed": seed, "plan_path": str(plan_path), "plan_sha256": sha(plan_path),
                        "campaign_spec_sha256": sha(spec_path), "ledger_path": str(ledger_path), "ledger_sha256": sha(ledger_path),
                        "target_count": len(rows), "potentially_skipped_count": len(skipped),
                        "observed_skippable_s_wall_seconds": sum(row["observed_s_wall_seconds"] for row in skipped),
                        "observed_skippable_s_cpu_seconds": sum(row["observed_s_cpu_seconds"] for row in skipped), "targets": rows})
    return {"schema": "zkfdo-wrapper-skip-historical-analysis-v1", "development_only": True,
            "new_engine_executions": 0, "coverage_risk": RISK, "preparation_savings_claimed": False,
            "cost_scope": "historical S process_wall_seconds and resource.cpu_seconds only; J/campaign cleanup excluded; unattempted targets contribute zero",
            "interpretation": "cost attached to targets the new rule would skip; not a measured speedup or proof that later candidates remain unchanged",
            "seeds": reports,
            "observed_skippable_s_wall_seconds_total": sum(row["observed_skippable_s_wall_seconds"] for row in reports),
            "observed_skippable_s_cpu_seconds_total": sum(row["observed_skippable_s_cpu_seconds"] for row in reports)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--skip-unmutable-wrappers", action="store_true")
    parser.add_argument("--campaign-spec", type=Path)
    parser.add_argument("--tools-manifest", type=Path)
    args = parser.parse_args(argv)
    report = prepare_plan(args.plan, args.output, skip_unmutable_wrappers=args.skip_unmutable_wrappers,
                          campaign_spec=args.campaign_spec, tools_manifest=args.tools_manifest)
    print(json.dumps({key: report[key] for key in ("enabled", "original_target_count", "kept_target_count", "coverage_changed")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
