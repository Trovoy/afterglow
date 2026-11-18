"""Play a show (show.json + audio.wav) with lights synced to the audio clock.

Colour cues: [t, colour, mode]; mode is one of
  beat   - theme colour punches on the drum beats, dark in between (default)
  steady - theme colour stays lit
  strobe - fast white/colour strobe
  off    - dark
Every 50 ms the colour for the current playback position is streamed to the board (stream R G B).
"""
import bisect
import json
import re
import subprocess
import threading
import time
import wave
from pathlib import Path

import pyaudiowpatch as pa

MODES = ('beat', 'steady', 'strobe', 'off')
MODE_NAMES = {'beat': '跟鼓点闪', 'steady': '常亮', 'strobe': '爆闪', 'off': '全黑'}


def load_show(show_dir):
    show = json.loads((Path(show_dir) / 'show.json').read_text(encoding='utf-8'))
    show['colours'] = [list(c) + ['beat'] * (3 - len(c)) for c in show['colours']]
    return show


def save_show(show_dir, show):
    data = {k: v for k, v in show.items() if not k.startswith('_')}
    (Path(show_dir) / 'show.json').write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding='utf-8')


class ShowPlayer:
    def __init__(self, show_dir, dev, bright=1.0, latency_ms=80, min_gap=0.4, base=0.0, on_status=None,
                 volume=0.4, show=None, on_pos=None):
        self.dir = Path(show_dir)
        self.volume = volume
        self.show = show if show is not None else load_show(show_dir)
        self.dev = dev
        self.bright = bright
        self.latency = latency_ms / 1000.0   # light leads audio output by this much (radio + output buffer)
        self.base = base
        self.on_status = on_status or (lambda s: None)
        self.on_pos = on_pos or (lambda p: None)
        self.stop_event = threading.Event()
        self.pos = 0.0
        pal = dict(self.show['palette']); pal['black'] = (0, 0, 0)
        self.pal = pal
        beats, last = [], -9
        for t in self.show['beats']:          # thin beats to at most one punch per min_gap
            if t - last >= min_gap:
                beats.append(t); last = t
        self.beats = beats

    def colour_at(self, t):
        cues = self.show['colours']
        if not cues:
            return (0, 0, 0), 'black', 'off'
        i = max(0, bisect.bisect_right([c[0] for c in cues], t) - 1)
        _, name, mode = cues[i][:3]
        rgb = self.pal.get(name, (255, 0, 0))
        if mode == 'off':
            k = 0.0
        elif mode == 'steady':
            k = 0.85
        elif mode == 'strobe':
            phase = (t * 8) % 1.0              # 8 Hz: 2-3 radio frames per state
            if phase < 0.5:
                k = 1.0; rgb = (255, 255, 255) if int(t * 8) % 4 == 0 else rgb
            else:
                k = 0.0
        else:
            j = bisect.bisect_right(self.beats, t) - 1
            since = t - self.beats[j] if j >= 0 else 9
            k = 1.0 if since < 0.11 else 0.6 if since < 0.22 else 0.25 if since < 0.33 else self.base
        return tuple(int(c * k * self.bright) for c in rgb), name, mode

    def _lights(self):
        while not self.stop_event.is_set():
            rgb, name, mode = self.colour_at(self.pos + self.latency)
            try:
                self.dev.stream(*rgb)
            except Exception:
                break
            self.on_status(f'{self.pos:6.1f}s  {name}  {MODE_NAMES.get(mode, mode)}')
            self.on_pos(self.pos)
            time.sleep(0.05)

    def play(self, from_s=0.0):
        with wave.open(str(self.dir / 'audio.wav')) as w, pa.PyAudio() as audio:
            rate, ch, width = w.getframerate(), w.getnchannels(), w.getsampwidth()
            w.setpos(min(w.getnframes(), int(from_s * rate)))
            stream = audio.open(format=audio.get_format_from_width(width), channels=ch, rate=rate, output=True,
                                frames_per_buffer=1024)
            self.pos = from_s
            lights = threading.Thread(target=self._lights, daemon=True)
            lights.start()
            written = int(from_s * rate)
            try:
                while not self.stop_event.is_set():
                    data = w.readframes(1024)
                    if not data:
                        break
                    if self.volume < 1.0 and width == 2:
                        import numpy as np
                        data = (np.frombuffer(data, np.int16) * self.volume).astype(np.int16).tobytes()
                    stream.write(data)
                    written += len(data) // (ch * width)
                    self.pos = written / rate
            finally:
                self.stop_event.set()
                stream.stop_stream(); stream.close()
                lights.join(timeout=1)

    def play_video(self, ffplay, video=None, volume=40, from_s=0.0):
        """Play the original video segment in an ffplay window; lights follow ffplay's own clock
        (parsed from its status line), so picture, sound and wristbands stay together."""
        video = video or self.show['source']
        start, dur = self.show['start_s'], self.show['duration_s']
        cmd = [ffplay, '-hide_banner', '-autoexit', '-volume', str(int(volume)), '-ss', str(start + from_s),
               '-t', str(max(1.0, dur - from_s)), '-window_title', 'Afterglow show', '-x', '960', '-y', '540', video]
        proc = subprocess.Popen(cmd, stderr=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        self.pos = from_s
        lights = threading.Thread(target=self._lights, daemon=True)
        clock_ok = False
        buf = b''
        num = re.compile(rb'^\s*(-?\d+\.\d+)\s+(?:A-V|M-A|M-V)')
        try:
            while not self.stop_event.is_set():
                ch = proc.stderr.read(1)
                if not ch:
                    break
                if ch in b'\r\n':
                    m = num.match(buf)
                    if m:
                        v = float(m.group(1))
                        self.pos = v - start if v > start - 5 else v
                        if not clock_ok:
                            clock_ok = True; lights.start()
                    buf = b''
                else:
                    buf += ch
        finally:
            self.stop_event.set()
            if proc.poll() is None:
                proc.terminate()
            if clock_ok:
                lights.join(timeout=1)

    def play_clocked(self, from_s=0.0):
        """Lights follow an external clock: the Studio page plays the original video and calls set_clock()."""
        self.pos = from_s
        self.clock_at = time.time()
        lights = threading.Thread(target=self._lights, daemon=True)
        lights.start()
        while not self.stop_event.wait(0.2):
            if time.time() - self.clock_at > 30:      # page closed without stopping: give up
                break
        self.stop_event.set()
        lights.join(timeout=1)

    def set_clock(self, pos):
        self.pos = float(pos)
        self.clock_at = time.time()

    def stop(self):
        self.stop_event.set()


# ---------- export to the controller (firmware >= 0.8.0, see firmware/include/show.h) ----------
MODE_CODES = {'beat': 0, 'steady': 1, 'strobe': 2, 'off': 3}


def export_bin(show, name, min_gap=0.4):
    """Pack a show into the controller's FLS1 format (colours as RGB, beats thinned like ShowPlayer)."""
    import struct
    pal = dict(show['palette']); pal['black'] = (0, 0, 0)
    raw = name.encode('utf-8')[:48]
    while raw:   # do not cut a UTF-8 character in half
        try:
            raw.decode('utf-8'); break
        except UnicodeDecodeError:
            raw = raw[:-1]
    cues = sorted(([float(c[0])] + list(c[1:]) + ['beat'] * (3 - len(c)))[:3] for c in show['colours'])
    beats, last = [], -9.0
    for t in show['beats']:
        if t - last >= min_gap:
            beats.append(t); last = t
    dur_ms = int(round(float(show['duration_s']) * 1000))
    out = b'FLS1' + bytes([len(raw)]) + raw + struct.pack('<IHH', dur_ms, len(cues), len(beats))
    for t, colour, mode in cues:
        r, g, b = pal.get(colour, (255, 0, 0))
        out += struct.pack('<IBBBB', int(round(t * 1000)), int(r), int(g), int(b), MODE_CODES.get(mode, 0))
    for t in beats:
        out += struct.pack('<I', int(round(t * 1000)))
    return out


def upload_to_device(dev, slot, data, log=print, chunk=48):
    dev.request(f'showput {int(slot)} {len(data)}')
    for off in range(0, len(data), chunk):
        dev.request(f'showdata {off} {data[off:off + chunk].hex()}')
        if off // chunk % 50 == 0:
            log(f'正在写入节目：{off * 100 // len(data)}%')
    dev.request('showend', timeout=5)
    log('节目写入完成')
