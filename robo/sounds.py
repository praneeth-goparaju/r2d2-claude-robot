"""Little robot sounds, synthesised on first use so nothing needs downloading
and nothing is copyrighted. Played with aplay on the Pi or afplay on a Mac."""
import math
import os
import shutil
import struct
import subprocess
import threading
import wave

from . import config, memory

RATE = 22050
# name: list of (frequency Hz, seconds); 0 Hz is a pause
SOUNDS = {
    "beep":   [(880, 0.12)],
    "boop":   [(440, 0.15)],
    "horn":   [(330, 0.18), (0, 0.05), (330, 0.25)],
    "tada":   [(523, 0.12), (659, 0.12), (784, 0.12), (1047, 0.3)],
    "oops":   [(392, 0.18), (349, 0.18), (311, 0.18), (262, 0.35)],
    "hello":  [(659, 0.1), (784, 0.1), (988, 0.18)],
    "think":  [(600, 0.06), (0, 0.06), (600, 0.06), (0, 0.06), (600, 0.06)],
    "alarm":  [(1000, 0.1), (0, 0.05)] * 4,
    "laugh":  [(700, 0.08), (0, 0.04), (650, 0.08), (0, 0.04), (600, 0.08), (0, 0.04), (550, 0.12)],
    # a bouncy 4-second loop for dancing
    "dance":  [(523, 0.15), (659, 0.15), (784, 0.15), (659, 0.15), (523, 0.15), (659, 0.15), (784, 0.3),
               (698, 0.15), (784, 0.15), (880, 0.15), (784, 0.15), (698, 0.15), (659, 0.15), (587, 0.3),
               (523, 0.15), (659, 0.15), (784, 0.15), (1047, 0.3), (784, 0.15), (659, 0.15), (523, 0.45)],
    # Happy Birthday, first two lines
    "birthday": [(392, 0.25), (392, 0.25), (440, 0.5), (392, 0.5), (523, 0.5), (494, 1.0), (0, 0.2),
                 (392, 0.25), (392, 0.25), (440, 0.5), (392, 0.5), (587, 0.5), (523, 1.0), (0, 0.2),
                 (392, 0.25), (392, 0.25), (784, 0.5), (659, 0.5), (523, 0.5), (494, 0.5), (440, 1.0), (0, 0.2),
                 (698, 0.25), (698, 0.25), (659, 0.5), (523, 0.5), (587, 0.5), (523, 1.0)],
}
# In the style of R2-D2: quick runs of short tones. Each step is its own little
# blip, which gives the burbling sound; these are our own patterns, not recordings.
def _run(start: int, end: int, steps: int, secs: float = 0.03) -> list:
    return [(round(start + (end - start) * i / (steps - 1)), secs) for i in range(steps)]


SOUNDS.update({
    "chirp":        [*_run(1400, 2600, 5), *_run(2600, 1800, 3), (2900, 0.07)],
    "whistle_up":   [*_run(700, 2800, 14, 0.035), (2800, 0.12)],
    "whistle_down": [*_run(2400, 500, 16, 0.04), (450, 0.2)],
    "chatter":      [(f, 0.045) for f in (1800, 2400, 1300, 2900, 1600, 2200, 1100, 2700, 1500, 3100, 1900, 2500, 1200, 2800)],
})

# Dramatic sounds for games and stories, the same kind of plain tones: a drumroll
# before a reveal, a "dun dun DUNN" when the music stops, a fanfare for a winner.
SOUNDS.update({
    "drumroll":       [(f, 0.03) for f in (180, 210) * 25] + [(0, 0.05), (2600, 1900, 0.35)],
    "suspense":       [(196, 0.28), (0, 0.1), (233, 0.28), (0, 0.1), (185, 175, 1.1)],
    "ticking":        [(1300, 0.03), (0, 0.42), (950, 0.03), (0, 0.42)] * 4,
    "fanfare":        [(392, 0.14), (523, 0.14), (659, 0.14), (784, 0.32), (0, 0.06), (659, 0.14), (784, 0.7)],
    "sad_trombone":   [(392, 0.4), (370, 0.4), (349, 0.45), (330, 315, 0.2), (315, 330, 0.2), (330, 315, 0.2), (315, 300, 0.5)],
    "spooky":         [(220, 660, 1.0), (660, 600, 0.25), (600, 680, 0.25), (680, 590, 0.25), (590, 400, 0.6)],
    "heartbeat":      [(160, 0.09), (0, 0.11), (140, 0.13), (0, 0.6)] * 3,
    "countdown":      [(660, 0.18), (0, 0.82)] * 3 + [(1320, 0.6)],
    "record_scratch": [(1800, 300, 0.22), (0, 0.04), (1100, 250, 0.18)],
})

# For the character modes (robo/characters.py): sounds in the style of famous
# film robots, made from our own tones like the rest, never taken from a film.
SOUNDS.update({
    "walle_call":    [(260, 430, 0.22), (430, 330, 0.18), (0, 0.08), (330, 720, 0.3), (720, 640, 0.25)],   # a wobbly "waa-lee"
    "eve_whoosh":    [(400, 2400, 0.45), (2400, 2000, 0.2), (0, 0.05), (2600, 0.08)],
    "power_up":      [*_run(200, 1400, 12, 0.05), (1400, 0.2)],
    "power_down":    [(1400, 150, 0.9)],
    "red_alert":     [(500, 0.12), (750, 0.12)] * 5,
    "villain_laugh": [(170, 0.16), (0, 0.06), (155, 0.12), (0, 0.06), (140, 0.12), (0, 0.06), (130, 0.22), (130, 90, 0.45)],
})

NAMES = list(SOUNDS)   # the sounds Claude may ask for


# What the robot mutters while it works on a request. R2-D2 talks in quick
# blips that jump about in pitch, slides up and down, and trills between two
# notes. A note written (from Hz, to Hz, seconds) slides. Each pattern below is
# built from those three; again our own patterns, not recordings. They are
# played by main.Thinking, one at random, and are not offered to Claude.
def _blips(seed: int, count: int, low: int = 700, high: int = 3400) -> list:
    """Short blips at pitches that jump about, the same ones every time for a seed."""
    import random
    r = random.Random(seed)
    out = []
    for _ in range(count):
        out.append((r.randrange(low, high, 50), r.choice((0.035, 0.045, 0.06, 0.08))))
        if r.random() < 0.25:
            out.append((0, 0.03))
    return out


def _trill(a: int, b: int, times: int, secs: float = 0.035) -> list:
    return [(a, secs), (b, secs)] * times


THINKING = {
    "think_burble":   [*_blips(1, 9), (1500, 2900, 0.12)],
    "think_question": [*_blips(2, 5), (0, 0.05), (900, 2600, 0.16), (2600, 3100, 0.07)],
    "think_trill":    [*_trill(2100, 2700, 5), (2700, 1100, 0.18), (0, 0.04), *_blips(3, 4)],
    "think_low":      [(600, 320, 0.14), (0, 0.05), *_blips(4, 6, 500, 1900), (700, 1500, 0.1)],
    "think_whistle":  [(1100, 3000, 0.16), (3000, 1700, 0.12), (0, 0.06), *_trill(1900, 2300, 3), (2300, 0.08)],
    "think_stutter":  [(1800, 0.07), (0, 0.07), (1800, 0.06), (0, 0.05), (2000, 0.05), (0, 0.04), (2200, 0.045), (0, 0.03),
                       (2400, 0.04), (2600, 0.035), (2800, 0.03), (3000, 0.03), (3200, 2200, 0.12)],
    "think_mumble":   [*_blips(5, 4, 600, 1500), (1500, 800, 0.1), (0, 0.08), *_blips(6, 5, 900, 2400), (2400, 1300, 0.14)],
    "think_sing":     [(1300, 1900, 0.09), (1900, 1500, 0.07), (1500, 2500, 0.09), (2500, 2100, 0.07), (2100, 3300, 0.12), (0, 0.04), *_blips(7, 3)],
}
SOUNDS.update(THINKING)


# Songs the robot can sing ("R2-D2, sing Twinkle Twinkle"). All are traditional
# tunes, or by composers dead for well over a century, so they are free to use.
# Written as note names with a length in beats: "C4:1" is middle C for one beat,
# "-:1" a rest. Played by play_song(), offered to Claude through the sing tool.
_STEPS = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}


def _melody(score: str, beat: float) -> list:
    """Turn "C4:1 D4:0.5 -:1" into (Hz, seconds) notes. Each note ends a little
    early, so two of the same pitch in a row are heard as two."""
    notes = []
    for item in score.split():
        name, beats = item.split(":")
        secs = float(beats) * beat
        if name == "-":
            notes.append((0, secs))
            continue
        semitones = _STEPS[name[0]] + (1 if "#" in name else 0) + 12 * (int(name[-1]) - 4)
        notes += [(round(261.63 * 2 ** (semitones / 12)), secs * 0.88), (0, secs * 0.12)]
    return notes


SONGS = {
    "twinkle_twinkle": _melody(
        "C4:1 C4:1 G4:1 G4:1 A4:1 A4:1 G4:2 F4:1 F4:1 E4:1 E4:1 D4:1 D4:1 C4:2 "
        "G4:1 G4:1 F4:1 F4:1 E4:1 E4:1 D4:2 G4:1 G4:1 F4:1 F4:1 E4:1 E4:1 D4:2 "
        "C4:1 C4:1 G4:1 G4:1 A4:1 A4:1 G4:2 F4:1 F4:1 E4:1 E4:1 D4:1 D4:1 C4:2", 0.36),
    "ode_to_joy": _melody(
        "E4:1 E4:1 F4:1 G4:1 G4:1 F4:1 E4:1 D4:1 C4:1 C4:1 D4:1 E4:1 E4:1.5 D4:0.5 D4:2 "
        "E4:1 E4:1 F4:1 G4:1 G4:1 F4:1 E4:1 D4:1 C4:1 C4:1 D4:1 E4:1 D4:1.5 C4:0.5 C4:2", 0.36),
    "frere_jacques": _melody(
        "C4:1 D4:1 E4:1 C4:1 C4:1 D4:1 E4:1 C4:1 E4:1 F4:1 G4:2 E4:1 F4:1 G4:2 "
        "G4:0.5 A4:0.5 G4:0.5 F4:0.5 E4:1 C4:1 G4:0.5 A4:0.5 G4:0.5 F4:0.5 E4:1 C4:1 "
        "C4:1 G3:1 C4:2 C4:1 G3:1 C4:2", 0.36),
    "mary_had_a_little_lamb": _melody(
        "E4:1 D4:1 C4:1 D4:1 E4:1 E4:1 E4:2 D4:1 D4:1 D4:2 E4:1 G4:1 G4:2 "
        "E4:1 D4:1 C4:1 D4:1 E4:1 E4:1 E4:1 E4:1 D4:1 D4:1 E4:1 D4:1 C4:4", 0.34),
    "old_macdonald": _melody(
        "G4:1 G4:1 G4:1 D4:1 E4:1 E4:1 D4:2 B4:1 B4:1 A4:1 A4:1 G4:3 D4:1 "
        "G4:1 G4:1 G4:1 D4:1 E4:1 E4:1 D4:2 B4:1 B4:1 A4:1 A4:1 G4:4", 0.32),
    "row_your_boat": _melody(
        "C4:1.5 C4:1.5 C4:1 D4:0.5 E4:1.5 E4:1 D4:0.5 E4:1 F4:0.5 G4:3 "
        "C5:0.5 C5:0.5 C5:0.5 G4:0.5 G4:0.5 G4:0.5 E4:0.5 E4:0.5 E4:0.5 C4:0.5 C4:0.5 C4:0.5 "
        "G4:1 F4:0.5 E4:1 D4:0.5 C4:3", 0.34),
    "jingle_bells": _melody(
        "E4:1 E4:1 E4:2 E4:1 E4:1 E4:2 E4:1 G4:1 C4:1.5 D4:0.5 E4:4 "
        "F4:1 F4:1 F4:1.5 F4:0.5 F4:1 E4:1 E4:1 E4:0.5 E4:0.5 E4:1 D4:1 D4:1 E4:1 D4:2 G4:2 "
        "E4:1 E4:1 E4:2 E4:1 E4:1 E4:2 E4:1 G4:1 C4:1.5 D4:0.5 E4:4 "
        "F4:1 F4:1 F4:1.5 F4:0.5 F4:1 E4:1 E4:1 E4:0.5 E4:0.5 G4:1 G4:1 F4:1 D4:1 C4:4", 0.26),
    "london_bridge": _melody(
        "G4:1.5 A4:0.5 G4:1 F4:1 E4:1 F4:1 G4:2 D4:1 E4:1 F4:2 E4:1 F4:1 G4:2 "
        "G4:1.5 A4:0.5 G4:1 F4:1 E4:1 F4:1 G4:2 D4:2 G4:2 E4:1 C4:3", 0.32),
    "happy_birthday": SOUNDS["birthday"],
}
SOUNDS.update({f"song_{name}": notes for name, notes in SONGS.items()})


def path_for(name: str, quiet: bool = False):
    """The sound as a WAV file. quiet is the night version, about a quarter as loud
    as the level 1.0 one. The day version follows SPEAKER_GAIN; its level is part
    of the file name, so changing the setting makes new files."""
    folder = memory.make_dir(config.ROOT / "sounds")
    volume = 0.12 if quiet else min(0.95, 0.5 * config.SPEAKER_GAIN)  # 1.0 would be the loudest a WAV can hold
    p = folder / f"{name}{'-quiet' if quiet else f'-{round(volume * 100)}'}.wav"
    if not p.exists():
        _synth(SOUNDS[name], p, volume=volume)
        memory.own(p)
    return p


def _night() -> bool:
    from .assistant import is_night
    return is_night()


def _synth(notes, path, volume: float = 0.5) -> None:
    """notes: (Hz, seconds) for a steady tone, 0 Hz for a pause, or
    (from Hz, to Hz, seconds) for a slide between two pitches."""
    frames = bytearray()
    for note in notes:
        start, end, secs = (note[0], note[0], note[1]) if len(note) == 2 else note
        n = int(RATE * secs)
        phase = 0.0
        for i in range(n):
            env = min(1.0, i / (RATE * 0.01), (n - i) / (RATE * 0.02))  # soft attack and release
            phase += 2 * math.pi * (start + (end - start) * i / n) / RATE  # the pitch now, added up: no clicks in a slide
            v = 0.0 if start == 0 else volume * env * math.sin(phase)
            frames += struct.pack("<h", int(v * 32767))
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(RATE); w.writeframes(bytes(frames))


def player_env() -> dict | None:
    """The environment for an audio player. The robot runs as root with HOME still
    set to the normal user's folder (sudo -E, and the systemd unit, so the key
    file and the Claude Code login are found). ALSA's check for a desktop sound
    service then prints "Home directory not accessible: Permission denied" for
    every sound. Players get root's own home instead. None: leave it as it is."""
    if not hasattr(os, "geteuid") or os.geteuid() != 0:
        return None
    import pwd
    return {**os.environ, "HOME": pwd.getpwuid(0).pw_dir}


_speaker_on = False


def enable_speaker() -> None:
    """Switch on the Robot HAT's speaker amplifier, once. i2samp.sh only does this
    during setup; after a reboot the pin is off again and the car is mute.
    SunFounder's own audio code calls this before it plays anything."""
    global _speaker_on
    if _speaker_on:
        return
    _speaker_on = True
    try:
        os.environ.setdefault("AUDIODRIVER", "alsa")  # for the sox command robot-hat runs here
        from robot_hat.device import enable_speaker as hat_enable
        home, env = os.environ.get("HOME"), player_env()
        try:
            if env:  # robot-hat starts sox itself, so HOME is swapped for the call
                os.environ["HOME"] = env["HOME"]
            hat_enable()
        finally:
            if env and home is not None:
                os.environ["HOME"] = home
    except Exception as e:  # not on the Pi, or no HAT
        if shutil.which("aplay"):
            print(f"[sound] could not switch the speaker on: {e}")


def play_background(name: str):
    """Start a sound and return at once (for dancing). Returns the process or None."""
    if name not in SOUNDS:
        return None
    p = path_for(name, quiet=_night())
    player = next((c for c in ("afplay", "aplay") if shutil.which(c)), None)
    if player is None:
        return None
    enable_speaker()
    return subprocess.Popen([player, "-q", str(p)] if player == "aplay" else [player, str(p)], env=player_env())


# The speaker plays one thing at a time: a second player started while the first
# is still running finds the sound card busy and plays nothing. The voice, the
# sounds Claude asks for and the thinking sound all wait for each other here.
ONE_AT_A_TIME = threading.Lock()


def song_seconds(name: str) -> float:
    return sum(n[-1] for n in SONGS[name])


def play_song(name: str, on_beat=None, stop=None, max_seconds: float | None = None, speaker_is_ours: bool = False) -> str:
    """Play a song from SONGS to the end. on_beat() is called about twice a second
    while it plays (the robot sways its head to it); stop() returning True ends
    the song early, so "stop" works during a song. max_seconds plays only the
    start (games). speaker_is_ours: the caller already holds ONE_AT_A_TIME."""
    import contextlib
    import time
    if name not in SONGS:
        return f"unknown song {name}; choose from {', '.join(SONGS)}"
    p = path_for(f"song_{name}", quiet=_night())
    player = next((c for c in ("afplay", "aplay") if shutil.which(c)), None)
    if player is None:
        return f"{name} (no audio player found)"
    enable_speaker()
    with contextlib.nullcontext() if speaker_is_ours else ONE_AT_A_TIME:
        proc = subprocess.Popen([player, "-q", str(p)] if player == "aplay" else [player, str(p)], env=player_env())
        t0 = time.time()
        try:
            while proc.poll() is None:
                if stop is not None and stop():
                    proc.terminate()
                    return f"stopped singing {name}"
                if max_seconds is not None and time.time() - t0 >= max_seconds:
                    proc.terminate()
                    return f"played the first {max_seconds:g} seconds of {name}"
                if on_beat is not None:
                    on_beat()
                time.sleep(0.45)
        finally:
            if proc.poll() is None:
                proc.terminate()
    return f"sang {name}"


def play(name: str, speaker_is_ours: bool = False) -> str:
    """Play a sound to the end. speaker_is_ours: the caller already holds
    ONE_AT_A_TIME (the voice does, for a sound in the middle of a reply)."""
    import contextlib
    if name not in SOUNDS:
        return f"unknown sound {name}; choose from {', '.join(NAMES)}"
    p = path_for(name, quiet=_night())
    player = next((c for c in ("afplay", "aplay") if shutil.which(c)), None)
    if player is None:
        return f"{name} (no audio player found)"
    enable_speaker()
    with contextlib.nullcontext() if speaker_is_ours else ONE_AT_A_TIME:
        subprocess.run([player, "-q", str(p)] if player == "aplay" else [player, str(p)], check=False, env=player_env())
    return f"played {name}"
