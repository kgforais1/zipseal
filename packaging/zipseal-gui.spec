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

# `resolved_data_files()` returns absolute sources. Analysis resolves a
# relative `datas` path against this spec's directory (`packaging/`), so
# passing the repo-relative tuples through would look for
# `packaging/src/zipseal/icon.svg` and stop with "Unable to find". Both files
# land under `_MEIPASS/zipseal/` beside the frozen `gui.py`, which is where
# `gui.ICON` and the `icon.png` fallback look for them. A "." destination
# would put them at the bundle root and the icon would silently not load.
_datas = build.resolved_data_files()

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

# Windows gets the generated `.ico` and the rendered version resource. The
# macOS `.icns` goes to BUNDLE below; Linux has neither at the EXE level.
_exe_extra = {}
if _target == "windows":
    if not build.WINDOWS_ICO.is_file():
        raise SystemExit(
            f"zipseal-gui.spec: {build.WINDOWS_ICO} is missing; build.py generates it "
            "before PyInstaller runs"
        )
    _version_file = build.REPO_ROOT / "build" / "windows-version-info.txt"
    _version_file.write_text(build.render_windows_version_info(_version), encoding="utf-8")
    _exe_extra = {"icon": str(build.WINDOWS_ICO), "version": str(_version_file)}

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
    **_exe_extra,
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

# `build.BUNDLE_ID` is the reverse-DNS id from the GitHub owner. The icon has
# to be the generated `.icns`: without `icon=`, PyInstaller writes its generic
# `icon-windowed.icns` and the Dock icon is not zipseal's.
if _target == "macos":
    if not build.MACOS_ICNS.is_file():
        raise SystemExit(
            f"zipseal-gui.spec: {build.MACOS_ICNS} is missing; build.py generates it "
            "before PyInstaller runs"
        )
    app = BUNDLE(
        coll,
        name="zipseal-gui.app",
        icon=str(build.MACOS_ICNS),
        bundle_identifier=build.BUNDLE_ID,
        version=_version,
        info_plist=build.render_info_plist(_version),
    )
