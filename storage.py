"""Version-independent data folder and non-destructive legacy import."""
import os
import sys
from pathlib import Path
import shutil
import sqlite3

VERSION='0.4.2'

def runtime_root():
    """App files: source folder, or PyInstaller _internal when frozen."""
    if getattr(sys, 'frozen', False):
        return Path(getattr(sys, '_MEIPASS', Path(sys.executable).parent / '_internal'))
    return Path(__file__).resolve().parent

def default_data_dir():
    return Path(os.environ.get('LOCALAPPDATA',Path.home()/'AppData/Local'))/'GhostNetReceiver'/'data'

def import_legacy(source,destination):
    source,destination=Path(source),Path(destination)
    destination.mkdir(parents=True,exist_ok=True)
    if source.resolve()==destination.resolve():return []
    copied=[]
    # SQLite backup includes committed WAL data even if another reader is open.
    old=source/'messages.sqlite3';new=destination/'messages.sqlite3'
    if old.is_file() and not new.exists():
        temporary=new.with_suffix('.importing')
        with sqlite3.connect(old.as_uri()+'?mode=ro',uri=True) as src, sqlite3.connect(temporary) as dest:
            src.backup(dest)
        temporary.replace(new);copied.append('messages')
    for name in ('settings.json',):
        if (source/name).is_file() and not (destination/name).exists():
            shutil.copy2(source/name,destination/name);copied.append(name)
    return copied
