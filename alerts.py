"""Local desktop alerts while the application is running."""
from datetime import datetime
import time
import tkinter as tk

def quiet_now(config,now=None):
    if not config.get('quiet_enabled',True):return False
    now=now or datetime.now()
    try:
        start=int(config.get('quiet_start','22'));end=int(config.get('quiet_end','7'))
    except (TypeError,ValueError):
        return False
    if not 0<=start<=23 or not 0<=end<=23:return False
    if start==end:return True
    return start<=now.hour<end if start<end else now.hour>=start or now.hour<end

def should_alert(message,config,now=None):
    if not config.get('alerts',False) or message['classification']=='Unclassified traffic':return False
    return not quiet_now(config,now) or (message['classification']=='FLASH' and config.get('flash_override',False))

class DesktopAlerts:
    def __init__(self,root):
        self.root=root;self.toast=None;self.seen={};self.last_shown=0

    def show(self,message,config):
        now=time.monotonic()
        self.seen={k:t for k,t in self.seen.items() if now-t<120}
        key=message['text']
        if not should_alert(message,config) or key in self.seen:return False
        self.seen[key]=now
        if self.toast and self.toast.winfo_exists():self.toast.destroy()
        toast=self.toast=tk.Toplevel(self.root)
        toast.title('GhostNet message');toast.attributes('-topmost',True)
        toast.resizable(False,False)
        flash=message['classification']=='FLASH'
        color='#714211' if flash else '#174b43'
        toast.configure(bg=color)
        tk.Label(toast,text='GhostNet FLASH' if flash else 'GhostNet message',bg=color,fg='white',font=('Segoe UI',12,'bold')).pack(anchor='w',padx=15,pady=(12,4))
        tk.Label(toast,text=message['text'][:300],bg=color,fg='white',wraplength=365,justify='left').pack(anchor='w',padx=15,pady=5)
        tk.Button(toast,text='Open inbox',command=lambda:(self.root.deiconify(),self.root.lift(),toast.destroy())).pack(anchor='e',padx=15,pady=10)
        toast.update_idletasks()
        toast.geometry(f'+{max(0,toast.winfo_screenwidth()-420)}+{max(0,toast.winfo_screenheight()-toast.winfo_height()-80)}')
        toast.after(12000,toast.destroy)
        self.last_shown=now
        return True
