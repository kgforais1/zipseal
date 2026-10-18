#!/bin/sh
# Double-click in Finder to open the zipseal window (macOS).
#
# Finder runs this in Terminal. It starts the GUI from this clone with uv, so
# nothing needs installing first. Closing the Terminal window quits the GUI.
set -eu

repo=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
self=$repo/$(basename -- "$0")

# First run: give this file the zipseal icon. A fresh clone has none.
if [ -f "$repo/scripts/set-icon.sh" ] &&
    ! xattr -p com.apple.ResourceFork "$self" >/dev/null 2>&1; then
    sh "$repo/scripts/set-icon.sh" "$self" || true
fi

# Finder's shell may not have uv's usual folders on PATH.
uv=$(command -v uv 2>/dev/null || true)
if [ -z "$uv" ]; then
    for dir in "${HOME:-}/.local/bin" /opt/homebrew/bin /usr/local/bin; do
        if [ -x "$dir/uv" ]; then
            uv=$dir/uv
            break
        fi
    done
fi

if [ -z "$uv" ]; then
    echo "zipseal: uv is required: https://docs.astral.sh/uv/" >&2
    printf 'Press Return to close this window. ' >&2
    read -r _ || true
    exit 1
fi

exec "$uv" run --project "$repo" zipseal-gui
