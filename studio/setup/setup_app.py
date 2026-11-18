"""Afterglow Studio installer / uninstaller with its own UI (ui/setup.html in a frameless pywebview window).

Built as one exe (AfterglowSetup.spec) carrying version.txt and the licence; the Studio program (payload.zip) is
appended to the end of the exe by build_release.ps1, so it is not unpacked at every start (that took ~6 s).
Per-user install, no administrator rights:
  program      %LOCALAPPDATA%\\Programs\\Afterglow Studio      (shows\\ and profiles\\ there are user data, kept on upgrade)
  shortcuts    Start menu + optional desktop
  uninstall    HKCU\\...\\Uninstall\\AfterglowStudio -> <program>\\uninstall.exe --uninstall  (a copy of this exe)

Command line (also used by the tests):
  --uninstall            uninstall mode
  --silent               no window; exit code 0 = ok
  --dir PATH             install somewhere else (tests)
  --no-desktop           no desktop shortcut
  --keep-registry        do not touch the Windows uninstall entry (tests)
  --no-shortcuts         do not create or remove any shortcut (tests)
  --delete-data          uninstall: also remove shows\\ and profiles\\
"""
import time as _t0mod
_T0 = _t0mod.time()
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import winreg
import zipfile
from pathlib import Path

APP = 'Afterglow Studio'
EXE = 'AfterglowStudio.exe'
USER_DATA = {'shows', 'profiles'}
REG_KEY = r'Software\Microsoft\Windows\CurrentVersion\Uninstall\AfterglowStudio'
OLD_INNO_KEY = r'Software\Microsoft\Windows\CurrentVersion\Uninstall\{8582A167-705C-4B1D-936B-3CD43F4BCF12}_is1'
NO_WINDOW = 0x08000000
SHORTCUTS = '--no-shortcuts' not in sys.argv
DETACHED, BREAKAWAY = 0x00000008, 0x01000000


def spawn_free(cmd, cwd=None):
    """Start a process that outlives this one. The one-file bootloader puts its children in a job object that is
    killed when it exits, so break away from the job (fall back to WMI, whose processes are never in our job)."""
    try:
        return subprocess.Popen(cmd, cwd=cwd, creationflags=DETACHED | BREAKAWAY | NO_WINDOW, close_fds=True)
    except OSError:
        line = subprocess.list2cmdline(cmd).replace("'", "''")
        cwdp = (cwd or '').replace("'", "''")
        ps = f"Invoke-CimMethod Win32_Process Create -Arguments @{{CommandLine='{line}'; CurrentDirectory={('$null' if not cwd else repr(cwdp))}}}"
        subprocess.run(['powershell', '-NoProfile', '-NonInteractive', '-Command', ps], capture_output=True, creationflags=NO_WINDOW)


def payload():
    """The program to install: a zip appended to this exe (zipfile copes with the leading exe bytes);
    when running from source, the staged build/setup/payload.zip."""
    if getattr(sys, 'frozen', False):
        return sys.executable
    return Path(__file__).resolve().parent.parent / 'build' / 'setup' / 'payload.zip'


def res(name):
    base = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent))
    return base / name


def arg(name, default=None):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default


def default_dir():
    return Path(os.environ['LOCALAPPDATA']) / 'Programs' / APP


def registered_location():
    """Folder of an existing install (from our uninstall entry), so upgrades land in the same place."""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_KEY) as k:
            loc = Path(winreg.QueryValueEx(k, 'InstallLocation')[0])
        return loc if (loc / EXE).exists() else None
    except OSError:
        return None


def version():
    try:
        return res('version.txt').read_text(encoding='utf-8').strip()
    except OSError:
        return 'dev'


class AppRunning(RuntimeError):
    pass


def running_in(target):
    """PIDs of Afterglow Studio processes whose exe lives in `target` (another copy elsewhere is left alone)."""
    import ctypes
    from ctypes import wintypes
    r = subprocess.run(['tasklist', '/FI', f'IMAGENAME eq {EXE}', '/FO', 'CSV', '/NH'], capture_output=True, text=True, creationflags=NO_WINDOW)
    want = os.path.normcase(str(Path(target).resolve()))
    pids = []
    for line in r.stdout.splitlines():
        parts = [x.strip('"') for x in line.split('","')]
        if len(parts) < 2 or not parts[1].isdigit():
            continue
        pid = int(parts[1])
        h = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)          # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            continue
        try:
            buf = ctypes.create_unicode_buffer(1024); n = wintypes.DWORD(1024)
            if ctypes.windll.kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(n)):
                if os.path.normcase(os.path.dirname(buf.value)) == want:
                    pids.append(pid)
        finally:
            ctypes.windll.kernel32.CloseHandle(h)
    return pids


def app_running(target):
    return bool(running_in(target))


def close_app(target):
    """Ask the Afterglow Studio in `target` to close, then force it after 3 s."""
    pids = running_in(target)
    for pid in pids:
        subprocess.run(['taskkill', '/PID', str(pid)], capture_output=True, creationflags=NO_WINDOW)
    for _ in range(30):
        if not app_running(target):
            return
        time.sleep(0.1)
    for pid in running_in(target):
        subprocess.run(['taskkill', '/F', '/T', '/PID', str(pid)], capture_output=True, creationflags=NO_WINDOW)
    time.sleep(0.5)


def remove_tree(p):
    """Delete a file/folder; junctions and links are removed themselves, never followed (old installers linked data)."""
    p = Path(p)
    if not os.path.lexists(p):
        return
    if p.is_symlink() or (hasattr(os.path, 'isjunction') and os.path.isjunction(p)):
        try:
            os.rmdir(p)
        except OSError:
            os.unlink(p)
        return
    if p.is_dir():
        for c in p.iterdir():
            remove_tree(c)
        p.rmdir()
    else:
        try:
            p.unlink()
        except PermissionError:
            os.chmod(p, 0o666); p.unlink()


def make_shortcuts(target_exe, desktop):
    """Start-menu (and desktop) shortcuts through WScript.Shell; the desktop path is resolved by Windows (OneDrive-safe)."""
    exe = str(target_exe).replace("'", "''")
    ps = f"""
$s = New-Object -ComObject WScript.Shell
$places = @([Environment]::GetFolderPath('Programs'))
{"$places += [Environment]::GetFolderPath('Desktop')" if desktop else ''}
foreach ($d in $places) {{
  $l = $s.CreateShortcut((Join-Path $d '{APP}.lnk'))
  $l.TargetPath = '{exe}'; $l.WorkingDirectory = (Split-Path '{exe}'); $l.IconLocation = '{exe},0'; $l.Description = '{APP}'
  $l.Save()
}}"""
    subprocess.run(['powershell', '-NoProfile', '-NonInteractive', '-Command', ps], check=True, capture_output=True, creationflags=NO_WINDOW)


def remove_shortcuts():
    ps = f"""foreach ($d in @([Environment]::GetFolderPath('Programs'), [Environment]::GetFolderPath('Desktop'))) {{
  $f = Join-Path $d '{APP}.lnk'; if (Test-Path $f) {{ Remove-Item $f -Force }} }}"""
    subprocess.run(['powershell', '-NoProfile', '-NonInteractive', '-Command', ps], capture_output=True, creationflags=NO_WINDOW)


def folder_kb(p):
    return sum(f.stat().st_size for f in Path(p).rglob('*') if f.is_file()) // 1024


def write_registry(target):
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, REG_KEY) as k:
        vals = {'DisplayName': APP, 'DisplayVersion': version(), 'Publisher': 'Afterglow 余场',
                'DisplayIcon': str(target / EXE), 'InstallLocation': str(target),
                'UninstallString': f'"{target / "uninstall.exe"}" --uninstall',
                'QuietUninstallString': f'"{target / "uninstall.exe"}" --uninstall --silent',
                'URLInfoAbout': 'https://github.com/Trovoy/afterglow', 'HelpLink': 'https://github.com/Trovoy/afterglow/issues'}
        for n, v in vals.items():
            winreg.SetValueEx(k, n, 0, winreg.REG_SZ, v)
        winreg.SetValueEx(k, 'EstimatedSize', 0, winreg.REG_DWORD, folder_kb(target))
        winreg.SetValueEx(k, 'NoModify', 0, winreg.REG_DWORD, 1)
        winreg.SetValueEx(k, 'NoRepair', 0, winreg.REG_DWORD, 1)
    for old in (OLD_INNO_KEY,):          # entry left by the earlier Inno Setup build, now replaced by ours
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, old)
        except OSError:
            pass


def delete_registry():
    try:
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, REG_KEY)
    except OSError:
        pass


# ---------------------------------------------------------------- install / uninstall work
def install(target, desktop, progress, registry=True):
    target = Path(target)
    if app_running(target):
        raise AppRunning('Afterglow Studio 还开着，需要先关掉它才能安装。')
    progress(2, '正在准备')
    try:
        target.mkdir(parents=True, exist_ok=True)
        probe = target / '.afterglow-write-test'
        probe.write_bytes(b''); probe.unlink()
    except PermissionError:
        raise RuntimeError('没有权限写入这个位置（比如 C:\\Program Files 需要管理员权限）。请换一个文件夹，例如 D:\\软件。')
    others = [c for c in target.iterdir() if c.name.lower() not in USER_DATA]
    if others and not (target / EXE).exists():
        # never wipe a folder that is not an earlier Afterglow install
        raise RuntimeError('这个文件夹里已经有别的文件。请选一个空文件夹，或者用默认位置。')
    for c in others:                                 # old program files go, user data stays
        remove_tree(c)
    with zipfile.ZipFile(payload()) as z:
        items = [i for i in z.infolist() if not i.is_dir()]
        total = sum(i.file_size for i in items) or 1
        done = 0
        for i in items:
            z.extract(i, target)
            done += i.file_size
            progress(4 + 86 * done / total, '正在复制文件')
    progress(91, '正在创建快捷方式')
    if getattr(sys, 'frozen', False):
        # the uninstaller is this exe without the appended program (a plain copy would not carry the download mark)
        with zipfile.ZipFile(sys.executable) as z:
            cut = min(i.header_offset for i in z.infolist())
        with open(sys.executable, 'rb') as src, open(target / 'uninstall.exe', 'wb') as dst:
            left = cut
            while left:
                block = src.read(min(left, 1 << 20)); dst.write(block); left -= len(block)
    if SHORTCUTS:
        make_shortcuts(target / EXE, desktop)
    if registry:
        progress(97, '正在登记到系统')
        write_registry(target)
    progress(100, '完成')


def uninstall(target, delete_data, progress, registry=True):
    target = Path(target)
    if app_running(target):
        raise AppRunning('Afterglow Studio 还开着，需要先关掉它才能卸载。')
    progress(5, '正在删除快捷方式')
    if SHORTCUTS:
        remove_shortcuts()
    me = Path(sys.executable).resolve() if getattr(sys, 'frozen', False) else None
    kids = [c for c in target.iterdir()] if target.exists() else []
    for n, c in enumerate(kids):
        if c.name.lower() in USER_DATA and not delete_data:
            continue
        if me and c.resolve() == me:
            continue                                  # the running uninstaller: removed after exit
        remove_tree(c)
        progress(10 + 80 * (n + 1) / max(1, len(kids)), '正在删除文件')
    if registry:
        progress(95, '正在从系统中移除')
        delete_registry()
    progress(100, '完成')
    global PENDING_SELF_DELETE
    if me and me.parent == target.resolve():
        PENDING_SELF_DELETE = (me, target)          # done after the window closes, see delete_self_later()


PENDING_SELF_DELETE = None


def delete_self_later():
    """The running uninstall.exe cannot delete itself: a detached helper retries until this process has exited,
    then removes the folder too if nothing (no kept user data) is left in it."""
    if not PENDING_SELF_DELETE:
        return
    exe, folder = (str(x).replace("'", "''") for x in PENDING_SELF_DELETE)
    ps = (f"for ($i = 0; $i -lt 60; $i++) {{ Start-Sleep -Milliseconds 500; "
          f"try {{ Remove-Item -LiteralPath '{exe}' -Force -ErrorAction Stop; break }} catch {{}} }}; "
          f"try {{ [IO.Directory]::Delete('{folder}') }} catch {{}}")
    spawn_free(['powershell', '-NoProfile', '-NonInteractive', '-WindowStyle', 'Hidden', '-Command', ps])


# ---------------------------------------------------------------- window
class Api:
    def __init__(self, mode, target, registry):
        self._mode, self._target, self._registry = mode, Path(target), registry
        self._window = None

    def info(self):
        upgrade = (self._target / EXE).exists() and self._mode == 'install'
        lic = res('license_zh.txt').read_text(encoding='utf-8-sig') if res('license_zh.txt').exists() else ''
        return {'version': version(), 'path': str(self._target), 'upgrade': upgrade, 'mode': self._mode, 'license': lic}

    def _progress(self, pct, text):
        self._window.evaluate_js(f'onProgress({pct:.1f}, {json.dumps(text)})')

    def _run(self, fn, *a):
        def job():
            try:
                fn(*a, self._progress, registry=self._registry)
                time.sleep(0.3)
                self._window.evaluate_js('onFinished(true)')
            except Exception as e:      # shown to the user in the window
                code = 'running' if isinstance(e, AppRunning) else 'error'
                self._window.evaluate_js(f'onFinished(false, {json.dumps(str(e) or e.__class__.__name__)}, {json.dumps(code)})')
        threading.Thread(target=job, daemon=True).start()

    def choose_dir(self):
        import webview
        r = self._window.create_file_dialog(webview.FOLDER_DIALOG, directory=str(self._target.parent))
        if not r:
            return None
        p = Path(r[0] if isinstance(r, (list, tuple)) else r)
        if p.name.lower() != APP.lower():            # always install into its own sub-folder
            p = p / APP
        self._target = p
        return {'path': str(p), 'upgrade': (p / EXE).exists()}

    def install(self, desktop):
        self._run(install, self._target, bool(desktop))

    def uninstall(self, delete_data):
        self._run(uninstall, self._target, bool(delete_data))

    def close_app(self):
        close_app(self._target)
        return not app_running(self._target)

    def open_app(self):
        spawn_free([str(self._target / EXE)], cwd=str(self._target))

    def log(self, msg):
        with open(Path(os.environ.get('TEMP', '.')) / 'afterglow_setup.log', 'a', encoding='utf-8') as f:
            f.write(time.strftime('%H:%M:%S ') + str(msg) + '\n')

    def ready(self):
        tlog('page ready -> show')
        if self._window and not getattr(self, '_shown', False):
            self._shown = True
            self._window.show()

    def minimize(self):
        self._window.minimize()

    def close(self):
        threading.Thread(target=lambda: (time.sleep(0.05), self._window.destroy()), daemon=True).start()


def win11():
    return sys.getwindowsversion().build >= 22000


def round_corners(win):
    try:
        import ctypes
        hwnd = win.native.Handle.ToInt32()
        pref = ctypes.c_int(2)                              # DWMWCP_ROUND (Windows 11)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 33, ctypes.byref(pref), 4)
    except Exception:
        pass


def tlog(what):
    """Startup timing (AFTERGLOW_SETUP_TIMING=1): seconds since the process was created."""
    if not os.environ.get('AFTERGLOW_SETUP_TIMING'):
        return
    import ctypes
    from ctypes import wintypes
    c, e, k, u = (wintypes.FILETIME() for _ in range(4))
    ctypes.windll.kernel32.GetProcessTimes(ctypes.windll.kernel32.GetCurrentProcess(), *(ctypes.byref(x) for x in (c, e, k, u)))
    created = ((c.dwHighDateTime << 32) | c.dwLowDateTime) / 1e7 - 11644473600
    with open(Path(os.environ.get('TEMP', '.')) / 'afterglow_setup_timing.log', 'a', encoding='utf-8') as f:
        f.write(f'{time.time() - created:6.2f}s  {what}\n')


def main():
    tlog(f'python main (module import took {time.time() - _T0:.2f}s)')
    me = Path(sys.executable).name.lower() if getattr(sys, 'frozen', False) else ''
    mode = 'uninstall' if ('--uninstall' in sys.argv or me == 'uninstall.exe') else 'install'   # double-clicked uninstall.exe too
    registry = '--keep-registry' not in sys.argv
    if mode == 'uninstall' and getattr(sys, 'frozen', False) and '--dir' not in sys.argv:
        target = Path(sys.executable).resolve().parent       # uninstall.exe lives in the program folder
    else:
        target = Path(arg('--dir', str(registered_location() or default_dir())))
    if '--silent' in sys.argv:
        quiet = lambda pct, text: None                       # noqa: E731
        try:
            if mode == 'install':
                install(target, '--no-desktop' not in sys.argv, quiet, registry)
            else:
                uninstall(target, '--delete-data' in sys.argv, quiet, registry)
        except Exception as e:
            print(e, file=sys.stderr); sys.exit(1)
        delete_self_later()
        return
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))   # winenv.py (shared with the app) when run from source
    import winenv
    if not winenv.ensure('Afterglow Studio 安装程序'):     # the installer window needs WebView2 / .NET too
        return
    import webview
    tlog('webview imported')
    api = Api(mode, target, registry)
    title = f'{APP} 卸载' if mode == 'uninstall' else f'{APP} 安装'
    win = webview.create_window(title, str(res('ui') / 'setup.html'), js_api=api, width=816, height=539, resizable=False,   # client area 800x500 (Windows keeps frame insets)
                                frameless=True, easy_drag=False, background_color='#0E1016', hidden=True,
                                shadow=win11())   # DWM shadow draws a 1-px white frame on Windows 10
    api._window = win
    win.events.shown += lambda: round_corners(win)
    win.events.loaded += lambda: (tlog('page loaded'), api.ready())   # DOM is in place: show now (timers are throttled while hidden)
    # the window stays hidden until the page has its content (api.ready); show it anyway after 3 s
    threading.Thread(target=lambda: (time.sleep(3), api.ready()), daemon=True).start()
    if os.environ.get('AFTERGLOW_SETUP_DEMO'):              # tests: press the main button by itself
        def demo():
            time.sleep(2.5)
            win.evaluate_js("$('desk').checked = false; STATE === 'uninstall' ? doUninstall() : doInstall()")
            if os.environ.get('AFTERGLOW_SETUP_DEMO') in ('close', 'open'):   # and finish like the user would
                time.sleep(6)
                if os.environ.get('AFTERGLOW_SETUP_DEMO') == 'open':
                    win.evaluate_js("api('open_app')"); time.sleep(1.5)
                win.destroy()
        win.events.shown += lambda: threading.Thread(target=demo, daemon=True).start()
    tlog('webview.start')
    webview.start()
    delete_self_later()
    os._exit(0)


if __name__ == '__main__':
    main()
