import unittest

from diskmd.analyze import from_smartctl, OK, WATCH, WARN, FAIL


def nvme(**over):
    log = dict(critical_warning=0, temperature=36, available_spare=100, available_spare_threshold=10,
               percentage_used=10, data_units_written=170_281_325, unsafe_shutdowns=1575,
               media_errors=0, power_cycles=4637, power_on_hours=9697)
    log.update(over)
    return {"model_name": "TestNVMe", "smart_status": {"passed": True}, "nvme_smart_health_information_log": log}


def ata(attrs, rotation=7200, passed=True):
    table = [{"id": i, "name": "x", "value": 100, "raw": {"value": v}} for i, v in attrs.items()]
    return {"model_name": "TestHDD", "rotation_rate": rotation, "smart_status": {"passed": passed},
            "power_on_time": {"hours": 15860}, "ata_smart_attributes": {"table": table}}


def old_hdd():
    """Old drive: no rotation_rate in smartctl output, but spin-related attributes."""
    j = ata({3: 5175, 4: 3851, 5: 0})
    del j["rotation_rate"]
    for a in j["ata_smart_attributes"]["table"]:
        a["name"] = {3: "Spin_Up_Time", 4: "Start_Stop_Count", 5: "Reallocated_Sector_Ct"}[a["id"]]
    return j


def lb(tran="nvme"):
    return {"name": "x", "tran": tran, "size": "1000000000000"}


class T(unittest.TestCase):
    def test_healthy_nvme(self):
        d = from_smartctl(lb(), nvme())
        self.assertEqual(d.level, OK)
        self.assertAlmostEqual(d.written_tb, 87.1, delta=0.2)
        self.assertTrue(1 < d.years_left < 15)

    def test_unsafe_shutdown_note_internal_vs_usb(self):
        self.assertTrue(from_smartctl(lb("nvme"), nvme()).notes)
        usb = from_smartctl(lb("usb"), nvme())
        self.assertIn("external", usb.notes[0])

    def test_media_errors_warn(self):
        self.assertEqual(from_smartctl(lb(), nvme(media_errors=3)).level, WARN)

    def test_low_spare_warn(self):
        self.assertEqual(from_smartctl(lb(), nvme(available_spare=8)).level, WARN)

    def test_critical_warning_fail(self):
        self.assertEqual(from_smartctl(lb(), nvme(critical_warning=1)).level, FAIL)

    def test_clean_hdd(self):
        d = from_smartctl(lb("sata"), ata({5: 0, 197: 0, 198: 0, 199: 0}))
        self.assertEqual((d.kind, d.level), ("hdd", OK))

    def test_pending_sectors_warn(self):
        self.assertEqual(from_smartctl(lb("sata"), ata({197: 4})).level, WARN)

    def test_few_reallocated_watch_and_crc_watch(self):
        self.assertEqual(from_smartctl(lb("sata"), ata({5: 2})).level, WATCH)
        self.assertEqual(from_smartctl(lb("sata"), ata({199: 9})).level, WATCH)

    def test_failed_selfassessment(self):
        self.assertEqual(from_smartctl(lb("sata"), ata({}, passed=False)).level, FAIL)




class HddRetract(unittest.TestCase):
    def test_hdd_ignores_attr_192(self):
        d = from_smartctl(lb("sata"), ata({192: 139}))
        self.assertIsNone(d.unsafe_shutdowns)

    def test_ssd_uses_attr_192(self):
        d = from_smartctl(lb("sata"), ata({192: 7}, rotation=0))
        self.assertEqual(d.unsafe_shutdowns, 7)


class Classify(unittest.TestCase):
    def test_old_hdd_without_rotation_rate(self):
        self.assertEqual(from_smartctl(lb("sata"), old_hdd()).kind, "hdd")

    def test_usb_ssd_without_rotation_rate(self):
        j = ata({3: 0, 5: 0})
        del j["rotation_rate"]
        for a in j["ata_smart_attributes"]["table"]:
            a["name"] = "Unknown_JMF_Attribute" if a["id"] == 3 else "Reallocated_Sector_Ct"
        self.assertEqual(from_smartctl(lb("usb"), j).kind, "ssd")


if __name__ == "__main__":
    unittest.main()
