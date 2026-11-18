"""Firmware packages and USB flashing (single or batch, one esptool process per board)."""
import hashlib
import json
import re
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path

import device


FIRMWARE_NAMES = ('afterglow-fw',)


class PackageError(Exception):
    pass


def load_package(path):
    path = Path(path)
    with zipfile.ZipFile(path) as z:
        manifest = json.loads(z.read('manifest.json'))
        blobs = {}
        for entry in manifest['files']:
            data = z.read(entry['file'])
            if hashlib.sha256(data).hexdigest() != entry['sha256'] or len(data) != entry['size']:
                raise PackageError(f"{entry['file']} 校验失败，包可能损坏")
            blobs[entry['file']] = data
    if manifest.get('chip') != 'esp32':
        raise PackageError('该固件包不适用于 ESP32')
    if manifest.get('name') not in FIRMWARE_NAMES:
        raise PackageError('这不是 Afterglow 控制器的固件包')
    return manifest, blobs


def esptool_cmd():
    # Frozen exe: the app re-launches itself with --esptool (see studio.py); dev: python -m esptool.
    if getattr(sys, 'frozen', False):
        return [sys.executable, '--esptool']
    return [sys.executable, '-m', 'esptool']


def wifi_update(host, manifest, blobs, log=print):
    """Upload firmware.bin to a board's hotspot (PC must be joined to its Afterglow-XXXX Wi-Fi)."""
    import urllib.request
    import uuid
    data = blobs['firmware.bin']
    boundary = uuid.uuid4().hex
    body = (f'--{boundary}\r\nContent-Disposition: form-data; name="fw"; filename="firmware.bin"\r\n'
            f'Content-Type: application/octet-stream\r\n\r\n').encode() + data + f'\r\n--{boundary}--\r\n'.encode()
    log(f'{host}: 通过 Wi-Fi 上传 {manifest["version"]}（{len(data)//1024} KB）…')
    req = urllib.request.Request(f'http://{host}/update', data=body, method='POST',
                                 headers={'Content-Type': f'multipart/form-data; boundary={boundary}'})
    with urllib.request.urlopen(req, timeout=120) as r:
        reply = r.read().decode(errors='replace')
    if reply.strip() != 'OK':
        raise RuntimeError(f'{host}: 更新失败：{reply}')
    log(f'{host}: 上传完成，等待控制器重启…')
    deadline = time.time() + 25
    while time.time() < deadline:
        time.sleep(2)
        try:
            with urllib.request.urlopen(f'http://{host}/api?c=hello', timeout=3) as r:
                info = json.loads(r.read())
            if info.get('ver') == manifest['version']:
                log(f"{host}: 完成，版本 {info['ver']}")
                return info
        except Exception:
            continue
    raise RuntimeError(f'{host}: 上传成功，但未能确认新版本（电脑可能未重新连接热点）')


class FlashError(RuntimeError):
    """A failed flash with a plain-language explanation (helpdesk.explain_flash)."""
    def __init__(self, port, info):
        super().__init__(f"{port}: {info['title']}")
        self.port, self.info = port, info


def _esptool(port, args, baud, log, progress, sizes):
    """Run esptool once. Returns (exit code, full output). progress(pct) follows the bytes written."""
    cmd = esptool_cmd() + ['--chip', 'esp32', '--port', port, '--baud', str(baud),
                           '--before', 'default_reset', '--after', 'hard_reset',
                           'write_flash', '-z', '--flash_mode', 'dio', '--flash_freq', '40m',
                           '--flash_size', 'detect'] + args
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, encoding='utf-8', errors='replace', creationflags=flags)
    out, total = [], sum(sz for _, sz in sizes) or 1
    for line in proc.stdout:
        line = line.strip()
        out.append(line)
        m = re.search(r'Writing at 0x([0-9a-f]+)\.*\s*\((\d+) ?%\)', line)
        if m and progress:
            addr = int(m.group(1), 16)
            done = sum(sz for off, sz in sizes if off + sz <= addr)
            cur = next(((off, sz) for off, sz in sizes if off <= addr < off + sz), None)
            if cur:
                done += cur[1] * int(m.group(2)) / 100
            progress(min(99.0, 100 * done / total))
        if line and ('Writing at' not in line or line.endswith('(100 %)')):
            log(f'{port}: {line}')
    return proc.wait(), '\n'.join(out)


def flash(port, manifest, blobs, app_only=False, log=print, baud=460800, progress=None):
    """Flash one board and confirm the new version answers. Returns hello dict.
    Raises FlashError with a plain-language explanation; a broken transfer is retried once at 115200 baud."""
    import helpdesk
    # App-only also rewrites boot_app0.bin (the OTA boot selector): after a Wi-Fi/phone update the board boots the
    # second app slot, and a USB write to the first slot alone would be ignored. Settings and shows are not touched.
    files = [f for f in manifest['files'] if not app_only or f['file'] in ('firmware.bin', 'boot_app0.bin')]
    with tempfile.TemporaryDirectory() as tmp:
        args, sizes = [], []
        for f in files:
            pth = Path(tmp) / f['file']
            pth.write_bytes(blobs[f['file']])
            args += [hex(f['offset']), str(pth)]
            sizes.append((f['offset'], f['size']))
        if not app_only:   # factory state: blank the settings and show storage (0xFF = erased flash)
            for e in manifest.get('erase_on_full', []):
                pth = Path(tmp) / f"blank_{e['name']}.bin"
                pth.write_bytes(bytes([0xFF]) * e['size'])
                args += [hex(e['offset']), str(pth)]
                sizes.append((e['offset'], e['size']))
        sizes.sort()
        log(f'{port}: 开始烧录 {manifest["name"]} {manifest["version"]}' + ('（仅程序）' if app_only else '（完整安装，清空设置和节目）'))
        code, out = _esptool(port, args, baud, log, progress, sizes)
        if code != 0:
            info = helpdesk.explain_flash(out)
            if info['kind'] in ('link', 'other') and baud > 115200:
                log(f'{port}: 传输不稳定，降低速度再试一次…')
                code, out = _esptool(port, args, 115200, log, progress, sizes)
                info = helpdesk.explain_flash(out) if code else None
            if code != 0:
                raise FlashError(port, info)
    if progress:
        progress(100.0)
    # Board reboots after flashing; give it time and confirm the version.
    deadline = time.time() + 8
    while time.time() < deadline:
        time.sleep(0.8)
        info = device.probe(port)
        if info.get('fw'):
            if info.get('ver') != manifest['version'] or helpdesk.firmware_is_older(info, manifest['version'], manifest.get('built')):
                raise FlashError(port, {'kind': 'stale', 'title': f"写入完成，但控制器还在运行旧固件（{info.get('ver')} · {info.get('built')}）",
                                        'steps': ['改用“完整安装”再刷一次（会清空设置和节目）', '还不行就点“一键诊断”，把报告发到群里']})
            log(f"{port}: 完成，版本 {info['ver']}，MAC {info.get('mac')}")
            return info
    raise RuntimeError(f'{port}: 烧录完成，但控制器无响应')
