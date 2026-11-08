#!/usr/bin/env python3
"""Observed host/process facts for new runners; no frozen runner is imported.

RSS, Darwin physical footprint, and cgroup memory are different metrics. Values
that cannot be observed are errors or explicit nulls, never fabricated zeroes.
Optional child affinity/cgroup enforcement runs before target exec. The separate
supervisor affinity scope includes Python preparation work and restores its mask.
"""
from __future__ import annotations

import ctypes
import ctypes.util
from contextlib import contextmanager
from decimal import Decimal
import errno
import json
import math
import os
from pathlib import Path
import platform
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.request
import uuid


class ObservationError(RuntimeError):
    """A required observation failed; callers must not treat this as zero usage."""


def _read(path: Path) -> str:
    try:
        return path.read_text()
    except OSError as error:
        raise ObservationError(f"read {path}: {error}") from error


def _run_text(argv: list[str], *, input_text: str | None = None) -> str:
    try:
        input_options = {"stdin": subprocess.DEVNULL} if input_text is None else {"input": input_text}
        result = subprocess.run(argv, **input_options, capture_output=True,
                                text=True, timeout=3, check=False,
                                env={**os.environ, "LC_ALL": "C"})
    except (OSError, subprocess.SubprocessError) as error:
        raise ObservationError(f"observe {argv[0]}: {error}") from error
    if result.returncode:
        raise ObservationError(f"observe {argv[0]} exited {result.returncode}: {result.stderr.strip()}")
    return result.stdout


def _nonnegative(value, label: str) -> int:
    try:
        number = int(value)
    except (ValueError, TypeError, OverflowError) as error:
        raise ObservationError(f"invalid {label}: {value!r}") from error
    if number < 0:
        raise ObservationError(f"negative {label}")
    return number


def _parse_linux_stat(text: str, expected_pid: int) -> dict:
    # comm may contain whitespace and parentheses; numeric fields follow the last ')'.
    close = text.rfind(")")
    try:
        pid = int(text[:text.index("(")].strip())
        tail = text[close + 1:].split()
        if close < 0 or pid != expected_pid or len(tail) < 22:
            raise ValueError("missing/mismatched stat fields")
        ppid, pgid = int(tail[1]), int(tail[2])
        ticks = _nonnegative(tail[19], "process start ticks")
        pages = _nonnegative(tail[21], "process RSS pages")
    except (ValueError, IndexError) as error:
        raise ObservationError(f"malformed /proc/{expected_pid}/stat") from error
    return {"pid": pid, "ppid": ppid, "pgid": pgid, "state": tail[0],
            "rss_bytes": pages * os.sysconf("SC_PAGE_SIZE"),
            "start_id": f"linux-start-ticks:{ticks}",
            "identity_source": "/proc/pid/stat field 22", "identity_error": None,
            "rss_source": "/proc/pid/stat RSS pages; sampled, may be approximate",
            "physical_footprint_bytes": None}


def _process_snapshot_linux(proc_root: Path = Path("/proc"), current_pid: int | None = None) -> dict:
    rows = {}
    try:
        entries = list(proc_root.iterdir())
    except OSError as error:
        raise ObservationError(f"enumerate {proc_root}: {error}") from error
    for entry in entries:
        if not entry.name.isdigit():
            continue
        pid = int(entry.name)
        try:
            text = (entry / "stat").read_text()
        except (FileNotFoundError, ProcessLookupError):
            continue  # Exit between enumeration and read is normal.
        except OSError as error:
            raise ObservationError(f"observe process {pid}: {error}") from error
        rows[pid] = _parse_linux_stat(text, pid)
    if (os.getpid() if current_pid is None else current_pid) not in rows:
        raise ObservationError("process snapshot omitted supervisor")
    return rows


class _RusageInfoV0(ctypes.Structure):
    _fields_ = [("uuid", ctypes.c_uint8 * 16)] + [
        (name, ctypes.c_uint64) for name in
        ("user", "system", "idle_wakeups", "interrupt_wakeups", "pageins", "wired",
         "resident", "physical", "start", "exit")]


_LIBPROC = None
_DARWIN_TRACKED: dict[int, tuple[str, str]] = {}


def _darwin_pid_usage(pid: int) -> dict:
    global _LIBPROC
    if _LIBPROC is None:
        library = ctypes.util.find_library("proc")
        if library is None:
            raise ObservationError("Darwin libproc unavailable")
        try:
            _LIBPROC = ctypes.CDLL(library, use_errno=True)
            _LIBPROC.proc_pid_rusage.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.POINTER(_RusageInfoV0)]
            _LIBPROC.proc_pid_rusage.restype = ctypes.c_int
        except (OSError, AttributeError) as error:
            raise ObservationError(f"Darwin libproc unavailable: {error}") from error
    value = _RusageInfoV0()
    if _LIBPROC.proc_pid_rusage(pid, 0, ctypes.byref(value)):
        code = ctypes.get_errno()
        raise OSError(code, f"proc_pid_rusage({pid}): {os.strerror(code)}")
    return {"start_id": f"darwin-start-abstime:{int(value.start)}",
            "physical_footprint_bytes": int(value.physical),
            "rusage_resident_bytes": int(value.resident)}


def _process_snapshot_darwin(*, current_pid: int | None = None) -> dict:
    supervisor = os.getpid() if current_pid is None else current_pid
    text = _run_text(["ps", "-axo", "pid=,ppid=,pgid=,stat=,rss=,lstart="])
    rows = {}
    for line in text.splitlines():
        fields = line.split(maxsplit=5)
        try:
            if len(fields) != 6:
                raise ValueError("missing fields")
            pid, ppid, pgid = map(int, fields[:3])
            rss = _nonnegative(fields[4], "ps RSS") * 1024
        except ValueError as error:
            raise ObservationError(f"malformed ps row: {line!r}") from error
        rows[pid] = {"pid": pid, "ppid": ppid, "pgid": pgid, "state": fields[3],
                     "rss_bytes": rss, "start_id": "ps-lstart:" + " ".join(fields[5].split()),
                     "identity_source": "ps lstart; unrelated process, not a signal identity",
                     "identity_error": None, "rss_source": "ps RSS KiB; sampled",
                     "physical_footprint_bytes": None}
    if supervisor not in rows:
        raise ObservationError("process snapshot omitted supervisor")
    for pid, (ps_start, _) in list(_DARWIN_TRACKED.items()):
        if pid not in rows or rows[pid]["start_id"] != ps_start:
            del _DARWIN_TRACKED[pid]
    related = {supervisor} | set(_DARWIN_TRACKED)
    while True:
        groups = {rows[pid]["pgid"] for pid in related if pid != supervisor and pid in rows
                  and rows[pid]["pgid"] > 1 and rows[pid]["pgid"] != rows[supervisor]["pgid"]}
        added = {pid for pid, row in rows.items()
                 if row["ppid"] in related or row["pgid"] in groups}
        if added <= related:
            break
        related |= added
    for pid in related:
        row = rows.get(pid)
        if row is None:
            continue
        ps_start = row["start_id"]
        try:
            usage = _darwin_pid_usage(pid)
        except OSError as error:
            if error.errno in (errno.ESRCH, errno.ENOENT):
                if row["state"].startswith("Z"):
                    cached = _DARWIN_TRACKED.get(pid)
                    if cached and cached[0] == ps_start:
                        row["start_id"] = cached[1]
                    row["identity_error"] = "zombie: libproc unavailable; never signal a zombie"
                    continue
                rows.pop(pid, None)
                _DARWIN_TRACKED.pop(pid, None)
                continue
            raise ObservationError(f"related process identity unavailable: {error}") from error
        row.update(usage)
        row["identity_source"] = "proc_pid_rusage ri_proc_start_abstime"
        _DARWIN_TRACKED[pid] = (ps_start, row["start_id"])
    if supervisor not in rows:
        raise ObservationError("supervisor disappeared during process observation")
    return rows


def process_snapshot() -> dict[int, dict]:
    if sys.platform == "darwin":
        return _process_snapshot_darwin()
    if sys.platform.startswith("linux"):
        return _process_snapshot_linux()
    raise ObservationError(f"unsupported process platform: {sys.platform}")


def _linux_kib_fields(text: str) -> dict[str, int]:
    values = {}
    for line in text.splitlines():
        fields = line.split()
        if len(fields) == 3 and fields[2] == "kB":
            values[fields[0].removesuffix(":")] = _nonnegative(fields[1], "meminfo value") * 1024
    return values


def _counter_fields(text: str, separator: str | None = None) -> dict[str, int]:
    values = {}
    for line in text.splitlines():
        fields = line.split(separator, 1) if separator else line.split()
        if len(fields) == 2 and fields[1].strip().rstrip(".").isdigit():
            values[fields[0].strip()] = int(fields[1].strip().rstrip("."))
    return values


def _require(fields: dict, *keys: str) -> None:
    missing = [key for key in keys if key not in fields]
    if missing:
        raise ObservationError(f"required observation fields missing: {', '.join(missing)}")


def _memory_linux(proc_root: Path = Path("/proc")) -> dict:
    info = _linux_kib_fields(_read(proc_root / "meminfo"))
    counters = _counter_fields(_read(proc_root / "vmstat"))
    _require(info, "MemTotal", "MemAvailable", "SwapTotal", "SwapFree")
    _require(counters, "pswpin", "pswpout")
    if info["SwapFree"] > info["SwapTotal"] or info["MemAvailable"] > info["MemTotal"]:
        raise ObservationError("inconsistent Linux memory totals")
    page = os.sysconf("SC_PAGE_SIZE")
    return {"platform": "linux", "total_bytes": info["MemTotal"],
            "available_bytes": info["MemAvailable"], "available_kind": "kernel_MemAvailable_estimate",
            "swap_total_bytes": info["SwapTotal"], "swap_free_bytes": info["SwapFree"],
            "swap_used_bytes": info["SwapTotal"] - info["SwapFree"],
            "swap_in_bytes": counters["pswpin"] * page, "swap_out_bytes": counters["pswpout"] * page,
            "page_size_bytes": page, "compressor_bytes": None,
            "source": {"memory": str(proc_root / "meminfo"), "swap_io": str(proc_root / "vmstat")},
            "error": None}


def _parse_darwin_swap(text: str) -> dict[str, int]:
    values = {}
    scales = {"B": 1, "K": 1024, "M": 1024**2, "G": 1024**3, "T": 1024**4}
    for key, value, unit in re.findall(r"\b(total|used|free)\s*=\s*([\d.]+)([BKMGT])", text, re.I):
        try:
            values[key.lower()] = int(Decimal(value) * scales[unit.upper()])
        except ArithmeticError as error:
            raise ObservationError("malformed Darwin swap size") from error
    _require(values, "total", "used", "free")
    if values["used"] > values["total"] or values["free"] > values["total"]:
        raise ObservationError("inconsistent Darwin swap totals")
    return values


def _memory_darwin() -> dict:
    total = _nonnegative(_run_text(["sysctl", "-n", "hw.memsize"]).strip(), "physical RAM")
    swap = _parse_darwin_swap(_run_text(["sysctl", "-n", "vm.swapusage"]))
    text = _run_text(["vm_stat"])
    match = re.search(r"page size of (\d+) bytes", text)
    if not match or int(match.group(1)) <= 0:
        raise ObservationError("vm_stat page size missing")
    page = int(match.group(1))
    counts = _counter_fields(text, ":")
    _require(counts, "Pages free", "Swapins", "Swapouts", "Pages occupied by compressor")
    free = counts["Pages free"] * page
    if free > total:
        raise ObservationError("inconsistent Darwin free memory")
    return {"platform": "darwin", "total_bytes": total, "available_bytes": free,
            "available_kind": "free_pages_only_not_Linux_MemAvailable",
            "swap_total_bytes": swap["total"], "swap_free_bytes": swap["free"],
            "swap_used_bytes": swap["used"], "swap_in_bytes": counts["Swapins"] * page,
            "swap_out_bytes": counts["Swapouts"] * page, "page_size_bytes": page,
            "compressor_bytes": counts["Pages occupied by compressor"] * page,
            "source": {"memory": "sysctl hw.memsize + vm_stat Pages free",
                       "swap": "sysctl vm.swapusage", "swap_io": "vm_stat Swapins/Swapouts"},
            "error": None}


def memory_snapshot() -> dict:
    if sys.platform == "darwin":
        return _memory_darwin()
    if sys.platform.startswith("linux"):
        return _memory_linux()
    raise ObservationError(f"unsupported memory platform: {sys.platform}")


def _darwin_continuous_ns() -> int:
    class Timebase(ctypes.Structure):
        _fields_ = [("numer", ctypes.c_uint32), ("denom", ctypes.c_uint32)]
    try:
        lib = ctypes.CDLL("/usr/lib/libSystem.B.dylib")
        lib.mach_continuous_time.argtypes = []
        lib.mach_continuous_time.restype = ctypes.c_uint64
        lib.mach_timebase_info.argtypes = [ctypes.POINTER(Timebase)]
        lib.mach_timebase_info.restype = ctypes.c_int
        scale = Timebase()
        if lib.mach_timebase_info(ctypes.byref(scale)) or scale.denom == 0:
            raise ObservationError("mach_timebase_info failed")
        return int(lib.mach_continuous_time()) * scale.numer // scale.denom
    except (OSError, AttributeError) as error:
        raise ObservationError(f"mach_continuous_time unavailable: {error}") from error


def clock_snapshot() -> dict:
    before = time.monotonic_ns()
    realtime = time.time_ns()
    monotonic = time.monotonic_ns()
    source = None
    error = None
    continuous = None
    try:
        if sys.platform == "darwin":
            continuous = _darwin_continuous_ns()
            source = "mach_continuous_time"
        elif sys.platform.startswith("linux") and hasattr(time, "CLOCK_BOOTTIME"):
            continuous = time.clock_gettime_ns(time.CLOCK_BOOTTIME)
            source = "CLOCK_BOOTTIME"
        else:
            error = "suspend-aware monotonic clock unavailable"
    except (OSError, ObservationError) as problem:
        error = str(problem)
    if continuous is None:
        raise ObservationError(error or "required suspend-aware clock unavailable")
    return {"realtime_ns": realtime, "monotonic_ns": monotonic,
            "suspend_aware_ns": continuous, "suspend_aware_source": source,
            "capture_span_ns": time.monotonic_ns() - before, "error": error}


def clock_delta(before: dict, after: dict, *, threshold_seconds: float = 1.0) -> dict:
    if not math.isfinite(threshold_seconds) or threshold_seconds < 0:
        raise ValueError("clock threshold must be finite and nonnegative")
    real = (after["realtime_ns"] - before["realtime_ns"]) / 1e9
    mono = (after["monotonic_ns"] - before["monotonic_ns"]) / 1e9
    if mono < 0:
        raise ObservationError("monotonic clock moved backwards")
    supported = (before.get("suspend_aware_ns") is not None
                 and after.get("suspend_aware_ns") is not None
                 and before.get("suspend_aware_source") == after.get("suspend_aware_source"))
    continuous = ((after["suspend_aware_ns"] - before["suspend_aware_ns"]) / 1e9
                  if supported else None)
    if continuous is not None and continuous < 0:
        raise ObservationError("suspend-aware clock moved backwards")
    suspend = continuous - mono if supported else None
    adjustment = real - continuous if supported else None
    uncertainty = sum(_nonnegative(row.get("capture_span_ns", 0), "clock capture span")
                      for row in (before, after)) / 1e9
    bound = threshold_seconds + uncertainty
    differences = [real - mono] if not supported else [suspend, adjustment]
    return {"realtime_seconds": real, "monotonic_seconds": mono,
            "suspend_aware_seconds": continuous, "suspend_clock_difference_seconds": suspend,
            "realtime_clock_difference_seconds": adjustment,
            "realtime_minus_monotonic_seconds": real - mono,
            "suspend_evidence": suspend is not None and suspend > bound,
            "clock_adjustment_evidence": adjustment is not None and abs(adjustment) > bound,
            "unclassified_clock_discrepancy": not supported and abs(real - mono) > bound,
            "capture_ambiguous": any(threshold_seconds < abs(value) <= bound for value in differences),
            "capture_uncertainty_seconds": uncertainty,
            "evidence_threshold_seconds": bound,
            "suspend_aware_source": after.get("suspend_aware_source") if supported else None}


def normalize_ru_maxrss(value) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        raise ObservationError("invalid ru_maxrss")
    if sys.platform == "darwin":
        return int(value)
    if sys.platform.startswith("linux"):
        return int(value * 1024)
    raise ObservationError(f"unsupported ru_maxrss platform: {sys.platform}")


def _fact(value, source: str, error: str | None = None) -> dict:
    return {"value": value, "source": source, "error": error}


def _observe(source: str, work) -> dict:
    try:
        return _fact(work(), source)
    except (OSError, ObservationError, ImportError, ValueError, IndexError, KeyError, subprocess.SubprocessError) as error:
        return _fact(None, source, str(error))


def _decode_disk_plist(raw: str) -> tuple[dict, dict]:
    try:
        import plistlib

        result = plistlib.loads(raw.encode())
        if not isinstance(result, dict):
            raise ValueError("disk metadata plist is not an object")
        return result, {"source": "Python plistlib", "error": None, "fallback_reason": None}
    except Exception as primary_error:
        # The host Python may have a broken optional libexpat dependency. plutil
        # reads only the supplied text, emits stdout, and does not rewrite a file.
        reason = f"{type(primary_error).__name__}: {primary_error}"
        try:
            converted = _run_text(["/usr/bin/plutil", "-convert", "json", "-o", "-", "--", "-"], input_text=raw)
            result = json.loads(converted)
            if not isinstance(result, dict):
                raise ValueError("disk metadata JSON is not an object")
        except (OSError, ObservationError, ValueError, TypeError) as error:
            raise ObservationError(f"plistlib failed ({reason}); plutil fallback failed: {error}") from error
        return result, {"source": "/usr/bin/plutil JSON conversion over stdin/stdout",
                        "error": None, "fallback_reason": reason}


def _read_metadata_candidates(paths, parse) -> dict:
    attempts = []
    for path in paths:
        try:
            value = parse(path.read_text().strip())
            return {**_fact(value, str(path)), "attempt_errors": attempts}
        except FileNotFoundError as error:
            attempts.append({"source": str(path), "error": str(error)})
        except (OSError, ValueError) as error:
            attempts.append({"source": str(path), "error": str(error)})
            break
    return {**_fact(None, str(path), attempts[-1]["error"]), "attempt_errors": attempts}


def _linux_block_metadata(device_id: str, sys_block_root: Path = Path("/sys/dev/block")) -> dict:
    link = sys_block_root / device_id
    resolution_error = None
    try:
        block = link.resolve(strict=True)
        parents = [block]
        if (block / "partition").is_file():
            parents.append(block.parent)
    except OSError as error:
        block, parents = None, [link]
        resolution_error = str(error)
    def rotation(text):
        if text not in ("0", "1"):
            raise ValueError("rotational must be the kernel value 0 or 1")
        return int(text)
    def model(text):
        if not text:
            raise ValueError("device model is empty")
        return text
    rotational = _read_metadata_candidates([parent / "queue/rotational" for parent in parents], rotation)
    raw_model = _read_metadata_candidates([candidate for parent in parents
                                          for candidate in (parent / "device/model", parent / "model")], model)
    return {"resolved_block_device": str(block) if block is not None else None,
            "block_resolution_error": resolution_error,
            "rotational": rotational["value"], "rotational_source": rotational["source"],
            "rotational_error": rotational["error"], "rotational_observation": rotational,
            "raw_model": raw_model["value"], "raw_model_source": raw_model["source"],
            "raw_model_error": raw_model["error"], "model_observation": raw_model}


def _disk_kind(output: Path) -> dict:
    if sys.platform == "darwin":
        device = _run_text(["df", "-P", str(output)]).splitlines()[-1].split()[0]
        result, parser = _decode_disk_plist(_run_text(["diskutil", "info", "-plist", device]))
        return {"device": device, "filesystem": result.get("FilesystemType"),
                "solid_state": result.get("SolidState"), "protocol": result.get("BusProtocol"),
                "virtual": result.get("VirtualOrPhysical"), "metadata_parser": parser,
                "metadata_source": "df -P output filesystem + diskutil info -plist"}
    if sys.platform.startswith("linux"):
        candidates = []
        for line in _read(Path("/proc/self/mountinfo")).splitlines():
            left, right = line.split(" - ", 1)
            fields, fs = left.split(), right.split()
            mount = re.sub(r"\\([0-7]{3})", lambda m: chr(int(m.group(1), 8)), fields[4])
            if output == Path(mount) or Path(mount) in output.parents:
                candidates.append((len(mount), fields[2], mount, fs[0], fs[1]))
        if not candidates:
            raise ObservationError("output filesystem not found in mountinfo")
        _, device_id, mount, filesystem, source = max(candidates)
        return {"device": source, "mountpoint": mount, "filesystem": filesystem,
                **_linux_block_metadata(device_id),
                "kind_note": "nonrotational/raw model observations do not establish an AWS volume product"}
    raise ObservationError(f"unsupported disk platform: {sys.platform}")


def _imds_identity() -> dict:
    # Explicit opt-in only; no credentials endpoints and no IMDSv1 fallback.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    token_request = urllib.request.Request("http://169.254.169.254/latest/api/token", method="PUT",
                                         headers={"X-aws-ec2-metadata-token-ttl-seconds": "60"})
    with opener.open(token_request, timeout=1) as response:
        token = response.read(4096).decode()
    request = urllib.request.Request("http://169.254.169.254/latest/dynamic/instance-identity/document",
                                     headers={"X-aws-ec2-metadata-token": token})
    with opener.open(request, timeout=1) as response:
        data = json.loads(response.read(65536))
    return {key: data.get(key) for key in ("instanceType", "availabilityZone", "region", "architecture")}


def host_environment(output, include_imds: bool = False) -> dict:
    path = Path(output).absolute()
    while not path.exists() and path != path.parent:
        path = path.parent
    disk = _observe("shutil.disk_usage(output filesystem)",
                    lambda: dict(zip(("total_bytes", "used_bytes", "free_bytes"), shutil.disk_usage(path))))
    memory = _observe("platform memory_snapshot", memory_snapshot)
    affinity = (_observe("os.sched_getaffinity(0)", lambda: sorted(os.sched_getaffinity(0)))
                if hasattr(os, "sched_getaffinity") else _fact(None, "CPU affinity", "unsupported"))
    return {"schema": "zkfdo-host-environment-v1", "captured_realtime_ns": time.time_ns(),
            "host": _fact(socket.gethostname(), "socket.gethostname"),
            "platform": _fact(sys.platform, "sys.platform"),
            "kernel": _fact(platform.release(), "platform.release"),
            "machine": _fact(platform.machine(), "platform.machine"),
            "logical_cpu_count": _fact(os.cpu_count(), "os.cpu_count; host-visible logical CPUs"),
            "effective_cpu_affinity": affinity, "memory": memory, "disk_space": disk,
            "disk_kind": _observe("diskutil/df on Darwin; mountinfo/sysfs on Linux", lambda: _disk_kind(path.resolve())),
            "imds": (_observe("AWS IMDSv2 instance identity (selected fields only)", _imds_identity)
                     if include_imds else _fact(None, "AWS IMDSv2", "not requested; no network probe"))}


def _cgroup2_mount(root: Path) -> str:
    candidates = []
    for line in _read(Path("/proc/self/mountinfo")).splitlines():
        try:
            left, right = line.split(" - ", 1)
            mount = Path(re.sub(r"\\([0-7]{3})", lambda m: chr(int(m.group(1), 8)), left.split()[4]))
            filesystem = right.split()[0]
        except (ValueError, IndexError) as error:
            raise ObservationError("malformed mountinfo while checking cgroup delegation") from error
        if root == mount or mount in root.parents:
            candidates.append((len(mount.parts), str(mount), filesystem))
    if not candidates or max(candidates)[2] != "cgroup2":
        raise ObservationError(f"delegated cgroup root is not on cgroup v2: {root}")
    return max(candidates)[1]


def _new_cgroup(root: Path) -> Path:
    path = root / ("zkfdo-" + uuid.uuid4().hex)
    path.mkdir()  # Never reuse an existing group or create a delegation parent.
    return path


def _remove_cgroup(path: Path) -> None:
    path.rmdir()  # cgroupfs removes its kernel control files; never recursively delete.


def _write_cgroup_control(path: Path, value: str) -> None:
    # No O_CREAT/O_TRUNC: a missing kernel interface must fail, not become a file.
    fd = os.open(path, os.O_WRONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
    try:
        payload = (value + "\n").encode("ascii")
        if os.write(fd, payload) != len(payload):
            raise ObservationError(f"short write to cgroup control: {path}")
    finally:
        os.close(fd)


def _strict_counters(path: Path, required: tuple[str, ...]) -> dict[str, int]:
    result = {}
    for line in _read(path).splitlines():
        parts = line.split()
        if len(parts) != 2 or parts[0] in result:
            raise ObservationError(f"malformed cgroup counters: {path}")
        result[parts[0]] = _nonnegative(parts[1], f"{path.name} {parts[0]}")
    _require(result, *required)
    return result


class IsolationContext:
    """Optional Linux limits; attach the stopped exec-gate child before target exec.

    The caller owns process-tree termination. kill() additionally covers members
    of our fresh cgroup even if their original parent/group has exited. A process
    intentionally migrating out of a writable delegated cgroup is not contained;
    this is resource accounting for trusted tools, not a security sandbox.
    """
    def __init__(self, cpus, memory_max_bytes, cgroup_root):
        self.cpus = cpus
        self.group = None
        self.group_identity = None
        self.pid = None
        self._final = None
        self.configuration = {"enabled": cpus is not None or memory_max_bytes is not None,
                              "cpus_requested": sorted(cpus) if cpus is not None else None,
                              "cpus_effective": None, "memory_max_bytes": memory_max_bytes,
                              "cgroup_root": str(cgroup_root) if cgroup_root is not None else None,
                              "cgroup_path": None, "cgroup_mount": None,
                              "memory_metric": "cgroup v2 memory; not RSS or Darwin physical footprint",
                              "swap_limit": "not configured"}
        if memory_max_bytes is None:
            return
        try:
            root = Path(cgroup_root).resolve(strict=True)
            self.configuration["cgroup_root"] = str(root)
            self.configuration["cgroup_mount"] = _cgroup2_mount(root)
            if "memory" not in _read(root / "cgroup.controllers").split():
                raise ObservationError("memory controller is unavailable in delegated cgroup root")
            if "memory" not in _read(root / "cgroup.subtree_control").split():
                raise ObservationError("delegated root must already enable memory in cgroup.subtree_control")
            if _read(root / "cgroup.type").strip() != "domain":
                raise ObservationError("memory isolation requires a domain cgroup delegation")
            self.group = _new_cgroup(root)
            info = self.group.stat()
            self.group_identity = (info.st_dev, info.st_ino)
            self.configuration["cgroup_path"] = str(self.group)
            self._write("memory.max", str(memory_max_bytes))
            effective = _nonnegative(_read(self.group / "memory.max").strip(), "effective memory.max")
            if effective != memory_max_bytes:
                raise ObservationError("kernel memory.max differs from requested limit")
            self.sample()  # Required usage interfaces must work before launching anything.
        except (OSError, ObservationError) as error:
            cleanup = ""
            if self.group is not None:
                try:
                    self._owned_group()
                    _remove_cgroup(self.group)
                except (OSError, ObservationError) as problem:
                    cleanup = f"; empty preparation group cleanup failed at {self.group}: {problem}"
            raise ObservationError(f"prepare isolation: {error}{cleanup}") from error

    def _owned_group(self) -> Path:
        if self.group is None or self.group_identity is None or self._final is not None:
            raise ObservationError("no active owned cgroup")
        try:
            if self.group.is_symlink():
                raise ObservationError("owned cgroup path became a symlink")
            info = self.group.stat()
            if (info.st_dev, info.st_ino) != self.group_identity:
                raise ObservationError("owned cgroup identity changed")
        except OSError as error:
            raise ObservationError(f"owned cgroup unavailable: {error}") from error
        return self.group

    def _write(self, name: str, value: str) -> None:
        try:
            _write_cgroup_control(self._owned_group() / name, value)
        except OSError as error:
            raise ObservationError(f"write owned cgroup {name}: {error}") from error

    def attach(self, pid: int) -> dict:
        if self._final is not None or self.pid is not None:
            raise ObservationError("isolation context may attach exactly one exec-gate child")
        if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 1 or pid == os.getpid():
            raise ObservationError("refuse isolation attachment of supervisor/system PID")
        try:
            if self.cpus is not None:
                inherited = set(os.sched_getaffinity(pid))
                if not self.cpus <= inherited:
                    raise ObservationError("requested CPUs exceed child inherited allowed affinity")
                os.sched_setaffinity(pid, self.cpus)
                effective = set(os.sched_getaffinity(pid))
                if effective != self.cpus:
                    raise ObservationError("effective CPU affinity differs from requested CPUs")
                self.configuration["cpus_effective"] = sorted(effective)
            if self.group is not None:
                self._write("cgroup.procs", str(pid))
                members = {_nonnegative(item, "cgroup PID") for item in _read(self.group / "cgroup.procs").split()}
                if pid not in members:
                    raise ObservationError("exec-gate child was not observed in owned cgroup")
        except (OSError, AttributeError) as error:
            raise ObservationError(f"attach isolation: {error}") from error
        self.pid = pid
        return {"status": "attached" if self.configuration["enabled"] else "disabled",
                "pid": pid, "configuration": dict(self.configuration)}

    def sample(self) -> dict:
        if self._final is not None:
            return self._final["sample"]
        if self.group is None:
            return {"enabled": False, "remaining_pids": [],
                    "source": "cgroup memory isolation disabled", "error": None}
        root = self._owned_group()
        current = _nonnegative(_read(root / "memory.current").strip(), "cgroup memory.current")
        peak = _nonnegative(_read(root / "memory.peak").strip(), "cgroup memory.peak")
        events = _strict_counters(root / "memory.events", ("max", "oom", "oom_kill"))
        cpu = _strict_counters(root / "cpu.stat", ("usage_usec", "user_usec", "system_usec"))
        group_events = _strict_counters(root / "cgroup.events", ("populated",))
        pids = sorted({_nonnegative(item, "cgroup PID") for item in _read(root / "cgroup.procs").split()})
        return {"enabled": True, "memory_current_bytes": current, "memory_peak_bytes": peak,
                "memory_events": events, "cpu_stat": cpu, "cpu_seconds": cpu["usage_usec"] / 1e6,
                "cgroup_events": group_events, "remaining_pids": pids,
                "source": str(root), "error": None}

    def kill(self) -> dict:
        if self.group is None or self._final is not None:
            return {"status": "not_needed", "source": "no active owned cgroup"}
        self._write("cgroup.kill", "1")
        return {"status": "kill_requested", "source": str(self.group / "cgroup.kill")}

    def finalize(self) -> dict:
        if self._final is not None:
            return self._final
        sample = self.sample()
        empty = self.group is None or (not sample["remaining_pids"] and sample["cgroup_events"]["populated"] == 0)
        if not empty:
            return {"cleanup_complete": False, "group_removed": False,
                    "remaining_pids": sample["remaining_pids"], "sample": sample,
                    "error": "owned cgroup is still populated; call kill and retry after process cleanup"}
        if self.group is not None:
            try:
                _remove_cgroup(self._owned_group())
            except OSError as error:
                raise ObservationError(f"remove owned cgroup {self.group}: {error}") from error
        self._final = {"cleanup_complete": True, "group_removed": self.group is not None,
                       "remaining_pids": [], "sample": sample, "error": None}
        return self._final


def parse_cpu_list(value) -> list[int] | None:
    """Parse list/set or CLI ranges such as '0-3,6'; reject empty/unbounded masks."""
    if value is None:
        return None
    if isinstance(value, str):
        cpus = set()
        for part in value.split(","):
            item = part.strip()
            if not re.fullmatch(r"\d+(?:-\d+)?", item):
                raise ObservationError("CPU mask must contain IDs or inclusive ranges, e.g. 0-3,6")
            bounds = item.split("-")
            first, last = int(bounds[0]), int(bounds[-1])
            if first > last or last - first >= 65536:
                raise ObservationError("CPU range is reversed or exceeds 65536 entries")
            cpus.update(range(first, last + 1))
            if len(cpus) > 65536:
                raise ObservationError("CPU mask exceeds 65536 entries")
    else:
        if not isinstance(value, (list, tuple, set, frozenset)) or len(value) > 65536 or any(
                isinstance(cpu, bool) or not isinstance(cpu, int) or cpu < 0 for cpu in value):
            raise ObservationError("cpus must be a collection of nonnegative integer CPU IDs")
        cpus = set(value)
    if not cpus:
        raise ObservationError("CPU mask must not be empty")
    return sorted(cpus)


def prepare_isolation(cpus=None, memory_max_bytes=None, cgroup_root=None) -> IsolationContext:
    """Prepare opt-in limits; memory requires an explicitly delegated cgroup root."""
    parsed = parse_cpu_list(cpus)
    cpus = frozenset(parsed) if parsed is not None else None
    if memory_max_bytes is not None and (isinstance(memory_max_bytes, bool)
            or not isinstance(memory_max_bytes, int) or memory_max_bytes <= 0):
        raise ObservationError("memory_max_bytes must be a positive integer")
    if (memory_max_bytes is None) != (cgroup_root is None):
        raise ObservationError("memory_max_bytes and explicit delegated cgroup_root must be supplied together")
    if (cpus is not None or memory_max_bytes is not None) and not sys.platform.startswith("linux"):
        raise ObservationError("CPU affinity/cgroup isolation is supported only on Linux")
    if cpus is not None and not all(hasattr(os, name) for name in ("sched_getaffinity", "sched_setaffinity")):
        raise ObservationError("Linux CPU affinity interfaces are unavailable")
    return IsolationContext(cpus, memory_max_bytes, cgroup_root)


@contextmanager
def scoped_supervisor_affinity(cpus=None):
    """Temporarily bind the main Python thread and future children; restore on exit.

    Existing non-main threads are not rebound. This runner requires single-thread
    orchestration; memory cgroups deliberately continue to exclude the supervisor.
    The yielded mutable receipt is updated during restoration, including failures.
    """
    requested = parse_cpu_list(cpus)
    receipt = {"before": None, "requested": requested, "effective": None,
               "restored": requested is None, "restored_mask": None, "error": None,
               "scope": "supervisor main thread and subsequently spawned children"}
    if requested is None:
        yield receipt
        return
    if not sys.platform.startswith("linux"):
        raise ObservationError("supervisor CPU affinity is supported only on Linux")
    if threading.current_thread() is not threading.main_thread():
        raise ObservationError("supervisor affinity scope requires the main thread")
    before = None
    try:
        before = set(os.sched_getaffinity(0))
        receipt["before"] = sorted(before)
        if not set(requested) <= before:
            raise ObservationError("requested supervisor CPUs exceed inherited allowed affinity")
    except (OSError, AttributeError) as error:
        raise ObservationError(f"read supervisor affinity: {error}") from error
    try:
        try:
            os.sched_setaffinity(0, requested)
            effective = set(os.sched_getaffinity(0))
        except (OSError, AttributeError) as error:
            raise ObservationError(f"set supervisor affinity: {error}") from error
        receipt["effective"] = sorted(effective)
        if effective != set(requested):
            raise ObservationError("effective supervisor affinity differs from requested CPUs")
        yield receipt
    finally:
        try:
            os.sched_setaffinity(0, before)
            restored = set(os.sched_getaffinity(0))
            receipt["restored_mask"] = sorted(restored)
            if restored != before:
                raise ObservationError("restored supervisor affinity differs from original CPUs")
            receipt["restored"] = True
        except (OSError, AttributeError, ObservationError) as error:
            receipt["restored"] = False
            receipt["error"] = f"restore supervisor affinity: {error}"
            raise ObservationError(receipt["error"]) from error
