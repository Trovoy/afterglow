"""Embed web/index.html into src/webpage.h (the phone control page served by the controller).
The page is stored gzip-compressed and sent with Content-Encoding: gzip (about a third of the size),
so it opens noticeably faster over the controller's hotspot. Also embeds the iOS home-screen icon.
Run after editing index.html, before building the firmware: python web/embed.py
"""
import gzip
from pathlib import Path

here = Path(__file__).resolve().parent
html = (here / 'index.html').read_text(encoding='utf-8').encode('utf-8')
gz = gzip.compress(html, compresslevel=9, mtime=0)
# "Add to Home Screen" icon for iOS (square; iOS rounds the corners itself).
icon = (here / 'apple-touch-icon.png').read_bytes()


def c_array(name, data):
    rows = [', '.join(f'0x{b:02x}' for b in data[i:i + 24]) for i in range(0, len(data), 24)]
    return (f'static const size_t {name}_LEN = {len(data)};\n'
            f'static const uint8_t {name}[] PROGMEM = {{\n' + ',\n'.join(rows) + '\n};\n')


out = here.parent / 'src' / 'webpage.h'
out.write_text('#pragma once\n// GENERATED from web/index.html by web/embed.py - edit the HTML, not this file.\n'
               '// Phone control page served at "/" (gzip). Talks to /api?c=<command> (same commands as USB serial).\n'
               '#include <stdint.h>\n#include <stddef.h>\n'
               + c_array('WEB_PAGE_GZ', gz) + c_array('APPLE_ICON', icon), encoding='utf-8')
print(out, len(html), 'bytes ->', len(gz), 'bytes gzip; icon', len(icon), 'bytes')
