import argparse
import json
import os
import shutil
import sys

from . import __version__, alerts, history, kernel, link, probe
from .analyze import from_smartctl, apply_link, OK
from .render import render, markdown_report, used_report


def reexec_prefix():
    """argv prefix that re-runs this program as root with the user's history/notify settings."""
    env = [f"DISKMD_DATA={history.path().parent}", f"DISKMD_NOTIFY_UID={os.getuid()}"]
    appimage = os.environ.get("APPIMAGE")
    if appimage:   # root cannot read our FUSE mount, so it extracts the AppImage file and runs that instead
        return ["env", *env, f"DISKMD_APPIMAGE={appimage}", "APPIMAGE_EXTRACT_AND_RUN=1", appimage, "--no-sudo"]
    pkg_parent = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return ["env", f"PYTHONPATH={pkg_parent}", *env, sys.executable, "-m", "diskmd", "--no-sudo"]


def scan(devices=()):
    """Read every drive. Raises PermissionError if not root."""
    wanted = [x.replace("/dev/", "") for x in devices]
    drives, skipped = [], 0
    for lb in probe.list_disks():
        if wanted and lb["name"] not in wanted:
            continue
        j, dtype = probe.read_smart(lb["name"], lb.get("tran"))
        if j is None:
            skipped += 1
        else:
            d = from_smartctl(lb, j, dtype)
            apply_link(d, link.usb(d.name, d.kind) if d.usb else link.nvme(d.name) if d.kind == "nvme" else None)
            drives.append(d)
    parts = probe.partitions()
    for d in drives:
        d.partitions = parts.get(d.name, [])
    if drives and os.geteuid() == 0:
        kernel.attach(drives, kernel.collect())
    return drives, skipped


def payload(drives, skipped, last, allrec=None):
    allrec = allrec or {}
    out = []
    for d in drives:
        days, changes = history.deltas(d, last)
        recs = allrec.get(history.key(d), [])
        out.append({**d.to_dict(), "days_since": days, "changes": changes,
                    "series": history.series(d, recs), "trend_years_left": history.trend_years_left(d, recs)})
    return {"drives": out, "skipped": skipped, "report": markdown_report(drives, __version__)}


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    ap = argparse.ArgumentParser(prog="diskmd", description="Plain-English drive health for Linux.")
    ap.add_argument("devices", nargs="*", help="limit to these devices, e.g. nvme0n1 sda")
    ap.add_argument("--gui", action="store_true", help="open the graphical interface (its own window)")
    ap.add_argument("--window", choices=["auto", "qt", "app", "browser"], default="auto",
                    help="with --gui: native Qt window, Chromium app window, or plain browser (default: best available)")
    ap.add_argument("--install-launcher", action="store_true", help="add diskmd to your application menu")
    ap.add_argument("--demo", action="store_true", help="with --gui: show sample data, no root needed")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--report", action="store_true", help="print a shareable Markdown report (no serial numbers)")
    ap.add_argument("--selftest", choices=probe.SELFTESTS, metavar="{short,long}",
                    help="start a read-only SMART self-test on the one device given, e.g. --selftest short sda")
    ap.add_argument("--used-check", action="store_true",
                    help="buying a used drive? check whether its SMART history looks reset or altered")
    ap.add_argument("--check", action="store_true", help="quiet mode for timers: notify only if something got worse")
    ap.add_argument("--install-timer", action="store_true", help="check daily in the background and notify (needs root)")
    ap.add_argument("--uninstall-timer", action="store_true", help="remove the daily background check")
    ap.add_argument("--no-color", action="store_true")
    ap.add_argument("--no-history", action="store_true", help="don't read/write the history file")
    ap.add_argument("--no-sudo", action="store_true", help="don't try to re-run with sudo")
    ap.add_argument("-V", "--version", action="version", version=f"diskmd {__version__}")
    args = ap.parse_args(argv)

    if args.gui:
        from . import gui
        return gui.run(demo=args.demo, prefer=args.window)
    if args.install_launcher:
        from . import window
        print("Installed:", window.install_launcher())
        return 0
    if args.selftest and len(args.devices) != 1:
        print("--selftest needs exactly one device, e.g. diskmd --selftest short sda", file=sys.stderr)
        return 2
    if not shutil.which("smartctl"):
        print("smartctl not found. Install smartmontools (e.g. `sudo dnf/apt/pacman install smartmontools`).",
              file=sys.stderr)
        return 2
    if os.geteuid() != 0 and not args.no_sudo:
        print("diskmd needs root to read SMART data - asking sudo...", file=sys.stderr)
        os.execvp("sudo", ["sudo", *reexec_prefix(), *argv])
    if args.selftest:
        try:
            res = probe.start_selftest(args.devices[0].replace("/dev/", ""), args.selftest)
        except PermissionError:
            print("Permission denied reading SMART data. Run as root (sudo diskmd).", file=sys.stderr)
            return 2
        print(json.dumps(res) if args.json else res["message"] + (
            f" (about {res['minutes']} min - run diskmd again to see the result)" if res.get("minutes") else ""))
        return 0 if res["ok"] else 1
    if args.install_timer or args.uninstall_timer:
        from . import timer
        (timer.install if args.install_timer else timer.uninstall)()
        return 0
    try:
        drives, skipped = scan(args.devices)
    except PermissionError:
        print("Permission denied reading SMART data. Run as root (sudo diskmd).", file=sys.stderr)
        return 2

    allrec = {} if args.no_history else history.load_all()
    last = {k: v[-1] for k, v in allrec.items()}
    if args.check:
        found = alerts.find(drives, last)
        if found:
            for d, _, reasons in found:
                print(f"ALERT {d.name} ({d.model}): " + "; ".join(reasons))
            alerts.notify(found)
        else:
            print(f"diskmd: {len(drives)} drives checked, nothing new to report.")
    elif args.used_check:
        print(used_report(drives, color=sys.stdout.isatty() and not args.no_color))
    elif args.report:
        print(markdown_report(drives, __version__), end="")
    elif args.json:
        print(json.dumps(payload(drives, skipped, last, allrec), indent=2))
    else:
        hist = {d.name: history.deltas(d, last) for d in drives}
        print(render(drives, hist, color=sys.stdout.isatty() and not args.no_color, skipped=skipped))
    if not args.no_history and drives:
        history.save(drives)
    return 0 if args.check else max((d.level for d in drives), default=OK)
