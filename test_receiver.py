import csv
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import queue
import socket
import tempfile
import time
import unittest
from unittest.mock import patch
from core import UTC, Journal, REGIONS, classify, occurrences, region_for_location, target

class ScheduleTests(unittest.TestCase):
    def test_north_america_is_friday_utc(self):
        local = datetime(2026,9,10,20,5,tzinfo=timezone(timedelta(hours=-5)))
        hz, mode, reason = target(REGIONS[0],local)
        self.assertEqual((hz,mode),(7107000,'JS8'))
        self.assertIn('weekly',reason)
        self.assertNotIn('weekly',target(REGIONS[0],local-timedelta(days=1))[2])

    def test_exclusive_boundaries(self):
        self.assertIn('weekly JS8',target(REGIONS[0],datetime(2026,9,11,1,29,59,tzinfo=UTC))[2])
        self.assertIn('VARA window not decoded',target(REGIONS[0],datetime(2026,9,11,1,30,tzinfo=UTC))[2])
        self.assertEqual(target(REGIONS[0],datetime(2026,9,11,2,tzinfo=UTC),True)[:2],(7077000,'RTTY'))
        self.assertEqual(target(REGIONS[0],datetime(2026,9,11,2,tzinfo=UTC),False)[:2],(7107000,'JS8'))
        self.assertIn('VOICE',target(REGIONS[0],datetime(2026,9,11,2,30,tzinfo=UTC),True)[2])

    def test_bridges(self):
        self.assertEqual(target(REGIONS[0],datetime(2026,9,12,12,tzinfo=UTC))[0],14107000)
        self.assertEqual(target(REGIONS[0],datetime(2026,9,12,13,30,tzinfo=UTC))[0],3575000)
        self.assertEqual(target(REGIONS[1],datetime(2026,9,12,12,tzinfo=UTC))[0],7107000)
        self.assertEqual(target(REGIONS[2],datetime(2026,9,12,8,tzinfo=UTC))[0],14107000)

    def test_regions_and_validation(self):
        self.assertEqual(region_for_location(40,-100),REGIONS[0])
        self.assertEqual(region_for_location(50,10),REGIONS[1])
        self.assertEqual(region_for_location(-34,151),REGIONS[2])
        for lat,lon in [(float('nan'),0),(0,181),(-20,-60)]:
            with self.assertRaises(ValueError):
                region_for_location(lat,lon)
        with self.assertRaises(ValueError):
            occurrences(REGIONS[0],datetime.now())

class JournalTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.path=Path(self.temp.name)/'journal.sqlite3'
        self.journal=Journal(self.path)

    def tearDown(self):
        self.journal.close()
        self.temp.cleanup()

    def packet(self,utc=1700000000000):
        return {'type':'RX.DIRECTED','value':'TEST: @GHOSTNET TEST MESSAGE',
                'params':{'UTC':utc,'DIAL':7107000,'SNR':-18,'FROM':'TEST','TO':'@GHOSTNET'}}

    def test_durable_and_retransmission(self):
        packet=self.packet()
        self.assertTrue(self.journal.ingest(packet,'test fixture'))
        self.assertFalse(self.journal.ingest(packet,'test fixture'))
        self.assertTrue(self.journal.ingest(self.packet(1700000001000),'test fixture'))
        self.journal.close()
        self.journal=Journal(self.path)
        self.assertEqual(len(self.journal.rows()),2)
        self.assertEqual(self.journal.rows()[0]['classification'],'GhostNet tagged')
        self.assertEqual(self.journal.rows()[0]['frequency'],7107000)

    def test_no_timestamp_never_drops_repeated_text(self):
        packet=self.packet()
        packet['params'].pop('UTC')
        self.assertTrue(self.journal.ingest(packet,'test'))
        self.assertTrue(self.journal.ingest(packet,'test'))

    def test_frame_and_assembled_are_distinct(self):
        packet=self.packet()
        self.journal.ingest(packet,'test')
        packet['type']='RX.ACTIVITY'
        self.journal.ingest(packet,'test')
        self.assertEqual(len(self.journal.rows()),2)

    def test_untrusted_csv_and_search(self):
        packet=self.packet()
        packet['value']='=HYPERLINK("bad")'
        self.journal.ingest(packet,'test')
        path=Path(self.temp.name)/'export.csv'
        self.journal.export(path)
        with path.open(encoding='utf-8-sig',newline='') as f:
            row=next(csv.DictReader(f))
        self.assertTrue(row['text'].startswith("'="))
        self.assertEqual(len(self.journal.rows('hyperlink')),1)
        self.assertEqual(len(self.journal.rows("' OR 1=1--")),0)

    def test_classification(self):
        self.assertEqual(classify('CQ TEST'),'Unclassified traffic')
        self.assertEqual(classify('@GNUSASC hello'),'GhostNet tagged')
        self.assertEqual(classify('@GSTFLASH test'),'FLASH')
        self.assertEqual(classify('@GHOSTNETFAKE'),'Unclassified traffic')

class DSPTests(unittest.TestCase):
    def test_usb_rejects_lower_sideband_and_preserves_chunk_state(self):
        import numpy as np
        from receivers import USBDemodulator
        n=np.arange(153600)
        iq=(.2*np.exp(2j*np.pi*13000*n/1536000)+.2*np.exp(2j*np.pi*10000*n/1536000)).astype(np.complex64)
        demod=USBDemodulator()
        output=np.concatenate([demod.process(iq[i:i+10001]) for i in range(0,len(iq),10001)])
        self.assertEqual(len(output),4800)
        samples=output[1000:]
        t=np.arange(len(samples))/48000
        upper=abs(np.sum(samples*np.exp(-2j*np.pi*1000*t)))
        lower=abs(np.sum(samples*np.exp(-2j*np.pi*2000*t)))
        self.assertGreater(upper/max(lower,1e-10),40)
        self.assertTrue(np.isfinite(output).all())

    def test_usb_demod_other_iq_rate(self):
        import numpy as np
        from receivers import USBDemodulator
        rate=960000
        demod=USBDemodulator(rate)
        n=np.arange(rate//10)
        iq=(.2*np.exp(2j*np.pi*13000*n/rate)).astype(np.complex64)
        out=demod.process(iq)
        self.assertEqual(len(out),4800)
        self.assertTrue(np.isfinite(out).all())

class DirectoryTests(unittest.TestCase):
    def test_trailing_comma_is_parsed_without_executing_code(self):
        from directory import parse_directory
        self.assertEqual(parse_directory('var kiwisdr_com = [{"name":"test"},];'),[{'name':'test'}])
        with self.assertRaises(ValueError):
            parse_directory('var kiwisdr_com = [function(){evil();}];')

    def test_unavailable_and_external_api_disabled_are_excluded(self):
        from directory import rank_stations
        base=dict(status='active',offline='no',ext_api='1',users='1',users_max='4',gps='(39,-98)',
                  bands='0-30000000',url='http://example.com',name='TEST',snr='20,15')
        self.assertEqual(len(rank_stations([base],REGIONS[0])),1)
        self.assertFalse(rank_stations([dict(base,users='4'),dict(base,ext_api='0')],REGIONS[0]))

if __name__=='__main__':
    unittest.main()
