from pathlib import Path
root = Path(SPECPATH)
binaries = [(str(path), 'bin') for path in (root / 'bin').glob('*.dll')]
datas = [
    (str(root / 'fixtures'), 'fixtures'),
    (str(root / 'vendor' / 'kiwiclient'), 'vendor/kiwiclient'),
    (str(root / 'README.md'), '.'),
    (str(root / 'QUICKSTART.md'), '.'),
    (str(root / 'VALIDATION.md'), '.'),
    (str(root / 'REVIEW_FIXES.md'), '.'),
    (str(root / 'CHANGELOG.md'), '.'),
    (str(root / 'THIRD_PARTY.md'), '.'),
    (str(root / 'LICENSE'), '.'),
    (str(root / 'ghostnet.ico'), '.'),
    (str(root / 'ghostnet-icon.png'), '.'),
]
a = Analysis(
    [str(root / 'app.py')],
    pathex=[str(root), str(root / 'vendor' / 'kiwiclient')],
    binaries=binaries,
    datas=datas,
    hiddenimports=['kiwi', 'mod_pywebsocket', 'scipy.signal', 'sounddevice'],
    excludes=['SoapySDR'],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='GhostNetReceiver',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    version=str(root / 'file_version_info.txt'),
    icon=str(root / 'ghostnet.ico'),
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name='GhostNetReceiver',
)
