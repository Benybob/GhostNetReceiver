"""Stateful rational FIR conversion; packet boundaries never change sample time."""
from math import gcd
import numpy as np
from scipy.signal import firwin

class StreamResampler:
    def __init__(self,rate,output_rate=12000):
        self.rate=int(rate);self.output_rate=int(output_rate)
        if self.rate<8000 or self.rate>384000:raise ValueError('Unsupported audio sample rate')
        factor=gcd(self.rate,self.output_rate)
        self.up=self.output_rate//factor;self.down=self.rate//factor
        scale=max(self.up,self.down)
        self.taps=firwin(20*scale+1,1/scale,window=('kaiser',5))*self.up if scale>1 else np.ones(1)
        self.history=np.empty(0,dtype=np.float64)
        self.input_count=0;self.output_count=0
        self.span=(len(self.taps)+self.up-1)//self.up

    def process(self,samples):
        samples=np.asarray(samples)
        if samples.ndim!=1:raise ValueError('Expected mono audio')
        data=samples.astype(np.float64)
        if np.issubdtype(samples.dtype,np.integer):data/=32768.0
        data=np.nan_to_num(data)
        if not len(data):return np.empty(0,dtype=np.int16)
        start=self.input_count-len(self.history)
        joined=np.concatenate((self.history,data))
        self.input_count+=len(data)
        total=(self.input_count*self.up+self.down-1)//self.down
        ticks=np.arange(self.output_count,total,dtype=np.int64)*self.down
        newest=ticks//self.up;phase=ticks%self.up
        back=np.arange(self.span)
        indices=newest[:,None]-back[None,:]-start
        taps=phase[:,None]+back[None,:]*self.up
        valid=(indices>=0)&(indices<len(joined))&(taps<len(self.taps))
        values=joined[np.clip(indices,0,len(joined)-1)]
        coefficients=self.taps[np.minimum(taps,len(self.taps)-1)]
        out=np.sum(values*coefficients*valid,axis=1)
        self.output_count=total
        self.history=joined[-self.span:].copy()
        return np.clip(np.rint(out*32768),-32768,32767).astype(np.int16)
