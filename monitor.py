"""Explicit listening-output monitor; no implicit system default."""
import queue
import threading
import numpy as np

def monitor_samples(samples, volume=0.3, agc=False, gain=1.0):
    """Prepare monitor-only audio. This never feeds the decoder path."""
    audio = np.asarray(samples, dtype=np.float32) / 32768
    next_gain = float(gain)
    if agc and len(audio):
        peak = float(np.max(np.abs(audio)))
        wanted = min(8.0, .35 / max(peak, .01))
        # Turn down quickly to avoid a loud burst and recover slowly on weak audio.
        speed = .65 if wanted < next_gain else .06
        next_gain += (wanted - next_gain) * speed
        audio = np.tanh(audio * next_gain)
    return (np.repeat(audio, 4) * float(volume)).reshape(-1, 1), next_gain


def upsample_12k_to_48k(samples,volume=0.3):
    return monitor_samples(samples, volume)[0]

class AudioMonitor:
    PLAY_RATE=48000
    def __init__(self,volume=0.3,agc=False):
        self.volume=float(volume);self.agc=bool(agc);self.agc_gain=1.0;self.enabled=threading.Event();self.stop_event=threading.Event()
        self.queue=queue.Queue(maxsize=12);self.thread=None;self.stream=None
        self.device_name='';self.error='';self.lock=threading.RLock()
    def push(self,samples):
        if not self.enabled.is_set():return
        try:self.queue.put_nowait(np.asarray(samples,dtype=np.int16).copy())
        except queue.Full:
            try:self.queue.get_nowait()
            except queue.Empty:pass
    def set_enabled(self,on,device_name=''):
        with self.lock:
            if on and self.enabled.is_set() and device_name==self.device_name:return
            self.enabled.clear();self.stop_event.set()
            if self.stream is not None:
                try:self.stream.abort()
                except Exception:pass
            if self.thread and self.thread is not threading.current_thread():
                self.thread.join(3)
                if self.thread.is_alive():raise RuntimeError('Listening output did not stop; do not reconnect it.')
            while not self.queue.empty():
                try:self.queue.get_nowait()
                except queue.Empty:break
            if not on:return
            if not device_name.strip():raise ValueError('Choose a headphones/speakers output in Advanced first.')
            from receivers import audio_output_device
            index=audio_output_device(device_name)
            self.device_name=device_name;self.error='';self.stop_event.clear();self.enabled.set()
            self.agc_gain=1.0
            self.thread=threading.Thread(target=self._run,args=(index,),daemon=True);self.thread.start()
    def _run(self,index):
        try:
            import sounddevice as sd
            with sd.OutputStream(device=index,samplerate=self.PLAY_RATE,channels=1,dtype='float32',latency='low') as stream:
                self.stream=stream
                while not self.stop_event.is_set():
                    try:chunk=self.queue.get(timeout=.1)
                    except queue.Empty:continue
                    if self.enabled.is_set():
                        output,self.agc_gain=monitor_samples(chunk,self.volume,self.agc,self.agc_gain)
                        stream.write(output)
        except Exception as exc:
            if not self.stop_event.is_set():self.error=str(exc)
        finally:self.stream=None;self.enabled.clear()
