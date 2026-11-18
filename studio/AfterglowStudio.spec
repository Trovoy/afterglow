# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_data_files
from PyInstaller.utils.hooks import collect_all

import glob, os, re
# ffmpeg (essentials build from https://www.gyan.dev/ffmpeg/builds/) is bundled for replica building.
FF = os.environ.get('AFTERGLOW_FFMPEG_DIR')
if not FF or not os.path.isfile(os.path.join(FF, 'bin', 'ffmpeg.exe')):
    raise SystemExit('set AFTERGLOW_FFMPEG_DIR to an unpacked ffmpeg build (folder with bin/ffmpeg.exe, LICENSE, README.txt)')
def _ver(p):
    return tuple(int(x) for x in re.search(r'afterglow-fw-([\d.]+)\.zip$', p).group(1).split('.'))
LATEST_FW = max(glob.glob('../firmware/dist/afterglow-fw-*.zip'), key=_ver)   # newest firmware ships with the app
datas = [('ui', 'ui'), (LATEST_FW, 'firmware'), ('../THIRD_PARTY_NOTICES.txt', '.'), (FF + '/LICENSE', 'ffmpeg'), (FF + '/README.txt', 'ffmpeg')]
binaries = [(FF + '/bin/ffmpeg.exe', 'ffmpeg')]   # replica building (the original video plays inside the app)
hiddenimports = []
# numpy 2.5 imports parts of numpy._core from C code (e.g. numpy._core._exceptions); PyInstaller can't see
# those imports, so the frozen app failed with "No module named numpy._core._exceptions". Bundle all of numpy.
from PyInstaller.utils.hooks import collect_submodules
hiddenimports += collect_submodules('numpy', filter=lambda n: not any(s in n for s in ('.tests', 'numpy.f2py', 'numpy.testing', 'numpy.distutils')))
datas += collect_data_files('esptool')
tmp_ret = collect_all('pyaudiowpatch')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('webview')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('pythonnet')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('clr_loader')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    ['app.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
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
    [],
    exclude_binaries=True,
    name='AfterglowStudio',
    icon='assets/afterglow.ico',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
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
    upx=True,
    upx_exclude=['ffmpeg.exe'],
    name='AfterglowStudio',
)
