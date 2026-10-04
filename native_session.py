"""Direct PCM -> in-process JS8 -> durable journal."""
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
import logging
import queue
import threading
import time
import wave

import numpy as np

from core import UTC, classify, listen_plan
from direct_radio import DirectKiwi
from embedded import EmbeddedDecoder, MODES
from receivers import USBAudioReceiver, USBReceiver, source_kind
from recovery import ReceiverPool, ReceiverUnavailable
from conversations import Assembler
from reports import heard_report
from rtty import RttyDecoder
from monitor import AudioMonitor
from audio_stream import StreamResampler

SPEED_CHOICES = ('Normal only', 'Normal + Fast', 'All speeds')
SPEED_MODES = {
    'Normal only': (0,),
    'Normal + Fast': (0, 1),
    'All speeds': (0, 1, 2, 4, 8),
}
HUNT_OFFSETS = (0.0, -1.0, 1.0, -2.0, 2.0, -3.0, 3.0)


def nutc_from_epoch(epoch):
    moment = datetime.fromtimestamp(float(epoch), timezone.utc)
    return moment.hour * 10000 + moment.minute * 100 + moment.second


def enabled_modes(config=None):
    name = (config or {}).get('js8_speeds', 'Normal + Fast')
    return {mode: MODES[mode] for mode in SPEED_MODES.get(name, SPEED_MODES['Normal + Fast'])}


def downsample_48k_to_12k(samples):
    """Cheap anti-aliased 4:1 decimation for USB audio already band-limited to ~3 kHz."""
    data = np.asarray(samples)
    if data.dtype != np.int16:
        data = np.clip(np.rint(np.clip(data, -1.0, 1.0) * 32767.0), -32768, 32767).astype(np.int16)
    extra = len(data) % 4
    if extra:
        data = data[:len(data) - extra]
    if not len(data):
        return np.empty(0, dtype=np.int16)
    return data.reshape(-1, 4).mean(axis=1).astype(np.int16)

def to_int16_12k(samples, rate):
    rate = int(rate)
    samples = np.asarray(samples)
    if not len(samples):
        return np.empty(0, dtype=np.int16)
    if rate == 12000:
        data = np.asarray(samples)
        if data.dtype == np.int16:
            return np.ascontiguousarray(data)
        return np.clip(np.rint(np.clip(data, -1.0, 1.0) * 32767.0), -32768, 32767).astype(np.int16)
    if rate == 48000:
        return downsample_48k_to_12k(samples)
    from math import gcd
    from scipy.signal import resample_poly
    data = np.asarray(samples, dtype=np.float64)
    if np.asarray(samples).dtype == np.int16 or np.max(np.abs(data), initial=0) > 1.5:
        data = data / 32768.0
    factor = gcd(rate, 12000)
    out = resample_poly(data, 12000 // factor, rate // factor)
    return np.clip(np.rint(out * 32767.0), -32768, 32767).astype(np.int16)


class AudioClock:
    """Map a 12 kHz stream onto UTC using packet arrival times as a PLL.

    JS8 dies if the decode window is more than about two seconds off UTC.
    Codex locked origin to the first Kiwi packet arrival and never corrected it.
    This clock keeps sample-count time and slowly steers it toward wall-clock UTC.
    """
    RATE = 12000

    def __init__(self, latency=0.25, gain=0.08):
        self.latency = float(latency)
        self.gain = float(gain)
        self.reset()

    def reset(self):
        self.buffer = np.empty(0, dtype=np.int16)
        self.end_utc = None
        self.last = {}
        self.error = 0.0

    def push(self, samples, receipt):
        samples = np.ascontiguousarray(samples, dtype=np.int16)
        if not len(samples):
            return
        duration = len(samples) / self.RATE
        observed_end = float(receipt) - self.latency
        if self.end_utc is None:
            self.end_utc = observed_end
        else:
            predicted = self.end_utc + duration
            residual = observed_end - predicted
            self.error = 0.9 * self.error + 0.1 * residual
            self.end_utc = predicted + self.gain * residual
        self.buffer = np.concatenate((self.buffer, samples))
        max_len = 90 * self.RATE
        if len(self.buffer) > max_len:
            self.buffer = self.buffer[len(self.buffer) - max_len:]

    def start_utc(self):
        if self.end_utc is None or not len(self.buffer):
            return None
        return self.end_utc - len(self.buffer) / self.RATE

    def cycle_at(self, period, hunt=0.0, mark=True, grid=None):
        start = self.start_utc()
        if start is None:
            return None
        period = float(period)
        hunt = float(hunt)
        end = self.end_utc
        grid = round(((end - period) // period) * period, 6) if grid is None else grid
        begin = round(grid + hunt, 6)
        if grid <= self.last.get(period, -1e18):
            return None
        if begin + period > end + 1.0 / self.RATE:
            return None
        offset = int(round((begin - start) * self.RATE))
        length = int(period * self.RATE)
        if offset + length > len(self.buffer):
            return None
        if offset < 0:
            pad = -offset
            if pad > int(0.25 * self.RATE):
                return None
            chunk = np.concatenate([np.zeros(pad, dtype=np.int16), self.buffer[:length - pad]])
        else:
            chunk = self.buffer[offset:offset + length]
        if len(chunk) != length:
            return None
        if mark:
            self.last[period] = grid
        return begin, chunk

    def latest_cycle(self, period, hunt=0.0):
        return self.cycle_at(period, hunt, mark=True)


class FrameLogger:
    def __init__(self, journal, notify=lambda: None, validate=None, on_complete=lambda message: None):
        if validate is None:
            validate = EmbeddedDecoder().validate_message
        self.journal = journal
        self.notify = notify
        self.assembler = Assembler(journal, validate)
        self.pending = self.assembler.pending
        self.on_complete = on_complete

    def write(self, frames, source, hz, epoch):
        best = {}
        for frame in frames:
            key = (frame['frame'], round(frame['offset'] / 10), frame['mode'])
            if key not in best or frame['snr'] > best[key]['snr']:
                best[key] = frame
        for frame in best.values():
            directed = frame.get('directed', [])
            params = {
                'DIAL': hz, 'FREQ': hz + frame['offset'], 'OFFSET': frame['offset'],
                'UTC': round(epoch * 1000), 'SNR': frame['snr'], 'SPEED': frame['mode'],
                'TDRIFT': frame['dt'], 'BITS': frame['bits'], 'FRAME_TYPE': frame['frame_type'],
                'RAW_FRAME': frame['frame'], 'LOW_CONFIDENCE': frame['low_confidence'],
            }
            if len(directed) > 2:
                params.update(FROM=directed[0], TO=directed[1], CMD=directed[2])
            elif frame.get('compound'):
                params['FROM'] = frame['compound']
            packet = {'type': 'RX.ACTIVITY', 'value': frame['text'], 'params': params}
            raw_id = self.journal.ingest(packet, source, hz)
            if not raw_id:
                continue
            complete = self.assembler.add(frame, raw_id, source, hz, epoch)
            self.notify()
            if complete:
                self.on_complete(complete)


class NativeSession:
    def __init__(self, config, journal, data_dir, updates):
        self.config = config
        self.journal = journal
        self.data_dir = data_dir
        self.updates = updates
        self.thread = None
        self.receiver = None
        self.error = ''
        self.stop_event = threading.Event()
        self.audio = queue.Queue(maxsize=600)
        self.last_decode = 0
        self.hz = 0
        self.generation = 0
        self.audio_overflow = False
        with journal.lock:
            start_id = journal.db.execute('SELECT COALESCE(MAX(id),0) FROM messages').fetchone()[0]
        self.metrics = {
            'start_message_id': start_id,
            'connections': 0, 'recoveries': 0, 'audio_packets': 0,
            'decode_cycles': 0, 'decoded_frames': 0, 'audio_gaps': 0,
            'overflows': 0, 'clock_offset': 0.0, 'audio_seconds': 0.0,
            'rtty_lines': 0, 'tagged': 0, 'flash': 0, 'receivers': [],
            'started_utc': datetime.now(timezone.utc).isoformat(), 'level': 0.0,
        }
        if config.get('lane_name'):
            self.metrics['source_prefix'] = config['lane_name'] + ' | '
        self.receiver_factory = DirectKiwi
        self.audio_receiver_factory = USBAudioReceiver
        self.usb_receiver_factory = USBReceiver
        self.decoder_factory = EmbeddedDecoder
        self.clock = AudioClock()
        self.monitor = AudioMonitor()
        self.latest_plan = {'banner': '', 'usb_hz': 7107000, 'sideband': 'USB', 'decode': 'JS8'}
        self.decode_mode = 'JS8'
        lane_slug = ''.join(c.lower() if c.isalnum() else '-' for c in config.get('lane_name','')).strip('-')
        log = Path(data_dir) / (('session-'+lane_slug+'.log') if lane_slug else 'session.log')
        self._log = logging.getLogger(f'ghostnet.session.{id(self)}')
        self._log.handlers.clear()
        self._log.propagate = False
        self._log.setLevel(logging.INFO)
        self._log_handler = RotatingFileHandler(log, maxBytes=1_000_000, backupCount=5, encoding='utf-8')
        self._log_handler.setFormatter(logging.Formatter('%(asctime)s %(message)s'))
        self._log.addHandler(self._log_handler)

    def report(self, message):
        try:
            self._log.info(message)
        except Exception:
            pass
        self.journal.event(message)
        self.updates.put(('event', message))

    def start(self):
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def on_audio(self, samples, rate, receipt, sequence=None):
        if samples is None:
            self.generation += 1
            return
        try:
            self.audio.put_nowait((np.asarray(samples).copy(), rate, receipt, sequence, self.generation))
        except queue.Full:
            self.audio_overflow = True
            try:
                self.audio.get_nowait()
            except queue.Empty:
                pass
            try:
                self.audio.put_nowait((np.asarray(samples).copy(), rate, receipt, sequence, self.generation))
            except queue.Full:
                pass

    def desired(self):
        if self.config.get('tuning') == 'Hold 40m JS8':
            self.latest_plan = {
                'hz': 7107000, 'decode': 'JS8', 'mode': 'JS8',
                'reason': 'Holding 40m JS8', 'banner': 'Holding 7.107 MHz USB',
                'usb_hz': 7107000, 'sideband': 'USB',
            }
            return 7107000, 'JS8', 'Holding 40m JS8'
        plan = listen_plan(self.config['region'], datetime.now(UTC), rtty=self.config.get('rtty', False))
        self.latest_plan = plan
        return plan['hz'], plan['decode'], plan['reason']

    def run(self):
        online = source_kind(self.config) == 'kiwi'
        pool = ReceiverPool(self.config) if online else None
        try:
            decoder = self.decoder_factory()
            while not self.stop_event.is_set():
                try:
                    if online:
                        self.updates.put(('telemetry', {
                            'connected': False, 'audio': False,
                            'frames': self.metrics['decoded_frames'],
                        }))
                        try:
                            station = pool.next(self.desired()[0])
                            self.station = station
                        except Exception as exc:
                            raise ReceiverUnavailable(str(exc)) from exc
                        if self.stop_event.is_set():
                            break
                        self.config['kiwi_url'] = station['url']
                        self.updates.put(('station', station.get('name', station['url']) + ' · ' + station['url']))
                    self.generation += 1
                    while not self.audio.empty():
                        try:
                            self.audio.get_nowait()
                        except queue.Empty:
                            break
                    self._receive(decoder, pool)
                    break
                except ReceiverUnavailable as exc:
                    if self.stop_event.is_set():
                        break
                    if not online:
                        raise
                    self.metrics['recoveries'] += 1
                    delay = pool.delay()
                    self.report(f'Receiver unavailable: {exc}. Trying again in {delay}s.')
                    self.updates.put(('health', f'Reconnecting in {delay}s… Your messages are saved.'))
                    self.updates.put(('telemetry', {
                        'connected': False, 'audio': False,
                        'frames': self.metrics['decoded_frames'],
                    }))
                    if self.stop_event.wait(delay):
                        break
        except Exception as exc:
            self.error = str(exc)
            self.updates.put(('error', self.error))
            try:
                self.journal.event('Reception stopped: ' + self.error)
            except Exception:
                pass
        finally:
            try:
                self.monitor.set_enabled(False)
                with self.journal.lock:
                    self.metrics['end_message_id'] = self.journal.db.execute('SELECT COALESCE(MAX(id),0) FROM messages').fetchone()[0]
                self.metrics['ended_utc'] = datetime.now(timezone.utc).isoformat()
                lane = ''.join(c.lower() if c.isalnum() else '-' for c in self.config.get('lane_name','')).strip('-')
                report_path = Path(self.data_dir) / 'net-night' / (('report-'+lane+'.json') if lane else 'report.json')
                heard_report(self.journal, self.metrics, report_path, self.latest_plan)
                report_path.with_name('report-' + str(time.time_ns()) + '.json').write_bytes(report_path.read_bytes())
            except Exception as exc:
                self.updates.put(('event', 'Session cleanup/report failed: ' + str(exc)))
            finally:
                self._log.removeHandler(self._log_handler)
                self._log_handler.close()
                self.updates.put(('monitor', False))
                self.updates.put(('stopped', None))

    def _receive(self, decoder, pool):
        try:
            logger = FrameLogger(
                self.journal,
                lambda: self.updates.put(('message', None)),
                decoder.validate_message,
                lambda message: self.updates.put(('complete', message)),
            )
            self.hz, self.decode_mode, reason = self.desired()
            kind = source_kind(self.config)
            if kind == 'kiwi':
                self.receiver = self.receiver_factory(self.config, self.report, self.on_audio)
            elif kind == 'audio':
                self.receiver = self.audio_receiver_factory(self.config, self.report, self.on_audio)
            else:
                self.receiver = self.usb_receiver_factory(self.config, self.report, self.on_audio)
            self.receiver.start(self.hz)
            connected_at = time.monotonic()
            stable = False
            self.metrics['connections'] += 1
            ident = self.config.get('kiwi_url') or self.config.get('audio_device') or self.config.get('usb_args') or kind
            self.metrics['receivers'].append(ident)
            speeds = enabled_modes(self.config)
            rtty = self._new_rtty()
            rtty_capture = None
            rtty_capture_path = None

            def close_rtty_capture():
                nonlocal rtty_capture
                capture, rtty_capture = rtty_capture, None
                if capture is not None:
                    capture.close()
                    self.report('Saved RTTY calibration audio to ' + str(rtty_capture_path))
            converter = None
            dumped = False
            next_hamlib = 0
            self.confirmed_hz = 0
            self.report('Integrated receiver started. ' + reason + '. Speeds: ' + self.config.get('js8_speeds', 'Normal + Fast'))
            self.updates.put(('banner', self.latest_plan.get('banner', '')))
            kind = source_kind(self.config)
            if kind == 'audio':
                source = self.config['source'] + ':' + (self.config.get('audio_device') or 'default')
            elif kind == 'soapy':
                source = self.config['source'] + ':' + (self.config.get('usb_args') or 'auto')
            else:
                source = self.config['source'] + ':' + self.config.get('kiwi_url', '')
            if self.config.get('lane_name'):
                source = self.config['lane_name'] + ' | ' + source
            self.clock.reset()
            logger.assembler.clear()
            last_sequence = None
            last_generation = self.generation
            next_health = 0
            hunt_index = 0
            empty_normal = 0
            hunt_locked = False
            self.updates.put(('health', 'Connecting to receiver…'))
            while not self.stop_event.is_set():
                now = time.monotonic()
                hz, decode, new_reason = self.desired()
                self.updates.put(('banner', self.latest_plan.get('banner', '')))
                if new_reason != reason:
                    reason = new_reason
                    self.report(reason)
                if hz != self.hz or decode != self.decode_mode:
                    close_rtty_capture()
                    if kind == 'kiwi' and not self.station.get('low',0) <= hz <= self.station.get('high',30_000_000):
                        raise ReceiverUnavailable('Selected receiver does not cover the scheduled band')
                    self.confirmed_hz = 0
                    self.hz = hz
                    self.decode_mode = decode
                    self.generation += 1
                    self.receiver.tune(hz)
                    self.report(f'Following schedule: {hz / 1e6:.6f} MHz {decode}')
                if self.receiver.error:
                    raise ReceiverUnavailable(self.receiver.error)
                if now - (self.receiver.last_audio or connected_at) > 20:
                    raise ReceiverUnavailable('No audio for 20 seconds')
                if not stable and now - connected_at > 60 and self.receiver.last_audio:
                    stable = True
                    if pool:
                        pool.stable()
                if self.audio_overflow:
                    close_rtty_capture()
                    self.audio_overflow = False
                    self.metrics['overflows'] += 1
                    self.metrics['audio_gaps'] += 1
                    self.clock.reset()
                    logger.assembler.clear()
                    converter = None
                    rtty = self._new_rtty()
                    hunt_locked = False
                    last_sequence = None
                    while not self.audio.empty():
                        try: self.audio.get_nowait()
                        except queue.Empty: break
                    self.report('Decoder fell behind; dropped oldest audio and realigned. Listening continues.')
                try:
                    samples, rate, receipt, seq, generation = self.audio.get(timeout=0.3)
                except queue.Empty:
                    samples = None
                if samples is not None and generation == self.generation:
                    self.metrics['audio_packets'] += 1
                    gap = seq is not None and last_sequence is not None and ((seq - last_sequence) & 0xffffffff) != 1
                    if gap or generation != last_generation:
                        close_rtty_capture()
                        self.metrics['audio_gaps'] += 1
                        self.report('Audio gap or frequency change: restarting decoder alignment')
                        self.clock.reset()
                        logger.assembler.clear()
                        empty_normal = 0
                        hunt_locked = False
                        converter = None
                        rtty = self._new_rtty()
                    last_sequence = seq
                    last_generation = generation
                    if converter is None or converter.rate != int(rate):
                        converter = StreamResampler(rate)
                    samples = converter.process(samples)
                    if not len(samples):
                        continue
                    self.monitor.push(samples)
                    if self.monitor.error:
                        self.report('Speaker monitor failed: ' + self.monitor.error)
                        self.monitor.error = ''
                        self.updates.put(('monitor', False))
                    self.metrics['audio_seconds'] += len(samples) / 12000
                    rms = float(np.sqrt(np.mean(samples.astype(np.float32) ** 2))) / 32768.0
                    self.metrics['level'] = min(1.0, rms * 6)
                    if self.decode_mode == 'RTTY':
                        if self.config.get('record_rtty', True):
                            if rtty_capture is None:
                                folder = Path(self.data_dir) / 'net-night'
                                folder.mkdir(parents=True, exist_ok=True)
                                lane = ''.join(c.lower() if c.isalnum() else '-' for c in self.config.get('lane_name','')).strip('-')
                                suffix = ('-' + lane) if lane else ''
                                rtty_capture_path = folder / f'rtty-{int(receipt)}-{time.time_ns()}{suffix}.wav'
                                rtty_capture = wave.open(str(rtty_capture_path), 'wb')
                                rtty_capture.setnchannels(1);rtty_capture.setsampwidth(2);rtty_capture.setframerate(12000)
                                self.report('Recording RTTY calibration audio to ' + str(rtty_capture_path))
                            rtty_capture.writeframesraw(np.ascontiguousarray(samples,dtype=np.int16).tobytes())
                        for line in rtty.feed(samples):
                            packet = {
                                'type': 'RTTY.CHUNK', 'value': line,
                                'params': {'DIAL': self.confirmed_hz if kind == 'audio' else self.hz, 'UTC': int(receipt * 1000), 'FROM': '', 'TO': ''},
                            }
                            raw_id = self.journal.ingest(packet, source, self.confirmed_hz if kind == 'audio' else self.hz)
                            if raw_id:
                                logger.assembler.store.create(raw_id, line, 'RTTY line')
                                self.metrics['rtty_lines'] += 1
                                self.last_decode = time.monotonic()
                                self.updates.put(('message', None))
                                complete = {'text': line, 'classification': classify(line)}
                                if complete['classification'] != 'Unclassified traffic':
                                    self.metrics['tagged'] += 1
                                    self.updates.put(('complete', complete))
                    else:
                        self.clock.push(samples, receipt)
                    js8_modes = list(speeds.items()) if self.decode_mode == 'JS8' else []
                    if js8_modes and not hunt_locked:
                        js8_modes = [(mode, period) for mode, period in js8_modes if mode == 0] or js8_modes
                    for mode, period in js8_modes:
                        hunts = HUNT_OFFSETS if (mode == 0 and not hunt_locked) else (HUNT_OFFSETS[hunt_index],)
                        grid_to_mark = None
                        matched = False
                        if self.clock.end_utc is None:
                            continue
                        ready_grid = round(((self.clock.end_utc - period - 3.0) // period) * period, 6)
                        for hunt in hunts:
                            cycle = self.clock.cycle_at(period, hunt, mark=False, grid=ready_grid)
                            if cycle is None:
                                continue
                            begin, chunk = cycle
                            grid_to_mark = begin - hunt
                            frames = decoder.decode(chunk, mode, utc=nutc_from_epoch(begin))
                            self.metrics['decode_cycles'] += 1
                            self.metrics['decoded_frames'] += len(frames)
                            logger.write(frames, source, self.confirmed_hz if kind == 'audio' else self.hz, begin)
                            if frames:
                                for frame in frames:
                                    tag = classify(frame.get('text', ''))
                                    if tag != 'Unclassified traffic':
                                        self.metrics['tagged'] += 1
                                    if tag == 'FLASH':
                                        self.metrics['flash'] += 1
                                if self.config.get('record_net', True) and not dumped:
                                    if any(classify(frame.get('text', '')) != 'Unclassified traffic' for frame in frames):
                                        self._dump_cycle(chunk, begin)
                                        dumped = True
                                matched = True
                                hunt_locked = True
                                hunt_index = HUNT_OFFSETS.index(hunt) if hunt in HUNT_OFFSETS else 0
                                self.metrics['clock_offset'] = hunt
                                self.last_decode = time.monotonic()
                                empty_normal = 0
                                if hunt != 0:
                                    self.report(
                                        f'JS8 decode alignment {hunt:+.0f}s (includes capture/network latency).'
                                    )
                                    self.updates.put(('clock', hunt))
                                break
                        if grid_to_mark is not None:
                            self.clock.last[period] = grid_to_mark
                        if mode == 0 and grid_to_mark is not None and not matched:
                            empty_normal += 1
                            if empty_normal >= 3:
                                hunt_locked = False
                                empty_normal = 0
                if now >= next_health:
                    next_health = now + 2
                    flowing = self.receiver.last_audio and now - self.receiver.last_audio < 8
                    status = 'Listening' if flowing else 'Waiting for receiver audio'
                    decoded = (
                        f'Last message {int(now - self.last_decode)}s ago'
                        if self.last_decode else 'Waiting for a JS8 message'
                    )
                    offset = self.metrics['clock_offset']
                    clock = f' · clock {offset:+.0f}s' if offset else ''
                    self.updates.put(('health', f'{status} · {self.hz / 1e6:.3f} MHz · {decoded}{clock}'))
                    self.updates.put(('telemetry', {
                        'connected': bool(self.receiver.last_audio),
                        'audio': bool(flowing),
                        'frames': self.metrics['decoded_frames'],
                        'level': self.metrics.get('level', 0),
                        'tagged': self.metrics.get('tagged', 0),
                    }))
                    if self.config.get('hamlib_enabled') and now >= next_hamlib:
                        next_hamlib = now + 5
                        self._hamlib_check()
        finally:
            if 'rtty_capture' in locals() and rtty_capture is not None:
                try:
                    close_rtty_capture()
                except Exception as exc:
                    self.report('RTTY calibration audio could not be finalized: ' + str(exc))
            if self.receiver:
                self.receiver.stop()

    def _dump_cycle(self, chunk, begin):
        folder = Path(self.data_dir) / 'net-night'
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f'js8-{int(begin)}.wav'
        with wave.open(str(path), 'wb') as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(12000)
            wav.writeframes(np.ascontiguousarray(chunk, dtype=np.int16).tobytes())
        self.report('Saved a GhostNet JS8 cycle to ' + str(path))

    def _hamlib_check(self):
        try:
            from hamlib_watch import compare
            wanted = self.latest_plan.get('usb_hz', self.hz)
            info = compare(
                wanted,
                self.config.get('hamlib_host') or '127.0.0.1',
                int(self.config.get('hamlib_port') or 4532),
            )
            self.confirmed_hz = int(info['actual'])
            self.updates.put(('cat', f"Radio reads {info['actual']/1e6:.6f} MHz; requested {wanted/1e6:.6f} MHz {self.latest_plan.get('sideband', 'USB')} (mode not verified)"))
            if not info['ok']:
                self.report(
                    f"Radio reads {info['actual']/1e6:.6f} MHz; schedule wants {info['expected']/1e6:.6f} MHz "
                    f"{self.latest_plan.get('sideband', 'USB')}. This app does not change the radio."
                )
        except Exception as exc:
            self.confirmed_hz = 0
            self.updates.put(('cat', 'Radio frequency unverified: ' + str(exc)))
            self.report('Hamlib frequency check failed: ' + str(exc))

    def confirm_frequency(self):
        self.confirmed_hz = self.hz
        self.generation += 1
        self.updates.put(('cat', f'Operator confirmed {self.hz/1e6:.6f} MHz USB'))

    def _new_rtty(self):
        return RttyDecoder(
            reverse=self.config.get('rtty_reverse', False),
            center_hz=float(self.config.get('rtty_center_hz') or 2210),
        )

    def set_monitor(self, on, device_name='', volume=0.3, agc=False):
        self.monitor.volume = max(0.0,min(1.0,float(volume)))
        self.monitor.agc = bool(agc)
        self.monitor.set_enabled(bool(on), device_name)
        if on:
            self.report('Speaker monitor on — you are hearing receive audio only. This does not transmit.')
        else:
            self.report('Speaker monitor off.')
        self.updates.put(('monitor', bool(on) and self.monitor.enabled.is_set()))

    def stop(self):
        self.stop_event.set()
        self.monitor.set_enabled(False)
