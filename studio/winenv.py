"""Windows components the UI needs, checked before pywebview starts (used by Afterglow Studio and its installer).

  WebView2 Runtime        draws the whole interface (built into Windows 11; Windows 10 usually has it through Edge)
  .NET Framework 4.7.2+   pythonnet loads the window through it (built into Windows 10 1803 and later)

If one is missing, a plain Windows message box says so in Chinese and offers Microsoft's official download page.
AFTERGLOW_FAKE_MISSING=webview2,netfx pretends a component is missing (tests only).
"""
import os
import sys

WEBVIEW2_ID = '{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}'
WEBVIEW2_URL = 'https://go.microsoft.com/fwlink/p/?LinkId=2124703'       # Microsoft's Evergreen bootstrapper
NETFX_URL = 'https://dotnet.microsoft.com/zh-cn/download/dotnet-framework/net48'
NETFX_472 = 461808                                                     # 'Release' value of .NET Framework 4.7.2


def _reg(root, path, name):
    import winreg
    for view in (winreg.KEY_WOW64_32KEY, winreg.KEY_WOW64_64KEY):
        try:
            with winreg.OpenKey(root, path, 0, winreg.KEY_READ | view) as k:
                return winreg.QueryValueEx(k, name)[0]
        except OSError:
            continue
    return None


def webview2_version():
    import winreg
    fake = os.environ.get('AFTERGLOW_FAKE_MISSING', '')
    if 'webview2' in fake:
        return None
    for root, path in ((winreg.HKEY_LOCAL_MACHINE, rf'SOFTWARE\Microsoft\EdgeUpdate\Clients\{WEBVIEW2_ID}'),
                       (winreg.HKEY_CURRENT_USER, rf'Software\Microsoft\EdgeUpdate\Clients\{WEBVIEW2_ID}')):
        v = _reg(root, path, 'pv')
        if v and v != '0.0.0.0':
            return v
    return None


def netfx_ok():
    import winreg
    if 'netfx' in os.environ.get('AFTERGLOW_FAKE_MISSING', ''):
        return False
    rel = _reg(winreg.HKEY_LOCAL_MACHINE, r'SOFTWARE\Microsoft\NET Framework Setup\NDP\v4\Full', 'Release')
    return isinstance(rel, int) and rel >= NETFX_472


def missing():
    """[(name, what it is for, download url)] for every missing component; [] when all is fine."""
    if sys.platform != 'win32':
        return []
    out = []
    if not netfx_ok():
        out.append(('.NET Framework 4.8', '软件窗口需要它', NETFX_URL))
    if not webview2_version():
        out.append(('Microsoft Edge WebView2 运行库', '软件界面需要它', WEBVIEW2_URL))
    return out


def ensure(app_name):
    """Returns True when the UI can start. Otherwise explains in a message box, offers the download, returns False."""
    gone = missing()
    if not gone:
        return True
    import ctypes
    lines = '\n'.join(f'·  {name}（{why}）' for name, why, _ in gone)
    text = (f'{app_name} 需要先安装下面的 Windows 组件：\n\n{lines}\n\n'
            '这是微软官方提供的免费组件。\n点「是」（Yes）打开微软官网下载页面，装好后再打开 {app}。'.replace('{app}', app_name))
    MB_YESNO, MB_ICONWARNING, IDYES = 0x4, 0x30, 6
    if ctypes.windll.user32.MessageBoxW(0, text, f'{app_name} · 缺少系统组件', MB_YESNO | MB_ICONWARNING) == IDYES:
        for _, _, url in gone:
            os.startfile(url)
    return False
