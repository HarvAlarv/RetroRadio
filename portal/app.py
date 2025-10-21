#!/usr/bin/env python3
import os
from flask import Flask, request

OLED_MSG="/tmp/display_message"
PORTAL_DONE="/var/local/radio_portal_done"

def show(msg):
    try: open(OLED_MSG,"w").write(msg)
    except: pass

app=Flask(__name__)

HTML='''<!doctype html><meta name=viewport content="width=device-width, initial-scale=1">
<title>RetroRadio Wi-Fi</title>
<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet">
<div class="container py-4" style="max-width:560px">
<h3 class="mb-3">RetroRadio Wi-Fi Setup</h3>
<p class="text-muted">Enter your home Wi-Fi details.</p>
<form method="post">
  <div class="mb-3"><label class="form-label">Country code</label>
    <input name="cc" class="form-control" value="US" maxlength="2" required></div>
  <div class="mb-3"><label class="form-label">Wi-Fi SSID</label>
    <input name="ssid" class="form-control" placeholder="MyNetwork" required></div>
  <div class="mb-3"><label class="form-label">Password</label>
    <input name="psk" type="password" class="form-control" placeholder="••••••••"></div>
  <button class="btn btn-primary" type="submit">Save & Connect</button>
</form>
<hr><p class="small text-muted mb-0">If connection fails, the setup network will return.</p>
</div>'''

@app.route("/", methods=["GET","POST"])
def index():
    if request.method=="POST":
        cc=(request.form.get("cc") or "US").strip()[:2].upper()
        ssid=(request.form.get("ssid") or "").strip()
        psk =(request.form.get("psk")  or "").strip()
        if not ssid: return HTML
        os.system('nmcli connection delete home-wifi >/dev/null 2>&1 || true')
        os.system(f'nmcli connection add type wifi ifname wlan0 con-name home-wifi ssid "{ssid}" >/dev/null 2>&1')
        if psk:
            os.system('nmcli connection modify home-wifi wifi-sec.key-mgmt wpa-psk')
            os.system(f'nmcli connection modify home-wifi wifi-sec.psk "{psk}"')
        os.system('nmcli connection modify home-wifi connection.autoconnect yes connection.autoconnect-priority 100')
        open("/etc/wpa_supplicant/wpa_supplicant.conf","w").write(f"country={cc}\n")
        os.system("chmod 600 /etc/wpa_supplicant/wpa_supplicant.conf || true")
        show("Connecting to Wi-Fi…")
        open(PORTAL_DONE,"w").close()
        return "<h3>Saved! Rebooting to join Wi-Fi…</h3>"
    show("Open: http://10.10.10.10/")
    return HTML

if __name__=="__main__":
    app.run(host="10.10.10.10", port=80)
