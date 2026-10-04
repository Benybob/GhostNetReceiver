"""Read-only directory discovery. Never executes the directory's JavaScript."""
import json
import math
import re
import threading
import time
import urllib.request
from urllib.parse import urlparse
from core import REGIONS, region_for_location

_DIRECTORY_LOCK=threading.Lock()
_DIRECTORY_CACHE={'at':0.0,'rows':None}

DIRECTORY_URL='http://rx.linkfanel.net/kiwisdr_com.js'

def parse_directory(text):
    match=re.search(r'var\s+kiwisdr_com\s*=\s*\[',text)
    if not match:
        raise ValueError('Directory format changed. Enter a receiver URL manually.')
    decoder=json.JSONDecoder()
    index=match.end()
    rows=[]
    while index<len(text):
        while index<len(text) and text[index] in ' \t\r\n,':
            index+=1
        if index<len(text) and text[index]==']':
            return rows
        item,index=decoder.raw_decode(text,index)
        if not isinstance(item,dict):
            raise ValueError('Unexpected directory entry')
        rows.append(item)
        if len(rows)>10000:
            raise ValueError('Unexpectedly large directory')
    raise ValueError('Incomplete directory')

def distance(lat,lon,other_lat,other_lon):
    a,b,c,d=map(math.radians,(lat,lon,other_lat,other_lon))
    x=math.sin((c-a)/2)**2+math.cos(a)*math.cos(c)*math.sin((d-b)/2)**2
    return 6371*2*math.asin(min(1,math.sqrt(x)))

def rank_stations(rows,region,location=None,hz=7107000):
    ranked=[]
    # Region centers are ranking defaults, never claims about the user's position.
    center=location or {REGIONS[0]:(39,-98),REGIONS[1]:(50,10),REGIONS[2]:(-30,140)}[region]
    hz=float(hz or 7107000)
    for row in rows:
        try:
            if row.get('status')!='active' or row.get('offline')!='no' or int(row.get('ext_api','0'))<=0:
                continue
            free=int(row['users_max'])-int(row['users'])
            if free<=0 or row.get('ant_connected')=='0' or float(row.get('freq_offset',0))!=0:
                continue
            lat,lon=map(float,row['gps'].strip('()').split(','))
            if region_for_location(lat,lon)!=region:
                continue
            low,high=map(float,row['bands'].split('-'))
            if not low<=hz<=high:
                continue
            url=urlparse(row['url'])
            if url.scheme!='http' or not url.hostname or url.username or url.password:
                continue
            # The tested client cannot reliably negotiate the public redirect proxy.
            if url.hostname.endswith('.proxy.kiwisdr.com'):
                continue
            snr=float(str(row.get('snr','0,0')).split(',')[-1])
            km=distance(*center,lat,lon)
            score=km-25*min(snr,50)-25*free
            ranked.append(dict(name=str(row.get('name',url.hostname)),url=row['url'],
                free=free,snr=snr,km=round(km),score=score,low=low,high=high))
        except (ValueError,TypeError,KeyError):
            continue
    return sorted(ranked,key=lambda r:r['score'])[:30]

def load_directory(ttl=120):
    with _DIRECTORY_LOCK:
        now=time.monotonic()
        if _DIRECTORY_CACHE['rows'] is not None and now-_DIRECTORY_CACHE['at']<ttl:
            return _DIRECTORY_CACHE['rows']
        request=urllib.request.Request(DIRECTORY_URL,headers={'User-Agent':'GhostNetReceiver/0.4.2'})
        with urllib.request.urlopen(request,timeout=15) as response:
            payload=response.read(5_000_001)
        if len(payload)>5_000_000:
            raise ValueError('Directory exceeded size limit')
        rows=parse_directory(payload.decode('utf-8'))
        _DIRECTORY_CACHE['rows']=rows
        _DIRECTORY_CACHE['at']=now
        return rows

def discover(region,location=None,hz=7107000):
    stations=rank_stations(load_directory(),region,location,hz)
    if not stations:
        raise ValueError('No available regional receivers in the directory snapshot. Try later or enter a URL.')
    return stations
