import time
import unittest

from diskmd import alerts, history
from diskmd.analyze import from_smartctl, OK, WATCH, WARN
from diskmd.render import markdown_report
from test_analyze import nvme, ata, lb


def rec(d, **over):
    r = {"key": history.key(d), "ts": time.time() - 86400, "level": OK,
         **{f: getattr(d, f) for f in history.WATCHED}}
    r.update(over)
    return r


class Alerts(unittest.TestCase):
    def test_quiet_when_nothing_changed(self):
        d = from_smartctl(lb(), nvme())
        self.assertEqual(alerts.find([d], {history.key(d): rec(d)}), [])

    def test_unsafe_shutdowns_and_wear_never_alert(self):
        d = from_smartctl(lb(), nvme())
        old = rec(d, unsafe_shutdowns=d.unsafe_shutdowns - 50, wear_pct=d.wear_pct - 1)
        self.assertEqual(alerts.find([d], {history.key(d): old}), [])

    def test_new_bad_sectors_alert(self):
        d = from_smartctl(lb("sata"), ata({5: 12}))
        found = alerts.find([d], {history.key(d): rec(d, reallocated=4)})
        self.assertEqual(len(found), 1)
        self.assertIn("+8 reallocated sectors", found[0][2][0])

    def test_level_getting_worse_alerts_once(self):
        d = from_smartctl(lb("sata"), ata({197: 3}))           # WARN
        first = alerts.find([d], {history.key(d): rec(d, level=OK, pending=3)})
        self.assertEqual(len(first), 1)
        again = alerts.find([d], {history.key(d): rec(d, level=WARN, pending=3)})
        self.assertEqual(again, [])                             # already known: don't nag daily

    def test_new_drive_alerts_only_if_already_bad(self):
        good = from_smartctl(lb(), nvme())
        self.assertEqual(alerts.find([good], {}), [])
        bad = from_smartctl(lb("sata"), ata({197: 3}))
        self.assertEqual(len(alerts.find([bad], {})), 1)
        watch = from_smartctl(lb("sata"), ata({5: 2}))           # WATCH on first sight: stay quiet
        self.assertEqual(alerts.find([watch], {}), [])


class Trend(unittest.TestCase):
    def test_trend_needs_enough_time_and_growth(self):
        d = from_smartctl(lb(), nvme(percentage_used=12))
        old = lambda days, wear: [{"ts": time.time() - days * 86400, "wear_pct": wear}]
        self.assertIsNone(history.trend_years_left(d, old(3, 10)))     # too recent
        self.assertIsNone(history.trend_years_left(d, old(60, 12)))    # no wear gained
        y = history.trend_years_left(d, old(100, 10))                  # 2% in 100 days
        self.assertAlmostEqual(y, 88 / (2 / 100) / 365, places=3)

    def test_series_appends_current_point(self):
        d = from_smartctl(lb(), nvme())
        self.assertEqual(len(history.series(d, [rec(d)])), 2)


class Report(unittest.TestCase):
    def test_report_has_no_serials(self):
        j = nvme()
        j["serial_number"] = "SECRET-SERIAL-123"
        d = from_smartctl(lb(), j)
        md = markdown_report([d])
        self.assertNotIn("SECRET-SERIAL-123", md)
        self.assertIn("| x | TestNVMe | NVMe |", md)


if __name__ == "__main__":
    unittest.main()
