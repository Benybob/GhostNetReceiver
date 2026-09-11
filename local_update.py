"""Inspect a user-selected installer before handing off a local update."""
import ctypes
from ctypes import wintypes
import hashlib
from pathlib import Path
import re
import subprocess

def version_tuple(value):
    """Accept 0.3.0, 0.3G, 0.3.0G, or a four-part Windows file version."""
    value=str(value).strip()
    if not re.fullmatch(r'\d+\.\d+(?:\.\d+)?(?:\.\d+)?|\d+\.\d+[A-Za-z]',value):
        raise ValueError('Invalid release version')
    parts=[p for p in re.sub(r'[A-Za-z]+$', '', value).strip('.').split('.') if p.isdigit()]
    while len(parts)<3:
        parts.append('0')
    return tuple(map(int, parts[:3]))

def inspect_installer(path,current):
    path=Path(path).resolve()
    if path.suffix.lower()!='.exe' or not path.is_file():raise ValueError('Select a GhostNet Receiver Setup .exe file.')
    dll=ctypes.windll.version
    dll.GetFileVersionInfoSizeW.argtypes=[wintypes.LPCWSTR,ctypes.POINTER(wintypes.DWORD)]
    dll.GetFileVersionInfoW.argtypes=[wintypes.LPCWSTR,wintypes.DWORD,wintypes.DWORD,wintypes.LPVOID]
    dll.VerQueryValueW.argtypes=[wintypes.LPCVOID,wintypes.LPCWSTR,ctypes.POINTER(ctypes.c_void_p),ctypes.POINTER(wintypes.UINT)]
    size=dll.GetFileVersionInfoSizeW(str(path),None)
    if not size:raise ValueError('This file has no installer version information.')
    buffer=ctypes.create_string_buffer(size)
    if not dll.GetFileVersionInfoW(str(path),0,size,buffer):raise ValueError('Cannot read installer metadata.')
    def query(key):
        ptr=ctypes.c_void_p();length=wintypes.UINT()
        if not dll.VerQueryValueW(buffer,key,ctypes.byref(ptr),ctypes.byref(length)):return None,0
        return ptr,length.value
    ptr,length=query('\\VarFileInfo\\Translation')
    if not ptr or length<4:raise ValueError('Missing installer product information.')
    languages=ctypes.cast(ptr,ctypes.POINTER(ctypes.c_ushort))
    prefix=f'\\StringFileInfo\\{languages[0]:04x}{languages[1]:04x}\\'
    def text(key):
        ptr,length=query(prefix+key)
        return ctypes.wstring_at(ptr) if ptr and length else ''
    product=text('ProductName').strip();version=text('ProductVersion').strip()
    description=text('FileDescription').strip()
    original=text('OriginalFilename').strip()
    if product!='GhostNet Receiver':raise ValueError('This is not a GhostNet Receiver installer.')
    if description!='GhostNet Receiver Setup' or original!='GhostNetReceiverSetup.exe':
        raise ValueError('Choose GhostNet Receiver Setup.exe, not the application executable.')
    if version_tuple(version)<=version_tuple(current):raise ValueError('Choose an installer newer than '+current+'.')
    # Metadata identifies the product for usability; it is not a signature or trust proof.
    digest=hashlib.file_digest(path.open('rb'),'sha256').hexdigest()
    return {'path':str(path),'version':version,'sha256':digest}

def launch_installer(info):
    # No shell interpolation; Windows setup provides its own interactive review.
    path=Path(info['path'])
    current=hashlib.file_digest(path.open('rb'),'sha256').hexdigest()
    if current!=info['sha256']:
        raise ValueError('The selected installer changed after inspection. Choose it again.')
    return subprocess.Popen([str(path)],close_fds=True)
