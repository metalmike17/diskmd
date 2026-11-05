"""Find kernel-reported I/O errors and link resets per drive from the journal.

These often show up before SMART notices anything: the OS asked the drive for data and
the drive (or its cable/port/enclosure) failed to deliver.
"""
import os
import re
import subprocess

WINDOW = "7 days ago"
IO_PATTERNS = [
    re.compile(r"I/O error, dev (\w+)"),
    re.compile(r"Buffer I/O error on dev (\w+)"),
    re.compile(r"\[(sd[a-z]+)\].*(?:Medium Error|Unrecovered read error|FAILED Result)"),
    re.compile(r"(?:EXT4-fs|XFS|BTRFS|F2FS)\b.*\berror\b.*\b(?:device|dev)[ :(]+(\w+)", re.I),
]
ATA_LINK = re.compile(r"\b(ata\d+)(?:\.\d+)?: (?:hard resetting link|failed command|exception Emask)")
NVME_LINK = re.compile(r"\b(nvme\d+): .*(?:timeout|controller is down|resetting controller)", re.I)
USB_LINK = re.compile(r"\busb (\d+-\d+(?:\.\d+)*): reset .*USB device")


def disk_of(name):
    """sda1 -> sda, nvme0n1p2 -> nvme0n1."""
    m = re.match(r"(nvme\d+n\d+)p\d+$", name) or re.match(r"((?:sd|vd|hd)[a-z]+)\d+$", name)
    return m.group(1) if m else name


def device_maps(sysblock="/sys/block"):
    """({ataN: disk}, {usb-port: disk}) built from sysfs."""
    ata, usb = {}, {}
    try:
        names = os.listdir(sysblock)
    except OSError:
        return ata, usb
    for n in names:
        path = os.path.realpath(os.path.join(sysblock, n))
        if m := re.search(r"/(ata\d+)/", path):
            ata[m.group(1)] = n
        if ports := re.findall(r"/(\d+-\d+(?:\.\d+)*):\d", path):
            usb[ports[-1]] = n
    return ata, usb


def parse(lines, ata_map, usb_map):
    """{disk: {"io": n, "link": n, "samples": [...]}} from kernel log lines."""
    ev = {}

    def hit(disk, kind, line):
        e = ev.setdefault(disk, {"io": 0, "link": 0, "samples": []})
        e[kind] += 1
        if len(e["samples"]) < 3 and line not in e["samples"]:
            e["samples"].append(line.strip()[:140])

    for line in lines:
        for pat in IO_PATTERNS:
            if m := pat.search(line):
                hit(disk_of(m.group(1)), "io", line)
                break
        else:
            if (m := ATA_LINK.search(line)) and m.group(1) in ata_map:
                hit(ata_map[m.group(1)], "link", line)
            elif m := NVME_LINK.search(line):
                hit(m.group(1), "link", line)  # resolved to a namespace in attach()
            elif (m := USB_LINK.search(line)) and m.group(1) in usb_map:
                hit(usb_map[m.group(1)], "link", line)
    return ev


def collect(window=WINDOW):
    """Read the kernel journal (needs root for a full view). Returns {} if unavailable."""
    try:
        r = subprocess.run(["journalctl", "-k", "--since", window, "-p", "warning", "--no-pager",
                            "-o", "cat", "-n", "50000"], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return {}
    if r.returncode != 0:
        return {}
    return parse(r.stdout.splitlines(), *device_maps())


def attach(drives, events):
    from .analyze import WATCH, WARN, _add
    for d in drives:
        e = events.get(d.name)
        if not e and d.name.startswith("nvme"):  # controller-level events ("nvme0") -> its namespaces
            e = events.get(re.match(r"nvme\d+", d.name).group(0))
        if not e:
            continue
        d.io_errors, d.link_resets, d.kernel_samples = e["io"], e["link"], e["samples"]
        sample = f" e.g. “{e['samples'][0]}”" if e["samples"] else ""
        if e["io"]:
            lvl = WARN if (not d.usb or e["io"] >= 10) else WATCH  # unplugging a USB drive logs a few
            _add(d, lvl, f"{e['io']} kernel I/O errors in the last 7 days - the OS failed to read or write "
                         f"this drive.{sample}")
        if e["link"] >= (3 if d.usb else 1):
            lvl = WARN if e["link"] >= 20 else WATCH
            _add(d, lvl, f"{e['link']} link resets/timeouts in the last 7 days - often a bad cable, port or "
                         "enclosure rather than the drive itself.")
