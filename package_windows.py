"""Build the unsigned Windows app and Setup.exe. Receive-only; does not sign."""
from pathlib import Path
import hashlib
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
DIST = ROOT / 'dist' / 'GhostNetReceiver'
INSTALLER_DIR = ROOT / 'release'
ISCC = ROOT / 'work' / 'tools' / 'inno' / 'ISCC.exe'
SETUP = INSTALLER_DIR / 'GhostNetReceiver-0.4.0-Setup.exe'
PORTABLE = INSTALLER_DIR / 'GhostNetReceiver-0.4.0-Portable.zip'


def main():
    python = Path(sys.executable)
    print('PyInstaller', python)
    subprocess.run(
        [str(python), '-m', 'PyInstaller', '--noconfirm', str(ROOT / 'GhostNetReceiver.spec')],
        cwd=ROOT,
        check=True,
    )
    if not (DIST / 'GhostNetReceiver.exe').is_file():
        raise SystemExit('PyInstaller did not produce GhostNetReceiver.exe')
    for name in ('README.md', 'QUICKSTART.md', 'VALIDATION.md', 'REVIEW_FIXES.md', 'CHANGELOG.md', 'THIRD_PARTY.md', 'LICENSE'):
        shutil.copy2(ROOT / name, DIST / name)
    if not ISCC.is_file():
        raise SystemExit('Inno Setup compiler not found: ' + str(ISCC))
    INSTALLER_DIR.mkdir(parents=True, exist_ok=True)
    subprocess.run([str(ISCC), str(ROOT / 'installer.iss')], cwd=ROOT, check=True)
    if not SETUP.is_file():
        raise SystemExit('Setup.exe was not written')
    if PORTABLE.exists():
        PORTABLE.unlink()
    shutil.make_archive(str(PORTABLE.with_suffix('')), 'zip', DIST.parent, DIST.name)
    sys.path.insert(0, str(ROOT))
    from local_update import inspect_installer
    info = inspect_installer(SETUP, '0.3.2')
    digests=[]
    for artifact in (SETUP,PORTABLE):
        digests.append((hashlib.file_digest(artifact.open('rb'),'sha256').hexdigest(),artifact.name))
    (INSTALLER_DIR/'SHA256SUMS.txt').write_text(''.join(f'{digest}  {name}\n' for digest,name in digests),encoding='utf-8')
    digest=digests[0][0]
    print('Setup', SETUP)
    print('Product', info['version'], digest)
    print('SHA-256 catalog', INSTALLER_DIR / 'SHA256SUMS.txt')
    print('Unsigned installer is ready. It is not Authenticode-signed.')


if __name__ == '__main__':
    main()
