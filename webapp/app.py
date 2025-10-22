#!/usr/bin/env python3
from flask import (
    Flask, render_template, request, redirect, url_for,
    send_from_directory, flash, jsonify
)
import os, json, subprocess, re, shutil, time

# ------------------ Paths & constants ------------------
USER_HOME = os.path.expanduser("~")
MUSIC_ROOT = os.path.join(USER_HOME, "music")
NAMES_FILE = os.path.join(MUSIC_ROOT, "stations.json")
PRESETS = ["EQ Warm","EQ Flat","EQ Voice","EQ Night","EQ Bright","EQ Bypass"]
PRESET_FILE = "/var/local/eq_preset"

# Services we expose in Settings > Services table
SERVICE_ALLOWLIST = [
    "mpd",
    "station-radio",
    "radio-web",
    "radio-netcheck",
    "radio-portal",
    "eq-apply",
    "amp-monitor",
    "ssh",
]

app = Flask(__name__)
app.secret_key = "retro_radio_secret"
app.config["MAX_CONTENT_LENGTH"] = 1024 * 1024 * 1024  # 1 GB uploads

# ------------------ Helpers ------------------
def sh(cmd: str, timeout: int = 10) -> int:
    """Run a shell command, non-throwing."""
    try:
        subprocess.run(cmd, shell=True, check=False, timeout=timeout)
        return 0
    except Exception:
        return 1

def run(cmd_list, timeout: int = 10):
    """Run a command list, capture stdout (utf-8), return (rc, out)."""
    try:
        out = subprocess.check_output(cmd_list, stderr=subprocess.STDOUT, timeout=timeout)
        return 0, out.decode("utf-8", "ignore")
    except subprocess.CalledProcessError as e:
        return e.returncode, e.output.decode("utf-8", "ignore")
    except Exception as e:
        return 1, str(e)

def load_names():
    try:
        with open(NAMES_FILE, encoding="utf-8") as f:
            data = json.load(f)
        return {k: v for k, v in data.items() if len(k) == 2 and k.isdigit()}
    except Exception:
        return {}

def save_names(n):
    os.makedirs(os.path.dirname(NAMES_FILE), exist_ok=True)
    tmp = NAMES_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(n, f, ensure_ascii=False, indent=2)
    os.replace(tmp, NAMES_FILE)

def station_dirs():
    if not os.path.isdir(MUSIC_ROOT):
        return []
    return sorted([d for d in os.listdir(MUSIC_ROOT)
                   if len(d) == 2 and d.isdigit()
                   and os.path.isdir(os.path.join(MUSIC_ROOT, d))])

def get_stations():
    names = load_names()
    items = [{"id": d, "label": names.get(d, f"Station {d}")} for d in station_dirs()]
    items.sort(key=lambda x: x["label"].lower())
    return items

def next_free_station():
    used = set(station_dirs())
    for i in range(1, 100):
        cand = f"{i:02d}"
        if cand not in used:
            return cand
    return None

def current_preset():
    # Prefer MPD's reported enabled output
    try:
        rc, out = run(["mpc", "outputs"], timeout=2)
        if rc == 0:
            for line in out.splitlines():
                m = re.match(r'output:\s+(.*?)\s+\(.*\)\s+\[(on|off)\]', line.strip())
                if m and m.group(2) == "on":
                    return m.group(1)
    except Exception:
        pass
    # Fallback to sticky file
    try:
        return open(PRESET_FILE).read().strip()
    except Exception:
        return "EQ Warm"

def set_preset(name: str):
    if name not in PRESETS:
        return False
    sh(f'mpc enableonly "{name}"')
    try:
        os.makedirs(os.path.dirname(PRESET_FILE), exist_ok=True)
        open(PRESET_FILE, "w").write(name)
    except Exception:
        pass
    return True

def ensure_mpd_volume_75():
    # You asked to keep MPD fixed at 75% for outboard amp control
    sh("mpc volume 75", timeout=3)

# Call once at startup (and we’ll also set it inside /api/play_station)
ensure_mpd_volume_75()

# ------------------ Web pages ------------------
@app.route("/")
def index():
    return render_template("index.html", stations=get_stations(), title="Stations")

@app.route("/station/<station>")
def station_view(station):
    p = os.path.join(MUSIC_ROOT, station)
    files = sorted([f for f in os.listdir(p) if f.lower().endswith(".mp3")]) if os.path.isdir(p) else []
    label = load_names().get(station, f"Station {station}")
    return render_template("station.html", station=station, label=label, files=files, title=label)

@app.route("/settings")
def settings_view():
    return render_template("settings.html",
                           presets=PRESETS,
                           selected=current_preset(),
                           stations=get_stations(),
                           title="Settings")

# ------------------ Uploads & files ------------------
@app.route("/upload/<station>", methods=["POST"])
def upload(station):
    # Multi-file upload support
    files = request.files.getlist("files") or []
    if not files:
        # Fallback for older single-file forms
        f = request.files.get("file")
        files = [f] if f else []

    saved = 0
    os.makedirs(os.path.join(MUSIC_ROOT, station), exist_ok=True)
    for f in files:
        if not f or not f.filename.lower().endswith(".mp3"):
            continue
        dest = os.path.join(MUSIC_ROOT, station, f.filename)
        # collision-safe rename
        base, ext = os.path.splitext(os.path.basename(f.filename))
        i = 1
        while os.path.exists(dest):
            dest = os.path.join(MUSIC_ROOT, station, f"{base}_{i}{ext}")
            i += 1
        f.save(dest)
        saved += 1

    sh("mpc update")
    flash(f"Uploaded {saved} file(s).")
    return redirect(url_for("station_view", station=station))

@app.route("/files/<station>/<fn>")
def download(station, fn):
    return send_from_directory(os.path.join(MUSIC_ROOT, station), fn, as_attachment=True)

@app.route("/delete/<station>/<fn>")
def delete_file(station, fn):
    p = os.path.join(MUSIC_ROOT, station, fn)
    if os.path.exists(p):
        os.remove(p)
        sh("mpc update")
        flash(f"Deleted {fn}")
    return redirect(url_for("station_view", station=station))

# ------------------ Station mgmt ------------------
@app.route("/station/<station>/set_name", methods=["POST"])
def set_station_name(station):
    new = request.form.get("name", "").strip()
    names = load_names()
    names[station] = new if new else names.get(station, f"Station {station}")
    save_names(names)
    flash("Saved station name.")
    return redirect(url_for("station_view", station=station))

@app.route("/add_station", methods=["POST"])
def add_station():
    nn = next_free_station()
    if not nn:
        flash("All station numbers 01–99 are already in use.")
        return redirect(url_for("index"))
    os.makedirs(os.path.join(MUSIC_ROOT, nn), exist_ok=True)
    names = load_names()
    names.setdefault(nn, f"Station {nn}")
    save_names(names)
    sh("mpc update")
    flash(f"Created {names[nn]}.")
    return redirect(url_for("station_view", station=nn))

@app.route("/station/<station>/delete", methods=["POST"])
def delete_station(station):
    if not (len(station) == 2 and station.isdigit()):
        flash("Invalid station.")
        return redirect(url_for("index"))
    d = os.path.join(MUSIC_ROOT, station)
    try:
        if os.path.isdir(d):
            shutil.rmtree(d)
    except Exception as e:
        flash(f"Failed to delete files: {e}")
        return redirect(url_for("station_view", station=station))
    names = load_names()
    if station in names:
        del names[station]
        save_names(names)
    sh("mpc update")
    flash("Station deleted.")
    return redirect(url_for("index"))

# ------------------ EQ settings (existing) ------------------
@app.route("/set_preset", methods=["POST"])
def set_preset_route():
    choice = request.form.get("preset", "EQ Warm")
    flash("EQ preset set to: " + choice if set_preset(choice) else "Failed to set preset")
    return redirect(url_for("settings_view"))

# ------------------ API: Playback & status ------------------
def parse_status():
    """Return dict with state/track and sticky 75% volume."""
    rc, out = run(["mpc", "-f", "%file%|%title%|%artist%"])
    state = "stopped"
    cur = {"file": None, "title": None, "artist": None}
    if rc == 0:
        lines = [l for l in out.splitlines() if l.strip()]
        if lines:
            parts = lines[0].split("|")
            if parts:
                cur["file"] = parts[0] or None
                cur["title"] = (parts[1] if len(parts) > 1 else None) or None
                cur["artist"] = (parts[2] if len(parts) > 2 else None) or None
        if len(lines) >= 2:
            if "[playing]" in lines[1]:
                state = "playing"
            elif "[paused]" in lines[1]:
                state = "paused"
    return {"state": state, "current": cur, "volume": 75}

@app.get("/api/status")
def api_status():
    return jsonify(parse_status())

@app.post("/api/play")
def api_play():
    sh("mpc play")
    ensure_mpd_volume_75()
    return jsonify(parse_status())

@app.post("/api/pause")
def api_pause():
    sh("mpc pause")
    return jsonify(parse_status())

@app.post("/api/stop")
def api_stop():
    sh("mpc stop")
    return jsonify(parse_status())

@app.post("/api/next")
def api_next():
    sh("mpc next")
    return jsonify(parse_status())

@app.post("/api/prev")
def api_prev():
    sh("mpc prev")
    return jsonify(parse_status())

@app.get("/api/stations")
def api_stations():
    return jsonify(get_stations())

@app.post("/api/play_station/<station_id>")
def api_play_station(station_id):
    # Clear queue, add folder by station id, play
    sh("mpc stop")
    sh("mpc clear")
    # MPD indexes relative to music_directory, so station_id is enough
    sh(f'mpc add "{station_id}"')
    sh("mpc play")
    ensure_mpd_volume_75()
    return jsonify(parse_status())

# ------------------ API: Disk & services ------------------
@app.get("/api/disks")
def api_disks():
    # Use df -B1 / for consistent bytes
    rc, out = run(["df", "-B1", "/"])
    total = used = avail = 0
    if rc == 0:
        # Filesystem 1B-blocks Used Available Use% Mounted on
        lines = out.splitlines()
        if len(lines) >= 2:
            parts = lines[1].split()
            if len(parts) >= 6:
                total = int(parts[1]); used = int(parts[2]); avail = int(parts[3])
    used_pct = int(round(100 * used / total)) if total else 0
    return jsonify({
        "total_bytes": total,
        "used_bytes": used,
        "free_bytes": avail,
        "used_pct": used_pct
    })

def svc_status(name: str):
    st = {"name": name, "active": False, "enabled": False, "since": None}
    rc, a = run(["sudo", "systemctl", "is-active", name])
    st["active"] = a.strip() == "active"
    rc, e = run(["sudo", "systemctl", "is-enabled", name])
    st["enabled"] = e.strip() == "enabled"
    # Optional: fetch since (best-effort)
    rc, out = run(["systemctl", "show", name, "--property=ActiveEnterTimestamp"])
    if rc == 0 and "ActiveEnterTimestamp=" in out:
        st["since"] = out.strip().split("=", 1)[1] or None
    return st

@app.get("/api/services")
def api_services():
    return jsonify([svc_status(s) for s in SERVICE_ALLOWLIST])

@app.post("/api/service/<name>/restart")
def api_service_restart(name):
    if name not in SERVICE_ALLOWLIST:
        return jsonify({"ok": False, "error": "disallowed"}), 400
    rc, out = run(["sudo", "systemctl", "restart", name], timeout=15)
    ok = (rc == 0)
    return jsonify({"ok": ok, "status": svc_status(name)}), (200 if ok else 500)

# ------------------ API: Library & system ------------------
@app.post("/api/library/rescan")
def api_library_rescan():
    sh("mpc update")
    return jsonify({"ok": True})

@app.get("/api/settings/ssh")
def api_settings_ssh_get():
    rc, a = run(["sudo", "systemctl", "is-active", "ssh"])
    rc, e = run(["sudo", "systemctl", "is-enabled", "ssh"])
    return jsonify({
        "active": a.strip() == "active",
        "enabled": e.strip() == "enabled",
    })

@app.post("/api/settings/ssh")
def api_settings_ssh_post():
    action = request.json.get("action") if request.is_json else request.form.get("action")
    if action == "enable":
        run(["sudo", "systemctl", "enable", "ssh"])
        run(["sudo", "systemctl", "start", "ssh"])
    elif action == "disable":
        run(["sudo", "systemctl", "stop", "ssh"])
        run(["sudo", "systemctl", "disable", "ssh"])
    elif action == "toggle":
        rc, e = run(["sudo", "systemctl", "is-enabled", "ssh"])
        if e.strip() == "enabled":
            run(["sudo", "systemctl", "stop", "ssh"])
            run(["sudo", "systemctl", "disable", "ssh"])
        else:
            run(["sudo", "systemctl", "enable", "ssh"])
            run(["sudo", "systemctl", "start", "ssh"])
    else:
        return jsonify({"ok": False, "error": "bad action"}), 400
    rc, a = run(["sudo", "systemctl", "is-active", "ssh"])
    rc, e = run(["sudo", "systemctl", "is-enabled", "ssh"])
    return jsonify({"ok": True, "active": a.strip() == "active", "enabled": e.strip() == "enabled"})

@app.post("/api/system/reboot")
def api_system_reboot():
    # Best-effort return before reboot
    sh("sync")
    sh("sudo /sbin/reboot")
    return jsonify({"ok": True, "rebooting": True})

# ------------------ App entry ------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=False)
