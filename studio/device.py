"""Serial link to an ESP32 running the Afterglow controller firmware (afterglow-fw), JSON line protocol."""
import json
import queue
import threading
import time

import serial
from serial.tools import list_ports

BAUD = 115200
SUPPORTED_PROTO = 1


class DeviceError(Exception):
    pass


def open_port(port, timeout=0.05):
    # DTR/RTS low before opening so the board is not reset just by connecting.
    s = serial.Serial(port=None, baudrate=BAUD, timeout=timeout, write_timeout=1)
    s.dtr = False
    s.rts = False
    s.port = port
    s.open()
    return s


class Device:
    def __init__(self, port, on_event=None, on_line=None):
        self.port = port
        self.on_event = on_event or (lambda e: None)
        self.on_line = on_line or (lambda direction, text: None)
        self.ser = open_port(port)
        self.ser.reset_input_buffer()
        self.replies = queue.Queue()
        self.lock = threading.Lock()
        self.alive = True
        self.thread = threading.Thread(target=self._reader, daemon=True)
        self.thread.start()
        self.info = None

    def _reader(self):
        buf = b''
        while self.alive:
            try:
                chunk = self.ser.read(256)
            except (serial.SerialException, OSError) as e:
                self.alive = False
                self.on_event({'evt': 'disconnected', 'msg': str(e)})
                return
            if not chunk:
                continue
            buf += chunk
            while b'\n' in buf:
                raw, buf = buf.split(b'\n', 1)
                text = raw.decode('utf-8', errors='replace').strip()
                if not text:
                    continue
                self.on_line('<', text)
                try:
                    msg = json.loads(text)
                except ValueError:
                    self.on_event({'evt': 'text', 'text': text})
                    continue
                if 'evt' in msg:
                    self.on_event(msg)
                else:
                    self.replies.put(msg)

    def _write(self, cmd):
        if not self.alive:
            raise DeviceError('控制器已断开')
        self.ser.write((cmd + '\n').encode('ascii'))

    def request(self, cmd, timeout=1.5):
        with self.lock:
            while not self.replies.empty():
                self.replies.get_nowait()
            self.on_line('>', cmd)
            self._write(cmd)
            try:
                reply = self.replies.get(timeout=timeout)
            except queue.Empty:
                raise DeviceError(f'控制器无响应：{cmd}')
        if not reply.get('ok'):
            raise DeviceError(reply.get('err', '未知错误'))
        return reply

    def send_nowait(self, cmd):
        with self.lock:
            self._write(cmd)

    # Convenience wrappers
    def hello(self, timeout=1.5):
        self.info = self.request('hello', timeout)
        return self.info

    def status(self):
        return self.request('status')

    def config(self):
        return self.request('config')['config']

    def set(self, key, value):
        return self.request(f'set {key} {value}')

    def save(self):
        return self.request('save')

    def color(self, r, g, b):
        return self.request(f'color {int(r)} {int(g)} {int(b)}')

    def stream(self, r, g, b):
        self.send_nowait(f'stream {int(r)} {int(g)} {int(b)}')

    def mic(self):
        return self.request('mic')

    def off(self):
        return self.request('off')

    def micmon(self, level):
        """0 off, 1 (or True) level reports every 100 ms, 2 onset/flash timestamps."""
        return self.request(f'micmon {int(level)}')

    def close(self, send_off=True):
        if self.alive and send_off:
            try:
                self.off()
                time.sleep(0.6)   # let the black tail frames go out
            except Exception:
                pass
        self.alive = False
        try:
            self.ser.close()
        except Exception:
            pass


def probe(port, timeout=1.2):
    """Return hello info for an Afterglow controller on this port, {'busy':True} or {'unknown':True}."""
    try:
        s = open_port(port, timeout=0.05)
    except (serial.SerialException, OSError):
        return {'busy': True}
    try:
        s.reset_input_buffer()
        s.write(b'hello\n')
        end = time.time() + timeout
        buf = b''
        while time.time() < end:
            buf += s.read(256)
            for raw in buf.split(b'\n'):
                try:
                    msg = json.loads(raw.decode('utf-8', errors='replace').strip())
                except ValueError:
                    continue
                if msg.get('fw'):
                    return msg
        return {'unknown': True}
    finally:
        s.close()


def list_serial_ports():
    return [{'port': p.device, 'desc': p.description, 'usb': 'CH340' in (p.description or '') or 'CP210' in (p.description or '')}
            for p in sorted(list_ports.comports(), key=lambda p: p.device)]
