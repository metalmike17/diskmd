"""Disk speed test with fio, using the same four profiles as KDiskMark.

Safety: it never touches the raw device. It writes ONE temporary file inside a mounted filesystem on the
chosen drive, then deletes it. Runs as the normal user (no root).
"""
import json
import os
import shutil
import subprocess
import threading
import time
import uuid

from . import history, probe

# (label, block size, queue depth, threads, pattern) - KDiskMark's default profiles
PROFILES = [("SEQ1M Q8T1", "1M", 8, 1, "seq"), ("SEQ1M Q1T1", "1M", 1, 1, "seq"),
            ("RND4K Q32T16", "4k", 32, 16, "rnd"), ("RND4K Q1T1", "4k", 1, 1, "rnd")]
SIZES_MB = (256, 512, 1024, 4096)
RUNTIME = 10   # seconds cap per job, so a slow HDD can't spend an hour on random 4K


def install_hint():
    ids = ""
    try:
        with open("/etc/os-release") as f:
            ids = " ".join(l.split("=", 1)[1].strip().strip('"') for l in f if l.startswith(("ID=", "ID_LIKE=")))
    except OSError:
        pass
    for key, cmd in (("fedora", "sudo dnf install fio"), ("rhel", "sudo dnf install fio"),
                     ("arch", "sudo pacman -S fio"), ("cachyos", "sudo pacman -S fio"),
                     ("debian", "sudo apt install fio"), ("ubuntu", "sudo apt install fio"),
                     ("suse", "sudo zypper install fio")):
        if key in ids.lower():
            return cmd
    return "install the 'fio' package with your package manager"


def kdiskmark_command():
    if shutil.which("kdiskmark"):
        return ["kdiskmark"]
    if shutil.which("flatpak") and subprocess.run(["flatpak", "info", "io.github.jonmagon.kdiskmark"],
                                                  capture_output=True).returncode == 0:
        return ["flatpak", "run", "io.github.jonmagon.kdiskmark"]
    return None


def pick_dir(mounts):
    """A writable directory that lives on one of the drive's filesystems, or None."""
    devs = set()
    for m in mounts:
        try:
            devs.add(os.stat(m).st_dev)
        except OSError:
            pass
    for d in [*mounts, os.path.expanduser("~"), os.environ.get("XDG_CACHE_HOME") or ""]:
        try:
            if d and os.stat(d).st_dev in devs and os.access(d, os.W_OK | os.X_OK):
                return d
        except OSError:
            pass
    return None


def fio_command(fio, path, profile, write, size_mb, direct=True):
    _, bs, qd, nj, pat = profile
    rw = {"seq": ("read", "write"), "rnd": ("randread", "randwrite")}[pat][1 if write else 0]
    return [fio, "--name=diskmd", f"--filename={path}", f"--rw={rw}", f"--bs={bs}", f"--iodepth={qd}",
            f"--numjobs={nj}", f"--size={size_mb}M", "--ioengine=libaio", f"--direct={int(direct)}",
            f"--runtime={RUNTIME}", "--group_reporting", "--thread", "--randrepeat=0", "--output-format=json"]


def parse_fio(out, write):
    """-> {"mbps","iops","lat_us"} from fio's JSON output."""
    job = json.loads(out)["jobs"][0]["write" if write else "read"]
    lat = (job.get("lat_ns") or job.get("clat_ns") or {}).get("mean", 0)
    return {"mbps": round(job["bw_bytes"] / 1e6, 1), "iops": round(job["iops"]), "lat_us": round(lat / 1000, 1)}


def bench_path():
    return history.path().parent / "bench.jsonl"


def drive_key(lb):
    return lb.get("serial") or f"{lb.get('model')}:{lb.get('size')}"


class Bench:
    def __init__(self, fio="fio", demo=False):
        self.fio, self.demo = fio, demo
        self.lock = threading.Lock()
        self.proc = None
        self.reset()

    def reset(self):
        self.state = {"running": False, "dev": None, "step": 0, "total": 0, "label": "", "results": [],
                      "error": None, "note": "", "dir": None, "cancelled": False}

    def available(self):
        return {"fio": self.demo or bool(shutil.which(self.fio)), "hint": install_hint(),
                "kdiskmark": bool(kdiskmark_command())}

    def status(self):
        with self.lock:
            return {**self.state, "results": list(self.state["results"]), **self.available()}

    def start(self, dev, size_mb):
        if size_mb not in SIZES_MB:
            return {"ok": False, "message": "unsupported test size"}
        disk = next((d for d in probe.list_disks() if d["name"] == dev), None) if not self.demo else {"name": dev}
        if disk is None:
            return {"ok": False, "message": f"no such disk: {dev!r}"}
        if not self.available()["fio"]:
            return {"ok": False, "message": f"fio is not installed - {install_hint()}"}
        if self.state["running"]:
            return {"ok": False, "message": "a speed test is already running"}
        base = None
        if not self.demo:
            mounts = [m for p in probe.partitions().get(dev, []) for m in p["mounts"]]
            if not mounts:
                return {"ok": False, "message": f"{dev} has no mounted filesystem. Mount it first - diskmd only "
                                                "ever writes a temporary test file, never to the raw device."}
            base = pick_dir(mounts)
            if base is None:
                return {"ok": False, "message": f"no folder on {dev} is writable by you. Mount it somewhere you can write."}
            need = size_mb * 2**20 * 1.25 + 64 * 2**20
            if shutil.disk_usage(base).free < need:
                return {"ok": False, "message": f"not enough free space on {dev} for a {size_mb} MB test file."}
        with self.lock:
            self.reset()
            self.state.update(running=True, dev=dev, total=len(PROFILES) * 2, dir=base)
        threading.Thread(target=self._run, args=(dev, size_mb, base, disk), daemon=True).start()
        return {"ok": True, "message": f"speed test started on {dev}"}

    def cancel(self):
        with self.lock:
            self.state["cancelled"] = True
            if self.proc and self.proc.poll() is None:
                self.proc.terminate()
        return {"ok": True}

    def _set(self, **kw):
        with self.lock:
            self.state.update(kw)

    def _run(self, dev, size_mb, base, disk):
        tmp = os.path.join(base, f".diskmd-bench-{uuid.uuid4().hex[:8]}") if base else None
        try:
            if tmp:
                os.makedirs(tmp)
            direct, step = True, 0
            for prof in PROFILES:
                for write in (False, True):
                    if self.state["cancelled"]:
                        raise RuntimeError("cancelled")
                    label = f"{prof[0]} {'write' if write else 'read'}"
                    self._set(step=step, label=label)
                    res = self._one(tmp, prof, write, size_mb, direct)
                    if res is None and direct and not self.state["cancelled"]:   # e.g. NTFS/FUSE: no O_DIRECT
                        direct = False
                        self._set(note="This filesystem doesn't support direct I/O, so results include OS caching.")
                        res = self._one(tmp, prof, write, size_mb, direct)
                    if res is None:
                        raise RuntimeError(f"fio failed during {label}")
                    with self.lock:
                        self.state["results"].append({"label": prof[0], "rw": "write" if write else "read", **res})
                    step += 1
            self._set(step=step, label="done")
            self._save(dev, size_mb, disk)
        except RuntimeError as e:
            self._set(error=None if str(e) == "cancelled" else str(e))
        finally:
            if tmp:
                shutil.rmtree(tmp, ignore_errors=True)
            self._set(running=False)

    def _one(self, tmp, prof, write, size_mb, direct):
        if self.demo:
            time.sleep(0.35)
            seed = (hash(prof[0]) % 7 + 3) * (0.8 if write else 1.0)
            big = prof[4] == "seq"
            return {"mbps": round(seed * (330 if big else 40), 1), "iops": round(seed * (330 if big else 10000)),
                    "lat_us": round(300 / seed, 1)}
        cmd = fio_command(self.fio, os.path.join(tmp, "testfile"), prof, write, size_mb, direct)
        try:
            self.proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            out, _ = self.proc.communicate(timeout=RUNTIME * 6 + 120)
            if self.proc.returncode != 0:
                return None
            return parse_fio(out[out.index("{"):], write)
        except (ValueError, KeyError, IndexError, subprocess.TimeoutExpired):
            self.proc.kill()
            return None

    def _save(self, dev, size_mb, disk):
        if self.demo or self.state["cancelled"]:
            return
        p = bench_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a") as f:
            f.write(json.dumps({"key": drive_key(disk), "dev": dev, "ts": time.time(), "size_mb": size_mb,
                                "results": self.state["results"], "note": self.state["note"]}) + "\n")


def past_results(dev, limit=8):
    """Earlier speed tests for this drive, newest last."""
    disk = next((d for d in probe.list_disks() if d["name"] == dev), None)
    p, out = bench_path(), []
    if disk and p.exists():
        for line in p.read_text().splitlines():
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if r.get("key") == drive_key(disk):
                out.append(r)
    return out[-limit:]
