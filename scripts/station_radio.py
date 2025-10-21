#!/usr/bin/env python3
import os, time, json, threading, subprocess
from gpiozero import RotaryEncoder, Button
from PIL import Image, ImageDraw, ImageFont
from luma.core.interface.serial import i2c
from luma.oled.device import ssd1306

USER_HOME = os.path.expanduser("~")
MUSIC_ROOT = os.path.join(USER_HOME, "music")
NAMES_FILE = os.path.join(MUSIC_ROOT, "stations.json")
STATE_FILE = os.path.join(USER_HOME, ".station")
OLED_ADDR = 0x3C
ENC_A, ENC_B, ENC_BTN = 16, 20, 21
FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"

BLINK_ONOFF_SECONDS = 0.5
TUNING_TIMEOUT_SEC  = 10

AMP_STATE_FILE = "/var/local/amp_state"  # "ON" / "OFF" written by amp_monitor.py
OLED_OFF_DELAY = 60                      # seconds to show AMP OFF before hiding panel

def sh(cmd): subprocess.run(cmd, shell=True, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
def mpc(cmd): sh(f"mpc {cmd}")

def detect_station_count():
    n=0
    try:
        for name in sorted(os.listdir(MUSIC_ROOT)):
            if len(name)==2 and name.isdigit() and os.path.isdir(os.path.join(MUSIC_ROOT,name)):
                n=max(n,int(name))
    except: pass
    return max(n,1)

STATION_COUNT = detect_station_count()

def load_names():
    try:
        with open(NAMES_FILE,"r",encoding="utf-8") as f:
            d=json.load(f); return {k:v for k,v in d.items() if len(k)==2 and k.isdigit()}
    except: return {}
def station_name(n, names=None):
    names = names or load_names()
    return names.get(f"{n:02d}", f"Station {n:02d}")
def load_station(default=1):
    try:
        n=int(open(STATE_FILE).read().strip()); 
        return n if 1<=n<=STATION_COUNT else default
    except: return default
def save_station(n):
    try: open(STATE_FILE,"w").write(str(int(n)))
    except: pass

def mpd_select_station(n):
    folder=f"{n:02d}"
    mpc("stop"); mpc("clear")
    mpc(f"add {folder}")
    mpc("random on"); mpc("repeat on"); mpc("play")

serial = i2c(port=1, address=OLED_ADDR)
dev = ssd1306(serial, width=128, height=64)
W,H=dev.width, dev.height
font_big=ImageFont.truetype(FONT_PATH,22)
font_med=ImageFont.truetype(FONT_PATH,16)

def draw_centered(text, blank=False):
    img = Image.new("1",(W,H))
    if not blank:
        d=ImageDraw.Draw(img)
        f=font_big if len(text)<=12 else font_med
        tw,th=d.textsize(text,font=f)
        d.text(((W-tw)//2,(H-th)//2), text, font=f, fill=1)
    dev.display(img)

names_cache=load_names()
current=load_station(1)
preview=current

tuning_active=False
stop_blink_ev=threading.Event()
tuning_timer=None

def _tuning_timeout():
    global tuning_active
    tuning_active=False
    stop_blink_ev.set()
    draw_centered(station_name(current,names_cache), blank=False)

def _start_tuning_timer():
    global tuning_timer
    if tuning_timer: tuning_timer.cancel()
    tuning_timer=threading.Timer(TUNING_TIMEOUT_SEC,_tuning_timeout)
    tuning_timer.daemon=True; tuning_timer.start()

def _blink_loop(name_to_blink):
    show=True
    while not stop_blink_ev.is_set():
        draw_centered(name_to_blink, blank=not show)
        time.sleep(BLINK_ONOFF_SECONDS)
        show=not show

def on_rotate():
    global preview, tuning_active
    steps = enc.steps % STATION_COUNT
    preview = steps + 1
    name = station_name(preview,names_cache)
    if not tuning_active:
        tuning_active=True
        stop_blink_ev.clear()
        threading.Thread(target=_blink_loop,args=(name,),daemon=True).start()
    else:
        draw_centered(name, blank=False)
    _start_tuning_timer()

def on_click():
    global current, tuning_active, names_cache
    if tuning_active:
        if tuning_timer: tuning_timer.cancel()
        tuning_active=False; stop_blink_ev.set()
        current=preview; save_station(current)
        names_cache=load_names()
        draw_centered(station_name(current,names_cache), blank=False)
        mpd_select_station(current)
    else:
        draw_centered(station_name(current,names_cache), blank=False)

def on_hold():
    mpc("stop")
    draw_centered(station_name(current,names_cache), blank=False)

enc=RotaryEncoder(a=ENC_A,b=ENC_B,max_steps=STATION_COUNT, wrap=True)
btn=Button(ENC_BTN,pull_up=True,bounce_time=0.05)
enc.when_rotated=on_rotate
btn.when_pressed=on_click
btn.hold_time=1.5
btn.when_held=on_hold

draw_centered(station_name(current,names_cache), blank=False)
mpd_select_station(current)

def watch_temp_messages():
    last=""
    while True:
        try:
            if os.path.exists("/tmp/display_message"):
                msg=open("/tmp/display_message").read().strip()
                if msg and msg!=last:
                    dev.show()
                    draw_centered(msg, blank=False)
                    last=msg
        except: pass
        time.sleep(1)
threading.Thread(target=watch_temp_messages,daemon=True).start()

oled_hidden=False
last_amp_off_at=None
def current_amp_state():
    try: return open(AMP_STATE_FILE).read().strip().upper()=="ON"
    except: return True

def oled_off():
    global oled_hidden
    if not oled_hidden:
        try: dev.hide()
        except: dev.clear()
        oled_hidden=True

def oled_on_and_render():
    global oled_hidden
    if oled_hidden:
        try: dev.show()
        except: pass
        oled_hidden=False
    draw_centered(station_name(current,names_cache), blank=False)

def amp_oled_power_manager():
    global last_amp_off_at
    was_on=None
    while True:
        amp_on=current_amp_state()
        now=time.time()
        if amp_on:
            last_amp_off_at=None
            oled_on_and_render()
        else:
            if was_on is True:
                last_amp_off_at=now
            if last_amp_off_at and (now-last_amp_off_at>=OLED_OFF_DELAY):
                oled_off()
        was_on=amp_on
        time.sleep(0.5)

threading.Thread(target=amp_oled_power_manager,daemon=True).start()

try:
    while True: time.sleep(0.2)
except KeyboardInterrupt:
    dev.clear()
