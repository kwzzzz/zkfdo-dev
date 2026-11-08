#!/usr/bin/env python3
"""Sequential Policy-A runner with task/request checkpoints and owned cleanup.

All external commands use zkfdo_runtime_v1. The total work budget starts before
validation, copies and preflight. Cleanup has its own measured grace; it may
extend total elapsed time beyond the work deadline. No historical runner is
installed or monkey-patched. Source trees and outputs must be disjoint.

Optional ``judge`` (also per-target) accepts ``command``, ``request_template``,
``project_snapshot_id`` and ``cap_seconds``. Templates may use {candidate},
{request}, {judge_output}, {workspace}, {entrypoint}, {project}, {source_root},
{cache}, {seed}, {target_id}, and tool names supplied by the caller. J is run
sequentially after the fuzzer has stopped and its descendants have been reaped.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import signal
import threading
import time
import uuid

import run_policy_a_engine as legacy
import zkfdo_runtime_v1 as runtime
import zkfdo_tools_v1 as tool_manifest
import zkfuzz_report


SCHEMA = "zkfdo-policy-a-campaign-v5"
REPORT_NAME = "zkfdo_report_counterexample.json"


class StopCampaign(RuntimeError):
    pass


def positive(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be finite and positive")
    return value


def safe_relative(value, name):
    if not isinstance(value, str) or not value or Path(value).is_absolute() or ".." in Path(value).parts:
        raise ValueError(f"{name} must be a nonempty relative path without '..'")
    return value


def argv_check(value, name):
    if not isinstance(value, list) or not value or any(not isinstance(v, str) or not v for v in value):
        raise ValueError(f"{name} must be a nonempty argv array")


def validate_spec(spec):
    if not isinstance(spec, dict) or spec.get("schema_version") != 1:
        raise ValueError("spec schema_version must be 1")
    if spec.get("method") not in ("whole", "split"):
        raise ValueError("method must be whole or split")
    positive(spec.get("total_budget_seconds"), "total_budget_seconds")
    positive(spec.get("attempt_cap_seconds"), "attempt_cap_seconds")
    if spec.get("concurrency") != 1 or spec.get("seed_rule") != "increment_per_pass":
        raise ValueError("only concurrency 1 and increment_per_pass are supported")
    seed = spec.get("initial_seed")
    if isinstance(seed, bool) or not isinstance(seed, int) or not 0 < seed < 2**64:
        raise ValueError("initial_seed must be a nonzero u64")
    if spec.get("memory_cap_bytes") is not None:
        raise ValueError("legacy memory_cap_bytes measured physical footprint; remove it and explicitly choose max_tree_rss_bytes (or null)")
    memory = spec.get("max_tree_rss_bytes")
    if memory is not None and (isinstance(memory, bool) or not isinstance(memory, int) or memory <= 0):
        raise ValueError("max_tree_rss_bytes must be null or a positive integer")
    snapshots = spec.get("source_snapshots")
    targets = spec.get("targets")
    if not isinstance(snapshots, list) or not snapshots or not isinstance(targets, list) or not targets:
        raise ValueError("source_snapshots and targets must be nonempty arrays")
    if spec["method"] == "whole" and len(targets) != 1:
        raise ValueError("whole requires one target")
    ids = set()
    for row in snapshots:
        identifier = safe_relative(row.get("id"), "snapshot id")
        if len(Path(identifier).parts) != 1 or identifier in ids:
            raise ValueError("snapshot ids must be unique single path components")
        ids.add(identifier)
        if not isinstance(row.get("path"), str):
            raise ValueError("snapshot needs a path")
        legacy.require_sha(row.get("tree_sha256"), "snapshot tree_sha256")
        if row.get("expected_baseline_candidates") != 0:
            raise ValueError("source snapshots must declare zero baseline candidates")
        patterns = row.get("candidate_globs")
        if not isinstance(patterns, list) or not patterns:
            raise ValueError("source snapshot needs candidate_globs")
        for pattern in patterns:
            safe_relative(pattern, "candidate glob")
    target_ids = set()
    mode = spec.get("zkfuzz_output", "save_output")
    if mode not in ("save_output", "stderr_report"):
        raise ValueError("unknown zkfuzz_output mode")
    for target in targets:
        identifier = target.get("target_id")
        if not isinstance(identifier, str) or not identifier or identifier in target_ids:
            raise ValueError("target ids must be nonempty and unique")
        target_ids.add(identifier)
        if target.get("source_snapshot_id") not in ids:
            raise ValueError("target references unknown source_snapshot_id")
        safe_relative(target.get("entrypoint_relative"), "entrypoint_relative")
        legacy.require_sha(target.get("entrypoint_sha256"), "entrypoint_sha256")
        argv_check(target.get("command"), "target command")
        if "{entrypoint}" not in "\0".join(target["command"]) or "{workspace}" not in "\0".join(target["command"]):
            raise ValueError("target command must reference entrypoint and workspace")
        if mode == "stderr_report" and "--save_output" in target["command"]:
            raise ValueError("--save_output suppresses stderr candidate reports")
        if mode == "save_output" and spec.get("require_save_output", True) and "--save_output" not in target["command"]:
            raise ValueError("save_output mode requires --save_output")
        if target.get("preflight_compile_command") is not None:
            argv_check(target["preflight_compile_command"], "preflight_compile_command")
        judge = target.get("judge", spec.get("judge"))
        if judge is not None:
            argv_check(judge.get("command"), "judge command")
            if any("{" + key + "}" not in "\0".join(judge["command"]) for key in ("request", "judge_output")):
                raise ValueError("judge command must reference request and judge_output")
            if not isinstance(judge.get("request_template"), (dict, str)):
                raise ValueError("judge request_template must be an object or a JSON path")
            if judge.get("project_snapshot_id") is not None and judge["project_snapshot_id"] not in ids:
                raise ValueError("judge references unknown project_snapshot_id")
    transport = spec.get("seed_transport", {})
    if transport.get("kind") not in ("mutation_settings", "placeholder"):
        raise ValueError("seed_transport kind must be mutation_settings or placeholder")
    if transport["kind"] == "mutation_settings":
        if not isinstance(transport.get("argument"), str) or not transport["argument"]:
            raise ValueError("mutation_settings requires argument")
        if not isinstance(transport.get("base", {}), dict):
            raise ValueError("seed transport base must be an object")
    elif any("{seed}" not in "\0".join(t["command"]) for t in targets):
        raise ValueError("placeholder seed transport requires {seed}")


def expand_value(value, replacements):
    if isinstance(value, str):
        return legacy.expand_command([value], replacements)[0]
    if isinstance(value, dict):
        return {key: expand_value(item, replacements) for key, item in value.items()}
    if isinstance(value, list):
        return [expand_value(item, replacements) for item in value]
    return value


def disjoint(left, right):
    left, right = Path(left).resolve(), Path(right).resolve()
    return not (left == right or left.is_relative_to(right) or right.is_relative_to(left))


class Campaign:
    def __init__(self, output, *, max_disk_bytes, max_request_disk_bytes=None,
                 request_cap_seconds=None, min_free_bytes=25 * 2**30, tools=None,
                 configuration_hook=None, comparison_hook=None, reference_configuration=None,
                 cancel_check=lambda: False, command_runner=None, tools_manifest_path=None,
                 load_tools_manifest=False, purpose="cost-comparison", peer_spec=None,
                 settings_materializer=None, isolation_options=None, include_imds=False):
        if threading.current_thread() is not threading.main_thread():
            raise ValueError("campaign must run on the main thread")
        self.started, self.cpu_started = time.monotonic(), time.process_time()
        self.clock_before = runtime.platform_layer.clock_snapshot()
        raw_output = Path(output).absolute()
        if any(p.is_symlink() for p in (raw_output, *raw_output.parents)):
            raise ValueError("symlink output ancestry is forbidden")
        self.output = raw_output.resolve()
        self.output.mkdir(parents=True, exist_ok=False)
        self.ledger = {"schema": SCHEMA, "status": "starting", "complete": False,
                       "started_utc_ns": time.time_ns(), "output": str(self.output),
                       "stages": [], "attempts": [], "commands": [], "signals": [],
                       "max_tree_rss_bytes": None, "configuration_comparisons": [],
                       "request_cap_seconds": request_cap_seconds, "max_request_disk_bytes": max_request_disk_bytes,
                       "purpose": purpose,
                       "isolation_options": isolation_options, "include_imds": include_imds,
                       "limitations": ["SIGKILL/host loss preserves checkpoints, not final receipts.",
                           "Work deadlines exclude a separately measured cleanup grace.",
                           "CPU sums supervisor process_time and command wait4 CPU; see command receipt scope.",
                           "Optional memory limit uses sampled process-tree RSS, not physical footprint.",
                           "All attempt workspaces are preserved; disk budgets can stop further work."]}
        self.current = None
        self.deadline = float("inf")
        self.previous = {}
        self.cancel_check = cancel_check
        self.run_command = command_runner or runtime.run_command
        self.tools = tools or {}
        self.tools_manifest_path, self.load_tools_manifest = tools_manifest_path, load_tools_manifest
        self.configuration_hook, self.comparison_hook = configuration_hook, comparison_hook
        self.purpose, self.peer_spec_input = purpose, peer_spec
        self.peer_spec = None
        self.wrapper_filter = None
        self.settings_materializer = settings_materializer
        self.isolation_options, self.include_imds = isolation_options, include_imds
        self.reference_configuration = reference_configuration
        self.disk = None
        self.request_disk = None
        self.request_deadline = float("inf")
        self.max_request_disk_bytes = max_request_disk_bytes
        self.request_cap_seconds = request_cap_seconds
        self.seen = {}
        self.pins = {}
        self.checkpoint()
        try:
            self.disk = runtime.DiskBudget(self.output, max_disk_bytes, min_free_bytes=min_free_bytes)
            if max_request_disk_bytes is not None:
                if isinstance(max_request_disk_bytes, bool) or not isinstance(max_request_disk_bytes, int) or max_request_disk_bytes <= 0:
                    raise ValueError("max_request_disk_bytes must be a positive integer")
            if request_cap_seconds is not None:
                positive(request_cap_seconds, "request_cap_seconds")
            for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
                self.previous[sig] = signal.signal(sig, self.signal_handler)
        except BaseException as error:
            self.ledger.update(status="configuration_error", error=f"{type(error).__name__}: {error}", complete=True)
            self.checkpoint()
            raise

    def checkpoint(self):
        self.ledger["wall_seconds"] = time.monotonic() - self.started
        self.ledger["supervisor_cpu_seconds"] = time.process_time() - self.cpu_started
        self.ledger["command_cpu_seconds"] = sum(row.get("cpu_seconds") or 0 for row in self.ledger["commands"])
        self.ledger["cpu_seconds_known_sum"] = self.ledger["supervisor_cpu_seconds"] + self.ledger["command_cpu_seconds"]
        self.ledger["unknown_command_cpu_count"] = sum(row.get("cpu_seconds") is None for row in self.ledger["commands"])
        self.ledger["cleanup_seconds_sum"] = sum(row.get("cleanup_seconds") or 0 for row in self.ledger["commands"])
        self.ledger["command_measurements_valid"] = all(row.get("measurement_valid") is True for row in self.ledger["commands"])
        self.ledger.update(self.command_metrics(self.ledger["commands"]))
        if self.current is not None:
            commands = [self.ledger["commands"][i] for i in self.current.get("command_indices", [])]
            self.current.update(self.command_metrics(commands))
            self.current["command_cpu_seconds"] = sum(row.get("cpu_seconds") or 0 for row in commands)
            self.current["measurement_valid"] = all(row.get("measurement_valid") is True and row.get("cleanup_complete") is True for row in commands)
            self.current["unknown_command_cpu_count"] = sum(row.get("cpu_seconds") is None for row in commands)
            self.current["cleanup_seconds_sum"] = sum(row.get("cleanup_seconds") or 0 for row in commands)
            runtime.atomic_json(Path(self.current["directory"]) / "ledger.json", self.current)
            self.save_receipt(Path(self.current["directory"]), self.current)
        runtime.atomic_json(self.output / "ledger.json", self.ledger)
        self.save_receipt(self.output, self.ledger)

    @staticmethod
    def save_receipt(directory, ledger):
        summary = {key: ledger.get(key) for key in ("status", "complete", "termination_reason", "error",
            "wall_seconds", "command_cpu_seconds", "supervisor_cpu_seconds", "cpu_seconds_known_sum",
            "unknown_command_cpu_count", "cleanup_seconds_sum", "measurement_valid", "invalid_reasons",
            "peak_process_tree_rss_bytes", "peak_process_tree_rss_scope", "environment", "disk",
            "supervisor_affinity", "isolation_options", "configuration_equivalence")}
        summary.update(schema="zkfdo-campaign-receipt-v5", ledger=str(directory / "ledger.json"),
                       ledger_sha256=legacy.sha256_file(directory / "ledger.json"))
        runtime.atomic_json(directory / "receipt.json", summary)

    @staticmethod
    def command_metrics(commands):
        values = [row["peak_process_tree_rss_bytes"] for row in commands if row.get("peak_process_tree_rss_bytes") is not None]
        return {"peak_process_tree_rss_bytes": max(values) if values else None,
                "peak_process_tree_rss_scope": "maximum sampled owned command process-tree RSS, including cleanup; campaign supervisor excluded; sequential commands",
                "environment": next((row["environment"] for row in commands if row.get("environment") is not None), None)}

    def signal_handler(self, signum, _frame):
        self.ledger["signals"].append(signum)

    def gate(self):
        if self.ledger["signals"] or self.cancel_check():
            raise StopCampaign("interrupted")
        if time.monotonic() >= self.deadline:
            raise StopCampaign("budget_exhausted")
        if time.monotonic() >= self.request_deadline:
            raise StopCampaign("request_budget_exhausted")
        for disk in (self.disk, self.request_disk):
            if disk is not None:
                disk.check()

    @contextmanager
    def stage(self, name, **metadata):
        row = {"stage": name, "status": "running", "start_offset_seconds": time.monotonic() - self.started, **metadata}
        self.ledger["stages"].append(row)
        start, cpu = time.monotonic(), time.process_time()
        self.checkpoint()
        try:
            yield row
            row["status"] = "completed"
        except BaseException as error:
            row.update(status="failed", error=f"{type(error).__name__}: {error}")
            raise
        finally:
            row.update(wall_seconds=time.monotonic() - start, supervisor_cpu_seconds=time.process_time() - cpu)
            self.checkpoint()

    def copy_tree(self, source, destination):
        source, destination = Path(source).resolve(), Path(destination).resolve()
        if not disjoint(source, destination) or not disjoint(source, self.output):
            # Clean copies already owned by this task are allowed, but outputs are
            # never placed beneath the tree being copied.
            if not source.is_relative_to(self.output / "snapshots") or not disjoint(source, destination):
                raise ValueError("source/output overlap would recursively copy generated outputs")
        self.gate()
        legacy.ensure_no_symlinks(source)
        def copy_file(src, dst):
            self.gate()
            with open(src, "rb") as inp, open(dst, "xb") as out:
                while chunk := inp.read(1024 * 1024):
                    self.gate()
                    out.write(chunk)
            shutil.copystat(src, dst, follow_symlinks=False)
            self.gate()
            return dst
        shutil.copytree(source, destination, copy_function=copy_file, symlinks=False)
        self.gate()

    def sha(self, path):
        digest = hashlib.sha256()
        with Path(path).open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                self.gate()
                digest.update(chunk)
        self.gate()
        return digest.hexdigest()

    def tree_sha(self, root):
        root = Path(root).resolve()
        if not root.is_dir():
            raise ValueError(f"source snapshot is not a directory: {root}")
        paths = []
        for directory, names, files in os.walk(root, followlinks=False):
            self.gate()
            paths.extend(Path(directory) / name for name in names + files)
        digest = hashlib.sha256()
        for path in sorted(paths, key=lambda item: item.relative_to(root).as_posix()):
            self.gate()
            if path.is_symlink():
                raise ValueError(f"source snapshot contains symlink: {path}")
            relative = path.relative_to(root).as_posix().encode()
            if path.is_dir():
                kind, payload = b"D", b""
            elif path.is_file():
                kind, payload = b"F", bytes.fromhex(self.sha(path))
            else:
                raise ValueError(f"unsupported source node: {path}")
            digest.update(kind + len(relative).to_bytes(8, "big") + relative)
            digest.update(len(payload).to_bytes(8, "big") + payload)
        return digest.hexdigest()

    def inventory(self, root, patterns):
        root = Path(root).resolve()
        found = {}
        for pattern in patterns:
            self.gate()
            for path in root.glob(pattern):
                self.gate()
                if not path.is_file() or path.is_symlink():
                    continue
                resolved = path.resolve()
                if not resolved.is_relative_to(root):
                    raise ValueError(f"candidate escapes workspace: {path}")
                found[resolved.relative_to(root).as_posix()] = self.sha(resolved)
        return dict(sorted(found.items()))
    def replacements(self, workspace, target, **extra):
        tools = {name: str(value["path"] if isinstance(value, dict) else value) for name, value in self.tools.items()}
        return {**tools, "workspace": str(workspace), "entrypoint": str(workspace / target["entrypoint_relative"]),
                "target_id": target["target_id"], **{key: str(value) for key, value in extra.items()}}

    def verify_command(self, argv):
        executable = shutil.which(argv[0]) if not Path(argv[0]).is_absolute() else argv[0]
        if executable is None:
            raise ValueError(f"command executable unavailable: {argv[0]}")
        path = Path(executable).resolve()
        if self.spec.get("require_pinned_command_tools", True):
            expected = self.pins.get(str(path))
            actual = self.sha(path)
            if expected is None or actual != expected:
                raise ValueError(f"command executable is not pinned or changed: {path}")
        else:
            actual = self.sha(path)
        metadata = next((value for value in self.tools.values()
                         if isinstance(value, dict) and Path(value["path"]).resolve() == path), {})
        return {**metadata, "path": str(path), "sha256": actual}

    def configure(self):
        if self.purpose not in ("cost-comparison", "discovery", "supervisor-test"):
            raise ValueError("purpose must be cost-comparison or discovery")
        if self.purpose != "supervisor-test":
            import zkfdo_zkfuzz_config_v1 as config_module
            self.configuration_hook = self.configuration_hook or config_module.resolve_configuration
            self.comparison_hook = self.comparison_hook or config_module.compare_w_s
            self.settings_materializer = self.settings_materializer or config_module.materialize_settings
        if self.purpose == "cost-comparison":
            if self.peer_spec_input is None:
                raise ValueError("cost-comparison requires peer_spec")
            if isinstance(self.peer_spec_input, (str, Path)):
                path = Path(self.peer_spec_input)
                self.peer_spec = json.loads(path.read_text())
                self.ledger["peer_spec"] = {"path": str(path.resolve()), "sha256": self.sha(path)}
            else:
                self.peer_spec = json.loads(json.dumps(self.peer_spec_input))
                self.ledger["peer_spec"] = {"sha256": hashlib.sha256(legacy.json_bytes(self.peer_spec)).hexdigest()}
            validate_spec(self.peer_spec)
            for key in ("initial_seed", "seed_rule"):
                if self.peer_spec[key] != self.spec[key]:
                    raise ValueError(f"peer spec {key} differs")
            self.ledger["configuration_equivalence"] = {"status": "pending",
                "scope": "declared_peer_config_at_pass", "peer_executed_by_this_check": False}
        else:
            self.ledger["configuration_equivalence"] = {"status": "not_applicable", "reason": self.purpose}
        self.ledger["configuration_validation"] = "required" if self.purpose != "supervisor-test" else "synthetic_supervisor_fixture_only"
        self.validate_wrapper_filter()

    def validate_wrapper_filter(self):
        metadata = self.spec.get("wrapper_filter")
        if metadata is None:
            return
        path = Path(metadata["report_path"])
        if self.sha(path) != metadata.get("report_sha256"):
            raise ValueError("wrapper filter report changed")
        report = json.loads(path.read_text())
        if report.get("schema") != "zkfdo-wrapper-filter-v2":
            raise ValueError("unsupported wrapper filter report")
        for key in ("enabled", "coverage_changed"):
            if report.get(key) != metadata.get(key):
                raise ValueError("wrapper filter metadata differs from its report")
        rows = report["targets"]
        ids = [row["target_id"] for row in rows]
        if len(ids) != len(set(ids)):
            raise ValueError("wrapper filter contains duplicate targets")
        skipped = set(report["skipped_target_ids"])
        if not skipped <= set(ids):
            raise ValueError("wrapper filter excludes an unknown target")
        if set(ids) - skipped != {row["target_id"] for row in self.spec["targets"]}:
            raise ValueError("campaign target set differs from wrapper filter report")
        if skipped and not report["enabled"]:
            raise ValueError("disabled wrapper filter cannot exclude targets")
        self.wrapper_filter = {row["target_id"]: row for row in rows}
        for row in rows:
            if row["target_id"] in skipped:
                if not row.get("eligible_for_skip"):
                    raise ValueError("wrapper filter excluded an ineligible target")
                if not row.get("source_hashes") or not row.get("snapshot_hashes"):
                    raise ValueError("excluded wrapper lacks source evidence")
                configuration = row.get("configuration_source", {})
                if not row.get("binary_sha256") or not configuration.get("path") or self.sha(Path(configuration["path"])) != configuration.get("sha256"):
                    raise ValueError("excluded target needs pinned engine configuration evidence")
                for ref in row["source_hashes"] + row["snapshot_hashes"]:
                    if self.sha(Path(ref["path"])) != ref["sha256"]:
                        raise ValueError("excluded wrapper evidence changed")
        self.ledger["wrapper_filter"] = metadata

    def validate_filtered_configuration(self, config):
        if self.wrapper_filter is None or not self.spec["wrapper_filter"].get("coverage_changed"):
            return
        target_id = self.current["target_id"]
        evidence = self.wrapper_filter[target_id]
        reference = evidence.get("configuration_source", {})
        if not reference.get("path"):
            raise ValueError("filtered campaign has unknown preparation-time configuration; regenerate the filter after resolving settings")
        if self.sha(Path(reference["path"])) != reference.get("sha256"):
            raise ValueError("filtered campaign needs unchanged observed input configuration evidence")
        recorded = json.loads(Path(reference["path"]).read_text())
        actual = {"whitelist": config["semantic_settings"]["whitelist"],
                  "trace_mutation_method": config["mutation_config"]["trace_mutation_method"],
                  "search_mode": config["semantic_settings"]["search_mode"],
                  "binary_sha256": config["binary_sha256"]}
        expected = {key: evidence[key] for key in ("whitelist", "trace_mutation_method", "search_mode")}
        expected["binary_sha256"] = recorded["binary_sha256"]
        if actual != expected:
            raise ValueError("engine settings changed after wrapper filtering")
        self.current["wrapper_filter_configuration_verified"] = True

    def seeded_command(self, spec, target, workspace, directory, seed):
        self.gate()
        replacements = self.replacements(workspace, target, seed=seed)
        transport = spec["seed_transport"]
        path = directory / "mutation-settings.json"
        if transport["kind"] == "mutation_settings":
            replacements["seed_settings"] = str(path)
        argv = legacy.expand_command(target["command"], replacements)
        metadata = None
        if transport["kind"] == "mutation_settings":
            if transport["argument"] in argv:
                raise ValueError("seed argument already present in command template")
            tool = {**self.verify_command(argv), "cwd": str(workspace)}
            settings = self.settings_materializer(transport.get("base", {}), seed, tool) if self.settings_materializer else {**transport.get("base", {}), "seed": seed}
            runtime.atomic_json(path, settings)
            metadata = {"path": str(path), "sha256": self.sha(path), "initial_mutation_config": settings,
                        "materialized_full_defaults": self.settings_materializer is not None}
            argv.extend([transport["argument"], str(path)])
        self.gate()
        return argv, metadata

    def peer_comparisons(self, config):
        pass_index = self.current["pass_index"]
        seed = self.peer_spec["initial_seed"] + pass_index
        snapshots = {row["id"]: row for row in self.peer_spec["source_snapshots"]}
        comparisons = []
        for index, target in enumerate(self.peer_spec["targets"]):
            workspace = Path(snapshots[target["source_snapshot_id"]]["path"]).resolve()
            directory = self.output / "peer-configurations" / f"attempt-{self.current['attempt_index']:06d}" / f"target-{index:04d}"
            argv, settings = self.seeded_command(self.peer_spec, target, workspace, directory, seed)
            tool = {**self.verify_command(argv), "cwd": str(workspace)}
            peer = self.configuration_hook(argv, tool)
            comparison = {**self.comparison_hook(config, peer), "scope": "declared_peer_config_at_pass",
                          "peer_executed_by_this_check": False, "peer_target_id": target["target_id"],
                          "pass_index": pass_index, "expected_seed": seed, "peer_configuration": peer,
                          "peer_initial_settings": settings}
            comparisons.append(comparison)
            self.ledger["configuration_comparisons"].append(comparison)
            self.checkpoint()
            if not comparison.get("equal", False):
                raise ValueError("W/S declared configuration differs at current pass")
        self.ledger["configuration_equivalence"]["status"] = "declared_equal_at_checked_passes"
        return comparisons

    def compiler_gate(self, stage, argv, directory, cap):
        if self.purpose == "supervisor-test" or stage not in ("preflight_compile", "judge"):
            return argv, None
        from zkfdo_compile_gate_v1 import create_gate
        compiler = self.tools.get("circom")
        if not isinstance(compiler, dict):
            raise ValueError("compiler launch requires the manifest circom entry")
        expected = Path(compiler["path"]).resolve()
        locations = []
        if stage == "preflight_compile":
            locations = [(0, False)]
        else:
            for index, argument in enumerate(argv):
                if argument == "--circom-bin":
                    if index + 1 >= len(argv):
                        raise ValueError("--circom-bin needs a compiler path")
                    locations.append((index + 1, False))
                elif argument.startswith("--circom-bin="):
                    locations.append((index, True))
            if len(locations) != 1:
                raise ValueError("J command must declare exactly one --circom-bin for launch guarding")
        for index, embedded in locations:
            supplied = argv[index].split("=", 1)[1] if embedded else argv[index]
            resolved = shutil.which(supplied) if not Path(supplied).is_absolute() else supplied
            if resolved is None or Path(resolved).resolve() != expected:
                raise ValueError("supplied compiler differs from manifest circom")
        gate = create_gate(directory.parent / (directory.name + "-compiler-gate"), compiler,
                  tuple(d for d in (self.disk, self.request_disk) if d is not None),
                  min(self.deadline, self.request_deadline, time.monotonic() + positive(cap, "command cap")))
        result = list(argv)
        for index, embedded in locations:
            result[index] = "--circom-bin=" + str(gate) if embedded else str(gate)
        return result, {"path": str(gate), "sha256": self.sha(gate), "real_compiler": compiler,
                        "launch_receipts_directory": str(gate.parent), "scope": "disk and deadline check before each Circom exec"}

    def command(self, stage, argv, directory, cap, *, cwd=None, configuration=False):
        argv = list(argv)
        row = {"stage": stage, "argv": list(argv), "argv_sha256": hashlib.sha256(legacy.json_bytes(argv)).hexdigest(),
               "directory": str(directory), "status": "validating", "configuration": None,
               "start_offset_seconds": time.monotonic() - self.started, "cpu_seconds": None}
        self.ledger["commands"].append(row)
        if self.current is not None:
            self.current.setdefault("command_indices", []).append(len(self.ledger["commands"]) - 1)
        self.checkpoint()
        self.gate()
        tool = {**self.verify_command(argv), "cwd": str(cwd or Path.cwd())}
        config = self.configuration_hook(argv, tool) if configuration and self.configuration_hook else None
        row.update(tool=tool, configuration=config)
        self.checkpoint()
        if configuration and self.purpose != "supervisor-test" and config is None:
            raise ValueError("initial engine configuration receipt is required")
        if configuration and config is not None:
            self.validate_filtered_configuration(config)
        if configuration and self.peer_spec is not None:
            row["peer_comparisons"] = self.peer_comparisons(config)
        if config is not None and self.reference_configuration is not None:
            if self.comparison_hook is None:
                raise ValueError("reference configuration requires comparison_hook")
            comparison = self.comparison_hook(self.reference_configuration, config)
            self.ledger["configuration_comparisons"].append(comparison)
            self.checkpoint()
            if not comparison.get("equal", False):
                raise ValueError("W/S configuration differs")
        row["status"] = "starting"
        row["original_argv"] = list(argv)
        argv, gate = self.compiler_gate(stage, argv, directory, cap)
        row.update(argv=list(argv), argv_sha256=hashlib.sha256(legacy.json_bytes(argv)).hexdigest())
        if gate is not None:
            row.update(compiler_gate=gate, gated_argv=list(argv))
        self.checkpoint()
        memory_exceeded = False
        next_save = 0.0
        def tick(receipt):
            nonlocal memory_exceeded, next_save
            memory = self.spec.get("max_tree_rss_bytes")
            if memory is not None and (receipt.get("peak_process_tree_rss_bytes") or 0) > memory:
                memory_exceeded = True
            if time.monotonic() >= next_save:
                row.update(status=receipt["status"], observed_wall_seconds=receipt.get("observed_wall_seconds"),
                           peak_process_tree_rss_bytes=receipt.get("peak_process_tree_rss_bytes"))
                self.checkpoint()
                next_save = time.monotonic() + 0.5
        seconds = min(positive(cap, "command cap"), self.deadline - time.monotonic(), self.request_deadline - time.monotonic())
        if seconds <= 0:
            self.gate()
            raise StopCampaign("budget_exhausted")
        if hashlib.sha256(legacy.json_bytes(argv)).hexdigest() != row["argv_sha256"]:
            raise ValueError("argv changed during configuration validation")
        settings = self.current.get("initial_settings") if configuration and self.current else None
        if settings is not None:
            before = self.sha(Path(settings["path"]))
            row["settings_sha256_before_execution"] = before
            if before != settings["sha256"]:
                raise ValueError("initial settings changed before dispatch")
        self.checkpoint()
        seconds = min(positive(cap, "command cap"), self.deadline - time.monotonic(), self.request_deadline - time.monotonic())
        if seconds <= 0:
            self.gate()
            raise StopCampaign("budget_exhausted")
        started = time.monotonic()
        optional_runtime = {}
        if self.isolation_options:
            optional_runtime["isolation_options"] = self.isolation_options
        if self.include_imds:
            optional_runtime["include_imds"] = True
        receipt = self.run_command(argv, directory, seconds, cwd=cwd,
                    cancel_check=lambda: memory_exceeded or bool(self.ledger["signals"]) or self.cancel_check(),
                    tick=tick, disk_budgets=tuple(d for d in (self.disk, self.request_disk) if d is not None), **optional_runtime)
        row.update({key: receipt.get(key) for key in ("status", "returncode", "cpu_seconds", "cleanup_seconds",
                   "cleanup_complete", "work_stop_seconds", "peak_process_tree_rss_bytes", "measurement_valid",
                   "invalid_reasons", "clock_delta", "memory_before", "memory_after", "environment")})
        row.update(external_wall_seconds=time.monotonic() - started, receipt=str(directory / "receipt.json"))
        row["argv_sha256_after_execution"] = hashlib.sha256(legacy.json_bytes(argv)).hexdigest()
        if settings is not None:
            after = legacy.sha256_file(Path(settings["path"]))
            row["settings_sha256_after_execution"] = after
            self.current["settings_sha256_after_execution"] = after
        unchanged = row["argv_sha256_after_execution"] == row["argv_sha256"] and (settings is None or after == settings["sha256"])
        row["execution_inputs_unchanged"] = unchanged
        if not unchanged:
            row["measurement_valid"] = False
        memory = self.spec.get("max_tree_rss_bytes")
        memory_exceeded = memory_exceeded or (memory is not None and (receipt.get("peak_process_tree_rss_bytes") or 0) > memory)
        if memory_exceeded:
            row["memory_limit_exceeded"] = True
        self.ledger["signals"].extend(receipt.get("received_signals", []))
        self.checkpoint()
        if not unchanged:
            raise ValueError("argv or initial settings changed during execution")
        if not receipt.get("cleanup_complete"):
            raise StopCampaign("cleanup_incomplete")
        if memory_exceeded:
            raise StopCampaign("memory_limit")
        if receipt["status"] in ("interrupted", "interrupted_before_spawn", "cancelled"):
            raise StopCampaign("interrupted")
        if receipt["status"] not in ("completed", "command_failed", "timeout"):
            raise StopCampaign(receipt["status"])
        if receipt.get("measurement_valid") is not True:
            raise StopCampaign("invalid_measurement")
        return row

    def prepare(self):
        with self.stage("validate_and_pin"):
            validate_spec(self.spec)
            self.ledger["max_tree_rss_bytes"] = self.spec.get("max_tree_rss_bytes")
            pins = legacy.verify_pins(self.spec)
            self.ledger["pinned_files"] = pins
            self.ledger["pinned_trees"] = legacy.verify_tree_pins(self.spec)
            self.pins = {str(Path(row["path"]).resolve()): row["sha256"] for row in pins}
            for tool in self.tools.values():
                if isinstance(tool, dict) and tool.get("sha256"):
                    self.pins[str(Path(tool["path"]).resolve())] = tool["sha256"]
        self.snapshots = {}
        self.snapshot_rows = {row["id"]: row for row in self.spec["source_snapshots"]}
        for index, snapshot in enumerate(self.spec["source_snapshots"]):
            with self.stage("source_copy", source_snapshot_id=snapshot["id"]):
                source = Path(snapshot["path"]).resolve()
                if not disjoint(source, self.output):
                    raise ValueError("source and output must be disjoint")
                self.gate()
                legacy.ensure_no_symlinks(source)
                if self.tree_sha(source) != snapshot["tree_sha256"]:
                    raise ValueError("source snapshot hash differs")
                if self.inventory(source, snapshot["candidate_globs"]):
                    raise ValueError("source snapshot contains baseline candidates")
                destination = self.output / "snapshots" / snapshot["id"]
                self.copy_tree(source, destination)
                if self.tree_sha(destination) != snapshot["tree_sha256"]:
                    raise ValueError("copied source hash differs")
                self.snapshots[snapshot["id"]] = destination
        legacy.verify_entrypoints(self.spec, self.snapshots)
        with self.stage("plan_validation"):
            self.ledger["plan_validation"] = legacy.verify_plan(self.spec, self.snapshots)
        for index, target in enumerate(self.spec["targets"]):
            if target.get("preflight_compile_command") is None:
                continue
            directory = self.output / "preflight" / f"{index:04d}"
            workspace = directory / "workspace"
            with self.stage("preflight_copy", target_id=target["target_id"]):
                self.copy_tree(self.snapshots[target["source_snapshot_id"]], workspace)
            artifacts = directory / "artifacts"
            artifacts.mkdir()
            argv = legacy.expand_command(target["preflight_compile_command"], self.replacements(workspace, target, compile_output=artifacts))
            result = self.command("preflight_compile", argv, directory / "process", self.spec.get("preflight_compile_timeout_seconds", 60), cwd=workspace)
            if result["status"] != "completed":
                raise StopCampaign("preflight_failed")

    def candidates(self, attempt, workspace, target, process_directory):
        self.gate()
        rows = []
        if self.spec.get("zkfuzz_output", "save_output") == "stderr_report":
            log = process_directory / "stderr.log"
            destination = attempt / "candidates" / REPORT_NAME
            link = {"stderr_path": str(log), "stderr_sha256": self.sha(log), "status": "no_report"}
            try:
                value = zkfuzz_report.convert(log, destination, attempt)
            except zkfuzz_report.ReportError as error:
                link.update(status="report_unparsed", error=str(error))
                value = None
            if value is not None:
                link.update(status="linked", candidate=str(destination))
                rows.append({"path": str(destination), "sha256": self.sha(destination)})
            self.gate()
            runtime.atomic_json(attempt / "report_link.json", link)
            self.current["report_link"] = link
        else:
            patterns = self.snapshot_rows[target["source_snapshot_id"]]["candidate_globs"]
            for relative, digest in self.inventory(workspace, patterns).items():
                destination = attempt / "candidates" / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                with (workspace / relative).open("rb") as source, destination.open("xb") as out:
                    while chunk := source.read(1024 * 1024):
                        self.gate()
                        out.write(chunk)
                if self.sha(destination) != digest:
                    raise ValueError("candidate changed while preserving it")
                rows.append({"path": str(destination), "sha256": digest, "workspace_relative": relative})
        for row in rows:
            self.gate()
            row["duplicate_of"] = self.seen.get(row["sha256"])
            self.seen.setdefault(row["sha256"], row["path"])
            row["collected_offset_seconds"] = time.monotonic() - self.started
            try:
                value = json.loads(Path(row["path"]).read_text())
            except (ValueError, UnicodeError) as error:
                row["candidate_parse_error"] = str(error)
                value = None
            auxiliary = value.get("8_auxiliary_result", {}) if isinstance(value, dict) else {}
            if isinstance(auxiliary, dict) and "mutation_test_config" in auxiliary:
                row["runtime_mutation_config"] = auxiliary["mutation_test_config"]
                row["runtime_mutation_config_scope"] = "returned adaptive configuration, separate from initial command configuration"
        self.gate()
        return rows

    def judge(self, config, attempt, target, workspace, candidate, seed, index):
        self.gate()
        directory = attempt / "judgements" / f"{index:04d}"
        directory.mkdir(parents=True)
        project = workspace
        project_id = config.get("project_snapshot_id")
        if project_id:
            project = attempt / "sources" / "project"
            if not project.exists():
                with self.stage("judge_project_copy", target_id=target["target_id"]):
                    self.copy_tree(self.snapshots[project_id], project)
        replacements = self.replacements(workspace, target, project=project, source_root=attempt / "sources",
                         candidate=candidate["path"], request=directory / "request.json", judge_output=directory / "out",
                         cache=attempt / "j-cache", seed=seed)
        template = config["request_template"]
        if isinstance(template, str):
            template = json.loads(Path(template).read_text())
        request = expand_value(template, replacements)
        if not isinstance(request, dict):
            raise ValueError("J request must be an object")
        for name in ("source_root", "project_root"):
            if request.get(name) and not disjoint(Path(request[name]), directory):
                raise ValueError("J output cannot be within its source/project root")
        runtime.atomic_json(directory / "request.json", request)
        row = {"candidate_sha256": candidate["sha256"], "request": str(directory / "request.json"),
               "request_sha256": legacy.sha256_file(directory / "request.json"), "status": "starting"}
        self.current.setdefault("judgements", []).append(row)
        self.checkpoint()
        result = self.command("judge", legacy.expand_command(config["command"], replacements),
                              directory / "process", config.get("cap_seconds", self.spec["total_budget_seconds"]))
        row.update(status=result["status"], process_receipt=result["receipt"])
        result_path = directory / "out" / "result.json"
        if result_path.is_file():
            row.update(result=str(result_path), result_sha256=legacy.sha256_file(result_path))
        self.checkpoint()

    def attempt(self, index):
        target_index = index % len(self.spec["targets"])
        pass_index = index // len(self.spec["targets"])
        seed = self.spec["initial_seed"] + pass_index
        if seed >= 2**64:
            raise StopCampaign("seed_exhausted")
        target = self.spec["targets"][target_index]
        directory = self.output / "attempts" / f"{index:06d}"
        directory.mkdir(parents=True)
        started = time.monotonic()
        cpu_started = time.process_time()
        clock_before = runtime.platform_layer.clock_snapshot()
        self.current = {"schema": "zkfdo-policy-a-request-v5", "attempt_index": index, "target_index": target_index,
                        "target_id": target["target_id"], "pass_index": pass_index, "seed": seed,
                        "directory": str(directory), "status": "starting", "complete": False, "candidates": [],
                        "work_cap_seconds": self.request_cap_seconds, "max_disk_bytes": self.max_request_disk_bytes}
        self.ledger["attempts"].append(self.current)
        self.request_deadline = started + self.request_cap_seconds if self.request_cap_seconds else float("inf")
        self.request_disk = runtime.DiskBudget(directory, self.max_request_disk_bytes) if self.max_request_disk_bytes else None
        self.checkpoint()
        try:
            workspace = directory / "sources" / "wrapper"
            with self.stage("attempt_copy_and_seed", attempt_index=index):
                self.copy_tree(self.snapshots[target["source_snapshot_id"]], workspace)
                argv, settings = self.seeded_command(self.spec, target, workspace, directory, seed)
                if settings is not None:
                    self.current["initial_settings"] = settings
                    self.current["seed_settings_sha256"] = settings["sha256"]
            process_directory = directory / "fuzz"
            result = self.command("fuzz", argv, process_directory, self.spec["attempt_cap_seconds"], cwd=workspace, configuration=True)
            self.current["outcome"] = result["status"]
            self.checkpoint()
            with self.stage("candidate_collection", attempt_index=index):
                self.current["candidates"] = self.candidates(directory, workspace, target, process_directory)
            self.current["outcome"] = "candidate" if self.current["candidates"] else ("no_candidate" if result["status"] == "completed" else result["status"])
            self.checkpoint()
            config = target.get("judge", self.spec.get("judge"))
            if config:
                for candidate_index, candidate in enumerate(self.current["candidates"]):
                    if candidate["duplicate_of"] is None or config.get("judge_duplicates", False):
                        self.judge(config, directory, target, workspace, candidate, seed, candidate_index)
            self.current["status"] = "completed"
            self.gate()
        except BaseException as error:
            self.current.update(status="stopped", error=f"{type(error).__name__}: {error}")
            raise
        finally:
            self.current.update(wall_seconds=time.monotonic() - started, supervisor_cpu_seconds=time.process_time() - cpu_started,
                                clock_before=clock_before, complete=True)
            try:
                self.current["clock_after"] = runtime.platform_layer.clock_snapshot()
                delta = runtime.platform_layer.clock_delta(clock_before, self.current["clock_after"])
                self.current["clock_delta"] = delta
                self.current["invalid_reasons"] = [key for key in ("suspend_evidence", "clock_adjustment_evidence",
                    "unclassified_clock_discrepancy", "capture_ambiguous") if delta.get(key)]
            except (OSError, runtime.ObservationError) as error:
                self.current.update(invalid_reasons=["request_clock_observation_failed"], clock_observation_error=str(error))
            commands = [self.ledger["commands"][i] for i in self.current.get("command_indices", [])]
            self.current["measurement_valid"] = not self.current["invalid_reasons"] and all(
                row.get("measurement_valid") is True and row.get("cleanup_complete") is True for row in commands)
            self.current["cpu_seconds_known_sum"] = self.current["supervisor_cpu_seconds"] + sum(row.get("cpu_seconds") or 0 for row in commands)
            if self.request_disk is not None:
                try:
                    self.current["disk"] = self.request_disk.sample()
                except (OSError, runtime.ObservationError) as error:
                    self.current["disk_observation_error"] = str(error)
            self.checkpoint()
            self.current = None
            self.request_disk = None
            self.request_deadline = float("inf")

    def run(self, spec_or_path, max_attempts=None):
        try:
            with self.stage("load_spec"):
                if max_attempts is not None and (isinstance(max_attempts, bool) or not isinstance(max_attempts, int) or max_attempts <= 0):
                    raise ValueError("max_attempts must be a positive integer")
                if isinstance(spec_or_path, (str, Path)):
                    path = Path(spec_or_path)
                    self.spec = json.loads(path.read_text())
                    self.ledger["spec_path"] = str(path.resolve())
                    self.ledger["spec_sha256"] = legacy.sha256_file(path)
                else:
                    self.spec = json.loads(json.dumps(spec_or_path))
                    self.ledger["spec_sha256"] = hashlib.sha256(legacy.json_bytes(self.spec)).hexdigest()
                total = positive(self.spec.get("total_budget_seconds"), "total_budget_seconds")
                self.deadline = self.started + total
                self.ledger.update(work_budget_seconds=total, method=self.spec.get("method"))
                runtime.atomic_json(self.output / "spec.json", self.spec)
            if self.load_tools_manifest:
                with self.stage("tools_manifest"):
                    self.gate()
                    manifest = tool_manifest.load_manifest(self.tools_manifest_path)
                    if self.tools:
                        raise ValueError("supply either tools or tools_manifest, not both")
                    self.tools = manifest["tools"]
                    self.ledger["tools_manifest"] = manifest
                    self.gate()
            with self.stage("configuration_policy"):
                self.configure()
            self.prepare()
            self.ledger["status"] = "running"
            index = 0
            while max_attempts is None or index < max_attempts:
                self.gate()
                self.attempt(index)
                index += 1
                if self.spec["method"] == "whole":
                    break
            self.ledger["status"] = "completed"
            self.gate()
            self.ledger["termination_reason"] = "whole_attempt_complete" if self.spec["method"] == "whole" else "max_attempts"
        except StopCampaign as error:
            self.ledger.update(status="stopped", termination_reason=str(error))
        except runtime.BudgetExceeded as error:
            self.ledger.update(status="stopped", termination_reason="disk_limit", error=str(error))
        except BaseException as error:
            self.ledger.update(status="failed", termination_reason="exception", error=f"{type(error).__name__}: {error}")
        finally:
            self.ledger.update(complete=True, finished_utc_ns=time.time_ns())
            self.ledger["clock_before"] = self.clock_before
            try:
                self.ledger["clock_after"] = runtime.platform_layer.clock_snapshot()
                delta = runtime.platform_layer.clock_delta(self.clock_before, self.ledger["clock_after"])
                self.ledger["clock_delta"] = delta
                self.ledger["invalid_reasons"] = [key for key in ("suspend_evidence", "clock_adjustment_evidence",
                    "unclassified_clock_discrepancy", "capture_ambiguous") if delta.get(key)]
            except (OSError, runtime.ObservationError) as error:
                self.ledger["invalid_reasons"] = ["campaign_clock_observation_failed"]
                self.ledger["clock_observation_error"] = str(error)
            self.ledger["measurement_valid"] = (self.ledger["status"] != "failed"
                and not self.ledger["invalid_reasons"]
                and all(row.get("measurement_valid") is True and row.get("cleanup_complete") is True
                        for row in self.ledger["commands"]))
            if self.disk is not None:
                try:
                    self.ledger["disk"] = self.disk.sample()
                    if self.ledger["disk"]["stop_reason"] and self.ledger["status"] == "completed":
                        self.ledger.update(status="stopped", termination_reason="disk_limit")
                except (OSError, runtime.ObservationError) as error:
                    self.ledger["disk_observation_error"] = str(error)
                    self.ledger["measurement_valid"] = False
                    self.ledger["invalid_reasons"].append("campaign_disk_observation_failed")
            self.ledger["overrun_seconds"] = max(0.0, time.monotonic() - self.deadline)
            try:
                self.checkpoint()
            except (OSError, TypeError, ValueError) as error:
                self.ledger.update(status="persistence_failed", measurement_valid=False,
                                   persistence_error=f"{type(error).__name__}: {error}")
            finally:
                for sig, old in self.previous.items():
                    signal.signal(sig, old)
        return self.ledger


def run_campaign(spec_or_path, output, *, max_disk_bytes, max_attempts=None, **options):
    campaign = Campaign(output, max_disk_bytes=max_disk_bytes, **options)
    try:
        cpus = (options.get("isolation_options") or {}).get("cpus")
        with runtime.platform_layer.scoped_supervisor_affinity(cpus) as affinity:
            campaign.ledger["supervisor_affinity"] = affinity
            campaign.run(spec_or_path, max_attempts=max_attempts)
    except runtime.ObservationError as error:
        campaign.ledger.update(status="failed", termination_reason="affinity_error",
                               measurement_valid=False, complete=True,
                               error=str(error), finished_utc_ns=time.time_ns())
    finally:
        for sig, old in campaign.previous.items():
            signal.signal(sig, old)
        try:
            campaign.checkpoint()
        except (OSError, TypeError, ValueError) as error:
            campaign.ledger.update(status="persistence_failed", measurement_valid=False,
                                   persistence_error=f"{type(error).__name__}: {error}")
    return campaign.ledger


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--tools-manifest", type=Path)
    parser.add_argument("--purpose", choices=("cost-comparison", "discovery"), required=True)
    parser.add_argument("--peer-spec", type=Path)
    parser.add_argument("--max-disk-bytes", type=int, required=True)
    parser.add_argument("--max-request-disk-bytes", type=int)
    parser.add_argument("--request-cap-seconds", type=float)
    parser.add_argument("--min-free-bytes", type=int, default=25 * 2**30)
    parser.add_argument("--max-attempts", type=int)
    parser.add_argument("--cpu-affinity")
    parser.add_argument("--memory-max-bytes", type=int)
    parser.add_argument("--cgroup-root", type=Path)
    parser.add_argument("--include-imds", action="store_true")
    args = parser.parse_args(argv)
    output = tool_manifest.output_path(args.output, uuid.uuid4().hex)
    isolation = {key: value for key, value in {"cpus": args.cpu_affinity,
                 "memory_max_bytes": args.memory_max_bytes,
                 "cgroup_root": str(args.cgroup_root) if args.cgroup_root else None}.items() if value is not None}
    ledger = run_campaign(args.spec, output, max_disk_bytes=args.max_disk_bytes,
                          max_request_disk_bytes=args.max_request_disk_bytes,
                          request_cap_seconds=args.request_cap_seconds, min_free_bytes=args.min_free_bytes,
                          max_attempts=args.max_attempts, tools_manifest_path=args.tools_manifest,
                          load_tools_manifest=True, purpose=args.purpose, peer_spec=args.peer_spec,
                          isolation_options=isolation or None, include_imds=args.include_imds)
    print(json.dumps({key: ledger.get(key) for key in ("status", "termination_reason", "wall_seconds")}, ensure_ascii=False))
    return 0 if ledger["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
