"""Build a firmware update package (zip) from the last PlatformIO build.

Package layout:
  manifest.json  {"name","version","proto","chip","built","files":[{"file","offset","sha256","size"}]}
  bootloader.bin @0x1000, partitions.bin @0x8000, boot_app0.bin @0xe000, firmware.bin @0x10000
The desktop app flashes all four for a full install, or only firmware.bin for an app update.
Usage: python make_package.py [--out DIR]
"""
import argparse
import datetime
import hashlib
import json
import os
import re
import zipfile
from pathlib import Path

here = Path(__file__).resolve().parent
pio_core = Path(os.environ.get('PLATFORMIO_CORE_DIR', Path.home() / '.platformio'))
boot_app0 = pio_core / 'packages' / 'framework-arduinoespressif32' / 'tools' / 'partitions' / 'boot_app0.bin'

parser = argparse.ArgumentParser()
parser.add_argument('--out', default=str(here / 'dist'))
args = parser.parse_args()
build = here / '.pio' / 'build' / 'esp32dev'

header = (here / 'include' / 'version.h').read_text(encoding='utf-8')
name = re.search(r'#define FW_NAME "([^"]+)"', header).group(1)
version = re.search(r'#define FW_VERSION "([^"]+)"', header).group(1)
proto = int(re.search(r'#define FW_PROTO (\d+)', header).group(1))

files = [('bootloader.bin', 0x1000, build / 'bootloader.bin'),
         ('partitions.bin', 0x8000, build / 'partitions.bin'),
         ('boot_app0.bin', 0xE000, boot_app0),
         ('firmware.bin', 0x10000, build / 'firmware.bin')]
# A full install restores the factory state: the settings (NVS) and the show storage are wiped, so no
# test settings or concert shows stay on a controller that is sold. Offsets come from the partition table.
ptable = pio_core / 'packages' / 'framework-arduinoespressif32' / 'tools' / 'partitions' / 'min_spiffs.csv'
erase = []
for row in ptable.read_text().splitlines():
    cols = [c.strip() for c in row.split(',')]
    if len(cols) >= 5 and cols[0] in ('nvs', 'spiffs'):
        erase.append({'name': cols[0], 'offset': int(cols[3], 16), 'size': int(cols[4], 16)})
assert {e['name'] for e in erase} == {'nvs', 'spiffs'}, 'partition table changed'
manifest = {'name': name, 'version': version, 'proto': proto, 'chip': 'esp32',
            'built': datetime.datetime.now().isoformat(timespec='seconds'), 'files': [], 'erase_on_full': erase}
out_dir = Path(args.out); out_dir.mkdir(parents=True, exist_ok=True)
out = out_dir / f'{name}-{version}.zip'
if out.exists():
    raise SystemExit(f'{out} already exists; bump FW_VERSION in include/version.h first')
with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as z:
    for fname, offset, src in files:
        data = src.read_bytes()
        manifest['files'].append({'file': fname, 'offset': offset, 'size': len(data),
                                  'sha256': hashlib.sha256(data).hexdigest()})
        z.writestr(fname, data)
    notices = here.parent / 'THIRD_PARTY_NOTICES.txt'
    if notices.exists():
        z.write(notices, 'THIRD_PARTY_NOTICES.txt')
    z.writestr('manifest.json', json.dumps(manifest, indent=2))
print(out)
print(json.dumps(manifest, indent=2))
