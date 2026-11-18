"""Back up / restore a controller's settings as a small JSON file (e.g. when replacing a controller).

The hotspot password is not included on purpose: a backup file may be shared, and the new controller keeps
its own password.
"""
import datetime
import json
import time

KEYS = ('freq', 'dbm', 'bitus', 'period', 'msens', 'mstyle', 'mhold', 'bright', 'mbase', 'pchan', 'psum',
        'mch', 'auto', 'aoff', 'ka', 'kams', 'wifi')
RADIO = ('freq', 'dbm', 'bitus', 'period')


class BackupError(Exception):
    pass


def make_backup(dev):
    cfg = dev.config()
    info = getattr(dev, 'info', None) or {}
    return {'app': 'Afterglow', 'kind': 'controller-settings', 'format': 1,
            'saved': datetime.datetime.now().isoformat(timespec='seconds'),
            'firmware': info.get('ver'), 'controller': info.get('mac'),
            'settings': {k: cfg[k] for k in KEYS if k in cfg}}


def read_backup(text):
    try:
        data = json.loads(text)
    except ValueError:
        raise BackupError('这不是有效的设置备份文件')
    if not isinstance(data, dict) or data.get('kind') != 'controller-settings' or not isinstance(data.get('settings'), dict):
        raise BackupError('这不是 Afterglow 控制器的设置备份文件')
    unknown = [k for k in data['settings'] if k not in KEYS]
    settings = {k: v for k, v in data['settings'].items() if k in KEYS}
    if not settings:
        raise BackupError('备份文件里没有可恢复的设置')
    return settings, unknown


def restore(dev, settings):
    """Apply settings in a safe order; the controller rejects out-of-range values one by one."""
    dev.off()
    time.sleep(0.7)                      # dark tail must finish before radio settings can change
    cur = dev.config()
    order = [k for k in ('freq', 'dbm') if k in settings]
    if 'bitus' in settings or 'period' in settings:
        # bitus and period limit each other: grow the period first, or shrink it last
        grow = int(settings.get('period', cur.get('period', 51))) >= int(cur.get('period', 51))
        pair = ['period', 'bitus'] if grow else ['bitus', 'period']
        order += [k for k in pair if k in settings]
    order += [k for k in settings if k not in RADIO]
    failed = {}
    for k in order:
        try:
            dev.set(k, settings[k])
        except Exception as e:      # keep going: one bad value should not block the rest
            failed[k] = str(e)
    dev.save()
    return {'applied': [k for k in order if k not in failed], 'failed': failed, 'config': dev.config()}
