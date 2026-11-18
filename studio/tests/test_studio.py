"""Offline tests for Afterglow Studio (no controller needed).

Run from studio/:  .venv\\Scripts\\python.exe -m unittest discover -s tests -v
"""
import hashlib
import json
import struct
import sys
import tempfile
import unittest
import xml.dom.minidom
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
STUDIO = HERE.parent
OUTPUTS = STUDIO.parent
sys.path.insert(0, str(STUDIO))
sys.path.insert(0, str(OUTPUTS))
sys.path.insert(0, str(OUTPUTS / 'brand'))

import flasher  # noqa: E402
import showplayer  # noqa: E402


def parse_fls1(data):
    """Same rules as the firmware's show.cpp parse()."""
    assert data[:4] == b'FLS1'
    name_len = data[4]
    name = data[5:5 + name_len].decode('utf-8')
    p = 5 + name_len
    dur, nc, nb = struct.unpack_from('<IHH', data, p)
    p += 8
    assert p + nc * 8 + nb * 4 == len(data), 'size does not match header'
    cues = [struct.unpack_from('<IBBBB', data, p + i * 8) for i in range(nc)]
    p += nc * 8
    beats = list(struct.unpack_from(f'<{nb}I', data, p))
    return name, dur, cues, beats


SHOW = {'duration_s': 120.0, 'palette': {'red': (255, 0, 0), 'blue': (0, 0, 255), 'white': (255, 255, 255)},
        'colours': [[0.0, 'red', 'beat'], [40.5, 'blue', 'steady'], [80.0, 'white', 'strobe'], [100.0, 'black', 'off']],
        'beats': [0.5, 0.7, 1.0, 1.6, 1.8, 2.5, 30.0, 30.1]}


class ShowExport(unittest.TestCase):
    def test_round_trip(self):
        data = showplayer.export_bin(SHOW, '测试节目')
        name, dur, cues, beats = parse_fls1(data)
        self.assertEqual(name, '测试节目')
        self.assertEqual(dur, 120000)
        self.assertEqual([c[0] for c in cues], [0, 40500, 80000, 100000])
        self.assertEqual(cues[1][4], showplayer.MODE_CODES['steady'])
        self.assertEqual(cues[3][1:4], (0, 0, 0))          # black
        # beats closer than 0.4 s are thinned, like the PC player does
        self.assertEqual(beats, [500, 1000, 1600, 2500, 30000])

    def test_long_name_is_cut_on_a_character_boundary(self):
        data = showplayer.export_bin(SHOW, '演' * 40)       # 120 bytes of UTF-8
        name, *_ = parse_fls1(data)
        self.assertLessEqual(len(name.encode('utf-8')), 48)
        self.assertEqual(name, '演' * 16)

    def test_real_replica_fits_the_controller(self):
        d = STUDIO / 'shows'
        shows = [p for p in d.iterdir() if (p / 'show.json').exists()] if d.exists() else []
        if not shows:
            self.skipTest('no replica on this computer')
        data = showplayer.export_bin(showplayer.load_show(shows[0]), 'x')
        self.assertLessEqual(len(data), 24 * 1024)          # SHOW_MAX_BYTES in show.h
        parse_fls1(data)


def make_package(path, name='afterglow-fw', tamper=False, chip='esp32'):
    blob = b'\xe9' + b'\x00' * 31
    entry = {'file': 'firmware.bin', 'offset': 0x10000, 'size': len(blob),
             'sha256': hashlib.sha256(blob).hexdigest()}
    with zipfile.ZipFile(path, 'w') as z:
        z.writestr('firmware.bin', blob + (b'!' if tamper else b''))
        z.writestr('manifest.json', json.dumps({'name': name, 'version': '9.9.9', 'chip': chip, 'files': [entry]}))


class ClockedPlayback(unittest.TestCase):
    def test_lights_follow_the_video_clock(self):
        import threading
        import time

        class Dev:
            def __init__(self): self.sent = []
            def stream(self, r, g, b): self.sent.append((time.time(), (r, g, b)))

        show = {'duration_s': 60.0, 'palette': {'red': (255, 0, 0), 'blue': (0, 0, 255)},
                'colours': [[0.0, 'red', 'steady'], [10.0, 'blue', 'steady']], 'beats': []}
        dev = Dev()
        p = showplayer.ShowPlayer('.', dev, latency_ms=0, show=show)
        t = threading.Thread(target=p.play_clocked, kwargs={'from_s': 2.0}); t.start()
        time.sleep(0.3); red = dev.sent[-1][1]
        p.set_clock(12.0); time.sleep(0.3); blue = dev.sent[-1][1]
        p.stop(); t.join(timeout=2)
        self.assertFalse(t.is_alive())
        self.assertEqual(red, (216, 0, 0))     # steady = 85 %
        self.assertEqual(blue, (0, 0, 216))


class SettingsBackup(unittest.TestCase):
    class Dev:
        def __init__(self, cfg, reject=()):
            self.cfg, self.reject, self.calls = dict(cfg), set(reject), []
            self.info = {'ver': '0.9.0', 'mac': 'A1B2C3D4E5F6'}
        def config(self): return dict(self.cfg)
        def off(self): self.calls.append('off')
        def save(self): self.calls.append('save')
        def set(self, k, v):
            self.calls.append(f'set {k} {v}')
            if k in self.reject: raise RuntimeError(f'{k} out of range')
            self.cfg[k] = v

    BASE = {'freq': 433.92, 'dbm': 10, 'bitus': 500, 'period': 51, 'pchan': 80, 'psum': 125, 'bright': 200,
            'appass': 'secret123', 'ka': 1}

    def test_backup_round_trip_without_password(self):
        import json
        import settings_backup as sb
        data = sb.make_backup(self.Dev(self.BASE))
        self.assertNotIn('appass', data['settings'])
        settings, unknown = sb.read_backup(json.dumps(data))
        self.assertEqual(settings['freq'], 433.92)
        self.assertEqual(unknown, [])

    def test_restore_order_and_partial_failure(self):
        from unittest import mock
        import settings_backup as sb
        dev = self.Dev(self.BASE, reject={'psum'})
        with mock.patch.object(sb.time, 'sleep', lambda s: None):   # no real waiting, restored afterwards
            r = sb.restore(dev, {'freq': 433.97, 'period': 60, 'bitus': 520, 'pchan': 100, 'psum': 999, 'ka': 0})
        sets = [c for c in dev.calls if c.startswith('set')]
        self.assertEqual(dev.calls[0], 'off')
        self.assertEqual(sets[:3], ['set freq 433.97', 'set period 60', 'set bitus 520'])   # period grows first
        self.assertEqual(dev.calls[-1], 'save')
        self.assertIn('psum', r['failed'])
        self.assertIn('pchan', r['applied'])

    def test_rejects_other_files(self):
        import settings_backup as sb
        for bad in ('not json', '{"kind": "something-else", "settings": {}}', '{"kind": "controller-settings", "settings": {"x": 1}}'):
            with self.assertRaises(sb.BackupError):
                sb.read_backup(bad)


class Packages(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_valid_package(self):
        p = self.dir / 'ok.zip'; make_package(p)
        m, blobs = flasher.load_package(p)
        self.assertEqual(m['version'], '9.9.9')
        self.assertIn('firmware.bin', blobs)

    def test_pre_release_name_rejected(self):
        p = self.dir / 'old.zip'; make_package(p, name='pixmob-fw')
        with self.assertRaises(flasher.PackageError):
            flasher.load_package(p)

    def test_tampered_package_rejected(self):
        p = self.dir / 'bad.zip'; make_package(p, tamper=True)
        with self.assertRaises(flasher.PackageError):
            flasher.load_package(p)

    def test_foreign_package_rejected(self):
        p = self.dir / 'other.zip'; make_package(p, name='someone-elses-firmware')
        with self.assertRaises(flasher.PackageError):
            flasher.load_package(p)

    def test_released_packages_are_valid(self):
        for p in sorted((OUTPUTS / 'firmware').glob('afterglow-fw-*.zip')):
            m, blobs = flasher.load_package(p)
            self.assertIn(b'AFTERGLOW-FW-IMAGE/1', blobs['firmware.bin'], f'{p.name}: no update marker')
            self.assertEqual({e['name'] for e in m.get('erase_on_full', [])}, {'nvs', 'spiffs'})


class ReleaseCheck(unittest.TestCase):
    def test_blocks_test_content(self):
        import release_check
        for bad in ('shows/x/show.json', 'test_audio/a.m4a', 'profiles/my.json', 'work/log.txt', 'clip.MP4'):
            self.assertTrue(release_check.bad(bad), bad)
        for good in ('AfterglowStudio.exe', '_internal/ui/app.js', '_internal/ffmpeg/ffmpeg.exe', 'firmware/afterglow-fw-0.9.0.zip'):
            self.assertFalse(release_check.bad(good), good)


class Waveform(unittest.TestCase):
    def test_peaks(self):
        import wave
        import numpy as np
        import app
        with tempfile.TemporaryDirectory() as d:
            t = np.arange(44100 * 3) / 44100
            pcm = (np.sin(2 * np.pi * 220 * t) * (t / 3) * 20000).astype(np.int16)
            with wave.open(str(Path(d) / 'audio.wav'), 'w') as w:
                w.setnchannels(1); w.setsampwidth(2); w.setframerate(44100); w.writeframes(pcm.tobytes())
            r = app.Api.show_peaks(app.Api.__new__(app.Api), d, 20)
        self.assertTrue(r['ok'], r.get('err'))
        peaks = r['data']
        self.assertEqual(len(peaks), 60)
        self.assertLess(peaks[2], peaks[-2])                    # louder towards the end
        self.assertLessEqual(max(peaks), 1.0)


if __name__ == '__main__':
    unittest.main()
