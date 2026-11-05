"""Tiny JSONL history so each run can report what changed and how things trend."""
import json
import os
import time
from pathlib import Path

WATCHED = {
    "unsafe_shutdowns": "unsafe shutdowns",
    "media_errors": "media errors",
    "reallocated": "reallocated sectors",
    "pending": "pending sectors",
    "uncorrectable": "uncorrectable sectors",
    "crc_errors": "CRC errors",
    "io_errors": "kernel I/O errors",
    "wear_pct": "% wear",
}
EXTRA = ("level", "temp_c", "written_tb", "hours")


def path():
    base = os.environ.get("DISKMD_DATA") or os.path.join(
        os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share"), "diskmd")
    return Path(base) / "history.jsonl"


def key(d):
    return d.serial or f"{d.model}:{d.size_bytes}"


def load_all():
    """{drive key: [records, oldest first]}"""
    p, out = path(), {}
    if p.exists():
        for line in p.read_text().splitlines():
            try:
                r = json.loads(line)
                out.setdefault(r["key"], []).append(r)
            except (ValueError, KeyError):
                pass
    return out


def load():
    """{drive key: most recent record}"""
    return {k: v[-1] for k, v in load_all().items()}


def deltas(d, last):
    prev = last.get(key(d))
    if not prev:
        return None, []
    days = (time.time() - prev["ts"]) / 86400
    out = []
    for f, label in WATCHED.items():
        a, b = prev.get(f), getattr(d, f)
        if a is not None and b is not None and b > a:
            out.append(f"+{b - a} {label}")
    return days, out


def series(d, records):
    """[[ts, temp_c, wear_pct, written_tb], ...] including the current reading."""
    pts = [[r["ts"], r.get("temp_c"), r.get("wear_pct"), r.get("written_tb")] for r in records[-200:]]
    pts.append([time.time(), d.temp_c, d.wear_pct, d.written_tb])
    return pts


def trend_years_left(d, records, min_days=14):
    """Years until 100% wear at the *recent* rate, or None if there isn't enough signal."""
    if d.wear_pct is None or not records:
        return None
    first = next((r for r in records if r.get("wear_pct") is not None), None)
    if not first:
        return None
    days = (time.time() - first["ts"]) / 86400
    gained = d.wear_pct - first["wear_pct"]
    if days < min_days or gained <= 0:
        return None
    return (100 - d.wear_pct) / (gained / days) / 365


def save(drives):
    p = path()
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a") as fh:
        for d in drives:
            r = {"key": key(d), "ts": time.time()}
            r.update({f: getattr(d, f) for f in (*WATCHED, *EXTRA)})
            fh.write(json.dumps(r) + "\n")
    uid = os.environ.get("SUDO_UID") or os.environ.get("PKEXEC_UID")
    if uid and os.geteuid() == 0:  # keep files owned by the real user
        for f in (p, p.parent):
            os.chown(f, int(uid), int(os.environ.get("SUDO_GID") or uid))
