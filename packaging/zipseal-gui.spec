# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the frozen zipseal-gui app (plan: GUI executables).

Build through ``packaging/build.py``: it generates the icons first and sets
``ZIPSEAL_BUILD_TARGET`` and ``ZIPSEAL_BUILD_VERSION`` in the environment, then
runs ``python -m PyInstaller`` on this file. PyInstaller ``exec``s a spec, so a
target or version cannot arrive as an argument, and the version therefore
defaults to ``pyproject.toml`` when the variable is unset.

``build.py`` is loaded by path. The directory name ``packaging`` must never sit
on ``sys.path``: it would shadow the PyPI ``packaging`` distribution.
"""

import importlib.util
import os
from pathlib import Path

_spec_dir = Path(SPECPATH)
_repo_root = _spec_dir.parent

_build_path = _spec_dir / "build.py"
_build_spec = importlib.util.spec_from_file_location("zipseal_packaging_build", _build_path)
if _build_spec is None or _build_spec.loader is None:
    raise SystemExit(f"zipseal-gui.spec: cannot load {_build_path}")
build = importlib.util.module_from_spec(_build_spec)
_build_spec.loader.exec_module(build)

_version = os.environ.get(build.BUILD_VERSION_ENV) or build.read_version()
# An empty value means a bare PyInstaller run: it gets the onedir tree only.
_target = os.environ.get(build.BUILD_TARGET_ENV, "")

# `collect_data_files()` returns repository-root-relative sources, so they are
# resolved here rather than against the spec's own directory. Both land under
# `_MEIPASS/zipseal/` beside the frozen `gui.py`, which is where `gui.ICON` and
# the `icon.png` fallback look for them. A "." destination would put them at
# the bundle root and the icon would silently not load.
_datas = [
    (str(_repo_root / source), destination)
    for source, destination in build.collect_data_files()
]

a = Analysis(
    [str(_spec_dir / "run_gui.py")],
    pathex=[str(_repo_root / "src")],
    binaries=[],
    datas=_datas,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["pytest", "hypothesis", "basedpyright", "yaml"],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    exclude_binaries=True,
    name="zipseal-gui",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    # UPX is a common antivirus false positive. The plan uses onedir to avoid that.
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="zipseal-gui",
)

# A reverse-DNS bundle identifier derived from the GitHub owner (kgforais1).
# Phase 1 adds the remaining Info.plist keys; this phase fills only the version
# and name fields `build.render_info_plist` renders.
if _target == "macos":
    app = BUNDLE(
        coll,
        name="zipseal-gui.app",
        bundle_identifier="io.github.kgforais1.zipseal-gui",
        version=_version,
        info_plist=build.render_info_plist(_version),
    )
