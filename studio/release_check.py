"""Release check: nothing derived from a concert may ship.

Scans what would be handed to buyers - the Studio build folder and the firmware packages - and fails if it
finds replica shows, audio/video, or folders the app creates at runtime (shows/, profiles/, work/): those hold the developer's own test data.
Usage: python release_check.py [paths...]   (default: dist/ and ../firmware/dist/)
Exit code 0 = clean, 1 = problems listed.
"""
import sys
import zipfile
from pathlib import Path

here = Path(__file__).resolve().parent
BAD_EXT = {'.wav', '.m4a', '.mp3', '.aac', '.flac', '.mp4', '.mov', '.mkv'}
BAD_NAMES = {'show.json'}
BAD_DIRS = {'shows', 'test_audio', 'work', 'profiles', 'licences', 'factory'}


def bad(name):
    parts = Path(name.replace('\\', '/')).parts
    return (Path(name).suffix.lower() in BAD_EXT or Path(name).name.lower() in BAD_NAMES
            or any(p.lower() in BAD_DIRS for p in parts[:-1]))


def scan(root):
    found = []
    root = Path(root)
    files = [root] if root.is_file() else [p for p in root.rglob('*') if p.is_file()]
    for f in files:
        rel = str(f.relative_to(root.parent if root.is_file() else root))
        if bad(rel):
            found.append(rel)
        if f.suffix.lower() == '.zip':
            with zipfile.ZipFile(f) as z:
                found += [f'{rel}!{n}' for n in z.namelist() if bad(n)]
    return found


def main():
    targets = sys.argv[1:] or [here / 'dist', here.parent / 'firmware' / 'dist']
    problems = []
    for t in targets:
        if Path(t).exists():
            problems += scan(t)
    if problems:
        print('不能发布：发现演唱会相关或测试用文件')
        for p in problems:
            print('  ' + p)
        return 1
    print('检查通过：未发现复刻节目、音频或视频文件')
    return 0


if __name__ == '__main__':
    sys.exit(main())
