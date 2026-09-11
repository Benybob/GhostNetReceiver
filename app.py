"""Simple local GUI for the integrated GhostNet receiver."""
import json
import os
from pathlib import Path
import queue
import sys
import threading
import tkinter as tk
from tkinter import ttk,filedialog,messagebox
from datetime import datetime
from core import UTC,REGIONS,Journal,occurrences,region_for_location,listen_plan
from native_session import NativeSession,FrameLogger,SPEED_CHOICES
from receivers import RECEIVER_CHOICES,SOURCE_AUDIO,SOURCE_KIWI,SOURCE_SOAPY,list_input_devices,list_output_devices,source_kind
from conversations import Conversations
from storage import VERSION,default_data_dir,import_legacy,runtime_root
from alerts import DesktopAlerts
from fleet import ReceiverFleet
import time

ROOT=runtime_root()
DATA_ROOT=default_data_dir()
DEFAULTS={'region':REGIONS[0],'source':SOURCE_KIWI,'automatic_receiver':True,'kiwi_url':'',
          'latitude':'','longitude':'','usb_args':'','gain':'30','audio_device':'',
          'tuning':'Automatic schedule','js8_speeds':'Normal + Fast','rtty':False,'rtty_reverse':False,'record_net':True,
          'alerts':True,'quiet_enabled':True,'quiet_start':'22','quiet_end':'7',
          'flash_override':True,'alert_sound':False,'speaker_device':'','monitor_volume':'0.3','multi_region':False,
          'hamlib_enabled':False,'hamlib_host':'127.0.0.1','hamlib_port':'4532'}

class App(tk.Tk):
    def __init__(self,data_dir=None):
        super().__init__()
        self.title('GhostNet Receiver '+VERSION)
        self.geometry('1100x760')
        self.minsize(850,600)
        self.configure(bg='#101922')
        icon=ROOT/'ghostnet.ico'
        if icon.is_file():
            try:self.iconbitmap(icon)
            except Exception:pass
        self.data_dir=Path(data_dir or DATA_ROOT)
        self.data_dir.mkdir(parents=True,exist_ok=True)
        if data_dir is None:
            legacy=(Path(sys.executable).parent if getattr(sys,'frozen',False) else ROOT)/'data'
            import_legacy(legacy,self.data_dir)
        self.settings=dict(DEFAULTS)
        self.settings_error=''
        try:
            if (self.data_dir/'settings.json').exists():
                saved=json.loads((self.data_dir/'settings.json').read_text())
                loaded={k:v for k,v in saved.items() if k in DEFAULTS}
                if loaded.get('source')=='USB / SoapySDR':
                    loaded['source']=SOURCE_SOAPY
                self.settings.update(loaded)
        except Exception as exc:self.settings_error=str(exc)
        self.vars={k:(tk.BooleanVar(value=v) if isinstance(v,bool) else tk.StringVar(value=v)) for k,v in self.settings.items()}
        self.journal=Journal(self.data_dir/'messages.sqlite3')
        self.conversations=Conversations(self.journal)
        self.alerts=DesktopAlerts(self)
        self.update_installer=None
        self.last_clock=0
        self.telemetry=tk.StringVar(value='Receiver: disconnected   •   Audio: waiting   •   Decoded: 0')
        self.countdown=tk.StringVar()
        self.updates=queue.Queue()
        self.session=None
        self.closing=False
        self.starting=False
        self.self_testing=False
        self.discovery_generation=0
        self.status=tk.StringVar(value='Ready to listen')
        self.station=tk.StringVar(value='An online receiver is selected automatically. No radio hardware needed.')
        self.summary=tk.StringVar(value='Your messages stay on this computer.')
        self.banner=tk.StringVar(value='Start listening to follow the published GhostNet hour.')
        self.search=tk.StringVar()
        self.tagged=tk.BooleanVar(value=True)
        self.items={}
        self.lane_status={region:tk.StringVar(value='Stopped') for region in REGIONS}
        style=ttk.Style(self)
        style.theme_use('clam')
        style.configure('.',background='#172532',foreground='#e5edf4',font=('Segoe UI',10))
        style.configure('TFrame',background='#172532')
        style.configure('TLabel',padding=4)
        style.configure('TButton',padding=(15,9),background='#284457')
        style.configure('Start.TButton',background='#207766',font=('Segoe UI',11,'bold'))
        style.configure('TNotebook.Tab',padding=(18,9))
        style.configure('TEntry',fieldbackground='#eef4f7',foreground='#172532')
        style.map('TCombobox',fieldbackground=[('readonly','#eef4f7')],foreground=[('readonly','#172532')])
        style.configure('Treeview',background='#101922',fieldbackground='#101922',foreground='#e5edf4',rowheight=34)
        style.configure('Treeview.Heading',background='#284457',font=('Segoe UI',10,'bold'))
        top=ttk.Frame(self,padding=18);top.pack(fill='x',padx=15,pady=(15,0))
        ttk.Label(top,text='GhostNet Receiver',font=('Segoe UI',24,'bold')).pack(anchor='w')
        ttk.Label(top,text='Listen. Read. Keep a local record.',foreground='#a9bdca').pack(anchor='w')
        row=ttk.Frame(top);row.pack(fill='x',pady=(12,5))
        ttk.Label(row,text='Your region').pack(side='left')
        self.region=ttk.Combobox(row,textvariable=self.vars['region'],values=REGIONS,state='readonly',width=24)
        self.region.pack(side='left',padx=10)
        self.start_button=ttk.Button(row,text='Start listening',style='Start.TButton',command=self.start)
        self.start_button.pack(side='left',padx=8)
        self.stop_button=ttk.Button(row,text='Stop',command=self.stop,state='disabled')
        self.stop_button.pack(side='left')
        self.hear_button=ttk.Button(row,text='Hear audio',command=self.toggle_hear,state='disabled')
        self.hear_button.pack(side='left',padx=8)
        self.tuned_button=ttk.Button(row,text='I tuned the radio',command=self.confirm_tuned,state='disabled')
        self.tuned_button.pack(side='left')
        ttk.Label(top,textvariable=self.status,font=('Segoe UI',12,'bold'),wraplength=960).pack(anchor='w',pady=(10,0))
        ttk.Label(top,textvariable=self.banner,font=('Segoe UI',16,'bold'),foreground='#f3d48b',wraplength=1000).pack(anchor='w',pady=(6,0))
        ttk.Label(top,textvariable=self.station,foreground='#a9bdca',wraplength=960).pack(anchor='w')
        meter=ttk.Frame(top);meter.pack(anchor='w',pady=(4,0))
        ttk.Label(meter,text='Audio').pack(side='left')
        self.meter=tk.Canvas(meter,width=160,height=12,bg='#101922',highlightthickness=0)
        self.meter.pack(side='left',padx=8)
        ttk.Label(top,textvariable=self.telemetry,foreground='#a9bdca').pack(anchor='w')
        ttk.Label(top,textvariable=self.countdown,foreground='#b6d9c8',wraplength=960).pack(anchor='w')
        self.tabs=ttk.Notebook(self);self.tabs.pack(fill='both',expand=True,padx=15,pady=15)
        self.inbox=ttk.Frame(self.tabs,padding=12)
        self.schedule=ttk.Frame(self.tabs,padding=12)
        self.advanced_tab=ttk.Frame(self.tabs)
        canvas=tk.Canvas(self.advanced_tab,bg='#172532',highlightthickness=0)
        scroll=ttk.Scrollbar(self.advanced_tab,orient='vertical',command=canvas.yview)
        scroll.pack(side='right',fill='y');canvas.pack(side='left',fill='both',expand=True)
        canvas.configure(yscrollcommand=scroll.set)
        self.advanced=ttk.Frame(canvas,padding=15)
        panel=canvas.create_window((0,0),window=self.advanced,anchor='nw')
        self.advanced.bind('<Configure>',lambda e:canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.bind('<Configure>',lambda e:canvas.itemconfigure(panel,width=e.width))
        self.regional=ttk.Frame(self.tabs,padding=10)
        self.activity=ttk.Frame(self.tabs,padding=12)
        for frame,title in [(self.inbox,'All messages'),(self.regional,'Regional feeds'),(self.schedule,'Next scheduled nets'),(self.advanced_tab,'Advanced'),(self.activity,'Activity')]:self.tabs.add(frame,text=title)
        self.build_inbox();self.build_advanced()
        self.build_regional()
        self.preferences=ttk.Frame(self.tabs,padding=15);self.tabs.insert(2,self.preferences,text='Alerts & updates')
        self.build_preferences()
        self.schedule_text=tk.Text(self.schedule,bg='#101922',fg='#d5e3ec',wrap='word',font=('Consolas',10),state='disabled')
        self.schedule_text.pack(fill='both',expand=True)
        self.events=tk.Text(self.activity,bg='#101922',fg='#d5e3ec',wrap='word',font=('Consolas',10),state='disabled')
        self.events.pack(fill='both',expand=True)
        self.refresh_schedule();self.refresh()
        self.region.bind('<<ComboboxSelected>>',lambda _:self.refresh_schedule())
        if self.settings_error:self.event('Settings could not be loaded: '+self.settings_error)
        self.protocol('WM_DELETE_WINDOW',self.close)
        self._poll_id=self.after(200,self.poll)

    def build_inbox(self):
        bar=ttk.Frame(self.inbox);bar.pack(fill='x',pady=(0,10))
        ttk.Label(bar,text='Search').pack(side='left')
        entry=ttk.Entry(bar,textvariable=self.search,width=26);entry.pack(side='left',padx=8)
        entry.bind('<KeyRelease>',lambda _:self.refresh())
        ttk.Checkbutton(bar,text='GhostNet tags only',variable=self.tagged,command=self.refresh).pack(side='left',padx=8)
        ttk.Button(bar,text='Export GhostNet CSV',command=self.export_ghostnet).pack(side='right')
        ttk.Button(bar,text='Export all',command=self.export).pack(side='right',padx=8)
        ttk.Button(bar,text='Net report',command=self.write_report).pack(side='right')
        body=ttk.Frame(self.inbox);body.pack(fill='both',expand=True)
        self.tree=ttk.Treeview(body,columns=('time','from','tag','text'),show='headings')
        for key,title,width in [('time','RECEIVED',140),('from','FROM',100),('tag','TRAFFIC',165),('text','MESSAGE',520)]:
            self.tree.heading(key,text=title);self.tree.column(key,width=width,minwidth=70,stretch=key=='text')
        scrollbar=ttk.Scrollbar(body,orient='vertical',command=self.tree.yview);scrollbar.pack(side='right',fill='y')
        self.tree.configure(yscrollcommand=scrollbar.set);self.tree.pack(fill='both',expand=True)
        self.tree.tag_configure('flash',foreground='#ffc47b')
        self.tree.tag_configure('incomplete',foreground='#9cb4c4')
        self.tree.bind('<<TreeviewSelect>>',self.details)
        ttk.Label(self.inbox,textvariable=self.summary).pack(anchor='w')
        self.detail=tk.Text(self.inbox,height=4,bg='#101922',fg='#d5e3ec',wrap='word',font=('Segoe UI',10),state='disabled')
        self.detail.pack(fill='x')

    def build_regional(self):
        ttk.Label(self.regional,text='Three independent online receivers. Each tab shows its lane status and messages copied near that region.',wraplength=900).pack(anchor='w',pady=(0,8))
        self.region_tabs=ttk.Notebook(self.regional);self.region_tabs.pack(fill='both',expand=True)
        self.region_trees={}
        for region in REGIONS:
            frame=ttk.Frame(self.region_tabs,padding=8);self.region_tabs.add(frame,text=region)
            ttk.Label(frame,textvariable=self.lane_status[region],foreground='#f3d48b',wraplength=850).pack(anchor='w',pady=(0,6))
            tree=ttk.Treeview(frame,columns=('time','from','tag','text'),show='headings')
            for key,title,width in [('time','RECEIVED',140),('from','FROM',100),('tag','TRAFFIC',150),('text','MESSAGE',500)]:
                tree.heading(key,text=title);tree.column(key,width=width,stretch=key=='text')
            tree.pack(fill='both',expand=True);self.region_trees[region]=tree

    def build_advanced(self):
        self.advanced.columnconfigure(1,weight=1)
        ttk.Label(self.advanced,text='Online listening needs no JS8Call app or virtual audio cable.',font=('Segoe UI',11,'bold')).grid(row=0,column=0,columnspan=2,sticky='w',pady=(0,8))
        try:self.inputs=list_input_devices()
        except Exception:self.inputs=[]
        try:self.outputs=list_output_devices()
        except Exception:self.outputs=[]
        fields=[('Receiver','source',RECEIVER_CHOICES),
                ('Custom receiver URL','kiwi_url',None),('Tuning','tuning',('Automatic schedule','Hold 40m JS8')),
                ('JS8 speeds','js8_speeds',SPEED_CHOICES),
                ('USB audio input','audio_device',[ '']+self.inputs),
                ('Hear-audio speakers','speaker_device',['']+self.outputs),
                ('Hear-audio volume (0 to 1)','monitor_volume',None),
                ('USB SDR arguments','usb_args',None),('USB SDR gain (dB)','gain',None)]
        for row,(label,key,values) in enumerate(fields,1):
            ttk.Label(self.advanced,text=label).grid(row=row,column=0,sticky='w',pady=5)
            w=(ttk.Combobox(self.advanced,textvariable=self.vars[key],values=values,state='readonly' if key not in ('audio_device','speaker_device') else 'normal') if values is not None else ttk.Entry(self.advanced,textvariable=self.vars[key]))
            w.grid(row=row,column=1,sticky='ew',padx=10,pady=5)
            if key=='audio_device':self.audio_combo=w
            if key=='speaker_device':self.speaker_combo=w
        ttk.Checkbutton(self.advanced,text='Choose an available online receiver automatically',variable=self.vars['automatic_receiver']).grid(row=10,column=0,columnspan=2,sticky='w',pady=8)
        ttk.Checkbutton(self.advanced,text='Monitor all published regions at once (uses 3 online receivers)',variable=self.vars['multi_region']).grid(row=11,column=0,columnspan=2,sticky='w',pady=4)
        location=ttk.Frame(self.advanced);location.grid(row=12,column=0,columnspan=2,sticky='w',pady=8)
        for label,key in [('Latitude','latitude'),('Longitude','longitude')]:
            ttk.Label(location,text=label).pack(side='left');ttk.Entry(location,textvariable=self.vars[key],width=12).pack(side='left',padx=5)
        ttk.Button(location,text='Suggest region',command=self.suggest).pack(side='left',padx=8)
        ttk.Button(location,text='Refresh audio devices',command=self.refresh_audio_devices).pack(side='left',padx=8)
        ttk.Checkbutton(self.advanced,text='Decode published 45.45 baud RTTY (7.077 MHz, preview)',variable=self.vars['rtty']).grid(row=13,column=0,columnspan=2,sticky='w',pady=4)
        ttk.Checkbutton(self.advanced,text='Reverse RTTY mark/space (USB polarity)',variable=self.vars['rtty_reverse']).grid(row=14,column=0,columnspan=2,sticky='w',pady=2)
        ttk.Checkbutton(self.advanced,text='Save a net-night WAV when GhostNet-tagged JS8 is copied',variable=self.vars['record_net']).grid(row=15,column=0,columnspan=2,sticky='w',pady=4)
        ham=ttk.Frame(self.advanced);ham.grid(row=16,column=0,columnspan=2,sticky='w',pady=6)
        ttk.Checkbutton(ham,text='Read-only Hamlib frequency check',variable=self.vars['hamlib_enabled']).pack(side='left')
        ttk.Label(ham,text='host').pack(side='left',padx=(12,4));ttk.Entry(ham,textvariable=self.vars['hamlib_host'],width=16).pack(side='left')
        ttk.Label(ham,text='port').pack(side='left',padx=(8,4));ttk.Entry(ham,textvariable=self.vars['hamlib_port'],width=6).pack(side='left')
        ttk.Label(self.advanced,text='Coordinates stay local. USB audio uses the radio’s USB sound card — the yellow banner is the frequency to tune. Choose headphones/speakers before Hear audio. This app never transmits and never sends Hamlib PTT or tune commands. VARA, ALE and voice are not decoded. RTTY is a preview decoder.',wraplength=820).grid(row=17,column=0,columnspan=2,sticky='w',pady=8)
        actions=ttk.Frame(self.advanced);actions.grid(row=18,column=0,columnspan=2,sticky='w')
        ttk.Button(actions,text='Save settings',command=self.save).pack(side='left',padx=(0,10))
        self.self_test_button=ttk.Button(actions,text='Test built-in decoder',command=self.self_test);self.self_test_button.pack(side='left')

    def refresh_audio_devices(self):
        try:
            ins=['']+list_input_devices();outs=['']+list_output_devices()
        except Exception as exc:
            messagebox.showerror('Audio',str(exc));return
        self.audio_combo.configure(values=ins)
        if hasattr(self,'speaker_combo'):self.speaker_combo.configure(values=outs)
        self.event('Capture: '+', '.join(n for n in ins if n)+' · Speakers: '+', '.join(n for n in outs if n))

    def build_preferences(self):
        ttk.Button(self.preferences,text='Choose installer…',command=self.choose_update).pack(anchor='e',pady=(0,6))
        canvas=tk.Canvas(self.preferences,bg='#172532',highlightthickness=0)
        scroll=ttk.Scrollbar(self.preferences,orient='vertical',command=canvas.yview)
        scroll.pack(side='right',fill='y');canvas.pack(side='left',fill='both',expand=True)
        canvas.configure(yscrollcommand=scroll.set)
        inner=ttk.Frame(canvas,padding=8)
        panel=canvas.create_window((0,0),window=inner,anchor='nw')
        inner.bind('<Configure>',lambda e:canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.bind('<Configure>',lambda e:canvas.itemconfigure(panel,width=max(1,e.width-4)))
        self.preferences_content=inner
        ttk.Label(inner,text='Alerts',font=('Segoe UI',12,'bold')).pack(anchor='w')
        ttk.Label(inner,text='Alerts stay on this computer. Nothing is sent to a network.',foreground='#a9bdca',wraplength=820).pack(anchor='w',pady=(0,8))
        ttk.Checkbutton(inner,text='Show a desktop notice for completed GhostNet-tagged messages',variable=self.vars['alerts']).pack(anchor='w',pady=3)
        quiet=ttk.Frame(inner);quiet.pack(anchor='w',pady=6)
        ttk.Checkbutton(quiet,text='Quiet hours from',variable=self.vars['quiet_enabled']).pack(side='left')
        ttk.Entry(quiet,textvariable=self.vars['quiet_start'],width=4).pack(side='left',padx=4)
        ttk.Label(quiet,text='to').pack(side='left')
        ttk.Entry(quiet,textvariable=self.vars['quiet_end'],width=4).pack(side='left',padx=4)
        ttk.Label(quiet,text='(hour 0–23, local time)').pack(side='left',padx=6)
        ttk.Checkbutton(inner,text='FLASH traffic overrides quiet hours',variable=self.vars['flash_override']).pack(anchor='w',pady=3)
        ttk.Label(inner,text='Desktop notices are silent. Hear audio uses only the output you explicitly select.',foreground='#a9bdca').pack(anchor='w',pady=3)
        ttk.Label(inner,text='Local updates',font=('Segoe UI',12,'bold')).pack(anchor='w',pady=(18,0))
        ttk.Label(inner,text='Messages live in %LOCALAPPDATA%\\GhostNetReceiver\\data. Keep that folder when you install a newer copy. Choose a GhostNet Receiver Setup .exe to install after this window closes.',foreground='#a9bdca',wraplength=820).pack(anchor='w',pady=(0,8))
        ttk.Label(inner,text='Use the always-visible Choose installer button above.',foreground='#a9bdca').pack(anchor='w')

    def choose_update(self):
        path=filedialog.askopenfilename(title='GhostNet Receiver Setup',filetypes=[('Setup','*.exe')])
        if not path:return
        try:
            from local_update import inspect_installer
            info=inspect_installer(path,VERSION)
        except Exception as exc:
            messagebox.showerror('Update',str(exc));return
        if messagebox.askokcancel('Update',f"Install {info['version']} after GhostNet Receiver closes?\nSHA-256 {info['sha256'][:16]}…\nThis file is not signature-checked."):
            self.update_installer=info;self.close()

    def update_countdown(self):
        now=datetime.now(UTC)
        if self.vars['tuning'].get()=='Hold 40m JS8':
            self.countdown.set('Holding 40m JS8 at 7.107 MHz. Scheduled retuning is off.')
            if not (self.session and self.session.thread.is_alive()):
                self.banner.set('Holding 7.107 MHz USB')
            return
        region=self.vars['region'].get()
        try:
            plan=listen_plan(region,now,rtty=self.vars['rtty'].get())
            windows=occurrences(region,now)
        except ValueError:
            self.countdown.set('');return
        if not (self.session and self.session.thread.is_alive()):
            self.banner.set(plan.get('banner',''))
        current=next(((start,end,window) for start,end,window in windows if start<=now<end),None)
        upcoming=next(((start,end,window) for start,end,window in windows if start>now),None)
        if current:
            start,end,window=current
            left=max(0,int((end-now).total_seconds()))
            extra=f' · {window.hz/1e6:.3f} MHz' if window.hz else ''
            self.countdown.set(f"Now: {window.name}{extra} · {left//60}m {left%60:02d}s left · {plan['reason']}")
        elif upcoming:
            start,end,window=upcoming
            until=max(0,int((start-now).total_seconds()))
            extra=f' · {window.hz/1e6:.3f} MHz' if window.hz else ''
            switch='SWITCH BAND · ' if 'bridge' in window.name.lower() and window.hz not in (0,7107000) else ''
            self.countdown.set(f'{switch}Next: {window.name}{extra} in {until//60}m {until%60:02d}s ({start.astimezone():%a %I:%M %p %Z})')
        else:
            self.countdown.set(plan['reason'])

    def suggest(self):
        try:self.vars['region'].set(region_for_location(self.vars['latitude'].get(),self.vars['longitude'].get()));self.refresh_schedule()
        except ValueError as exc:messagebox.showerror('Location',str(exc))

    def save(self):
        try:
            config={k:v.get() for k,v in self.vars.items()}
            if config['region'] not in REGIONS:raise ValueError('Choose a region.')
            for key in ('quiet_start','quiet_end'):
                if not 0<=int(config[key])<=23:raise ValueError('Quiet hours must be 0 through 23.')
            if config['js8_speeds'] not in SPEED_CHOICES:raise ValueError('Choose a JS8 speed preset.')
            if not -20<=float(config['gain'])<=100:raise ValueError('USB gain must be -20 to 100 dB.')
            if not 0<=float(config['monitor_volume'])<=1:raise ValueError('Hear-audio volume must be 0 through 1.')
            if not 1<=int(config['hamlib_port'])<=65535:raise ValueError('Hamlib port must be 1–65535.')
            path=self.data_dir/'settings.tmp';path.write_text(json.dumps(config,indent=2),encoding='utf-8');path.replace(self.data_dir/'settings.json')
            return config
        except Exception as exc:messagebox.showerror('Settings',str(exc));return None

    def start(self):
        if self.self_testing or self.starting or (self.session and self.session.thread.is_alive()):return
        config=self.save()
        if not config:return
        kind=source_kind(config)
        if kind=='kiwi' and not config['automatic_receiver'] and not config['kiwi_url'].strip():
            messagebox.showerror('Receiver','Enter a receiver URL or enable automatic selection.');return
        if kind=='soapy':
            try:
                import SoapySDR  # noqa: F401
            except ImportError:
                messagebox.showerror('USB SDR','SoapySDR is not installed. Choose USB audio (radio) for a transceiver, or install PothosSDR for a USB dongle.');return
        if config.get('multi_region') and kind!='kiwi':
            messagebox.showerror('Regional feeds','Monitoring all regions requires online KiwiSDR receivers.');return
        if config['js8_speeds'] not in SPEED_CHOICES:
            messagebox.showerror('Settings','Choose a JS8 speed preset.');return
        self.starting=True
        self.start_button.configure(state='disabled');self.stop_button.configure(state='normal');self.hear_button.configure(state='disabled' if config.get('multi_region') else 'normal');self.tuned_button.configure(state='normal' if kind=='audio' else 'disabled');self.region.configure(state='disabled')
        self.connect(config)

    def connect(self,config):
        self.starting=False
        self.status.set('Connecting…')
        kind=source_kind(config)
        if kind=='kiwi':self.station.set(config['kiwi_url'] or 'Online receiver')
        elif kind=='audio':self.station.set(config.get('audio_device') or 'USB audio input — tune the radio to the scheduled frequency')
        else:self.station.set(config.get('usb_args') or 'USB SDR')
        self.session=(ReceiverFleet(config,self.journal,self.data_dir,self.updates)
                      if config.get('multi_region') else NativeSession(config,self.journal,self.data_dir,self.updates))
        self.session.start()

    def stop(self):
        self.discovery_generation+=1;self.starting=False
        if self.session and self.session.thread.is_alive():self.session.stop();self.status.set('Stopping…')
        else:self.reset_controls();self.status.set('Stopped. Messages are saved.')

    def reset_controls(self):
        self.start_button.configure(state='normal');self.stop_button.configure(state='disabled');self.hear_button.configure(state='disabled',text='Hear audio');self.tuned_button.configure(state='disabled');self.region.configure(state='readonly')

    def confirm_tuned(self):
        if self.session and not isinstance(self.session,ReceiverFleet) and self.session.thread.is_alive():
            self.session.confirm_frequency()

    def toggle_hear(self):
        if not self.session or not self.session.thread.is_alive():
            return
        if isinstance(self.session,ReceiverFleet):
            messagebox.showinfo('Hear audio','Choose one regional receiver at a time to hear audio. Concurrent playback from three receivers is intentionally disabled.');return
        on=not self.session.monitor.enabled.is_set()
        speaker=(self.vars.get('speaker_device').get() if 'speaker_device' in self.vars else '') or ''
        if on and not speaker.strip():
            messagebox.showerror('Hear audio','Choose headphones or speakers in Advanced first.');return
        try:
            if on and not messagebox.askokcancel('Hear audio',f'This will play receive audio through:\n\n{speaker}\n\nUse headphones and confirm this is not a radio/virtual-cable input. Continue?'):
                return
            self.session.set_monitor(on, speaker, self.vars['monitor_volume'].get())
        except Exception as exc:
            messagebox.showerror('Hear audio',str(exc));return
        self.hear_button.configure(text='Mute speaker' if on else 'Hear audio')

    def refresh(self):
        rows=self.conversations.rows(self.search.get(),self.tagged.get())
        self.tree.delete(*self.tree.get_children());self.items={str(r['id']):r for r in rows}
        for r in rows:
            clock=datetime.fromisoformat(r['received_utc']).astimezone().strftime('%b %d %H:%M:%S')
            incomplete=r['state'] not in ('Complete frame','Checksum verified','Complete · no message checksum','RTTY line')
            prefix=('['+r['state']+'] ' if incomplete or r['state']=='RTTY line' else '')
            tags=[]
            if r['classification']=='FLASH':tags.append('flash')
            if incomplete:tags.append('incomplete')
            self.tree.insert('','end',iid=str(r['id']),values=(clock,r['sender'],r['classification'],prefix+r['text'].replace('\n',' ')),tags=tags)
        empty='No GhostNet-tagged messages yet. Uncheck “GhostNet tags only” to see other JS8.' if self.tagged.get() else 'No messages yet. This inbox fills when a JS8 or RTTY transmission is received.'
        self.summary.set(f'{len(rows)} conversations shown · incomplete stays marked · saved automatically' if rows else empty)
        all_rows=self.conversations.rows(self.search.get(),False)
        for region,tree in getattr(self,'region_trees',{}).items():
            tree.delete(*tree.get_children())
            regional=[r for r in all_rows if r.get('source','').startswith(region+' | ')]
            for r in regional:
                clock=datetime.fromisoformat(r['received_utc']).astimezone().strftime('%b %d %H:%M:%S')
                tree.insert('','end',values=(clock,r['sender'],r['classification'],r['text'].replace('\n',' ')))

    def details(self,_=None):
        selected=self.tree.selection()
        if selected:
            r=self.items[selected[0]]
            kind=r['state']
            frames=self.conversations.frames(r['id'])
            raw='\n'.join(f"Frame {f['id']}: {f['text']}" for f in frames)
            self.set_text(self.detail,f"{r['text']}\n{kind} · {r['frequency']/1e6:.6f} MHz · SNR {r['snr']} · {r['source']}\n{raw}")

    def refresh_schedule(self):
        lines=['Times below use this computer’s local time.\nJS8 is decoded. VARA and ALE are not. RTTY 45.45 is a preview. Voice is a tune reminder only.\n']
        for start,end,w in occurrences(self.vars['region'].get(),datetime.now(UTC)):
            extra=f' · {w.hz/1e6:.3f} MHz' if w.hz else ''
            note={'JS8':'','VARA':' · not decoded, stay on 7.107 JS8','RTTY':' · 7.077 MHz 45.45 baud preview','VOICE':' · tune 7.190 LSB, not decoded','ALE':' · not decoded'}.get(w.mode,'')
            switch='SWITCH BAND · ' if 'bridge' in w.name.lower() and w.hz not in (0,7107000) else ''
            lines.append(f'{start.astimezone():%a %b %d %I:%M %p} – {end.astimezone():%I:%M %p %Z}\n{switch}{w.name}{extra}{note}')
        self.set_text(self.schedule_text,'\n\n'.join(lines))

    @staticmethod
    def set_text(widget,text):
        widget.configure(state='normal');widget.delete('1.0','end');widget.insert('end',text);widget.configure(state='disabled')

    def event(self,text):
        self.events.configure(state='normal');self.events.insert('end',f'{datetime.now():%H:%M:%S}  {text}\n\n');self.events.see('end');self.events.configure(state='disabled')

    def export(self):
        path=filedialog.asksaveasfilename(defaultextension='.csv',initialfile='ghostnet-messages.csv',filetypes=[('CSV','*.csv')])
        if path:
            try:self.journal.export(path);self.event('Exported messages to '+path)
            except Exception as exc:messagebox.showerror('Export',str(exc))

    def export_ghostnet(self):
        path=filedialog.asksaveasfilename(defaultextension='.csv',initialfile='ghostnet-tagged.csv',filetypes=[('CSV','*.csv')])
        if path:
            try:
                from reports import export_ghostnet
                export_ghostnet(self.journal,path,True);self.event('Exported GhostNet-tagged conversations to '+path)
            except Exception as exc:messagebox.showerror('Export',str(exc))

    def write_report(self):
        folder=self.data_dir/'net-night';folder.mkdir(parents=True,exist_ok=True)
        path=folder/'report.json'
        try:
            from reports import heard_report
            metrics=self.session.metrics if self.session else {'audio_packets':0}
            report=heard_report(self.journal,metrics,path)
            self.event(f"Net report: heard={report['heard']} tagged={report['tagged_messages']} flash={report['flash_messages']} → {path}")
            self.tabs.select(self.activity)
        except Exception as exc:messagebox.showerror('Report',str(exc))

    def draw_meter(self,level=0):
        self.meter.delete('all')
        width=max(0,min(160,int(160*float(level or 0))))
        color='#3d9e7a' if level<0.8 else '#d4a017'
        if level>=0.95:color='#c45c4a'
        self.meter.create_rectangle(0,0,width,12,fill=color,outline='')

    def self_test(self):
        if self.self_testing:return
        if self.starting or (self.session and self.session.thread.is_alive()):
            self.event('Stop listening before running the recorded self-test.');self.tabs.select(self.activity);return
        self.self_testing=True;self.self_test_button.configure(state='disabled');self.start_button.configure(state='disabled')
        self.event('Testing the built-in decoder with a recorded reference signal. Results stay separate from live messages.')
        self.tabs.select(self.activity)
        def run():
            try:
                import wave,numpy as np
                from embedded import EmbeddedDecoder
                with wave.open(str(ROOT/'fixtures'/'A_1_4.wav')) as w:audio=np.frombuffer(w.readframes(w.getnframes()),dtype='<i2')
                frames=EmbeddedDecoder().decode(audio)
                journal=Journal(self.data_dir/'self-test.sqlite3')
                try:FrameLogger(journal).write(frames,'RECORDED SELF-TEST',7107000,1700000000)
                finally:journal.close()
                if len(frames)<4:raise RuntimeError(f'Expected four reference frames; decoded {len(frames)}.')
                self.updates.put(('selftest_done',f'Self-test passed: {len(frames)} JS8 frames decoded and logged. This is a recorded test, not live GhostNet traffic.'))
            except Exception as exc:self.updates.put(('selftest_done','Self-test failed: '+str(exc)))
        threading.Thread(target=run,daemon=True).start()

    def poll(self):
        if not self.winfo_exists():
            return
        changed=False
        closed=False
        try:
            closed=self._poll_body()
        except Exception as exc:
            try:self.event('Display error: '+str(exc))
            except Exception:pass
        if closed or not self.winfo_exists():
            return
        self._poll_id=self.after(200,self.poll)

    def _poll_body(self):
        changed=False
        for _ in range(200):
            try:kind,value=self.updates.get_nowait()
            except queue.Empty:break
            region=None
            if kind=='lane':
                region,kind,value=value
                if kind in ('health','station','banner','error'):
                    self.lane_status[region].set(str(value))
            if kind=='message':changed=True
            elif kind=='selftest_done':
                self.self_testing=False;self.self_test_button.configure(state='normal');self.start_button.configure(state='normal');self.event(value)
            elif kind=='health':
                if region:self.status.set('Regional monitoring active · see Regional feeds')
                else:self.status.set(value)
            elif kind=='telemetry':
                tagged=value.get('tagged',0)
                if region:
                    state='connected' if value['connected'] else 'connecting'
                    audio='audio arriving' if value['audio'] else 'audio waiting'
                    self.lane_status[region].set(f'{state} · {audio} · decoded {value["frames"]} · GhostNet {tagged}')
                    metrics=self.session.metrics
                    self.telemetry.set(f'3 regional lanes   •   Decoded: {int(metrics["decoded_frames"])}   •   GhostNet: {int(metrics["tagged"])}')
                else:
                    self.telemetry.set(f"Receiver: {'connected' if value['connected'] else 'connecting'}   •   Audio: {'arriving' if value['audio'] else 'waiting'}   •   Decoded: {value['frames']}   •   GhostNet: {tagged}")
                    self.draw_meter(value.get('level',0))
            elif kind=='banner':
                if region:self.lane_status[region].set(str(value))
                else:self.banner.set(value)
            elif kind=='cat':
                extra=str(value)
                base=self.banner.get().split(' · radio')[0]
                self.banner.set(base+' · '+extra)
            elif kind=='monitor':
                self.hear_button.configure(text='Mute speaker' if value else 'Hear audio')
            elif kind=='station':
                if region:self.lane_status[region].set('Receiver: '+str(value))
                else:self.station.set(value)
            elif kind=='complete':self.alerts.show(value,{k:v.get() for k,v in self.vars.items()})
            elif kind=='clock':
                self.event(f'JS8 decode alignment {value:+.0f}s. This includes receiver and network latency; compensation is automatic.')
            elif kind=='error':
                if region:self.lane_status[region].set('Stopped: '+str(value))
                else:self.status.set('Reception stopped: '+value)
                self.event((region+': ' if region else '')+str(value))
            elif kind=='stopped':
                if region:
                    self.lane_status[region].set('Stopped' + (': '+self.session.sessions[region].error if self.session.sessions[region].error else ''))
                    if self.session.thread.is_alive():continue
                self.telemetry.set('Receiver: disconnected   •   Audio: stopped   •   Messages saved')
                self.reset_controls()
                if not (self.session and self.session.error):self.status.set('Stopped. Messages are saved.')
            else:self.event((region+': ' if region else '')+str(value))
        if changed:self.refresh()
        if time.monotonic()-self.last_clock>=1:
            self.last_clock=time.monotonic();self.update_countdown()
        if self.closing and (not self.session or not self.session.thread.is_alive()):
            if self.update_installer:
                try:
                    from local_update import launch_installer
                    launch_installer(self.update_installer)
                except Exception as exc:
                    self.closing=False;self.update_installer=None;messagebox.showerror('Update',str(exc));self.after(200,self.poll);return
            self.journal.close();self.destroy();return True
        return False

    def destroy(self):
        if getattr(self,'_poll_id',None):
            try:self.after_cancel(self._poll_id)
            except Exception:pass
            self._poll_id=None
        super().destroy()

    def close(self):
        self.closing=True;self.stop()

if __name__=='__main__':
    if len(sys.argv)>=3 and sys.argv[1]=='--self-test':
        result={'passed':False,'root':str(ROOT)}
        out=Path(sys.argv[2])
        try:
            import wave,numpy as np
            from embedded import EmbeddedDecoder
            fixture=ROOT/'fixtures'/'A_1_4.wav'
            with wave.open(str(fixture)) as w:
                samples=np.frombuffer(w.readframes(w.getnframes()),dtype='<i2')
            frames=EmbeddedDecoder().decode(samples)
            result['frames']=[frame.get('text') for frame in frames]
            result['passed']=len(frames)>=4
        except Exception as exc:
            result['error']=str(exc)
        out.write_text(json.dumps(result,indent=2,default=str))
        os._exit(0 if result.get('passed') else 1)
    else:App().mainloop()
