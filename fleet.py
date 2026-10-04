"""Concurrent receive-only regional sessions sharing one journal."""
from copy import deepcopy
import threading

from core import REGIONS
from native_session import NativeSession


class _LaneUpdates:
    def __init__(self, destination, region):
        self.destination = destination
        self.region = region

    def put(self, item):
        kind, value = item
        self.destination.put(('lane', (self.region, kind, value)))


class _FleetThread:
    def __init__(self, fleet):
        self.fleet = fleet

    def is_alive(self):
        return any(session.thread and session.thread.is_alive()
                   for session in self.fleet.sessions.values())


class ReceiverFleet:
    """One independent KiwiSDR/decoder lane for each published region."""
    def __init__(self, config, journal, data_dir, updates, session_factory=NativeSession):
        self.config = config
        self.journal = journal
        self.data_dir = data_dir
        self.updates = updates
        self.sessions = {}
        self.listening_region = None
        for region in REGIONS:
            lane = deepcopy(config)
            lane['region'] = region
            lane['kiwi_url'] = ''
            lane['automatic_receiver'] = True
            lane['lane_name'] = region
            lane['record_net'] = True
            self.sessions[region] = session_factory(
                lane, journal, data_dir, _LaneUpdates(updates, region))
        self.thread = _FleetThread(self)

    @property
    def error(self):
        return '; '.join(f'{region}: {s.error}' for region, s in self.sessions.items() if s.error)

    @property
    def metrics(self):
        numeric = ('connections', 'recoveries', 'audio_packets', 'decode_cycles',
                   'decoded_frames', 'audio_gaps', 'overflows', 'audio_seconds',
                   'rtty_lines', 'tagged', 'flash')
        result={key: sum(float(s.metrics.get(key, 0)) for s in self.sessions.values())
                for key in numeric}
        result['start_message_id']=min(int(s.metrics.get('start_message_id',0)) for s in self.sessions.values())
        with self.journal.lock:
            result['end_message_id']=self.journal.db.execute('SELECT COALESCE(MAX(id),0) FROM messages').fetchone()[0]
        result['receivers']=[receiver for s in self.sessions.values() for receiver in s.metrics.get('receivers',[])]
        result['regions']=list(self.sessions)
        return result

    def start(self):
        for session in self.sessions.values():
            session.start()

    def set_monitor(self, on, device_name='', volume=0.3, agc=False, region=None):
        for session in self.sessions.values():
            session.set_monitor(False)
        if on:
            if not region or region not in self.sessions:
                raise ValueError('Choose one regional feed to hear.')
            self.sessions[region].set_monitor(True, device_name, volume, agc)
        self.listening_region = region if on else None

    def stop(self):
        for session in self.sessions.values():
            session.stop()
