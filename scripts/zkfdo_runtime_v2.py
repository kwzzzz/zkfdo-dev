#!/usr/bin/env python3
"""Versioned, sequential process supervisor; never edits historical runners.

The work deadline stops work. A separate, measured cleanup interval reaps owned
process groups and persists receipts. SIGKILL and host/power failure cannot run
Python finally blocks; checkpoints survive those events but are not final receipts.
"""
from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from typing import Callable

import zkfdo_platform as platform_layer

ObservationError = platform_layer.ObservationError


from zkfdo_observer_v1 import DiskBudget, ObservationCosts
from zkfdo_runtime_v1 import BudgetExceeded


def atomic_json(path: Path, value) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(value, stream, ensure_ascii=False, sort_keys=True, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        try:
            os.unlink(name)
        except FileNotFoundError:
            pass


process_snapshot = platform_layer.process_snapshot


def identity(row):
    return row["pid"], row["start_id"]


def run_command(argv: list[str], output: Path, seconds: float, *,
                cleanup_grace_seconds: float = 1.0,
                cleanup_cap_seconds: float = 5.0,
                poll_seconds: float = 0.05,
                env: dict[str, str] | None = None,
                cwd: Path | None = None,
                cancel_check: Callable[[], bool] = lambda: False,
                tick: Callable[[dict], None] | None = None,
                disk_budgets: tuple[DiskBudget, ...] = (),
                environment_info: dict | None = None,
                isolation_options: dict | None = None,
                include_imds: bool = False,
                snapshot: Callable[[], dict] | None = None) -> dict:
    if threading.current_thread() is not threading.main_thread():
        raise ValueError("supervisor must run on the main thread")
    if not argv or any(not isinstance(x, str) or not x for x in argv):
        raise ValueError("argv must contain nonempty strings")
    for name, value in [("seconds", seconds), ("cleanup_grace_seconds", cleanup_grace_seconds),
                        ("cleanup_cap_seconds", cleanup_cap_seconds), ("poll_seconds", poll_seconds)]:
        if isinstance(value, bool) or not math.isfinite(value) or value <= 0:
            raise ValueError(f"{name} must be finite and positive")
    if cleanup_cap_seconds <= cleanup_grace_seconds:
        raise ValueError("cleanup cap must exceed TERM grace")
    output = Path(output).absolute()
    if any(p.is_symlink() for p in (output, *output.parents)):
        raise ValueError("symlink output ancestry is forbidden")
    output.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    deadline = started + seconds
    receipt = {"schema": "zkfdo-process-receipt-v2", "argv": argv,
               "cwd": str(cwd or Path.cwd()), "status": "starting", "returncode": None,
               "work_budget_seconds": seconds, "cleanup_grace_seconds": cleanup_grace_seconds,
               "cleanup_cap_seconds": cleanup_cap_seconds, "cleanup_complete": False,
               "started_utc_ns": time.time_ns(), "received_signals": [], "events": [],
               "observation_errors": [], "signals_sent": [], "peak_process_tree_rss_bytes": None,
               "rss_scope": "sampled sum of owned command descendants, excluding supervisor; includes cleanup",
               "peak_process_count": 0, "cpu_seconds": None, "remaining_processes": [],
               "measurement_valid": True, "invalid_reasons": [],
               "limitations": ["SIGKILL/host loss leaves the last checkpoint, not a final receipt.",
                   "A sampled process tree cannot prove ownership of an unobserved detached orphan.",
                   "RSS is a sampled sum; wait4 CPU excludes descendants not reaped by the child."]}
    observation = ObservationCosts()
    previous = {}
    proc = None
    usage = None
    owned = {}
    baseline = set()
    snap = snapshot or process_snapshot
    gate_read = gate_write = None
    finalized = False
    clock_before = None
    isolation = None

    def persist():
        receipt["observation"] = observation.snapshot()
        receipt["observation_scope"] = "supervisor disk checks, process sampling/reaping, memory/isolation sampling and clock checks; CPU separates parent process_time and waited observer helpers measured only around process/memory sampling (never reap); excludes setup, serialization and final receipt write; raw elapsed and command wait4 CPU remain unchanged"
        receipt["observed_wall_seconds"] = time.monotonic() - started
        atomic_json(output / "ledger.json", {"schema": "zkfdo-process-ledger-v2",
                    "status": receipt["status"], "argv": argv, "events": receipt["events"],
                    "work_budget_seconds": seconds, "complete": finalized})
        atomic_json(output / "receipt.json", receipt)

    def persist_without_blocking_cleanup():
        try:
            persist()
            return True
        except (OSError, TypeError, ValueError) as error:
            receipt.setdefault("persistence_errors", []).append(f"{type(error).__name__}: {error}")
            return False

    @observation.timed("disk_checks")
    def check_disk(*, force=False):
        # Evaluate all budgets even when one is exceeded, preserving both peaks.
        receipt["disk_budgets"] = [budget.sample(force=force) for budget in disk_budgets]
        reasons = [row["stop_reason"] for row in receipt["disk_budgets"] if row["stop_reason"]]
        if reasons:
            raise BudgetExceeded(", ".join(reasons))

    @observation.timed("clock")
    def check_clock():
        after = platform_layer.clock_snapshot()
        receipt["clock_after"] = after
        delta = platform_layer.clock_delta(clock_before, after)
        receipt["clock_delta"] = delta
        reasons = [key for key in ("suspend_evidence", "clock_adjustment_evidence",
                   "unclassified_clock_discrepancy", "capture_ambiguous") if delta.get(key)]
        for reason in reasons:
            if reason not in receipt["invalid_reasons"]:
                receipt["invalid_reasons"].append(reason)
        if reasons:
            receipt["measurement_valid"] = False
        return reasons

    def event(name, **values):
        receipt["events"].append({"event": name, "offset_seconds": time.monotonic() - started, **values})

    def handler(signum, _frame):
        receipt["received_signals"].append(signum)

    @observation.timed("process_snapshot", helper_children=True)
    def observe():
        rows = snap()
        if proc is not None and proc.returncode is None:
            row = rows.get(proc.pid)
            if row and row["ppid"] == os.getpid() and row["pgid"] == proc.pid:
                owned.setdefault(identity(row), row)
        current = {pid for pid, row in rows.items() if identity(row) in owned}
        changed = True
        while changed:
            changed = False
            groups = {rows[pid]["pgid"] for pid in current}
            for pid, row in rows.items():
                key = identity(row)
                if pid == os.getpid() or key in baseline or key in owned:
                    continue
                leader = rows.get(row["pgid"])
                group_owned = row["pgid"] in groups and (leader is None or identity(leader) in owned)
                if row["ppid"] in current or group_owned:
                    owned[key] = row
                    current.add(pid)
                    changed = True
        live = [row for row in rows.values() if identity(row) in owned and not row["state"].startswith("Z")]
        receipt["peak_process_count"] = max(receipt["peak_process_count"], len(live))
        rss = sum(row["rss_bytes"] for row in live)
        receipt["peak_process_tree_rss_bytes"] = max(receipt["peak_process_tree_rss_bytes"] or 0, rss)
        return live

    @observation.timed("memory_snapshot", helper_children=True)
    def sample_memory():
        return platform_layer.memory_snapshot()

    @observation.timed("isolation_sample")
    def sample_isolation():
        return isolation.sample()

    @observation.timed("reap")
    def reap():
        nonlocal usage
        if proc is None or proc.returncode is not None:
            return
        try:
            pid, status, measured = os.wait4(proc.pid, os.WNOHANG)
        except InterruptedError:
            return
        if pid == proc.pid:
            usage = measured
            proc.returncode = os.waitstatus_to_exitcode(status)
            receipt["returncode"] = proc.returncode
            event("direct_child_reaped", pid=pid, returncode=proc.returncode)

    def signal_owned(live, signum):
        groups = {row["pgid"] for row in live}
        for group in groups:
            if group <= 1 or group == os.getpgrp():
                raise ObservationError("refusing to signal supervisor or system group")
            # Every broadcast is anchored in a freshly observed owned process.
            try:
                os.killpg(group, signum)
                receipt["signals_sent"].append({"pgid": group, "signal": signum})
            except ProcessLookupError:
                pass

    try:
        for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
            previous[sig] = signal.signal(sig, handler)
        persist()
        check_disk(force=True)  # No new process/compile starts after a task/request cap trips.
        clock_before = platform_layer.clock_snapshot()
        receipt["clock_before"] = clock_before
        receipt["memory_before"] = sample_memory()
        receipt["environment"] = environment_info if environment_info is not None else platform_layer.host_environment(output, include_imds=include_imds)
        isolation = platform_layer.prepare_isolation(**(isolation_options or {}))
        receipt["isolation"] = {"configuration": isolation.configuration}
        with observation.measure("process_snapshot", helper_children=True):
            baseline = {identity(row) for row in snap().values()}
        check_disk(force=True)
        if receipt["received_signals"] or cancel_check():
            receipt["status"] = "interrupted_before_spawn"
        elif time.monotonic() >= deadline:
            receipt["status"] = "timeout_before_spawn"
        else:
            gate_read, gate_write = os.pipe()
            child_env = {**os.environ, **(env or {})}
            shim = [sys.executable, "-B", str(Path(__file__).resolve()), "_exec", str(gate_read), *argv]
            with (output / "stdout.log").open("xb") as stdout, (output / "stderr.log").open("xb") as stderr:
                proc = subprocess.Popen(shim, stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr,
                                        cwd=cwd, env=child_env, start_new_session=True, pass_fds=(gate_read,))
                os.close(gate_read)
                gate_read = None
                observe()  # Bind identity before permitting the command to fork.
                receipt["isolation"]["attached"] = isolation.attach(proc.pid)
                receipt["pid"] = proc.pid
                event("process_started", pid=proc.pid, pgid=proc.pid)
                receipt["status"] = "running"
                persist()
                check_disk(force=True)
                if receipt["received_signals"] or cancel_check():
                    receipt["status"] = "interrupted_before_exec"
                elif time.monotonic() >= deadline:
                    receipt["status"] = "timeout_before_exec"
                else:
                    os.write(gate_write, b"1")
                os.close(gate_write)
                gate_write = None
                next_checkpoint = time.monotonic() + 0.5
                next_memory_sample = time.monotonic() + 1.0
                while proc.returncode is None:
                    if receipt["status"] != "running":
                        break
                    observe()
                    receipt["isolation"]["latest"] = sample_isolation()
                    reap()
                    if proc.returncode is not None:
                        receipt["status"] = "completed" if proc.returncode == 0 else "command_failed"
                        break
                    if tick is not None:
                        tick(receipt)
                    check_disk()
                    reasons = check_clock()
                    if reasons:
                        receipt["status"] = "invalid_sleep" if "suspend_evidence" in reasons else "invalid_clock"
                        break
                    if time.monotonic() >= next_memory_sample:
                        receipt["memory_latest"] = sample_memory()
                        next_memory_sample = time.monotonic() + 1.0
                    if receipt["received_signals"]:
                        receipt["status"] = "interrupted"
                        break
                    if cancel_check():
                        receipt["status"] = "cancelled"
                        break
                    if time.monotonic() >= deadline:
                        receipt["status"] = "timeout"
                        break
                    if time.monotonic() >= next_checkpoint:
                        persist()
                        next_checkpoint = time.monotonic() + 0.5
                    time.sleep(min(poll_seconds, max(0, deadline - time.monotonic())))
    except BudgetExceeded as error:
        receipt["status"] = "disk_limit"
        receipt["error"] = str(error)
    except BaseException as error:
        receipt["status"] = "resource_monitor_failure" if isinstance(error, ObservationError) else "supervisor_error"
        receipt["error"] = f"{type(error).__name__}: {error}"
        receipt["measurement_valid"] = False
        receipt["invalid_reasons"].append(receipt["status"])
    finally:
        event("work_stopped", status=receipt["status"])
        receipt["work_stop_seconds"] = time.monotonic() - started
        persist_without_blocking_cleanup()
        cleanup_start = time.monotonic()
        sent = set()
        while proc is not None and time.monotonic() - cleanup_start < cleanup_cap_seconds:
            try:
                live = observe()
                reap()
                live = [row for row in live if row["pid"] != proc.pid or proc.returncode is None]
                try:
                    isolated_live = sample_isolation().get("remaining_pids", []) if isolation is not None else []
                except (OSError, ObservationError) as error:
                    receipt["observation_errors"].append(f"isolation cleanup sample: {error}")
                    isolated_live = ["unknown"]
                if not live and not isolated_live and proc.returncode is not None:
                    break
                signum = signal.SIGTERM if time.monotonic() - cleanup_start < cleanup_grace_seconds else signal.SIGKILL
                if signum == signal.SIGKILL and isolation is not None:
                    try:
                        receipt["isolation"]["kill"] = isolation.kill()
                    except (OSError, ObservationError) as error:
                        receipt["observation_errors"].append(f"isolation cleanup kill: {error}")
                groups = {row["pgid"] for row in live}
                if any((group, signum) not in sent for group in groups):
                    signal_owned(live, signum)
                    sent.update((group, signum) for group in groups)
            except Exception as error:
                receipt["observation_errors"].append(str(error))
                # An unreaped direct-child PID cannot be reused by another group.
                if proc.returncode is None:
                    try:
                        os.killpg(proc.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    reap()
            time.sleep(poll_seconds)
        try:
            remaining = observe() if proc is not None else []
            reap()
        except Exception as error:
            remaining = None
            receipt["observation_errors"].append(str(error))
        receipt["remaining_processes"] = remaining
        receipt["cleanup_complete"] = remaining == [] and (proc is None or proc.returncode is not None)
        if isolation is not None:
            try:
                result = isolation.finalize()
                while not result.get("cleanup_complete", False) and time.monotonic() - cleanup_start < cleanup_cap_seconds:
                    receipt["isolation"]["kill"] = isolation.kill()
                    time.sleep(poll_seconds)
                    result = isolation.finalize()
                receipt["isolation"]["final"] = result
                receipt["cleanup_complete"] = receipt["cleanup_complete"] and result.get("cleanup_complete", False)
                events = result.get("sample", {}).get("memory_events", {})
                if any(events.get(key, 0) > 0 for key in ("oom", "oom_kill", "max")):
                    receipt["status_before_memory_limit"] = receipt["status"]
                    receipt["status"] = "memory_limit"
            except (OSError, ObservationError) as error:
                receipt["observation_errors"].append(f"isolation finalize: {error}")
                receipt["cleanup_complete"] = False
        if not receipt["cleanup_complete"]:
            receipt["status_before_cleanup_failure"] = receipt["status"]
            receipt["status"] = "cleanup_incomplete"
            receipt["measurement_valid"] = False
            receipt["invalid_reasons"].append("cleanup_incomplete")
        receipt["cleanup_seconds"] = time.monotonic() - cleanup_start
        receipt["finished_utc_ns"] = time.time_ns()
        try:
            if clock_before is not None:
                reasons = check_clock()
                if reasons and receipt["status"] not in {"invalid_sleep", "invalid_clock"}:
                    receipt["status_before_clock_invalid"] = receipt["status"]
                    receipt["status"] = "invalid_sleep" if "suspend_evidence" in reasons else "invalid_clock"
            receipt["memory_after"] = sample_memory()
        except (OSError, ObservationError) as error:
            receipt["observation_errors"].append(f"final platform sample: {error}")
            receipt["measurement_valid"] = False
            receipt["invalid_reasons"].append("final_platform_sample_failed")
        try:
            with observation.measure("disk_checks"):
                receipt["disk_budgets"] = [budget.sample() for budget in disk_budgets]
            if any(row["stop_reason"] for row in receipt["disk_budgets"]):
                if receipt["status"] in {"completed", "command_failed", "timeout"}:
                    receipt["status_before_disk_limit"] = receipt["status"]
                    receipt["status"] = "disk_limit"
        except (OSError, ObservationError) as error:
            receipt["observation_errors"].append(f"final disk sample: {error}")
            receipt["measurement_valid"] = False
            receipt["invalid_reasons"].append("final_disk_sample_failed")
        if usage is not None:
            receipt["cpu_seconds"] = usage.ru_utime + usage.ru_stime
            receipt["wait4_cpu_seconds"] = receipt["cpu_seconds"]
            receipt["cpu_scope"] = "wait4 direct child and descendants it reaped; detached orphan CPU may be absent"
            receipt["ru_maxrss_raw"] = usage.ru_maxrss
            receipt["ru_maxrss_bytes"] = platform_layer.normalize_ru_maxrss(usage.ru_maxrss)
        cgroup_sample = receipt.get("isolation", {}).get("final", {}).get("sample", {})
        if cgroup_sample.get("enabled") and cgroup_sample.get("cpu_seconds") is not None:
            receipt["cpu_seconds"] = cgroup_sample["cpu_seconds"]
            receipt["cpu_scope"] = "fresh owned cgroup cpu.stat usage_usec from attachment, including cleanup and detached descendants; pre-attachment shim CPU excluded"
        for fd in (gate_read, gate_write):
            if fd is not None:
                os.close(fd)
        finalized = True
        event("finalized", cleanup_complete=receipt["cleanup_complete"])
        if not persist_without_blocking_cleanup():
            receipt["status_before_persistence_failure"] = receipt["status"]
            receipt["status"] = "persistence_failed"
            receipt["measurement_valid"] = False
            receipt["invalid_reasons"].append("persistence_failed")
            persist_without_blocking_cleanup()
        for sig, old in previous.items():
            signal.signal(sig, old)
    return receipt


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] == "_exec":
        fd = int(argv[1])
        permit = os.read(fd, 1)
        os.close(fd)
        if permit != b"1":
            return 125
        os.execvpe(argv[2], argv[2:], os.environ)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seconds", type=float, required=True)
    parser.add_argument("--cleanup-grace-seconds", type=float, default=1.0)
    parser.add_argument("--max-disk-bytes", type=int, required=True)
    parser.add_argument("--min-free-bytes", type=int, default=25 * 2**30)
    parser.add_argument("--cpu-affinity")
    parser.add_argument("--memory-max-bytes", type=int)
    parser.add_argument("--cgroup-root", type=Path)
    parser.add_argument("--include-imds", action="store_true")
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    disk = DiskBudget(args.output, args.max_disk_bytes, min_free_bytes=args.min_free_bytes)
    result = run_command(command, args.output, args.seconds, cleanup_grace_seconds=args.cleanup_grace_seconds,
                         disk_budgets=(disk,), include_imds=args.include_imds,
                         isolation_options={"cpus": args.cpu_affinity, "memory_max_bytes": args.memory_max_bytes,
                                            "cgroup_root": args.cgroup_root})
    print(json.dumps({k: result.get(k) for k in ("status", "cleanup_complete", "returncode")}))
    return 0 if result["status"] == "completed" and result["cleanup_complete"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
