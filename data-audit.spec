# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['data_quality_auditor/main.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='Data Quality Auditor',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

from pathlib import Path
import shutil

package_dir = Path(DISTPATH) / "Data Quality Auditor"
package_dir.mkdir(parents=True, exist_ok=True)
(package_dir / "input").mkdir(exist_ok=True)
(package_dir / "reports").mkdir(exist_ok=True)
built_exe = Path(DISTPATH) / "Data Quality Auditor.exe"
target_exe = package_dir / "Data Quality Auditor.exe"
if built_exe.exists():
    if target_exe.exists():
        target_exe.unlink()
    shutil.move(built_exe, target_exe)
old_exe = Path(DISTPATH) / "data-audit.exe"
try:
    if old_exe.exists():
        old_exe.unlink()
except OSError:
    pass
