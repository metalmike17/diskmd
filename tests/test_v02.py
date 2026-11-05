import unittest
from unittest import mock

from diskmd import alerts, history, kernel, probe
from diskmd.analyze import from_smartctl, OK, WATCH, WARN
from test_analyze import nvme, ata, lb


def ssd(named, lbs=512):
    """SATA SSD with named attributes: {id: (name, value, raw)}"""
    t = [{"id": i, "name": n, "value": v, "raw": {"value": r}} for i, (n, v, r) in named.items()]
    return {"model_name": "TestSSD", "rotation_rate": 0, "smart_status": {"passed": True},
            "logical_block_size": lbs, "ata_smart_attributes": {"table": t}}


class VendorDecoding(unittest.TestCase):
    def test_crucial_style_wear_and_lbas(self):
        d = from_smartctl(lb("sata"), ssd({202: ("Percent_Lifetime_Remain", 87, 13),
                                           246: ("Total_LBAs_Written", 100, 2_000_000_000)}))
        self.assertEqual(d.wear_pct, 13)
        self.assertAlmostEqual(d.written_tb, 2_000_000_000 * 512 / 1e12)

    def test_intel_style_32mib_writes(self):
        d = from_smartctl(lb("sata"), ssd({233: ("Media_Wearout_Indicator", 99, 0),
                                           241: ("Host_Writes_32MiB", 100, 30_000)}))
        self.assertEqual(d.wear_pct, 1)
        self.assertAlmostEqual(d.written_tb, 30_000 * 32 * 2**20 / 1e12)

    def test_id_alone_is_not_trusted(self):
        # 231 is a temperature on some vendors: an unrecognised name must NOT be read as wear
        d = from_smartctl(lb("sata"), ssd({231: ("Temperature_Celsius", 40, 40)}))
        self.assertIsNone(d.wear_pct)

    def test_ssd_without_wear_data_says_so(self):
        d = from_smartctl(lb("usb"), ssd({169: ("Unknown_JMF_Attribute", 91, 0)}))
        self.assertTrue(any("doesn't report wear" in n for n in d.notes))


SAMPLE = """\
blk_update_request: I/O error, dev sdb, sector 123456 op 0x0:(READ) flags 0x0 phys_seg 1 prio class 2
Buffer I/O error on dev sdb1, logical block 15432, async page read
ata5: hard resetting link
ata5.00: exception Emask 0x10 SAct 0x0 SErr 0x4050000 action 0xe frozen
ata7: hard resetting link
nvme nvme0: I/O 12 QID 3 timeout, aborting
usb 4-2: reset SuperSpeed USB device number 4 using xhci_hcd
usb 4-9: reset SuperSpeed USB device number 7 using xhci_hcd
EXT4-fs error (device sdd1): ext4_find_entry:1455: inode #2: comm ls: reading directory lblock 0
ata5: SATA link up 6.0 Gbps (SStatus 133 SControl 300)
""".splitlines()


class KernelParse(unittest.TestCase):
    def setUp(self):
        self.ev = kernel.parse(SAMPLE, {"ata5": "sda"}, {"4-2": "sdc"})

    def test_io_errors_map_partitions_to_disks(self):
        self.assertEqual(self.ev["sdb"]["io"], 2)
        self.assertEqual(self.ev["sdd"]["io"], 1)          # filesystem error on sdd1

    def test_link_resets_map_via_ata_and_usb(self):
        self.assertEqual(self.ev["sda"]["link"], 2)
        self.assertEqual(self.ev["sdc"]["link"], 1)

    def test_unmapped_ports_and_normal_link_up_ignored(self):
        self.assertNotIn("ata7", str(self.ev))
        self.assertEqual(sum(e["link"] for k, e in self.ev.items() if k.startswith("sd")), 3)

    def test_nvme_controller_events_reach_namespaces(self):
        d = from_smartctl({"name": "nvme0n1", "tran": "nvme", "size": "1"}, nvme())
        kernel.attach([d], self.ev)
        self.assertEqual(d.link_resets, 1)

    def test_attach_levels(self):
        internal = from_smartctl(lb("sata"), ata({5: 0}))
        internal.name = "sdb"
        usb = from_smartctl(lb("usb"), ata({5: 0}))
        usb.name = "sdd"
        kernel.attach([internal, usb], self.ev)
        self.assertEqual(internal.level, WARN)              # internal drive: I/O errors are serious
        self.assertEqual(usb.level, WATCH)                  # one error on a USB drive: just watch it

    def test_disk_of(self):
        self.assertEqual(kernel.disk_of("nvme0n1p3"), "nvme0n1")
        self.assertEqual(kernel.disk_of("sda12"), "sda")
        self.assertEqual(kernel.disk_of("sdb"), "sdb")


class SelfTest(unittest.TestCase):
    def test_ata_last_result_and_age(self):
        j = ata({5: 0})
        j["ata_smart_data"] = {"self_test": {"polling_minutes": {"short": 2, "extended": 400}}}
        j["ata_smart_self_test_log"] = {"standard": {"table": [
            {"type": {"string": "Short offline"}, "lifetime_hours": 15800,
             "status": {"string": "Completed without error", "passed": True}}]}}
        d = from_smartctl(lb("sata"), j)
        self.assertEqual(d.selftest["minutes"], {"short": 2, "long": 400})
        self.assertEqual(d.selftest["last"]["hours_ago"], 60)
        self.assertEqual(d.level, OK)

    def test_failed_selftest_warns(self):
        j = ata({5: 0})
        j["ata_smart_self_test_log"] = {"standard": {"table": [
            {"type": {"string": "Extended offline"}, "lifetime_hours": 1,
             "status": {"string": "Completed: read failure", "passed": False}}]}}
        self.assertEqual(from_smartctl(lb("sata"), j).level, WARN)

    def test_nvme_selftest(self):
        j = nvme()
        j["nvme_self_test_log"] = {"current_self_test_operation": {"value": 1},
                                   "current_self_test_completion_percent": 30,
                                   "table": [{"self_test_code": {"string": "Short"},
                                              "self_test_result": {"string": "Completed without error", "value": 0},
                                              "power_on_hours": 9000}]}
        d = from_smartctl(lb(), j)
        self.assertEqual(d.selftest["running"], 70)
        self.assertTrue(d.selftest["last"]["passed"])

    def test_unsupported_drive_has_no_selftest(self):
        self.assertIsNone(from_smartctl(lb("sata"), ata({5: 0})).selftest)

    def test_malformed_log_does_not_crash(self):
        j = ata({5: 0})
        j["ata_smart_self_test_log"] = {"standard": {"table": [None]}}
        self.assertIsNone(from_smartctl(lb("sata"), j).selftest)


class StartSelfTest(unittest.TestCase):
    def test_rejects_unknown_device_and_type(self):
        with mock.patch.object(probe, "list_disks", return_value=[{"name": "sda", "tran": "sata"}]):
            self.assertFalse(probe.start_selftest("sda; rm -rf /", "short")["ok"])
            self.assertFalse(probe.start_selftest("../../etc/passwd", "short")["ok"])
            self.assertFalse(probe.start_selftest("sda", "offline-destructive")["ok"])

    def test_never_runs_smartctl_for_rejected_input(self):
        with mock.patch.object(probe, "list_disks", return_value=[]), \
             mock.patch.object(probe, "_run") as run:
            probe.start_selftest("sdz", "short")
            run.assert_not_called()


class IoErrorAlerts(unittest.TestCase):
    def test_new_io_errors_alert(self):
        d = from_smartctl(lb("sata"), ata({5: 0}))
        d.io_errors = 4
        prev = {"key": history.key(d), "ts": 0, "level": OK, "io_errors": 0}
        found = alerts.find([d], {history.key(d): prev})
        self.assertIn("+4 kernel I/O errors", found[0][2][0])


if __name__ == "__main__":
    unittest.main()
