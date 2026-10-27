# R2-D2: a Raspberry Pi 4 + SunFounder PiCar-X robot with a Claude brain

The car body is a SunFounder PiCar-X (camera, ultrasonic sensor, grayscale sensor,
and a speaker on the Robot HAT). Robot HAT V5 also has a microphone; V4 does not,
so a V4 car (like ours) needs a USB microphone, picked by name with `MIC_NAME`
in `robo/config.py`. The version is printed on the HAT. The brain is this Python package. It
listens for "Hey R2-D2", sends what you said to Claude, Claude looks through the
camera tool and drives the car through a small set of tools.

**No extra cost.** Max plans include a monthly API credit ($100 on Max 5x) that covers the
Messages API and the Agent SDK. Put an API key from the Console organisation linked to the
plan in `~/.robo.env` as `ANTHROPIC_API_KEY=...` (never in the repo) and the robot spends
that credit. Two interchangeable brains share the same tools, prompt and safety wrapper:

| Brain | Used when | Speed |
|---|---|---|
| `DirectBrain` (`robo/brain_api.py`), the Messages API | `ANTHROPIC_API_KEY` is set (default) | fastest, no extra process |
| `Brain` (`robo/brain.py`), the Claude Agent SDK | no key, or `ROBO_BRAIN=agent`; uses the Claude Code login | a little slower |

`ROBO_BRAIN=api|agent|auto` forces a choice. Both brains run the tools in `robo/tools.py`,
so a new tool is written once.

## Layout

| Path | What it is |
|---|---|
| `robo/config.py` | Name, wake words, personality, voice, language, model, safety limits. Edit this first. |
| `robo/car.py` | `Car`: thin safe wrapper over `picarx.Picarx`. `MockCar` for the Mac. |
| `robo/camera.py` | One function: `snapshot()` returns JPEG bytes from the vilib camera. |
| `robo/voice.py` | `listen()` (Moonshine for the words, Vosk for the name and "stop", both on the Pi) and `say()` (Piper, a voice made on the Pi itself; the online Edge voice "Sonia" and espeak-ng as fallbacks). Keyboard fallback. |
| `robo/brain.py` | The system prompt, the 22 tool schemas, and the Agent SDK brain. `robo/brain_api.py` is the default Messages API brain; both run the tools in `robo/tools.py`. |
| `robo/family.example.yaml` | Example household: who lives here, house rules, and the games the robot can offer. Copy it to `robo/family.yaml` (git-ignored) and make it yours. |
| `robo/face.py` | Eyes and mouth on a 0.96 inch I2C OLED. Claude can show a feeling with the `express` tool. |
| `robo/main.py` | The assistant loop: wake word (or `--button` push-to-talk on HAT pin D0), listen, think, act, speak. |
| `robo.service` | systemd unit so the assistant starts on boot; `setup_pi.sh` installs it for your user. |
| `tests/` | Safety and plumbing tests: `python -m unittest -v`. Lint with `ruff check .` (config in `pyproject.toml`). |
| `programs/` | Standalone programs, numbered in the order to try them. |

## Run on the Mac first (no hardware, no cost)

```bash
git clone https://github.com/praneeth-goparaju/r2d2-claude-robot.git && cd r2d2-claude-robot
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python programs/01_drive_test.py --mock
python programs/05_talk.py --mock --keyboard        # needs Claude Code logged in on the Mac
```

Put any room photo at `tests/mock_view.jpg` and that is what Claude "sees" in mock mode.

`--mock` swaps the car, camera and microphone for fakes. `--keyboard` types instead
of speaking. Both flags work on the Pi too, which is how you debug the brain
without the car driving off the table.

## Set up the Pi (once the PiCar-X is assembled)

1. Flash **Raspberry Pi OS (64-bit)** with Raspberry Pi Imager: the recommended
   entry, Debian 13 "Trixie", which is what SunFounder's current PiCar-X 2.0 docs
   use. They warn against 32-bit. In Imager's settings set hostname `r2d2`,
   enable SSH, and enter the Wi-Fi password. Then `ssh <user>@r2d2.local`.
2. Clone the repo on the Pi into `~/robo-picarx` (the start-at-boot service
   expects that folder name):
   ```bash
   git clone https://github.com/praneeth-goparaju/r2d2-claude-robot.git ~/robo-picarx
   ```
   Then run the setup script. It installs SunFounder's `robot-hat`, `vilib` and
   `picar-x`, this project's requirements and the Vosk speech model, and creates
   the key file. Reboot when it is done:
   ```bash
   cd ~/robo-picarx && bash setup_pi.sh
   ```
3. Create an API key in the Console organisation linked to your Max plan
   (claude.ai → Settings → Billing → monthly API credits; ideally a separate
   workspace "robo" with a monthly spend limit) and paste it into `~/.robo.env`
   on the Pi as `ANTHROPIC_API_KEY=...`. The setup script creates the file.
   Alternative: run `claude` over SSH and log in with the Max account.
4. Once the Robot HAT is mounted: `cd ~/robot-hat && sudo bash i2samp.sh`, then
   reboot. If there is no sound, `robot_hat doctor` says which part is broken.
   Run SunFounder's `sudo python3 servo_zeroing.py` **before** assembling the servos.
5. Calibrate on the real car with SunFounder's scripts, so straight is straight
   and the edge stop works on your floor:
   `cd ~/picar-x/example && sudo python3 1.cali_servo_motor.py` (steering, camera,
   motor direction), then `sudo python3 1.cali_grayscale.py` over black tape and
   lifted in the air (cliff reference).
6. Sound on the Robot HAT needs root: run programs with `sudo -E python3 ...`
   (`-E` keeps the environment variable).
   For German, download `vosk-model-small-de-0.15` into `models/` the same way
   and set `LANGUAGE = "de"` in `robo/config.py`.

## Google voice and ears (optional, recommended)

With a Google Cloud key the robot speaks with Google's voice and Google writes
down what it is asked: quicker than the Pi and dependable. Claude stays the
brain. Without the key it uses the free Microsoft voice and Moonshine on the Pi,
as before. Only speech meant for the robot goes to Google: what follows its
name, the answer after "Yes?", and what is said during a conversation.

1. At https://console.cloud.google.com create a project (e.g. "robo") and add a
   billing account. The voice is free up to 1 million characters a month; the
   ears cost about $0.016 to $0.024 per minute of speech, a few dollars a month.
   Set a budget alert under Billing → Budgets if you like.
2. Under APIs & Services → Library switch on **Cloud Text-to-Speech API** and
   **Cloud Speech-to-Text API**.
3. Under APIs & Services → Credentials → Create credentials → API key. Edit the
   key: under "API restrictions" pick only those two APIs.
4. On the Pi, add the line `GOOGLE_API_KEY=<the key>` to `~/.robo.env` and
   restart the robot (`systemctl --user restart robo`). The self-check at
   start says "Google speech: key works", or what Google objected to.

The voice is `GOOGLE_VOICE` in `robo/config.py`; `VOICE_ENGINE = "edge"` and
`LISTEN_ENGINE = "moonshine"` switch back to the old ones.

## Programs

| Program | What it does | Needs |
|---|---|---|
| `00_self_check.py` | The robot tests its own battery, sensors, camera, ears, internet, voice, temperature and disk, and says what works. Run first. | car |
| `01_drive_test.py` | Forward, back, steer, pan the camera, print distance. Proves the body works. | car |
| `02_say_hello.py` | Speaks a sentence, then echoes back what you say. Proves audio in and out. | car, mic |
| `03_what_do_you_see.py` | One photo, one Claude call, spoken description. First brain test. | car, camera, login |
| `04_patrol.py` | Roams with obstacle and cliff stops for N seconds, then Claude summarises what the camera saw. No Claude in the control loop. | car, camera, login |
| `05_talk.py` | The full assistant: "Hey R2-D2", then talk; Claude drives, looks and answers. | everything |
| `06_controller_drive.py` | Drive with the Xbox controller over Bluetooth without Claude, camera on the right stick, A takes a photo. Pair it once with `bluetoothctl`; `--axes` shows which stick is which. The talking robot (`05_talk.py`) can be driven with the controller too. | car, controller |

Every program takes `--mock` and, where it listens, `--keyboard`.

## Safety limits (robo/config.py)

- Speed is capped at `MAX_SPEED` (default 40 of 100) and any single move at `MAX_MOVE_SECONDS` (default 3).
- There is no rear sensor, so reversing is capped at `REVERSE_MAX_SPEED` (30) and `REVERSE_MAX_SECONDS` (1.5).
- Forward motion polls the ultrasonic sensor and stops below `STOP_DISTANCE_CM` (default 25). No reading at all counts as an obstacle.
- Say "stop" (or press the push-to-talk button) while the robot is busy and the motors stop at once, without waiting for Claude.
- Any motion stops when the grayscale sensor reports a cliff.
- Claude never gets a raw motor call. It only gets the tools in `robo/tools.py`.
- The camera's live web view (port 9000) has no password, so it is off unless `CAMERA_WEB_VIEW = True`.
- Old photos, voice clips and diary days are deleted automatically (`KEEP_SNAPSHOTS`, `KEEP_TTS_FILES`, `KEEP_DIARY_DAYS`).
- `MAX_TURNS_PER_DAY` (default 120) stops the robot answering after that many spoken turns in a day, so the kids cannot use up the Claude plan.
- Night mode (`NIGHT_START` 20:00 to `NIGHT_END` 07:00): the voice drops by a third, replies are one soft sentence, and the car refuses to drive.
- Below 7,15 V battery (where the Robot HAT's battery LEDs go dark) the robot is "hungry" and every move is cut to 1 second; below 6,8 V the car refuses to drive. Both are enforced in `robo/car.py`, not left to Claude.
- The camera turns at most ±35° left and right (`CAM_PAN_LIMIT`), the range SunFounder's own examples use. A servo pushed past its stop stalls and snaps back to centre.
- The ultrasonic sensor (2 to 400 cm) only sees flat things of about half a square metre or more; legs, toys and cushions can be invisible to it. The cliff stop and the speed and time caps are the safety net for those.

## Personality

- `robo/family.yaml` (copied from `robo/family.example.yaml`): who lives here, house rules, the games it offers.
- The face blinks, follows the camera, and moves its mouth while talking. Previews in `docs/faces/`.
- Say "can I call you Ziggy?" and after a yes the robot renames itself; the new wake word is "hey Ziggy" and it survives restarts. Delete `state.json`, or ask to be called R2-D2 again, to go back.
- "How was your day?" or "good night" makes it tell the three best moments from its diary.
- "Hey R2-D2, how do you work?" or "how do your eyes work?": it explains itself truthfully at the listener's level (5, 10 or grown-up).
- "Hey R2-D2, are you okay?": it runs a self-check and says what works and what needs help. It also checks itself at startup.
- Tricks: nod, shake, wiggle, peekaboo, bow, twirl, look around. It answers yes/no questions with a nod or a shake.
- Dance: plays its own tune, wiggles wheels and head to the beat, bows.
- Music games: Freeze Dance (it stops the music without warning and checks the camera for anyone still moving), Copy My Dance (a growing sequence of moves, each with its own note, to copy) and Name That Tune (it plays and dances to the start of a song for you to guess).
- Dramatic sounds: drumroll, suspense, ticking, fanfare, sad trombone, spooky, heartbeat, countdown and record scratch, for games and stories.
- Silly voices: robot, giant, chipmunk, sleepy, excited, for stories and on request.
- Birthdays in `robo/family.yaml`: on the day it sings Happy Birthday once and shows hearts.
- Idle curiosity: left alone, it looks around, nods or hums every minute or so. Never at night.
- Games added: Story time with sound effects and character voices, Simon says, Silly voices.

## Make it yours

Two things are personal and stay on your Pi, never in the repo:

1. **Your household.** Copy the example and edit it:
   `cp robo/family.example.yaml robo/family.yaml`. Without it the robot uses the example family.
2. **Where you live,** for weather and pollen. Add to `~/.robo.env`:
   ```
   ROBO_PLACE=Your Town
   ROBO_LAT=52.52
   ROBO_LON=13.41
   ```
   Without these lines it reports the weather for Berlin.

## Licence

MIT, see `LICENSE`.
