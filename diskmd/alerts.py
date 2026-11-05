"""Decide what is worth interrupting the user about, and tell them."""
import os
import pwd
import shutil
import subprocess

from . import history
from .analyze import OK, WATCH, WARN, FAIL

# Counters where *any* increase matters. (Unsafe shutdowns and wear change normally.)
BAD_COUNTERS = {k: history.WATCHED[k] for k in
                ("media_errors", "reallocated", "pending", "uncorrectable", "crc_errors", "io_errors")}


def find(drives, last):
    """Return [(drive, worst_level, [reason, ...])] for drives that need attention."""
    out = []
    for d in drives:
        prev = last.get(history.key(d))
        reasons = []
        prev_level = prev.get("level", OK) if prev else OK
        if prev:  # what changed first - it's the most useful part of a notification
            for f, label in BAD_COUNTERS.items():
                a, b = prev.get(f), getattr(d, f)
                if a is not None and b is not None and b > a:
                    reasons.append(f"+{b - a} {label} since last check")
        # Brand-new drives only alert if already bad; known drives alert when they get worse.
        if d.level > prev_level and (prev or d.level >= WARN):
            reasons += [t for lvl, t in d.issues if lvl == d.level]
        if reasons:
            out.append((d, d.level, list(dict.fromkeys(reasons))))
    return out


def real_uid():
    for v in ("DISKMD_NOTIFY_UID", "SUDO_UID", "PKEXEC_UID"):
        if os.environ.get(v, "").isdigit():
            return int(os.environ[v])
    return os.getuid()


def notify(alerts):
    """Desktop notification. Works from a root service by dropping to the user's session bus."""
    if not alerts or not shutil.which("notify-send"):
        return False
    worst = max(lvl for _, lvl, _ in alerts)
    title = f"diskmd: {len(alerts)} drive{'s' if len(alerts) > 1 else ''} need attention"
    body = "\n".join(f"{d.name} ({d.model}): {r[0]}" for d, _, r in alerts)
    cmd = ["notify-send", "-a", "diskmd", "-u", "critical" if worst >= WARN else "normal", title, body]
    uid = real_uid()
    if os.geteuid() == 0 and uid != 0:
        user = pwd.getpwuid(uid).pw_name
        cmd = ["runuser", "-u", user, "--", "env",
               f"DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/{uid}/bus"] + cmd
    return subprocess.run(cmd, capture_output=True).returncode == 0
