#!/usr/bin/env python3
"""Bound one local N7 worker, including observed descendants in other sessions.

No process-group broadcast is used. A process is signalled only after a fresh
ps observation matches its recorded PID and start time. Polling cannot discover
a child that forks, changes session and becomes orphaned between observations;
this limitation, and any incomplete cleanup, are recorded rather than hidden.
"""

from __future__ import annotations

import json
import math
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_ROOT = ROOT / "runs/n7-allcost-2026-10-28"
POLL_SECONDS = 0.2
TERM_GRACE_SECONDS = 1.0
CLEANUP_CAP_SECONDS = 4.0


class ObservationError(RuntimeError):
    """Process ownership cannot currently be checked safely."""


def _snapshot() -> dict[int, dict[str, Any]]:
    try:
        result = subprocess.run(
            ["/bin/ps", "-axo", "pid=,ppid=,pgid=,rss=,lstart="],
            capture_output=True, text=True, timeout=1.0,
            env={**os.environ, "LC_ALL": "C"}, check=False,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise ObservationError(f"ps failed: {error}") from error
    if result.returncode != 0:
        raise ObservationError(f"ps exit {result.returncode}: {result.stderr.strip()}")
    rows: dict[int, dict[str, Any]] = {}
    for line in result.stdout.splitlines():
        fields = line.split(maxsplit=4)
        if len(fields) != 5:
            raise ObservationError(f"malformed ps row: {line!r}")
        try:
            pid, ppid, pgid, rss = map(int, fields[:4])
        except ValueError as error:
            raise ObservationError("non-integer ps identity") from error
        started = " ".join(fields[4].split())
        if pid <= 0 or ppid < 0 or pgid < 0 or rss < 0 or len(started.split()) != 5:
            raise ObservationError(f"invalid ps identity: {line!r}")
        if pid in rows:
            raise ObservationError(f"duplicate PID in ps: {pid}")
        rows[pid] = {"pid": pid, "ppid": ppid, "pgid": pgid,
                     "rss_bytes": rss * 1024, "lstart": started}
    if os.getpid() not in rows:
        raise ObservationError("ps did not contain the supervisor")
    return rows


def _identity(row: dict[str, Any]) -> tuple[int, str]:
    return row["pid"], row["lstart"]


def _new_output(output: Path) -> Path:
    raw = Path(output)
    if not raw.is_absolute():
        raw = ROOT / raw
    allowed = OUTPUT_ROOT.resolve()
    resolved = raw.resolve()
    if resolved == allowed or not resolved.is_relative_to(allowed):
        raise ValueError(f"output must be a new directory below {OUTPUT_ROOT}")
    for path in (OUTPUT_ROOT, *raw.parents, raw):
        if path.is_symlink():
            raise ValueError(f"symlink output path is forbidden: {path}")
    if raw.exists():
        raise FileExistsError(f"refuse to overwrite supervisor output: {raw}")
    raw.mkdir(parents=True, exist_ok=False)
    if raw.resolve() != resolved or not raw.resolve().is_relative_to(allowed):
        raise ValueError("output ancestry changed while creating it")
    return raw


def _free_bytes(output: Path) -> int:
    stat = os.statvfs(output)
    return stat.f_bavail * stat.f_frsize


def run_bounded(
    argv: list[str], output: Path, timeout_seconds: float, *,
    env: dict[str, str] | None = None,
    memory_cap_bytes: int = 10 * 2**30,
    min_free_bytes: int = 18 * 2**30,
) -> dict[str, Any]:
    """Run a single worker; return and persist its inclusive supervision receipt.

    Must run on the main thread so SIGTERM/SIGINT/SIGHUP can request cleanup.
    ``env`` overlays the current environment; the two N7 monotonic values always
    come from this function. A fresh output directory is mandatory. The receipt
    reports unresolved ownership explicitly; ``cleanup_complete`` must be checked.
    """
    if threading.current_thread() is not threading.main_thread():
        raise ValueError("run_bounded must run on the main thread")
    if not isinstance(argv, list) or not argv or any(not isinstance(x, str) or not x for x in argv):
        raise ValueError("argv must be a nonempty list of nonempty strings")
    if isinstance(timeout_seconds, bool) or not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be finite and positive")
    if isinstance(memory_cap_bytes, bool) or not isinstance(memory_cap_bytes, int) or memory_cap_bytes <= 0:
        raise ValueError("memory_cap_bytes must be a positive integer")
    if isinstance(min_free_bytes, bool) or not isinstance(min_free_bytes, int) or min_free_bytes < 0:
        raise ValueError("min_free_bytes must be a nonnegative integer")
    if env is not None and any(not isinstance(k, str) or not isinstance(v, str) for k, v in env.items()):
        raise ValueError("env keys and values must be strings")

    t0 = time.monotonic()
    deadline = t0 + timeout_seconds
    folder = _new_output(output)
    receipt: dict[str, Any] = {
        "schema": "n7-allcost-supervisor-v1", "argv": argv,
        "output": str(folder), "t0_monotonic": t0,
        "deadline_monotonic": deadline, "timeout_seconds": timeout_seconds,
        "memory_cap_bytes": memory_cap_bytes, "min_free_bytes": min_free_bytes,
        "poll_seconds": POLL_SECONDS, "status": "not_started", "returncode": None,
        "peak_process_tree_rss_bytes": 0, "peak_owned_process_count": 0,
        "samples": 0, "stop_trigger_offset_seconds": None,
        "deadline_trigger_offset_seconds": None, "received_signals": [],
        "observation_errors": [], "signals_sent": [], "ownership_conflicts": [],
        "stdout_path": str(folder / "stdout.log"), "stderr_path": str(folder / "stderr.log"),
        "tracking_limitations": [
            "Unobserved fork+setsid+orphan transitions between ps samples cannot be attributed.",
            "lstart has ps display precision; PID and displayed start time are checked before every signal.",
            "SIGKILL or host termination cannot execute supervisor cleanup.",
            "Peak RSS is the sampled sum, not a continuous or physical-footprint peak.",
        ],
    }
    owned: dict[tuple[int, str], dict[str, Any]] = {}
    baseline: set[tuple[int, str]] = set()
    proc: subprocess.Popen[bytes] | None = None
    pipe_read: int | None = None
    pipe_write: int | None = None
    interrupted: list[int] = []
    previous_handlers: dict[int, Any] = {}

    def handler(signum: int, _frame: Any) -> None:
        interrupted.append(signum)

    def stop(status: str) -> None:
        if receipt["stop_trigger_offset_seconds"] is None:
            receipt["stop_trigger_offset_seconds"] = time.monotonic() - t0
            receipt["status"] = status
            if status == "timeout":
                receipt["deadline_trigger_offset_seconds"] = receipt["stop_trigger_offset_seconds"]

    def observe(rows: dict[int, dict[str, Any]]) -> list[dict[str, Any]]:
        # An unreaped direct-child PID cannot be recycled. This also lets
        # cleanup bind the blocked shim after an initial ps failure.
        if proc is not None and proc.returncode is None:
            root = rows.get(proc.pid)
            if (root is not None and root["ppid"] == os.getpid() and root["pgid"] == proc.pid
                    and _identity(root) not in baseline and _identity(root) not in owned):
                owned[_identity(root)] = {**root, "first_seen_offset_seconds": time.monotonic() - t0,
                                          "ownership": "spawned_direct_child"}
        current = {pid for pid, row in rows.items() if _identity(row) in owned}
        changed = True
        while changed:
            changed = False
            for row in rows.values():
                ident = _identity(row)
                if ident in owned or ident in baseline or row["pid"] == os.getpid():
                    continue
                parent_owned = row["ppid"] in current
                # Do not retain an empty historical PGID: it can later be
                # recycled by an unrelated task. At least one currently
                # observed owned member must still anchor the group.
                active_groups = {rows[pid]["pgid"] for pid in current}
                in_owned_group = row["pgid"] in active_groups
                if not (parent_owned or in_owned_group):
                    continue
                # A previously owned group ID cannot silently become a new group.
                leader = rows.get(row["pgid"])
                if in_owned_group and leader is not None and _identity(leader) not in owned:
                    in_owned_group = False
                if not (parent_owned or in_owned_group):
                    continue
                owned[ident] = {**row, "first_seen_offset_seconds": time.monotonic() - t0,
                                "ownership": "parent" if parent_owned else "observed_owned_group"}
                current.add(row["pid"])
                changed = True
        live = [row for row in rows.values() if _identity(row) in owned]
        receipt["samples"] += 1
        receipt["peak_process_tree_rss_bytes"] = max(
            receipt["peak_process_tree_rss_bytes"], sum(row["rss_bytes"] for row in live))
        receipt["peak_owned_process_count"] = max(receipt["peak_owned_process_count"], len(live))
        return live

    def checked_signal(ident: tuple[int, str], signum: int) -> bool:
        rows = _snapshot()
        observe(rows)
        row = rows.get(ident[0])
        if row is None:
            return False
        if _identity(row) != ident:
            receipt["ownership_conflicts"].append({"pid": ident[0], "expected_lstart": ident[1],
                                                   "observed_lstart": row["lstart"]})
            return False
        if ident not in owned or ident in baseline or row["pid"] == os.getpid():
            raise ObservationError("refusing signal without owned process identity")
        try:
            os.kill(row["pid"], signum)
        except ProcessLookupError:
            return False
        except PermissionError as error:
            receipt["observation_errors"].append(f"signal denied for owned PID {row['pid']}: {error}")
            return False
        receipt["signals_sent"].append({"pid": row["pid"], "lstart": row["lstart"],
                                         "signal": signum, "offset_seconds": time.monotonic() - t0})
        return True

    def cleanup() -> None:
        start = time.monotonic()
        sent_term: set[tuple[int, str]] = set()
        sent_kill: set[tuple[int, str]] = set()
        while time.monotonic() - start < CLEANUP_CAP_SECONDS:
            try:
                live = observe(_snapshot())
                if proc is not None:
                    proc.poll()  # Only the directly spawned child is waitable here.
                    if proc.returncode is not None:
                        live = [row for row in live if row["pid"] != proc.pid]
                if not live:
                    if proc is None or proc.returncode is not None:
                        break
                    time.sleep(POLL_SECONDS)
                    continue
                signum = signal.SIGTERM if time.monotonic() - start < TERM_GRACE_SECONDS else signal.SIGKILL
                sent = sent_term if signum == signal.SIGTERM else sent_kill
                # Direct child first limits further forks; identities of its known
                # children remain owned after reparenting, including other sessions.
                live.sort(key=lambda row: (row["pid"] != (proc.pid if proc else -1), row["pid"]))
                for row in live:
                    ident = _identity(row)
                    if ident not in sent and checked_signal(ident, signum):
                        sent.add(ident)
            except ObservationError as error:
                receipt["observation_errors"].append(str(error))
                stop("ps_failed")
            time.sleep(POLL_SECONDS)

    try:
        for signum in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
            previous_handlers[signum] = signal.getsignal(signum)
            signal.signal(signum, handler)
        with (folder / "stdout.log").open("xb") as stdout, (folder / "stderr.log").open("xb") as stderr:
            receipt["free_bytes_start"] = _free_bytes(folder)
            before = _snapshot()
            baseline = {_identity(row) for row in before.values()}
            if receipt["free_bytes_start"] < min_free_bytes:
                stop("disk_limit")
            elif interrupted:
                stop("interrupted")
            elif time.monotonic() >= deadline:
                stop("timeout")
            else:
                pipe_read, pipe_write = os.pipe()
                child_env = {**os.environ, **(env or {}),
                             "N7_ARM_T0_MONOTONIC": str(t0),
                             "N7_ARM_DEADLINE_MONOTONIC": str(deadline)}
                current_nice = os.getpriority(os.PRIO_PROCESS, 0)
                if current_nice > 19:
                    raise ValueError("parent nice exceeds 19; cannot safely raise its priority")
                command = ["/usr/bin/nice", "-n", str(19 - current_nice), sys.executable, str(Path(__file__).resolve()),
                           "--handshake-child", str(pipe_read), *argv]
                proc = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr,
                                        start_new_session=True, env=child_env, pass_fds=(pipe_read,))
                receipt["pid"] = proc.pid
                os.close(pipe_read)
                pipe_read = None
                rows = _snapshot()
                root = rows.get(proc.pid)
                if root is None or _identity(root) in baseline or root["ppid"] != os.getpid() or root["pgid"] != proc.pid:
                    raise ObservationError("could not bind the blocked direct child identity")
                owned[_identity(root)] = {**root, "first_seen_offset_seconds": time.monotonic() - t0,
                                          "ownership": "spawned_direct_child"}
                observe(rows)
                if interrupted:
                    stop("interrupted")
                elif time.monotonic() >= deadline:
                    stop("timeout")
                elif receipt["peak_process_tree_rss_bytes"] > memory_cap_bytes:
                    stop("memory_limit")
                else:
                    os.write(pipe_write, b"G")
                    receipt["worker_released_offset_seconds"] = time.monotonic() - t0
                    receipt["status"] = "running"
                os.close(pipe_write)
                pipe_write = None
                while receipt["status"] == "running":
                    live = observe(_snapshot())
                    code = proc.poll()
                    free = _free_bytes(folder)
                    receipt["minimum_free_bytes_observed"] = min(
                        receipt.get("minimum_free_bytes_observed", receipt["free_bytes_start"]), free)
                    if interrupted:
                        stop("interrupted")
                    elif time.monotonic() >= deadline:
                        stop("timeout")
                    elif free < min_free_bytes:
                        stop("disk_limit")
                    elif sum(row["rss_bytes"] for row in live) > memory_cap_bytes:
                        stop("memory_limit")
                    elif code is not None:
                        if any(row["pid"] != proc.pid for row in live):
                            stop("child_exited_with_descendants")
                        else:
                            receipt["status"] = "completed" if code == 0 else "nonzero_exit"
                            break
                    else:
                        time.sleep(min(POLL_SECONDS, max(0.0, deadline - time.monotonic())))
    except ObservationError as error:
        receipt["observation_errors"].append(str(error))
        stop("ps_failed")
    except BaseException as error:
        receipt["supervisor_error"] = f"{type(error).__name__}: {error}"
        stop("supervisor_error")
    finally:
        for fd in (pipe_write, pipe_read):
            if fd is not None:
                os.close(fd)
        if proc is not None:
            cleanup()
        try:
            remaining = observe(_snapshot()) if proc is not None else []
            if proc is not None:
                proc.poll()
                receipt["returncode"] = proc.returncode
                if proc.returncode is not None:
                    remaining = [row for row in remaining if row["pid"] != proc.pid]
            receipt["remaining_owned_pids"] = [row["pid"] for row in remaining]
            receipt["remaining_owned_identities"] = remaining
            receipt["cleanup_complete"] = not remaining and (proc is None or proc.returncode is not None)
        except ObservationError as error:
            receipt["observation_errors"].append(str(error))
            stop("ps_failed")
            receipt["remaining_owned_pids"] = sorted({ident[0] for ident in owned})
            receipt["remaining_owned_identities"] = list(owned.values())
            receipt["cleanup_complete"] = False
            receipt["remaining_identity_status"] = "unverified_after_ps_failure"
        receipt["received_signals"] = interrupted
        receipt["owned_processes"] = list(owned.values())
        receipt["ended_monotonic"] = time.monotonic()
        receipt["wall_seconds"] = receipt["ended_monotonic"] - t0
        triggered = receipt["stop_trigger_offset_seconds"]
        receipt["tail_seconds"] = receipt["wall_seconds"] - triggered if triggered is not None else 0.0
        receipt["deadline_overrun_seconds"] = max(0.0, receipt["ended_monotonic"] - deadline)
        receipt["measurement_boundary"] = "includes startup, worker and cleanup; ends before final receipt persistence"
        try:
            receipt["free_bytes_end"] = _free_bytes(folder)
        except OSError as error:
            receipt["free_bytes_end_error"] = str(error)
        temporary = folder / "receipt.json.tmp"
        try:
            temporary.write_text(json.dumps(receipt, indent=2, ensure_ascii=False) + "\n")
            os.replace(temporary, folder / "receipt.json")
        finally:
            for signum, previous in previous_handlers.items():
                signal.signal(signum, previous)
    return receipt


def _handshake_child() -> None:
    if len(sys.argv) < 4 or sys.argv[1] != "--handshake-child":
        raise SystemExit("Import run_bounded(); this module is not a campaign CLI.")
    fd = int(sys.argv[2])
    token = os.read(fd, 1)
    os.close(fd)
    if token != b"G":
        raise SystemExit(125)
    if os.getpriority(os.PRIO_PROCESS, 0) != 19:
        raise SystemExit("handshake child did not reach nice 19")
    os.execvpe(sys.argv[3], sys.argv[3:], os.environ)


if __name__ == "__main__":
    _handshake_child()
