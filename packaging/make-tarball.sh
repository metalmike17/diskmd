#!/bin/sh
# Create diskmd-<version>.tar.gz from the working tree (what the rpm/AUR packages build from).
set -eu
cd "$(dirname "$0")/.."
VER=$(sed -n 's/^__version__ = "\(.*\)"/\1/p' diskmd/__init__.py)
OUT=${OUT:-.}
tar --exclude=__pycache__ --exclude='*.pyc' --exclude=dist --exclude=build --exclude='*.egg-info' \
    --transform "s,^\./,diskmd-$VER/," -czf "$OUT/diskmd-$VER.tar.gz" \
    ./diskmd ./data ./packaging ./tests ./docs ./README.md ./LICENSE ./pyproject.toml
echo "$OUT/diskmd-$VER.tar.gz"
