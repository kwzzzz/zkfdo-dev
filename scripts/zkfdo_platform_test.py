#!/usr/bin/env python3
"""Fixture-only platform checks: no engine, compiler, IMDS or host mutation."""
import errno
from contextlib import contextmanager, ExitStack
import importlib.util
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location("zkfdo_platform", Path(__file__).with_name("zkfdo_platform.py"))
p = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(p)


def linux_stat(pid=100, ppid=1, pgid=100, ticks=6789, rss=12, state="S"):
    tail = ["0"] * 22
    tail[0], tail[1], tail[2] = state, str(ppid), str(pgid)
    tail[19], tail[21] = str(ticks), str(rss)
    return f"{pid} (name with ) parentheses) " + " ".join(tail)


PS_ROWS = ("100 1 50 S 12 Thu Nov  5 01:00:00 2026\n"
           "101 100 101 S 13 Thu Nov  5 01:00:01 2026\n"
           "800 1 800 S 99 Thu Nov  5 00:00:00 2026\n")


class ProcessTests(unittest.TestCase):
    def setUp(self):
        p._DARWIN_TRACKED.clear()

    def tearDown(self):
        p._DARWIN_TRACKED.clear()

    def test_linux_stat_parentheses_identity_and_rss_units(self):
        with patch.object(p.os, "sysconf", return_value=4096):
            row = p._parse_linux_stat(linux_stat(), 100)
        self.assertEqual(row["start_id"], "linux-start-ticks:6789")
        self.assertEqual(row["rss_bytes"], 12 * 4096)
        self.assertEqual((row["ppid"], row["pgid"]), (1, 100))
        self.assertIsNone(row["physical_footprint_bytes"])
        with self.assertRaises(p.ObservationError):
            p._parse_linux_stat(linux_stat(pid=101), 100)
        with self.assertRaises(p.ObservationError):
            p._parse_linux_stat("100 broken", 100)

    def test_linux_fixture_skips_exited_pids_but_not_malformed_observation(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "100").mkdir()
            (root / "100/stat").write_text(linux_stat())
            (root / "101").mkdir()  # Exit race: no longer has a stat file.
            rows = p._process_snapshot_linux(root, 100)
            self.assertEqual(set(rows), {100})
            (root / "101/stat").write_text("malformed")
            with self.assertRaises(p.ObservationError):
                p._process_snapshot_linux(root, 100)

    def test_linux_missing_supervisor_is_not_empty_success(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(p.ObservationError, "supervisor"):
                p._process_snapshot_linux(Path(folder), 100)

    def test_darwin_only_reads_related_libproc_and_preserves_reparented_identity(self):
        def usage(pid):
            self.assertIn(pid, (100, 101))
            return {"start_id": f"darwin-start-abstime:{pid + 400}",
                    "physical_footprint_bytes": 50, "rusage_resident_bytes": 40}
        with patch.object(p, "_run_text", return_value=PS_ROWS), patch.object(p, "_darwin_pid_usage", side_effect=usage) as reader:
            first = p._process_snapshot_darwin(current_pid=100)
        self.assertEqual(reader.call_count, 2)
        self.assertTrue(first[800]["start_id"].startswith("ps-lstart:"))
        detached = PS_ROWS.replace("101 100 101", "101 1 101")
        with patch.object(p, "_run_text", return_value=detached), patch.object(p, "_darwin_pid_usage", side_effect=usage):
            second = p._process_snapshot_darwin(current_pid=100)
        self.assertEqual(first[101]["start_id"], second[101]["start_id"])

    def test_darwin_permission_failure_is_not_a_disappeared_process(self):
        with patch.object(p, "_run_text", return_value=PS_ROWS), patch.object(p, "_darwin_pid_usage", side_effect=PermissionError(errno.EPERM, "denied")):
            with self.assertRaisesRegex(p.ObservationError, "unavailable"):
                p._process_snapshot_darwin(current_pid=100)

    def test_darwin_reused_unrelated_pid_is_removed_before_libproc_queries(self):
        p._DARWIN_TRACKED[800] = ("ps-lstart:Wed Nov 4 23:00:00 2026", "old-start")
        def usage(pid):
            self.assertNotEqual(pid, 800)
            return {"start_id": f"darwin-start-abstime:{pid}"}
        with patch.object(p, "_run_text", return_value=PS_ROWS), patch.object(p, "_darwin_pid_usage", side_effect=usage):
            rows = p._process_snapshot_darwin(current_pid=100)
        self.assertNotIn(800, p._DARWIN_TRACKED)
        self.assertTrue(rows[800]["start_id"].startswith("ps-lstart:"))

    def test_darwin_child_in_supervisor_group_does_not_adopt_unrelated_group_members(self):
        text = PS_ROWS.replace("101 100 101", "101 100 50").replace("800 1 800", "800 1 50")
        def usage(pid):
            self.assertNotEqual(pid, 800)
            return {"start_id": f"darwin-start-abstime:{pid}"}
        with patch.object(p, "_run_text", return_value=text), patch.object(p, "_darwin_pid_usage", side_effect=usage) as reader:
            p._process_snapshot_darwin(current_pid=100)
        self.assertEqual(reader.call_count, 2)

    def test_darwin_zombie_uses_only_matching_cached_ps_identity(self):
        p._DARWIN_TRACKED[101] = ("ps-lstart:Thu Nov 5 01:00:01 2026", "darwin-start-abstime:501")
        def usage(pid):
            if pid == 101:
                raise ProcessLookupError(errno.ESRCH, "zombie")
            return {"start_id": "darwin-start-abstime:500"}
        text = PS_ROWS.replace("101 100 101 S", "101 1 101 Z")
        with patch.object(p, "_run_text", return_value=text), patch.object(p, "_darwin_pid_usage", side_effect=usage):
            rows = p._process_snapshot_darwin(current_pid=100)
        self.assertEqual(rows[101]["start_id"], "darwin-start-abstime:501")
        self.assertIn("never signal", rows[101]["identity_error"])
        changed = text.replace("01:00:01", "01:00:02")
        with patch.object(p, "_run_text", return_value=changed), patch.object(p, "_darwin_pid_usage", side_effect=usage):
            rows = p._process_snapshot_darwin(current_pid=100)
        self.assertTrue(rows[101]["start_id"].startswith("ps-lstart:"))

    def test_ru_maxrss_has_platform_specific_units_and_rejects_invalid_values(self):
        with patch.object(p.sys, "platform", "darwin"):
            self.assertEqual(p.normalize_ru_maxrss(123), 123)
        with patch.object(p.sys, "platform", "linux"):
            self.assertEqual(p.normalize_ru_maxrss(123), 123 * 1024)
        for value in (-1, True, float("nan"), "3"):
            with self.assertRaises(p.ObservationError):
                p.normalize_ru_maxrss(value)


class MemoryTests(unittest.TestCase):
    def test_linux_memory_uses_kib_and_vmstat_pages(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "meminfo").write_text("MemTotal: 1024 kB\nMemAvailable: 512 kB\nSwapTotal: 2048 kB\nSwapFree: 1024 kB\n")
            (root / "vmstat").write_text("pswpin 2\npswpout 3\n")
            with patch.object(p.os, "sysconf", return_value=4096):
                row = p._memory_linux(root)
            self.assertEqual(row["total_bytes"], 1024**2)
            self.assertEqual(row["swap_used_bytes"], 1024**2)
            self.assertEqual(row["swap_in_bytes"], 8192)
            self.assertEqual(row["swap_out_bytes"], 12288)
            (root / "vmstat").write_text("pswpin 2\n")
            with self.assertRaisesRegex(p.ObservationError, "pswpout"):
                p._memory_linux(root)

    def test_required_memory_failure_never_becomes_zero(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(p.ObservationError):
                p._memory_linux(Path(folder))
        with self.assertRaises(p.ObservationError):
            p._parse_darwin_swap("total = 10M free = 10M")
        with self.assertRaises(p.ObservationError):
            p._parse_darwin_swap("total = 1M used = 2M free = 0M")

    def test_darwin_vm_page_size_and_swapouts_not_pageouts(self):
        answers = {("sysctl", "-n", "hw.memsize"): str(1024**3),
                   ("sysctl", "-n", "vm.swapusage"): "total = 1.00G used = 512.00M free = 512.00M",
                   ("vm_stat",): "Mach Virtual Memory Statistics: (page size of 16384 bytes)\nPages free: 2.\nSwapins: 3.\nSwapouts: 4.\nPageouts: 999.\nPages occupied by compressor: 5.\n"}
        with patch.object(p, "_run_text", side_effect=lambda args: answers[tuple(args)]):
            row = p._memory_darwin()
        self.assertEqual(row["available_bytes"], 2 * 16384)
        self.assertEqual(row["swap_out_bytes"], 4 * 16384)
        self.assertEqual(row["compressor_bytes"], 5 * 16384)
        self.assertIn("not_Linux", row["available_kind"])


class ClockTests(unittest.TestCase):
    def snapshot(self, real, mono, continuous, source="fixture"):
        return {"realtime_ns": real * 10**9, "monotonic_ns": mono * 10**9,
                "suspend_aware_ns": None if continuous is None else continuous * 10**9,
                "suspend_aware_source": source, "capture_span_ns": 1000}

    def test_suspend_and_realtime_clock_adjustment_are_distinct(self):
        before = self.snapshot(100, 10, 20)
        sleep = p.clock_delta(before, self.snapshot(170, 20, 90))
        self.assertEqual(sleep["suspend_clock_difference_seconds"], 60)
        self.assertTrue(sleep["suspend_evidence"])
        self.assertFalse(sleep["clock_adjustment_evidence"])
        adjust = p.clock_delta(before, self.snapshot(200, 20, 30))
        self.assertFalse(adjust["suspend_evidence"])
        self.assertTrue(adjust["clock_adjustment_evidence"])
        self.assertEqual(adjust["realtime_clock_difference_seconds"], 90)

    def test_missing_continuous_clock_does_not_claim_sleep(self):
        delta = p.clock_delta(self.snapshot(100, 10, None), self.snapshot(200, 20, None))
        self.assertFalse(delta["suspend_evidence"])
        self.assertFalse(delta["clock_adjustment_evidence"])
        self.assertTrue(delta["unclassified_clock_discrepancy"])
        with patch.object(p.sys, "platform", "unsupported"):
            with self.assertRaisesRegex(p.ObservationError, "clock unavailable"):
                p.clock_snapshot()

    def test_clock_backwards_and_invalid_threshold_fail(self):
        with self.assertRaises(p.ObservationError):
            p.clock_delta(self.snapshot(100, 10, 20), self.snapshot(110, 9, 30))
        with self.assertRaises(ValueError):
            p.clock_delta({}, {}, threshold_seconds=float("nan"))

    def test_slow_capture_does_not_misclassify_scheduler_stall_as_sleep(self):
        before = self.snapshot(100, 10, 20)
        after = self.snapshot(115, 20, 35)
        after["capture_span_ns"] = 5 * 10**9
        result = p.clock_delta(before, after)
        self.assertFalse(result["suspend_evidence"])
        self.assertTrue(result["capture_ambiguous"])
        self.assertAlmostEqual(result["evidence_threshold_seconds"], 6.000001)
        changed = self.snapshot(120, 20, 30)
        changed["capture_span_ns"] = 10 * 10**9
        result = p.clock_delta(before, changed)
        self.assertFalse(result["clock_adjustment_evidence"])
        self.assertTrue(result["capture_ambiguous"])


class HostTests(unittest.TestCase):
    def test_host_optional_failures_are_explicit_and_imds_never_runs_by_default(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(p, "memory_snapshot", side_effect=p.ObservationError("fixture missing")), patch.object(p, "_disk_kind", side_effect=p.ObservationError("no device metadata")), patch.object(p, "_imds_identity") as imds:
                result = p.host_environment(Path(folder) / "not-created-yet")
        imds.assert_not_called()
        self.assertIsNone(result["memory"]["value"])
        self.assertIn("fixture missing", result["memory"]["error"])
        self.assertIsNone(result["disk_kind"]["value"])
        self.assertGreater(result["disk_space"]["value"]["free_bytes"], 0)
        self.assertIn("no network probe", result["imds"]["error"])

    def test_imds_requires_explicit_optin_and_only_its_errors_are_metadata(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(p, "memory_snapshot", return_value={"total_bytes": 123}), patch.object(p, "_disk_kind", return_value={}), patch.object(p, "_imds_identity", side_effect=OSError("not EC2")) as imds:
                result = p.host_environment(folder, include_imds=True)
        imds.assert_called_once()
        self.assertIsNone(result["imds"]["value"])
        self.assertEqual(result["imds"]["error"], "not EC2")


class DiskMetadataTests(unittest.TestCase):
    def test_darwin_plistlib_import_failure_uses_readonly_plutil_pipe(self):
        raw = "<plist><dict><key>SolidState</key><true/></dict></plist>"
        def observe(argv, **options):
            if argv[0] == "df":
                return "Filesystem blocks used available capacity mount\n/dev/disk3s1 1 1 1 1% /\n"
            if argv[0] == "diskutil":
                return raw
            self.assertEqual(argv, ["/usr/bin/plutil", "-convert", "json", "-o", "-", "--", "-"])
            self.assertEqual(options, {"input_text": raw})
            return '{"SolidState":true,"FilesystemType":"apfs","BusProtocol":"PCI-Express"}'
        with patch.object(p.sys, "platform", "darwin"), patch.dict(p.sys.modules, {"plistlib": None}), \
             patch.object(p, "_run_text", side_effect=observe):
            result = p._disk_kind(Path("/fixture"))
        self.assertEqual(result["device"], "/dev/disk3s1")
        self.assertTrue(result["solid_state"])
        self.assertEqual(result["filesystem"], "apfs")
        self.assertIn("plutil", result["metadata_parser"]["source"])
        self.assertIn("ModuleNotFoundError", result["metadata_parser"]["fallback_reason"])

    def test_plistlib_success_needs_no_converter_and_both_failures_remain_explicit(self):
        with patch.dict(p.sys.modules, {"plistlib": SimpleNamespace(loads=lambda _raw: {"SolidState": False})}), \
             patch.object(p, "_run_text") as converter:
            value, parser = p._decode_disk_plist("fixture")
        self.assertFalse(value["SolidState"])
        self.assertEqual(parser["source"], "Python plistlib")
        converter.assert_not_called()
        with patch.dict(p.sys.modules, {"plistlib": None}), \
             patch.object(p, "_run_text", side_effect=p.ObservationError("converter denied")):
            fact = p._observe("fixture plist", lambda: p._decode_disk_plist("fixture"))
        self.assertIsNone(fact["value"])
        self.assertIn("plistlib failed", fact["error"])
        self.assertIn("converter denied", fact["error"])

    def test_text_input_is_passed_without_shell_or_conflicting_stdin(self):
        with patch.object(p.subprocess, "run", return_value=SimpleNamespace(returncode=0, stdout="{}", stderr="")) as run:
            self.assertEqual(p._run_text(["/usr/bin/plutil", "-"], input_text="fixture"), "{}")
        self.assertEqual(run.call_args.kwargs["input"], "fixture")
        self.assertNotIn("stdin", run.call_args.kwargs)
        self.assertNotIn("shell", run.call_args.kwargs)

    def test_linux_partition_reads_parent_queue_and_model_and_keeps_fallback_sources(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            block = root / "devices/nvme0n1"
            partition = block / "nvme0n1p1"
            partition.mkdir(parents=True)
            (partition / "partition").write_text("1\n")
            (block / "queue").mkdir()
            (block / "queue/rotational").write_text("0\n")
            (block / "device").mkdir()
            (block / "device/model").write_text("fixture raw NVMe model   \n")
            links = root / "dev/block"
            links.mkdir(parents=True)
            (links / "259:1").symlink_to(partition)
            row = p._linux_block_metadata("259:1", links)
        self.assertEqual(row["rotational"], 0)
        self.assertEqual(row["raw_model"], "fixture raw NVMe model")
        self.assertEqual(row["rotational_source"], str(block / "queue/rotational"))
        self.assertEqual(row["raw_model_source"], str(block / "device/model"))
        self.assertIsNone(row["rotational_error"])
        self.assertTrue(row["rotational_observation"]["attempt_errors"])

    def test_linux_missing_or_malformed_metadata_is_unknown_not_zero(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            absent = p._linux_block_metadata("0:1", root)
            self.assertIsNone(absent["rotational"])
            self.assertIsNone(absent["raw_model"])
            self.assertTrue(absent["block_resolution_error"])
            block = root / "8:0"
            (block / "queue").mkdir(parents=True)
            (block / "queue/rotational").write_text("unknown\n")
            malformed = p._linux_block_metadata("8:0", root)
        self.assertIsNone(malformed["rotational"])
        self.assertIn("0 or 1", malformed["rotational_error"])

    def test_metadata_permission_error_is_preserved_without_fallback(self):
        with patch.object(Path, "read_text", side_effect=PermissionError("fixture permission denied")) as read:
            result = p._read_metadata_candidates([Path("/first"), Path("/parent")], int)
        self.assertIsNone(result["value"])
        self.assertIn("permission denied", result["error"])
        self.assertEqual(read.call_count, 1)


class IsolationTests(unittest.TestCase):
    @contextmanager
    def cgroup_fixture(self, *, omit=()):
        with tempfile.TemporaryDirectory() as folder, ExitStack() as stack:
            root = Path(folder)
            for name, text in {"cgroup.controllers": "cpu memory\n", "cgroup.subtree_control": "memory\n",
                               "cgroup.type": "domain\n"}.items():
                (root / name).write_text(text)
            original = p._new_cgroup
            writes = []
            def create(parent):
                group = original(parent)
                controls = {"memory.max": "max\n", "memory.current": "1024\n", "memory.peak": "2048\n",
                            "memory.events": "low 0\nhigh 0\nmax 0\noom 0\noom_kill 0\n",
                            "cpu.stat": "usage_usec 123456\nuser_usec 100000\nsystem_usec 23456\n",
                            "cgroup.events": "populated 0\nfrozen 0\n", "cgroup.procs": "", "cgroup.kill": ""}
                for name, text in controls.items():
                    if name not in omit:
                        (group / name).write_text(text)
                return group
            def write(path, value):
                if not path.exists():
                    raise FileNotFoundError(path)
                writes.append((path, value))
                path.write_text(value + "\n")
                if path.name == "cgroup.procs":
                    (path.parent / "cgroup.events").write_text("populated 1\nfrozen 0\n")
                elif path.name == "cgroup.kill":
                    (path.parent / "cgroup.procs").write_text("")
                    (path.parent / "cgroup.events").write_text("populated 0\nfrozen 0\n")
            def remove(path):
                # Simulate kernel-owned control files disappearing with rmdir.
                for child in path.iterdir():
                    child.unlink()
                path.rmdir()
            stack.enter_context(patch.object(p.sys, "platform", "linux"))
            stack.enter_context(patch.object(p, "_cgroup2_mount", return_value=folder))
            stack.enter_context(patch.object(p, "_new_cgroup", side_effect=create))
            stack.enter_context(patch.object(p, "_write_cgroup_control", side_effect=write))
            stack.enter_context(patch.object(p, "_remove_cgroup", side_effect=remove))
            yield root, writes

    def test_default_isolation_is_noop_and_darwin_options_fail(self):
        with patch.object(p.sys, "platform", "darwin"), patch.object(p, "_new_cgroup") as create:
            context = p.prepare_isolation()
            self.assertFalse(context.configuration["enabled"])
            self.assertEqual(context.attach(424242)["status"], "disabled")
            self.assertTrue(context.finalize()["cleanup_complete"])
            self.assertEqual(context.kill()["status"], "not_needed")
            with self.assertRaisesRegex(p.ObservationError, "only on Linux"):
                p.prepare_isolation(cpus=[0])
            with self.assertRaisesRegex(p.ObservationError, "only on Linux"):
                p.prepare_isolation(memory_max_bytes=4096, cgroup_root="/unused")
        create.assert_not_called()

    def test_cpu_cli_parser_and_invalid_masks(self):
        self.assertEqual(p.parse_cpu_list("0-3,6,2"), [0, 1, 2, 3, 6])
        self.assertEqual(p.parse_cpu_list([3, 1, 3]), [1, 3])
        self.assertIsNone(p.parse_cpu_list(None))
        for value in ("", "1,", "3-1", "-1", "0-99999999", [], [True], [-1], [1.5]):
            with self.subTest(value=value), self.assertRaises(p.ObservationError):
                p.parse_cpu_list(value)

    def test_affinity_is_set_on_child_and_verified_before_attach_returns(self):
        with patch.object(p.sys, "platform", "linux"), \
             patch.object(p.os, "sched_getaffinity", side_effect=[{1, 2, 3}, {1, 3}], create=True), \
             patch.object(p.os, "sched_setaffinity", create=True) as setter:
            context = p.prepare_isolation(cpus="1,3")
            self.assertEqual(context.attach(424242)["configuration"]["cpus_effective"], [1, 3])
        setter.assert_called_once_with(424242, frozenset({1, 3}))
        with self.assertRaisesRegex(p.ObservationError, "exactly one"):
            context.attach(424243)

    def test_affinity_rejects_expansion_permission_failure_and_silent_narrowing(self):
        with patch.object(p.sys, "platform", "linux"), \
             patch.object(p.os, "sched_getaffinity", return_value={1}, create=True), \
             patch.object(p.os, "sched_setaffinity", create=True) as setter:
            with self.assertRaisesRegex(p.ObservationError, "inherited"):
                p.prepare_isolation(cpus=[2]).attach(424242)
            setter.assert_not_called()
        with patch.object(p.sys, "platform", "linux"), \
             patch.object(p.os, "sched_getaffinity", side_effect=[{1, 2}, {1}], create=True), \
             patch.object(p.os, "sched_setaffinity", create=True):
            with self.assertRaisesRegex(p.ObservationError, "differs"):
                p.prepare_isolation(cpus=[1, 2]).attach(424242)
        with patch.object(p.sys, "platform", "linux"), \
             patch.object(p.os, "sched_getaffinity", side_effect=PermissionError("denied"), create=True), \
             patch.object(p.os, "sched_setaffinity", create=True):
            with self.assertRaisesRegex(p.ObservationError, "denied"):
                p.prepare_isolation(cpus=[1]).attach(424242)

    def test_cgroup_lifecycle_uses_only_fresh_group_and_preserves_final_counters(self):
        with self.cgroup_fixture() as (root, writes):
            context = p.prepare_isolation(memory_max_bytes=4096, cgroup_root=root)
            group = context.group
            self.assertTrue(group.name.startswith("zkfdo-"))
            self.assertEqual((group / "memory.max").read_text(), "4096\n")
            self.assertEqual((root / "cgroup.subtree_control").read_text(), "memory\n")
            context.attach(424242)
            sample = context.sample()
            self.assertEqual(sample["memory_peak_bytes"], 2048)
            self.assertEqual(sample["remaining_pids"], [424242])
            self.assertEqual(sample["cpu_seconds"], .123456)
            self.assertFalse(context.finalize()["cleanup_complete"])
            self.assertFalse(context.finalize()["cleanup_complete"])
            (group / "memory.events").write_text("max 3\noom 1\noom_kill 1\n")
            context.kill()
            final = context.finalize()
            self.assertTrue(final["cleanup_complete"])
            self.assertTrue(final["group_removed"])
            self.assertEqual(final["sample"]["memory_events"]["oom_kill"], 1)
            self.assertFalse(group.exists())
            self.assertEqual(context.finalize(), final)
            self.assertEqual(context.sample(), final["sample"])
            self.assertTrue(all(path.parent == group for path, _ in writes))

    def test_cgroup_rejects_missing_delegation_and_required_interfaces(self):
        with self.cgroup_fixture() as (root, _):
            (root / "cgroup.subtree_control").write_text("")
            with self.assertRaisesRegex(p.ObservationError, "already enable memory"):
                p.prepare_isolation(memory_max_bytes=4096, cgroup_root=root)
            self.assertFalse(list(root.glob("zkfdo-*")))
        with self.cgroup_fixture(omit=("memory.peak",)) as (root, _):
            with self.assertRaisesRegex(p.ObservationError, "memory.peak"):
                p.prepare_isolation(memory_max_bytes=4096, cgroup_root=root)
            self.assertFalse(list(root.glob("zkfdo-*")))
        with self.assertRaisesRegex(p.ObservationError, "supplied together"):
            p.prepare_isolation(memory_max_bytes=4096)

    def test_owned_cgroup_replacement_is_not_signalled_or_removed(self):
        with self.cgroup_fixture() as (root, writes):
            context = p.prepare_isolation(memory_max_bytes=4096, cgroup_root=root)
            context.group_identity = (-1, -1)
            count = len(writes)
            with self.assertRaisesRegex(p.ObservationError, "identity changed"):
                context.kill()
            self.assertEqual(len(writes), count)
            with self.assertRaisesRegex(p.ObservationError, "identity changed"):
                context.finalize()

    def test_cgroup_mount_requires_v2_and_respects_nested_mounts(self):
        mountinfo = "1 0 0:1 / / rw - ext4 /dev/root rw\n2 1 0:2 / /cg rw - cgroup2 cgroup rw\n3 2 0:3 / /cg/other rw - tmpfs tmpfs rw\n"
        with patch.object(p, "_read", return_value=mountinfo):
            self.assertEqual(p._cgroup2_mount(Path("/cg/delegated")), "/cg")
            with self.assertRaises(p.ObservationError):
                p._cgroup2_mount(Path("/cg/other/fake"))

    def test_missing_cgroup_kill_is_explicit_and_does_not_fallback(self):
        with self.cgroup_fixture(omit=("cgroup.kill",)) as (root, _):
            context = p.prepare_isolation(memory_max_bytes=4096, cgroup_root=root)
            with self.assertRaisesRegex(p.ObservationError, "cgroup.kill"):
                context.kill()
            self.assertTrue(context.finalize()["cleanup_complete"])


class SupervisorAffinityTests(unittest.TestCase):
    def test_disabled_scope_is_noop_on_darwin(self):
        with patch.object(p.sys, "platform", "darwin"), patch.object(p.os, "sched_setaffinity", create=True) as setter:
            with p.scoped_supervisor_affinity() as receipt:
                self.assertIsNone(receipt["requested"])
        self.assertTrue(receipt["restored"])
        setter.assert_not_called()

    def test_success_restores_original_mask_and_mutates_receipt(self):
        with patch.object(p.sys, "platform", "linux"), \
             patch.object(p.os, "sched_getaffinity", side_effect=[{0, 1, 2}, {1, 2}, {0, 1, 2}], create=True), \
             patch.object(p.os, "sched_setaffinity", create=True) as setter:
            with p.scoped_supervisor_affinity("1-2") as receipt:
                self.assertEqual(receipt["before"], [0, 1, 2])
                self.assertEqual(receipt["effective"], [1, 2])
                self.assertFalse(receipt["restored"])
            self.assertTrue(receipt["restored"])
            self.assertEqual(receipt["restored_mask"], [0, 1, 2])
        self.assertEqual(setter.call_args_list[0].args, (0, [1, 2]))
        self.assertEqual(setter.call_args_list[1].args, (0, {0, 1, 2}))

    def test_body_failure_still_restores_and_preserves_original_exception(self):
        with patch.object(p.sys, "platform", "linux"), \
             patch.object(p.os, "sched_getaffinity", side_effect=[{0, 1}, {1}, {0, 1}], create=True), \
             patch.object(p.os, "sched_setaffinity", create=True):
            with self.assertRaisesRegex(ValueError, "work failed"):
                with p.scoped_supervisor_affinity([1]) as receipt:
                    raise ValueError("work failed")
        self.assertTrue(receipt["restored"])

    def test_restore_failure_is_reported_and_raised(self):
        with patch.object(p.sys, "platform", "linux"), \
             patch.object(p.os, "sched_getaffinity", side_effect=[{0, 1}, {1}], create=True), \
             patch.object(p.os, "sched_setaffinity", side_effect=[None, PermissionError("restore denied")], create=True):
            with self.assertRaisesRegex(p.ObservationError, "restore denied"):
                with p.scoped_supervisor_affinity([1]) as receipt:
                    pass
        self.assertFalse(receipt["restored"])
        self.assertIn("restore denied", receipt["error"])

    def test_setup_verification_failure_still_restores(self):
        with patch.object(p.sys, "platform", "linux"), \
             patch.object(p.os, "sched_getaffinity", side_effect=[{0, 1}, {0}, {0, 1}], create=True), \
             patch.object(p.os, "sched_setaffinity", create=True) as setter:
            with self.assertRaisesRegex(p.ObservationError, "differs"):
                with p.scoped_supervisor_affinity([1]):
                    self.fail("work must not execute after verification failure")
        self.assertEqual(setter.call_count, 2)
        self.assertEqual(setter.call_args.args, (0, {0, 1}))

    def test_requested_scope_rejects_wrong_platform_thread_and_expansion(self):
        with patch.object(p.sys, "platform", "darwin"):
            with self.assertRaisesRegex(p.ObservationError, "only on Linux"):
                with p.scoped_supervisor_affinity([0]):
                    pass
        with patch.object(p.sys, "platform", "linux"), patch.object(p.threading, "current_thread", return_value=object()):
            with self.assertRaisesRegex(p.ObservationError, "main thread"):
                with p.scoped_supervisor_affinity([0]):
                    pass
        with patch.object(p.sys, "platform", "linux"), \
             patch.object(p.os, "sched_getaffinity", return_value={0}, create=True), \
             patch.object(p.os, "sched_setaffinity", create=True) as setter:
            with self.assertRaisesRegex(p.ObservationError, "inherited"):
                with p.scoped_supervisor_affinity([1]):
                    pass
        setter.assert_not_called()


if __name__ == "__main__":
    unittest.main()
