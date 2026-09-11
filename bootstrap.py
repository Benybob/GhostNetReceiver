"""First-run setup. Downloads a pinned upstream KiwiClient into this app folder."""
import io
from pathlib import Path
import subprocess
import sys
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parent
KIWI_COMMIT = '4eb733e6b6147f7fbeb97ced64cdac029b202d18'

def main():
    requirements=ROOT/'requirements.txt'
    stamp=Path(sys.prefix)/'ghostnet-requirements-installed.txt'
    wanted=requirements.read_text()
    if not stamp.exists() or stamp.read_text()!=wanted:
        subprocess.run([sys.executable,'-m','pip','install','-r',str(requirements)],check=True)
        stamp.parent.mkdir(parents=True,exist_ok=True)
        stamp.write_text(wanted)
    vendor=ROOT/'vendor'/'kiwiclient'
    if not (vendor/'kiwiclientd.py').exists():
        print('Downloading pinned KiwiClient audio adapter…')
        url=f'https://codeload.github.com/jks-prv/kiwiclient/zip/{KIWI_COMMIT}'
        with urllib.request.urlopen(url,timeout=60) as response:
            data=response.read(30_000_001)
        if len(data)>30_000_000:
            raise RuntimeError('Unexpectedly large KiwiClient archive')
        prefix=f'kiwiclient-{KIWI_COMMIT}/'
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            for item in archive.infolist():
                if not item.filename.startswith(prefix) or item.is_dir():
                    continue
                relative=Path(item.filename[len(prefix):])
                destination=(vendor/relative).resolve()
                if not destination.is_relative_to(vendor.resolve()):
                    raise RuntimeError('Unsafe archive path')
                destination.parent.mkdir(parents=True,exist_ok=True)
                destination.write_bytes(archive.read(item))
    print('Setup complete. Starting GhostNet Receiver.')

if __name__=='__main__':
    main()
