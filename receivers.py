"""Optional hardware/audio dependencies are imported only when needed."""
import threading
import time
from contextlib import nullcontext

SOURCE_KIWI = 'KiwiSDR online'
SOURCE_AUDIO = 'USB audio (radio)'
SOURCE_SOAPY = 'USB SDR (SoapySDR)'
SOURCE_SOAPY_LEGACY = 'USB / SoapySDR'
RECEIVER_CHOICES = (SOURCE_KIWI, SOURCE_AUDIO, SOURCE_SOAPY)
PREFERRED_IQ_RATES = (1536000, 1920000, 960000, 768000)

def source_kind(config):
    source = (config or {}).get('source', SOURCE_KIWI)
    if source == SOURCE_KIWI:
        return 'kiwi'
    if source in (SOURCE_AUDIO, 'USB audio'):
        return 'audio'
    return 'soapy'

def audio_output_device(name):
    """PortAudio lists one Windows endpoint under several APIs; prefer WASAPI."""
    import sounddevice as sd
    hosts=sd.query_hostapis()
    candidates=[(i,d) for i,d in enumerate(sd.query_devices())
                if d['max_output_channels']>0 and d['name']==name]
    if not candidates:
        raise ValueError('Audio output device not found: '+name)
    wasapi=[i for i,d in candidates if hosts[d['hostapi']]['name']=='Windows WASAPI']
    if len(wasapi)==1:
        return wasapi[0]
    if len(candidates)==1:
        return candidates[0][0]
    raise ValueError('Audio device is ambiguous. Select a uniquely named endpoint.')

def _unique_endpoints(kind):
    import sounddevice as sd
    hosts = sd.query_hostapis()
    key = 'max_input_channels' if kind == 'input' else 'max_output_channels'
    seen = set()
    names = []
    for device in sd.query_devices():
        if device[key] <= 0:
            continue
        name = device['name']
        host = hosts[device['hostapi']]['name']
        if name in seen:
            continue
        if host != 'Windows WASAPI' and any(True for other in sd.query_devices()
            if other['name'] == name and other[key] > 0
            and hosts[other['hostapi']]['name'] == 'Windows WASAPI'):
            continue
        seen.add(name)
        names.append(name)
    return names

def list_input_devices():
    """Unique WASAPI-preferred capture endpoints for the USB-audio radio path."""
    return _unique_endpoints('input')

def list_output_devices():
    """Unique WASAPI-preferred playback endpoints for the speaker monitor."""
    return _unique_endpoints('output')

def audio_input_device(name=''):
    import sounddevice as sd
    hosts = sd.query_hostapis()
    inputs = [(i, d) for i, d in enumerate(sd.query_devices()) if d['max_input_channels'] > 0]
    if not inputs:
        raise RuntimeError('No capture device found. Plug in the radio USB audio cable.')
    name = (name or '').strip()
    if not name:
        default = sd.default.device[0]
        if default is None or default < 0:
            raise RuntimeError('Select a USB audio input in Advanced.')
        return int(default)
    candidates = [(i, d) for i, d in inputs if d['name'] == name or name.lower() in d['name'].lower()]
    if not candidates:
        raise ValueError('Audio input device not found: ' + name)
    wasapi = [i for i, d in candidates if hosts[d['hostapi']]['name'] == 'Windows WASAPI']
    if len(wasapi) == 1:
        return wasapi[0]
    if len(candidates) == 1:
        return candidates[0][0]
    raise ValueError('Audio input is ambiguous. Pick the WASAPI name from the device list.')

class USBDemodulator:
    """Continuous-state USB demodulator, integer-decimated IQ -> 48 kHz mono audio."""
    rate = 1536000
    output_rate = 48000
    shift = 12000

    def __init__(self, iq_rate=None):
        import numpy as np
        from scipy import signal
        self.rate = int(iq_rate or self.rate)
        if self.rate % self.output_rate:
            raise ValueError('IQ sample rate must divide 48 kHz.')
        self.decim = self.rate // self.output_rate
        self.np, self.signal = np, signal
        self.lp = signal.firwin(513, 8000, fs=self.rate)
        self.z1 = np.zeros(512, dtype=complex)
        taps = signal.firwin(257, 1400, fs=self.output_rate)
        self.bp = taps * np.exp(2j * np.pi * 1600 * np.arange(257) / self.output_rate)
        self.z2 = np.zeros(256, dtype=complex)
        self.index = 0
        self.gain = 1.0

    def process(self, iq):
        np, signal = self.np, self.signal
        n = self.index + np.arange(len(iq))
        mixed = iq * np.exp(-2j * np.pi * self.shift * (n % self.rate) / self.rate)
        filtered, self.z1 = signal.lfilter(self.lp, [1.0], mixed, zi=self.z1)
        down = filtered[(-self.index) % self.decim::self.decim]
        self.index += len(iq)
        if len(down) == 0:
            return np.empty(0, dtype=np.float32)
        usb, self.z2 = signal.lfilter(self.bp, [1.0], down, zi=self.z2)
        audio = usb.real
        rms = float(np.sqrt(np.mean(audio ** 2)))
        wanted = min(500.0, 0.12 / max(rms, 1e-7))
        self.gain = 0.9 * self.gain + 0.1 * wanted
        return np.clip(audio * self.gain, -0.95, 0.95).astype(np.float32)

def _choose_iq_rate(device, soapy):
    for rate in PREFERRED_IQ_RATES:
        try:
            device.setSampleRate(soapy.SOAPY_SDR_RX, 0, rate)
            actual = device.getSampleRate(soapy.SOAPY_SDR_RX, 0)
            if abs(actual - rate) <= 1:
                return int(actual)
        except Exception:
            continue
    raise RuntimeError(
        'USB SDR must support 1.536, 1.92, 0.96, or 0.768 MHz IQ. '
        'Use an HF-capable SoapySDR driver, or choose USB audio (radio) instead.'
    )

class USBReceiver:
    def __init__(self, config, report, audio_sink=None):
        self.config, self.report = config, report
        self.audio_sink=audio_sink
        self.stop_event = threading.Event()
        self.thread = None
        self.frequency = 0
        self.last_audio = 0
        self.error = ''

    def start(self, hz):
        self.frequency = hz
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def tune(self, hz):
        self.frequency = hz

    def run(self):
        device = stream = None
        try:
            import numpy as np
            import sounddevice as sd
            try:
                import SoapySDR as soapy
            except ImportError as exc:
                raise RuntimeError(
                    'SoapySDR is not installed. For a USB HF dongle install PothosSDR. '
                    'For a transceiver with USB audio, choose USB audio (radio) instead.'
                ) from exc
            args = dict(item.strip().split('=', 1) for item in self.config.get('usb_args', '').split(',') if item.strip())
            found = soapy.Device.enumerate(args)
            if not found:
                raise RuntimeError('No matching SoapySDR receiver found. Check USB driver and device arguments (driver=rtlsdr,serial=…).')
            if len(found) > 1 and not args:
                raise RuntimeError('Multiple USB receivers found. Select one using driver and serial arguments.')
            device = soapy.Device(found[0])
            iq_rate = _choose_iq_rate(device, soapy)
            try:
                device.setGain(soapy.SOAPY_SDR_RX, 0, float(self.config.get('gain', 30)))
            except Exception as exc:
                self.report('USB gain was not applied: ' + str(exc))
            stream = device.setupStream(soapy.SOAPY_SDR_RX, soapy.SOAPY_SDR_CF32)
            if device.activateStream(stream) != 0:
                raise RuntimeError('Could not activate USB receive stream.')
            buffer = np.empty(32768, np.complex64)
            current = None
            settle_until = 0
            last_read = time.monotonic()
            output_context=(nullcontext(None) if self.audio_sink else
                sd.OutputStream(device=audio_output_device(self.config['audio_device']),samplerate=48000,channels=1,dtype='float32'))
            with output_context as output:
                while not self.stop_event.is_set():
                    desired = self.frequency
                    if desired != current:
                        rf = desired-USBDemodulator.shift
                        ranges = list(device.getFrequencyRange(soapy.SOAPY_SDR_RX, 0) or [])
                        if ranges and not any(r.minimum() <= rf <= r.maximum() for r in ranges):
                            raise RuntimeError('Receiver does not expose this HF frequency. An HF-capable device/driver is required.')
                        device.setFrequency(soapy.SOAPY_SDR_RX, 0, rf)
                        actual = device.getFrequency(soapy.SOAPY_SDR_RX, 0)
                        if abs(actual-rf)>5:
                            raise RuntimeError(f'Receiver tuning readback differs: requested {rf}, got {actual}.')
                        current = desired
                        demod = USBDemodulator(iq_rate)
                        settle_until = time.monotonic()+0.5
                        if self.audio_sink:self.audio_sink(None,0,time.time(),None)
                        self.report(f'USB SDR tuned to {desired/1e6:.6f} MHz USB at {iq_rate/1e6:.3f} MHz IQ')
                    result = device.readStream(stream, [buffer], len(buffer), timeoutUs=200000)
                    if result.ret <= 0:
                        if result.ret not in (soapy.SOAPY_SDR_TIMEOUT, soapy.SOAPY_SDR_OVERFLOW):
                            raise RuntimeError(f'USB stream error {result.ret}')
                        if result.ret == soapy.SOAPY_SDR_OVERFLOW:
                            self.report('USB overflow: audio gap; some messages may be lost')
                            if self.audio_sink:self.audio_sink(None,0,time.time(),None)
                        if time.monotonic()-last_read>5:
                            raise RuntimeError('USB receiver stopped delivering samples.')
                        continue
                    last_read = time.monotonic()
                    if time.monotonic()<settle_until:
                        continue
                    audio = demod.process(buffer[:result.ret])
                    if len(audio):
                        if self.audio_sink:
                            self.audio_sink(audio,48000,time.time(),None)
                            underflow=False
                        else:
                            underflow = output.write(audio)
                        self.last_audio = time.monotonic()
                        if underflow:
                            self.report('Audio output underflow: decoder audio gap')
        except Exception as exc:
            self.error = str(exc)
            self.report('USB receiver failed: '+self.error)
        finally:
            if stream is not None:
                try:
                    device.deactivateStream(stream)
                    device.closeStream(stream)
                except Exception:
                    pass

    def stop(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=5)
            if self.thread.is_alive():
                raise RuntimeError('USB driver did not stop. Restart the app before reconnecting.')

class USBAudioReceiver:
    """Capture USB-codec audio from a radio. The radio is tuned by the operator; this path does not transmit."""

    def __init__(self, config, report, audio_sink=None):
        self.config, self.report = config, report
        self.audio_sink = audio_sink
        self.stop_event = threading.Event()
        self.thread = None
        self.frequency = 0
        self.last_audio = 0
        self.error = ''
        self.sequence = 0
        self.device_name = ''

    def start(self, hz):
        self.frequency = hz
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def tune(self, hz):
        if hz == self.frequency:
            return
        self.frequency = hz
        self.report(f'Tune the radio to {hz / 1e6:.6f} MHz USB. USB audio does not change the radio.')

    def run(self):
        try:
            import numpy as np
            import sounddevice as sd
            if self.audio_sink is None:
                raise RuntimeError('USB audio requires the integrated decoder.')
            index = audio_input_device(self.config.get('audio_device', ''))
            info = sd.query_devices(index)
            self.device_name = info['name']
            channels = 1 if info['max_input_channels'] >= 1 else info['max_input_channels']
            rate = 48000
            try:
                sd.check_input_settings(device=index, samplerate=rate, channels=1, dtype='float32')
            except Exception:
                rate = int(info.get('default_samplerate') or 48000)
            self.report(
                f'USB audio from {self.device_name} at {rate} Hz. Tune the radio to {self.frequency / 1e6:.6f} MHz USB.'
            )
            owner = self

            def callback(indata, frames, time_info, status):
                if owner.stop_event.is_set():
                    raise sd.CallbackStop
                if status:
                    if getattr(status,'input_overflow',False):
                        owner.audio_sink(None,0,time.time(),None)
                mono = np.ascontiguousarray(indata[:, 0] if indata.ndim > 1 else indata)
                owner.last_audio = time.monotonic()
                owner.sequence = (owner.sequence + 1) & 0xffffffff
                receipt=time.time()
                try:
                    receipt += float(time_info.inputBufferAdcTime)+frames/rate-float(time_info.currentTime)
                except (AttributeError,TypeError,ValueError):
                    pass
                owner.audio_sink(mono.copy(), rate, receipt, owner.sequence)

            with sd.InputStream(device=index, samplerate=rate, channels=channels, dtype='float32',
                                blocksize=2048, callback=callback):
                while not self.stop_event.is_set():
                    self.stop_event.wait(0.2)
        except Exception as exc:
            if not self.stop_event.is_set():
                self.error = str(exc)
                self.report('USB audio failed: ' + self.error)

    def stop(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=5)
            if self.thread.is_alive():
                raise RuntimeError('USB audio did not stop. Restart the app before reconnecting.')
