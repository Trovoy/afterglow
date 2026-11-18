"""Plain-language explanations for the things fans get stuck on: no board found, missing USB driver, flashing
errors, and a one-click health check of a connected controller (with a report they can paste into the group).
"""
import json
import platform
import re
import subprocess
import sys

NO_WINDOW = 0x08000000 if sys.platform == 'win32' else 0
USB_SERIAL_VIDS = {'1A86': 'CH340', '10C4': 'CP210x', '0403': 'FTDI'}


# ---------------------------------------------------------------- USB
def usb_serial_chips():
    """USB-serial chips Windows can see, with or without a working driver.
    [{'chip': 'CH340', 'name': ..., 'ok': bool}]  (ok=False: plugged in but no driver / error)"""
    if sys.platform != 'win32':
        return []
    ps = ("Get-CimInstance Win32_PnPEntity | Where-Object { $_.PNPDeviceID -match '^USB\\\\VID_(1A86|10C4|0403)' } | "
          "Select-Object Name, PNPDeviceID, ConfigManagerErrorCode | ConvertTo-Json -Compress")
    try:
        r = subprocess.run(['powershell', '-NoProfile', '-NonInteractive', '-Command', ps], capture_output=True, text=True,
                           timeout=15, creationflags=NO_WINDOW)
        rows = json.loads(r.stdout or '[]')
    except Exception:
        return []
    if isinstance(rows, dict):
        rows = [rows]
    out = []
    for d in rows:
        vid = re.search(r'VID_([0-9A-F]{4})', d.get('PNPDeviceID') or '', re.I)
        chip = USB_SERIAL_VIDS.get(vid.group(1).upper(), 'USB 串口') if vid else 'USB 串口'
        out.append({'chip': chip, 'name': d.get('Name') or '', 'ok': d.get('ConfigManagerErrorCode') == 0 and 'COM' in (d.get('Name') or '')})
    return out


def no_port_hint():
    """Why the port list is empty, as {'title', 'steps'}."""
    chips = usb_serial_chips()
    if any(not c['ok'] for c in chips):
        chip = next(c['chip'] for c in chips if not c['ok'])
        return {'kind': 'driver', 'title': f'电脑认出了板子，但缺少 {chip} 驱动',
                'steps': [f'在浏览器搜索“{chip} 驱动”，到芯片厂家官网下载（CH340 是“沁恒”官网）',
                          '安装后拔掉数据线再插上',
                          '回到这里，会自动重新检测']}
    return {'kind': 'none', 'title': '没有检测到控制器',
            'steps': ['确认数据线两头都插紧了，ESP32 上的小灯应该会亮',
                      '换一根数据线试试：很多 Type-C 线只能充电，不能传数据',
                      '换一个电脑 USB 口，尽量不要插在扩展坞或键盘上']}


# ---------------------------------------------------------------- flashing
FLASH_RULES = [
    # (kind, patterns, title, steps)
    ('busy', [r'could not open port', r'PermissionError', r'Access is denied', r'拒绝访问', r'being used by another'],
     '端口被别的程序占用了',
     ['关掉其他可能在用这块板子的程序（串口助手、Arduino、另一个 Afterglow Studio）', '拔掉数据线重新插上，再试一次']),
    ('wrong_chip', [r'This chip is (ESP32-[A-Z0-9]+)', r'Unexpected chip id', r'not an? ESP32\b', r'Wrong --chip argument'],
     '这块板子的芯片型号不对',
     ['Afterglow 只支持经典 ESP32（30 针 Type-C 版）', 'ESP32-C3、S3、S2、Super Mini 等型号刷不了这个固件，请按 DIY 指南买对应的板子']),
    ('no_boot', [r'Failed to connect to ESP32', r'No serial data received', r'Timed out waiting for packet header', r'Wrong boot mode'],
     '板子没有进入刷机模式',
     ['按住 ESP32 上的 BOOT 键不放，再点一次“刷入固件”', '看到进度开始走了，就可以松开 BOOT 键', '还不行就换一根数据线']),
    ('link', [r'Invalid head of packet', r'Packet content transfer stopped', r'SerialException', r'ClearCommError',
              r'device (has been )?disconnected', r'Lost connection', r'MD5 of file does not match', r'Corrupt data',
              r'The device does not recognize the command'],
     '传输中断了，多半是数据线或接口接触不良',
     ['换一根数据线，或者换一个电脑 USB 口', '刷机过程中不要碰数据线和板子']),
]


def explain_flash(text):
    """Classify esptool output. Returns {'kind', 'title', 'steps', 'detail'}."""
    for kind, pats, title, steps in FLASH_RULES:
        for p in pats:
            m = re.search(p, text, re.I)
            if m:
                if kind == 'wrong_chip' and m.groups() and m.group(1):
                    title = f'这是 {m.group(1)}，不是 Afterglow 支持的 ESP32'
                return {'kind': kind, 'title': title, 'steps': steps, 'detail': m.group(0)}
    return {'kind': 'other', 'title': '刷机没有成功',
            'steps': ['拔掉数据线重新插上，再试一次', '还不行就点“一键诊断”，把报告发到群里问'], 'detail': ''}


# ---------------------------------------------------------------- health check
def _ver(v):
    try:
        return tuple(int(x) for x in str(v).split('.'))
    except ValueError:
        return (0,)


def _built(text):
    """'Nov 15 2026 12:07:42' (firmware __DATE__ __TIME__) or '2026-11-15T12:17:59' (package manifest) -> datetime."""
    from datetime import datetime
    for fmt in ('%b %d %Y %H:%M:%S', '%Y-%m-%dT%H:%M:%S'):
        try:
            return datetime.strptime(' '.join(str(text).split()), fmt)
        except (ValueError, TypeError):
            continue
    return None


def firmware_is_older(hello, latest, latest_built=None):
    """True when the bundled package is newer: higher version, or same version built later (> 2 min apart)."""
    if not latest:
        return False
    if _ver(hello.get('ver')) != _ver(latest):
        return _ver(hello.get('ver')) < _ver(latest)
    a, b = _built(hello.get('built')), _built(latest_built)
    return bool(a and b and (b - a).total_seconds() > 120)


RESET_TEXT = {'poweron': '正常上电', 'software': '软件重启（更新或重启命令）', 'external': '按了复位键', 'deepsleep': '休眠唤醒',
              'brownout': '供电电压不足', 'panic': '程序异常', 'task_wdt': '程序卡住后自动恢复', 'int_wdt': '程序卡住后自动恢复',
              'wdt': '程序卡住后自动恢复'}


def health_check(app_version, latest_fw, hello, status, config, latest_built=None):
    """Checks for a connected controller. Returns (items, report_text).
    items: [{'name', 'state': 'ok'|'warn'|'bad', 'text'}]"""
    items = []

    def add(name, state, text):
        items.append({'name': name, 'state': state, 'text': text})

    ver = hello.get('ver', '?')
    if firmware_is_older(hello, latest_fw, latest_built):
        add('固件版本', 'warn', f'{ver}，软件里有更新的固件 {latest_fw}（“烧录 / 更新”页面，选“仅更新程序”）')
    else:
        add('固件版本', 'ok', f'{ver}，已是最新')
    add('射频模块', 'ok' if hello.get('radio') and status.get('radio') else 'bad',
        'E07 工作正常' if hello.get('radio') and status.get('radio') else 'E07 没有响应：检查 E07 的 1～7 号线，尤其是 3V3 和 GND')
    tx = int(status.get('tx_errors') or 0)
    add('发射', 'ok' if tx == 0 else 'warn', '没有发射错误' if tx == 0 else f'有 {tx} 次发射错误：检查 E07 的接线是否松动')
    if not hello.get('audio'):
        add('麦克风', 'warn', '没有检测到麦克风（可选配件；没接的话忽略即可）')
    else:
        lvl = float(status.get('level') or 0)
        add('麦克风', 'ok' if lvl > 0.0003 else 'warn',
            '工作正常，能听到声音' if lvl > 0.0003 else '接上了但几乎没声音：检查 SD、WS、SCK 三根线，L/R 要接 GND')
    ap = status.get('ap') or {}
    if hello.get('wifi') and ap.get('up', True):
        add('手机热点', 'ok', f"{hello.get('ssid', 'Afterglow')} 已开启，当前 {status.get('wifi_clients', 0)} 台手机连接")
    else:
        add('手机热点', 'warn', '热点没有开启：长按控制器按键 3 秒可以打开')
    reset = status.get('reset') or hello.get('reset') or ''
    bad_reset = reset in ('brownout', 'panic', 'task_wdt', 'int_wdt', 'wdt')
    add('上次重启', 'warn' if bad_reset else 'ok',
        RESET_TEXT.get(reset, reset or '未知') + ('：换一根数据线或 USB 口，供电不稳会导致重启' if reset == 'brownout' else ''))

    lines = ['Afterglow 诊断报告',
             f"软件 {app_version} · 固件 {ver}（{hello.get('built', '?')}）· {platform.system()} {platform.release()}",
             f"频率 {status.get('freq', config.get('freq', '?'))} MHz · 功率 {status.get('dbm', config.get('dbm', '?'))} dBm · "
             f"运行 {int(status.get('uptime_s') or 0) // 60} 分钟 · 启动 {status.get('boots', '?')} 次 · 重启原因 {reset or '?'}",
             '']
    mark = {'ok': '✓', 'warn': '!', 'bad': '✗'}
    lines += [f"{mark[i['state']]} {i['name']}：{i['text']}" for i in items]
    return items, '\n'.join(lines)


def offline_report(app_version, ports, hint):
    """Report when no controller is connected (so the group can still help)."""
    lines = ['Afterglow 诊断报告（未连接控制器）', f'软件 {app_version} · {platform.system()} {platform.release()}', '']
    if ports:
        for p in ports:
            state = '固件 ' + p['ver'] if p.get('fw') else ('被占用' if p.get('busy') else '没有 Afterglow 固件')
            lines.append(f"· {p['port']} {p.get('desc', '')}：{state}")
    else:
        lines.append('· 没有串口设备')
    if hint:
        lines.append(f"! {hint['title']}")
    chips = usb_serial_chips()
    if chips:
        lines.append('USB 芯片：' + '；'.join(f"{c['chip']}（{'驱动正常' if c['ok'] else '没有驱动'}）" for c in chips))
    return '\n'.join(lines)
