"""Is the drive's SMART history believable? Signs that counters were reset or faked.

These are *signals*, not proof: firmware bugs and unusual workloads exist. Each finding is worded as
something to ask the seller about.
"""

MAX_TB_PER_HOUR = 5.0   # ~1.4 GB/s sustained for the drive's whole life: implausible for almost anyone


def check(d, j):
    """Return a list of plain-English findings (empty = nothing suspicious)."""
    out = []
    hours = d.hours
    if hours is None:
        return out

    def hours_rollback(label, value):
        if value is not None and value > hours + 2:
            out.append(f"{label} from hour {value:,}, but the drive says it has only {hours:,} power-on hours - "
                       "the hours counter looks reset or rolled back.")

    try:
        ata_log = j.get("ata_smart_self_test_log", {}).get("standard", {}).get("table") or []
        hours_rollback("A self-test log entry is", max((e.get("lifetime_hours") or 0 for e in ata_log), default=None))
        err = j.get("ata_smart_error_log", {}).get("summary", {}).get("table") or []
        hours_rollback("An error-log entry is", max((e.get("lifetime_hours") or 0 for e in err), default=None))
        nv_tests = j.get("nvme_self_test_log", {}).get("table") or []
        hours_rollback("A self-test log entry is", max((e.get("power_on_hours") or 0 for e in nv_tests), default=None))

        nv = j.get("nvme_smart_health_information_log")
        if nv:
            busy = nv.get("controller_busy_time")
            if busy is not None and busy > hours * 60 * 1.02 + 60:
                out.append(f"The controller reports {busy:,} busy minutes, more than the {hours * 60:,} minutes "
                           "it has been powered on - impossible, so the hours counter was likely reset.")
            cycles, unsafe = nv.get("power_cycles"), nv.get("unsafe_shutdowns")
            if cycles is not None and unsafe is not None and unsafe > cycles + 5:
                out.append(f"{unsafe:,} unsafe shutdowns but only {cycles:,} power cycles - the counters "
                           "don't agree with each other.")
    except (AttributeError, TypeError):
        pass

    if d.written_tb and hours >= 1 and d.written_tb / hours > MAX_TB_PER_HOUR:
        out.append(f"{d.written_tb:,.0f} TB written in {hours:,} hours is {d.written_tb / hours:.1f} TB for every "
                   "hour on - not plausible, so the hours or write counters were probably altered.")
    if d.wear_pct is not None and d.wear_pct >= 5 and hours < 100:
        out.append(f"{d.wear_pct}% worn after only {hours:,} power-on hours - the hours look too low for the wear.")
    return out
