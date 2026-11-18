"""Afterglow Studio: web-based UI (pywebview / Edge WebView2) on top of the existing backend modules.

The page (ui/index.html) calls window.pywebview.api.<method>(...); long jobs report back through
window.onBackend({type, ...}) events. studio.py (Tk) stays as a fallback UI.
"""
import sys

if len(sys.argv) > 1 and sys.argv[1] == '--esptool':   # frozen exe re-entry used by flasher.py
    import os
    if sys.stdout is None:
        try:
            sys.stdout = os.fdopen(1, 'w', buffering=1, encoding='utf-8', errors='replace')
            sys.stderr = sys.stdout
        except OSError:
            sys.stdout = sys.stderr = open(os.devnull, 'w')
    import esptool
    sys.argv = ['esptool'] + sys.argv[2:]
    esptool._main()
    sys.exit(0)

import json
import os
import threading
import time
from pathlib import Path


def _unblock_downloaded_files():
    """Files unzipped from a download carry Windows' 'from the internet' mark (Zone.Identifier stream);
    .NET then refuses to load Python.Runtime.dll and pywebview fails with 'Failed to resolve
    Python.Runtime.Loader.Initialize'. Remove the mark from our own files before the UI loads."""
    if os.name != 'nt' or not getattr(sys, 'frozen', False):
        return
    root = Path(sys.executable).resolve().parent
    for dirpath, _dirs, files in os.walk(root):
        for name in files:
            try:
                os.remove(os.path.join(dirpath, name) + ':Zone.Identifier')
            except OSError:
                pass        # no mark, or a read-only install location


_unblock_downloaded_files()

import webview  # noqa: E402  (after the unblock above)

import device
import flasher
import helpdesk
import profiles
import videoserve

APP_VERSION = '0.4.3'


def base_dir():
    return profiles.base_dir()


def ui_dir():
    if getattr(sys, 'frozen', False):
        return Path(sys._MEIPASS) / 'ui'
    return Path(__file__).resolve().parent / 'ui'


class Api:
    def __init__(self):
        self._window = None
        self._dev = None
        self._log = []
        self._loopback = None
        self._loop_stop = threading.Event()
        self._player = None
        self._lock = threading.Lock()
        self._closing = False
        self._video = videoserve.VideoServer()   # the page can't read file:// videos

    # ---------- plumbing ----------
    def emit(self, kind, **data):
        # While the window closes, the UI thread is busy: evaluate_js would wait on it forever (white frozen window).
        if self._window and not self._closing:
            data['type'] = kind
            try:
                self._window.evaluate_js(f'window.onBackend && window.onBackend({json.dumps(data, ensure_ascii=False)})')
            except Exception:
                pass

    def _line(self, direction, text):
        if text.startswith('{"evt":"mic"') or text.startswith('{"evt":"onset"') or text.startswith('{"evt":"flash"'):
            return
        entry = f'{time.strftime("%H:%M:%S")} {direction} {text}'
        self._log.append(entry); self._log = self._log[-1500:]
        self.emit('log', line=entry)

    def _event(self, e):
        if e.get('evt') == 'mic':
            self.emit('mic', **e)
        elif e.get('evt') == 'disconnected':
            self._dev = None
            self.emit('disconnected', msg=e.get('msg', ''))
        elif e.get('evt') in ('tx_error', 'wake_done', 'button'):
            self.emit('device_event', **e)

    def _need(self):
        if not self._dev or not self._dev.alive:
            raise RuntimeError('请先连接控制器')
        return self._dev

    def _call(self, fn):
        try:
            return {'ok': True, 'data': fn()}
        except Exception as e:
            return {'ok': False, 'err': str(e)}

    def app_info(self):
        return {'version': APP_VERSION, 'base': str(base_dir())}

    # ---------- devices ----------
    def latest_firmware(self):
        pk = [p for p in self.packages() if not p.get('error')]
        return pk[0] if pk else None

    def scan(self):
        def work():
            busy = self._dev.port if self._dev and self._dev.alive else None
            lp = self.latest_firmware() or {}
            latest, latest_built = lp.get('version'), lp.get('built')
            rows = []
            for p in device.list_serial_ports():
                info = dict(self._dev.info or {}, connected=True) if p['port'] == busy else device.probe(p['port'])
                row = {**p, **info}
                # state for the guide: ready (latest firmware) / old / blank (no Afterglow firmware yet) / busy
                if row.get('fw'):
                    row['state'] = 'old' if helpdesk.firmware_is_older(row, latest, latest_built) else 'ready'
                else:
                    row['state'] = 'busy' if row.get('busy') else 'blank'
                rows.append(row)
            return rows
        return self._call(work)

    def scan_hint(self):
        """Why no board shows up (empty port list): missing driver vs. cable/port."""
        return helpdesk.no_port_hint()

    def connect(self, port):
        def work():
            self.disconnect()
            d = device.Device(port, on_event=self._event, on_line=self._line)
            try:
                info = d.hello()
            except Exception:
                d.close(send_off=False); raise
            if info.get('proto') != device.SUPPORTED_PROTO:
                d.close(send_off=False)
                raise RuntimeError(f"固件协议 {info.get('proto')} 与本软件不兼容，请先烧录新固件")
            self._dev = d
            return info
        return self._call(work)

    def disconnect(self):
        self.stop_loopback(); self.stop_show()
        if self._dev:
            self._dev.close(); self._dev = None
        return {'ok': True}

    def status(self):
        if not self._dev or not self._dev.alive or self._dev.lock.locked():
            return {'ok': False, 'connected': bool(self._dev and self._dev.alive)}
        r = self._call(lambda: self._dev.status())
        r['connected'] = True
        r['info'] = self._dev.info if self._dev else None
        return r

    def config(self):
        return self._call(lambda: self._need().config())

    def set_key(self, key, value):
        return self._call(lambda: self._need().set(key, value))

    def save(self):
        return self._call(lambda: self._need().save())

    def command(self, text):
        return self._call(lambda: self._need().request(text))

    def color(self, r, g, b):
        self.stop_loopback(); self.stop_show()
        return self._call(lambda: self._need().color(r, g, b))

    def off(self):
        self.stop_loopback(); self.stop_show()
        return self._call(lambda: self._need().off())

    def mic(self):
        self.stop_loopback(); self.stop_show()
        return self._call(lambda: self._need().mic())

    def micmon(self, level):
        return self._call(lambda: self._need().micmon(level))

    def get_log(self):
        return self._log[-500:]

    # ---------- flashing ----------
    def packages(self):
        pkgs = []
        bundled = Path(getattr(sys, '_MEIPASS', base_dir())) / 'firmware'   # firmware shipped inside the app
        for d in dict.fromkeys((bundled, base_dir() / 'firmware', base_dir().parent / 'firmware',
                                base_dir().parent / 'firmware' / 'dist')):   # running from the source tree
            if d.exists():
                for p in d.glob('afterglow-fw-*.zip'):
                    try:
                        m, _ = flasher.load_package(p)
                        pkgs.append({'path': str(p), 'version': m['version'], 'built': m['built'], 'name': m['name']})
                    except Exception as e:
                        pkgs.append({'path': str(p), 'error': str(e)})
        def key(p):
            try:
                return tuple(int(x) for x in p.get('version', '0').split('.'))
            except ValueError:
                return (0,)
        return sorted(pkgs, key=key, reverse=True)

    def pick_package(self):
        res = self._window.create_file_dialog(webview.OPEN_DIALOG, file_types=('固件包 (*.zip)',))
        if not res:
            return None
        try:
            m, _ = flasher.load_package(res[0])
            return {'path': res[0], 'version': m['version'], 'built': m['built'], 'name': m['name']}
        except Exception as e:
            return {'path': res[0], 'error': str(e)}

    def flash(self, ports, package, app_only):
        manifest, blobs = flasher.load_package(package)
        if self._dev and self._dev.port in ports:
            self.disconnect()
        results = {}
        errors = {}
        def one(port):
            try:
                flasher.flash(port, manifest, blobs, app_only=app_only, log=lambda s: self.emit('flash_log', line=s),
                              progress=lambda pct: self.emit('flash_progress', port=port, pct=round(pct, 1)))
                results[port] = '成功'
            except flasher.FlashError as e:
                results[port] = f"失败：{e.info['title']}"
                errors[port] = e.info
                self.emit('flash_log', line=f"{port}: {e.info['title']}")
            except Exception as e:
                results[port] = f'失败：{e}'
                errors[port] = {'kind': 'other', 'title': str(e), 'steps': ['拔掉数据线重新插上，再试一次']}
                self.emit('flash_log', line=str(e))
        def all_():
            ts = [threading.Thread(target=one, args=(p,)) for p in ports]
            for t in ts: t.start()
            for t in ts: t.join()
            self.emit('flash_done', results=results, errors=errors)
        threading.Thread(target=all_, daemon=True).start()
        return {'ok': True}

    def wifi_update(self, host, package):
        manifest, blobs = flasher.load_package(package)
        def work():
            try:
                flasher.wifi_update(host, manifest, blobs, log=lambda s: self.emit('flash_log', line=s))
                self.emit('flash_done', results={host: '成功'})
            except Exception as e:
                self.emit('flash_done', results={host: f'失败：{e}'})
        threading.Thread(target=work, daemon=True).start()
        return {'ok': True}

    # ---------- help ----------
    def diagnose(self):
        def work():
            lp = self.latest_firmware() or {}
            latest, latest_built = lp.get('version'), lp.get('built')
            if self._dev and self._dev.alive:
                hello = self._dev.info or self._dev.hello()
                st = self._dev.status()
                cfg = self._dev.config()
                items, report = helpdesk.health_check(APP_VERSION, latest, hello, st, cfg, latest_built)
                return {'connected': True, 'items': items, 'report': report}
            sc = self.scan()
            ports = sc['data'] if sc.get('ok') else []
            # a controller with our firmware is plugged in but not connected: open it briefly for the full check
            ready = [p for p in ports if p.get('fw')]
            if len(ready) == 1:
                d = device.Device(ready[0]['port'])
                try:
                    hello = d.hello()
                    items, report = helpdesk.health_check(APP_VERSION, latest, hello, d.status(), d.config(), latest_built)
                    return {'connected': True, 'items': items, 'report': report}
                except Exception:
                    pass                                   # fall back to the computer-side report below
                finally:
                    d.close(send_off=False)
            hint = None if ports else helpdesk.no_port_hint()
            items = []
            if hint:
                items.append({'name': '连接', 'state': 'bad', 'text': hint['title'] + '：' + '；'.join(hint['steps'])})
            for p in ports:
                txt = {'ready': f"固件 {p.get('ver')}，点“连接”即可", 'old': f"固件 {p.get('ver')}，可以更新到 {latest}",
                       'blank': '还没有 Afterglow 固件，需要先刷机', 'busy': '被别的程序占用，先关掉它'}[p['state']]
                items.append({'name': p['port'], 'state': 'ok' if p['state'] == 'ready' else 'warn', 'text': txt})
            return {'connected': False, 'items': items, 'report': helpdesk.offline_report(APP_VERSION, ports, hint)}
        return self._call(work)

    def copy_text(self, text):
        """Clipboard through Windows clip.exe (works regardless of the page's clipboard permissions)."""
        import subprocess
        subprocess.run(['clip'], input=text.encode('utf-16'), creationflags=0x08000000, check=True)
        return True

    def onboarding(self):
        return {'done': (base_dir() / '.onboarded').exists()}

    def onboarding_done(self):
        try:
            (base_dir() / '.onboarded').write_text(time.strftime('%Y-%m-%d %H:%M:%S'), encoding='utf-8')
        except OSError:
            pass
        return True

    # ---------- profiles ----------
    def profiles(self):
        return [{k: v for k, v in p.items()} for p in profiles.load_all()]

    def save_profile(self, p):
        def work():
            p2 = dict(p)
            p2['freq'] = float(p2['freq']); p2['dbm'] = int(p2['dbm']); p2['bitus'] = int(p2['bitus']); p2['period'] = int(p2['period'])
            if not 433.05 <= p2['freq'] <= 434.79: raise ValueError('频率须在 433.05–434.79 MHz 范围内')
            if p2['dbm'] not in (-10, 0, 5, 10): raise ValueError('功率仅支持 -10、0、5、10 dBm')
            if p2.get('_path') and Path(p2['_path']).stem != profiles._filename(p2['name']):
                Path(p2['_path']).unlink(missing_ok=True)
            return str(profiles.save(p2))
        return self._call(work)

    def delete_profile(self, p):
        return self._call(lambda: profiles.delete(p))

    def apply_profile(self, p):
        return self._call(lambda: profiles.apply(self._need(), p))

    # ---------- PC music (loopback) ----------
    def loop_devices(self):
        try:
            import audio_engine
            return audio_engine.devices()
        except Exception as e:
            return {'error': str(e)}

    def start_loopback(self, index):
        import audio_engine
        dev = self._need()
        self.stop_loopback(); self.stop_show()
        self._loopback = audio_engine.AudioInput(int(index), {'sensitivity': 1.2, 'brightness': 128, 'effect': 'beat'})
        self._loopback.start(); self._loop_stop.clear()
        def pump():
            while not self._loop_stop.is_set() and dev.alive:
                snap = self._loopback.snapshot if self._loopback else {}
                if snap.get('error'):
                    self.emit('toast', msg='电脑音频：' + snap['error'], kind='err'); break
                try:
                    dev.stream(*snap.get('rgb', (0, 0, 0)))
                except Exception:
                    break
                self.emit('loop_level', level=snap.get('level', 0), rgb=snap.get('rgb', (0, 0, 0)))
                time.sleep(0.05)
        threading.Thread(target=pump, daemon=True).start()
        return {'ok': True}

    def stop_loopback(self):
        if self._loopback:
            self._loop_stop.set(); self._loopback.close(); self._loopback = None
        return {'ok': True}

    # ---------- concert shows ----------
    def shows_dir(self):
        d = base_dir() / 'shows'; d.mkdir(exist_ok=True)
        return d

    def shows(self):
        from showplayer import load_show
        out = []
        for p in sorted(self.shows_dir().iterdir()):
            if (p / 'show.json').exists():
                try:
                    s = load_show(p)
                    out.append({'name': p.name, 'dir': str(p), 'duration': s['duration_s'], 'cues': len(s['colours']),
                                'beats': len(s['beats']), 'source': s['source'], 'has_video': Path(s['source']).exists()})
                except Exception as e:
                    out.append({'name': p.name, 'dir': str(p), 'error': str(e)})
        return out

    # ---------- settings backup / restore ----------
    def export_settings(self):
        import settings_backup
        def work():
            dev = self._need()
            data = settings_backup.make_backup(dev)
            name = f"Afterglow设置_{(data.get('controller') or 'controller')[-4:]}_{time.strftime('%Y%m%d')}.json"
            res = self._window.create_file_dialog(webview.SAVE_DIALOG, save_filename=name, file_types=('设置备份 (*.json)',))
            if not res:
                return None
            path = res if isinstance(res, str) else res[0]
            Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding='utf-8')
            return path
        return self._call(work)

    def import_settings(self):
        import settings_backup
        def work():
            dev = self._need()
            self.stop_loopback(); self.stop_show()
            res = self._window.create_file_dialog(webview.OPEN_DIALOG, file_types=('设置备份 (*.json)', '全部 (*.*)'))
            if not res:
                return None
            settings, _ = settings_backup.read_backup(Path(res[0]).read_text(encoding='utf-8'))
            return settings_backup.restore(dev, settings)
        return self._call(work)

    def pick_video(self):
        res = self._window.create_file_dialog(webview.OPEN_DIALOG, file_types=('视频 (*.mp4;*.mov;*.mkv)', '全部 (*.*)'))
        return res[0] if res else None

    def build_show(self, video, start_s, dur_s, name):
        import showbuild
        out = self.shows_dir() / name
        def work():
            try:
                showbuild.build(video, float(start_s), float(dur_s), out, log=lambda s: self.emit('build_log', line=s))
                self.emit('build_done', ok=True, name=name)
            except Exception as e:
                self.emit('build_done', ok=False, err=str(e))
        threading.Thread(target=work, daemon=True).start()
        return {'ok': True}

    def load_show(self, d):
        from showplayer import load_show
        return self._call(lambda: load_show(d))

    def show_peaks(self, d, per_second=20):
        """Loudness envelope of the replica's audio for the editor (0..1, per_second values per second)."""
        def work():
            import wave
            import numpy as np
            with wave.open(str(Path(d) / 'audio.wav')) as w:
                rate, ch = w.getframerate(), w.getnchannels()
                pcm = np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float32)
            if ch > 1:
                pcm = pcm.reshape(-1, ch).mean(1)
            step = max(1, rate // int(per_second))
            n = len(pcm) // step
            rms = np.sqrt((pcm[:n * step].reshape(n, step) ** 2).mean(1))
            top = float(np.percentile(rms, 99)) or 1.0
            return [round(min(1.0, float(v) / top), 3) for v in rms]
        return self._call(work)

    def save_show(self, d, show):
        from showplayer import save_show
        return self._call(lambda: save_show(d, show))

    def play_show(self, d, opts):
        from showplayer import ShowPlayer, load_show
        dev = self._need()
        self.stop_loopback(); self.stop_show()
        show = opts.get('show') or load_show(d)
        player = ShowPlayer(d, dev, latency_ms=int(opts.get('latency', 80)), volume=int(opts.get('volume', 35)) / 100,
                            show=show, on_status=lambda s: None, on_pos=lambda p: self.emit('show_pos', pos=p))
        self._player = player
        def work():
            try:
                if opts.get('wake'):
                    dev.request('wake 30'); self.emit('show_state', state='waking')
                    end = time.time() + 30
                    while time.time() < end and not player.stop_event.is_set():
                        time.sleep(0.2)
                if not player.stop_event.is_set():
                    self.emit('show_state', state='playing')
                    start = float(opts.get('from', 0))
                    if opts.get('video') and Path(show['source']).exists():
                        # the page plays the original video in a popup and reports its clock (show_clock)
                        self.emit('show_video', src=self._video.url(show['source']), start=float(show['start_s']),
                                  offset=start, duration=float(show['duration_s']), volume=int(opts.get('volume', 35)))
                        player.play_clocked(from_s=start)
                    else:
                        player.play(from_s=start)
            except Exception as e:
                self.emit('toast', msg='播放失败：' + str(e), kind='err')
            finally:
                try:
                    dev.off()
                except Exception:
                    pass
                self.emit('show_state', state='stopped')
        threading.Thread(target=work, daemon=True).start()
        return {'ok': True}

    # Shows stored on the controller (firmware >= 0.8.0): played from the phone page without the PC.
    def device_shows(self):
        return self._call(lambda: self._need().request('shows', timeout=3)['shows'])

    def upload_show(self, d, slot, name):
        from showplayer import export_bin, load_show, upload_to_device
        dev = self._need()
        self.stop_loopback(); self.stop_show()
        def work():
            try:
                data = export_bin(load_show(d), name)
                upload_to_device(dev, slot, data, log=lambda s: self.emit('build_log', line=s))
                self.emit('device_show_done', ok=True, slot=slot)
            except Exception as e:
                self.emit('device_show_done', ok=False, err=str(e))
        threading.Thread(target=work, daemon=True).start()
        return {'ok': True}

    def delete_device_show(self, slot):
        return self._call(lambda: self._need().request(f'showdel {int(slot)}'))

    def show_clock(self, pos):
        if self._player and hasattr(self._player, 'set_clock'):
            self._player.set_clock(pos)
        return {'ok': True}

    def stop_show(self):
        if self._player:
            self._player.stop(); self._player = None
        return {'ok': True}

    def shutdown(self):
        """Runs on the UI thread when the window closes. Turn the bands off and release the port in the
        background, never waiting on the UI, and give up after a few seconds so closing never hangs."""
        self._closing = True
        if self._loopback:
            # a silent WASAPI loopback read blocks; don't wait for it, the process exits right after
            self._loop_stop.set(); self._loopback.stop_event.set(); self._loopback = None
        t = threading.Thread(target=self.disconnect, daemon=True)
        t.start()
        t.join(timeout=3)


def dark_frame(win):
    """Dark Windows title bar/border (Win10 20H1+: dark mode; Win11: caption colour = page background)."""
    try:
        import ctypes
        hwnd = win.native.Handle.ToInt32()
        dwm = ctypes.windll.dwmapi
        on = ctypes.c_int(1)
        for attr in (20, 19):                       # DWMWA_USE_IMMERSIVE_DARK_MODE
            if dwm.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(on), 4) == 0:
                break
        bg = ctypes.c_int(0x00151110)               # COLORREF 0x00BBGGRR of #0f1115
        dwm.DwmSetWindowAttribute(hwnd, 35, ctypes.byref(bg), 4)   # DWMWA_CAPTION_COLOR (Win11 only)
        dwm.DwmSetWindowAttribute(hwnd, 34, ctypes.byref(bg), 4)   # DWMWA_BORDER_COLOR (Win11 only)
        # Windows 10 repaints the caption only after a frame change: nudge the size once.
        w, h = win.width, win.height
        win.resize(w + 1, h); win.resize(w, h)
    except Exception:
        pass


def selftest(out):
    """`AfterglowStudio.exe --selftest <file>`: check the frozen build can load every lazily imported module
    (PyInstaller misses some, e.g. parts of numpy) and do real work with numpy. Writes OK or the error."""
    import traceback
    lines = []
    try:
        import numpy as np
        x = np.fft.rfft(np.sin(np.linspace(0, 100, 4096)).astype(np.float32))
        lines.append(f'numpy {np.__version__} fft ok ({float(np.abs(x).max()):.1f})')
        np.seterr(all='raise')
        try:
            np.float32(1) / np.float32(0)
        except FloatingPointError:
            lines.append('numpy errors ok')       # needs numpy._core._exceptions
        import audio_engine, showbuild, showplayer, settings_backup, flasher, helpdesk, winenv  # noqa: F401
        lines.append('modules ok; loopback devices: ' + str(len(audio_engine.devices())))
        lines.append('ffmpeg: ' + str(showbuild.tool('ffmpeg')))
        lines.append('RESULT: OK')
    except Exception:
        lines.append(traceback.format_exc()); lines.append('RESULT: FAIL')
    Path(out).write_text('\n'.join(lines), encoding='utf-8')


def main():
    if '--selftest' in sys.argv:
        selftest(sys.argv[sys.argv.index('--selftest') + 1]); return
    import winenv
    if not winenv.ensure('Afterglow Studio'):       # WebView2 / .NET missing: explained in a message box
        return
    api = Api()
    win = webview.create_window(f'Afterglow Studio {APP_VERSION}', str(ui_dir() / 'index.html'), js_api=api,
                                width=1200, height=800, min_size=(980, 640), background_color='#0f1115')
    api._window = win
    win.events.closing += lambda: api.shutdown()
    win.events.shown += lambda: dark_frame(win)
    webview.start(debug='--debug' in sys.argv)
    os._exit(0)     # stray worker threads (a stuck serial read, a build) must not keep the process alive


if __name__ == '__main__':
    main()
