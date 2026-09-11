"""Bounded receiver rotation; all waits can be cancelled by Stop."""
import time
from directory import discover

class ReceiverUnavailable(RuntimeError):
    pass

class ReceiverPool:
    def __init__(self,config,discover_fn=discover):
        self.config=config
        self.discover=discover_fn
        self.stations=list(config.get('stations',[]))
        self.index=0
        self.failures=0
        self.refresh_at=0
        self.last_url=''

    def next(self,hz=7107000):
        if not self.config.get('automatic_receiver',True):
            url=(self.config.get('kiwi_url') or '').strip()
            if not url:
                raise ReceiverUnavailable('Enter a receiver URL or enable automatic selection.')
            return {'url':url,'name':url,'low':0,'high':30_000_000}
        if not self.stations or self.index>=len(self.stations):
            if time.monotonic()>=self.refresh_at or not self.stations:
                coords=None
                if self.config.get('latitude') and self.config.get('longitude'):
                    coords=(float(self.config['latitude']),float(self.config['longitude']))
                self.stations=self.discover(self.config['region'],coords,hz)
                self.refresh_at=time.monotonic()+300
            self.index=0
            if len(self.stations)>1 and self.stations[0]['url']==self.last_url:
                self.stations=self.stations[1:]+self.stations[:1]
        if not self.stations:raise ReceiverUnavailable('No available online receivers')
        result=self.stations[self.index]
        self.index+=1
        self.last_url=result['url']
        return result

    def delay(self):
        self.failures+=1
        return min(60,5*2**min(self.failures-1,4))

    def stable(self):
        self.failures=0
