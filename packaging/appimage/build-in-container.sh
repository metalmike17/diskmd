#!/bin/bash
# Run INSIDE ubuntu:24.04 (glibc 2.39). /src = repo (read-only), /out = output dir.
# Produces /out/AppDir with a trimmed Python + diskmd (stdlib only, no other dependencies).
set -e
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq python3 binutils libssl3t64 libsqlite3-0 liblzma5 libbz2-1.0 libffi8 zlib1g libexpat1 >/dev/null
A=/out/AppDir
rm -rf "${A:?}"; mkdir -p "$A/usr/bin" "$A/usr/lib"
PYV=$(python3 -c 'import sys;print(f"{sys.version_info[0]}.{sys.version_info[1]}")')
cp "/usr/bin/python$PYV" "$A/usr/bin/python3"
mkdir -p "$A/usr/lib/python$PYV"
cp -a "/usr/lib/python$PYV/." "$A/usr/lib/python$PYV/"
PL="$A/usr/lib/python$PYV"
for d in test idlelib tkinter turtledemo lib2to3 ensurepip EXTERNALLY-MANAGED; do rm -rf "${PL:?}/$d"; done
SP="$PL/site-packages"; mkdir -p "$SP"
cp -a /src/diskmd "$SP/"
find "${A:?}" -name __pycache__ -type d -prune -exec rm -rf {} +
EX='^(linux-vdso|ld-linux|libc\.|libm\.|libdl\.|libpthread|librt\.|libutil|libresolv|libnsl|libudev|libsystemd|libgcc_s|libnss)'
for f in "$A/usr/bin/python3" $(find "$A/usr/lib" -name '*.so*' -type f); do
  ldd "$f" 2>/dev/null | awk '/=> \//{print $3}' | while read -r l; do
    b=$(basename "$l"); echo "$b" | grep -Eq "$EX" && continue
    cp -nL "$l" "$A/usr/lib/"
  done
done
du -sh "$A"; echo "py $PYV"
