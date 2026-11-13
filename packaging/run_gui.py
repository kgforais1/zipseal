"""The PyInstaller entry point for the frozen zipseal-gui app.

`zipseal.gui` and `zipseal.gui_view` have no ``__main__`` block of their own,
so the ``.spec`` targets this thin script. The import is guarded so that
loading the file (a smoke check, a test) never opens a window; only running it
does.
"""

import sys

from zipseal.gui import main

if __name__ == "__main__":
    sys.exit(main())
