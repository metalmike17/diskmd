"""Open the GUI in a real app window: Qt WebEngine > Chromium --app > default browser."""
import os
import shutil
import subprocess
import sys
import webbrowser

CHROMIUMS = ["google-chrome-stable", "google-chrome", "chromium", "chromium-browser",
             "brave-browser", "brave", "microsoft-edge", "vivaldi"]
FLATPAKS = ["com.brave.Browser", "com.google.Chrome", "org.chromium.Chromium", "com.microsoft.Edge"]
APP_ID = "io.github.metalmike17.DiskMD"
ICON = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "diskmd.svg")


def have_qt():
    try:
        from PySide6.QtWebEngineWidgets import QWebEngineView  # noqa: F401
        return True
    except Exception:  # missing module, or a broken Qt install
        return False


def make_qt_window(url, title="diskmd"):
    """Return (QApplication, QWebEngineView) showing url. Caller shows it and runs the loop."""
    from PySide6.QtGui import QColor, QIcon
    from PySide6.QtWebEngineCore import QWebEngineSettings
    from PySide6.QtWebEngineWidgets import QWebEngineView
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import QUrl
    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName("diskmd")
    app.setDesktopFileName(APP_ID)
    view = QWebEngineView()
    view.setWindowTitle(title)
    view.setWindowIcon(QIcon(ICON))
    view.resize(1500, 920)
    view.page().setBackgroundColor(QColor("#0D0F14"))   # no white flash while loading
    view.settings().setAttribute(QWebEngineSettings.WebAttribute.JavascriptCanAccessClipboard, True)
    view.setUrl(QUrl(url))
    return app, view


def app_mode_command(url):
    """argv for a chromeless Chromium-family window, or None."""
    for exe in CHROMIUMS:
        if shutil.which(exe):
            return [exe, f"--app={url}", "--window-size=1500,920"]
    if shutil.which("flatpak"):
        for app_id in FLATPAKS:
            if subprocess.run(["flatpak", "info", app_id], capture_output=True).returncode == 0:
                return ["flatpak", "run", app_id, f"--app={url}", "--window-size=1500,920"]
    return None


def show(url, prefer="auto"):
    """Open the window. Returns "qt" (already closed by the user), "app" or "browser" (still running)."""
    if prefer in ("auto", "qt") and have_qt():
        app, view = make_qt_window(url)
        view.show()
        app.exec()
        return "qt"
    if prefer in ("auto", "app"):
        cmd = app_mode_command(url)
        if cmd:
            subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return "app"
    if prefer == "auto":
        print("diskmd: no app window available, opening your browser. "
              "For a native window install PySide6 (pip install PySide6) or a Chromium-based browser.", flush=True)
    webbrowser.open(url)
    return "browser"


DESKTOP = """[Desktop Entry]
Type=Application
Name=DiskMD
GenericName=Drive health
Comment=Drive health for Linux, in plain English
Exec={exec_line}
Icon={icon}
Terminal=false
Categories=System;Monitor;
Keywords=disk;drive;smart;nvme;ssd;health;
StartupWMClass=io.github.metalmike17.DiskMD
"""


def install_launcher():
    """Add diskmd to the user's application menu (no root needed)."""
    appimage = os.environ.get("APPIMAGE")
    if appimage:
        exec_line = f"{appimage} --gui"
    else:
        pkg_parent = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        exec_line = f"env PYTHONPATH={pkg_parent} {sys.executable} -m diskmd --gui"
    apps = os.path.join(os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share"), "applications")
    os.makedirs(apps, exist_ok=True)
    path = os.path.join(apps, APP_ID + ".desktop")
    with open(path, "w") as f:
        f.write(DESKTOP.format(exec_line=exec_line, icon=ICON))
    subprocess.run(["update-desktop-database", apps], capture_output=True)
    return path
