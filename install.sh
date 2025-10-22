#!/usr/bin/env bash
# RetroRadio installer (user-agnostic, Bookworm-safe, idempotent)
set -euo pipefail

# --- User/home detection (works with/without sudo) ---------------------------
RADIO_USER="${RADIO_USER:-${SUDO_USER:-$USER}}"
RADIO_HOME="$(getent passwd "$RADIO_USER" | cut -d: -f6)"
if [ -z "${RADIO_HOME:-}" ] || [ ! -d "$RADIO_HOME" ]; then
  echo "Error: target user '$RADIO_USER' not found or has no home dir" >&2
  exit 1
fi

# Paths (do NOT hardcode /home/pi)
USER_NAME="$RADIO_USER"
USER_HOME="$RADIO_HOME"
MUSIC_ROOT="${USER_HOME}/music"
WEB_ROOT="${USER_HOME}/webapp"
PORTAL_DIR="${USER_HOME}/portal"

echo "[1/12] System packages"
sudo apt-get update
sudo apt-get install -y \
  network-manager python3-pip python3-flask python3-pil python3-smbus \
  python3-gpiozero i2c-tools mpd mpc alsa-utils ladspa-sdk rsync

echo "[2/12] Enable I2C & NetworkManager"
# Safe even if already enabled
sudo raspi-config nonint do_i2c 0 || true
sudo systemctl enable NetworkManager
sudo systemctl disable wpa_supplicant || true
sudo systemctl stop wpa_supplicant || true

echo "[3/12] Python libs"
# PEP 668-safe: do NOT invoke pip for luma.oled globally
echo "Skipping luma.oled (already installed system-wide)"

echo "[4/12] I2S DAC overlay (PCM5102A default)"
# Keep onboard audio on to avoid card index churn; overlay the simple I2S DAC (hifiberry-dac)
sudo sed -i 's/^dtparam=audio=.*/dtparam=audio=on/' /boot/config.txt
if ! grep -q '^dtoverlay=hifiberry-dac' /boot/config.txt; then
  echo 'dtoverlay=hifiberry-dac' | sudo tee -a /boot/config.txt >/dev/null
fi
# Ensure no user-specific ~/.asoundrc that could override our system ALSA
sudo rm -f "${USER_HOME}/.asoundrc" || true

echo "[5/12] Folders, defaults"
sudo -u "${USER_NAME}" mkdir -p "${MUSIC_ROOT}"/{01,02,03,04,05}
sudo -u "${USER_NAME}" mkdir -p "${WEB_ROOT}/templates" "${PORTAL_DIR}/templates"
if [ ! -f "${MUSIC_ROOT}/stations.json" ]; then
  sudo -u "${USER_NAME}" tee "${MUSIC_ROOT}/stations.json" >/dev/null <<'JSON'
{ "01":"Classics","02":"Synthwave","03":"Lo-Fi","04":"Podcasts","05":"Jazz" }
JSON
fi

echo "[6/12] ALSA (EQ presets)"
sudo install -m 0644 -o root -g root config/asound.conf /etc/asound.conf

echo "[7/12] MPD config"
# Prepare MPD state dirs/files & permissions before touching the service
sudo install -d -m 0755 -o mpd -g audio /var/lib/mpd /var/lib/mpd/playlists
sudo install -d -m 0755 -o mpd -g audio /run/mpd
# log dir group may be 'adm' on Debian; fall back to audio if needed
if ! sudo install -d -m 0755 -o mpd -g adm /var/log/mpd 2>/dev/null; then
  sudo install -d -m 0755 -o mpd -g audio /var/log/mpd
fi
sudo touch /var/lib/mpd/tag_cache /var/lib/mpd/state /var/lib/mpd/sticker.sql
sudo chown mpd:audio /var/lib/mpd/tag_cache /var/lib/mpd/state /var/lib/mpd/sticker.sql

# Write a minimal, safe /etc/mpd.conf (Unix line endings; device left default)
sudo tee /etc/mpd.conf >/dev/null <<EOF
music_directory         "${MUSIC_ROOT}"
playlist_directory      "/var/lib/mpd/playlists"
db_file                 "/var/lib/mpd/tag_cache"
log_file                "/var/log/mpd/mpd.log"
pid_file                "/run/mpd/pid"
state_file              "/var/lib/mpd/state"
sticker_file            "/var/lib/mpd/sticker.sql"

user                    "mpd"
bind_to_address         "any"
port                    "6600"

audio_output {
    type            "alsa"
    name            "RetroRadio DAC"
    mixer_type      "software"
}

filesystem_charset      "UTF-8"
id3v1_encoding          "UTF-8"
EOF
# Strip any stray CRs (safety)
sudo sed -i 's/\r$//' /etc/mpd.conf

# Prefer service mode and keep the socket out of the way (Debian often re-enables it)
sudo systemctl stop mpd.service mpd.socket || true
sudo systemctl disable --now mpd.socket || true
sudo systemctl mask mpd.socket || true
sudo systemctl daemon-reload
sudo systemctl enable mpd.service
sudo systemctl restart mpd.service || true
# Build DB (don’t fail if empty)
mpc update || true

echo "[8/12] Web app + portal"
sudo -u "${USER_NAME}" rsync -a webapp/ "${WEB_ROOT}/"
sudo -u "${USER_NAME}" rsync -a portal/ "${PORTAL_DIR}/"

echo "[9/12] Services"
# Install unit files
sudo install -m 0644 services/station-radio.service /etc/systemd/system/
sudo install -m 0644 services/radio-web.service /etc/systemd/system/
sudo install -m 0644 services/radio-netcheck.service /etc/systemd/system/
sudo install -m 0644 services/radio-portal.service /etc/systemd/system/
sudo install -m 0644 services/eq-apply.service /etc/systemd/system/
sudo install -m 0644 services/amp-monitor.service /etc/systemd/system/

# Patch unit files to use correct user/home (avoid baked-in 'pi' or /home/pi)
for UNIT in /etc/systemd/system/*.service; do
  sudo sed -i "s#^User=pi#User=${USER_NAME}#g" "$UNIT"
  sudo sed -i "s#^Group=pi#Group=${USER_NAME}#g" "$UNIT"
  sudo sed -i "s#/home/pi#${USER_HOME//\//\\/}#g" "$UNIT"
done

sudo systemctl daemon-reload
sudo systemctl enable station-radio.service eq-apply.service radio-netcheck.service amp-monitor.service
# Do not start portal/web here—net may be reconfiguring; leave units to start on boot or by dependency.

echo "[10/12] Scripts"
sudo install -m 0755 scripts/station_radio.py "${USER_HOME}/station_radio.py"
sudo install -m 0755 scripts/amp_monitor.py    "${USER_HOME}/amp_monitor.py"
sudo chown "${USER_NAME}:${USER_NAME}" "${USER_HOME}/station_radio.py" "${USER_HOME}/amp_monitor.py"

echo "[11/12] NetworkManager captive DNS"
if ! grep -q '^dns=dnsmasq' /etc/NetworkManager/NetworkManager.conf 2>/dev/null; then
  sudo tee -a /etc/NetworkManager/NetworkManager.conf >/dev/null <<'CONF'
[main]
dns=dnsmasq
CONF
fi
sudo mkdir -p /etc/NetworkManager/dnsmasq.d
echo 'address=/RetroRadio/10.10.10.10' | sudo tee /etc/NetworkManager/dnsmasq.d/retro-radio.conf >/dev/null
sudo systemctl restart NetworkManager || true

echo "[12/12] Default EQ preset"
echo "EQ Warm" | sudo tee /var/local/eq_preset >/dev/null
sudo mpc enableonly "EQ Warm" || true

echo "Done. Rebooting..."
sleep 2
sudo reboot
