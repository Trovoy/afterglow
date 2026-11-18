# -*- mode: python ; coding: utf-8 -*-
# One-file Afterglow installer (UI + logic only). build_release.ps1 writes build/setup/version.txt, runs
#   pyinstaller setup\AfterglowSetup.spec --distpath dist-setup --workpath build\setup-work
# and then appends build\setup\payload.zip to the produced exe.
import os
from PyInstaller.utils.hooks import collect_all

ROOT = os.path.dirname(SPECPATH)                     # studio/
STAGE = os.path.join(ROOT, 'build', 'setup')
VER = open(os.path.join(STAGE, 'version.txt'), encoding='utf-8').read().strip()

datas = [(os.path.join(STAGE, 'version.txt'), '.'),   # payload.zip is appended to the exe afterwards
         (os.path.join(ROOT, 'installer', 'license_zh.txt'), '.'), (os.path.join(ROOT, 'setup', 'ui'), 'ui')]
binaries, hiddenimports = [], []
for pkg in ('webview', 'pythonnet', 'clr_loader'):
    d, b, h = collect_all(pkg)
    datas += d; binaries += b; hiddenimports += h

a = Analysis([os.path.join(ROOT, 'setup', 'setup_app.py')], pathex=[os.path.join(ROOT, 'setup'), ROOT], binaries=binaries, datas=datas, hiddenimports=hiddenimports,
             excludes=['numpy', 'tkinter', 'esptool', 'serial', 'pyaudiowpatch', 'cryptography'], noarchive=False, optimize=0)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name=f'Afterglow-Studio-Setup-{VER}', icon=os.path.join(ROOT, 'assets', 'afterglow.ico'),
          debug=False, bootloader_ignore_signals=False, strip=False, upx=False, console=False, runtime_tmpdir=None,
          disable_windowed_traceback=False, uac_admin=False)
