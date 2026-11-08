#!/usr/bin/env python3
"""Aq-state-gated Round 4c replay, S and new-J executor.

Only a human-supplied, SHA-pinned plan can execute. J's request workspace,
cache, output and instance store live in a dedicated mounted image tree.
The immutable 4b runner supplies the S mechanics; its pre-deadline monitor
is not used for execution.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time

import n6_a_remeasure_aq_cleanup_v2_1 as cleanup
import n6_a_remeasure_aq_execute_v3_2 as aq_v32
import s_round4b_postdeadline_20261027 as previous
import s_round4c_protocol_20261027 as protocol

ROOT = Path(__file__).resolve().parents[1]
ROUND = ROOT / "runs/s-round4-2026-10-27"
OUT = ROUND / "round4c-main"
MOUNT = Path("/Volumes/zkfdo-jcache")
IMAGE = MOUNT / "s-round4c-20261027"
GIB = 1024**3
DEADLINE = datetime(2026, 10, 28, 15, tzinfo=timezone.utc)
AQ_STATE = ROOT / "runs/n6-a-remeasure-2026-10-25.noindex/aq-exec/state-v3_2.json"
AQ_V31_STATE = AQ_STATE.with_name("state-v3_1.json")
if os.environ.get("S_ROUND4C_AQ_STATE_PATH"):
    selected_state = Path(os.environ["S_ROUND4C_AQ_STATE_PATH"])
    if selected_state not in (AQ_STATE, AQ_V31_STATE):
        raise ValueError("unrecognized aq state path")
    AQ_STATE = selected_state
AMENDMENT = ROOT / "docs/s_round4c_amendment_2026-10-27_v3.md"
PREVIOUS_AMENDMENT = ROOT / "docs/s_round4c_amendment_2026-10-27.md"
PREVIOUS_AMENDMENT_SHA = "a7051cd0f36edcb8a4383b638bd51ead8a9d502092e7f259cb62709105501726"


def require(ok: bool, message: str) -> None:
    if not ok:
        raise ValueError(message)


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def checked_input(value: str | Path) -> Path:
    path = Path(value).absolute()
    require(".." not in path.parts and path.is_relative_to(ROOT), "input outside repository")
    require(path.is_file() and path.resolve().is_relative_to(ROOT), "missing or external input")
    return path


def checked_output(value: str | Path) -> Path:
    path = Path(value).absolute()
    require(".." not in path.parts and path.is_relative_to(OUT) and path != OUT,
            "output outside new 4c folder")
    require(path.parent.resolve().is_relative_to(OUT), "output parent escapes new folder")
    return path


def read_pin(pin: dict) -> tuple[Path, dict]:
    path = checked_input(pin["path"])
    require(sha(path) == pin["sha256"], f"input SHA changed: {path}")
    return path, json.loads(path.read_text())


def write_new(path: str | Path, value: dict) -> dict:
    path = checked_output(path)
    raw = (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(raw)
    return {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}


def required_image_bytes(peak: int, retained: int) -> int:
    """Same 1.2 * measured peak + retained reserve used by aq v3.2."""
    require(type(peak) is int and peak > 0 and type(retained) is int and retained >= 0,
            "measured positive peak and nonnegative retained bytes required")
    return math.ceil(1.2 * max(aq_v32.INITIAL_PEAK, peak)) + retained


def image_gate(peak: int, retained: int, *, mount: Path = MOUNT,
               free_bytes=None, is_mount=None) -> dict:
    mounted = (is_mount or Path.is_mount)(mount)
    require(mounted and mount.resolve() == mount, "dedicated image is not mounted")
    free = (free_bytes or (lambda path: os.statvfs(path).f_bavail * os.statvfs(path).f_frsize))(mount)
    required = required_image_bytes(peak, retained)
    require(free >= required, "image free space below aq v3.2 reserve")
    return {"image_free_bytes": free, "image_required_bytes": required,
            "measured_peak_bytes": peak, "retained_bytes": retained}


def internal_gate(peak: int, retained: int) -> dict:
    require(type(peak) is int and peak > 0 and type(retained) is int and retained >= 0,
            "measured internal peak/retained required")
    free = os.statvfs(ROOT).f_bavail * os.statvfs(ROOT).f_frsize
    needed = max(15 * GIB, math.ceil(1.2 * peak) + retained)
    require(free >= needed, "internal free space below stage estimate")
    return {"internal_free_bytes": free, "internal_required_bytes": needed,
            "measured_peak_bytes": peak, "retained_bytes": retained}


def quiet_host() -> None:
    rows = subprocess.run(["/bin/ps", "-axo", "pid=,args="], check=True,
                          capture_output=True, text=True).stdout
    for row in rows.splitlines():
        parts = row.strip().split(None, 1)
        if len(parts) != 2 or not parts[0].isdigit() or int(parts[0]) in (os.getpid(), os.getppid()):
            continue
        command = parts[1]
        if any(name in command for name in ("n6_a_remeasure_aq_execute_", "n6_a_remeasure_aq_switch")):
            raise ValueError("aq executor still active; no process touched")


def validate_aq_state(state: dict, *, now: datetime | None = None,
                      aq_stopped_by_miiz: bool = False) -> dict:
    """Accept only a saved, quiescent v3.2 endpoint for this invocation."""
    require(state.get("schema") == aq_v32.SCHEMA, "aq v3.2 state schema differs")
    require((now or datetime.now(timezone.utc)) >= DEADLINE or aq_stopped_by_miiz,
            "--aq-stopped-by-miiz required before 2026-10-28T15:00:00Z")
    status = state.get("status")
    if status == "completed":
        require(bool(state.get("finished_at")), "completed aq state lacks finished_at")
    elif status == "stopped" and state.get("stop_kind") == "deadline":
        require(bool(state.get("stopped_at")), "deadline-stopped aq state lacks stopped_at")
    elif status == "stopped" and state.get("stop_kind") == "interrupted":
        require(bool(state.get("stopped_at")) and
                re.fullmatch(r"signal (?:2|15); request saved", state.get("stop_reason") or ""),
                "aq signal stop has no saved request")
    else:
        raise ValueError("aq state is not a permitted final endpoint")
    require(not state.get("pending_progress"), "aq progress save is pending")
    engines = state.get("engines")
    require(isinstance(engines, dict) and engines, "aq request state missing")
    for engine in engines.values():
        requests = engine.get("requests")
        require(isinstance(requests, dict), "aq request table missing")
        for event in requests.values():
            require(event.get("status") in ("completed", "preparation_failure", "failed"),
                    "aq request remains running or has an unknown state")
            for kind in ("metrics", "result"):
                path, digest = event.get(f"{kind}_path"), event.get(f"{kind}_sha256")
                require(bool(path) == bool(digest), f"aq {kind} path/SHA incomplete")
                require(kind != "metrics" or bool(path), "aq saved request lacks metrics")
                require(event["status"] == "failed" or kind != "result" or bool(path),
                        "aq terminal request lacks result")
                if path:
                    require(sha(checked_input(path)) == digest, f"aq saved {kind} SHA changed")
    return state


def capture_aq_state(output: Path, *, source: Path | None = None,
                     now: datetime | None = None,
                     aq_stopped_by_miiz: bool = False) -> tuple[dict, dict]:
    """Copy the live final state byte-for-byte at this invocation's start."""
    global AQ_STATE
    if source is None:
        source = AQ_STATE if AQ_STATE.is_file() else AQ_V31_STATE
        AQ_STATE = source
        os.environ["S_ROUND4C_AQ_STATE_PATH"] = str(source)
    source = checked_input(source)
    require(source.name in ("state-v3_2.json", "state-v3_1.json"), "aq state source must be v3.1 or v3.2")
    output = checked_output(output)
    quiet_host()
    raw = source.read_bytes()
    state = validate_aq_state(json.loads(raw), now=now,
                              aq_stopped_by_miiz=aq_stopped_by_miiz)
    digest = hashlib.sha256(raw).hexdigest()
    require(sha(source) == digest, "aq state changed while being copied")
    quiet_host()
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("xb") as stream:
        stream.write(raw)
    require(sha(source) == digest, "aq state changed after start-state copy")
    quiet_host()
    receipt = write_new(output.with_name(output.stem + ".receipt.json"), {
        "source_path": str(source), "source_sha256": digest,
        "snapshot_path": str(output), "snapshot_sha256": digest,
        "copied_at": datetime.now(timezone.utc).isoformat(),
    })
    return {"path": str(output), "sha256": digest, "receipt": receipt}, state


def aq_disk_peaks(state: dict) -> dict[tuple[str, int, str], int]:
    """Per-request workspace peaks recorded in the final state's cleanup receipts."""
    peaks: dict[tuple[str, int, str], int] = {}
    for receipt in state.get("cleanup_receipts", []):
        binding = receipt.get("binding", {})
        key = (binding.get("engine"), binding.get("queue_order"),
               binding.get("request_sha256"))
        size = receipt.get("du_bytes")
        if (key[0] and type(key[1]) is int and key[2] and
                type(size) is int and size > 0 and
                binding.get("kind") not in ("caches", "stores", "request_remainder")):
            peaks[key] = max(peaks.get(key, 0), size)
    return peaks


def select_replay(inventory: dict, aq_state: dict) -> list[dict]:
    """Selection depends only on revision, request order, completeness and size."""
    require(inventory["schema"] == "s-round4c-replay-inventory-v1", "replay inventory schema")
    rows = inventory["rows"]
    selected: list[dict] = []
    for revision, count in (("banyan-fixed", 24), ("banyan-vulnerable", 108)):
        eligible = sorted((r for r in rows if r["revision"] == revision and r["method"] == "S"),
                          key=lambda r: r["queue_order"])
        require(len(eligible) >= count, "banyan replay inventory insufficient")
        accepted = 0
        elapsed = 0.0
        time_prefix_complete = False
        for row in eligible:
            if not valid_replay_row(row):
                continue
            if revision == "banyan-vulnerable" and elapsed + row["recorded_wall_seconds"] > 10800:
                time_prefix_complete = True
                break
            selected.append(row)
            accepted += 1
            elapsed += row["recorded_wall_seconds"]
            if accepted == count:
                break
        require(accepted == count or (time_prefix_complete and accepted > 0),
                "banyan eligible replay rows exhausted")
    peaks = aq_disk_peaks(aq_state)
    aq_inventory = {}
    for row in rows:
        if row["corpus"] == "aq":
            key = (row.get("engine"), row["queue_order"], row["request"]["sha256"])
            require(key not in aq_inventory, "duplicate aq replay inventory row")
            aq_inventory[key] = row
    aq = []
    for engine_name, engine in aq_state["engines"].items():
        if engine_name != "v2.2":
            continue
        for queue, event in engine["requests"].items():
            if event.get("status") != "completed":
                continue
            key = (engine_name, int(queue), event["request_sha256"])
            row = aq_inventory.get(key)
            if (row is not None and key in peaks and
                    row["completed_result"]["sha256"] == event.get("result_sha256") and
                    row.get("recorded_peak_bytes") == peaks[key]):
                aq.append(row)
    aq.sort(key=lambda r: (peaks[(r["engine"], r["queue_order"], r["request"]["sha256"])],
                           r["queue_order"], r["engine"]))
    chosen = 0
    for row in aq:
        if valid_replay_row(row):
            selected.append(row)
            chosen += 1
            if chosen == 5:
                break
    require(chosen == 5, "fewer than five intact completed aq requests")
    return selected


def valid_replay_row(row: dict) -> bool:
    if row.get("status") != "completed" or row.get("recorded_wall_seconds", 0) <= 0:
        return False
    try:
        for pin in (row["request"], row["completed_result"], *row["inputs"]):
            path = checked_input(pin["path"])
            if sha(path) != pin["sha256"]:
                return False
        result = json.loads(checked_input(row["completed_result"]["path"]).read_text())
        return result.get("request_sha256") == row["request"]["sha256"] and \
            result.get("preparation", {}).get("status") == "ok"
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        return False


class PostMonitor:
    """Only owned children; each cap is exactly twice its recorded estimate."""

    ROOT = ROOT
    RUNROOT = ROUND
    GIB = GIB

    def __init__(self, limits: dict[str, int]):
        self.limits = limits
        self.cargo_started = False
        self.phase_end = None
        self.phase_name = None
        self.retained_image_bytes = 0

    def begin_phase(self, name: str, expected: float):
        require(math.isfinite(expected) and expected > 0, "positive stage estimate required")
        self.phase_name = name
        self.phase_end = time.monotonic() + 2 * expected

    def end_phase(self):
        require(self.phase_end is not None and time.monotonic() <= self.phase_end,
                "stage exceeded twice its estimate")
        self.phase_name = self.phase_end = None

    @staticmethod
    def owned(value):
        return checked_output(value)

    @staticmethod
    def write_new(path, value):
        return write_new(path, value)

    @staticmethod
    def free_bytes():
        return os.statvfs(ROOT).f_bavail * os.statvfs(ROOT).f_frsize

    @staticmethod
    def target_bytes() -> int:
        target = ROUND / "cargo-target"
        require(not target.is_symlink(), "cargo target symlink refused")
        if not target.exists():
            return 0
        result = subprocess.run(["/usr/bin/du", "-sk", str(target)], check=True,
                                capture_output=True, text=True)
        return int(result.stdout.split()[0]) * 1024

    def gate(self, cargo: bool = False):
        quiet_host()
        require(os.getpriority(os.PRIO_PROCESS, 0) == 19, "nice 19 required")
        free = self.free_bytes()
        require(free >= 20 * GIB, "internal free space below 20 GiB start gate")
        if cargo:
            require(self.target_bytes() <= 8 * GIB, "cargo target exceeds 8 GiB")
            if not self.cargo_started:
                require(free >= 30 * GIB, "first cargo build requires 30 GiB free")
                self.cargo_started = True

    def run(self, argv: list[str], label: str, timeout: int = 0, cargo: bool = False) -> dict:
        start_sha = os.environ.get("S_ROUND4C_AQ_START_SHA256")
        require(bool(start_sha) and sha(AQ_STATE) == start_sha,
                "aq state changed since the start-state copy")
        self.gate(cargo)
        require(label in self.limits, f"missing expected time: {label}")
        expected = self.limits[label]
        require(type(expected) is int and expected > 0, "positive expected seconds required")
        cap = expected * 2
        if cargo:
            require("-j" in argv and argv[argv.index("-j") + 1] == "1", "cargo -j 1 required")
        require(re.fullmatch(r"[A-Za-z0-9_-]+", label) is not None, "unsafe monitor label")
        folder = OUT / "monitor" / label
        require(not folder.exists(), "monitor label already used")
        folder.mkdir(parents=True)
        start_utc = datetime.now(timezone.utc).isoformat()
        start = time.monotonic()
        samples = []
        temporary = folder / "tmp"
        temporary.mkdir()
        with (folder / "stdout.log").open("xb") as stdout, (folder / "stderr.log").open("xb") as stderr:
            process = subprocess.Popen(argv, cwd=ROOT, stdout=stdout, stderr=stderr,
                                       start_new_session=True,
                                       env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1",
                                                 TMPDIR=os.environ.get("S_ROUND4C_TMPDIR", str(temporary)), RAYON_NUM_THREADS="1",
                                                 OMP_NUM_THREADS="1", CARGO_INCREMENTAL="0",
                                                 CARGO_BUILD_JOBS="1", CARGO_TARGET_DIR=str(ROUND / "cargo-target")))
            status = "running"
            next_sample = start
            while process.poll() is None:
                if time.monotonic() - start > cap:
                    status = "time_cap"
                if self.phase_end is not None and time.monotonic() > self.phase_end:
                    status = "stage_time_cap"
                if (folder / "stdout.log").stat().st_size + (folder / "stderr.log").stat().st_size > 100_000_000:
                    status = "internal_log_cap"
                if time.monotonic() >= next_sample:
                    try:
                        quiet_host()
                        require(sha(AQ_STATE) == start_sha, "aq state changed")
                    except (OSError, ValueError):
                        status = "aq_resumed_or_state_changed"
                    free = self.free_bytes()
                    samples.append({"elapsed_seconds": time.monotonic() - start,
                                    "internal_free_bytes": free})
                    if free < 18 * GIB:
                        status = "internal_space_floor"
                    if cargo and self.target_bytes() > 8 * GIB:
                        status = "cargo_target_8GiB_limit"
                    next_sample = time.monotonic() + 10
                if status != "running":
                    try:
                        os.killpg(process.pid, signal.SIGTERM)
                    except ProcessLookupError:
                        pass
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        try:
                            os.killpg(process.pid, signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                    break
                time.sleep(0.5)
            code = process.wait()
        if status == "running":
            status = "completed" if code == 0 else "failed"
        receipt = write_new(folder / "result.json", {
            "label": label, "argv": argv, "start_utc": start_utc,
            "end_utc": datetime.now(timezone.utc).isoformat(),
            "elapsed_seconds": time.monotonic() - start, "expected_seconds": expected,
            "cap_seconds": cap, "status": status, "returncode": code,
            "phase": self.phase_name,
            "internal_free_bytes_after": self.free_bytes(),
            "internal_free_bytes_min_sampled": min((s["internal_free_bytes"] for s in samples),
                                                     default=None),
            "cargo_target_bytes_after": self.target_bytes() if cargo else None,
        })
        return {"status": status, "receipt": receipt, "returncode": code}


def j_command(plan: dict, request: Path, external: Path) -> list[str]:
    engine = checked_input(plan["engine"]["path"])
    require(engine.is_relative_to(ROUND) and sha(engine) == plan["engine"]["sha256"],
            "v2.3 engine pin changed")
    command = [str(engine), "--request", str(request), "--output", str(external / "result"),
               "--cache", str(external / "cache"), "--instance-store", str(external / "instance-store")]
    for name in ("circom", "node", "snarkjs", "z3"):
        pin = plan["tools"][name]
        tool = Path(pin["path"])
        require(tool.is_file() and sha(tool) == pin["sha256"], f"{name} tool pin changed")
        command += ["--" + name + "-bin", str(tool)]
    return command


def execute_j(plan: dict, row: dict, index: int, monitor: PostMonitor, label: str) -> dict:
    request, data = read_pin(row["request"])
    require(data.get("schema") in ("zkfdo-lifting-request-v1", "zkfdo-lifting-request-v2.3"),
            "unsupported J request")
    pins = set()
    for pin in row["inputs"]:
        path = checked_input(pin["path"])
        require(sha(path) == pin["sha256"], f"J input SHA changed: {path}")
        pins.add(path.resolve())
    root = Path(data["source_root"])
    for field in ("component_wrapper", "entrypoint", "base_input"):
        value = data.get(field)
        if value:
            require((root / value).resolve() in pins, f"missing {field} input pin")
    require((root / data["candidate"]["path"]).resolve() in pins, "missing candidate input pin")
    if data["schema"] == "zkfdo-lifting-request-v2.3":
        view = data["component_view"]
        require(sha(checked_input(request.parent / view["spec"])) == view["sha256"],
                "component view SHA changed")
    peak = max(row["recorded_peak_bytes"], plan["aq_observed_peak_bytes"],
               getattr(monitor, "observed_peak_bytes", 0))
    retained = max(row["retained_image_bytes"], getattr(monitor, "retained_image_bytes", 0))
    image_record = image_gate(peak, retained)
    internal_record = internal_gate(row["recorded_internal_peak_bytes"], row["retained_internal_bytes"])
    internal = OUT / "j-records" / f"{index:04d}"
    external = IMAGE / f"request-{index:04d}"
    require(not external.resolve().is_relative_to(root.resolve()), "J output must be outside its source root")
    require(not external.exists() and not internal.exists(), "request output already exists")
    internal.mkdir(parents=True)
    external.mkdir(parents=True)
    write_new(internal / "space.json", {**image_record, **internal_record})
    run = monitor.run(j_command(plan, request, external), label)
    result_path = external / "result/result.json"
    result_pin = None
    result = None
    if result_path.is_file():
        raw = result_path.read_bytes()
        require(len(raw) <= 20_000_000, "J result is not a small record")
        result = json.loads(raw)
        with (internal / "result.json").open("xb") as stream:
            stream.write(raw)
        result_pin = {"path": str(internal / "result.json"), "sha256": hashlib.sha256(raw).hexdigest()}
    binding = {"request": row["request"], "result": result_pin, "run": run["receipt"]}
    # Instance proof evidence must survive until joins and scoring finish. Use
    # exactly the aq cleanup module's retention predicate, never a new deletion rule.
    receipt = cleanup.cleanup_tree(external, IMAGE, OUT / "cleanup-records", binding, True)
    monitor.observed_peak_bytes = max(peak, receipt.get("du_bytes", 0))
    monitor.retained_image_bytes = retained + receipt.get("after", {}).get("du_bytes", 0)
    write_new(internal / "cleanup.json", {"before_path": receipt["before_path"],
              "before_sha256": receipt["before_sha256"], "after_path": receipt["after_path"],
              "after_sha256": receipt["after_sha256"], "freed_du_bytes": receipt["freed_du_bytes"]})
    require(run["status"] == "completed" and result is not None, "J failed; later requests stopped")
    require(result.get("preparation", {}).get("status") in ("ok", "not_tcct_deviation"),
            "J preparation failed; later requests stopped")
    return {"request": row["request"], "result": result_pin, "run": run["receipt"],
            "retained_evidence": receipt.get("retained_evidence", []),
            "retained_image_bytes": monitor.retained_image_bytes}


def replay(plan: dict, monitor: PostMonitor, output: Path, aq_state_pin: dict) -> dict:
    _, inventory = read_pin(plan["replay_inventory"])
    state_path, aq_state = read_pin(aq_state_pin)
    require(state_path.is_relative_to(OUT) and state_path.name in ("state-v3_2-at-start.json", "state-at-start.json"),
            "replay requires this invocation's aq state copy")
    rows = select_replay(inventory, aq_state)
    selected = []
    for index, row in enumerate(rows):
        baseline = read_pin(row["completed_result"])[1]
        result = execute_j(plan, row, index, monitor, f"replay-{index:04d}")
        new = read_pin(result["result"])[1]
        same = previous.verdict(baseline) == previous.verdict(new)
        selected.append({"queue_order": row["queue_order"], "revision": row["revision"],
                         "corpus": row["corpus"],
                         "aq_recorded_peak_bytes": (row["recorded_peak_bytes"]
                                                    if row["corpus"] == "aq" else None),
                         "completed_result": row["completed_result"],
                         "same_kind_and_reason": same, **result})
        write_new(output / f"comparison-{index:04d}.json", selected[-1])
        require(same, "v2.3 differs from v2.2; adoption and all later stages stop")
    return {"passed": True, "rows": selected, "sample_count": len(selected),
            "aq_start_state": aq_state_pin}


def compare_views(plan: dict, sample: dict, monitor: PostMonitor, output: Path) -> dict:
    if plan.get("view_plan"):
        _, view_plan = read_pin(plan["view_plan"])
    else:
        import s_round4c_view_replay_20261027 as converter
        _, inventory = read_pin(plan["replay_inventory"])
        originals = {(r["revision"], r["queue_order"]): r for r in inventory["rows"] if r["corpus"] == "banyan"}
        converted = []
        for i, old in enumerate(r for r in sample["rows"] if r.get("corpus") == "banyan"):
            row = originals[old["revision"], old["queue_order"]]
            change = converter.convert(row, output / f"converted-{i:04d}")
            converted.append({**row, **change})
        view_plan = {"schema": "s-round4c-view-replay-v1", "rows": converted}
        write_new(output / "view-plan.json", view_plan)
    require(view_plan["schema"] == "s-round4c-view-replay-v1", "view conversion plan schema")
    by_key = {(row["revision"], row["queue_order"]): row for row in view_plan["rows"]}
    banyan = [row for row in sample["rows"] if row.get("corpus") == "banyan"]
    expected = {(row["revision"], row["queue_order"]) for row in banyan}
    require(len(by_key) == len(view_plan["rows"]) and set(by_key) == expected,
            "view conversion must cover exactly the replay sample")
    comparisons = []
    for index, old in enumerate(banyan):
        row = by_key[(old["revision"], old["queue_order"])]
        monitor.limits[f"view-{index:04d}"] = math.ceil(row["recorded_wall_seconds"])
        _, request = read_pin(row["request"])
        require(request["schema"] == "zkfdo-lifting-request-v2.3" and
                "component_view" in request, "view request absent")
        require(row["original_request_sha256"] == old["request"]["sha256"],
                "view conversion not bound to unchanged original request")
        result = execute_j(plan, row, index + 500, monitor, f"view-{index:04d}")
        old_result = read_pin(old["completed_result"])[1]
        new_result = read_pin(result["result"])[1]
        same = previous.verdict(old_result) == previous.verdict(new_result)
        comparisons.append({"revision": old["revision"], "queue_order": old["queue_order"],
                            "same_kind_and_reason": same, **result})
        write_new(output / f"comparison-{index:04d}.json", comparisons[-1])
        require(same, "v2.3 view differs from v2.2; later stages stopped")
    return {"passed": True, "rows": comparisons}


def execute_s(plan: dict, monitor: PostMonitor, output: Path) -> dict:
    _, s_plan = read_pin(plan["S_plan"])
    require(s_plan["schema"] == "s-round4c-S-plan-v1" and s_plan.get("ready_for_execution") is True and
            len(s_plan["jobs"]) == 45,
            "complete 15-revision/3-seed S bundle required")
    for index, job in enumerate(s_plan["jobs"]):
        monitor.limits[f"post-{output.name}-preflight-{index}"] = job["expected_preflight_seconds"]
        monitor.limits[f"post-{output.name}-S-{index}"] = job["expected_campaign_seconds"]
    original_monitor, original_availability, original_file = (
        previous.monitor, previous.availability, previous.__file__)
    try:
        previous.monitor = monitor
        previous.availability = lambda peak, retained: internal_gate(peak, retained)
        # 4b mechanics launch their own child via __file__; use this runner so
        # the child checks the aq endpoint instead of the superseded time gate.
        previous.__file__ = __file__
        output.mkdir(parents=True, exist_ok=False)
        previous.fuzz(s_plan, output)
    finally:
        previous.monitor, previous.availability, previous.__file__ = (
            original_monitor, original_availability, original_file)
    summary = json.loads((output / "summary.json").read_text())
    for index, run in enumerate(summary["runs"]):
        receipt = OUT / "monitor" / f"post-{output.name}-preflight-{index}" / "result.json"
        run["preflight_monitor"] = {"path": str(receipt), "sha256": sha(receipt)}
    return {"summary": write_new(output / "summary-with-costs.json", summary)}


def historical_judgements(inventory: dict) -> tuple[dict[str, dict], set[str]]:
    require(inventory.get("complete") is True and isinstance(inventory.get("rows"), list),
            "historical candidate inventory incomplete")
    judged: dict[str, dict] = {}
    unjudged = set()
    for row in inventory["rows"]:
        candidate_sha = row["sha256"]
        require(isinstance(candidate_sha, str) and re.fullmatch(r"[0-9a-f]{64}", candidate_sha),
                "historical candidate SHA malformed")
        require(row.get("status") in ("judged", "unjudged"), "historical judgement status missing")
        if row["status"] == "judged":
            _, result = read_pin(row["completed_result"])
            require(result.get("candidate_sha256") == candidate_sha and
                    result.get("preparation", {}).get("status") == "ok" and
                    isinstance(result.get("classes"), list) and
                    isinstance(result.get("verdict_counts"), dict),
                    "historical candidate has no complete judgement")
            judged[candidate_sha] = row["completed_result"]
        else:
            unjudged.add(candidate_sha)
    return judged, unjudged


def judged_old_hashes(inventory: dict) -> set[str]:
    return set(historical_judgements(inventory)[0])


def new_j(plan: dict, monitor: PostMonitor, output: Path) -> dict:
    _, bundle = read_pin(plan["new_J_plan"])
    _, inventory = read_pin(bundle["old_candidate_inventory"])
    judged, unjudged = historical_judgements(inventory)
    historical_rows = {r["sha256"]: r for r in inventory["rows"] if r["status"] == "judged"}
    seen = set(judged)
    results = []
    for index, row in enumerate(bundle["requests"]):
        candidate = checked_input(row["candidate"]["path"])
        require(candidate.is_relative_to(ROUND) and sha(candidate) == row["candidate"]["sha256"],
                "new candidate SHA/path changed")
        _, ledger = read_pin(row["S_ledger"])
        require(row["candidate"]["sha256"] in
                {item["sha256"] for attempt in ledger["attempts"]
                 for item in attempt.get("candidates", [])}, "candidate absent from new S ledger")
        if row["candidate"]["sha256"] in seen:
            candidate_sha = row["candidate"]["sha256"]
            results.append({"candidate_sha256": candidate_sha, "status": "old_or_duplicate",
                            "skip_reason": ("historical_judged" if candidate_sha in judged
                                            else "current_batch_duplicate"),
                            "historical_result": judged.get(candidate_sha)})
            if candidate_sha in judged:
                results[-1]["historical_source"] = historical_rows[candidate_sha]
            continue
        seen.add(row["candidate"]["sha256"])
        label = f'{plan.get("new_j_label", "new-J")}-{index:04d}'
        monitor.limits[label] = math.ceil(row.get("expected_seconds", plan["new_j_expected_seconds_per_request"]))
        result = execute_j(plan, row, index + plan.get("new_j_offset", 1000), monitor, label)
        results.append({"candidate_sha256": row["candidate"]["sha256"], "status": "completed",
                        "historical_unjudged": row["candidate"]["sha256"] in unjudged, **result})
    return {"requests": results}


def execute_sequence(plan: dict, amendment_sha: str, output: Path, *,
                     aq_stopped_by_miiz: bool = False) -> None:
    import s_round4c_pipeline_20261027 as pipeline
    import s_round4c_sequence_20261027 as comparison
    global IMAGE, OUT
    require(os.getpriority(os.PRIO_PROCESS, 0) == 19, "nice 19 required")
    require(sha(AMENDMENT) == amendment_sha == plan["amendment_sha256"],
            "miiz-approved amendment SHA is required")
    require(sha(PREVIOUS_AMENDMENT) == PREVIOUS_AMENDMENT_SHA ==
            plan["previous_amendment_sha256"], "previous amendment SHA changed")
    require(protocol.REG_SHA == plan["preregistration_sha256"], "original preregistration changed")
    require(plan["baseline_engine_sha256"] ==
            "c78166319c0e12a62d89697ec0b248ef916e236961db9f890ec992f53c59a835",
            "baseline engine must be frozen v2.2")
    require(not output.exists(), "new invocation directory required")
    output.mkdir(parents=True)
    readiness = pipeline.preflight(plan)
    write_new(output / "preflight.json", readiness)
    require(readiness["ready"], "preflight refused: " + "; ".join(readiness["problems"]))
    OUT = output
    # This snapshot is the only aq state used to choose the five replay rows.
    state_pin, _ = capture_aq_state(output / "inputs/state-at-start.json",
                                  aq_stopped_by_miiz=aq_stopped_by_miiz)
    os.environ["S_ROUND4C_AQ_START_SHA256"] = state_pin["sha256"]
    if aq_stopped_by_miiz:
        os.environ["S_ROUND4C_AQ_STOPPED_BY_MIIZ"] = "1"
    start_pin = write_new(output / "execution-start.json", {
        "start_utc": datetime.now(timezone.utc).isoformat(), "aq_final_verified": True,
        "aq_process_absent": True, "aq_stopped_by_miiz": aq_stopped_by_miiz, "state": state_pin})
    IMAGE = IMAGE / output.name
    image_gate(plan["aq_observed_peak_bytes"], 0)
    require(IMAGE.resolve() == IMAGE and not IMAGE.exists(), "image execution directory exists or has a symlink")
    IMAGE.mkdir(parents=True)
    monitor = PostMonitor({})
    completed = []

    def stage(name, expected, action):
        monitor.begin_phase(name, expected)
        value = action()
        monitor.end_phase()
        ref = write_new(output / f"stage-{name}.json", value)
        completed.append({"stage": name, "result": ref})
        return value

    try:
        estimates = plan["stage_estimates_seconds"]
        stage("cargo24", estimates["cargo24"], lambda: pipeline.run_cargo_tests(plan, monitor, output / "cargo24"))
        rows = select_replay(read_pin(plan["replay_inventory"])[1], read_pin(state_pin)[1])
        for i, row in enumerate(rows):
            monitor.limits[f"replay-{i:04d}"] = math.ceil(row["recorded_wall_seconds"])
        sample = stage("replay", estimates["replay"], lambda: replay(plan, monitor, output / "replay", state_pin))
        stage("view", estimates["view"], lambda: compare_views(plan, sample, monitor, output / "view"))
        # Recheck approval at the two steps that produce new evaluation evidence.
        require(sha(AMENDMENT) == amendment_sha, "amendment changed before S")
        s = stage("S", estimates["S"], lambda: execute_s(plan, monitor, output / "S"))
        plan["new_J_plan"] = pipeline.build_new_j(plan, s["summary"], output / "new-J-inputs")
        count = len(read_pin(plan["new_J_plan"])[1]["requests"])
        require(sha(AMENDMENT) == amendment_sha, "amendment changed before new J")
        result = stage("new-J", max(1, count * plan["new_j_expected_seconds_per_request"]),
                       lambda: new_j(plan, monitor, output / "new-J"))
        scored = stage("score", estimates["score"], lambda: pipeline.score_new(
            plan, plan["new_J_plan"], result, monitor, output / "scoring"))
        costs = pipeline.measured_costs(plan, s["summary"], plan["new_J_plan"], result, start_pin, output)
        scored["costs"] = costs
        reg = protocol.registration()
        w_plan = comparison.make_w_plan(scored, reg)
        write_new(output / "required-W-plan.json", w_plan)
        if not w_plan["jobs"]:
            conclusion = comparison.finish_comparison({"S": scored}, reg)
        else:
            resources = read_pin(plan["W_resources"])[1]
            keys = {(j["revision"], j["seed"]) for j in w_plan["jobs"]}
            resources = {**resources, "jobs": [r for r in resources["jobs"] if (r["revision"], r["seed"]) in keys]}
            comparison.monitor = monitor
            w_output = protocol.OUT / (output.name + "-required-W")
            expected = w_plan["fuzz_budget_seconds"] + sum(r["expected_preflight_seconds"] +
                       r["expected_overhead_seconds"] for r in resources["jobs"])
            w_runs = stage("W", expected, lambda: comparison.execute_w(w_plan, resources, w_output))
            w_data = read_pin(w_runs)[1]
            w_summary = write_new(output / "W-summary.json", {"runs": [
                {"revision": r["revision"], "seed": r["seed"], "campaign": r["campaign"], "spec": r["spec"]}
                for r in w_data["jobs"]]})
            w_j = pipeline.build_new_j(plan, w_summary, output / "W-J-inputs", method="W")
            w_config = {**plan, "new_J_plan": w_j, "new_j_label": "W-confirm", "new_j_offset": 1000000}
            count = len(read_pin(w_j)[1]["requests"])
            w_result = stage("W-confirm", max(1, count * plan["new_j_expected_seconds_per_request"]),
                             lambda: new_j(w_config, monitor, output / "W-confirm"))
            w_score = stage("W-score", estimates["score"], lambda: pipeline.score_new(
                w_config, w_j, w_result, monitor, output / "W-scoring"))
            audit = read_pin(w_score["strict_input_audit"])[1]
            require(not audit.get("outside_strict"), "W candidate confirmation is not complete in the strict layer")
            audit.update(W_runs_sha256=w_runs["sha256"], all_candidate_confirmations_finished=True)
            w_score["strict_input_audit"] = write_new(output / "W-confirmation-audit.json", audit)
            conclusion = comparison.finish_comparison({"S": scored, "W": w_score, "W_runs": w_runs}, reg)
        write_new(output / "conclusion.json", conclusion)
        write_new(output / "sequence.json", {"status": "completed", "stages": completed,
                  "retained_image_bytes": monitor.retained_image_bytes, "optional_all_15_W_executed": False})
    except Exception as error:
        write_new(output / "sequence-failed.json", {"status": "stopped", "reason": str(error), "stages": completed})
        raise


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] in ("_preflight", "_campaign"):
        require(len(sys.argv) == 5, "S child arguments")
        quiet_host()
        require(sha(AQ_STATE) == os.environ.get("S_ROUND4C_AQ_START_SHA256"),
                "S child has no matching start-state copy")
        validate_aq_state(json.loads(AQ_STATE.read_text()),
                          aq_stopped_by_miiz=os.environ.get("S_ROUND4C_AQ_STOPPED_BY_MIIZ") == "1")
        previous.monitor = PostMonitor({})
        previous.deadline = lambda: None
        previous.campaign_child(*sys.argv[2:], preparation=sys.argv[1] == "_preflight")
        return
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", required=True)
    parser.add_argument("--plan-sha256", required=True)
    parser.add_argument("--amendment-sha256")
    parser.add_argument("--output", required=True)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--aq-stopped-by-miiz", action="store_true")
    args = parser.parse_args()
    _, plan = read_pin({"path": args.plan, "sha256": args.plan_sha256})
    if args.validate_only:
        require(not args.execute, "validation cannot execute")
        import s_round4c_pipeline_20261027 as pipeline
        print(json.dumps(write_new(args.output, pipeline.preflight(plan)), ensure_ascii=False))
        return
    require(args.execute and args.amendment_sha256, "explicit --execute and approved amendment SHA required")
    if args.aq_stopped_by_miiz:
        os.environ["S_ROUND4C_AQ_STOPPED_BY_MIIZ"] = "1"
    execute_sequence(plan, args.amendment_sha256, checked_output(args.output),
                     aq_stopped_by_miiz=args.aq_stopped_by_miiz)


if __name__ == "__main__":
    main()
