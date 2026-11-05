"""Sample drives for --demo (screenshots, trying the GUI without root)."""
from . import link
from .analyze import from_smartctl, apply_link


def _nvme(model, **log):
    base = dict(critical_warning=0, temperature=38, available_spare=100, available_spare_threshold=10,
                percentage_used=2, data_units_written=60_000_000, unsafe_shutdowns=12, media_errors=0,
                power_cycles=900, power_on_hours=4200)
    base.update(log)
    return {"model_name": model, "serial_number": model, "smart_status": {"passed": True},
            "nvme_self_test_log": {"current_self_test_operation": {"value": 0}, "table": [
                {"self_test_code": {"string": "Short"}, "self_test_result": {"string": "Completed without error", "value": 0},
                 "power_on_hours": base["power_on_hours"] - 70}]},
            "nvme_smart_health_information_log": base}


def _hdd(model, hours, realloc=0, pending=0):
    t = [{"id": i, "name": n, "value": 100, "raw": {"value": v}} for i, n, v in
         [(5, "Reallocated_Sector_Ct", realloc), (197, "Current_Pending_Sector", pending),
          (199, "UDMA_CRC_Error_Count", 0)]]
    return {"model_name": model, "serial_number": model, "rotation_rate": 7200, "smart_status": {"passed": True},
            "power_on_time": {"hours": hours}, "temperature": {"current": 34},
            "ata_smart_data": {"self_test": {"polling_minutes": {"short": 2, "extended": 410}}},
            "ata_smart_self_test_log": {"standard": {"table": [
                {"type": {"string": "Short offline"}, "lifetime_hours": hours - 40,
                 "status": {"string": "Completed without error", "passed": True}}]}},
            "ata_smart_attributes": {"table": t}}


def drives():
    spec = [
        ("nvme0n1", "nvme", "Samsung 990 PRO 2TB", _nvme("Samsung 990 PRO 2TB", percentage_used=3)),
        ("nvme1n1", "nvme", "WD Black SN850X 1TB", _nvme("WD Black SN850X 1TB", percentage_used=47,
                                                       temperature=52, unsafe_shutdowns=640, power_cycles=1800,
                                                       data_units_written=900_000_000, power_on_hours=11000)),
        ("sda", "sata", "Seagate Barracuda 4TB", _hdd("Seagate Barracuda 4TB", 31000, realloc=8)),
        ("sdb", "usb", "WD Elements 2TB", _hdd("WD Elements 2TB", 9000, pending=3)),
    ]
    sizes = {"nvme0n1": 2000, "nvme1n1": 1000, "sda": 4000, "sdb": 2000}
    ds = [from_smartctl({"name": n, "tran": t, "size": str(sizes[n] * 10**9)}, j) for n, t, _, j in spec]
    links = {"nvme0n1": link._result("PCIe Gen4 x4"),
             "nvme1n1": link._result("PCIe Gen4 x2", [(link.WATCH, "Running at x2 but this drive supports x4 - it is "
                                                       "getting about 50% of its possible bandwidth. Check the M.2 slot "
                                                       "(some share lanes with other slots or SATA ports).")]),
             "sda": link._result("SATA 6 Gbps"),
             "sdb": link._result("USB 2.0 (480 Mbps)", notes=["Connected at USB 2.0 (480 Mbps); a USB 3 port would "
                                                              "roughly double this drive's transfer speed."])}
    GB = 10**9
    fw = {"nvme0n1": "4B2QJXD7", "nvme1n1": "611110WD", "sda": "CC51", "sdb": "01.01A01"}
    layout = {"nvme0n1": [("nvme0n1p1", 1 * GB, "vfat", "EFI", ["/boot/efi"], 0.1 * GB), ("nvme0n1p2", 1999 * GB, "btrfs", "root", ["/", "/home"], 640 * GB)],
              "nvme1n1": [("nvme1n1p1", 1000 * GB, "ext4", "games", ["/mnt/games"], 710 * GB)],
              "sda": [("sda1", 4000 * GB, "ntfs", "storage", ["/mnt/storage"], 2900 * GB)],
              "sdb": [("sdb1", 2000 * GB, "exfat", "Backup", ["/run/media/you/Backup"], 1100 * GB)]}
    for d in ds:
        apply_link(d, links[d.name])
        d.firmware = fw[d.name]
        d.serial = "DEMO-" + d.name.upper() + "-0000"
        d.partitions = [{"name": n, "size": int(sz), "fstype": f, "label": lb, "mounts": m, "used": int(u),
                         "free": int(sz - u)} for n, sz, f, lb, m, u in layout[d.name]]
    return ds


def history_records(drives_):
    """Fake 30-day history so the GUI shows sparklines and a trend in --demo."""
    import random, time
    from . import history
    rnd, now, out = random.Random(7), time.time(), {}
    for d in drives_:
        base = d.temp_c or 35
        out[history.key(d)] = [
            {"key": history.key(d), "ts": now - (30 - i) * 86400, "temp_c": base + rnd.randint(-4, 4),
             "wear_pct": None if d.wear_pct is None else max(0, d.wear_pct - (30 - i) // 12),
             "written_tb": None} for i in range(0, 30, 3)]
    return out
