# Setting up your robot

This guide goes from an empty box to a robot that answers "Hey R2-D2". The
install script asks what you want first (which Claude account, which voice,
which language, your town, your family), then installs everything without
stopping. Plan an evening: about an hour to build the car, 30 minutes for the
install, 15 minutes to calibrate.

## What you need

| | |
|---|---|
| **Car** | SunFounder PiCar-X 2.0 kit (Robot HAT, camera, distance and floor sensors, motors, servos), with the batteries SunFounder's kit list asks for |
| **Computer on the car** | Raspberry Pi 4 and a microSD card of 32 GB or more |
| **Microphone** | Robot HAT V5 has one. Robot HAT V4 has none: a small USB microphone. The version is printed on the board. |
| **Claude** | An Anthropic API key from [console.anthropic.com](https://console.anthropic.com), or a Claude account you can log in to Claude Code with |
| **Optional** | A Google Cloud key for the better voice and ears; a 0.96 inch SSD1306 OLED screen for the face; an Xbox controller to drive by hand |
| **To set it up** | A computer on the same Wi-Fi, to flash the card and to connect to the Pi with `ssh` |

## Pick your setup

The install script asks these questions. Every one has a default, so pressing
Enter always works, and `python3 setup_questions.py` changes an answer later.

| Question | Choices | What changes |
|---|---|---|
| Claude, the brain | **API key** (quickest), or **Claude Code login** (press Enter, then run `claude` once on the Pi and log in) | Where the answers come from and who pays for them |
| Voice and ears | **Google Cloud key**, or **none** | With the key: Google's voice, and Google writes down what it hears (quicker, better with children, a few dollars a month). Without: a free voice and a recognizer on the Pi |
| Language | **en** or **de** | What the robot speaks and listens for. German downloads one more speech model and voice |
| Robot HAT version | **4** or **5** | V4 listens through the USB microphone, V5 through its own |
| Town | Any town or city | The weather and pollen it reports. The script finds the coordinates for you |
| Your household | Names, who they are, a note, birthdays | Who Claude knows it is talking to, and whose birthday to sing for. Skip it and the robot uses the example family |
| Start at boot | **yes** or **no** | Whether the robot starts by itself when the Pi is switched on |

The answers go into `~/.robo.env` and `robo/family.yaml` on the Pi. Neither is
ever put into git, so your keys and your family stay on the robot.

## 1. Try it on your computer first (optional)

No car and no cost: the car, camera and microphone are replaced by fakes and you
type instead of speaking. You need a recent Python 3 (the Pi has 3.13) and Claude Code logged in.

```bash
git clone https://github.com/praneeth-goparaju/r2d2-claude-robot.git && cd r2d2-claude-robot
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python programs/05_talk.py --mock --keyboard
```

## 2. Build the car

Follow SunFounder's PiCar-X 2.0 assembly instructions. One thing to do **before**
the servos go on: set them to their middle position with SunFounder's
`servo_zeroing.py`, which step 4 installs. If you build first, take the servo
arms off again afterwards and run it then.

## 3. Prepare the microSD card

1. Install [Raspberry Pi Imager](https://www.raspberrypi.com/software/) on your computer.
2. Choose **Raspberry Pi OS (64-bit)**, the recommended entry (Debian 13
   "Trixie"). Not the 32-bit one.
3. In Imager's settings: hostname `r2d2`, a user name and password, your Wi-Fi
   name and password, and **enable SSH**.
4. Write the card, put it in the Pi, switch the car on and wait two minutes.
5. From your computer: `ssh <your user>@r2d2.local`

## 4. Install

On the Pi:

```bash
sudo apt install -y git
git clone https://github.com/praneeth-goparaju/r2d2-claude-robot.git ~/robo-picarx
cd ~/robo-picarx && bash setup_pi.sh
```

Keep the folder name `~/robo-picarx`: the start-at-boot service looks for it.

The script asks the questions from "Pick your setup" first. Keys are typed
without showing on screen. Then it installs SunFounder's libraries, this
project, the speech models and Claude Code, which takes 15 to 30 minutes. When
it says it is done:

```bash
sudo reboot
```

## 5. Sound and calibration

Connect again with `ssh`, and with the batteries switched on:

1. **Sound.** `cd ~/robot-hat && sudo bash i2samp.sh`, answer `y`, reboot. If
   the speaker stays silent, run it again (SunFounder says it can take a few
   tries); `robot_hat doctor` says which part of the sound is broken.
2. **Servos**, if not done before building: `cd ~/picar-x/example && sudo python3 servo_zeroing.py`
3. **Steering, camera and motors**, so straight is straight:
   `cd ~/picar-x/example && sudo python3 1.cali_servo_motor.py`
4. **Floor sensors**, so the robot stops at the edge of a table or stairs:
   `sudo python3 1.cali_grayscale.py`, over the floor, then lifted in the air.

## 6. First run

```bash
cd ~/robo-picarx
sudo -E python3 programs/00_self_check.py
```

The robot checks its battery, sensors, camera, ears, internet and voice, and
says what works. Fix anything it names, then try the programs in order (the
README lists them). `03_what_do_you_see.py` is the first one that asks Claude,
so it proves the key or the login works. Then the full robot:

```bash
sudo -E python3 programs/05_talk.py
```

Say **"Hey R2-D2"**, wait for "Yes?", and talk. If you chose start at boot it
runs by itself from the next time the Pi starts.

## Change your answers later

```bash
cd ~/robo-picarx && python3 setup_questions.py
```

Then restart the robot: `systemctl --user restart robo` (Pi with the desktop) or
`sudo systemctl restart robo` (without). You can also edit `robo/family.yaml`
directly; `robo/family.example.yaml` shows everything it can hold, including
house rules and games. Settings such as speed limits, the voice and the
personality are in `robo/config.py`, each explained where it is set.

## When something goes wrong

| What happens | What to do |
|---|---|
| The install stops at "SunFounder libraries do not import" | Scroll up for SunFounder's error, or run `robot_hat doctor` |
| No sound | Run `sudo bash i2samp.sh` in `~/robot-hat` again and reboot; `robot_hat doctor` |
| It does not react to "Hey R2-D2" | Run the self check: it says whether the microphone was found. On a V4 HAT, check the USB microphone is plugged in, and that you answered 4 to the HAT question |
| `03_what_do_you_see.py` gets no answer from Claude | Add or fix the key with `python3 setup_questions.py`, or run `claude` once and log in |
| The robot drives crooked or will not drive near edges | Repeat the calibration in step 5 |
| The weather is for the wrong town | `python3 setup_questions.py`, question 5 |
| The Xbox controller connects and drops off | See the end of `setup_pi.sh`'s output for the Bluetooth settings that fix it |
| You want to see what it is doing | `journalctl --user -u robo -f` (or `sudo journalctl -u robo -f`); the newest run is also in `/tmp/talk.log` |
