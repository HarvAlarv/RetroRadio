#!/usr/bin/env bash
set -euo pipefail

USER_NAME="pi"
USER_HOME="/home/${USER_NAME}"
MUSIC_ROOT="${USER_HOME}/music"
WEB_ROOT="${USER_HOME}/webapp"
PORTAL_DIR="${USER_HOME}/portal"

echo "[1/12] System packages"
sudo apt-get update
sudo apt-get install -y network-manager python3-pip python3-flask python3-pil python3-smbus \
  python3-gpiozero i2c-tools mpd mpc alsa-utils ladspa-sdk rsync

echo "[2/12] Enable I2C & NetworkManager"
sudo raspi-config nonint do_i2c 0 || true
sudo systemctl enable NetworkManager
sudo systemctl disable wpa_supplicant || true
sudo systemctl stop wpa_supplicant || true

echo "[3/12] Python libs"
sudo pip3 install --no-input luma.oled

echo "[4/12] I2S DAC overlay (PCM5102A)"
sudo sed -i 's/^dtparam=audio=.*/dtparam=audio=on/' /boot/config.txt
if ! grep -q '^dtoverlay=hifiberry-dac' /boot/config.txt; then
  echo 'dtoverlay=hifiberry-dac' | sudo tee -a /boot/config.txt >/dev/null
fi
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
sudo install -m 644 -o root -g root config/asound.conf /etc/asound.conf

echo "[7/12] MPD config"
sudo systemctl stop mpd || true
sudo install -m 644 -o root -g root config/mpd.conf /etc/mpd.conf
sudo mkdir -p "${USER_HOME}/.mpd" && sudo chown -R "${USER_NAME}:${USER_NAME}" "${USER_HOME}/.mpd"
sudo systemctl enable mpd
sudo systemctl restart mpd

echo "[8/12] Web app + portal"
sudo -u "${USER_NAME}" rsync -a webapp/ "${WEB_ROOT}/"
sudo -u "${USER_NAME}" rsync -a portal/ "${PORTAL_DIR}/"

echo "[9/12] Services"
sudo install -m 644 services/station-radio.service /etc/systemd/system/
sudo install -m 644 services/radio-web.service /etc/systemd/system/
sudo install -m 644 services/radio-netcheck.service /etc/systemd/system/
sudo install -m 644 services/radio-portal.service /etc/systemd/system/
sudo install -m 644 services/eq-apply.service /etc/systemd/system/
sudo install -m 644 services/amp-monitor.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable station-radio.service eq-apply.service radio-netcheck.service amp-monitor.service

echo "[10/12] Scripts"
sudo install -m 755 scripts/station_radio.py "${USER_HOME}/station_radio.py"
sudo install -m 755 scripts/amp_monitor.py "${USER_HOME}/amp_monitor.py"
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
sudo systemctl restart NetworkManager

echo "[12/12] Default EQ preset"
echo "EQ Warm" | sudo tee /var/local/eq_preset >/dev/null
sudo mpc enableonly "EQ Warm" || true
echo "Done. Rebooting…"
sleep 2
sudo reboot
