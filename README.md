# RetroRadio (Pi Zero W • PCM5102A • PAM8406)

A modern, headless MP3 “radio” that feels vintage:
- Two knobs: amp power/volume + rotary encoder select/click
- OLED shows the station (playlist) name
- I²S DAC (PCM5102A) → PAM8406 5W x2 amp → 2" speakers
- NetworkManager onboarding hotspot with 6-digit pass
- Web UI to add/delete stations, upload tracks, choose EQ presets
- Amp-off pause with fade, OLED auto-off after 60s, resume on amp-on

## Quick start
```bash
# On a fresh Raspberry Pi OS Lite (Bookworm)
sudo apt-get update
sudo apt-get install -y git
git clone https://github.com/HarvAlarv/retro-radio.git
cd retro-radio
sudo bash install.sh
```
The system will install services and reboot.

## First boot (no Wi-Fi)
- OLED shows:
  ```
  Join Wi-Fi: RetroRadio
  Pass: 123456
  ```
- Join that SSID from your phone, visit: `http://10.10.10.10/` (or `http://RetroRadio/`)
- Enter your home Wi-Fi. The Pi reboots, joins Wi-Fi, and the radio starts.
- Web UI is on `http://<pi-ip>:8080/` → **Stations** / **EQ Settings**

## Hardware pins (Pi Zero W)
- PCM5102A (I²S): 3V3→VIN, GND→GND, GPIO18→BCK, GPIO19→LRCK, GPIO21→DIN
- PAM8406: L/R from DAC line-out; speaker outputs to your 2" drivers
- Rotary encoder: A=GPIO16, B=GPIO20, Button=GPIO21 (change if needed)
- OLED: I²C @ 0x3C (enable I²C)
- Amp sense: GPIO23 (via divider/optocoupler from amp’s switched rail)

## Safety & notes
- Keep speaker wires twisted/short (Class D mode recommended)
- Common ground between Pi, DAC, amp
- Station folders: `/home/pi/music/01`…`/home/pi/music/99` (numbers internal)
