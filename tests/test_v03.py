import os
import tempfile
import unittest

from diskmd import integrity, link
from diskmd.analyze import from_smartctl, OK, WATCH
from diskmd.render import used_report
from test_analyze import nvme, ata, lb


def write(path, text):
    with open(path, "w") as f:
        f.write(text)


class UsbLink(unittest.TestCase):
    def sysblock(self, speed):
        """Fake /sys tree: block/sdx -> devices/usb1/1-2/.../block/sdx with speed+busnum at the USB device."""
        root = tempfile.mkdtemp()
        usbdev = os.path.join(root, "devices", "usb1", "1-2")
        leaf = os.path.join(usbdev, "1-2:1.0", "host6", "block", "sdx")
        os.makedirs(leaf)
        for f, v in (("speed", str(speed)), ("busnum", "1")):
            write(os.path.join(usbdev, f), v + "\n")
        os.makedirs(os.path.join(root, "block"))
        os.symlink(leaf, os.path.join(root, "block", "sdx"))
        return os.path.join(root, "block")

    def test_ssd_on_usb2_is_flagged(self):
        r = link.usb("sdx", "ssd", self.sysblock(480))
        self.assertEqual(r["summary"], "USB 2.0 (480 Mbps)")
        self.assertEqual(r["issues"][0][0], WATCH)

    def test_hdd_on_usb2_is_only_a_note(self):
        r = link.usb("sdx", "hdd", self.sysblock(480))
        self.assertEqual((r["issues"], len(r["notes"])), ([], 1))

    def test_usb3_is_fine(self):
        r = link.usb("sdx", "nvme", self.sysblock(5000))
        self.assertEqual((r["summary"], r["issues"], r["notes"]), ("USB 3.0 (5 Gbps)", [], []))

    def test_unknown_device_returns_none(self):
        self.assertIsNone(link.usb("nope", "ssd", self.sysblock(5000)))


class PcieLink(unittest.TestCase):
    def ctrl(self, cs, cw, ms="16.0 GT/s PCIe", mw=4):
        root = tempfile.mkdtemp()
        dev = os.path.join(root, "nvme0", "device")
        os.makedirs(dev)
        for f, v in (("current_link_speed", cs), ("current_link_width", cw),
                     ("max_link_speed", ms), ("max_link_width", mw)):
            write(os.path.join(dev, f), f"{v}\n")
        return root

    def test_full_speed(self):
        r = link.nvme("nvme0n1", self.ctrl("16.0 GT/s PCIe", 4))
        self.assertEqual((r["summary"], r["issues"], r["notes"]), ("PCIe Gen4 x4", [], []))

    def test_narrow_link_flagged(self):
        r = link.nvme("nvme0n1", self.ctrl("16.0 GT/s PCIe", 2))
        self.assertIn("x2 but this drive supports x4", r["issues"][0][1])

    def test_lower_gen_is_only_a_note(self):
        r = link.nvme("nvme0n1", self.ctrl("8.0 GT/s PCIe", 4))
        self.assertEqual((r["issues"], len(r["notes"])), ([], 1))

    def test_missing_sysfs(self):
        self.assertIsNone(link.nvme("nvme9n1", tempfile.mkdtemp()))


class SataLink(unittest.TestCase):
    def j(self, cur, mx):
        mk = lambda v: {"string": f"{v} Gb/s"}
        return {"interface_speed": {"current": mk(cur), "max": mk(mx)}}

    def test_ssd_below_max_flagged(self):
        self.assertEqual(link.sata(self.j("3.0", "6.0"), "ssd")["issues"][0][0], WATCH)

    def test_old_hdd_at_its_max_ok(self):
        self.assertEqual(link.sata(self.j("3.0", "3.0"), "hdd")["issues"], [])

    def test_hdd_at_3gbps_on_6gbps_port_ok(self):
        self.assertEqual(link.sata(self.j("3.0", "6.0"), "hdd")["issues"], [])

    def test_no_data(self):
        self.assertIsNone(link.sata({}, "ssd"))


def _named(d, name):
    d.name = name
    return d


class Integrity(unittest.TestCase):
    def test_real_drives_are_clean(self):
        # numbers from the maintainer's actual drives must not trigger anything
        d = from_smartctl(lb(), nvme())            # 87 TB / 9,697 h, 1575 unsafe of 4637 cycles
        self.assertEqual(d.integrity, [])

    def test_selftest_hours_beyond_poweron_flags_reset(self):
        j = ata({5: 0})
        j["ata_smart_self_test_log"] = {"standard": {"table": [
            {"type": {"string": "Short"}, "lifetime_hours": 30000, "status": {"passed": True, "string": "ok"}}]}}
        d = from_smartctl(lb("sata"), j)           # power-on hours = 15,860
        self.assertTrue(any("reset or rolled back" in t for t in d.integrity))
        self.assertEqual(d.level, WATCH)

    def test_nvme_busy_time_impossible(self):
        d = from_smartctl(lb(), nvme(power_on_hours=100, controller_busy_time=50_000))
        self.assertTrue(any("busy minutes" in t for t in d.integrity))

    def test_implausible_write_rate(self):
        d = from_smartctl(lb(), nvme(power_on_hours=10, data_units_written=500_000_000))   # ~256 TB in 10 h
        self.assertTrue(any("not plausible" in t for t in d.integrity))

    def test_unsafe_exceeding_cycles(self):
        d = from_smartctl(lb(), nvme(unsafe_shutdowns=900, power_cycles=100))
        self.assertTrue(any("don't agree" in t for t in d.integrity))

    def test_wear_without_hours(self):
        d = from_smartctl(lb(), nvme(percentage_used=12, power_on_hours=20, power_cycles=30, unsafe_shutdowns=1))
        self.assertTrue(any("too low for the wear" in t for t in d.integrity))

    def test_brand_new_drive_is_clean(self):
        d = from_smartctl(lb(), nvme(percentage_used=0, power_on_hours=3, power_cycles=5, unsafe_shutdowns=0,
                                     data_units_written=2000))
        self.assertEqual(d.integrity, [])

    def test_report_notes_are_separate_markdown_blocks(self):
        from diskmd.render import markdown_report
        a = from_smartctl(lb("usb"), nvme())          # USB drive with a note
        a.name = "sdc"
        b = from_smartctl(lb("sata"), ata({197: 3}))   # drive with an issue
        b.name = "sdb"
        md = markdown_report([a, b])
        lines = md.splitlines()
        i = lines.index("**sdb** (TestHDD)")
        self.assertEqual(lines[i - 1], "")             # blank line before a drive heading, so it isn't
        self.assertEqual(lines[i + 1], "")             # swallowed by the previous bullet
        self.assertTrue(md.endswith("\n") and not md.endswith("\n\n"))

    def test_summary_line(self):
        from diskmd.render import summary_line
        ok = lambda n: _named(from_smartctl(lb(), nvme()), n)
        watch = _named(from_smartctl(lb("sata"), ata({5: 2})), "sde")          # WATCH
        warn = _named(from_smartctl(lb("sata"), ata({197: 3})), "sdb")         # WARN
        self.assertEqual(summary_line([ok("a"), ok("b")]), "2 drives checked - all healthy.")
        self.assertEqual(summary_line([ok("a")]), "1 drive checked - all healthy.")
        self.assertEqual(summary_line([ok("a"), watch, warn]),
                         "3 drives checked: 1 healthy, 1 warning (sdb), 1 to watch (sde).")
        self.assertEqual(summary_line([warn]), "1 drive checked: 1 warning (sdb).")

    def test_report_has_connection_column_and_summary(self):
        from diskmd.render import markdown_report
        from diskmd import link
        d = _named(from_smartctl(lb(), nvme()), "nvme0n1")
        d.link = {"summary": "PCIe Gen4 x4"}
        md = markdown_report([d, _named(from_smartctl(lb("sata"), ata({5: 0})), "sda")])
        lines = md.splitlines()
        self.assertEqual(lines[3], "**2 drives checked - all healthy.**")
        self.assertIn("| Connection |", md)
        self.assertIn("| nvme0n1 | TestNVMe | NVMe | PCIe Gen4 x4 |", md)
        self.assertIn("| sda | TestHDD | HDD | - |", md)          # no link info -> dash, not a crash

    def test_used_report_wording(self):
        good = from_smartctl(lb(), nvme())
        bad = from_smartctl(lb(), nvme(power_on_hours=100, controller_busy_time=50_000))
        text = used_report([good, bad], color=False)
        self.assertIn("no signs of reset", text)
        self.assertIn("signals, not proof", text)


if __name__ == "__main__":
    unittest.main()
