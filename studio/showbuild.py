"""Build a show (colour cues + beat punches + audio) from one segment of a concert video.

Colour: theme colour of the video frames (bright, saturated pixels), snapped to band palette, smoothed.
Beats : bass onsets of the segment's own audio. Output folder: show.json + audio.wav.
Needs ffmpeg/ffplay: next to the app in ffmpeg/, on PATH, or the developer install below.
"""
import colorsys
import json
import os
import shutil
import subprocess
import sys
import wave
from pathlib import Path

import numpy as np

DEV_FFMPEG_DIR = Path(os.environ.get('AFTERGLOW_DEV_FFMPEG', '.'))   # developer machine only: ffmpeg outside the bundle
PALETTE = {'red': (255, 0, 0), 'orange': (255, 80, 0), 'yellow': (255, 200, 0), 'green': (0, 255, 0),
           'cyan': (0, 255, 255), 'blue': (0, 0, 255), 'purple': (200, 0, 255), 'pink': (255, 0, 120),
           'white': (255, 255, 255)}
HUES = {k: colorsys.rgb_to_hsv(*(c / 255 for c in v))[0] for k, v in PALETTE.items() if k != 'white'}
NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)


def tool(name):
    base = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parent
    bundled = Path(getattr(sys, '_MEIPASS', base)) / 'ffmpeg' / f'{name}.exe'   # packaged app: _internal/ffmpeg
    for cand in (bundled, base / 'ffmpeg' / f'{name}.exe', DEV_FFMPEG_DIR / f'{name}.exe'):
        if cand.exists():
            return str(cand)
    found = shutil.which(name)
    if found:
        return found
    raise FileNotFoundError(f'未找到 {name}：安装文件可能不完整，请重新安装 Afterglow Studio')


def colour_track(video, start, dur, fps=10, log=print):
    W, H = 64, 36
    cmd = [tool('ffmpeg'), '-v', 'error', '-ss', str(start), '-t', str(dur), '-i', video,
           '-vf', f'fps={fps},scale={W}:{H}:flags=area', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-']
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, creationflags=NO_WINDOW)
    names = []
    while True:
        buf = proc.stdout.read(W * H * 3)
        if len(buf) < W * H * 3:
            break
        px = np.frombuffer(buf, np.uint8).reshape(-1, 3).astype(np.float32) / 255
        mx = px.max(1); mn = px.min(1)
        sat = np.where(mx > 0, (mx - mn) / np.maximum(mx, 1e-6), 0)
        sel = (mx > 0.35) & (sat > 0.35)
        if sel.sum() >= 8:
            w = mx[sel] ** 2
            col = (px[sel] * w[:, None]).sum(0) / w.sum()
            h, s, v = colorsys.rgb_to_hsv(*(col / max(col.max(), 1e-6)))
            names.append('white' if s < 0.3 else min(HUES, key=lambda k: min(abs(h - HUES[k]), 1 - abs(h - HUES[k]))))
        else:
            names.append('white' if mx.mean() > 0.5 else 'black')
        if len(names) % 300 == 0:
            log(f'正在分析颜色：{len(names) / fps:.0f}/{dur:.0f} 秒')
    proc.wait()
    win = int(fps * 2)
    voted = []
    for i in range(len(names)):
        w = names[max(0, i - win // 2): i + win // 2 + 1]
        voted.append(max(set(w), key=w.count))
    runs = []
    for i, n in enumerate(voted):
        if not runs or runs[-1][1] != n:
            runs.append([i / fps, n])
    merged = []
    for j, (t, n) in enumerate(runs):
        nxt = runs[j + 1][0] if j + 1 < len(runs) else dur
        if merged and (nxt - t < 1.5 or merged[-1][1] == n):
            continue
        merged.append([round(t, 2), n])
    return merged


def beat_track(wav_path):
    with wave.open(str(wav_path)) as w:
        rate = w.getframerate()
        pcm = np.frombuffer(w.readframes(w.getnframes()), np.int16).reshape(-1, 2).mean(1) / 32768.0
    hop, n = 512, 2048
    win = np.hanning(n)
    e = np.array([np.abs(np.fft.rfft(pcm[i:i + n] * win))[2:9].sum() for i in range(0, len(pcm) - n, hop)])
    flux = np.maximum(0, np.diff(e, prepend=e[0]))
    beats, last = [], -1.0
    avg = flux[:40].mean() if len(flux) > 40 else flux.mean()
    for i, x in enumerate(flux):
        t = i * hop / rate
        avg += (x - avg) * 0.02
        if x > avg * 2.2 and x > 1e-3 and t - last > 0.27:
            beats.append(round(t, 3)); last = t
    return beats


def build(video, start, dur, out_dir, log=print):
    out_dir = Path(out_dir); out_dir.mkdir(parents=True, exist_ok=True)
    log('正在提取音频…')
    wav = out_dir / 'audio.wav'
    subprocess.run([tool('ffmpeg'), '-v', 'error', '-y', '-ss', str(start), '-t', str(dur), '-i', video, '-vn',
                    '-ac', '2', '-ar', '44100', '-sample_fmt', 's16', str(wav)], check=True, creationflags=NO_WINDOW)
    log('正在分析节拍…')
    beats = beat_track(wav)
    log('正在分析颜色…')
    colours = colour_track(video, start, dur, log=log)
    show = {'source': str(video), 'start_s': start, 'duration_s': dur, 'palette': PALETTE,
            'colours': colours, 'beats': beats}
    (out_dir / 'show.json').write_text(json.dumps(show, ensure_ascii=False, indent=1), encoding='utf-8')
    log(f'生成完成：{len(colours)} 个换色点，{len(beats)} 个节拍')
    return show
