"""In-process JS8 decoding. No JS8Call application, UDP listener or virtual cable."""
import ctypes
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import threading
from storage import runtime_root

ROOT=runtime_root()
MODES={0:15,1:10,2:6,4:30,8:4}

class EmbeddedDecoder:
    def __init__(self,library=None):
        self.directory=Path(library).resolve().parent if library else ROOT/'bin'
        self.search=[]
        if os.name=='nt':
            for folder in (self.directory, self.directory.parent):
                if folder.is_dir():
                    self.search.append(os.add_dll_directory(str(folder)))
        self.library=ctypes.CDLL(str(library or self.directory/'ghostnet_js8.dll'))
        for export in ('ghostnet_decode','ghostnet_validate_message'):
            if not hasattr(self.library,export):
                raise RuntimeError('Decoder library is incompatible (missing '+export+'). Reinstall the complete release.')
        self.callback_type=ctypes.CFUNCTYPE(None,ctypes.c_char_p,ctypes.c_void_p)
        self.library.ghostnet_decode.argtypes=[ctypes.POINTER(ctypes.c_int16),ctypes.c_int,
            ctypes.c_int,ctypes.c_int,self.callback_type,ctypes.c_void_p]
        self.library.ghostnet_decode.restype=ctypes.c_int
        self.lock=threading.Lock()

    def validate_message(self,command,body):
        function=self.library.ghostnet_validate_message
        function.argtypes=[ctypes.c_char_p,ctypes.c_char_p,self.callback_type,ctypes.c_void_p]
        function.restype=ctypes.c_int
        result=[]
        callback=self.callback_type(lambda raw,context:result.append(json.loads(raw.decode('utf-8'))))
        status=function(command.encode('utf-8'),body.encode('utf-8'),callback,None)
        if status<0 or not result:raise RuntimeError('Message checksum validation failed')
        return result[0]

    def decode(self,samples,mode=0,utc=0):
        import numpy as np
        if mode not in MODES:
            raise ValueError('Unsupported JS8 submode')
        data=np.ascontiguousarray(samples,dtype=np.int16)
        if data.ndim!=1 or not 0<len(data)<=MODES[mode]*12000:
            raise ValueError('Expected one mono JS8 cycle at 12000 Hz')
        result=[]
        errors=[]
        def received(raw,_):
            try:
                item=json.loads(raw.decode('utf-8'))
                if 'error' in item:
                    errors.append(item['error'])
                else:
                    result.append(item)
            except Exception as exc:
                errors.append(str(exc))
        callback=self.callback_type(received)
        with self.lock:
            status=self.library.ghostnet_decode(data.ctypes.data_as(ctypes.POINTER(ctypes.c_int16)),
                len(data),mode,int(utc),callback,None)
        if status<0 or errors:
            raise RuntimeError('Embedded JS8 decode failed: '+('; '.join(errors) or str(status)))
        return result
