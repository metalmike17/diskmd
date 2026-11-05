#!/bin/sh
# Build diskmd_<version>_all.deb from the working tree (Debian, Ubuntu, Mint, Pop!_OS...).
# Uses dpkg-deb when present, otherwise assembles the .deb with ar + tar (a .deb is just an ar archive).
set -eu
cd "$(dirname "$0")/../.."
VER=$(sed -n 's/^__version__ = "\(.*\)"/\1/p' diskmd/__init__.py)
ROOT=$(mktemp -d)
PKG=$ROOT/diskmd_${VER}_all
install -d "$PKG/DEBIAN" "$PKG/usr/lib/python3/dist-packages"
cp -r diskmd "$PKG/usr/lib/python3/dist-packages/"
find "$PKG" -name __pycache__ -prune -exec rm -rf {} +
install -Dm755 packaging/diskmd-launcher "$PKG/usr/bin/diskmd"
install -Dm644 data/io.github.metalmike17.DiskMD.desktop -t "$PKG/usr/share/applications/"
install -Dm644 data/io.github.metalmike17.DiskMD.metainfo.xml -t "$PKG/usr/share/metainfo/"
install -Dm644 data/io.github.metalmike17.DiskMD.svg -t "$PKG/usr/share/icons/hicolor/scalable/apps/"
install -Dm644 LICENSE "$PKG/usr/share/doc/diskmd/copyright"
SIZE=$(du -sk "$PKG/usr" | cut -f1)
cat > "$PKG/DEBIAN/control" <<CTRL
Package: diskmd
Version: $VER
Architecture: all
Maintainer: metalmike17 <michaeljg0717@gmail.com>
Installed-Size: $SIZE
Depends: python3 (>= 3.10), smartmontools
Recommends: pkexec | policykit-1, fio
Suggests: python3-pyside6.qtwebenginewidgets, libnotify-bin
Section: utils
Priority: optional
Homepage: https://github.com/metalmike17/diskmd
Description: Drive health for Linux, in plain English
 diskmd makes SMART data readable. It checks every drive in your PC, explains
 in plain English whether it is healthy and what to do about it, and detects
 USB enclosures automatically. It checks link speed (an SSD stuck on USB 2.0,
 an NVMe running at x2), scans the kernel log for I/O errors, runs SMART
 self-tests, benchmarks with fio, tracks wear and temperature over time, can
 alert you daily, and can check whether a used drive's SMART history looks
 altered.
 .
 diskmd only reads SMART data. It never writes to or reconfigures a drive.
CTRL
OUT=${OUT:-.}
DEB="$OUT/diskmd_${VER}_all.deb"
if command -v dpkg-deb >/dev/null 2>&1; then
    dpkg-deb --root-owner-group --build "$PKG" "$DEB"
else
    T=$ROOT/parts; mkdir -p "$T"
    (cd "$PKG/DEBIAN" && tar --owner=0 --group=0 --numeric-owner -czf "$T/control.tar.gz" ./control)
    (cd "$PKG" && tar --owner=0 --group=0 --numeric-owner --exclude=./DEBIAN -czf "$T/data.tar.gz" ./usr)
    echo "2.0" > "$T/debian-binary"
    rm -f "$DEB"; (cd "$T" && ar rc "$(cd "$OLDPWD" && cd "$OUT" && pwd)/$(basename "$DEB")" debian-binary control.tar.gz data.tar.gz)
fi
echo "$DEB"
