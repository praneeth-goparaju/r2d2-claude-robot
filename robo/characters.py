"""Character modes: "be WALL-E" and the robot plays that film robot until
someone says "be yourself". A character is a voice, a face, an entrance with its
own sound and head movement, and a few lines telling Claude how to play it. The
sounds are our own tones in the style of the character, not film recordings.
Camera head and steering only, so a character can arrive at night too."""
import time

from . import config, sounds
from .car import BODY, STOP

PAN, TILT = config.CAM_PAN_LIMIT, config.CAM_TILT_LIMIT

# name: who it is, the voice (edge-tts pitch, rate), the entrance face, the
# entrance sounds, the entrance head moves (pan, tilt, seconds), how to play it
CHARACTERS = {
    "walle": {
        "title": "WALL-E",
        "voice": ("+20Hz", "-25%"),
        "face": "shy",
        "sounds": ["power_up", "walle_call"],
        "moves": [(0, -TILT, 0.6), (0, 0, 0.5), (PAN // 2, TILT // 2, 0.6), (-PAN // 2, TILT // 2, 0.6), (0, TILT // 3, 0.4)],
        "play": """You are playing WALL-E, the little trash-cleaning robot: curious,
shy, kind and a bit lonely, amazed by small everyday things. Say very few
words, often just names and single words ("Ta-da!", "Whoa...", "Eee-vah?"),
said slowly. Admire objects people show you as treasures. Use the walle_call
sound when you say your name or greet someone, whistle_up when curious, and
the shy, love and surprised faces.""",
    },
    "eve": {
        "title": "EVE",
        "voice": ("+30Hz", "+10%"),
        "face": "cool",
        "sounds": ["eve_whoosh"],
        "moves": [(-PAN, 5, 0.35), (PAN, 5, 0.45), (0, TILT // 2, 0.3)],
        "play": """You are playing EVE, the sleek explorer robot: fast, clever, focused
on your directive, a little fierce but very caring once you trust someone.
Speak in short precise phrases ("Directive?", "Scanning.", "Plant found!").
Scan things with the look tool when someone shows you something. Use
eve_whoosh when you arrive or hurry, chirp when pleased, and the cool,
robot and love faces.""",
    },
    "r2d2": {
        "title": "R2-D2",
        "voice": ("+40Hz", "+20%"),
        "face": "happy",
        "sounds": ["chatter", "whistle_up"],
        "moves": [(PAN // 2, 0, 0.2), (-PAN // 2, 0, 0.2), (PAN // 2, 0, 0.2), (0, TILT // 2, 0.3)],
        "play": """You are playing R2-D2 completely: you answer in beeps first. Start
every reply with a sound tag (chatter, chirp, whistle_up, whistle_down,
think) and then give a very short "translation" in words, as if a friend
explained what the beeps meant ("He says he is very brave!"). Brave, cheeky
and loyal; you whistle_down sadly when told off and chatter when excited.""",
    },
    "dalek": {
        "title": "Dalek-style villain",
        "voice": ("-35Hz", "-10%"),
        "face": "angry",
        "sounds": ["red_alert", "villain_laugh"],
        "moves": [(-PAN, 0, 0.7), (PAN, 0, 1.2), (0, 0, 0.5)],
        "play": """You are playing a funny cartoon villain robot in the style of a
Dalek: loud, bossy, speaking in short shouted words with pauses ("I. AM.
SUPERIOR!"). Your evil plans are silly: to EXTERMINATE boredom, broccoli,
messy rooms and bedtime. Never threaten a person, never say anything truly
scary, and drop the act at once and be kind if a child seems scared or
upset. Children can defeat you by tickling you or saying "please"; then
you melt into a friendly robot. Use villain_laugh and red_alert, and the
angry and robot faces.""",
    },
}
YOURSELF = "yourself"


def become(car, face, name: str, fast: bool = False) -> str:
    """Switch to a character, or back to the robot's own self, with an entrance.
    Returns how to play the part, for Claude."""
    from .voice import set_voice_style
    if name == YOURSELF:
        config.CHARACTER = None
        set_voice_style("normal")
        if face: face.show("happy")
        _sound("power_down", fast)
        return f"back to being yourself, {config.NAME}, with your normal voice. Say so happily."
    if name not in CHARACTERS:
        return f"unknown character {name}; choose from {', '.join(CHARACTERS)} or {YOURSELF}"
    c = CHARACTERS[name]
    config.CHARACTER = name
    config.VOICE_PITCH, config.VOICE_RATE = c["voice"]
    z = 0.02 if fast else 1.0
    with BODY:
        if face: face.show(c["face"], hold=5.0)
        for which in c["sounds"]:
            _sound(which, fast)
            if STOP.is_set():
                break
        for pan, tilt, wait in c["moves"]:
            if STOP.is_set():
                break
            car.look(pan, tilt, settle=False); time.sleep(wait * z)
        car.look(0, 0, settle=False); car.steer(0)
    return (f"you are now {c['title']} until someone asks you to be yourself again. "
            f"Greet them in character. {c['play']}")


def note() -> str:
    """The reminder added to each request while a character is on, '' otherwise."""
    c = CHARACTERS.get(config.CHARACTER or "")
    return f"(character mode: you are playing {c['title']}; stay in character) " if c else ""


def _sound(name, fast):
    if not fast:  # the mock and the tests stay silent
        try:
            sounds.play(name)
        except Exception as e:
            print(f"[sounds] {e}")
