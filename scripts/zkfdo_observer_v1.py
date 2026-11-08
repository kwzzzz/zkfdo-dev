"""Task-owned disk accounting with separately timed fast and tree observations."""
from contextlib import contextmanager
import math
import os
from pathlib import Path
import resource
import time

from zkfdo_runtime_v1 import BudgetExceeded, ObservationError


class ObservationCosts:
    def __init__(self):
        self.rows = {}

    @contextmanager
    def measure(self, label, *, helper_children=False):
        # Only helper-launching observations may enable this in the sequential
        # supervisor. Payload wait4/reap scopes must keep it off to avoid charging
        # the workload's CPU as observation overhead.
        wall, cpu = time.monotonic(), time.process_time()
        before = resource.getrusage(resource.RUSAGE_CHILDREN) if helper_children else None
        try:
            yield
        finally:
            parent_cpu = time.process_time() - cpu
            helper_cpu = 0.0
            if before is not None:
                after = resource.getrusage(resource.RUSAGE_CHILDREN)
                helper_cpu = (after.ru_utime + after.ru_stime) - (before.ru_utime + before.ru_stime)
            row = self.rows.setdefault(label, {"calls": 0, "wall_seconds": 0.0,
                "parent_cpu_seconds": 0.0, "helper_cpu_seconds": 0.0, "cpu_seconds": 0.0})
            row["calls"] += 1
            row["wall_seconds"] += time.monotonic() - wall
            row["parent_cpu_seconds"] += parent_cpu
            row["helper_cpu_seconds"] += helper_cpu
            row["cpu_seconds"] += parent_cpu + helper_cpu

    def timed(self, label, *, helper_children=False):
        def decorate(function):
            def call(*args, **kwargs):
                with self.measure(label, helper_children=helper_children):
                    return function(*args, **kwargs)
            return call
        return decorate

    def snapshot(self):
        return {key: dict(value) for key, value in self.rows.items()}


class DiskBudget:
    """One task traversal, independent inode sets for each active request subtotal.

    Tree detection can lag by tree_interval_seconds plus traversal/poll latency.
    Fast free-space checks run on every gate by default. Forced boundary samples
    always scan. Neither this sampler nor statvfs is a filesystem quota.
    """
    def __init__(self, root, max_bytes, *, min_free_bytes=0, tree_interval_seconds=1.0,
                 free_interval_seconds=0.0, parent=None):
        if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes <= 0:
            raise ValueError("max disk bytes must be a positive integer")
        if isinstance(min_free_bytes, bool) or not isinstance(min_free_bytes, int) or min_free_bytes < 0:
            raise ValueError("minimum free bytes must be a nonnegative integer")
        for value in (tree_interval_seconds, free_interval_seconds):
            if isinstance(value, bool) or not math.isfinite(value) or value < 0:
                raise ValueError("observation intervals must be finite and nonnegative")
        raw = Path(root).absolute()
        if any(p.is_symlink() for p in (raw, *raw.parents)):
            raise ObservationError("disk accounting refuses symlink root ancestry")
        self.root = raw.resolve()
        if self.root.name == "runs" or self.root == Path(self.root.anchor):
            raise ValueError("refuse a whole runs/filesystem-root disk scan")
        self.max_bytes, self.min_free_bytes = max_bytes, min_free_bytes
        if parent is not None:
            tree_interval_seconds = parent.tree_interval_seconds
            free_interval_seconds = parent.free_interval_seconds
        self.tree_interval_seconds, self.free_interval_seconds = tree_interval_seconds, free_interval_seconds
        self.parent = parent
        self.request = None
        self.last_tree = self.last_free = -float("inf")
        self.peak_bytes = self.last_bytes = self.samples = self.visited_entries = 0
        self.free_bytes = None
        self.tripped = None
        self.costs = ObservationCosts()
        if parent is not None:
            if not self.root.is_relative_to(parent.root) or self.root == parent.root:
                raise ValueError("request must be strictly inside task")
            parent.request = self
            parent.last_tree = -float("inf")

    def _record(self):
        return {"root": str(self.root), "max_disk_bytes": self.max_bytes,
                "current_bytes": self.last_bytes, "peak_bytes": self.peak_bytes,
                "min_free_bytes": self.min_free_bytes, "free_bytes": self.free_bytes,
                "samples": self.samples, "stop_reason": self.tripped,
                "visited_entries": self.visited_entries,
                "tree_interval_seconds": self.tree_interval_seconds,
                "free_interval_seconds": self.free_interval_seconds,
                "observation": self.costs.snapshot(),
                "measurement": "sampled logical regular-file bytes; independent per-scope inode deduplication; no deletion"}

    def sample(self, *, force=True):
        if self.parent is not None:
            self.parent.sample(force=force)
            return self._record()
        budgets = [self] + ([self.request] if self.request is not None else [])
        now = time.monotonic()
        if force or now - self.last_free >= self.free_interval_seconds:
            with self.costs.measure("free_space"):
                root = self.root if self.root.exists() else self.root.parent
                space = os.statvfs(root)
                free = space.f_bavail * space.f_frsize
                for budget in budgets:
                    budget.free_bytes = free
                    if free < budget.min_free_bytes:
                        budget.tripped = budget.tripped or "minimum_free_bytes_exceeded"
            self.last_free = time.monotonic()
        if force or now - self.last_tree >= self.tree_interval_seconds:
            with self.costs.measure("tree"):
                totals, seen = [0] * len(budgets), [set() for _ in budgets]
                stack = [self.root]
                visits = 0
                while stack:
                    directory = stack.pop()
                    try:
                        with os.scandir(directory) as entries:
                            for entry in entries:
                                visits += 1
                                try:
                                    if entry.is_symlink():
                                        raise ObservationError(f"disk accounting refuses unowned symlink: {entry.path}")
                                    if entry.is_dir(follow_symlinks=False):
                                        stack.append(Path(entry.path))
                                    elif entry.is_file(follow_symlinks=False):
                                        stat = entry.stat(follow_symlinks=False)
                                        key = stat.st_dev, stat.st_ino
                                        for index, budget in enumerate(budgets):
                                            if index and not Path(entry.path).is_relative_to(budget.root):
                                                continue
                                            if key not in seen[index]:
                                                totals[index] += stat.st_size
                                                seen[index].add(key)
                                except FileNotFoundError:
                                    continue
                    except FileNotFoundError:
                        continue
                for budget, total in zip(budgets, totals):
                    budget.samples += 1
                    budget.last_bytes = total
                    budget.peak_bytes = max(budget.peak_bytes, total)
                    if total > budget.max_bytes:
                        budget.tripped = budget.tripped or "max_disk_bytes_exceeded"
                self.visited_entries += visits
            self.last_tree = time.monotonic()
        row = self._record()
        if self.request is not None:
            row["request"] = self.request._record()
            if self.request.tripped:
                row["stop_reason"] = row["stop_reason"] or "request_" + self.request.tripped
        return row

    def check(self, *, force=False):
        row = self.sample(force=force)
        if row["stop_reason"]:
            raise BudgetExceeded(row["stop_reason"])
        return row
