"""Find drives and read SMART data, auto-detecting USB bridge types."""
import json
import subprocess

# smartctl -d values to try, in order, for USB-attached drives it can't identify.
USB_TYPES = ["sat", "sntasmedia", "sntjmicron", "sntrealtek", "usbjmicron", "usbsunplus", "usbcypress"]


def _run(cmd, timeout=25):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None


def list_disks():
    """Return physical-looking disks from lsblk (skips zram, loop, zero-size)."""
    r = _run(["lsblk", "-J", "-d", "-b", "-o", "NAME,MODEL,SIZE,TRAN,TYPE,ROTA,RM,SERIAL"])
    if not r or r.returncode != 0:
        return []
    disks = []
    for d in json.loads(r.stdout).get("blockdevices", []):
        if d.get("type") != "disk" or not int(d.get("size") or 0):
            continue
        if d["name"].startswith(("zram", "loop", "ram")):
            continue
        disks.append(d)
    return disks


def partitions():
    """{disk name: [{name,size,fstype,label,mounts,used,free}]} from lsblk (works without root)."""
    import shutil
    r = _run(["lsblk", "-J", "-b", "-o", "NAME,SIZE,TYPE,FSTYPE,LABEL,MOUNTPOINTS"])
    out = {}
    if not r or r.returncode != 0:
        return out

    def walk(node, acc):
        for c in node.get("children", []) or []:
            mounts = [m for m in (c.get("mountpoints") or []) if m and not m.startswith("[")]
            part = {"name": c["name"], "size": int(c.get("size") or 0), "fstype": c.get("fstype") or "",
                    "label": c.get("label") or "", "mounts": mounts, "used": None, "free": None}
            for m in mounts:
                try:
                    u = shutil.disk_usage(m)
                    part["used"], part["free"] = u.used, u.free
                    break
                except OSError:
                    pass
            acc.append(part)
            walk(c, acc)

    for dev in json.loads(r.stdout).get("blockdevices", []):
        acc = []
        walk(dev, acc)
        out[dev["name"]] = acc
    return out


def _has_data(j):
    return any(k in j for k in ("nvme_smart_health_information_log", "ata_smart_attributes"))


def _denied(j):
    msgs = j.get("smartctl", {}).get("messages", [])
    return any("Permission denied" in m.get("string", "") for m in msgs)


def read_smart(name, tran):
    """Return (smartctl_json, device_type_used) or (None, None) if unsupported.

    Raises PermissionError if smartctl needs root.
    """
    dev = f"/dev/{name}"
    tries = [None] + (USB_TYPES if tran == "usb" else [])
    for dtype in tries:
        cmd = ["smartctl", "-j", "-a"] + (["-d", dtype] if dtype else []) + [dev]
        r = _run(cmd)
        if r is None or not r.stdout.strip():
            continue
        try:
            j = json.loads(r.stdout)
        except ValueError:
            continue
        if _denied(j):
            raise PermissionError(dev)
        if _has_data(j):
            return j, dtype or "auto"
    return None, None


SELFTESTS = ("short", "long")


def start_selftest(name, kind):
    """Start a SMART self-test (read-only; the drive stays usable). Returns a result dict.

    `name` must exactly match a disk lsblk reports - it is never used as a free-form path,
    because the GUI can pass it to a root process.
    """
    if kind not in SELFTESTS:
        return {"ok": False, "message": f"unknown test type {kind!r}"}
    disk = next((d for d in list_disks() if d["name"] == name), None)
    if disk is None:
        return {"ok": False, "message": f"no such disk: {name!r}"}
    j, dtype = read_smart(name, disk.get("tran"))
    if j is None:
        return {"ok": False, "message": "this drive doesn't expose SMART self-tests"}
    poll = j.get("ata_smart_data", {}).get("self_test", {}).get("polling_minutes", {})
    minutes = poll.get("short" if kind == "short" else "extended")
    cmd = ["smartctl", "-j", "-t", kind] + (["-d", dtype] if dtype != "auto" else []) + [f"/dev/{name}"]
    r = _run(cmd)
    try:
        out = json.loads(r.stdout)
    except (ValueError, AttributeError):
        return {"ok": False, "message": "smartctl gave no usable answer"}
    if out.get("smartctl", {}).get("exit_status", 1) != 0:
        msgs = [m.get("string", "") for m in out.get("smartctl", {}).get("messages", [])]
        return {"ok": False, "message": "; ".join(m for m in msgs if m) or "smartctl refused to start the test"}
    return {"ok": True, "message": f"{kind} self-test started on {name}", "minutes": minutes}
