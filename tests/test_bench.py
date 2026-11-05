import json
import os
import stat
import tempfile
import time
import unittest
from unittest import mock

from diskmd import bench, probe

FIO_JSON = {"jobs": [{"read": {"bw_bytes": 3_200_000_000, "iops": 3050.0, "lat_ns": {"mean": 2_500_000.0}},
                      "write": {"bw_bytes": 2_100_000_000, "iops": 2002.0, "clat_ns": {"mean": 4_000_000.0}}}]}

FAKE_FIO = '''#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
get = lambda k: next(a.split("=", 1)[1] for a in args if a.startswith("--" + k + "="))
if "--direct=1" in args and os.environ.get("FAKE_NO_DIRECT"):
    sys.stderr.write("fio: Invalid argument\\n"); sys.exit(1)
if os.environ.get("FAKE_FAIL"):
    sys.exit(1)
open(get("filename"), "w").write("x")          # like fio laying out its test file
print("some banner line before the json")      # fio can print stray text first
print(json.dumps(%r))
''' % FIO_JSON


def fake_fio(directory):
    path = os.path.join(directory, "fakefio")
    with open(path, "w") as f:
        f.write(FAKE_FIO)
    os.chmod(path, os.stat(path).st_mode | stat.S_IEXEC)
    return path


class Parse(unittest.TestCase):
    def test_read_and_write(self):
        self.assertEqual(bench.parse_fio(json.dumps(FIO_JSON), False),
                         {"mbps": 3200.0, "iops": 3050, "lat_us": 2500.0})
        w = bench.parse_fio(json.dumps(FIO_JSON), True)
        self.assertEqual((w["mbps"], w["lat_us"]), (2100.0, 4000.0))     # falls back to clat_ns

    def test_command_uses_kdiskmark_profiles_and_never_a_raw_device(self):
        cmd = bench.fio_command("fio", "/mnt/x/.b/testfile", bench.PROFILES[2], True, 1024)
        self.assertIn("--rw=randwrite", cmd)
        self.assertIn("--bs=4k", cmd)
        self.assertIn("--iodepth=32", cmd)
        self.assertIn("--numjobs=16", cmd)
        self.assertIn("--runtime=10", cmd)
        self.assertFalse(any(a.startswith("--filename=/dev/") for a in cmd))

    def test_direct_flag(self):
        self.assertIn("--direct=0", bench.fio_command("fio", "/t", bench.PROFILES[0], False, 256, direct=False))


class PickDir(unittest.TestCase):
    def test_prefers_writable_mount_on_same_device(self):
        d = tempfile.mkdtemp()
        self.assertEqual(bench.pick_dir([d]), d)

    def test_none_when_nothing_writable(self):
        self.assertIsNone(bench.pick_dir(["/definitely/not/mounted"]))


class StartRules(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.fio = fake_fio(self.tmp)
        self.b = bench.Bench(fio=self.fio)
        self.patches = [mock.patch.object(probe, "list_disks", return_value=[{"name": "sdx", "serial": "S1"}]),
                        mock.patch.object(probe, "partitions", return_value={"sdx": [{"mounts": [self.tmp]}]})]
        for p in self.patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in self.patches])

    def test_rejects_bad_size(self):
        self.assertFalse(self.b.start("sdx", 12345)["ok"])

    def test_rejects_unknown_disk(self):
        self.assertFalse(self.b.start("sdy", 1024)["ok"])

    def test_rejects_when_fio_missing(self):
        r = bench.Bench(fio="/no/such/fio").start("sdx", 1024)
        self.assertFalse(r["ok"])
        self.assertIn("fio is not installed", r["message"])

    def test_rejects_unmounted_drive(self):
        with mock.patch.object(probe, "partitions", return_value={"sdx": [{"mounts": []}]}):
            r = self.b.start("sdx", 1024)
        self.assertIn("no mounted filesystem", r["message"])

    def test_rejects_insufficient_space(self):
        with mock.patch("shutil.disk_usage", return_value=mock.Mock(free=10 * 2**20)):
            r = self.b.start("sdx", 1024)
        self.assertIn("not enough free space", r["message"])


class FullRun(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.data = tempfile.mkdtemp()
        env = mock.patch.dict(os.environ, {"DISKMD_DATA": self.data})
        env.start()
        self.addCleanup(env.stop)
        self.b = bench.Bench(fio=fake_fio(self.tmp))
        for p in (mock.patch.object(probe, "list_disks", return_value=[{"name": "sdx", "serial": "S1"}]),
                  mock.patch.object(probe, "partitions", return_value={"sdx": [{"mounts": [self.tmp]}]})):
            p.start()
            self.addCleanup(p.stop)

    def wait(self):
        for _ in range(100):
            if not self.b.status()["running"]:
                return self.b.status()
            time.sleep(0.1)
        self.fail("benchmark never finished")

    def leftovers(self):
        return [n for n in os.listdir(self.tmp) if n.startswith(".diskmd-bench")]

    def test_complete_run_saves_history_and_cleans_up(self):
        self.assertTrue(self.b.start("sdx", 256)["ok"])
        s = self.wait()
        self.assertEqual((len(s["results"]), s["error"], s["step"]), (8, None, 8))
        self.assertEqual({r["label"] for r in s["results"]}, {p[0] for p in bench.PROFILES})
        self.assertEqual(self.leftovers(), [])                       # temp file removed
        past = bench.past_results("sdx")
        self.assertEqual((len(past), past[0]["size_mb"]), (1, 256))

    def test_direct_io_fallback_adds_note(self):
        with mock.patch.dict(os.environ, {"FAKE_NO_DIRECT": "1"}):
            self.b.start("sdx", 256)
            s = self.wait()
        self.assertEqual(len(s["results"]), 8)
        self.assertIn("direct I/O", s["note"])

    def test_fio_failure_reports_error_and_still_cleans_up(self):
        with mock.patch.dict(os.environ, {"FAKE_FAIL": "1"}):
            self.b.start("sdx", 256)
            s = self.wait()
        self.assertIn("fio failed", s["error"])
        self.assertEqual(self.leftovers(), [])
        self.assertEqual(bench.past_results("sdx"), [])               # failed runs aren't saved

    def test_second_start_while_running_is_refused(self):
        self.b.state["running"] = True
        self.assertIn("already running", self.b.start("sdx", 256)["message"])


class Demo(unittest.TestCase):
    def test_demo_runs_without_fio_or_disks(self):
        b = bench.Bench(fio="/no/such/fio", demo=True)
        self.assertTrue(b.start("nvme0n1", 1024)["ok"])
        for _ in range(80):
            if not b.status()["running"]:
                break
            time.sleep(0.1)
        self.assertEqual(len(b.status()["results"]), 8)


if __name__ == "__main__":
    unittest.main()
