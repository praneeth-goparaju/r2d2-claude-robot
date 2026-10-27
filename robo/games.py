"""Music and dance games: Freeze Dance, Copy My Dance and Name That Tune.
Each tool call is one round; Claude does the talking around it (rules, who is
out, the reveal). Camera head and steering only, so they work at night too.
While a round runs it holds the speaker, so the thinking mutter waits."""
import random
import time

from . import config, sounds
from .car import BODY, STOP

PAN, TILT = config.CAM_PAN_LIMIT, config.CAM_TILT_LIMIT


# Dance steps, one call per beat (about twice a second); i counts the beats.
def _sway(car, i):
    car.look(15 if i % 2 else -15, 6, settle=False)


def _bounce(car, i):
    car.steer(15 if i % 2 else -15); car.look(0, 15 if i % 2 else -5, settle=False)


def _wiggle(car, i):
    car.steer(25 if i % 2 else -25); car.look(25 if i % 4 < 2 else -25, 12 if i % 2 else -4, settle=False)


def _nod(car, i):
    car.look(10 if i % 4 < 2 else -10, 12 if i % 2 else -4, settle=False)


STEPS = {"sway": _sway, "bounce": _bounce, "wiggle": _wiggle, "nod": _nod}
# the way the robot dances to each song: slow songs sway, lively ones wiggle
SONG_STYLE = {"twinkle_twinkle": "sway", "ode_to_joy": "nod", "frere_jacques": "sway",
              "mary_had_a_little_lamb": "bounce", "old_macdonald": "bounce", "row_your_boat": "sway",
              "jingle_bells": "wiggle", "london_bridge": "nod", "happy_birthday": "wiggle"}


def _straighten(car):
    car.steer(0); car.look(0, 0, settle=False)


def _dance_to(car, face, song, max_seconds, z):
    """Play a song (or its start) and dance to it in its style. Returns False if
    someone said stop. The caller holds BODY and the speaker."""
    step, beat = STEPS[SONG_STYLE.get(song, "wiggle")], [0]

    def on_beat():
        step(car, beat[0]); beat[0] += 1
    if face: face.show("singing", hold=None); face.set_talking(True)
    try:
        sounds.play_song(song, on_beat=on_beat, stop=STOP.is_set, max_seconds=max_seconds * z, speaker_is_ours=True)
    finally:
        if face: face.set_talking(False)
        _straighten(car)
    return not STOP.is_set()


def _sound(name, fast):
    if not fast:  # the mock and the tests stay silent
        sounds.play(name, speaker_is_ours=True)


def freeze_dance(car, camera, face, last_song=None, fast=False):
    """One round: dance to a random song, stop the music without warning, then
    take two photos a moment apart so Claude can see who kept moving.
    Returns (song, text, photos)."""
    z = 0.02 if fast else 1.0
    song = random.choice([s for s in sounds.SONGS if s != last_song])
    cut = random.uniform(4, min(12, sounds.song_seconds(song) - 1))
    with BODY, sounds.ONE_AT_A_TIME:
        if not _dance_to(car, face, song, cut, z):
            return song, "stopped: someone said stop", []
        car.look(0, 8, settle=False)
        if face: face.show("surprised", hold=None)
        _sound("record_scratch", fast)
        photos, problem = [], None
        try:
            time.sleep(0.3 * z); photos.append(camera.snapshot())
            _sound("suspense", fast)   # about two seconds of "dun dun DUNN" while they hold still
            photos.append(camera.snapshot())
        except Exception as e:
            problem = str(e)
        if face: face.show("thinking")
    if problem:
        return song, (f"The music stopped after {cut:.0f} seconds of {song}, but the camera is not working ({problem}). "
                      "Ask who wobbled instead."), []
    return song, (f"The music stopped after {cut:.0f} seconds of {song}. Two photos about two seconds apart, "
                  "taken while everyone should be frozen. Compare them: anyone whose arms, legs or head moved "
                  "is out. Only call someone out if the change is clear."), photos


# Copy My Dance: each move has its own note, like the Simon memory game.
# (pan, tilt, steer) positions held for a moment, then back to the middle.
MOVES = {
    "nod":        (523, [(0, 20, 0), (0, -10, 0), (0, 20, 0)]),
    "shake":      (659, [(-30, 0, 0), (30, 0, 0), (-30, 0, 0)]),
    "wiggle":     (392, [(0, 0, -25), (0, 0, 25), (0, 0, -25)]),
    "look_up":    (784, [(0, TILT, 0)]),
    "look_down":  (262, [(0, -TILT, 0)]),
    "lean_left":  (587, [(-PAN, 10, -20)]),
    "lean_right": (440, [(PAN, 10, 20)]),
}
sounds.SOUNDS.update({f"step_{name}": [(hz, 0.4)] for name, (hz, _) in MOVES.items()})  # not offered to Claude
LONGEST = 12


def copy_my_dance(car, face, sequence: list, new_game: bool, fast=False) -> str:
    """Add one move to the sequence (two for a new game) and perform all of it,
    each move with its note. sequence is changed in place."""
    z = 0.02 if fast else 1.0
    starting = new_game or not sequence
    if starting:
        sequence.clear()
        sequence.append(random.choice(list(MOVES)))
    sequence.append(random.choice([m for m in MOVES if m != sequence[-1]]))
    with BODY, sounds.ONE_AT_A_TIME:
        if face: face.show("cool", hold=None)
        if starting:
            _sound("countdown", fast)
        for name in sequence:
            if STOP.is_set():
                _straighten(car)
                return "stopped: someone said stop"
            if not fast:
                sounds.play_background(f"step_{name}")
            hold = 0.6 / len(MOVES[name][1])
            for pan, tilt, steer in MOVES[name][1]:
                car.look(pan, tilt, settle=False); car.steer(steer); time.sleep(hold * z)
            _straighten(car); time.sleep(0.3 * z)
        if face: face.show("happy")
    moves = ", ".join(m.replace("_", " ") for m in sequence)
    if len(sequence) >= LONGEST:
        return f"Round {len(sequence) - 1}, the longest dance there is: {moves}. Whoever copies this is the champion."
    return (f"Round {len(sequence) - 1}: danced {len(sequence)} moves: {moves}. Now say it is their turn and let them "
            "copy it; if they ask, name the moves.")


def name_that_tune(car, face, recent: list, longer: bool, fast=False) -> tuple[str, str]:
    """Play the opening of a song and dance to it. longer replays the same song
    for longer, as a hint. recent (newest last) is changed in place.
    Returns (song, text)."""
    z = 0.02 if fast else 1.0
    if longer and recent:
        song, seconds = recent[-1], 10
    else:
        fresh = [s for s in sounds.SONGS if s not in recent[-4:]]
        song, seconds = random.choice(fresh), 5
        recent.append(song); del recent[:-6]
    with BODY, sounds.ONE_AT_A_TIME:
        if not _dance_to(car, face, song, seconds, z):
            return song, "stopped: someone said stop"
        if face: face.show("thinking")
    title = song.replace("_", " ")
    return song, (f"Played the first {seconds} seconds of {title}. It is a secret: do not say the name. Ask them "
                  "to guess. When someone guesses, reveal it with [sound:drumroll] before the answer.")


def _photos(camera, aims, car, z):
    """Photos at each (pan, tilt). Returns (photos, problem); problem is None if the camera worked."""
    photos = []
    try:
        for pan, tilt in aims:
            car.look(pan, tilt, settle=False); time.sleep(0.4 * z)
            photos.append(camera.snapshot())
    except Exception as e:
        return photos, str(e)
    finally:
        _straighten(car)
    return photos, None


# Hide and seek: count with the head down, then look around for the hiders.
def hide_and_seek(car, camera, face, phase: str, seconds: float = 20, fast=False):
    """phase "count": eyes shut and ticking for seconds. phase "seek": photos to
    the left, ahead and to the right. Returns (text, photos)."""
    z = 0.02 if fast else 1.0
    if phase == "count":
        with BODY, sounds.ONE_AT_A_TIME:
            if face: face.show("sleepy", hold=None)
            car.look(0, -TILT, settle=False)
            end = time.time() + seconds * z
            while time.time() < end and not STOP.is_set():
                if fast:
                    time.sleep(0.01)
                else:
                    _sound("ticking", fast)
            _straighten(car)
            if face: face.show("happy")
        if STOP.is_set():
            return "stopped: someone said stop", []
        return (f"Counted {seconds:g} seconds with eyes shut. Say \"Ready or not, here I come!\", then call "
                "hide_and_seek with phase seek."), []
    with BODY:
        if face: face.show("confused", hold=None)
        photos, problem = _photos(camera, ((-PAN, 5), (0, 5), (PAN, 5)), car, z)
        if face: face.show("thinking")
    if problem:
        return f"The camera is not working ({problem}). Ask the hiders to make a little noise instead, and guess where.", []
    return ("Three photos: left, straight ahead, right. If you see a child or a bit of one (a foot, a hand, hair "
            "behind a curtain), say \"Found you!\" with [sound:fanfare] and where. Otherwise say something funny "
            "like \"Hmm, not behind the sofa...\", drive a short way somewhere new and seek again. Never claim to see "
            "someone who is not in a photo."), photos


# Simon Says: the robot gives the order, then watches who obeys.
def simon_says(car, camera, face, voice, command: str, simon: bool, fast=False):
    """Say the order (with "Simon says" in front when simon), give the players a
    moment, then take a photo. Returns (text, photos)."""
    z = 0.02 if fast else 1.0
    voice.say(("Simon says, " if simon else "") + command)
    with BODY, sounds.ONE_AT_A_TIME:
        if face: face.show("thinking", hold=None)
        if fast:
            time.sleep(2.5 * z)
        else:
            _sound("ticking", fast)   # about four seconds to do it
        if STOP.is_set():
            _straighten(car)
            return "stopped: someone said stop", []
        photos, problem = _photos(camera, ((0, 8),), car, z)
        if face: face.show("happy")
    rule = (f"Simon said it, so anyone NOT doing \"{command}\" is out." if simon else
            f"Simon did NOT say it, so anyone who did \"{command}\" is out, and the ones who stayed still were clever.")
    if problem:
        return f"{rule} The camera is not working ({problem}), so ask who did it.", []
    return (f"{rule} Look at the photo and judge kindly: only call someone out if it is clear, and cheer the "
            "ones still in. Then give the next order, and mix in some without Simon says."), photos


# Color hunt: "bring me something red!", then check it with the camera.
COLORS = ["red", "blue", "green", "yellow", "orange", "purple", "pink", "white", "black", "brown"]


def color_hunt(car, camera, face, recent: list, check: bool, fast=False):
    """check False: pick a new colour (not one of the last few). check True: photo
    of what the players hold up. recent (newest last) is changed in place.
    Returns (text, photos)."""
    z = 0.02 if fast else 1.0
    if not check or not recent:
        color = random.choice([c for c in COLORS if c not in recent[-3:]])
        recent.append(color); del recent[:-5]
        _sound("countdown", fast)
        return (f"The colour is {color}. Say \"Bring me something {color}!\" and that they have until the count of ten. "
                "When they are back, call color_hunt with check true."), []
    color = recent[-1]
    with BODY:
        if face: face.show("thinking", hold=None)
        photos, problem = _photos(camera, ((0, 15),), car, z)
        if face: face.show("happy")
    if problem:
        return f"They were to bring something {color}. The camera is not working ({problem}), so ask them to tell you what they found.", []
    return (f"They were to bring something {color}. Look at what they hold up. If it is {color}, cheer with "
            "[sound:tada] and name the thing. If not, giggle kindly, say what colour it really is, and let them "
            "try again. Then start a new round with check false."), photos
