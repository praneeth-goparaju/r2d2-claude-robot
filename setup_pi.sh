#!/usr/bin/env bash
# One-shot setup for a fresh Raspberry Pi OS (64-bit, Debian 13 "Trixie") install.
# Run as the normal user (not root): bash setup_pi.sh. Takes 15 to 30 minutes on a Pi 4.
# Steps 2 to 4 are SunFounder's own install commands for PiCar-X 2.0
# (docs.sunfounder.com/projects/picar-x-v20, "Install All the Modules").
# Safe to run again: finished steps are skipped or repeated without harm.
set -euo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"   # wherever this repo was cloned
cd ~

echo "== 1. system packages"
sudo apt update && sudo apt full-upgrade -y
# python3-lgpio, -smbus2 and -pygame: robot-hat refuses to import without them and
# its install.py does not install lgpio. espeak-ng is the offline voice. pygame is
# also what the controller program uses.
sudo apt install -y git python3-pip python3-setuptools python3-dev python3-smbus python3-smbus2 \
    python3-lgpio python3-spidev python3-pygame python3-pyaudio portaudio19-dev \
    unzip wget curl mpg123 espeak-ng rfkill

echo "== 2. SunFounder robot-hat 2.5.x"
[ -d robot-hat ] || git clone -b 2.5.x https://github.com/sunfounder/robot-hat.git --depth 1
(cd robot-hat && sudo python3 install.py)

echo "== 3. SunFounder vilib (camera)"
[ -d vilib ] || git clone https://github.com/sunfounder/vilib.git --depth 1
(cd vilib && sudo python3 install.py)

echo "== 4. SunFounder picar-x 2.1.x"
[ -d picar-x ] || git clone -b 2.1.x https://github.com/sunfounder/picar-x.git --depth 1
(cd picar-x && sudo pip3 install . --break-system-packages)
# SunFounder's installers print their errors and still exit 0, so check here.
python3 -c "from robot_hat import Pin; import picarx" \
    || { echo "!! SunFounder libraries do not import. Scroll up for the installer's errors, or run: robot_hat doctor"; exit 1; }

echo "== 5. this project"
cd "$REPO"
# --ignore-installed: on Trixie pip cannot replace the older copies of
# typing-extensions and jsonschema that apt installed, and stops with
# "uninstall-no-record-file". With this flag the newer ones go to /usr/local.
sudo pip3 install -r requirements.txt --break-system-packages --ignore-installed
# The better speech recognizer. --no-deps: its package also lists numba and librosa,
# large packages that only its own file loader uses. onnxruntime came with piper-tts.
sudo pip3 install tokenizers huggingface-hub --break-system-packages \
    && sudo pip3 install useful-moonshine-onnx --no-deps --break-system-packages \
    || echo "   Moonshine not installed; the robot will use the small Vosk recognizer"
sudo pip3 install luma.oled --break-system-packages \
    || echo "   luma.oled not installed; only the optional face screen needs it"

echo "== 6. Vosk speech model (English, small)"
mkdir -p models && cd models
if [ ! -d vosk-model-small-en-us-0.15 ]; then
  rm -f vosk-model-small-en-us-0.15.zip   # a download cut off by an earlier run
  wget -q https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip
  unzip -q vosk-model-small-en-us-0.15.zip && rm vosk-model-small-en-us-0.15.zip
fi
cd "$REPO"
# The voice the robot speaks with, made on the Pi itself (about 63 MB). PIPER_VOICE in robo/config.py.
if [ ! -f models/piper/en_GB-cori-medium.onnx ]; then
  mkdir -p models/piper
  python3 -m piper.download_voices en_GB-cori-medium --data-dir models/piper \
      || echo "   voice not downloaded; the robot will use the online voice until it is"
fi

# The model for the better recognizer (about 250 MB), fetched once into models/huggingface.
HF_HOME="$REPO/models/huggingface" python3 -c "from moonshine_onnx import MoonshineOnnxModel; MoonshineOnnxModel(model_name='moonshine/base')" \
    || echo "   recognizer model not downloaded; it is fetched the first time the robot starts"

echo "== 7. Claude: an API key (default), or the Claude Code login as the fallback"
if ! command -v claude >/dev/null 2>&1; then
  curl -fsSL https://claude.ai/install.sh | bash || echo "   Claude Code not installed; the API key still works"
  export PATH="$HOME/.local/bin:$PATH"
fi
claude --version || echo "   claude not on PATH yet: open a new shell"
if [ ! -f ~/.robo.env ]; then
  # Commented out on purpose: an example value would make the robot try a fake key
  # instead of falling back to the Claude Code login.
  echo "# ANTHROPIC_API_KEY=paste-the-key-from-your-Console-org-here" > ~/.robo.env
  echo "# GOOGLE_API_KEY=paste-your-google-key-here   (optional: README, Google voice and ears)" >> ~/.robo.env
  chmod 600 ~/.robo.env
fi
echo "   put ANTHROPIC_API_KEY=<your key> in ~/.robo.env (key from the Console org linked to your Max plan)"
echo "   (or, without a key: run  claude  once and log in with the Max account)"

echo "== 8. start on boot (systemd), for user $USER"
# two steps through placeholders, so a home folder that itself starts with
# /home/pi (pieter, pi4) is not substituted a second time
sed -e "s#/home/pi/robo-picarx#@REPO@#g" -e "s#/home/pi#@HOME@#g" \
    -e "s#@REPO@#$REPO#g" -e "s#@HOME@#$HOME#g" robo.service | sudo tee /etc/systemd/system/robo.service >/dev/null
sudo systemctl daemon-reload
echo "   enable it once the car works:  sudo systemctl enable --now robo"
echo "   or, on a Pi that logs its user in by itself (Raspberry Pi OS with desktop), without sudo:"
echo "     mkdir -p ~/.config/systemd/user && cp $REPO/robo-user.service ~/.config/systemd/user/robo.service"
echo "     systemctl --user daemon-reload && systemctl --user enable --now robo"
echo "   (one or the other, not both; see the top of robo-user.service)"

cat <<'MSG'

== done with the software. First:  sudo reboot
   Then these steps need the car itself:
   a) with the Robot HAT mounted and the batteries switched on:
        cd ~/robot-hat && sudo bash i2samp.sh
      (answer y, reboot; if silent, run it again, SunFounder says up to several times)
        robot_hat doctor        (says which part of the sound path is broken)
   b) servo zeroing BEFORE assembly:
        cd ~/picar-x/example && sudo python3 servo_zeroing.py
   c) once assembled, calibrate:
        cd ~/picar-x/example
        sudo python3 1.cali_servo_motor.py   (steering, camera, motor direction)
        sudo python3 1.cali_grayscale.py     (line and cliff reference, for the edge stop)
   d) Robot HAT V4 has no microphone: plug in a USB one (V5 has one on board)
   e) the Xbox controller, once:  bluetoothctl   then: scan on, pair, trust, connect
      If it connects and drops off again after a few seconds, put these in
      /etc/bluetooth/main.conf, then: sudo systemctl restart bluetooth, remove and pair again:
        under [General]:  JustWorksRepairing = always   FastConnectable = true   Privacy = device
        under [LE]:       MinConnectionInterval=7   MaxConnectionInterval=9   ConnectionLatency=0
      If "power on" fails in bluetoothctl, Bluetooth is blocked:  sudo rfkill unblock bluetooth
MSG
echo "   then:  cd $REPO && sudo -E python3 programs/00_self_check.py"
