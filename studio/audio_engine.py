"""Local WASAPI loopback analysis; PCM is neither saved nor uploaded."""
import colorsys
import math
import threading
import time

import numpy as np
import pyaudiowpatch as pa


class Analyzer:
    def __init__(self, rate=48000):
        self.rate = rate
        self.average = 0.0
        self.previous = 0.0
        self.envelope = 0.0
        self.last_beat = -100.0
        self.hue = 0.60
        self.previous_time = None
        self.history = np.zeros(1024, dtype=np.float32)

    def process(self, mono, now, sensitivity=1.2, brightness=96, effect='beat'):
        mono = np.asarray(mono, dtype=np.float32)
        if len(mono) < 32 or not np.isfinite(mono).all():
            return (0, 0, 0), 0.0, 0.0, False
        dt = len(mono)/self.rate if self.previous_time is None else min(0.25, max(0.001, now-self.previous_time))
        self.previous_time = now
        rms = float(np.sqrt(np.mean(mono*mono)))
        self.history = np.concatenate((self.history, mono))[-1024:]
        window = np.hanning(len(self.history))
        spectrum = np.abs(np.fft.rfft((self.history-self.history.mean())*window))
        frequencies = np.fft.rfftfreq(len(self.history), 1/self.rate)
        bass = float(np.sqrt(np.sum(spectrum[(frequencies >= 40) & (frequencies <= 180)]**2))*2/len(self.history))
        threshold = max(0.0010/sensitivity, self.average*max(1.10, 1.65-.22*sensitivity))
        beat = bass > threshold and bass > self.previous*1.05 and now-self.last_beat > 0.18
        if beat:
            self.last_beat = now
            self.hue = (self.hue+0.173) % 1.0
        self.average += (1-math.exp(-dt/1.3))*(bass-self.average)
        self.previous = bass
        if effect == 'beat':
            # Hold each attack long enough for multiple 51ms RF frames.
            # This favors a shared beat pulse over two constantly changing bodies.
            if now-self.last_beat <= .11:
                self.envelope = 1.0
            else:
                self.envelope *= math.exp(-dt/.055)
            envelope = (1.0 if self.envelope >= .75 else .55 if self.envelope >= .40
                        else .25 if self.envelope >= .15 else 0.0)
        else:
            target = min(1.0, math.sqrt(max(0.0, rms*8*sensitivity)))
            if rms < 0.00045/sensitivity:
                target = 0.0
            if beat:
                target = max(target, 0.85)
            self.envelope = max(target, self.envelope*math.exp(-dt/0.12))
            envelope = self.envelope
        if self.envelope < 0.025:
            self.envelope = 0.0
        rgb = tuple(round(v*min(128, max(0, brightness))*envelope)
                    for v in colorsys.hsv_to_rgb(self.hue, 0.94, 1.0))
        return rgb, min(1.0, rms*8), min(1.0, bass*12), beat


def devices():
    with pa.PyAudio() as audio:
        default = audio.get_default_wasapi_loopback()
        items = list(audio.get_loopback_device_info_generator())
        items.sort(key=lambda item: item['index'] != default['index'])
        return [{'index': d['index'], 'name': d['name'].replace(' [Loopback]', '')}
                for d in items]


class AudioInput:
    def __init__(self, device_index, settings):
        self.device_index = device_index
        self.settings = settings
        self.snapshot = {'rgb': (0, 0, 0), 'level': 0.0, 'bass': 0.0, 'error': None, 'timestamp': time.monotonic()}
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)

    def start(self):
        self.thread.start()

    def close(self):
        self.stop_event.set()
        self.thread.join(timeout=2)

    def _run(self):
        try:
            with pa.PyAudio() as audio:
                info = audio.get_device_info_by_index(self.device_index)
                if not info.get('isLoopbackDevice'):
                    raise RuntimeError('请选择系统播放设备，不能选择麦克风。')
                rate = int(info['defaultSampleRate'])
                channels = int(info['maxInputChannels'])
                analyzer = Analyzer(rate)
                stream = audio.open(format=pa.paFloat32, channels=channels, rate=rate,
                                    input=True, input_device_index=self.device_index,
                                    frames_per_buffer=512)
                try:
                    while not self.stop_event.is_set():
                        data = stream.read(512, exception_on_overflow=False)
                        samples = np.frombuffer(data, dtype=np.float32).reshape(-1, channels).mean(axis=1)
                        rgb, level, bass, beat = analyzer.process(samples, time.monotonic(),
                            self.settings['sensitivity'], self.settings['brightness'], self.settings.get('effect', 'beat'))
                        self.snapshot = {'rgb': rgb, 'level': level, 'bass': bass,
                                         'beat': beat, 'error': None, 'timestamp': time.monotonic()}
                finally:
                    stream.stop_stream()
                    stream.close()
        except Exception as error:
            self.snapshot = {'rgb': (0, 0, 0), 'level': 0.0, 'bass': 0.0, 'error': str(error), 'timestamp': time.monotonic()}
