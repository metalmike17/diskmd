"""Install/remove a daily systemd timer that runs `diskmd --check`."""
import os
import subprocess
import sys

from . import alerts, history

SERVICE = "/etc/systemd/system/diskmd.service"
TIMER = "/etc/systemd/system/diskmd.timer"


def _program():
    """(extra Environment= lines, ExecStart command) for this install: AppImage file, or python -m diskmd."""
    appimage = os.environ.get("DISKMD_APPIMAGE") or os.environ.get("APPIMAGE")
    if appimage:
        return "Environment=APPIMAGE_EXTRACT_AND_RUN=1\n", appimage
    pkg_parent = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return f"Environment=PYTHONPATH={pkg_parent}\n", f"{sys.executable} -m diskmd"


def install():
    env_line, command = _program()
    with open(SERVICE, "w") as f:
        f.write(f"""[Unit]
Description=diskmd drive health check

[Service]
Type=oneshot
{env_line}Environment=DISKMD_DATA={history.path().parent}
Environment=DISKMD_NOTIFY_UID={alerts.real_uid()}
ExecStart={command} --check --no-sudo
""")
    with open(TIMER, "w") as f:
        f.write("""[Unit]
Description=Daily diskmd drive health check

[Timer]
OnCalendar=daily
Persistent=true
RandomizedDelaySec=30min

[Install]
WantedBy=timers.target
""")
    subprocess.run(["systemctl", "daemon-reload"], check=True)
    subprocess.run(["systemctl", "enable", "--now", "diskmd.timer"], check=True)
    print("Installed: diskmd will check your drives daily and notify you of problems.")
    print("Status: systemctl list-timers diskmd.timer   |   Remove: diskmd --uninstall-timer")


def uninstall():
    subprocess.run(["systemctl", "disable", "--now", "diskmd.timer"], check=False)
    for f in (SERVICE, TIMER):
        if os.path.exists(f):
            os.remove(f)
    subprocess.run(["systemctl", "daemon-reload"], check=False)
    print("diskmd timer removed.")
