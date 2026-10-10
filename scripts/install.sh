#!/usr/bin/env sh
# Install zipseal's commands (zipseal, and zipseal-gui once it exists) on PATH.
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

case "${1:-}" in
    "") uv tool install --force --editable "$repo" ;;
    --release) uv tool install --force "$repo" ;;
    --uninstall) uv tool uninstall zipseal; exit 0 ;;
    *) echo "usage: $0 [--release | --uninstall]" >&2; exit 2 ;;
esac

bin=$(uv tool dir --bin)
case ":$PATH:" in
    *":$bin:"*) ;;
    *) echo "install.sh: $bin is not on PATH. Run: uv tool update-shell" >&2 ;;
esac
echo "install.sh: installed. Try: zipseal --help"
