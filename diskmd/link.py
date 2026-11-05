"""How is each drive actually connected, and is that link holding it back?

Reads sysfs (no root needed) for USB and PCIe/NVMe, and smartctl's interface_speed for SATA.
"""
import os
import re

USB_LABELS = {1.5: "USB 1.0 (1.5 Mbps)", 12: "USB 1.1 (12 Mbps)", 480: "USB 2.0 (480 Mbps)",
              5000: "USB 3.0 (5 Gbps)", 10000: "USB 3.1 Gen 2 (10 Gbps)", 20000: "USB 3.2 Gen 2x2 (20 Gbps)"}
PCIE_GEN = {2.5: 1, 5.0: 2, 8.0: 3, 16.0: 4, 32.0: 5, 64.0: 6}
WATCH = 1


def _read(path):
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return None


def usb_speed(name, sysblock="/sys/block"):
    """Negotiated USB speed in Mbps for the device behind /sys/block/<name>, or None."""
    d = os.path.realpath(os.path.join(sysblock, name))
    while d and d != "/":
        if os.path.exists(os.path.join(d, "busnum")):
            try:
                return float(_read(os.path.join(d, "speed")))
            except (TypeError, ValueError):
                return None
        d = os.path.dirname(d)
    return None


def _result(summary, issues=(), notes=()):
    return {"summary": summary, "issues": list(issues), "notes": list(notes)}


def usb(name, kind, sysblock="/sys/block"):
    s = usb_speed(name, sysblock)
    if s is None:
        return None
    label = USB_LABELS.get(s, f"USB {s:g} Mbps")
    if s <= 480 and kind in ("nvme", "ssd"):
        return _result(label, [(WATCH, f"Connected at {label} - about 40 MB/s at best. This is an SSD that can go "
                                       "far faster: try a USB 3 port (usually blue) or a different cable/hub.")])
    if s <= 480:
        return _result(label, notes=[f"Connected at {label}; a USB 3 port would roughly double this drive's "
                                     "transfer speed."])
    return _result(label)


def nvme(name, root="/sys/class/nvme"):
    m = re.match(r"(nvme\d+)", name)
    if not m:
        return None
    base = os.path.join(root, m.group(1), "device")
    cs, ms = _read(f"{base}/current_link_speed"), _read(f"{base}/max_link_speed")
    cw, mw = _read(f"{base}/current_link_width"), _read(f"{base}/max_link_width")
    try:
        gen = lambda t: PCIE_GEN.get(float(t.split()[0]))
        cur_gen, max_gen, cw, mw = gen(cs), gen(ms), int(cw), int(mw)
    except (AttributeError, TypeError, ValueError):
        return None
    summary = f"PCIe Gen{cur_gen or '?'} x{cw}"
    issues, notes = [], []
    if cw < mw:
        issues.append((WATCH, f"Running at x{cw} but this drive supports x{mw} - it is getting about "
                              f"{cw * 100 // mw}% of its possible bandwidth. Check the M.2 slot (some share lanes "
                              "with other slots or SATA ports)."))
    if cur_gen and max_gen and cur_gen < max_gen:
        notes.append(f"Link is at Gen{cur_gen}, drive supports Gen{max_gen} - could be the slot/CPU limit, or "
                     "idle power saving.")
    return _result(summary, issues, notes)


def sata(j, kind):
    """From smartctl's interface_speed (internal SATA drives only; USB bridges report misleading values)."""
    try:
        speed = lambda k: float(re.match(r"[\d.]+", j["interface_speed"][k]["string"]).group(0))
        cur, mx = speed("current"), speed("max")
    except (KeyError, TypeError, AttributeError):
        return None
    summary = f"SATA {cur:g} Gbps"
    if cur < mx and (kind == "ssd" or cur < 3):
        return _result(summary, [(WATCH, f"SATA link negotiated at {cur:g} Gbps but the drive supports {mx:g} Gbps "
                                         "- check the cable, the port, and the BIOS SATA mode.")])
    return _result(summary)
