#!/usr/bin/env python3
"""A-only J boost measurement: prepare, gate, pilot, run, status, recheck, summary.

All real J writes live in the dedicated image subtree. Existing aq files are
read-only. Preparation follows explicit Circom includes; no directory sweep is
used to discover sources. No compact, installation, or aq restart is performed.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import math
import mmap
import os
from pathlib import Path
import re
import shlex
import shutil
import signal
import struct
import subprocess
import sys
import time
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
DEV = ROOT / "runs/j-dev-2026-10-27"
RUN = ROOT / "runs/j-boost-2026-10-27"
LOCAL = RUN / "step4"
IMAGE = Path("/Volumes/zkfdo-jcache/j-boost-2026-10-27")
MOUNT = IMAGE.parent
AQ_STATE = ROOT / "runs/n6-a-remeasure-2026-10-25.noindex/aq-exec/state-v3_2.json"
ENGINE = RUN / "cargo-target/release/zkfdo-j-v23"
ENGINE_SHA = "3fcf4c1ff5db62606f570ff25d786035a025bf91910ed2184f32a08736930eda"
REVISIONS = {
    "aq-011-93343c3cd34c", "aq-016-0a7d49b1c135",
    "aq-017-9703bbce0c43", "aq-026-2bcd7ed6110f",
}
ARMS = ("default", "fair", "direct")
CONCLUSIONS = {"excluded_in_context", "entrypoint_violation", "assumption_input_reachable",
               "compatible_no_top_violation_observed"}
FLAGS = {
    "default": [],
    "fair": ["--class-sweep-budget-seconds", "20"],
    "direct": ["--class-sweep-budget-seconds", "20", "--constraint-witness", "--aligned-diagnostics"],
}
GIB = 2**30
STOP = None
SCHEMA = "j-boost-measure-v1"


class Stop(RuntimeError):
    def __init__(self, kind, detail):
        super().__init__(str(detail))
        self.kind = kind


def now():
    return datetime.now(timezone.utc).isoformat()


def sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def atomic(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + "." + uuid4().hex + ".tmp")
    with tmp.open("x") as f:
        json.dump(data, f, ensure_ascii=False, sort_keys=True, indent=2)
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def fresh(path, data):
    path = Path(path)
    if path.exists():
        raise Stop("existing_record", str(path))
    atomic(path, data)


def below(path, boundary, *, exists=True):
    p = Path(os.path.abspath(path))
    boundary = Path(boundary)
    if not p.is_relative_to(boundary) or ".." in p.parts:
        raise Stop("path_outside_scope", str(p))
    cursor = boundary
    if cursor.is_symlink():
        raise Stop("symlink", str(cursor))
    for part in p.relative_to(boundary).parts:
        cursor /= part
        if cursor.is_symlink():
            raise Stop("symlink", str(cursor))
    if exists and not p.exists():
        raise Stop("missing_input", str(p))
    return p


def free(path):
    s = os.statvfs(path)
    return s.f_bavail * s.f_frsize


def process_rows():
    result = subprocess.run(
        ["/bin/ps", "-axo", "pid=,ppid=,pgid=,rss=,command="],
        capture_output=True, text=True, check=True,
    )
    rows = []
    for line in result.stdout.splitlines():
        fields = line.strip().split(None, 4)
        if len(fields) == 5:
            rows.append(dict(zip(("pid", "ppid", "pgid", "rss", "command"),
                                [*(int(v) for v in fields[:4]), fields[4]])))
    return rows


def process_gate(rows, own_pid=None):
    blockers, observers = [], []
    for row in rows:
        command = row["command"]
        try:
            argv = shlex.split(command)
        except ValueError:
            argv = command.split()
        if not argv or row["pid"] == own_pid:
            continue
        executable = Path(argv[0]).name
        # A held terminal title is not its old shell/script process.
        if executable in {"kitty", "kitten", "ps"}:
            continue
        shell = executable in {"sh", "bash", "zsh"}
        python = executable.lower().startswith("python")
        if shell and "until ! pgrep" in command and "tail " in command and "hdiutil" not in command:
            observers.append({"pid": row["pid"], "kind": "read_only_status_shell"})
            continue
        runner = any("n6_a_remeasure_aq_execute" in Path(a).name for a in argv[1:]
                     if " " not in a)
        restart = shell and any(s in command for s in (
            "compact-v3", "switch-v3", "run-v3", "auto-compact",
            "hdiutil compact", "n6_a_remeasure_aq_execute",
        ))
        unknown_watch = (shell or python) and any(
            re.search(r"(?:^|[-_])(watch|watcher|monitor)(?:[-_.]|$)", Path(a).name)
            for a in argv[1:] if " " not in a
        )
        heavy = executable in {"circom", "zkfDO-v2.2", "zkfDO", "zkfdo-j-v23",
                               "zkfDO-v2.3-development", "z3"} and (
            str(ROOT) in command or str(MOUNT) in command or executable == "circom")
        if runner or restart or unknown_watch or heavy:
            blockers.append({"pid": row["pid"], "ppid": row["ppid"], "command": command,
                             "kind": "aq_runner" if runner else "compact_or_restart" if restart
                             else "unclassified_watcher" if unknown_watch else "other_heavy_job"})
    return blockers, observers


def start_gate():
    raw = AQ_STATE.read_bytes()
    state = json.loads(raw)
    rows = process_rows()
    blockers, observers = process_gate(rows, os.getpid())
    stopped = (state.get("status") == "stopped"
               and state.get("stop_kind") == "interrupted"
               and re.search(r"signal (2|15);", state.get("stop_reason") or "") is not None
               and bool(state.get("stopped_at")))
    active = [
        {"engine": e, "queue_order": q, "status": r.get("status")}
        for e, d in state.get("engines", {}).items()
        for q, r in d.get("requests", {}).items()
        if r.get("status") == "running"
    ]
    record = {"checked_at": now(), "state_sha256": hashlib.sha256(raw).hexdigest(),
              "state_status": state.get("status"), "stop_kind": state.get("stop_kind"),
              "stop_reason": state.get("stop_reason"), "stopped_at": state.get("stopped_at"),
              "process_blockers": blockers, "observers": observers,
              "active_state_requests": active, "passed": stopped and not blockers and not active}
    return record, state


def revision_space(state):
    """Use request deltas only; never inventory or modify aq caches."""
    rows = {}
    for revision in sorted(REVISIONS):
        samples, caches = [], []
        for engine, data in state.get("engines", {}).items():
            for queue, current in data.get("requests", {}).items():
                for event in [*current.get("history", []), current]:
                    if event.get("revision", current.get("revision")) != revision:
                        continue
                    before = event.get("disk_before", {})
                    start, finish = before.get("external_free_bytes"), event.get("judging_free_bytes_at_finish")
                    if isinstance(start, int) and isinstance(finish, int):
                        samples.append({"engine": engine, "queue": queue,
                                        "delta_bytes": max(0, start - finish),
                                        "disk_before_external_free_bytes": start,
                                        "judging_free_bytes_at_finish": finish})
                    cache = before.get("deferred_cache_store_bytes")
                    if isinstance(cache, int):
                        caches.append(cache)
        peak = max((s["delta_bytes"] for s in samples), default=math.ceil(399.7 * GIB))
        # State exposes aggregate preserved cache/store bytes, not per-request
        # cold cache size. Reserve that entire observed aggregate as a cautious
        # proxy for NEW cache growth; keep the limitation explicit, then measure.
        cache = max(caches, default=math.ceil(399.7 * GIB))
        rows[revision] = {"workspace_peak_bytes": peak, "samples": samples,
                          "workspace_fallback": not samples, "new_cache_estimate_bytes": cache,
                          "cache_estimate_basis": "max recorded aggregate deferred_cache_store_bytes; conservative proxy, not a bound" if caches else "no cache metadata: 399.7 GiB proxy",
                          "required_bytes": 2 * peak + cache}
    return rows


def physical_backing():
    raw = subprocess.check_output(["/usr/bin/hdiutil", "info", "-plist"])
    info = json.loads(subprocess.check_output(["/usr/bin/plutil", "-convert", "json", "-o", "-", "-"], input=raw))
    matches = [i for i in info.get("images", []) if any(
        e.get("mount-point") == str(MOUNT) for e in i.get("system-entities", []))]
    if len(matches) != 1:
        raise Stop("image_backing_unresolved", str(MOUNT))
    image_path = Path(matches[0]["image-path"])
    volume = image_path.parent
    while not volume.is_mount() and volume != volume.parent:
        volume = volume.parent
    if not volume.name.startswith("X9") or volume.stat().st_dev == ROOT.stat().st_dev:
        raise Stop("image_not_on_X9", str(image_path))
    return {"image_path": str(image_path), "x9_volume": str(volume)}


def space_snapshot(backing):
    volume = Path(backing["x9_volume"])
    if not MOUNT.is_mount() or not volume.is_mount():
        raise Stop("mount_missing", backing)
    image_free, x9_free = free(MOUNT), free(volume)
    return {"checked_at": now(), "image_free_bytes": image_free,
            "x9_actual_free_bytes": x9_free, "available_min_bytes": min(image_free, x9_free),
            "internal_free_bytes": free(ROOT)}


def image_gate(plan, state, row=None, *, initial=False):
    gate, _ = start_gate()
    if not gate["passed"]:
        raise Stop("start_gate", gate)
    if gate["state_sha256"] != plan["aq_state_sha256"]:
        raise Stop("aq_state_changed", gate)
    backing = physical_backing()
    if backing != plan["physical_backing"]:
        raise Stop("image_backing_changed", backing)
    record = space_snapshot(backing)
    internal_min = (30 if initial else 20) * GIB
    if record["internal_free_bytes"] < internal_min:
        raise Stop("internal_space", record)
    row = row or next(r for r in plan["requests"] if r["key"] == plan["pilot_key"])
    space = plan["revision_space"][row["revision"]]
    required = space["required_bytes"]
    record.update(revision=row["revision"], workspace_peak_bytes=space["workspace_peak_bytes"],
                  new_cache_estimate_bytes=space["new_cache_estimate_bytes"],
                  required_image_free_bytes=required,
                  formula="2 * revision_max(disk_before.external_free_bytes - judging_free_bytes_at_finish) + new_cache_estimate",
                  passed=record["image_free_bytes"] >= required and record["available_min_bytes"] >= 100 * GIB)
    if not record["passed"]:
        raise Stop("image_space", record)
    return record


def checked_copy_file(folder, info, label):
    entries = [row for row in info["files"] if row["label"] == label]
    if len(entries) != 1:
        raise Stop("copy_binding_missing", f"{folder.name}: {label}")
    p = below(entries[0]["copy"], folder)
    if sha(p) != entries[0]["sha256"]:
        raise Stop("copy_hash_mismatch", str(p))
    return p


def catalog():
    index = read(DEV / "cases/index.json")
    classes_path = DEV / "classes-v1.json"
    if not isinstance(read(classes_path).get("classes"), list):
        raise Stop("class_catalog_invalid", str(classes_path))
    aq = read(AQ_STATE)
    grouped = {}
    for item in index:
        revision, queue = item["revision"], item["queue_order"]
        if revision not in REVISIONS:
            raise Stop("revision_outside_scope", revision)
        folder = below(DEV / "cases" / item["case"], DEV / "cases")
        info = read(folder / "class.json")
        request_path = checked_copy_file(folder, info, "request")
        result_path = checked_copy_file(folder, info, "result")
        request, result = read(request_path), read(result_path)
        key = (revision, queue)
        request_sha = sha(request_path)
        if request_sha != info["class"]["request_sha256"]:
            raise Stop("request_hash_mismatch", item["case"])
        if key not in grouped:
            event = aq["engines"]["v2.2"]["requests"][str(queue)]
            matches = [e for e in [event, *event.get("history", [])]
                       if e.get("result_sha256") == sha(result_path)]
            if len(matches) != 1:
                raise Stop("prior_time_binding", str(queue))
            old = matches[0]
            if old.get("status") != "completed" or old["request_sha256"] != request_sha:
                raise Stop("prior_not_completed", str(queue))
            n = len(result["classes"])
            project = ROOT / "runs/n6-a1b-2026-10-08/units" / revision / "project"
            entry = below(request["entrypoint"], project)
            row = {
                "key": f"{revision}-q{queue:06d}", "revision": revision, "queue_order": queue,
                "original_request_sha256": request_sha, "request_id": request["id"],
                "request_copy": str(request_path), "result_copy": str(result_path),
                "result_copy_sha256": sha(result_path), "class_count": n,
                "old_wall_seconds": old["wall_seconds"],
                "wall_cap_seconds": math.ceil(2 * (old["wall_seconds"] + n * 20)),
                "candidate_copy": str(checked_copy_file(folder, info, "candidate")),
                "base_input_copy": str(checked_copy_file(folder, info, "base_input")),
                "wrapper_copy": str(checked_copy_file(folder, info, "component_wrapper")),
                "project": str(project), "entrypoint": str(entry),
                "library_paths": list(dict.fromkeys(
                    p for p in request.get("library_paths", [])
                    if Path(p).is_relative_to(project))),
                "omitted_external_library_count": len(dict.fromkeys(
                    p for p in request.get("library_paths", [])
                    if not Path(p).is_relative_to(project))),
                "expected_entrypoint": result["entrypoint"],
                "entrypoint_public_outputs": result["entrypoint"]["public_outputs"],
                "cases": [],
            }
            row["input_sha256"] = {p: sha(p) for p in [
                row["candidate_copy"], row["base_input_copy"], row["wrapper_copy"]]}
            grouped[key] = row
        row = grouped[key]
        if row["original_request_sha256"] != request_sha or row["result_copy_sha256"] != sha(result_path):
            raise Stop("duplicate_request_differs", str(queue))
        row["cases"].append({"id": item["case"], "group": item["group"],
                             "representative": item["representative"],
                             "legacy": {k: info["class"].get(k) for k in (
                                 "verdict", "final_reason", "cause_before_budget", "b_outcome")}})
    rows = sorted(grouped.values(), key=lambda r: (r["revision"], r["queue_order"]))
    return index, rows, aq


INCLUDE = re.compile(r'\binclude\s*"([^"]+)"\s*;')


def mask_comments(text):
    # Preserve string literals and offsets while masking comments.
    out, i, quoted = list(text), 0, False
    while i < len(text):
        if text[i] == '"' and (i == 0 or text[i - 1] != "\\"):
            quoted = not quoted
            i += 1
        elif not quoted and text.startswith("//", i):
            end = text.find("\n", i)
            end = len(text) if end < 0 else end
            out[i:end] = " " * (end - i)
            i = end
        elif not quoted and text.startswith("/*", i):
            end = text.find("*/", i + 2)
            if end < 0:
                raise Stop("source_parse", "unterminated comment")
            end += 2
            out[i:end] = ["\n" if c == "\n" else " " for c in text[i:end]]
            i = end
        else:
            i += 1
    return "".join(out)


def source_closure(row):
    project = Path(row["project"])
    wrapper = Path(row["wrapper_copy"])
    libraries = [below(p, project) for p in row["library_paths"]]
    todo = [Path(row["entrypoint"]), wrapper]
    sources, includes = {}, {}
    while todo:
        path = todo.pop()
        if path in sources:
            continue
        if path != wrapper:
            below(path, project)
        text = path.read_text()
        sources[path] = text
        links = []
        for match in INCLUDE.finditer(mask_comments(text)):
            name = match.group(1)
            candidates = [Path(name)] if Path(name).is_absolute() else [
                path.parent / name, project / name, *(p / name for p in libraries)]
            resolved = None
            for candidate in candidates:
                lexical = Path(os.path.abspath(candidate))
                if not lexical.is_relative_to(project):
                    continue
                if lexical.is_file():
                    resolved = below(lexical, project)
                    break
            if resolved is None:
                raise Stop("source_dependency_outside_scope_or_missing",
                           {"source": str(path), "include": name})
            links.append((match.start(1), match.end(1), resolved))
            todo.append(resolved)
        includes[path] = links
    return sources, includes


def make_plan(path):
    path = below(path, LOCAL, exists=False)
    if path.exists():
        raise Stop("existing_plan", str(path))
    index, rows, aq = catalog()
    gate, _ = start_gate()
    for row in rows:
        try:
            sources, _ = source_closure(row)
            row["source_sha256"] = {
                str(p): hashlib.sha256(t.encode()).hexdigest() for p, t in sources.items()}
            row["source_status"] = "ready"
        except (OSError, Stop) as error:
            row["source_status"] = "blocked"
            row["source_error"] = str(error)
    tools = {tool: shutil.which(tool) for tool in ("circom", "node", "snarkjs", "z3")}
    if not all(tools.values()) or sha(ENGINE) != ENGINE_SHA:
        raise Stop("tool_or_engine_missing", tools)
    pilot = min((r for r in rows if r["revision"].startswith("aq-011-")),
                key=lambda r: (r["old_wall_seconds"], r["queue_order"]))
    plan = {"schema": SCHEMA, "created_at": now(), "development_only": True,
            "seed": 0, "class_budget_seconds": 20, "engine": str(ENGINE),
            "engine_sha256": ENGINE_SHA, "runner_sha256": sha(__file__),
            "cleanup_sha256": sha(ROOT / "scripts/n6_a_remeasure_aq_cleanup_v2_1.py"),
            "tools": tools, "tool_sha256": {k: sha(v) for k, v in tools.items()},
            "index_sha256": sha(DEV / "cases/index.json"),
            "classes_sha256": sha(DEV / "classes-v1.json"),
            "aq_state_sha256": sha(AQ_STATE), "initial_gate": gate,
            "revision_space": revision_space(aq), "physical_backing": physical_backing(),
            "allowed_queues": [2055, 2200], "mode": "two_pilots_only",
            "aq_observed_peak_bytes": aq["observed_request_peak_bytes"],
            "case_count": len(index), "request_count": len(rows),
            "pilot_key": pilot["key"], "requests": rows,
            "uncalibrated_seconds": sum(3 * (r["old_wall_seconds"] + 20 * r["class_count"]) for r in rows),
            "total_arm_wall_cap_seconds": sum(3 * r["wall_cap_seconds"] for r in rows),
            "local_recheck_count": sum(c["group"] == "local_refutation" for r in rows for c in r["cases"]),
            "local_recheck_cap_seconds": 300}
    fresh(path, plan)
    return plan


def stage_request(plan, row):
    target = below(IMAGE / row["key"] / "source", IMAGE, exists=False)
    manifest = target.parent / "source-manifest.json"
    if manifest.exists():
        saved = read(manifest)
        if saved["original_source_sha256"] != row["source_sha256"] or sha(saved["request"]) != saved["request_sha256"]:
            raise Stop("staged_request_changed", str(manifest))
        for p, digest in saved["staged_sha256"].items():
            if sha(below(p, target)) != digest:
                raise Stop("staged_source_changed", p)
        return saved
    # A signal can arrive between the first source copy and the manifest.
    # That directory is owned by this request and its manifest is absent, so
    # repeat only the exact pinned copies rather than requiring manual cleanup.
    sources, includes = source_closure(row)
    if {str(p): hashlib.sha256(t.encode()).hexdigest() for p, t in sources.items()} != row["source_sha256"]:
        raise Stop("source_changed", row["key"])
    project = Path(row["project"])
    wrapper = Path(row["wrapper_copy"])
    mapped = {p: target / ("target.circom" if p == wrapper else
                          Path("project") / p.relative_to(project)) for p in sources}
    for original, text in sources.items():
        for start, end, dependency in reversed(includes[original]):
            # Keep relative include bytes (and anonymous-component offsets)
            # intact whenever the project copy preserves their resolution.
            original_name = text[start:end]
            if Path(original_name).is_absolute():
                text = text[:start] + str(mapped[dependency]) + text[end:]
        dest = mapped[original]
        below(dest, target, exists=False)
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_name(dest.name + "." + uuid4().hex + ".tmp")
        tmp.write_text(text)
        os.replace(tmp, dest)
    libraries = list(dict.fromkeys(
        str(target / "project" / Path(p).relative_to(project)) for p in row["library_paths"]))
    for library in libraries:
        Path(library).mkdir(parents=True, exist_ok=True)
    request = read(row["request_copy"])
    request.update(source_root=str(target), entrypoint=str(mapped[Path(row["entrypoint"])]),
                   component_wrapper=str(mapped[wrapper]), library_paths=libraries,
                   base_input=row["base_input_copy"])
    request["candidate"]["path"] = row["candidate_copy"]
    request_path = target.parent / "request.json"
    atomic(request_path, request)
    saved = {"request": str(request_path), "request_sha256": sha(request_path),
             "staged_sha256": {str(p): sha(p) for p in mapped.values()},
             "original_source_sha256": row["source_sha256"],
             "include_rewrite_only": True, "entrypoint": request["entrypoint"],
             "source_root": str(target), "libraries": libraries}
    fresh(manifest, saved)
    return saved


def original_artifact_paths(plan, row, staged):
    # Match lifting/mod.rs::compile_cached exactly; no cache directory search.
    h = hashlib.sha256()
    h.update(b"o0=true\0wasm=true\0")
    h.update(plan["tool_sha256"]["circom"].encode())
    h.update(staged["entrypoint"].encode())
    for p in [staged["source_root"], *staged["libraries"]]:
        h.update(p.encode())
    for p in sorted(staged["staged_sha256"]):
        h.update(p.encode())
        h.update(staged["staged_sha256"][p].encode())
    folder = IMAGE / row["key"] / "cache/j-v2.3" / h.hexdigest()
    stem = Path(staged["entrypoint"]).stem
    return folder / (stem + ".r1cs"), folder / (stem + ".sym")


def tree_rss(rows, root_pid):
    descendants = {root_pid}
    changed = True
    while changed:
        before = len(descendants)
        descendants.update(r["pid"] for r in rows if r["ppid"] in descendants)
        changed = len(descendants) != before
    groups = {r["pgid"] for r in rows if r["pid"] in descendants}
    # Include reparented descendants still in an owned child's process group.
    return sum(r["rss"] * 1024 for r in rows
               if r["pid"] in descendants or (r["pgid"] in groups and r["pgid"] != os.getpgrp()))


def signal_stop(signum, _frame):
    global STOP
    STOP = signum


def terminate_group(process):
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        pass
    # The group leader may exit while a descendant ignores TERM.
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    process.wait()


def execute_process(argv, folder, cap, heartbeat, *, external=True):
    folder.mkdir(parents=True, exist_ok=True)
    tmp = folder / "tmp"
    tmp.mkdir(exist_ok=True)
    env = dict(os.environ, TMPDIR=str(tmp), PYTHONDONTWRITEBYTECODE="1",
               RAYON_NUM_THREADS="1", OMP_NUM_THREADS="1")
    backing = physical_backing() if external else None
    disk_before = space_snapshot(backing) if external else {"internal_free_bytes": free(ROOT)}
    before_free = free(MOUNT if external else ROOT)
    last_disk_check = 0
    disk_samples = []
    started = time.monotonic()
    peak_rss = peak_delta = peak_workspace = 0
    samples = 0
    status = "running"
    with (folder / "stdout.log").open("xb") as stdout, (folder / "stderr.log").open("xb") as stderr:
        process = subprocess.Popen(argv, cwd=ROOT, env=env, stdout=stdout, stderr=stderr,
                                   start_new_session=True)
        try:
            heartbeat({"child_pid": process.pid, "command_started_at": now()})
            while process.poll() is None:
                peak_rss = max(peak_rss, tree_rss(process_rows(), process.pid))
                samples += 1
                peak_delta = max(peak_delta, before_free - free(MOUNT if external else ROOT))
                if STOP is not None:
                    status = "interrupted"
                elif time.monotonic() - started >= cap:
                    status = "wall_cap"
                elif free(ROOT) < 18 * GIB:
                    status = "internal_18GiB_stop"
                if external and time.monotonic() - last_disk_check >= 60:
                    disk = space_snapshot(backing)
                    import n6_a_remeasure_aq_cleanup_v2_1 as cleanup
                    workspace_bytes = cleanup.scan_stats(folder)["du_bytes"]
                    peak_workspace = max(peak_workspace, workspace_bytes)
                    disk_samples.append({**disk, "workspace_allocated_bytes": workspace_bytes})
                    last_disk_check = time.monotonic()
                    if disk["available_min_bytes"] < 100 * GIB:
                        status = "image_emergency_stop"
                heartbeat({"child_pid": process.pid, "wall_seconds": time.monotonic() - started,
                           "sampled_process_tree_peak_rss_bytes": peak_rss,
                           "sampled_image_allocation_peak_bytes": peak_delta})
                if status != "running":
                    terminate_group(process)
                    break
                time.sleep(1)
        except BaseException:
            terminate_group(process)
            raise
        code = process.wait()
    lingering = [r["pid"] for r in process_rows()
                 if r["pgid"] == process.pid and r["pid"] != process.pid]
    if lingering:
        terminate_group(process)
        status = "lingering_child"
    if status == "running":
        status = "completed" if code == 0 else "failed"
    return {"status": status, "returncode": code, "wall_seconds": time.monotonic() - started,
            "wall_cap_seconds": cap, "sampled_process_tree_peak_rss_bytes": peak_rss,
            "rss_sampling_interval_seconds": 1, "rss_samples": samples,
            "sampled_image_allocation_peak_bytes": max(0, peak_delta),
            "disk_before": disk_before, "disk_after": space_snapshot(backing) if external else {"internal_free_bytes": free(ROOT)},
            "minute_disk_samples": disk_samples, "sampled_workspace_peak_bytes": peak_workspace,
            "workspace_sampling_interval_seconds": 60,
            "lingering_child_pids": lingering, "argv": argv}


def compact_class(row):
    synth = row.get("synthesis") or {}
    return {k: row.get(k) for k in ("representative", "pattern", "sites", "verdict", "reason")} | {
        "cause_before_budget": synth.get("cause_before_budget"),
        "b_outcome": synth.get("b_outcome")}


def comparison(result, boost, request_row):
    by_site = {c["representative"]: c for c in result["classes"]}
    if len(by_site) != len(result["classes"]):
        raise Stop("duplicate_class_representative", request_row["key"])
    records = (boost or {}).get("records", [])
    rows = []
    for case in request_row["cases"]:
        site = case["representative"]
        c = by_site.get(site)
        if c is None:
            raise Stop("class_mapping_missing", {"request": request_row["key"], "site": site})
        records_here = [r for r in records if r.get("site") == site]
        direct = [r for r in records_here if r.get("method") == "constraint_witness"]
        verified = [r for r in direct if r.get("status") == "reached"
                    and r.get("rust") == "correct" and r.get("snarkjs") == "correct"
                    and r.get("witness_sha256")]
        budgets = [r for r in records_here if r.get("kind") == "class_budget"]
        steps = [s for s in result["costs"]["steps"] if s.get("site") == site]
        actual_sweep = sum(s["seconds"] for s in steps if s.get("label") == "z3 exclusion sweep")
        rows.append({
            "case": case["id"], "representative": site, "group": case["group"],
            "v2_2": {k: case["legacy"].get(k) for k in (
                "verdict", "final_reason", "cause_before_budget", "b_outcome")},
            "legacy_result": compact_class(c) if c else None,
            "class_mapping_missing": False,
            "direct_attempts": len(direct), "direct_status_counts": dict(Counter(r.get("status") for r in direct)),
            "direct_verified_reach": bool(verified), "direct_l1": any(r.get("l1") is True for r in verified),
            "verdict_conflict": bool(verified and c and c["verdict"] == "excluded_in_context"),
            "aligned": [r.get("aligned", {"reason":"unknown"}) for r in direct],
            "direct_class_diagnostic": next((r for r in records_here if r.get("kind") == "direct_class_diagnostic"), None),
            "direct_seconds": sum(r.get("seconds", 0) for r in direct),
            "direct_stage_seconds": {stage: sum(r.get("stage_seconds", {}).get(stage, 0) for r in direct)
                                     for stage in {k for r in direct for k in r.get("stage_seconds", {})}},
            "failure_diagnostics": [r["failure_diagnostic"] for r in direct if "failure_diagnostic" in r],
            "budget_records": budgets, "measured_sweep_seconds": actual_sweep,
            "class_step_seconds": sum(s["seconds"] for s in steps),
        })
    return rows


def collect_result(plan, row, arm, workspace, local):
    result = read(workspace / "result.json")
    if result.get("request_id") != row["request_id"] or result.get("preparation", {}).get("status") != "ok":
        raise Stop("result_preparation_or_identity", result.get("preparation"))
    for key in ("r1cs_sha256", "sym_sha256", "o0_r1cs_sha256", "public_outputs"):
        if result["entrypoint"].get(key) != row["expected_entrypoint"].get(key):
            raise Stop("original_artifact_mismatch", {"key": key, "request": row["key"]})
    if len(result["classes"]) != row["class_count"]:
        raise Stop("class_count_changed", row["key"])
    boost = read(workspace / "j-boost.json") if (workspace / "j-boost.json").is_file() else None
    if arm == "default" and boost is not None:
        raise Stop("default_option_leak", row["key"])
    if arm != "default" and boost is None:
        raise Stop("boost_record_missing", row["key"])
    # Preserve direct-completion evidence outside the workspace before cleanup.
    evidence = IMAGE / row["key"] / "evidence" / arm
    artifact_rows = []
    for record in (boost or {}).get("records", []):
        if record.get("method") != "constraint_witness":
            continue
        if record.get("status") == "reached":
            witness = below(record["witness"], workspace)
            if sha(witness) != record["witness_sha256"]:
                raise Stop("direct_witness_hash_mismatch", str(witness))
            group = witness.parent
            names = ("completed-o0.wtns", "completed-o0.snarkjs.log", "constraint-witness.wtns",
                     "constraint-witness.snarkjs.log", "input.json", "honest.wtns", "honest.log")
        elif record.get("diagnostic_folder"):
            group = below(record["diagnostic_folder"], workspace)
            names = ("completed-o0.snarkjs.log", "constraint-witness.snarkjs.log", "honest.log")
        else:
            continue
        # Full query/start vectors are large and are not needed once a verified
        # witness or a numbered failure diagnostic has been preserved.
        for name in names:
            source = group / name
            if source.is_file():
                dest = evidence / group.name / name
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, dest)
                digest = sha(source)
                if sha(dest) != digest:
                    raise Stop("evidence_copy_mismatch", str(dest))
                artifact_rows.append({"original": str(source), "preserved": str(dest),
                                      "sha256": digest, "bytes": source.stat().st_size})
    fresh(local / "result.json", result)
    if boost is not None:
        fresh(local / "j-boost.json", boost)
    # Preserve small original adjudication evidence and its bindings before
    # workspace cleanup. Large ordinary witnesses are not duplicated internally.
    legacy_evidence = []
    for c in result["classes"]:
        for label, value in c.get("evidence", {}).items():
            source = Path(value)
            if not source.is_absolute(): source = workspace / source
            if not source.is_relative_to(workspace) or not source.is_file(): continue
            below(source, workspace)
            item = {"site": c["representative"], "label": label, "original": str(source),
                    "bytes": source.stat().st_size, "sha256": sha(source)}
            if source.stat().st_size <= 1024*1024:
                dest = evidence / "legacy-small" / source.relative_to(workspace)
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, dest)
                item["preserved"] = str(dest)
            else: item["preservation"] = "large ordinary evidence; hash only"
            legacy_evidence.append(item)
    fresh(local / "legacy-evidence.json", legacy_evidence)
    fresh(local / "direct-evidence.json", artifact_rows)
    rows = comparison(result, boost, row)
    fresh(local / "cases.json", rows)
    original = read(row["result_copy"])
    full_row = dict(row, cases=[{
        "id": c["representative"], "representative": c["representative"], "group": "all_classes",
        "legacy": {**compact_class(c), "final_reason": c.get("reason")},
    } for c in original["classes"]])
    fresh(local / "all-classes.json", comparison(result, boost, full_row))
    return {"result_sha256": sha(local / "result.json"), "cases": rows,
            "class_count": len(result["classes"]),
            "entrypoint_public_outputs": result["entrypoint"]["public_outputs"],
            "direct_total_seconds": sum(r.get("seconds", 0) for r in (boost or {}).get("records", []) if r.get("method") == "constraint_witness"),
            "preparation_steps": [s for s in result["costs"]["steps"] if not s.get("site")],
            "compile_seconds": sum(s["seconds"] for s in result["costs"]["steps"] if s["stage"] == "compile"),
            "compile_cache_hits": sum(bool(s["cached"]) for s in result["costs"]["steps"] if s["stage"] == "compile"),
            "costs_by_stage": result["costs"]["by_stage"],
            "direct_evidence_files": len(artifact_rows)}


def cleanup_request(row, request_state, local):
    import n6_a_remeasure_aq_cleanup_v2_1 as cleanup
    receipts = []
    for arm in ARMS:
        for attempt in request_state.get("arms", {}).get(arm, []):
            if attempt.get("cleaned"):
                continue
            workspace = below(attempt["workspace"], IMAGE, exists=False)
            binding = {"request": row["key"], "arm": arm, "attempt": attempt["number"],
                       "metrics_path": attempt["metrics_path"],
                       "metrics_sha256": sha(attempt["metrics_path"]),
                       "result_sha256": attempt.get("result_sha256")}
            receipt = cleanup.cleanup_tree(workspace, IMAGE, local / "cleanup", binding, True)
            receipts.append(receipt)
            attempt["cleaned"] = True
    return receipts


def owned_size(row):
    import n6_a_remeasure_aq_cleanup_v2_1 as cleanup
    return cleanup.scan_stats(IMAGE / row["key"])["du_bytes"]


def candidate_values(path):
    raw = read(path)
    raw = raw.get("7_assignment", raw)
    if not isinstance(raw, dict) or not raw:
        raise Stop("candidate_invalid", str(path))
    values = {}
    for name, value in raw.items():
        if not isinstance(value, (str, int)) or not str(value).isdigit():
            raise Stop("candidate_invalid", name)
        values[name] = int(value)
    return values


def make_recheck_query(rpath, spath, candidate, site, target, seed, seconds,
                       expected_r1cs=None, tick=lambda: None):
    if expected_r1cs is not None and sha(rpath) != expected_r1cs:
        raise Stop("recheck_original_r1cs_hash", str(rpath))
    started = time.monotonic()
    symbols = {}
    def check_budget():
        tick()
        if STOP is not None or time.monotonic() - started >= seconds:
            raise Stop("recheck_generation_budget", str(target))
    for index, line in enumerate(Path(spath).read_text().splitlines()):
        parts = line.split(",", 3)
        if len(parts) != 4:
            raise Stop("sym_format", line[:80])
        wire = int(parts[1])
        if parts[3] in symbols and symbols[parts[3]] != wire:
            raise Stop("sym_alias_conflict", parts[3])
        symbols[parts[3]] = wire
        if index % 1000 == 0:
            check_budget()
    with Path(rpath).open("rb") as source, mmap.mmap(source.fileno(), 0, access=mmap.ACCESS_READ) as data:
        if len(data) < 12 or data[:4] != b"r1cs" or struct.unpack_from("<I", data, 4)[0] != 1:
            raise Stop("r1cs_format", str(rpath))
        sections, pos = {}, 12
        for _ in range(struct.unpack_from("<I", data, 8)[0]):
            if pos + 12 > len(data):
                raise Stop("r1cs_sections", str(rpath))
            kind, length = struct.unpack_from("<IQ", data, pos)
            pos += 12
            if kind in sections or pos + length > len(data):
                raise Stop("r1cs_sections", str(rpath))
            sections[kind] = (pos, length)
            pos += length
        if 1 not in sections or 2 not in sections:
            raise Stop("r1cs_sections", str(rpath))
        h, header_length = sections[1]
        width = struct.unpack_from("<I", data, h)[0]
        if width == 0 or width > 128 or header_length != width + 32:
            raise Stop("r1cs_header", str(rpath))
        prime = int.from_bytes(data[h + 4:h + 4 + width], "little")
        wires, outputs, public, private, _, count = struct.unpack_from("<IIIIQI", data, h + 4 + width)
        if prime <= 1 or wires < 1 + outputs + public + private:
            raise Stop("r1cs_header", str(rpath))
        pins, named = {}, []
        for name, value in candidate.items():
            if not name.startswith("main."):
                raise Stop("candidate_mapping_missing", name)
            mapped = site + name[4:]
            wire = symbols.get(mapped, -1)
            if not 0 <= wire < wires or not 0 <= value < prime:
                raise Stop("candidate_mapping_missing", mapped)
            if wire in pins and pins[wire] != value:
                raise Stop("candidate_alias_conflict", mapped)
            pins[wire] = value
            named.append({"name": mapped, "wire": wire, "value": str(value)})
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("x") as out:
            out.write(f"(set-option :timeout {seconds * 1000})\n")
            out.write(f"(set-option :smt.random_seed {seed})\n(set-option :sat.random_seed {seed})\n")
            for wire in range(1, wires):
                out.write(f"(declare-const w{wire} Int)\n(assert (and (<= 0 w{wire}) (< w{wire} {prime})))\n")
                if wire % 1000 == 0:
                    check_budget()
            pos, length = sections[2]
            end = pos + length
            for index in range(count):
                terms3 = []
                for _ in range(3):
                    if pos + 4 > end:
                        raise Stop("r1cs_length", str(rpath))
                    n = struct.unpack_from("<I", data, pos)[0]
                    pos += 4
                    if pos + n * (4 + width) > end:
                        raise Stop("r1cs_length", str(rpath))
                    terms = []
                    for _ in range(n):
                        wire = struct.unpack_from("<I", data, pos)[0]
                        pos += 4
                        coef = int.from_bytes(data[pos:pos + width], "little")
                        pos += width
                        if wire >= wires or coef >= prime:
                            raise Stop("r1cs_term_invalid", index)
                        terms.append(str(coef) if wire == 0 else f"(* {coef} w{wire})")
                    terms3.append("0" if not terms else terms[0] if len(terms) == 1
                                  else "(+ " + " ".join(terms) + ")")
                a, b, c = terms3
                out.write(f"(assert (= (mod (- (* {a} {b}) {c}) {prime}) 0))\n")
                if index % 1000 == 0:
                    check_budget()
            if pos != end:
                raise Stop("r1cs_length", str(rpath))
            for wire, value in pins.items():
                if wire == 0:
                    if value != 1:
                        raise Stop("candidate_wire_zero", value)
                else:
                    out.write(f"(assert (= w{wire} {value}))\n")
            out.write("(check-sat)\n")
    return {"scope": "exact_candidate; other main inputs free; no implicit public-input pins",
            "sat": "recheck_not_refuted; not verified reachability", "pins": named,
            "constraints": count, "wires": wires, "query_sha256": sha(target),
            "r1cs_sha256": sha(rpath), "sym_sha256": sha(spath),
            "query_generation_seconds": time.monotonic() - started}


def assert_pilot_passed(pilot):
    if not pilot.get("cleanup_completed"):
        raise Stop("pilot_cleanup_missing", "per-arm cleanup incomplete")
    for arm in ARMS:
        attempts = pilot.get("arms", {}).get(arm, [])
        if not attempts or attempts[-1]["status"] != "completed" or not attempts[-1].get("validated") or not attempts[-1].get("cleaned"):
            raise Stop("pilot_not_passed", arm)


def estimate_remaining(plan, requests):
    pilots = [r for r in plan["requests"] if r["queue_order"] in (2055, 2200)]
    calibration = []
    for row in pilots:
        p = requests[row["key"]]
        assert_pilot_passed(p)
        arms = {a: p["arms"][a][-1] for a in ARMS}
        dynamic = {a: max(0, v["wall_seconds"] - v.get("compile_seconds", 0)) for a, v in arms.items()}
        calibration.append({"queue": row["queue_order"],
            "ratio": max(1, arms["default"]["wall_seconds"] / row["old_wall_seconds"]),
            "fair_extra_per_class": max(0, dynamic["fair"] - dynamic["default"]) / row["class_count"],
            "direct_extra_per_class": max(0, dynamic["direct"] - dynamic["fair"]) / row["class_count"],
            "measured_peak_bytes": p["observed_peak_bytes"]})
    ratio = max(c["ratio"] for c in calibration)
    fair = max(c["fair_extra_per_class"] for c in calibration)
    direct = max(c["direct_extra_per_class"] for c in calibration)
    rows = []
    for row in plan["requests"]:
        if row["queue_order"] in (2055, 2200): continue
        seconds = 3 * row["old_wall_seconds"] * ratio + row["class_count"] * (2 * fair + direct)
        rows.append({"request": row["key"], "expected_seconds": seconds,
                     "planning_upper_seconds": 2 * seconds, "arm_cap_seconds": row["wall_cap_seconds"],
                     "image_required_bytes": plan["revision_space"][row["revision"]]["required_bytes"]})
    return {"rows": rows, "calibration": calibration, "expected_seconds": sum(r["expected_seconds"] for r in rows),
            "planning_upper_seconds": sum(r["planning_upper_seconds"] for r in rows),
            "note": "two development pilots; maxima extrapolated, not a measured or guaranteed upper bound; full run prohibited"}


class Execution:
    def __init__(self, plan_path):
        self.path = below(plan_path, LOCAL)
        self.plan = read(self.path)
        if self.plan["runner_sha256"] != sha(__file__) or sha(ENGINE) != self.plan["engine_sha256"]:
            raise Stop("runner_or_engine_changed", str(self.path))
        for tool, path in self.plan["tools"].items():
            if sha(path) != self.plan["tool_sha256"][tool]:
                raise Stop("tool_changed", tool)
        if sha(ROOT / "scripts/n6_a_remeasure_aq_cleanup_v2_1.py") != self.plan["cleanup_sha256"]:
            raise Stop("cleanup_module_changed", "")
        self.directory = LOCAL / "execution" / self.path.stem
        self.directory.mkdir(parents=True, exist_ok=True)
        self.state_path = self.directory / "state.json"
        self.state = read(self.state_path) if self.state_path.exists() else {
            "schema": SCHEMA, "plan": str(self.path), "plan_sha256": sha(self.path),
            "status": "prepared", "requests": {}, "created_at": now(),
            "observed_request_peak_bytes": 0, "owned_preserved_bytes": 0}
        if self.state["plan_sha256"] != sha(self.path):
            raise Stop("plan_changed", str(self.path))
        self.last_heartbeat = 0
        self.retry_failed = False

    def save(self, detail=None, force=False):
        if detail:
            self.state["current"] = detail
        self.state["pid"] = os.getpid()
        self.state["updated_at"] = now()
        atomic(self.state_path, self.state)
        if force or time.monotonic() - self.last_heartbeat >= 60:
            beat = {"at": now(), "pid": os.getpid(), "status": self.state["status"],
                    "current": self.state.get("current")}
            atomic(self.directory / "heartbeat.json", beat)
            with (self.directory / "heartbeat.jsonl").open("a") as stream:
                stream.write(json.dumps(beat, ensure_ascii=False) + "\n")
            self.last_heartbeat = time.monotonic()

    def callback(self, detail):
        if time.monotonic() - self.last_heartbeat >= 60:
            self.save({**(self.state.get("current") or {}), **detail})

    @contextmanager
    def lock(self):
        with (self.directory / "execution.lock").open("a") as handle:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise Stop("execution_already_running", str(self.state_path)) from None
            yield

    def recover(self):
        rows = process_rows()
        pids = {r["pid"] for r in rows}
        for request in self.state["requests"].values():
            for attempts in request.get("arms", {}).values():
                for attempt in attempts:
                    if attempt["status"] == "running":
                        if attempt.get("child_pid") in pids:
                            raise Stop("previous_child_alive", attempt["child_pid"])
                        attempt["status"] = "interrupted_unreaped"
                        metrics = Path(attempt["metrics_path"])
                        if not metrics.exists():
                            fresh(metrics, {**attempt, "recovered_at": now(), "incomplete_measurement": True})
        self.save(force=True)

    def arm(self, row, arm, staged, request_state):
        attempts = request_state.setdefault("arms", {}).setdefault(arm, [])
        if attempts:
            last = attempts[-1]
            if last["status"] == "completed" and last.get("validated"):
                return
            if last["status"] in {"wall_cap", "failed", "invalid_result"} and not self.retry_failed:
                return
        guard = image_gate(self.plan, self.state, row)
        number = len(attempts) + 1
        workspace = IMAGE / row["key"] / "work" / arm / f"attempt-{number:04d}"
        local = self.directory / row["key"] / arm / f"attempt-{number:04d}"
        local.mkdir(parents=True, exist_ok=True)
        fresh(local / "disk-before.json", guard)
        argv = [str(ENGINE), "--request", staged["request"], "--output", str(workspace / "judgment"),
                "--cache", str(IMAGE / row["key"] / "cache"),
                "--instance-store", str(IMAGE / row["key"] / "stores" / arm)]
        for tool in ("circom", "node", "snarkjs"):
            argv += ["--" + tool + "-bin", self.plan["tools"][tool]]
        argv += ["--z3-bin", str(self.directory / "z3-seeded"), *FLAGS[arm]]
        attempt = {"number": number, "status": "running", "started_at": now(),
                   "workspace": str(workspace), "metrics_path": str(local / "metrics.json")}
        attempts.append(attempt)
        self.state["status"] = "running"
        self.save({"request": row["key"], "arm": arm, "attempt": number}, force=True)

        def tick(detail):
            if detail.get("child_pid"):
                first_child = "child_pid" not in attempt
                attempt["child_pid"] = detail["child_pid"]
                if first_child:
                    self.save({**self.state["current"], **detail}, force=True)
            self.callback(detail)

        metrics = execute_process(argv, workspace, row["wall_cap_seconds"], tick)
        attempt.update(metrics, finished_at=now())
        for name in ("stdout.log", "stderr.log"):
            source = workspace / name
            if source.exists():
                with source.open("rb") as f:
                    f.seek(max(0, source.stat().st_size - 65536))
                    (local / name).write_bytes(f.read())
        if metrics["status"] == "completed":
            try:
                attempt.update(collect_result(self.plan, row, arm, workspace / "judgment", local), validated=True)
            except (OSError, KeyError, ValueError, Stop) as error:
                attempt.update(status="invalid_result", result_error=str(error), validated=False)
                if (workspace / "judgment/result.json").is_file() and not (local / "unvalidated-result.json").exists():
                    fresh(local / "unvalidated-result.json", read(workspace / "judgment/result.json"))
        import n6_a_remeasure_aq_cleanup_v2_1 as cleanup
        attempt["workspace_allocated_bytes_at_finish"] = cleanup.scan_stats(workspace)["du_bytes"]
        attempt["sampled_workspace_peak_bytes"] = max(attempt["sampled_workspace_peak_bytes"], attempt["workspace_allocated_bytes_at_finish"])
        peak = max(attempt["sampled_workspace_peak_bytes"], attempt["sampled_image_allocation_peak_bytes"])
        request_state["observed_peak_bytes"] = max(request_state.get("observed_peak_bytes", 0), peak)
        self.state["observed_request_peak_bytes"] = max(self.state["observed_request_peak_bytes"], peak)
        attempt["direct_fraction_of_arm_wall"] = attempt.get("direct_total_seconds", 0) / max(attempt["wall_seconds"], 1e-9)
        fresh(local / "metrics.json", {k: v for k, v in attempt.items() if k != "cases"})
        receipts = cleanup_request(row, request_state, self.directory / row["key"])
        request_state.setdefault("cleanup_receipts", []).extend(receipts)
        attempt["disk_after_cleanup"] = space_snapshot(self.plan["physical_backing"])
        fresh(local / "disk-after-cleanup.json", attempt["disk_after_cleanup"])
        request_state["preserved_bytes"] = owned_size(row)
        self.state["owned_preserved_bytes"] = sum(r.get("preserved_bytes", 0) for r in self.state["requests"].values())
        self.save(force=True)
        if metrics["status"] in {"interrupted", "internal_18GiB_stop", "image_emergency_stop"}:
            raise Stop(metrics["status"], row["key"])

    def recheck(self, row, staged, request_state):
        rpath, spath = original_artifact_paths(self.plan, row, staged)
        for case in row["cases"]:
            if case["group"] != "local_refutation":
                continue
            saved = request_state.setdefault("rechecks", {})
            if case["id"] in saved:
                continue
            if not rpath.is_file() or not spath.is_file():
                saved[case["id"]] = {"status": "unknown", "reason": "original_o0_artifacts_missing",
                                     "required": [str(rpath), str(spath)]}
                self.save()
                continue
            guard = image_gate(self.plan, self.state, row)
            folder = IMAGE / row["key"] / "rechecks" / case["id"]
            # A prior interrupted query is preserved; resume uses a new folder.
            folder /= uuid4().hex
            started = time.monotonic()
            cap = self.plan["local_recheck_cap_seconds"]
            self.save({"request": row["key"], "recheck": case["id"]}, force=True)
            def tick():
                self.callback({})
                if STOP is not None:
                    raise Stop("interrupted", STOP)
                if free(ROOT) < 18 * GIB:
                    raise Stop("internal_18GiB_stop", "during recheck preparation")
                if space_snapshot(self.plan["physical_backing"])["available_min_bytes"] < 100 * GIB:
                    raise Stop("image_emergency_stop", "during recheck preparation")
            try:
                scope = make_recheck_query(
                    rpath, spath, candidate_values(row["candidate_copy"]), case["representative"],
                    folder / "query.smt2", self.plan["seed"], cap,
                    row["expected_entrypoint"]["o0_r1cs_sha256"], tick)
                fresh(folder / "scope.json", scope)
                remaining = max(1, cap - (time.monotonic() - started))
                metrics = execute_process(
                    [self.plan["tools"]["z3"], "-smt2", str(folder / "query.smt2")],
                    folder / "solver", remaining, self.callback)
                if metrics["status"] in {"interrupted", "internal_18GiB_stop", "image_emergency_stop"}:
                    raise Stop(metrics["status"], str(folder))
                lines = (folder / "solver/stdout.log").read_text().splitlines()
                outcome = next((x.strip() for x in lines if x.strip() in {"sat", "unsat", "unknown"}), None)
                status = ("exact_candidate_excluded_without_unrelated_main_pins" if outcome == "unsat"
                          else "recheck_not_refuted" if outcome == "sat" else "unknown")
                if metrics["status"] != "completed":
                    status = "unknown"
                saved[case["id"]] = {"status": status, "solver_outcome": outcome,
                                     "scope": scope, "metrics": metrics, "disk_before": guard,
                                     "folder": str(folder), "total_seconds": time.monotonic() - started}
            except (OSError, ValueError, KeyError, Stop) as error:
                if isinstance(error, Stop) and error.kind in {"interrupted", "internal_18GiB_stop", "image_emergency_stop"}:
                    raise
                saved[case["id"]] = {"status": "unknown", "reason": str(error),
                                     "folder": str(folder), "total_seconds": time.monotonic() - started}
            request_state["preserved_bytes"] = owned_size(row)
            self.state["owned_preserved_bytes"] = sum(r.get("preserved_bytes", 0) for r in self.state["requests"].values())
            self.save(force=True)

    def run(self, action, with_rechecks):
        if os.getpriority(os.PRIO_PROCESS, 0) != 19:
            raise Stop("nice_required", "run with nice -n 19")
        with self.lock():
            self.recover()
            guard = image_gate(self.plan, self.state, initial=True)
            self.state["initial_image_gate"] = guard
            IMAGE.mkdir(exist_ok=True)
            if not (self.directory / "z3-seeded").exists():
                script = "#!/usr/bin/env python3\nimport os,sys\np=" + repr(self.plan["tools"]["z3"]) + "\nos.execv(p,[p,'smt.random_seed=" + str(self.plan["seed"]) + "','sat.random_seed=" + str(self.plan["seed"]) + "',*sys.argv[1:]])\n"
                (self.directory / "z3-seeded").write_text(script)
                (self.directory / "z3-seeded").chmod(0o755)
            pilot = next(r for r in self.plan["requests"] if r["key"] == self.plan["pilot_key"])
            second = next(r for r in self.plan["requests"] if r["queue_order"] == 2200)
            if self.plan.get("mode") != "two_pilots_only" or self.plan.get("allowed_queues") != [2055, 2200]:
                raise Stop("plan_mode", "this runner only permits the two step4 pilots")
            ordered = [pilot] if action in {"pilot", "recheck"} else [pilot, second]
            for row in ordered:
                if row == second:
                    assert_pilot_passed(self.state["requests"].get(pilot["key"], {}))
                if row["source_status"] != "ready":
                    raise Stop("source_preparation_blocked", row.get("source_error"))
                for path, expected in row["input_sha256"].items():
                    if sha(path) != expected:
                        raise Stop("input_changed", path)
                request_state = self.state["requests"].setdefault(row["key"], {})
                image_gate(self.plan, self.state, row)
                staged = stage_request(self.plan, row)
                if action != "recheck":
                    for arm in ARMS:
                        self.arm(row, arm, staged, request_state)
                    if not request_state.get("cleanup_completed"):
                        receipts = cleanup_request(row, request_state, self.directory / row["key"])
                        request_state.setdefault("cleanup_receipts", []).extend(receipts)
                        request_state["cleanup_completed"] = True
                        request_state["preserved_bytes"] = owned_size(row)
                        self.state["owned_preserved_bytes"] = sum(r.get("preserved_bytes", 0) for r in self.state["requests"].values())
                        self.save(force=True)
                if with_rechecks or action == "recheck":
                    self.recheck(row, staged, request_state)
                assert_pilot_passed(request_state)
            if action == "pilots":
                self.state["estimate_remaining_13"] = estimate_remaining(self.plan, self.state["requests"])
            self.state["status"] = "pilot_completed" if action == "pilot" else "completed"
            self.save(force=True)


def status(plan_path):
    directory = LOCAL / "execution" / Path(plan_path).stem
    p = directory / "state.json"
    if not p.exists():
        return {"status": "not_started", "state": str(p)}
    s = read(p)
    return {k: s.get(k) for k in ("status", "pid", "updated_at", "current", "stop_kind", "stop_reason", "estimate_remaining_13")} | {
        "requests_recorded": len(s["requests"]), "state": str(p),
        "heartbeat": read(directory / "heartbeat.json") if (directory / "heartbeat.json").exists() else None}


def summarize(plan_path):
    plan = read(plan_path)
    directory = LOCAL / "execution" / Path(plan_path).stem
    state = read(directory / "state.json") if (directory / "state.json").exists() else {"requests": {}}
    output = []
    reasons = ("model_not_reproduced", "synthesis_timeout", "cone_refuted_by_propagation_only", "injection_not_applied")
    for row in plan["requests"]:
        req = state["requests"].get(row["key"], {})
        for arm in ARMS:
            attempts = req.get("arms", {}).get(arm, [])
            last = attempts[-1] if attempts else {}
            classes_path = Path(last["metrics_path"]).parent / "all-classes.json" if last else None
            classes = read(classes_path) if classes_path and classes_path.exists() else []
            pairs = [(c["v2_2"].get("verdict"), (c["legacy_result"] or {}).get("verdict")) for c in classes]
            grouped = {}
            for reason in reasons:
                subset = [c for c in classes if any(
                    reason == v or (reason == "model_not_reproduced" and v == "synthesis_model_not_reproduced")
                    for v in c["v2_2"].values())]
                grouped[reason] = {"prior_count": len(subset), "current": dict(Counter(
                    (c["legacy_result"] or {}).get("verdict", "missing") for c in subset)),
                    "direct_verified_reach": sum(c["direct_verified_reach"] for c in subset)}
            output.append({"request": row["key"], "arm": arm, "status": last.get("status", "not_run"),
                           "full_class_count": row["class_count"], "selected_case_count": len(row["cases"]),
                           "entrypoint_public_outputs": row["entrypoint_public_outputs"],
                           "aligned_attempt_distribution": dict(Counter(a.get("reason", "unknown") for c in classes for a in c.get("aligned", []))),
                           "failure_diagnostic_distribution": dict(Counter(d.get("category") for c in classes for d in c.get("failure_diagnostics", []))),
                           "direct_seconds": last.get("direct_total_seconds"),
                           "direct_fraction_of_arm_wall": last.get("direct_fraction_of_arm_wall"),
                           "baseline_differences": [c["representative"] for c in classes if c["v2_2"].get("verdict") != c["legacy_result"].get("verdict") or c["v2_2"].get("final_reason") != c["legacy_result"].get("reason")],
                           "unknown_to_conclusion": sum(a == "unknown" and b in CONCLUSIONS for a, b in pairs) if classes else None,
                           "conclusion_to_unknown": sum(a in CONCLUSIONS and b == "unknown" for a, b in pairs) if classes else None,
                           "transition_counts": dict(Counter(f"{a}->{b}" for a, b in pairs)),
                           "direct_reach_supplement": sum(c["direct_verified_reach"] and not c["verdict_conflict"] for c in classes) if classes else None,
                           "direct_l1_supplement": sum(c["direct_l1"] and not c["verdict_conflict"] for c in classes) if classes else None,
                           "direct_conflicts": sum(c["verdict_conflict"] for c in classes) if classes else None,
                           "direct_attempts": sum(c["direct_attempts"] for c in classes) if classes else None,
                           "wall_seconds": last.get("wall_seconds"), "all_attempt_seconds": sum(a.get("wall_seconds", 0) for a in attempts),
                           "peak_rss_bytes": last.get("sampled_process_tree_peak_rss_bytes"),
                           "workspace_bytes": last.get("sampled_workspace_peak_bytes"),
                           "by_prior_cause": grouped, "rechecks": req.get("rechecks", {})})
    return {"development_only": True, "plan_sha256": sha(plan_path), "generated_at": now(), "rows": output}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "gate", "pilot", "pilots", "status", "recheck", "summary"))
    parser.add_argument("--plan", type=Path, default=LOCAL / "plan-v6.json")
    parser.add_argument("--local-refutation-recheck", action="store_true")
    parser.add_argument("--retry-failed", action="store_true", help="preserve failed attempts and explicitly retry them")
    args = parser.parse_args()
    LOCAL.mkdir(parents=True, exist_ok=True)
    execution = None
    try:
        if args.action == "prepare":
            plan = make_plan(args.plan)
            output = {k: plan[k] for k in ("request_count", "case_count", "pilot_key", "initial_gate",
                                           "uncalibrated_seconds", "total_arm_wall_cap_seconds")}
            output["source_status"] = dict(Counter(r["source_status"] for r in plan["requests"]))
        elif args.action == "gate":
            output, _ = start_gate()
            fresh(LOCAL / ("gate-" + uuid4().hex + ".json"), output)
        elif args.action == "status":
            output = status(args.plan)
        elif args.action == "summary":
            output = summarize(args.plan)
        else:
            signal.signal(signal.SIGTERM, signal_stop)
            signal.signal(signal.SIGINT, signal_stop)
            execution = Execution(args.plan)
            execution.retry_failed = args.retry_failed
            execution.run(args.action, args.local_refutation_recheck)
            output = status(args.plan)
        print(json.dumps(output, ensure_ascii=False, indent=2))
        return 0
    except (Stop, OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        kind = error.kind if isinstance(error, Stop) else type(error).__name__
        if execution is not None:
            execution.state.update(status="stopped", stop_kind=kind, stop_reason=str(error))
            execution.save(force=True)
        print(json.dumps({"status": "stopped", "kind": kind, "reason": str(error)}, ensure_ascii=False), flush=True)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

