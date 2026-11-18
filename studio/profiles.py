"""Band profiles: radio settings per batch of wristbands (venue/event). Stored as JSON files."""
import json
import re
import sys
import time
from pathlib import Path

RADIO_KEYS = ('freq', 'dbm', 'bitus', 'period')


def base_dir():
    return Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parent


def profile_dir():
    d = base_dir() / 'profiles'
    d.mkdir(exist_ok=True)
    return d


DEFAULT = {
    'name': '默认（标准频率）',
    'venue': '',
    'pcb': 'CEMENT V1.1r3, 晶振 27.138266MHz',
    'freq': 433.92, 'dbm': 10, 'bitus': 500, 'period': 51,
    'notes': '2026-11-12 验证：433.92/500us/51ms 可用；434.16-434.24 无反应；510us 无反应。'
             '距离短：A 立放约 90cm、平放约 40cm（+10dBm，天线竖直）。',
}


def _filename(name):
    return re.sub(r'[\\/:*?"<>|\s]+', '_', name).strip('_') or 'profile'


def load_all():
    d = profile_dir()
    if not any(d.glob('*.json')):
        save(DEFAULT)
    out = []
    for p in sorted(d.glob('*.json')):
        try:
            data = json.loads(p.read_text(encoding='utf-8'))
            data['_path'] = str(p)
            out.append(data)
        except ValueError:
            continue
    return out


def save(profile):
    data = {k: v for k, v in profile.items() if not k.startswith('_')}
    path = profile_dir() / (_filename(data['name']) + '.json')
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return path


def delete(profile):
    Path(profile['_path']).unlink(missing_ok=True)


def apply(dev, profile):
    """Stop transmitting, write radio keys, persist on the board."""
    dev.off()
    cur = dev.config()
    order = ['freq', 'dbm']
    # bitus/period depend on each other: grow the period before the bit width, shrink it after.
    order += ['period', 'bitus'] if int(profile['period']) >= int(cur['period']) else ['bitus', 'period']
    time.sleep(0.6)  # off tail must finish before radio settings can change
    for key in order:
        dev.set(key, profile[key])
    dev.save()
    return dev.config()
