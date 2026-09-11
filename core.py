"""Receive-only GhostNet scheduler and durable event journal. Python 3.11+."""
from __future__ import annotations
import csv
import hashlib
import json
import math
import re
import sqlite3
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

UTC = timezone.utc
REGIONS = ('North America', 'Europe', 'Australia / Pacific')
SOURCE = 'https://github.com/s2underground/GhostNet/blob/main/GhostNet_Version_1.5.pdf'

def region_for_location(lat, lon):
    """Conservative approximate region suggestion; explicit override is authoritative."""
    lat, lon = float(lat), float(lon)
    if not math.isfinite(lat) or not math.isfinite(lon) or not -90 <= lat <= 90 or not -180 <= lon <= 180:
        raise ValueError('Latitude must be -90..90 and longitude -180..180.')
    if 7 <= lat <= 84 and -170 <= lon <= -50:
        return REGIONS[0]
    if 34 <= lat <= 72 and -25 <= lon <= 45:
        return REGIONS[1]
    if -50 <= lat <= 0 and (110 <= lon <= 180 or -180 <= lon <= -130):
        return REGIONS[2]
    raise ValueError('No published local profile mapped here. Select a region to monitor explicitly.')

@dataclass(frozen=True)
class Window:
    name: str
    regions: tuple
    weekday: int
    minute: int
    duration: int
    hz: int
    mode: str

def windows():
    result = []
    # Pages 13, 15, 17: NA Thursday local is FRIDAY UTC.
    for region, day, start in [(REGIONS[0], 4, 60), (REGIONS[1], 3, 1080), (REGIONS[2], 3, 420)]:
        for offset, mode, hz in [(0, 'JS8', 7107000), (30, 'VARA', 7107000),
                                  (60, 'RTTY', 7077000), (90, 'VOICE', 7190000)]:
            result.append(Window(f'{region} weekly {mode}', (region,), day, start+offset, 30, hz, mode))
    # Pages 14, 16, 18: Saturday UTC data bridges.
    for name, regions, start, duration, hz, mode in [
        ('NA / Australia', (REGIONS[0], REGIONS[2]), 720, 60, 14107000, 'JS8'),
        ('NA / Australia', (REGIONS[0], REGIONS[2]), 780, 30, 0, 'ALE'),
        ('NA / Australia', (REGIONS[0], REGIONS[2]), 810, 30, 3575000, 'JS8'),
        ('NA / Europe', (REGIONS[0], REGIONS[1]), 1080, 60, 14107000, 'JS8'),
        ('NA / Europe', (REGIONS[0], REGIONS[1]), 1140, 60, 0, 'ALE'),
        ('Europe / Australia', (REGIONS[1], REGIONS[2]), 1200, 60, 14107000, 'JS8'),
        ('Europe / Australia', (REGIONS[1], REGIONS[2]), 1260, 30, 0, 'ALE'),
        ('Europe / Australia', (REGIONS[1], REGIONS[2]), 1290, 30, 3575000, 'JS8'),
        ('Australia / Pacific', (REGIONS[2],), 480, 60, 14107000, 'JS8'),
        ('Australia / Pacific', (REGIONS[2],), 540, 30, 7107000, 'JS8'),
        ('Australia / Pacific', (REGIONS[2],), 570, 30, 0, 'ALE'),
    ]:
        result.append(Window(name+' bridge '+mode, regions, 5, start, duration, hz, mode))
    return result

WINDOWS = windows()

def occurrences(region, now, days=8):
    if region not in REGIONS:
        raise ValueError('Select a published region.')
    if now.tzinfo is None:
        raise ValueError('Schedule requires a timezone-aware time.')
    now = now.astimezone(UTC)
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    result = []
    for delta in range(-1, days):
        date = midnight + timedelta(days=delta)
        for window in WINDOWS:
            if region in window.regions and date.weekday() == window.weekday:
                start = date + timedelta(minutes=window.minute)
                end = start + timedelta(minutes=window.duration)
                if end > now:
                    result.append((start, end, window))
    return sorted(result, key=lambda item: item[0])

def current_window(region, now):
    for start, end, window in occurrences(region, now):
        if start <= now < end:
            return start, end, window
    return None

def listen_plan(region, now, rtty=True):
    """What to monitor right now. decode is JS8, RTTY, or NONE. Never transmits."""
    hit = current_window(region, now)
    if not hit:
        return {
            'hz': 7107000, 'mode': 'JS8', 'decode': 'JS8',
            'reason': 'Between scheduled nets; monitoring 40m JS8',
            'banner': 'Between nets · monitor 7.107 MHz USB',
            'usb_hz': 7107000, 'sideband': 'USB', 'bridge': False,
        }
    start, end, window = hit
    left = max(0, int((end - now.astimezone(UTC)).total_seconds()))
    bridge = 'bridge' in window.name.lower()
    if window.mode == 'JS8':
        banner = f"{'SWITCH BAND · ' if bridge and window.hz != 7107000 else ''}Tune USB to {window.hz/1e6:.3f} MHz"
        return {
            'hz': window.hz, 'mode': 'JS8', 'decode': 'JS8', 'reason': window.name,
            'banner': banner, 'usb_hz': window.hz, 'sideband': 'USB', 'bridge': bridge,
            'window': window, 'end': end, 'left': left,
        }
    if window.mode == 'VARA':
        return {
            'hz': 7107000, 'mode': 'VARA', 'decode': 'JS8',
            'reason': 'VARA window not decoded; monitoring 40m JS8 at 7.107 MHz',
            'banner': 'VARA window · not decoded · stay on 7.107 MHz USB JS8',
            'usb_hz': 7107000, 'sideband': 'USB', 'bridge': False,
            'window': window, 'end': end, 'left': left,
        }
    if window.mode == 'RTTY':
        if rtty:
            return {
                'hz': 7077000, 'mode': 'RTTY', 'decode': 'RTTY',
                'reason': window.name,
                'banner': 'Tune USB to 7.077 MHz · RTTY 45.45 baud (preview)',
                'usb_hz': 7077000, 'sideband': 'USB', 'bridge': False,
                'window': window, 'end': end, 'left': left,
            }
        return {
            'hz': 7107000, 'mode': 'RTTY', 'decode': 'JS8',
            'reason': 'RTTY window; decoder off — monitoring 40m JS8',
            'banner': 'RTTY window · decoder off · 7.107 MHz USB',
            'usb_hz': 7107000, 'sideband': 'USB', 'bridge': False,
            'window': window, 'end': end, 'left': left,
        }
    if window.mode == 'VOICE':
        return {
            'hz': 7107000, 'mode': 'VOICE', 'decode': 'JS8',
            'reason': 'VOICE window: 7.190 MHz LSB — not decoded. Online stays on 7.107 JS8.',
            'banner': 'VOICE · tune 7.190 MHz LSB · not decoded',
            'usb_hz': 7190000, 'sideband': 'LSB', 'bridge': False,
            'window': window, 'end': end, 'left': left,
        }
    if window.mode == 'ALE':
        return {
            'hz': 7107000, 'mode': 'ALE', 'decode': 'JS8',
            'reason': 'ALE window not decoded; monitoring 40m JS8',
            'banner': 'ALE window · not decoded · stay on 7.107 MHz USB',
            'usb_hz': 7107000, 'sideband': 'USB', 'bridge': False,
            'window': window, 'end': end, 'left': left,
        }
    return {
        'hz': window.hz or 7107000, 'mode': window.mode, 'decode': 'JS8',
        'reason': window.name, 'banner': window.name,
        'usb_hz': window.hz or 7107000, 'sideband': 'USB', 'bridge': bridge,
        'window': window, 'end': end, 'left': left,
    }

def target(region, now, rtty=False):
    plan = listen_plan(region, now, rtty=rtty)
    return plan['hz'], plan['mode'] if plan['decode'] != 'JS8' and plan['mode'] in ('RTTY',) else plan['decode'], plan['reason']

def classify(text, destination=''):
    value = (destination+' '+text).upper()
    if re.search(r'@GSTFLASH\b', value):
        return 'FLASH'
    if re.search(r'@GHOSTNET\b|@GN[A-Z]{3}(?:[A-Z]{2})?\b', value):
        return 'GhostNet tagged'
    return 'Unclassified traffic'

class Journal:
    """Raw decode frames and assembled directed messages remain separate records."""
    def __init__(self, path):
        self.lock = threading.RLock()
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.execute('PRAGMA wal_autocheckpoint=1000')
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS messages (
              id INTEGER PRIMARY KEY, received_utc TEXT NOT NULL, event_utc TEXT,
              source TEXT, frequency INTEGER, mode TEXT, kind TEXT, sender TEXT,
              destination TEXT, snr REAL, classification TEXT, text TEXT,
              raw_json TEXT NOT NULL, fingerprint TEXT UNIQUE NOT NULL);
            CREATE INDEX IF NOT EXISTS messages_received ON messages(received_utc);
            CREATE TABLE IF NOT EXISTS events (
              id INTEGER PRIMARY KEY, utc TEXT, detail TEXT);
        ''')
        self.db.commit()

    def event(self, detail):
        with self.lock, self.db:
            self.db.execute('INSERT INTO events(utc,detail) VALUES (?,?)',
                            (datetime.now(UTC).isoformat(), detail))
            count = self.db.execute('SELECT COUNT(*) FROM events').fetchone()[0]
            if count > 20000:
                self.db.execute('DELETE FROM events WHERE id IN (SELECT id FROM events ORDER BY id LIMIT ?)', (count // 2,))
        # SQLite's auto-checkpoint runs after commits; never checkpoint a live write transaction.

    def ingest(self, packet, source, tuned_hz=0):
        if not isinstance(packet, dict) or packet.get('type') not in ('RX.ACTIVITY', 'RX.DIRECTED', 'RX.ASSEMBLED', 'RTTY.CHUNK'):
            return False
        p = packet.get('params', {})
        if not isinstance(p, dict):
            raise ValueError('Invalid decoder parameters')
        body = packet.get('value') or p.get('TEXT', '')
        if not isinstance(body, str) or not body:
            return False
        raw = json.dumps(packet, ensure_ascii=False, sort_keys=True)
        timestamp = p.get('UTC')
        event_utc = None
        if timestamp is not None:
            event_utc = datetime.fromtimestamp(float(timestamp)/1000, UTC).isoformat()
        # No decoder timestamp means no safe duplicate suppression: preserve receipt.
        receipt = datetime.now(UTC).isoformat()
        key = source+'\0'+raw+('' if event_utc else uuid.uuid4().hex)
        fingerprint = hashlib.sha256(key.encode()).hexdigest()
        hz = int(p.get('DIAL', tuned_hz) or 0)
        snr = float(p['SNR']) if p.get('SNR') is not None else None
        if snr is not None and not math.isfinite(snr):
            raise ValueError('Invalid SNR')
        sender, dest = str(p.get('FROM', '')), str(p.get('TO', ''))
        mode = 'RTTY' if packet['type'] == 'RTTY.CHUNK' else 'JS8'
        with self.lock, self.db:
            cur = self.db.execute('''INSERT OR IGNORE INTO messages
              (received_utc,event_utc,source,frequency,mode,kind,sender,destination,snr,
               classification,text,raw_json,fingerprint) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)''',
              (receipt,event_utc,source,hz,mode,packet['type'],sender,dest,snr,
               classify(body,dest),body,raw,fingerprint))
            if cur.rowcount != 1:
                return False
            return cur.lastrowid

    def rows(self, query='', tagged=False, limit=500):
        with self.lock:
            sql = 'SELECT * FROM messages WHERE (instr(lower(text),lower(?))>0 OR instr(lower(sender),lower(?))>0)'
            if tagged:
                sql += " AND classification != 'Unclassified traffic'"
            sql += ' ORDER BY id DESC'
            args = [query, query]
            if limit is not None:
                sql += ' LIMIT ?'
                args.append(limit)
            return [dict(row) for row in self.db.execute(sql, args)]

    def export(self, path):
        fields = ['id','received_utc','event_utc','source','frequency','mode','kind',
                  'sender','destination','snr','classification','text','raw_json']
        with self.lock, open(path, 'w', newline='', encoding='utf-8-sig') as stream:
            writer = csv.DictWriter(stream, fieldnames=fields, extrasaction='ignore')
            writer.writeheader()
            for row in self.db.execute('SELECT * FROM messages ORDER BY id'):
                values = dict(row)
                # Radio text is untrusted; prevent spreadsheet formula execution.
                for key, value in values.items():
                    if isinstance(value, str) and value.lstrip().startswith(('=', '+', '-', '@')):
                        values[key] = "'" + value
                writer.writerow(values)

    def close(self):
        with self.lock:
            self.db.close()
