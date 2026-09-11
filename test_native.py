"""Tests for the 0.3G native receiver path. Does not transmit."""
import json
import queue
import subprocess
import sys
import tempfile
import time
import unittest
import wave
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from alerts import quiet_now, should_alert
from conversations import Assembler
from core import Journal, REGIONS
from local_update import version_tuple
from native_session import (
    AudioClock, NativeSession, downsample_48k_to_12k, enabled_modes, nutc_from_epoch, to_int16_12k,
)
from receivers import SOURCE_AUDIO, SOURCE_KIWI, SOURCE_SOAPY, USBReceiver, list_input_devices, source_kind
from recovery import ReceiverPool, ReceiverUnavailable
from storage import VERSION

ROOT = Path(__file__).resolve().parent
UTC = timezone.utc


class HelperTests(unittest.TestCase):
    def test_version_and_speeds(self):
        self.assertEqual(VERSION, '0.4.0')
        self.assertEqual(version_tuple('0.3G'), (0, 3, 0))
        self.assertEqual(version_tuple('0.3.1'), (0, 3, 1))
        self.assertEqual(version_tuple('1.2.3.4'), (1, 2, 3))
        self.assertLess(version_tuple('0.3G'), version_tuple('0.4.0'))
        self.assertEqual(set(enabled_modes({'js8_speeds': 'Normal only'})), {0})
        self.assertEqual(set(enabled_modes({})), {0, 1})
        self.assertEqual(nutc_from_epoch(datetime(2026, 9, 11, 1, 7, 15, tzinfo=UTC).timestamp()), 10715)

    def test_downsample_48k(self):
        samples = np.arange(16, dtype=np.int16)
        out = downsample_48k_to_12k(samples)
        self.assertEqual(len(out), 4)
        self.assertEqual(int(out[0]), 1)

    def test_audio_clock_utc_slice(self):
        clock = AudioClock(latency=0, gain=0)
        for second in range(15):
            clock.push(np.full(12000, second + 1, dtype=np.int16), float(second + 1))
        cycle = clock.latest_cycle(15, hunt=0)
        self.assertIsNotNone(cycle)
        begin, chunk = cycle
        self.assertEqual(begin, 0)
        self.assertEqual(len(chunk), 180000)
        self.assertEqual(int(chunk[0]), 1)
        self.assertEqual(int(chunk[-1]), 15)
        self.assertIsNone(clock.latest_cycle(15, hunt=0))

    def test_audio_clock_hunt_recovers_three_second_skew(self):
        clock = AudioClock(latency=0, gain=0)
        skew = 3.0
        for second in range(15):
            clock.push(np.ones(12000, dtype=np.int16), skew + second + 1)
        self.assertIsNone(clock.latest_cycle(15, hunt=0))
        cycle = clock.latest_cycle(15, hunt=skew)
        self.assertIsNotNone(cycle)
        self.assertAlmostEqual(cycle[0], skew)
        self.assertEqual(len(cycle[1]), 180000)


class PoolTests(unittest.TestCase):
    def test_manual_url_and_empty_url(self):
        pool = ReceiverPool({'automatic_receiver': False, 'kiwi_url': 'http://example.com:8073'})
        self.assertEqual(pool.next()['url'], 'http://example.com:8073')
        empty = ReceiverPool({'automatic_receiver': False, 'kiwi_url': '  '})
        with self.assertRaises(ReceiverUnavailable):
            empty.next()

    def test_rotates_discovered_stations(self):
        stations = [{'url': 'http://a:8073', 'name': 'A'}, {'url': 'http://b:8073', 'name': 'B'}]
        pool = ReceiverPool(
            {'automatic_receiver': True, 'region': REGIONS[0]},
            discover_fn=lambda region, location=None, hz=7107000: list(stations),
        )
        first = pool.next()['url']
        second = pool.next()['url']
        self.assertNotEqual(first, second)
        third = pool.next()['url']
        self.assertEqual(third, first)


class AlertTests(unittest.TestCase):
    def test_quiet_hours_and_flash(self):
        night = datetime(2026, 9, 11, 23, 0)
        day = datetime(2026, 9, 11, 12, 0)
        config = {'alerts': True, 'quiet_enabled': True, 'quiet_start': '22', 'quiet_end': '7', 'flash_override': True}
        tagged = {'text': '@GHOSTNET hello', 'classification': 'GhostNet tagged'}
        flash = {'text': '@GSTFLASH go', 'classification': 'FLASH'}
        self.assertTrue(quiet_now(config, night))
        self.assertFalse(quiet_now(config, day))
        self.assertFalse(should_alert(tagged, config, night))
        self.assertTrue(should_alert(flash, config, night))
        self.assertTrue(should_alert(tagged, config, day))
        self.assertFalse(should_alert({'text': 'CQ', 'classification': 'Unclassified traffic'}, config, day))


class AssemblerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.journal = Journal(Path(self.temp.name) / 'messages.sqlite3')
        self.calls = []

        def validate(command, body):
            self.calls.append((command, body))
            if body.endswith(' BAD'):
                return {'valid': False, 'checksum_bits': 16, 'text': body}
            return {'valid': True, 'checksum_bits': 16, 'text': body.replace(' ABCD', '')}

        self.assembler = Assembler(self.journal, validate)

    def tearDown(self):
        self.journal.close()
        self.temp.cleanup()

    def ingest(self, text, bits, frame_type, epoch, sender='K1AAA', dest='@GHOSTNET', offset=1500):
        packet = {
            'type': 'RX.ACTIVITY', 'value': text,
            'params': {'UTC': int(epoch * 1000), 'DIAL': 7107000, 'FROM': sender, 'TO': dest, 'SNR': -10},
        }
        raw_id = self.journal.ingest(packet, 'test', 7107000)
        frame = {
            'text': text, 'mode': 0, 'bits': bits, 'frame_type': frame_type, 'offset': offset,
            'snr': -10, 'dt': 0.1, 'frame': text[:12], 'low_confidence': False,
            'compound': '', 'directed': [sender, dest, 'MSG'],
        }
        return self.assembler.add(frame, raw_id, 'test', 7107000, epoch)

    def test_single_complete_frame(self):
        result = self.ingest('K1AAA: @GHOSTNET hi ', bits=3, frame_type=0, epoch=1000)
        self.assertIsNotNone(result)
        self.assertEqual(result['classification'], 'GhostNet tagged')
        rows = self.assembler.store.rows()
        self.assertEqual(rows[0]['state'], 'Complete frame')

    def test_multi_frame_checksum(self):
        first = self.ingest('K1AAA: @GHOSTNET MSG hello ', bits=1, frame_type=0, epoch=1000)
        self.assertIsNone(first)
        complete = self.ingest('world ABCD', bits=2, frame_type=4, epoch=1015, sender='K1AAA')
        self.assertIsNotNone(complete)
        self.assertEqual(complete['text'], 'K1AAA: @GHOSTNET MSG hello world')
        self.assertEqual(self.assembler.store.rows()[0]['state'], 'Checksum verified')

    def test_checksum_failed_stays_incomplete(self):
        self.ingest('K1AAA: @GHOSTNET MSG hello ', bits=1, frame_type=0, epoch=1000)
        result = self.ingest('world BAD', bits=2, frame_type=4, epoch=1015)
        self.assertIsNone(result)
        self.assertEqual(self.assembler.store.rows()[0]['state'], 'Checksum failed')

    def test_missing_middle_does_not_glue_new_header(self):
        self.ingest('K1AAA: @GHOSTNET MSG hello ', bits=1, frame_type=0, epoch=1000)
        later = self.ingest('K2BBB: @GHOSTNET other ', bits=1, frame_type=0, epoch=1060, sender='K2BBB', offset=1800)
        self.assertIsNone(later)
        rows = self.assembler.store.rows()
        self.assertEqual(len(rows), 2)
        states = {row['sender']: row['state'] for row in rows}
        self.assertEqual(states['K1AAA'], 'Incomplete')
        self.assertEqual(states['K2BBB'], 'Incomplete')


class NativePipelineTests(unittest.TestCase):
    def test_recorded_wav_through_session(self):
        wav_path = ROOT / 'fixtures' / 'A_1_4.wav'
        with wave.open(str(wav_path)) as wav:
            signal = np.frombuffer(wav.readframes(wav.getnframes()), dtype='<i2')
        period = 15
        needed = period * 12000
        if len(signal) < needed:
            signal = np.concatenate([signal, np.zeros(needed - len(signal), dtype=np.int16)])
        else:
            signal = signal[:needed]
        base = 1_700_000_010
        self.assertEqual(base % period, 0)

        class Recorded:
            def __init__(self, config, report, sink):
                self.sink = sink
                self.error = ''
                self.last_audio = time.monotonic()

            def start(self, hz):
                audio = np.concatenate([signal, np.zeros(5 * 12000, dtype=np.int16)])
                for index in range(0, len(audio), 12000):
                    chunk = audio[index:index + 12000]
                    self.sink(chunk, 12000, base + (index + len(chunk)) / 12000, index // 12000)
                    self.last_audio = time.monotonic()

            def stop(self):
                pass

            def tune(self, hz):
                pass

        with tempfile.TemporaryDirectory() as folder:
            journal = Journal(Path(folder) / 'messages.sqlite3')
            updates = queue.Queue()
            session = NativeSession(
                {
                    'source': 'KiwiSDR online', 'region': REGIONS[0], 'tuning': 'Hold 40m JS8',
                    'automatic_receiver': False, 'kiwi_url': 'http://recorded.test:8073',
                    'js8_speeds': 'Normal only',
                },
                journal, folder, updates,
            )
            session.clock.latency = 0
            session.clock.gain = 0
            session.receiver_factory = Recorded
            session.start()
            deadline = time.monotonic() + 40
            while time.monotonic() < deadline and not session.error:
                if journal.rows():
                    break
                time.sleep(0.05)
            session.stop()
            session.thread.join(15)
            rows = journal.rows()
            texts = [row['text'] for row in rows]
            journal.close()
            self.assertFalse(session.error, session.error)
            self.assertGreaterEqual(len(rows), 4, texts)
            self.assertTrue(any('HEARTBEAT' in text for text in texts))


class HardwareTests(unittest.TestCase):
    def test_source_kind_and_devices(self):
        self.assertEqual(source_kind({'source': SOURCE_KIWI}), 'kiwi')
        self.assertEqual(source_kind({'source': SOURCE_AUDIO}), 'audio')
        self.assertEqual(source_kind({'source': SOURCE_SOAPY}), 'soapy')
        self.assertEqual(source_kind({'source': 'USB / SoapySDR'}), 'soapy')
        names = list_input_devices()
        self.assertIsInstance(names, list)
        self.assertEqual(len(names), len(set(names)))

    def test_to_12k_from_48k_and_44100(self):
        forty_eight = np.ones(48, dtype=np.float32) * 0.5
        out = to_int16_12k(forty_eight, 48000)
        self.assertEqual(len(out), 12)
        sine = np.sin(np.arange(4410) * 2 * np.pi * 1000 / 44100).astype(np.float32)
        resampled = to_int16_12k(sine, 44100)
        self.assertGreater(len(resampled), 1000)
        self.assertLess(len(resampled), 1400)

    def test_streaming_resampler_has_no_packet_drift(self):
        from audio_stream import StreamResampler
        for rate in (44100,48000):
            converter=StreamResampler(rate)
            total=0
            for _ in range(100):
                total += len(converter.process(np.zeros(2048,dtype=np.float32)))
            expected=(100*2048*12000+rate-1)//rate
            self.assertEqual(total,expected)

    def test_soapy_missing_is_a_clear_error(self):
        reports = []
        receiver = USBReceiver({'usb_args': '', 'gain': '30', 'audio_device': ''}, reports.append, lambda *args: None)
        receiver.start(7107000)
        receiver.thread.join(8)
        self.assertIn('SoapySDR', receiver.error)

    def test_usb_audio_session_uses_audio_factory(self):
        wav_path = ROOT / 'fixtures' / 'A_1_4.wav'
        with wave.open(str(wav_path)) as wav:
            signal = np.frombuffer(wav.readframes(wav.getnframes()), dtype='<i2')
        needed = 15 * 12000
        if len(signal) < needed:
            signal = np.concatenate([signal, np.zeros(needed - len(signal), dtype=np.int16)])
        else:
            signal = signal[:needed]
        base = 1_700_000_010

        class Recorded:
            def __init__(self, config, report, sink):
                self.sink = sink
                self.error = ''
                self.last_audio = time.monotonic()

            def start(self, hz):
                audio = np.concatenate([signal, np.zeros(5 * 12000, dtype=np.int16)])
                for index in range(0, len(audio), 12000):
                    chunk = audio[index:index + 12000]
                    self.sink(chunk, 12000, base + (index + len(chunk)) / 12000, index // 12000)
                    self.last_audio = time.monotonic()

            def stop(self):
                pass

            def tune(self, hz):
                pass

        with tempfile.TemporaryDirectory() as folder:
            journal = Journal(Path(folder) / 'messages.sqlite3')
            session = NativeSession(
                {
                    'source': SOURCE_AUDIO, 'region': REGIONS[0], 'tuning': 'Hold 40m JS8',
                    'audio_device': 'loopback-test', 'js8_speeds': 'Normal only',
                },
                journal, folder, queue.Queue(),
            )
            session.clock.latency = 0
            session.clock.gain = 0
            session.audio_receiver_factory = Recorded
            session.start()
            deadline = time.monotonic() + 40
            while time.monotonic() < deadline and not session.error:
                if journal.rows():
                    break
                time.sleep(0.05)
            session.stop()
            session.thread.join(15)
            rows = journal.rows()
            journal.close()
            self.assertFalse(session.error, session.error)
            self.assertGreaterEqual(len(rows), 4)


class GuiSmokeTests(unittest.TestCase):
    def _run_gui(self, assertions):
        code = """import tempfile
from app import App
with tempfile.TemporaryDirectory() as folder:
    ui=App(folder)
    try:
        ui.update()
        %s
    finally:
        ui.journal.close(); ui.destroy()
""" % assertions
        result=subprocess.run([sys.executable,'-c',code],cwd=ROOT,text=True,capture_output=True,timeout=30)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    def test_app_builds_preferences_and_countdown(self):
        self._run_gui("assert hasattr(ui,'build_preferences'); assert ui.preferences.winfo_exists(); ui.update_countdown(); assert ui.countdown.get(); assert len(ui.region_trees)==3")

    def test_inbox_defaults_to_tagged_and_has_banner(self):
        self._run_gui("assert ui.tagged.get(); assert ui.vars['alerts'].get(); assert ui.vars['flash_override'].get(); assert ui.banner.get(); ui.draw_meter(0.4)")


class MonitorTests(unittest.TestCase):
    def test_upsample_and_disabled_drop(self):
        from monitor import AudioMonitor, upsample_12k_to_48k
        out = upsample_12k_to_48k(np.ones(100, dtype=np.int16), volume=1.0)
        self.assertEqual(out.shape, (400, 1))
        monitor = AudioMonitor()
        monitor.push(np.ones(1200, dtype=np.int16))
        self.assertTrue(monitor.queue.empty())
        monitor.enabled.set()
        monitor.push(np.ones(1200, dtype=np.int16))
        self.assertFalse(monitor.queue.empty())
        monitor.set_enabled(False)


class ReviewFixTests(unittest.TestCase):
    def test_validate_export_exists(self):
        from embedded import EmbeddedDecoder
        decoder = EmbeddedDecoder()
        result = decoder.validate_message(' MSG', 'hello ABC')
        self.assertIn('valid', result)

    def test_event_checkpoint_survives_200(self):
        with tempfile.TemporaryDirectory() as folder:
            journal = Journal(Path(folder) / 'messages.sqlite3')
            for i in range(250):
                journal.event('e%d' % i)
            count = journal.db.execute('SELECT COUNT(*) FROM events').fetchone()[0]
            journal.close()
            self.assertEqual(count, 250)

    def test_report_serializes_active_plan(self):
        from core import listen_plan
        from reports import heard_report
        with tempfile.TemporaryDirectory() as folder:
            journal = Journal(Path(folder) / 'messages.sqlite3')
            plan = listen_plan(REGIONS[0], datetime(2026, 9, 11, 1, 10, tzinfo=UTC))
            path = Path(folder) / 'report.json'
            report = heard_report(journal, {'start_message_id': 0, 'end_message_id': 0, 'audio_seconds': 1}, path, plan)
            self.assertFalse(report['heard'])
            json.loads(path.read_text(encoding='utf-8'))
            journal.close()


class ProductTests(unittest.TestCase):
    def test_listen_plan_follows_the_hour(self):
        from core import listen_plan
        js8 = listen_plan(REGIONS[0], datetime(2026, 9, 11, 1, 10, tzinfo=UTC))
        self.assertEqual(js8['decode'], 'JS8')
        self.assertEqual(js8['hz'], 7107000)
        vara = listen_plan(REGIONS[0], datetime(2026, 9, 11, 1, 40, tzinfo=UTC))
        self.assertEqual(vara['mode'], 'VARA')
        self.assertEqual(vara['hz'], 7107000)
        self.assertEqual(vara['decode'], 'JS8')
        rtty = listen_plan(REGIONS[0], datetime(2026, 9, 11, 2, 10, tzinfo=UTC), rtty=True)
        self.assertEqual(rtty['decode'], 'RTTY')
        self.assertEqual(rtty['hz'], 7077000)
        voice = listen_plan(REGIONS[0], datetime(2026, 9, 11, 2, 40, tzinfo=UTC))
        self.assertEqual(voice['mode'], 'VOICE')
        self.assertEqual(voice['usb_hz'], 7190000)
        self.assertEqual(voice['sideband'], 'LSB')
        self.assertEqual(voice['hz'], 7107000)
        bridge = listen_plan(REGIONS[0], datetime(2026, 9, 12, 12, 10, tzinfo=UTC))
        self.assertEqual(bridge['hz'], 14107000)
        self.assertTrue(bridge['bridge'])

    def test_rtty_roundtrip(self):
        from rtty import RttyDecoder, synthesize
        audio = synthesize('GHOSTNET\r')
        lines = RttyDecoder().feed(audio)
        joined = ' '.join(lines).replace(' ', '')
        self.assertIn('GHOSTNET', joined.replace('\n', ''))

    def test_rtty_survives_packet_boundaries_and_figures(self):
        from rtty import RttyDecoder, synthesize
        audio=synthesize('GHOST 123\r')
        decoder=RttyDecoder();lines=[]
        for offset in range(0,len(audio),511):
            lines.extend(decoder.feed(audio[offset:offset+511]))
        self.assertIn('GHOST123',''.join(lines).replace(' ',''))

    def test_regional_fleet_builds_three_receive_lanes(self):
        from fleet import ReceiverFleet
        class FakeSession:
            def __init__(self,config,journal,data_dir,updates):
                self.config=config;self.metrics={};self.error='';self.thread=None
            def start(self):pass
            def stop(self):pass
        with tempfile.TemporaryDirectory() as folder:
            journal=Journal(Path(folder)/'messages.sqlite3')
            fleet=ReceiverFleet({'source':SOURCE_KIWI,'region':REGIONS[0]},journal,folder,queue.Queue(),FakeSession)
            self.assertEqual(set(fleet.sessions),set(REGIONS))
            self.assertTrue(all(s.config['automatic_receiver'] for s in fleet.sessions.values()))
            self.assertTrue(all(s.config['lane_name']==r for r,s in fleet.sessions.items()))
            journal.close()

    def test_ghostnet_export_and_report(self):
        from reports import export_ghostnet, heard_report
        from conversations import Conversations
        with tempfile.TemporaryDirectory() as folder:
            journal = Journal(Path(folder) / 'messages.sqlite3')
            store = Conversations(journal)
            packet = {
                'type': 'RX.ACTIVITY', 'value': 'K1AAA: @GHOSTNET hello',
                'params': {'UTC': 1700000000000, 'DIAL': 7107000, 'FROM': 'K1AAA', 'TO': '@GHOSTNET', 'SNR': -12},
            }
            raw_id = journal.ingest(packet, 'test', 7107000)
            store.create(raw_id, 'K1AAA: @GHOSTNET hello', 'Complete frame', '@GHOSTNET')
            csv_path = Path(folder) / 'tagged.csv'
            export_ghostnet(journal, csv_path)
            text = csv_path.read_text(encoding='utf-8-sig')
            self.assertIn('@GHOSTNET', text)
            report = heard_report(journal, {'start_message_id': 0, 'end_message_id': raw_id, 'audio_seconds': 90, 'decoded_frames': 1, 'receivers': ['kiwi']}, Path(folder) / 'report.json')
            self.assertTrue(report['heard'])
            self.assertEqual(report['tagged_messages'], 1)
            journal.close()

    def test_hamlib_readonly_parses_frequency(self):
        from hamlib_watch import read_frequency
        class Fake:
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
            def sendall(self, data):
                self.sent = data
                self.assertNotIn(b'T', data)
                self.assertNotIn(b'PTT', data.upper())
            def makefile(self, mode):
                class Reply:
                    def readline(self, n=None):
                        return b'7107000\n'
                return Reply()
            def assertNotIn(self, item, data):
                if item in data:
                    raise AssertionError('transmit command')
        import hamlib_watch
        original = hamlib_watch.socket.create_connection
        hamlib_watch.socket.create_connection = lambda *args, **kwargs: Fake()
        try:
            self.assertEqual(read_frequency(), 7107000)
        finally:
            hamlib_watch.socket.create_connection = original


if __name__ == '__main__':
    unittest.main()
