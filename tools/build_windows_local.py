"""Run on Windows with x64 Python 3.13, including inside an ARM Windows VM."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import sysconfig

ROOT = Path(__file__).resolve().parent.parent


def main():
    if os.name != 'nt':
        raise SystemExit('Run this script inside Windows, not macOS. See docs/WINDOWS-LOCAL-BUILD.md.')
    if sys.version_info[:2] != (3, 13) or sysconfig.get_platform() != 'win-amd64':
        raise SystemExit('Use Windows x64 (AMD64) Python 3.13. ARM64 and 32-bit Python are not supported by this build.')
    candidates = [os.environ.get('ISCC_PATH'), shutil.which('ISCC.exe')]
    candidates.extend(str(Path(os.environ.get(key, '')) / 'Inno Setup 6/ISCC.exe')
                      for key in ('ProgramFiles(x86)', 'ProgramFiles'))
    compiler = next((p for p in candidates if p and Path(p).is_file()), None)
    if not compiler:
        raise SystemExit('Install official Inno Setup 6, or set ISCC_PATH to ISCC.exe, then run again.')
    build_root = ROOT / '.build-windows'
    build_root.mkdir(exist_ok=True)
    env = os.environ.copy()
    env['ISCC_PATH'] = compiler
    env['PYTHONUTF8'] = '1'

    def run(args, extra_env=None):
        print('\n> ' + subprocess.list2cmdline([str(x) for x in args]), flush=True)
        subprocess.run([str(x) for x in args], cwd=ROOT,
                       env={**env, **(extra_env or {})}, check=True)

    run([sys.executable, '-m', 'venv', build_root / 'venv'])
    python = build_root / 'venv/Scripts/python.exe'
    run([python, '-m', 'pip', 'install', '-r', 'requirements-desktop.txt', 'pyinstaller==6.17.0'])
    run([python, '-m', 'unittest', 'discover', '-s', 'tests', '-t', '.', '-p', 'test_*.py', '-v'],
        {'QT_QPA_PLATFORM': 'offscreen'})
    dist = build_root / 'dist'
    run([python, str(Path(__file__).with_name('build.py')), '--dist', dist, '--work', build_root / 'pyinstaller'])
    run([python, str(Path(__file__).with_name('smoke_packaged.py')), dist / 'EllaPuede/EllaPuedeWorker.exe',
         dist / 'EllaPuede/_internal/models'])
    run([python, str(Path(__file__).with_name('package_installers.py')), '--dist', dist, '--output', ROOT / 'installers'])
    print('\nInstaller and SHA256 are in: ' + str(ROOT / 'installers'))
    print('Build and packaged OCR checks completed. Installation, upgrade and real x64 PC checks are still required.')


if __name__ == '__main__':
    try:
        main()
    except subprocess.CalledProcessError as error:
        raise SystemExit(f'Build stopped: command exited with {error.returncode}. See the output above.') from error
