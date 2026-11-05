import os
import tempfile
import unittest
from unittest import mock

from diskmd import cli, timer, window


class AppImageAware(unittest.TestCase):
    def test_reexec_runs_the_appimage_file_not_the_fuse_mount(self):
        with mock.patch.dict(os.environ, {"APPIMAGE": "/home/u/diskmd.AppImage"}):
            argv = cli.reexec_prefix()
        self.assertIn("/home/u/diskmd.AppImage", argv)
        self.assertIn("APPIMAGE_EXTRACT_AND_RUN=1", argv)
        self.assertEqual(argv[-1], "--no-sudo")
        self.assertFalse(any(a.startswith("PYTHONPATH=") for a in argv))   # nothing from inside the mount

    def test_reexec_normal_install_uses_python_module(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("APPIMAGE", None)
            argv = cli.reexec_prefix()
        self.assertEqual(argv[-4:-1], [argv[-4], "-m", "diskmd"])
        self.assertTrue(any(a.startswith("PYTHONPATH=") for a in argv))

    def test_timer_unit_points_at_the_appimage(self):
        with mock.patch.dict(os.environ, {"DISKMD_APPIMAGE": "/home/u/d.AppImage"}):
            env_line, command = timer._program()
        self.assertEqual(command, "/home/u/d.AppImage")
        self.assertIn("APPIMAGE_EXTRACT_AND_RUN=1", env_line)

    def test_launcher_uses_appimage_and_flatpak_style_id(self):
        d = tempfile.mkdtemp()
        with mock.patch.dict(os.environ, {"APPIMAGE": "/home/u/d.AppImage", "XDG_DATA_HOME": d}), \
             mock.patch("subprocess.run"):
            path = window.install_launcher()
        self.assertTrue(path.endswith("io.github.metalmike17.DiskMD.desktop"))
        with open(path) as f:
            text = f.read()
        self.assertIn("Exec=/home/u/d.AppImage --gui", text)
        self.assertIn("StartupWMClass=io.github.metalmike17.DiskMD", text)


if __name__ == "__main__":
    unittest.main()
