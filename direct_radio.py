"""Direct KiwiSDR PCM input for the embedded receiver."""
import socket
from pathlib import Path
import sys
import threading
import time
from types import SimpleNamespace
from urllib.parse import urlparse

class ClockResampler:
    """Continuous interpolation corrects a Kiwi's small sample-clock deviation."""
    def __init__(self,rate):
        if not 11900<=rate<=12100:
            raise ValueError(f'Expected nominal 12 kHz Kiwi audio, got {rate}')
        self.step=rate/12000
        self.cursor=0
        self.next=0.0
        self.previous=None

    def process(self,samples):
        import numpy as np
        data=np.asarray(samples)
        if not len(data):return np.empty(0,dtype=np.int16)
        start=self.cursor
        self.cursor+=len(data)
        if self.previous is not None:
            data=np.concatenate(([self.previous],data))
            start-=1
        last=start+len(data)-1
        count=max(0,int((last-self.next)/self.step)+1)
        positions=self.next+self.step*np.arange(count)
        out=np.interp(positions,np.arange(start,last+1),data)
        self.next+=self.step*count
        self.previous=data[-1]
        return np.rint(out).astype(np.int16)

class DirectKiwi:
    def __init__(self,config,report,on_audio):
        self.config,self.report,self.on_audio=config,report,on_audio
        self.stop_event=threading.Event()
        self.thread=None
        self.stream=None
        self.frequency=7107000
        self.last_audio=0
        self.error=''
        self.tuned=0
        self.settle_until=0

    def start(self,hz):
        self.frequency=hz
        self.thread=threading.Thread(target=self.run,daemon=True)
        self.thread.start()

    def tune(self,hz):
        self.frequency=hz
        self.settle_until=time.monotonic()+1.0
        self.on_audio(None,0,time.time(),None)

    def run(self):
        try:
            root=Path(__file__).resolve().parent/'vendor'/'kiwiclient'
            if not (root/'kiwi').exists():
                raise RuntimeError('Kiwi adapter missing. Run Start.cmd once to install dependencies.')
            if str(root) not in sys.path:
                sys.path.insert(0,str(root))
            from kiwi import KiwiSDRStream
            address=self.config['kiwi_url'].strip()
            uri=urlparse(address if '://' in address else 'http://'+address)
            if uri.scheme!='http' or not uri.hostname or uri.username or uri.password:
                raise ValueError('Enter a public HTTP KiwiSDR URL.')
            if uri.hostname.endswith('.proxy.kiwisdr.com'):
                raise ValueError('This adapter requires a direct receiver URL; use Find receivers.')
            port=uri.port or (80 if '://' in address else 8073)
            owner=self
            class Stream(KiwiSDRStream):
                def __init__(self):
                    super().__init__()
                    self._type='SND'
                    self._start_time=None
                    self._camp_wait_event=None
                    self._options=SimpleNamespace(wideband=False,ws_timestamp=int(time.time()),
                        socket_timeout=8,admin=False,nolocal=False,password='',tlimit_password='',
                        idx=0,wf_cal=None,modulation='usb',lp_cut=0,hp_cut=3500,freq_pbc=False,
                        S_meter=-1,ADC_OV=False,stats=False,netcat=False,sound=True,
                        tlimit=None,nb=False,nb_test=False,resample=0,multiple_connections=False,
                        test_mode=False,station=None,tstamp=False,sdt=0,user='GhostNetReceiver',
                        bad_cmd=False,server_host=uri.hostname,camp_allow_1ch=False,
                        rev_bin=False,filename='',dir='')
                def _setup_rx_params(self):
                    self.resampler=ClockResampler(self._sample_rate)
                    self.set_name('GhostNetReceiver')
                    self.set_mod('usb',0,3500,owner.frequency/1000)
                    self.set_agc(on=True)
                    self._set_snd_comp(False)
                    owner.tuned=owner.frequency
                    owner.report(f'Connected to {uri.hostname}; receiving {owner.frequency/1e6:.6f} MHz USB')
                def _process_audio_samples(self,seq,samples,rssi,fmt):
                    if owner.frequency!=owner.tuned:
                        self.set_mod('usb',0,3500,owner.frequency/1000)
                        owner.tuned=owner.frequency
                        self.resampler=ClockResampler(self._sample_rate)
                        owner.settle_until=time.monotonic()+1.0
                        owner.on_audio(None,0,time.time(),None)
                        return
                    if time.monotonic()<owner.settle_until:
                        return
                    owner.last_audio=time.monotonic()
                    owner.on_audio(self.resampler.process(samples),12000,time.time(),seq)
            self.stream=Stream()
            self.stream.connect(uri.hostname,port)
            self.stream.open()
            while not self.stop_event.is_set():
                self.stream.run()
        except Exception as exc:
            if not self.stop_event.is_set():
                self.error=str(exc)
                self.report('Online receiver stopped: '+self.error)
        finally:
            if self.stream:
                self.stream.close()

    def stop(self):
        self.stop_event.set()
        if self.stream and self.stream._socket:
            try:
                self.stream._socket.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        if self.thread:
            self.thread.join(timeout=10)
