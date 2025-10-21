#!/usr/bin/env python3
import os, time, subprocess
from gpiozero import DigitalInputDevice

SENSE_PIN = 23            # GPIO tied to amp's switched rail via divider/isolator
ACTIVE_HIGH = True        # True if pin is HIGH when amp is ON
DEBOUNCE_SEC = 0.15
FADE_STEP = 5
FADE_DELAY = 0.05

OLED_MSG = "/tmp/display_message"
VOL_FILE  = "/var/local/amp_prev_volume"
FLAG_FILE = "/var/local/amp_paused_by_monitor"
AMP_STATE = "/var/local/amp_state"  # "ON"/"OFF"

def sh(cmd): subprocess.run(cmd, shell=True, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
def get_volume():
    try:
        out = subprocess.check_output("mpc volume", shell=True, text=True, timeout=2).strip()
        for tok in out.split():
            if tok.endswith("%") and tok[:-1].isdigit():
                return int(tok[:-1])
    except: pass
    return 100
def set_volume(v): sh(f"mpc volume {max(0,min(100,int(v)))}")
def fade_to(target):
    cur=get_volume()
    step = -FADE_STEP if cur>target else FADE_STEP
    for v in range(cur, target + (1 if step>0 else -1), step):
        set_volume(v); time.sleep(FADE_DELAY)
    set_volume(target)
def show(msg):
    try: open(OLED_MSG,"w").write(msg)
    except: pass
def save_prev_volume():
    try: open(VOL_FILE,"w").write(str(get_volume()))
    except: pass
def load_prev_volume(defv=60):
    try: return int(open(VOL_FILE).read().strip())
    except: return defv
def set_amp_state(on: bool):
    try: open(AMP_STATE,"w").write("ON" if on else "OFF")
    except: pass

def pause_playback():
    save_prev_volume()
    fade_to(0)
    sh("mpc pause")
    open(FLAG_FILE,"w").close()
def resume_playback():
    if os.path.exists(FLAG_FILE):
        target=load_prev_volume()
        sh("mpc play")
        if get_volume()<target:
            for v in range(get_volume(), target+1, FADE_STEP):
                set_volume(v); time.sleep(FADE_DELAY)
        else:
            set_volume(target)
        try: os.remove(FLAG_FILE)
        except: pass

def amp_is_on(level): return bool(level) if ACTIVE_HIGH else not bool(level)

def main():
    sense = DigitalInputDevice(SENSE_PIN, pull_up=False, bounce_time=DEBOUNCE_SEC)
    on = amp_is_on(sense.value)
    set_amp_state(on)
    if not on:
        show("AMP OFF")
        pause_playback()

    def on_rising():
        if ACTIVE_HIGH:
            set_amp_state(True)
            show("Resuming…")
            resume_playback()
    def on_falling():
        if ACTIVE_HIGH:
            set_amp_state(False)
            show("AMP OFF")
            pause_playback()

    if ACTIVE_HIGH:
        sense.when_activated = on_rising
        sense.when_deactivated = on_falling
    else:
        sense.when_activated = on_falling
        sense.when_deactivated = on_rising

    try:
        while True: time.sleep(1)
    except KeyboardInterrupt:
        pass

if __name__=="__main__":
    main()
