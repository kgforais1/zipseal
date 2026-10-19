#!/usr/bin/env sh
# Install zipseal's commands (zipseal and zipseal-gui) on PATH.
#
# Usage: scripts/install.sh            # editable: picks up source changes
#        scripts/install.sh --release  # snapshot copy of the current tree
#        scripts/install.sh --uninstall
set -eu

repo=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)

if ! command -v uv >/dev/null 2>&1; then
    echo "install.sh: uv is required: https://docs.astral.sh/uv/" >&2
    exit 1
fi

if [ "$#" -gt 1 ]; then
    echo "usage: $0 [--release | --uninstall]" >&2
    exit 2
fi

case "${1:-}" in
    "") uv tool install --force --editable "$repo" ;;
    --release) uv tool install --force "$repo" ;;
    --uninstall)
        # Not installed counts as done; any other failure is reported.
        if uv tool list | grep -q '^zipseal '; then
            uv tool uninstall zipseal
        else
            echo "install.sh: zipseal is not installed"
        fi
        exit 0
        ;;
    *) echo "usage: $0 [--release | --uninstall]" >&2; exit 2 ;;
esac

# Give the double-clickable launcher its icon (macOS only; never fails).
sh "$repo/scripts/set-icon.sh" "$repo/zipseal-gui.command" || true

bin=$(uv tool dir --bin)
case ":$PATH:" in
    *":$bin:"*) ;;
    *)
        echo "install.sh: installed, but $bin is not on PATH." >&2
        echo "install.sh: run 'uv tool update-shell', then open a new shell." >&2
        exit 1
        ;;
esac
echo "install.sh: installed. Try: zipseal --help, or zipseal-gui"
