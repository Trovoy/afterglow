"""Design preview of the phone page without a controller: serves index.html and a fake /api.
python web/mock_server.py [port]   then open http://127.0.0.1:8766/
"""
import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

HTML = Path(__file__).resolve().parent / 'index.html'
CFG = {'freq': 433.92, 'dbm': 10, 'msens': 1.8, 'bright': 200, 'mbase': 0, 'mstyle': 4, 'auto': 0, 'ka': 1}


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        u = urlparse(self.path)
        if u.path == '/api':
            c = parse_qs(u.query).get('c', [''])[0]
            if c == 'status':
                import time
                body = {'ok': True, 'mode': 'mic', 'bpm': 170.5, 'beats': int(time.time() * 2.8), 'mic': True,
                        'level': 0.018, 'uptime_s': 93780, 'freq': 433.97, 'reset': 'poweron', 'boots': 12, 'wifi_clients': 1}
            elif c == 'shows':
                body = {'ok': True, 'fs': True, 'shows': [{'slot': 0, 'name': '示例节目 1', 'dur_ms': 300000, 'cues': 39, 'beats': 477},
                                                          {'slot': 2, 'name': '示例节目 2', 'dur_ms': 184000, 'cues': 12, 'beats': 260}]}
            elif c == 'config':
                body = {'ok': True, 'config': CFG}
            elif c == 'hello':
                body = {'ok': True, 'ver': '0.9.0', 'ssid': 'Afterglow-E4F5', 'mac': 'A0B1C2D3E4F5'}
            else:
                body = {'ok': True}
            data = json.dumps(body, ensure_ascii=False).encode()
            ctype = 'application/json'
        else:
            data = HTML.read_bytes(); ctype = 'text/html; charset=utf-8'
        self.send_response(200); self.send_header('Content-Type', ctype); self.end_headers(); self.wfile.write(data)


HTTPServer(('127.0.0.1', int(sys.argv[1]) if len(sys.argv) > 1 else 8766), H).serve_forever()
