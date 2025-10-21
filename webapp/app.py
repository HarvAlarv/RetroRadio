#!/usr/bin/env python3
from flask import Flask, render_template, request, redirect, url_for, send_from_directory, flash
import os, json, subprocess, re, shutil

USER_HOME=os.path.expanduser("~")
MUSIC_ROOT=os.path.join(USER_HOME,"music")
NAMES_FILE=os.path.join(MUSIC_ROOT,"stations.json")
PRESETS = ["EQ Warm","EQ Flat","EQ Voice","EQ Night","EQ Bright","EQ Bypass"]
PRESET_FILE = "/var/local/eq_preset"

app=Flask(__name__)
app.secret_key="retro_radio_secret"
app.config["MAX_CONTENT_LENGTH"]=100*1024*1024

def sh(c): subprocess.run(c,shell=True,check=False)
def load_names():
    try: return {k:v for k,v in json.load(open(NAMES_FILE,encoding="utf-8")).items() if len(k)==2 and k.isdigit()}
    except: return {}
def save_names(n):
    tmp=NAMES_FILE+".tmp"; json.dump(n,open(tmp,"w",encoding="utf-8"),ensure_ascii=False,indent=2); os.replace(tmp,NAMES_FILE)
def station_dirs():
    return sorted([d for d in os.listdir(MUSIC_ROOT) if len(d)==2 and d.isdigit() and os.path.isdir(os.path.join(MUSIC_ROOT,d))])
def get_stations():
    names=load_names()
    items=[{"id":d,"label":names.get(d,f"Station {d}")} for d in station_dirs()]
    items.sort(key=lambda x:x["label"].lower()); return items
def next_free_station():
    used=set(station_dirs())
    for i in range(1,100):
        cand=f"{i:02d}"
        if cand not in used: return cand
    return None
def current_preset():
    try:
        out = subprocess.check_output("mpc outputs", shell=True, text=True, timeout=2)
        for line in out.splitlines():
            m=re.match(r'output:\s+(.*?)\s+\(.*\)\s+\[(on|off)\]', line.strip())
            if m and m.group(2)=="on": return m.group(1)
    except Exception: pass
    try: return open(PRESET_FILE).read().strip()
    except: return "EQ Warm"
def set_preset(name:str):
    if name not in PRESETS: return False
    sh(f'mpc enableonly "{name}"')
    try: os.makedirs(os.path.dirname(PRESET_FILE), exist_ok=True); open(PRESET_FILE,"w").write(name)
    except: pass
    return True

@app.route("/")
def index(): return render_template("index.html", stations=get_stations(), title="Stations")

@app.route("/station/<station>")
def station_view(station):
    p=os.path.join(MUSIC_ROOT,station)
    files=sorted([f for f in os.listdir(p) if f.lower().endswith(".mp3")]) if os.path.isdir(p) else []
    label=load_names().get(station, f"Station {station}")
    return render_template("station.html", station=station, label=label, files=files, title=label)

@app.route("/upload/<station>", methods=["POST"])
def upload(station):
    f=request.files.get("file")
    if not f or not f.filename.lower().endswith(".mp3"):
        flash("Upload a .mp3 file."); return redirect(url_for("station_view", station=station))
    d=os.path.join(MUSIC_ROOT,station); os.makedirs(d,exist_ok=True); f.save(os.path.join(d,f.filename)); sh("mpc update")
    flash(f"Uploaded {f.filename}")
    return redirect(url_for("station_view", station=station))

@app.route("/files/<station>/<fn>")
def download(station,fn):
    return send_from_directory(os.path.join(MUSIC_ROOT,station),fn,as_attachment=True)

@app.route("/delete/<station>/<fn>")
def delete_file(station,fn):
    p=os.path.join(MUSIC_ROOT,station,fn)
    if os.path.exists(p): os.remove(p); sh("mpc update"); flash(f"Deleted {fn}")
    return redirect(url_for("station_view", station=station))

@app.route("/station/<station>/set_name", methods=["POST"])
def set_station_name(station):
    new=request.form.get("name","").strip(); names=load_names(); names[station]=new if new else names.get(station,f"Station {station}"); save_names(names); flash("Saved station name.")
    return redirect(url_for("station_view", station=station))

@app.route("/add_station", methods=["POST"])
def add_station():
    nn=next_free_station()
    if not nn: flash("All station numbers 01–99 are already in use."); return redirect(url_for("index"))
    os.makedirs(os.path.join(MUSIC_ROOT,nn), exist_ok=True)
    names=load_names(); names.setdefault(nn, f"Station {nn}"); save_names(names)
    sh("mpc update"); flash(f"Created {names[nn]}.")
    return redirect(url_for("station_view", station=nn))

@app.route("/station/<station>/delete", methods=["POST"])
def delete_station(station):
    if not (len(station)==2 and station.isdigit()):
        flash("Invalid station."); return redirect(url_for("index"))
    d=os.path.join(MUSIC_ROOT,station)
    try:
        if os.path.isdir(d): shutil.rmtree(d)
    except Exception as e:
        flash(f"Failed to delete files: {e}"); return redirect(url_for("station_view", station=station))
    names=load_names(); 
    if station in names: del names[station]; save_names(names)
    sh("mpc update"); flash("Station deleted.")
    return redirect(url_for("index"))

@app.route("/settings")
def settings_view(): return render_template("settings.html", presets=PRESETS, selected=current_preset(), title="EQ Settings")

@app.route("/set_preset", methods=["POST"])
def set_preset_route():
    choice=request.form.get("preset","EQ Warm")
    flash("EQ preset set to: "+choice if set_preset(choice) else "Failed to set preset")
    return redirect(url_for("settings_view"))

if __name__=="__main__":
    app.run(host="0.0.0.0", port=8080, debug=False)
