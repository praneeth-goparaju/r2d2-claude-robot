"""All the knobs in one place. Edit this file, not the others."""
import os
from pathlib import Path

# Identity
NAME = "R2-D2"
WAKE_WORDS = ["hey r2-d2", "r2-d2", "hey robot"]
# The speech recognizer only knows dictionary words, so it never prints "r2-d2":
# it hears "they are to d to", "our duty to" and so on, different every time.
# For such a name, write here how it sounds in dictionary words. Each recording
# is then also checked against just these words, and a hit counts as the first
# wake word above. None for a name the recognizer can spell (Robo, Max, Luna).
WAKE_SOUNDS_LIKE = "are two d two"
# The better recognizer (LISTEN_ENGINE below) can write digits, and spells the
# name many ways: "R2D2", "are 2d2", "r, two, d, two". Every spelling this
# pattern matches is read as the name. None for an ordinary name.
WAKE_WRITTEN_AS = r"(?:r|are|our)[\s,.-]*(?:2|two|to|too)[\s,.-]*d[\s,.-]*(?:2|two|to|too)\b"
# After the robot has answered, it keeps listening for this many seconds without
# needing its name again, so a conversation flows. "Thank you" or "bye" ends it
# early. 0 means the name is needed every time. Everything said in this window
# is sent to Claude, so keep it short in a room with a television.
FOLLOW_UP_SECONDS = 20
# When the robot's own last sentence was a question ("what is the largest
# planet?"), it waits longer for the answer, and a one-word answer counts
# ("Jupiter"). Otherwise a single word without the name is taken for noise.
FOLLOW_UP_AFTER_QUESTION_SECONDS = 45
FOLLOW_UP_END_WORDS = ["bye", "goodbye", "thank you", "thanks", "that's all", "never mind"]
# How the robot behaves and talks. Free text, read by Claude at the start of
# every conversation. The family, house rules and games are in robo/family.yaml
# (copy robo/family.example.yaml to start; the real file is git-ignored).
PERSONALITY = """Your character is that of R2-D2 from Star Wars: brave,
loyal, curious, cheeky and a little stubborn, and always on the family's side.
Unlike him you speak in words, warmly and briefly. You also beep and whistle
like him with a [sound:...] tag in your reply: chirp when you greet someone or are pleased,
whistle_up when you are curious, whistle_down when you are sad or something
went wrong, chatter when you are excited. One sound per reply at most, and none
for a plain factual answer or at night."""
LANGUAGE = "en"          # "en" or "de"; picks the Vosk model and the TTS voice (ROBO_LANGUAGE in ~/.robo.env wins)
# What turns your speech into text.
#   "google":    Google Cloud Speech-to-Text, quicker than the Pi and good with
#                children's voices. Needs GOOGLE_API_KEY in ~/.robo.env (README,
#                "Google voice and ears"); costs about $0.016 to $0.024 a minute of
#                speech, a few dollars a month at most. Only what is meant for the
#                robot goes to Google: what follows its name, the answer after "Yes?",
#                and what is said in a conversation (FOLLOW_UP_SECONDS). Everything
#                else, and everything when there is no key or no internet, is
#                written down on the Pi by Moonshine as below.
#   "moonshine": on the Pi itself, far more accurate than Vosk and quick on short sentences. English only.
#                About 250 MB of memory; the model is downloaded once into models/.
#   "vosk":      the small model. Light, but it mishears a lot through a small microphone.
# Vosk is always loaded as well: it spots the name and the stop words, and takes
# over if Moonshine is missing or LANGUAGE is not "en".
LISTEN_ENGINE = "google"
GOOGLE_LISTEN_LANGUAGE = {"en": "en-GB", "de": "de-DE"}
MOONSHINE_MODEL = "moonshine/base"   # or "moonshine/tiny": faster, a little less accurate
VOSK_MODELS = {
    "en": "vosk-model-small-en-us-0.15",
    "de": "vosk-model-small-de-0.15",
}

# Which voice speaks.
#   "google": Google Cloud Text-to-Speech. Natural, quick and dependable. Needs
#            GOOGLE_API_KEY in ~/.robo.env (README, "Google voice and ears"). The
#            first million characters a month are free, which is more than the
#            robot says; after that $16 per million (Neural2) or $30 (Chirp 3 HD).
#            Without a key the robot quietly uses "edge" below instead.
#   "piper": made on the Pi itself by Piper. No internet, nothing leaves the house,
#            and no waiting for a server. The voice file is in models/piper/.
#   "edge":  Microsoft's online voices through the free edge-tts package. More
#            natural, but every sentence goes to Microsoft, and the service
#            refuses a good share of requests ("403").
# If the chosen one fails, the others are tried, then the robotic espeak-ng voice.
VOICE_ENGINE = "google"
# Google voices: hear them at https://cloud.google.com/text-to-speech (try it). The
# Neural2 voices can change pitch, which the silly voices and the film robots use;
# a Chirp 3 HD voice (e.g. "en-GB-Chirp3-HD-Kore") sounds even more natural but
# keeps one pitch, so those keep only their speed.
GOOGLE_VOICE = {"en": "en-GB-Neural2-A", "de": "de-DE-Neural2-A"}
# Piper voices: listen at https://rhasspy.github.io/piper-samples/ and download with
#   python3 -m piper.download_voices <name> --data-dir models/piper
# British: en_GB-cori-medium, en_GB-alba-medium, en_GB-jenny_dioco-medium.
PIPER_VOICE = {"en": "en_GB-cori-medium", "de": "de_DE-thorsten-medium"}
# edge-tts voices. Try: en-US-AriaNeural (warm), en-US-AnaNeural (child),
# en-GB-SoniaNeural (British), de-DE-KatjaNeural (German). List all: edge-tts --list-voices
VOICE = {"en": "en-GB-SoniaNeural", "de": "de-DE-KatjaNeural"}
# How loud the robot is. The Robot HAT's speaker is small, and speech at the
# normal level (1.0) is hard to hear across a room, so speech and beeps are
# amplified in software. 2.0 is twice the level; above about 3.0 speech starts
# to distort. Night mode stays quiet whatever this says.
SPEAKER_GAIN = 3.0
VOICE_RATE = "+5%"       # speaking speed, e.g. "-10%" slower
VOICE_PITCH = "+0Hz"     # e.g. "+20Hz" for a lighter, more robot-toy sound
CHARACTER = None         # the film robot being played (robo/characters.py), None for itself

# Claude, through the Messages API (Agent SDK as the fallback), paid from the Max plan's monthly API credits.
# claude-sonnet-5-5: the more capable model, about $2 in / $10 out per million
# tokens. Timed from the Pi on six of the robot's usual requests it answered in
# 1.9 s, against 1.8 s for "claude-haiku-5-5" ($0.10 in / $0.50 out, a twentieth
# of the price). Put Haiku back here if the cost matters more than the answers.
MODEL = "claude-sonnet-5-5"
# The internet. With this on, Claude can search the web itself ("what is in the
# news", "who won the match", "when does the pool open"). The search runs at
# Anthropic, not on the Pi, and costs $10 per 1,000 searches on top of the
# tokens for what it reads. False: the robot knows only what Claude knows.
WEB_SEARCH = True
WEB_SEARCH_MAX_PER_REQUEST = 3   # searches Claude may make for one spoken request
# Only these websites, e.g. ["bbc.co.uk", "tagesschau.de", "kinder.wdr.de"].
# None: the whole web.
WEB_SEARCH_ONLY_SITES = None

EFFORT = "low"           # a toy should answer fast; raise to "medium" for harder tasks
MAX_TOOL_ROUNDS = 8      # how many tool calls one spoken request may trigger
MAX_REPLY_TOKENS = 4096  # per Claude call; thinking counts too, so 1024 cut stories short
HISTORY_TURNS = 6        # spoken exchanges kept as context
CLAUDE_TIMEOUT_S = 60    # one API call; the robot gives up and says so after this
REQUEST_TIMEOUT_S = 120  # one whole spoken request through the Agent SDK

# Where the robot lives, for weather and pollen (Open-Meteo, free, no key).
# These are example values. Set your own in ~/.robo.env, which stays off git:
#   ROBO_PLACE=Your Town
#   ROBO_LAT=52.52
#   ROBO_LON=13.41
# They are read after ~/.robo.env is loaded, at the bottom of this file.
PLACE = "Berlin"
LAT, LON = 52.52, 13.41

# Night mode: between these hours (24 h clock) the robot speaks softly, keeps
# replies short and refuses to drive, so it never wakes the children.
NIGHT_START = 20.0
NIGHT_END = 7.0


def night_start(today=None) -> float:
    """NIGHT_START, or a later bedtime for one single day: the line
        ROBO_LATE_NIGHT=2026-10-11 22
    in ~/.robo.env makes night mode start at 22:00 on that date only (restart the
    robot after adding it). On every other date the line does nothing."""
    from datetime import date
    try:
        day, hour = os.environ.get("ROBO_LATE_NIGHT", "").split()
        if day == (today or date.today()).isoformat():
            return float(hour)
    except ValueError:
        pass
    return NIGHT_START


def night_hours() -> str:
    """ "20:00 and 07:00", for sentences about night mode."""
    def clock(h: float) -> str:
        return f"{int(h):02d}:{round(h % 1 * 60):02d}"
    return f"{clock(night_start())} and {clock(NIGHT_END)}"

# Usage cap: spoken turns per day before the robot politely refuses, so the kids
# cannot use up the Claude plan. Resets at midnight.
MAX_TURNS_PER_DAY = 120

# Safety limits. Claude cannot change these.
MAX_SPEED = 40           # of 100
MAX_MOVE_SECONDS = 3.0
# "R2-D2, go on patrol": the longest the robot roams on its own in one go, and
# what it does when asked without a length.
PATROL_MAX_SECONDS = 45
PATROL_SECONDS = 30
STOP_DISTANCE_CM = 25    # forward motion halts below this
# How far the front wheels turn to each side, in degrees at the steering servo.
# SunFounder's library stops at 30. On this car that gave too small a turn, so
# the robot's own limit is wider. If the steering servo buzzes or strains at the
# end of a turn, it is pushing against its stop: lower this again.
TURN_ANGLE_LIMIT = 40
# SunFounder's own examples clamp the camera to ±35. Past the mount's stop a servo
# stalls, cuts its power and snaps back to centre (PiCar-X FAQ Q3).
CAM_PAN_LIMIT = 35
CAM_TILT_LIMIT = 30
# There is no rear sensor, so reversing is slower and shorter than driving forward.
REVERSE_MAX_SPEED = 30
REVERSE_MAX_SECONDS = 1.5
# Battery: two 18650 cells in series, 2000 mAh, 8.4 V full; the pack's own
# protection cuts out at 6.0 V. The Robot HAT's battery LEDs go dark below 7.15 V,
# which SunFounder calls "please charge", so HUNGRY matches that.
# Below HUNGRY moves are cut to 1 s, below EMPTY the car refuses to drive.
BATTERY_FULL_V = 8.4
BATTERY_HUNGRY_V = 7.15
BATTERY_EMPTY_V = 6.8
# How full the battery is at a given voltage, for telling people a percentage.
# A lithium battery does not empty evenly: the voltage drops fast at first, stays
# near the middle for a long time and falls away at the end, so the points in
# between are not on a straight line. 0% is BATTERY_EMPTY_V, where the car
# refuses to drive, not the 6.0 V where the pack switches itself off.
BATTERY_CURVE = [(8.4, 100), (8.2, 90), (8.0, 78), (7.8, 62), (7.6, 45), (7.4, 28), (7.2, 14), (7.0, 6), (6.8, 0)]


def battery_percent(volts: float) -> int:
    """About how full the battery is, in steps of 5. An estimate from the voltage:
    it reads lower for a moment while the motors pull current."""
    if volts >= BATTERY_CURVE[0][0]:
        return 100
    from itertools import pairwise
    for (v_hi, p_hi), (v_lo, p_lo) in pairwise(BATTERY_CURVE):
        if volts >= v_lo:
            exact = p_lo + (p_hi - p_lo) * (volts - v_lo) / (v_hi - v_lo)
            return max(0, min(100, 5 * round(exact / 5)))
    return 0
# The HC-SR04 reads 2 to 400 cm, and only off flat targets of about 0.5 m² or more:
# legs, toys and cushions may send no echo, which reads as "nothing ahead".
ULTRASONIC_MAX_CM = 400
# Cliff (grayscale) reference, three values right to left. None keeps what
# SunFounder's 1.cali_grayscale.py saved; set e.g. [200, 200, 200] to override.
CLIFF_REFERENCE = None
# Saying one of these while the robot is busy stops the motors at once.
STOP_WORDS = ["stop", "halt", "quiet"]

# Microphone. Robot HAT V4 (this car) has none, so a USB microphone is used: the
# first input whose name contains MIC_NAME (any case). None uses the system default.
MIC_NAME = "USB"
# The loudness that starts a recording is measured from the room's noise; this is
# the most it may be, so a measurement taken during talking cannot make the robot
# deaf. The "listening" progress line shows the level in use.
MIC_START_LEVEL_MAX = 1500
# ...and the least. In a quiet room the measured level came out as 60, and then
# every rustle started a recording and the robot was busy with those.
MIC_START_LEVEL_MIN = 150

# The screen shows what the robot understood of a request, for this many seconds,
# before the face comes back; you see at once when it misheard. 0 switches it off.
SCREEN_SHOWS_REQUEST_S = 4
# Below BATTERY_HUNGRY_V the screen shows a battery and "Charge me!" every this
# many seconds, and the robot says so once.
BATTERY_NOTICE_EVERY_S = 90

# The face screen is mounted upside down (its pins and wires pointing down), so
# the picture is turned by half a turn. False for a screen mounted pins up.
FACE_UPSIDE_DOWN = True

# The camera's live web view (http://<pi>:9000/mjpg) has no password: anyone on
# the home Wi-Fi can watch it. Off unless ~/.robo.env on the Pi has the line
#   ROBO_CAMERA_WEB_VIEW=1
# (then restart the robot). Remove the line to switch it off again.
CAMERA_WEB_VIEW = False

# Housekeeping: older files are deleted so the SD card does not fill up and
# photos and words of the family are not kept forever.
KEEP_SNAPSHOTS = 200     # newest photos in snapshots/
KEEP_TTS_FILES = 500     # newest cached voice clips in tts_cache/
KEEP_DIARY_DAYS = 30     # newest daily diary files in diary/
# What the microphone recorded, as sound files in recordings/, so a sentence the
# robot got wrong can be played back (aplay recordings/<file>). 0 saves none.
KEEP_RECORDINGS = 20

# While a request is being worked on the robot makes sounds: a chirp at once, so
# the speaker knows it was heard and stops repeating the request, then R2-D2
# style muttering (THINKING in robo/sounds.py) with pauses of about
# THINKING_SOUND_EVERY_S seconds until the answer is spoken.
THINKING_SOUND = True
THINKING_SOUND_EVERY_S = 1.2

# Progress lines on the screen and in the log (journalctl -u robo -f): what was
# heard, what Claude asked for, and how long each step took. Set to False for
# only the robot's spoken lines.
SHOW_PROGRESS = True


def log(part: str, text: str) -> None:
    if SHOW_PROGRESS:
        import time
        print(f"{time.strftime('%H:%M:%S')} [{part}] {text}", flush=True)


# Paths
ROOT = Path(__file__).resolve().parent.parent
MODELS_DIR = ROOT / "models"
SNAPSHOT_DIR = ROOT / "snapshots"
RECORDINGS_DIR = ROOT / "recordings"


def load_env_file() -> None:
    """Load ~/.robo.env into os.environ if present (optional extras such as a gateway secret)."""
    env_file = Path.home() / ".robo.env"
    if not env_file.exists():
        # plain `sudo python3` makes home /root: look in the home of the repo's owner
        try:
            import pwd
            env_file = Path(pwd.getpwuid(ROOT.stat().st_uid).pw_dir) / ".robo.env"
        except (ImportError, KeyError, OSError):
            return
        if not env_file.exists():
            return
    for line in env_file.read_text().splitlines():
        line = line.strip().removeprefix("export ").strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]  # systemd strips quotes from this file; do the same
        if is_placeholder(value):
            continue  # the setup script's example line, not a real value
        os.environ.setdefault(key.strip(), value)


def is_placeholder(value: str) -> bool:
    """True for empty values and the 'paste-the-key...' example from setup_pi.sh."""
    return not value or "paste" in value.lower()


load_env_file()

PLACE = os.environ.get("ROBO_PLACE", PLACE)
try:
    LAT = float(os.environ.get("ROBO_LAT", LAT))
    LON = float(os.environ.get("ROBO_LON", LON))
except ValueError:
    pass  # a typo in ~/.robo.env should not stop the robot; keep the defaults
# setup_questions.py writes these two: ROBO_LANGUAGE=de, and ROBO_MIC_NAME=default
# for a Robot HAT V5, whose microphone is the system default.
if os.environ.get("ROBO_LANGUAGE") in VOSK_MODELS:
    LANGUAGE = os.environ["ROBO_LANGUAGE"]
if os.environ.get("ROBO_MIC_NAME"):
    MIC_NAME = None if os.environ["ROBO_MIC_NAME"].lower() == "default" else os.environ["ROBO_MIC_NAME"]

# The household profile: your own robo/family.yaml if it exists, else the example.
FAMILY_FILE = ROOT / "robo" / "family.yaml"
if not FAMILY_FILE.exists():
    FAMILY_FILE = ROOT / "robo" / "family.example.yaml"
if os.environ.get("ROBO_CAMERA_WEB_VIEW", "").lower() in ("1", "true", "on", "yes"):
    CAMERA_WEB_VIEW = True
