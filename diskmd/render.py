"""Plain-text rendering with optional ANSI color. No dependencies."""
from .analyze import OK, WATCH, WARN, FAIL, LABELS

COLORS = {OK: "32", WATCH: "33", WARN: "31", FAIL: "1;31"}


def _c(text, code, on):
    return f"\033[{code}m{text}\033[0m" if on else text


def human_size(n):
    for unit, div in (("TB", 1e12), ("GB", 1e9), ("MB", 1e6)):
        if n >= div:
            return f"{n / div:.0f} {unit}"
    return f"{n} B"


def life_text(y):
    return None if y is None else ("10+ years" if y >= 10 else f"~{y:.0f} years" if y >= 2 else f"~{y * 12:.0f} months")


def render(drives, hist, color=True, skipped=0):
    out = []
    for d in drives:
        kind = {"nvme": "NVMe", "ssd": "SSD", "hdd": "HDD"}[d.kind] + (" (USB)" if d.usb else "")
        badge = _c(f"● {LABELS[d.level]}", COLORS[d.level], color)
        out.append(f"{badge:<{10 + (len(badge) - len(LABELS[d.level]) - 2)}} "
                   f"{_c(d.name, '1', color)}  {d.model}  {human_size(d.size_bytes)} {kind}")
        bits = []
        if d.wear_pct is not None:
            bits.append(f"{d.wear_pct}% worn")
        if d.written_tb is not None:
            bits.append(f"{d.written_tb:.1f} TB written")
        if d.temp_c is not None:
            bits.append(f"{d.temp_c}°C")
        if d.hours is not None:
            bits.append(f"{d.hours:,} h on")
        if d.link:
            bits.append(d.link["summary"])
        if life_text(d.years_left):
            bits.append(f"est. {life_text(d.years_left)} left")
        out.append("    " + " · ".join(bits))
        for lvl, text in d.issues:
            out.append("    " + _c(f"• {text}", COLORS[lvl], color))
        for text in d.notes:
            out.append("    " + _c(f"ℹ {text}", "2", color))
        days, changes = hist.get(d.name, (None, []))
        if days is not None:
            when = "today" if days < 1 else f"{days:.0f} days ago"
            out.append("    " + (_c(f"↑ since last check ({when}): {', '.join(changes)}", "33", color)
                                  if changes else _c(f"✓ no changes since last check ({when})", "2", color)))
        out.append("")
    worst = max((d.level for d in drives), default=OK)
    summary = f"{len(drives)} drive(s) checked"
    if skipped:
        summary += f", {skipped} without SMART data (card readers, some enclosures)"
    out.append(_c(summary + (" - all healthy." if worst == OK else "."), COLORS[worst], color))
    return "\n".join(out)


def summary_line(drives):
    """'8 drives checked - all healthy.' or '8 drives checked: 6 healthy, 1 to watch (sde), 1 warning (sdb).'"""
    n = len(drives)
    word = f"{n} drive{'s' if n != 1 else ''} checked"
    ok = sum(d.level == OK for d in drives)
    if ok == n:
        return f"{word} - all healthy."
    parts = [f"{ok} healthy"] if ok else []
    for lvl, label in ((FAIL, "failing"), (WARN, "warning"), (WATCH, "to watch")):
        names = [d.name for d in drives if d.level == lvl]
        if names:
            parts.append(f"{len(names)} {label} ({', '.join(names)})")
    return f"{word}: {', '.join(parts)}."


def markdown_report(drives, version=""):
    """Shareable summary. Serial numbers are deliberately never included."""
    import datetime
    lines = ["# Drive health report", f"_diskmd {version} - {datetime.date.today()}_", "",
             f"**{summary_line(drives)}**", "",
             "| Drive | Model | Type | Connection | Size | Verdict | Wear | Written | Temp | Power-on |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    for d in drives:
        kind = {"nvme": "NVMe", "ssd": "SSD", "hdd": "HDD"}[d.kind] + (" (USB)" if d.usb else "")
        lines.append(f"| {d.name} | {d.model} | {kind} | {d.link['summary'] if d.link else '-'} | "
                     f"{human_size(d.size_bytes)} | {LABELS[d.level]} | "
                     f"{'-' if d.wear_pct is None else str(d.wear_pct) + '%'} | "
                     f"{'-' if d.written_tb is None else f'{d.written_tb:.1f} TB'} | "
                     f"{'-' if d.temp_c is None else f'{d.temp_c}C'} | "
                     f"{'-' if d.hours is None else f'{d.hours:,} h'} |")
    flagged = [d for d in drives if d.issues or d.notes]
    if flagged:
        lines += ["", "## Notes", ""]
        for d in flagged:
            lines += [f"**{d.name}** ({d.model})", ""]          # blank lines keep each drive its own block
            lines += [f"- {t}" for _, t in d.issues] + [f"- {t}" for t in d.notes] + [""]
    return "\n".join(lines).rstrip("\n") + "\n"


def used_report(drives, color=True):
    """Buyer-focused view: is this drive's SMART history believable?"""
    out = ["Used-drive check - are the SMART counters believable?", ""]
    for d in drives:
        facts = " \u00b7 ".join(x for x in (
            f"{d.hours:,} h on" if d.hours is not None else None,
            f"{d.power_cycles:,} power cycles" if d.power_cycles is not None else None,
            f"{d.written_tb:.1f} TB written" if d.written_tb is not None else None) if x)
        head = f"{d.name}  {d.model}  ({facts})"
        if d.integrity:
            out.append(_c("\u26a0 " + head, "33", color))
            out += [_c(f"    \u2022 {t}", "33", color) for t in d.integrity]
        else:
            out.append(_c("\u2713 ", "32", color) + head + _c("  no signs of reset or altered counters", "2", color))
    out += ["", _c("These are signals, not proof - firmware quirks exist. If you are buying a drive, treat a "
                   "warning as a reason to ask the seller questions, and also check the health verdict.", "2", color)]
    return "\n".join(out)
