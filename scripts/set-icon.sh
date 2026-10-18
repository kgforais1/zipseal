#!/bin/sh
# Give a file the zipseal icon in Finder (macOS only).
#
# Usage: scripts/set-icon.sh FILE
#
# The icon is stored in FILE's extended attributes, so git sees no change.
# On other systems, or if anything fails, it does nothing and exits 0: an
# icon is never worth blocking an install or a launch.
set -u

if [ "$#" -ne 1 ]; then
    echo "usage: $0 FILE" >&2
    exit 2
fi

[ "$(uname -s)" = Darwin ] || exit 0
command -v osascript >/dev/null 2>&1 || exit 0

icon=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)/assets/icon.svg
target=$(CDPATH= cd -- "$(dirname -- "$1")" && pwd)/$(basename -- "$1") || exit 0

# NSImage reads SVG directly, so no raster copy of the icon is needed.
osascript -l JavaScript - "$icon" "$target" >/dev/null 2>&1 <<'EOF' || true
function run(argv) {
    ObjC.import("AppKit");
    var image = $.NSImage.alloc.initWithContentsOfFile(argv[0]);
    if (image.isNil()) return "no image";
    return String($.NSWorkspace.sharedWorkspace.setIconForFileOptions(image, argv[1], 0));
}
EOF
exit 0
