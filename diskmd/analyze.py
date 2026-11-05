"""Turn raw smartctl JSON into a normalized Drive plus a plain-English verdict."""
from dataclasses import dataclass, field, asdict

from . import explain, integrity, link

OK, WATCH, WARN, FAIL = 0, 1, 2, 3
LABELS = {OK: "HEALTHY", WATCH: "WATCH", WARN: "WARNING", FAIL: "FAILING"}
NVME_UNIT = 512_000  # bytes per NVMe "data unit"
# SATA SSD attributes (matched by *name*, since IDs mean different things per vendor,
# names from smartmontools' drivedb) whose normalized VALUE is % life remaining.
WEAR_NAMES = {"Wear_Leveling_Count", "Media_Wearout_Indicator", "SSD_Life_Left", "Percent_Lifetime_Remain",
              "Remaining_Lifetime_Perc", "Percent_Life_Remaining", "Remaining_Life", "Perc_Rated_Life_Used"}
# Host-write counters (not NAND writes, which include write amplification) -> bytes per raw unit.
WRITE_UNITS = {"Host_Writes_32MiB": 32 * 2**20, "Host_Writes_GiB": 2**30, "Lifetime_Writes_GiB": 2**30,
               "Total_Writes_GiB": 2**30, "Lifetime_Wts_Frm_Hst_GB": 10**9}
SPIN_ATTRS = {"Spin_Up_Time", "Start_Stop_Count", "Spin_Retry_Count", "Calibration_Retry_Count"}


@dataclass
class Drive:
    name: str
    model: str = "?"
    serial: str = ""
    size_bytes: int = 0
    kind: str = "hdd"            # nvme | ssd | hdd
    usb: bool = False
    passed: bool = True
    temp_c: int | None = None
    hours: int | None = None
    power_cycles: int | None = None
    wear_pct: int | None = None
    written_tb: float | None = None
    spare_pct: int | None = None
    spare_threshold: int | None = None
    unsafe_shutdowns: int | None = None
    media_errors: int | None = None
    firmware: str = ""
    smart_table: list = field(default_factory=list)   # rows for the detail page
    partitions: list = field(default_factory=list)
    link: dict | None = None     # {"summary": "PCIe Gen4 x4"}
    integrity: list = field(default_factory=list)
    dtype: str = "auto"          # smartctl -d value that worked
    selftest: dict | None = None
    io_errors: int = 0           # kernel I/O errors, last 7 days
    link_resets: int = 0         # ATA/NVMe/USB link resets, last 7 days
    kernel_samples: list = field(default_factory=list)
    critical_warning: int = 0
    reallocated: int = 0
    pending: int = 0
    uncorrectable: int = 0
    crc_errors: int = 0
    level: int = OK
    issues: list = field(default_factory=list)   # (level, text)
    notes: list = field(default_factory=list)

    @property
    def years_left(self):
        if self.wear_pct is None or self.wear_pct < 1 or not self.hours or self.hours < 300:
            return None
        return (100 - self.wear_pct) * self.hours / self.wear_pct / 8760

    def to_dict(self):
        d = asdict(self)
        d["verdict"] = LABELS[self.level]
        d["years_left"] = self.years_left
        return d


def _raw(attrs, *ids):
    for i in ids:
        if i in attrs:
            return attrs[i]["raw"]["value"]
    return None


def from_smartctl(lsblk, j, dtype="auto"):
    d = Drive(name=lsblk["name"], dtype=dtype)
    d.model = j.get("model_name") or (lsblk.get("model") or "?").strip()
    d.firmware = j.get("firmware_version") or ""
    d.serial = j.get("serial_number") or (lsblk.get("serial") or "")
    d.size_bytes = j.get("user_capacity", {}).get("bytes") or int(lsblk.get("size") or 0)
    d.usb = lsblk.get("tran") == "usb"
    d.passed = j.get("smart_status", {}).get("passed", True)
    d.temp_c = j.get("temperature", {}).get("current")
    d.hours = j.get("power_on_time", {}).get("hours")
    d.power_cycles = j.get("power_cycle_count")

    nv = j.get("nvme_smart_health_information_log")
    if nv:
        d.kind = "nvme"
        d.critical_warning = nv.get("critical_warning", 0)
        d.temp_c = nv.get("temperature", d.temp_c)
        d.spare_pct = nv.get("available_spare")
        d.spare_threshold = nv.get("available_spare_threshold")
        d.wear_pct = nv.get("percentage_used")
        d.written_tb = nv.get("data_units_written", 0) * NVME_UNIT / 1e12
        d.unsafe_shutdowns = nv.get("unsafe_shutdowns")
        d.media_errors = nv.get("media_errors")
        d.power_cycles = nv.get("power_cycles", d.power_cycles)
        d.hours = nv.get("power_on_hours", d.hours)
        d.smart_table = [{"name": n, "raw": str(v), "help": h} for n, v, h in [
            ("Critical warning", f"0x{nv.get('critical_warning', 0):02x}", "Flags from the drive itself. 0x00 means none are set."),
            ("Temperature", f"{d.temp_c} C", "Current composite temperature."),
            ("Available spare", f"{d.spare_pct}% (threshold {d.spare_threshold}%)", "Spare flash left for replacing worn blocks."),
            ("Percentage used", f"{d.wear_pct}%", "Share of the rated write endurance consumed. Can pass 100% while still working."),
            ("Data written", f"{d.written_tb:.1f} TB", "Total host writes over the drive's life."),
            ("Data read", f"{nv.get('data_units_read', 0) * NVME_UNIT / 1e12:.1f} TB", "Total host reads over the drive's life."),
            ("Power cycles", f"{nv.get('power_cycles', 0):,}", "Times the drive was powered on."),
            ("Power-on hours", f"{nv.get('power_on_hours', 0):,}", "Total hours powered on."),
            ("Unsafe shutdowns", f"{nv.get('unsafe_shutdowns', 0):,}", "Power losses without a clean shutdown. Expected to be high on external drives."),
            ("Media and data integrity errors", f"{nv.get('media_errors', 0):,}", "Unrecovered data errors. Should be 0."),
            ("Error log entries", f"{nv.get('num_err_log_entries', 0):,}", "Entries in the drive's error log; usually harmless command errors."),
        ]]
    else:
        attrs = {a["id"]: a for a in j.get("ata_smart_attributes", {}).get("table", [])}
        if "rotation_rate" in j:
            spinning = j["rotation_rate"] > 0
        else:  # old drives don't report it; lsblk's ROTA lies over USB, so use attribute names
            spinning = any(a.get("name") in SPIN_ATTRS for a in attrs.values())
        d.kind = "hdd" if spinning else "ssd"
        d.reallocated = _raw(attrs, 5, 196) or 0
        d.pending = _raw(attrs, 197) or 0
        d.uncorrectable = _raw(attrs, 198) or 0
        d.crc_errors = _raw(attrs, 199) or 0
        # 174/192 mean "unexpected power loss" on SSDs, but 192 is head-retract count on HDDs
        d.unsafe_shutdowns = _raw(attrs, 174, 192) if d.kind == "ssd" else None
        d.hours = d.hours if d.hours is not None else _raw(attrs, 9)
        d.smart_table = [{"id": a["id"], "name": a.get("name", "?"), "value": a.get("value"), "worst": a.get("worst"),
                          "thresh": a.get("thresh"), "raw": a.get("raw", {}).get("string", str(a.get("raw", {}).get("value"))),
                          "failing": bool(a.get("when_failed")), "help": explain.ATTR_HELP.get(a.get("name"), "")}
                         for a in j.get("ata_smart_attributes", {}).get("table", [])]
        by_name = {a.get("name"): a for a in attrs.values()}
        if d.kind == "ssd":
            for n in WEAR_NAMES & by_name.keys():
                d.wear_pct = min(100, max(0, 100 - by_name[n]["value"]))
                break
            if d.wear_pct is None:
                d.notes.append("This SSD doesn't report wear data over SMART, so wear and life left can't be shown.")
        lbs = j.get("logical_block_size") or 512
        for n, a in by_name.items():
            unit = lbs if n == "Total_LBAs_Written" else WRITE_UNITS.get(n)
            if unit:
                d.written_tb = a["raw"]["value"] * unit / 1e12
                break
    d.selftest = _selftest(j, d.hours)
    if d.kind != "nvme" and not d.usb:
        apply_link(d, link.sata(j, d.kind))
    _judge(d)
    for text in integrity.check(d, j):
        d.integrity.append(text)
        _add(d, WATCH, text)
    return d


def _selftest(j, hours):
    """Summarize the drive's self-test state. Returns None if the drive doesn't support them."""
    try:
        ata = j.get("ata_smart_data", {}).get("self_test", {})
        ata_log = j.get("ata_smart_self_test_log", {}).get("standard", {}).get("table")
        nv = j.get("nvme_self_test_log")
        if ata_log is None and nv is None and not ata.get("polling_minutes"):
            return None
        poll = ata.get("polling_minutes", {})
        st = {"minutes": {"short": poll.get("short"), "long": poll.get("extended")}, "running": None, "last": None}
        life = None
        if nv is not None:
            if nv.get("current_self_test_operation", {}).get("value"):
                st["running"] = 100 - (nv.get("current_self_test_completion_percent") or 0)
            if nv.get("table"):
                e = nv["table"][0]
                life = e.get("power_on_hours")
                st["last"] = {"type": e.get("self_test_code", {}).get("string", "test").lower(),
                              "result": e.get("self_test_result", {}).get("string", "unknown").lower(),
                              "passed": e.get("self_test_result", {}).get("value") == 0}
        else:
            status = ata.get("status", {})
            if "progress" in status.get("string", "").lower():
                st["running"] = status.get("remaining_percent")
            if ata_log:
                e = ata_log[0]
                life = e.get("lifetime_hours")
                st["last"] = {"type": e.get("type", {}).get("string", "test").lower(),
                              "result": e.get("status", {}).get("string", "unknown").lower(),
                              "passed": e.get("status", {}).get("passed")}
        if st["last"] is not None:
            st["last"]["hours_ago"] = hours - life if hours is not None and life is not None else None
        return st
    except (AttributeError, KeyError, IndexError, TypeError):
        return None


def apply_link(d, res):
    """Attach a link.py result (summary + issues + notes) to a drive."""
    if not res:
        return
    d.link = {"summary": res["summary"]}
    for lvl, text in res["issues"]:
        _add(d, lvl, text)
    d.notes.extend(res["notes"])


def _add(d, level, text):
    d.issues.append((level, text))
    d.level = max(d.level, level)


def _judge(d):
    if not d.passed:
        _add(d, FAIL, "The drive's own SMART self-assessment says it is FAILING. Back up now.")
    if d.critical_warning:
        _add(d, FAIL, f"The drive is reporting a critical warning (flags 0x{d.critical_warning:02x}).")
    if d.media_errors:
        _add(d, WARN, f"{d.media_errors} media/data integrity errors - the flash has returned bad data.")
    if d.spare_pct is not None and d.spare_threshold is not None and d.spare_pct <= d.spare_threshold:
        _add(d, WARN, f"Spare capacity is down to {d.spare_pct}% (threshold {d.spare_threshold}%).")
    if d.pending or d.uncorrectable:
        _add(d, WARN, f"{d.pending} pending / {d.uncorrectable} uncorrectable sectors - data may be unreadable. Back up.")
    if d.reallocated:
        lvl = WARN if d.reallocated >= 50 else WATCH
        _add(d, lvl, f"{d.reallocated} reallocated sectors. A few can be stable; a rising count means decay.")
    if d.crc_errors:
        _add(d, WATCH, f"{d.crc_errors} interface CRC errors - usually a bad or loose cable, not the drive.")
    if d.wear_pct is not None:
        if d.wear_pct >= 100:
            _add(d, WARN, "Rated write endurance is used up. It may keep working, but plan a replacement.")
        elif d.wear_pct >= 80:
            _add(d, WATCH, f"{d.wear_pct}% of rated write endurance used.")
    last = (d.selftest or {}).get("last")
    if last and last.get("passed") is False:
        _add(d, WARN, f"The last SMART self-test ({last['type']}) did not pass: {last['result']}.")
    hot = (70, 60) if d.kind == "nvme" else (60, 50) if d.kind == "hdd" else (70, 60)
    if d.temp_c is not None:
        if d.temp_c >= hot[0]:
            _add(d, WARN, f"Running hot at {d.temp_c}°C.")
        elif d.temp_c >= hot[1]:
            _add(d, WATCH, f"Warm at {d.temp_c}°C.")
    if d.unsafe_shutdowns and d.power_cycles:
        if d.usb:
            if d.unsafe_shutdowns > 100:
                d.notes.append(f"{d.unsafe_shutdowns:,} unsafe shutdowns is normal for an external drive "
                               "(every unplug counts). Unmount before unplugging.")
        elif d.unsafe_shutdowns > 100 and d.unsafe_shutdowns / d.power_cycles > 0.25:
            d.notes.append(f"{d.unsafe_shutdowns:,} of {d.power_cycles:,} power-offs were unclean - "
                           "check for hard resets, crashes or a switched-off PSU.")
