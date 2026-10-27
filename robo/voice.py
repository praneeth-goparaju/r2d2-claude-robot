"""Ears and mouth.

listen(): records one utterance from the microphone (on board on Robot HAT V5;
a V4 HAT has none, so plug in a USB one) and transcribes it with Google's
recognizer when it is meant for the robot, else on the Pi with Moonshine or
Vosk. say(): speaks through the Robot HAT speaker, with an online neural voice
first and espeak-ng as the offline one. Both have keyboard/print
fallbacks for the Mac.
"""
import contextlib
import json
import os
import sys
import threading
import time

from . import config, memory, sounds

# Silly voices: pitch and rate offsets for edge-tts. "normal" resets.
VOICE_STYLES = {
    "normal":   ("+0Hz", "+5%"),
    "robot":    ("+25Hz", "+15%"),
    "giant":    ("-40Hz", "-20%"),
    "chipmunk": ("+70Hz", "+30%"),
    "sleepy":   ("-15Hz", "-30%"),
    "excited":  ("+15Hz", "+25%"),
}


def set_voice_style(style: str) -> str:
    if style not in VOICE_STYLES:
        return f"unknown style {style}; choose from {', '.join(VOICE_STYLES)}"
    config.VOICE_PITCH, config.VOICE_RATE = VOICE_STYLES[style]
    return f"voice style is now {style}"


def _percent(text: str) -> float:
    """"+5%" -> 5.0, "-20%" -> -20.0, "+25Hz" -> 25.0."""
    return float(text.rstrip("%Hz") or 0)


def louder(path, gain: float) -> None:
    """Make a 16-bit WAV file louder in place. Piper's speech already reaches the
    top of the range at its loudest moments, so plain multiplying would crackle:
    tanh turns the quiet and middle parts up by about `gain` and rounds the
    peaks off just below the top. The online voices get the same gain from
    mpg123, so a sentence Piper stands in for is no longer much quieter."""
    import array
    import math
    import wave
    with wave.open(str(path)) as w:
        params, frames = w.getparams(), w.readframes(w.getnframes())
    if params.sampwidth != 2 or gain <= 1.0:
        return
    samples = array.array("h", frames)
    if sys.byteorder == "big":
        samples.byteswap()
    top = math.tanh(gain)
    samples = array.array("h", (int(32767 * math.tanh(gain * v / 32768) / top) for v in samples))
    if sys.byteorder == "big":
        samples.byteswap()
    with wave.open(str(path), "wb") as w:
        w.setparams(params)
        w.writeframes(samples.tobytes())


LONG_SENTENCE = 110   # characters; a longer sentence is spoken in pieces


def speakable_parts(text: str) -> list[str]:
    """The text as the pieces that are made and played one after the other:
    sentences, and a long sentence cut at its commas into pieces of up to about
    LONG_SENTENCE characters. On the Pi a 12 second sentence took 6.5 s to make
    with the local voice, all of it silence before the first word."""
    import re
    parts = []
    for sentence in re.split(r"(?<=[.!?])\s+", text.strip()):
        if len(sentence) <= LONG_SENTENCE:
            parts.append(sentence)
            continue
        piece = ""
        for clause in re.split(r"(?<=[,;:])\s+", sentence):
            if piece and len(piece) + len(clause) + 1 > LONG_SENTENCE:
                parts.append(piece)
                piece = clause
            else:
                piece = f"{piece} {clause}".strip()
        parts.append(piece)
    return [p for p in parts if p]


class NotAvailable(Exception):
    """A voice that is not installed or not loaded: a reason to use the next one, not worth a message."""


class Speaker:
    """Text to speech. Which voice comes first is VOICE_ENGINE in config.py:
    - Google Cloud Text-to-Speech (needs internet and GOOGLE_API_KEY)
    - Microsoft Edge neural voices via the free edge-tts package (needs internet)
    - Piper, made on the Pi itself (no internet)
    If the first fails the others are tried, then espeak-ng on the Pi (robotic) or
    the macOS `say` command, then print only."""

    def __init__(self):
        import platform
        import shutil
        self.system = platform.system()
        self.player = self._find_player()
        self.piper = None
        # Under `sudo -E` this still points at the normal user's folder, and every
        # player then prints two "XDG_RUNTIME_DIR is not owned by us" lines while
        # looking for that user's sound service. Root plays straight to the speaker.
        if hasattr(os, "geteuid") and os.geteuid() == 0:
            os.environ.pop("XDG_RUNTIME_DIR", None)
        # robot-hat 2.5.x no longer has the TTS class this used, so the offline
        # voice is the espeak-ng command itself.
        self.espeak = next((c for c in ("espeak-ng", "espeak") if shutil.which(c)), None) if self.system == "Linux" else None
        if self.system == "Linux":
            from . import sounds
            sounds.enable_speaker()
        self.mac_say = self.system == "Darwin" and shutil.which("say") is not None
        self.cache = memory.make_dir(config.ROOT / "tts_cache")
        memory.prune(self.cache, "*.mp3", config.KEEP_TTS_FILES)
        memory.prune(self.cache, "*.wav", config.KEEP_TTS_FILES)
        self.wav_player = next(([c, *flags] for c, flags in (("aplay", ["-q"]), ("afplay", [])) if shutil.which(c)), None)
        # Loaded for either setting: when Microsoft refuses a sentence, the local voice
        # speaks it instead of the robotic espeak-ng one. Loading takes about 9 s on
        # the Pi, so when it is only the stand-in it loads while the robot starts.
        if config.VOICE_ENGINE == "piper":
            self.piper = self._load_piper()
        else:
            threading.Thread(target=lambda: setattr(self, "piper", self._load_piper()), daemon=True).start()
        # Timers speak from their own thread; one voice at a time, never two at once.
        self._lock = threading.Lock()
        # Clips already being made for what is said next (see prepare)
        self._prepared, self._prepared_lock = {}, threading.Lock()

    def _find_player(self):
        import shutil
        for cmd in ("afplay", "mpg123", "ffplay", "cvlc"):
            if shutil.which(cmd):
                return cmd
        return None

    def _load_piper(self):
        """The local voice, or None with the reason printed once."""
        model = config.MODELS_DIR / "piper" / f"{config.PIPER_VOICE[config.LANGUAGE]}.onnx"
        try:
            if self.wav_player is None:
                raise RuntimeError("no aplay to play it with")
            if not model.exists():
                raise FileNotFoundError(f"{model.name} is not in models/piper; see PIPER_VOICE in robo/config.py")
            from piper import PiperVoice
            t0 = time.time()
            voice = PiperVoice.load(str(model))
            config.log("voice", f"local voice {model.stem} loaded in {time.time() - t0:.1f} s")
            return voice
        except Exception as e:
            print(f"[voice] local voice not available ({e}); using the online voice")
            return None

    def _clip(self, sentence: str) -> list[str]:
        """The command that plays one sentence: made by the chosen voice, or by the
        other one when that fails. Raises when neither can make it."""
        # the chosen voice first, then the others in this order
        makers = {"google": self._google_clip, "edge": self._edge_clip, "piper": self._piper_command}
        first = makers.pop(config.VOICE_ENGINE, None)
        makers = [m for m in (first, *makers.values()) if m is not None]
        problem = None
        for make in makers:
            try:
                return make(sentence)
            except Exception as e:
                problem = e
                if not isinstance(e, NotAvailable):
                    print(f"[voice] {make.__name__.strip('_').split('_')[0]} voice failed ({str(e)[:80]}), trying the next voice")
        raise problem

    def _start_making(self, text: str):
        """Start making the clips of one piece of speech on a thread of its own.
        Returns (its sentences, the queue their play commands arrive in, an event
        that stops the making); a clip that cannot be made arrives as None."""
        import queue
        parts = speakable_parts(text)
        ready: queue.Queue = queue.Queue()
        give_up = threading.Event()

        def make():
            for part in parts:
                if give_up.is_set():
                    return
                try:
                    ready.put(self._clip(part))
                except Exception:
                    ready.put(None)
                    return

        threading.Thread(target=make, daemon=True).start()
        return parts, ready, give_up

    def prepare(self, text: str) -> None:
        """Start making the voice for a reply that is about to be said, while the
        thinking sound ends. say() with the same text then uses these clips. Any
        clips prepared earlier and never said (a "stop" came) are dropped."""
        from .face import stage_directions
        with self._prepared_lock:
            for _, _, give_up in self._prepared.values():
                give_up.set()
            self._prepared = {}
            for kind, value in stage_directions(text):
                if kind == "say" and value not in self._prepared:
                    self._prepared[value] = self._start_making(value)

    def _speak_in_sentences(self, text: str) -> str:
        """Speak sentence by sentence: the first one is heard while the next ones
        are still being made, so a long answer starts as fast as a short one.
        Returns the part that could not be spoken ("" when all of it was)."""
        import subprocess
        with self._prepared_lock:
            made = self._prepared.pop(text, None)
        parts, ready, give_up = made or self._start_making(text)
        for i in range(len(parts)):
            command = ready.get()
            if command is None:
                return " ".join(parts[i:])
            try:
                subprocess.run(command, check=True, env=sounds.player_env())
            except Exception as e:
                give_up.set()
                print(f"[voice] could not play a sentence ({e})")
                return " ".join(parts[i:])
        return ""

    def _piper_command(self, sentence: str) -> list[str]:
        if self.piper is None or self.wav_player is None:
            raise NotAvailable("the local voice is not loaded")
        return [*self.wav_player, str(self._piper_clip(sentence))]

    def _piper_clip(self, text: str):
        """One sentence as a WAV file in the cache."""
        import hashlib
        import shutil
        import subprocess
        import wave

        from piper import SynthesisConfig

        from .assistant import is_night
        name = config.PIPER_VOICE[config.LANGUAGE]
        # night is quieter; by day louder() below turns it up like the online voices
        volume = 0.35 if is_night() else 1.0
        gain = 1.0 if is_night() else config.SPEAKER_GAIN
        key = hashlib.sha1(f"{name}{config.VOICE_RATE}{config.VOICE_PITCH}{volume}{gain}{text}".encode()).hexdigest()[:16]
        path = self.cache / f"{key}.wav"
        if path.exists():
            return path
        t0 = time.time()
        part = path.with_suffix(".part")  # renamed when complete: a power cut leaves no half clip
        speed = 1 / (1 + _percent(config.VOICE_RATE) / 100)  # "+5%" faster = slightly shorter sounds
        try:
            with wave.open(str(part), "wb") as out:
                self.piper.synthesize_wav(text, out, syn_config=SynthesisConfig(volume=volume, length_scale=speed))
        except Exception:
            part.unlink(missing_ok=True)
            raise
        pitch = _percent(config.VOICE_PITCH)  # the silly voices: Piper has no pitch setting, sox does
        if pitch and shutil.which("sox"):
            shifted = path.with_suffix(".shift.wav")
            done = subprocess.run(["sox", str(part), str(shifted), "pitch", str(int(pitch * 8))],
                                  check=False, capture_output=True, env=sounds.player_env())
            if done.returncode == 0:
                shifted.replace(part)
        louder(part, gain)
        part.replace(path)
        memory.own(path)
        with wave.open(str(path)) as made:
            secs = made.getnframes() / made.getframerate()
        config.log("voice", f"{secs:.1f} s of speech made on the Pi in {time.time() - t0:.1f} s")
        return path

    face = None  # set by main; the mouth animates while speaking

    gesture = None  # set by main: a function that moves the head to suit a face

    def say(self, text: str) -> None:
        """Speak a reply. [face:...] and [sound:...] in it are not spoken: where
        one stands, the robot puts that face on (with its head gesture) or plays
        that sound, then carries on with the words."""
        from .face import stage_directions, without_faces
        print(f"{config.NAME}: {without_faces(text)}")
        steps = stage_directions(text)
        if not steps:
            return
        # Every piece of speech is made from now on, not when its turn comes: a
        # reply that opens with a sound (R2-D2's beeps start each of his) was
        # silent for the whole sound and then again while the words were made.
        with self._prepared_lock:
            for kind, value in steps:
                if kind == "say" and value not in self._prepared:
                    self._prepared[value] = self._start_making(value)
        with self._lock, sounds.ONE_AT_A_TIME:
            for kind, value in steps:
                try:
                    if kind == "say":
                        self._say(value)
                    elif kind == "sound":
                        config.log("sound", value)
                        sounds.play(value, speaker_is_ours=True)
                    elif self.face is not None:
                        config.log("face", value)
                        self.face.show(value, hold=None)
                        if self.gesture is not None:
                            self.gesture(value)
                except Exception as e:  # a face, gesture or sound must never cost the rest of the reply
                    if kind == "say":
                        raise
                    print(f"[voice] {kind} {value} failed: {e}")

    def _say(self, text: str) -> None:
        if self.face is not None:
            self.face.set_talking(True)
        try:
            text = self._speak_in_sentences(text)
            if not text:
                return
            import shutil
            import subprocess
            if self.espeak:
                from .assistant import is_night
                loud = 60 if is_night() else min(200, int(100 * config.SPEAKER_GAIN))  # espeak: 100 is normal, 200 the most
                say = [self.espeak, "-v", config.LANGUAGE, "-s", "150", "-a", str(loud)]
                if shutil.which("aplay"):
                    # through aplay, straight to the speaker: on its own espeak-ng first
                    # looks for a desktop sound service and prints warnings as root
                    made = subprocess.Popen([*say, "--stdout", "--", text], stdout=subprocess.PIPE, env=sounds.player_env())
                    subprocess.run(["aplay", "-q"], stdin=made.stdout, check=False, env=sounds.player_env())
                    made.wait()
                else:
                    subprocess.run([*say, "--", text], check=False, env=sounds.player_env())
                return
            if self.mac_say:
                subprocess.run(["say", text], check=False)
        finally:
            if self.face is not None:
                self.face.set_talking(False)

    def _player_command(self, path) -> list[str]:
        """The command that plays an MP3 clip, as loud as SPEAKER_GAIN says."""
        from .assistant import is_night
        # mpg123 -f scales the samples: 32768 is unchanged. At night the clip is already made quieter.
        # -o alsa plays straight to the speaker instead of looking for a desktop sound service first.
        gain = 1.0 if is_night() else config.SPEAKER_GAIN
        flags = {"afplay": [], "mpg123": ["-q", "-o", "alsa", "-f", str(int(32768 * gain))], "ffplay": ["-nodisp", "-autoexit", "-loglevel", "quiet"], "cvlc": ["--play-and-exit", "-q"]}[self.player]
        return [self.player, *flags, str(path)]

    def _google_clip(self, text: str) -> list[str]:
        """One sentence made by Google's voice (see GOOGLE_VOICE in config), as the
        command that plays it. Raises on any failure, so the next voice is used."""
        import hashlib

        from . import google_speech
        from .assistant import is_night
        if not self.player:
            raise NotAvailable("no player for the online voice")
        try:
            google_speech.key()
        except google_speech.NotAvailable as e:
            raise NotAvailable(str(e)) from None
        voice, quiet = config.GOOGLE_VOICE[config.LANGUAGE], is_night()
        key = hashlib.sha1(f"google{voice}{config.VOICE_RATE}{config.VOICE_PITCH}{quiet}{text}".encode()).hexdigest()[:16]
        path = self.cache / f"{key}.mp3"
        if not path.exists():
            t0 = time.time()
            audio = google_speech.synthesize(text, voice, config.VOICE_RATE, config.VOICE_PITCH, quiet=quiet)
            part = path.with_suffix(".part")  # renamed when complete: a power cut leaves no half clip
            try:
                part.write_bytes(audio)
                part.replace(path)
            except Exception:
                part.unlink(missing_ok=True)
                raise
            memory.own(path)
            config.log("voice", f"sentence made by Google in {time.time() - t0:.1f} s")
        return self._player_command(path)

    def _edge_clip(self, text: str) -> list[str]:
        """One sentence made by edge-tts, as the command that plays it. Raises on
        any failure, so the caller uses the other voice for this sentence."""
        import asyncio
        import hashlib
        if not self.player:
            raise NotAvailable("no player for the online voice")
        try:
            import edge_tts
        except ImportError:
            raise NotAvailable("edge-tts is not installed") from None
        from .assistant import is_night
        voice = config.VOICE[config.LANGUAGE]
        volume = "-35%" if is_night() else "+0%"
        key = hashlib.sha1(f"{voice}{config.VOICE_RATE}{config.VOICE_PITCH}{volume}{text}".encode()).hexdigest()[:16]
        path = self.cache / f"{key}.mp3"
        if not path.exists():
            part = path.with_suffix(".part")  # renamed when complete: a power cut leaves no half clip

            async def gen():
                await edge_tts.Communicate(text, voice, rate=config.VOICE_RATE, pitch=config.VOICE_PITCH, volume=volume).save(str(part))
            # The service now and then refuses a request with "403" and accepts
            # the same one a moment later, so a quick refusal is tried again.
            t0 = time.time()
            try:
                for attempt in range(3):
                    try:
                        asyncio.run(asyncio.wait_for(gen(), timeout=4))
                        break
                    except Exception as e:
                        # a refusal comes back at once and is tried again; a request
                        # that hangs is not: the local voice is quicker than waiting
                        if attempt == 2 or time.time() - t0 > 2.5:
                            raise
                        print(f"[voice] edge-tts refused ({str(e)[:60]}), trying again")
                        time.sleep(0.3)
            except Exception:
                part.unlink(missing_ok=True)  # not pruned like the finished clips
                raise
            part.replace(path)
            memory.own(path)
            config.log("voice", f"sentence made online in {time.time() - t0:.1f} s")
        return self._player_command(path)


def pick_microphone(names: list[str], wanted: str | None, warn: bool = True) -> int | None:
    """Index of the first input device whose name contains `wanted`, or None for
    the system default. The Robot HAT V4 has no microphone and its speaker card is
    often the default, so on this car the USB microphone has to be picked by name."""
    if not wanted:
        return None
    for i, name in enumerate(names):
        if wanted.lower() in (name or "").lower():
            return i
    if warn:
        print(f"[voice] no microphone named like {wanted!r} in {names}; using the default")
    return None


def arecord_device(wanted: str | None, root: str = "/proc/asound") -> str | None:
    """The ALSA name ("plughw:3,0") of the sound card to record from: the first
    card that can record and whose line in /proc/asound/cards contains `wanted`,
    else the first that can record. None when there is none, or no ALSA (a Mac)."""
    import glob
    import re
    try:
        with open(os.path.join(root, "cards")) as f:
            lines = f.read().splitlines()
    except OSError:
        return None
    found = []
    for i, line in enumerate(lines):
        m = re.match(r"\s*(\d+) \[", line)
        if m and glob.glob(os.path.join(root, f"card{m.group(1)}", "pcm*c")):
            found.append((m.group(1), line + " " + (lines[i + 1] if i + 1 < len(lines) else "")))
    for number, text in found:
        if wanted and wanted.lower() in text.lower():
            return f"plughw:{number},0"
    return f"plughw:{found[0][0]},0" if found else None


RUMBLE_BELOW_HZ = 200


class WithoutRumble:
    """Removes the low rumble from the microphone's sound as it arrives. The
    microphone sits on the car: wheels on the floor, a hand lifting it, a servo
    turning all arrive as thumps below 200 Hz. They are several times louder
    than a voice across the room, so they started recordings with no words in
    them (of four such recordings, three had 88 to 99% of their sound below
    300 Hz). Voices are understood just as well without that part.

    A second-order high-pass filter; it keeps its state between calls."""

    def __init__(self, rate: int = 16000, below_hz: float = RUMBLE_BELOW_HZ):
        import math
        w = 2 * math.pi * below_hz / rate
        alpha = math.sin(w) / (2 * 0.7071)
        a0 = 1 + alpha
        self.b = [(1 + math.cos(w)) / 2 / a0, -(1 + math.cos(w)) / a0, (1 + math.cos(w)) / 2 / a0]
        self.a = [1.0, -2 * math.cos(w) / a0, (1 - alpha) / a0]
        self.state = [0.0, 0.0]

    def __call__(self, pcm: bytes) -> bytes:
        import numpy
        x = numpy.frombuffer(pcm, dtype=numpy.int16).astype(numpy.float64)
        try:
            from scipy.signal import lfilter
            y, self.state = lfilter(self.b, self.a, x, zi=self.state)
        except ImportError:  # the same sums, one sample at a time
            (b0, b1, b2), (_, a1, a2), (z1, z2) = self.b, self.a, self.state
            y = numpy.empty_like(x)
            for i, v in enumerate(x.tolist()):
                out = b0 * v + z1
                z1 = b1 * v - a1 * out + z2
                z2 = b2 * v - a2 * out
                y[i] = out
            self.state = [z1, z2]
        return numpy.clip(y, -32768, 32767).astype(numpy.int16).tobytes()


def arecord_microphone(sr, device: str, during_motors: bool = False):
    """A microphone for the SpeechRecognition library that reads from the arecord
    command instead of PyAudio. Measured on this car with a tone from its own
    speaker: through PyAudio about a third of the sound went missing (a one second
    pause came out as 0.6 s, so "hey r2-d2 what do you see" arrived squeezed and
    was not understood); through arecord every sample arrived."""
    import subprocess

    from .car import motor_noise

    class Arecord(sr.AudioSource):
        SAMPLE_RATE, SAMPLE_WIDTH, CHUNK = 16000, 2, 1600  # read 0.1 s at a time

        def __init__(self):
            self.stream = self.proc = None
            self.without_rumble = WithoutRumble()

        def __enter__(self):
            self.proc = subprocess.Popen(
                ["arecord", "-q", "-D", device, "-f", "S16_LE", "-r", "16000", "-c", "1", "-t", "raw"],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=sounds.player_env())
            self.stream = self
            return self

        def read(self, size: int) -> bytes:
            data = self.proc.stdout.read(size * 2)
            if len(data) < size * 2:
                raise OSError(f"the microphone {device} gave no sound (unplugged, or in use by another program)")
            data = self.without_rumble(data)
            # see MOTOR_NOISE_AFTER_S in car.py; the listener for "stop" hears through it
            if motor_noise() and not during_motors:
                return bytes(len(data))
            return data

        def __exit__(self, *exc):
            self.proc.terminate()
            self.proc.stdout.close()
            self.proc.wait()
            self.stream = self.proc = None

    return Arecord()


WAKE_LEAD_MAX_S = 0.6   # other speech allowed before the name ("um, r2-d2 ...")


def wake_end(words: list[dict], sounds_like: str) -> float | None:
    """Where the wake name ends in a recording, in seconds, or None if the
    recording does not start with it. words is Vosk's word list from the pass
    limited to the sounds-like words. The last three words in a row are enough:
    "R2-D2" on its own often comes out as "two d two" without the leading "are".

    The name has to open the phrase, so "who is r2-d2 in the film" stays a normal
    sentence. It also has to be followed by other speech or by nothing: ordinary
    talk such as "what are we going to do today" can come out as "two d two d
    hey", the name's own words running on."""
    name = sounds_like.split()
    want = name[-3:]
    heard = [w["word"] for w in words]
    for i in range(len(heard) - len(want) + 1):
        if heard[i:i + len(want)] != want:
            continue
        lead = sum(w["end"] - w["start"] for w in words[:i] if w["word"] not in ("hey", *name))
        after = heard[i + len(want)] if i + len(want) < len(heard) else None
        if lead <= WAKE_LEAD_MAX_S and after not in name:
            return float(words[i + len(want) - 1]["end"])
        return None
    return None


STOP_OTHER_MAX_S = 1.2   # "hey r2-d2 stop" has about 1.1 s of other speech; sentences have more
STOP_BOTH_SIDES_MAX_S = 0.6


def is_stop_phrase(words: list[dict]) -> bool:
    """True when a recording is a stop command rather than a sentence that happens
    to contain a stop word. words is Vosk's word list from the pass limited to the
    stop words; everything else comes back as "[unk]", and several unknown words
    in a row are merged into one, so counting words does not work. What separates
    the two is time: a command ("stop", "r2-d2 stop", "stop right there") has
    little other speech, and only before or only after the stop word. "I will
    stop when I get to the door" has it on both sides."""
    stops = [i for i, w in enumerate(words) if w["word"] in config.STOP_WORDS]
    if not stops:
        return False
    other = sum(w["end"] - w["start"] for w in words if w["word"] not in config.STOP_WORDS)
    both_sides = stops[0] > 0 and stops[-1] < len(words) - 1
    return other <= (STOP_BOTH_SIDES_MAX_S if both_sides else STOP_OTHER_MAX_S)


@contextlib.contextmanager
def quiet_stderr():
    """On the Pi, every time the microphone is opened the ALSA and JACK libraries
    print some 200 lines about sound devices that do not exist ("Unknown PCM
    surround51", "jack server is not running"). They are harmless and bury the
    robot's own output, so the error stream is closed off while that happens."""
    sys.stderr.flush()
    saved, null = os.dup(2), os.open(os.devnull, os.O_WRONLY)
    try:
        os.dup2(null, 2)
        yield
    finally:
        os.dup2(saved, 2)
        os.close(saved); os.close(null)


QUIET_KEPT_S = 0.3   # quiet left around the words when the rest is cut off


def loudness(pcm: bytes) -> tuple[int, int]:
    """(loudest sample, average level) of a recording; samples go up to 32768."""
    import numpy
    a = numpy.frombuffer(pcm, dtype=numpy.int16).astype(numpy.float32)
    if not len(a):
        return 0, 0
    return int(abs(a).max()), int(numpy.sqrt((a ** 2).mean()))


def trim_quiet(pcm: bytes) -> tuple[bytes, float]:
    """Cut the quiet off both ends of a recording. Returns (the rest, seconds removed).

    The microphone recording begins up to a second before the first word and ends
    a second after the last. Moonshine returns no text at all for a recording that
    starts with about 1.5 s of quiet, so only QUIET_KEPT_S is left on each side.
    A stretch counts as speech when it is clearly louder than the quietest tenth
    of the recording and at least a tenth as loud as its loudest stretch."""
    import numpy
    step = 320  # 20 ms at 16000 samples a second
    a = numpy.frombuffer(pcm, dtype=numpy.int16).astype(numpy.float32)
    pieces = a[:len(a) // step * step].reshape(-1, step)
    if not len(pieces):
        return pcm, 0.0
    level = numpy.sqrt((pieces ** 2).mean(axis=1))
    loud = numpy.nonzero(level > max(numpy.percentile(level, 10) * 3, level.max() * 0.1))[0]
    if not len(loud):  # the same level all the way through: nothing to cut
        return pcm, 0.0
    keep = int(QUIET_KEPT_S * 16000)
    start = max(0, int(loud[0]) * step - keep)
    end = min(len(a), (int(loud[-1]) + 1) * step + keep)
    return pcm[start * 2:end * 2], (len(a) - (end - start)) / 16000


class Moonshine:
    """The more accurate recognizer (see LISTEN_ENGINE in config). Runs on the Pi
    with onnxruntime; the work grows with the length of the recording, so a short
    sentence takes well under a second."""

    def __init__(self, name: str):
        # keep the downloaded model inside the repo, not in a hidden folder of whoever runs this
        os.environ.setdefault("HF_HOME", str(config.MODELS_DIR / "huggingface"))
        import numpy
        from moonshine_onnx import MoonshineOnnxModel, load_tokenizer
        self.np = numpy
        self.model = MoonshineOnnxModel(model_name=name)
        self.tokenizer = load_tokenizer()

    def text(self, pcm: bytes) -> str:
        secs = len(pcm) / 32000
        if secs < 0.3:
            return ""
        audio = (self.np.frombuffer(pcm, dtype=self.np.int16).astype(self.np.float32) / 32768.0)[self.np.newaxis, :]
        # speech is at most about 6 word pieces a second; the limit stops it inventing a long text from noise
        tokens = self.model.generate(audio, max_len=int(secs * 6.5) + 8)
        return self.tokenizer.decode_batch(tokens)[0].strip()


def spell_name(text: str) -> str:
    """Rewrite every way the recognizer spells the name (WAKE_WRITTEN_AS) as the
    name itself: "Hey are 2d2, what do you see?" -> "hey r2-d2 , what do you see?"."""
    import re
    text = text.lower()
    if config.WAKE_WRITTEN_AS:
        text = re.sub(config.WAKE_WRITTEN_AS, f" {config.NAME.lower()} ", text)
    return " ".join(text.split())


class Voice:
    def __init__(self):
        import speech_recognition as sr
        from vosk import Model, SetLogLevel
        SetLogLevel(-1)  # no "LOG (VoskAPI:...)" lines for every recording

        model_dir = config.MODELS_DIR / config.VOSK_MODELS[config.LANGUAGE]
        if not model_dir.exists():
            raise FileNotFoundError(
                f"Vosk model missing at {model_dir}. See README step 3.")
        self.sr = sr
        self._mic_names = None
        self.pick_microphone()
        self.recognizer = sr.Recognizer()
        # How loud a sound must be to start a recording. The library's default
        # moves this level with every sound it hears while waiting, several times
        # a second: the quiet start of a sentence ("hey") pushed it up, and the
        # recording then began in the middle ("he are you see" for "hey r2-d2,
        # what do you see"). It is now measured from a second of room noise at
        # most once a minute and otherwise left alone.
        self.recognizer.dynamic_energy_threshold = False
        self.recognizer.dynamic_energy_ratio = 1.5       # start level = room noise x this
        self.recognizer.pause_threshold = 0.8            # a silence this long ends the sentence
        self.recognizer.non_speaking_duration = 0.8      # kept from before the first loud sound
        self.vosk_model = Model(str(model_dir))
        self.moonshine = None
        # also the stand-in for Google's recognizer: without a key, offline, and for
        # everything said without the name outside a conversation
        if config.LISTEN_ENGINE in ("moonshine", "google") and config.LANGUAGE == "en":
            try:
                t0 = time.time()
                with quiet_stderr():
                    self.moonshine = Moonshine(config.MOONSHINE_MODEL)
                config.log("ears", f"recognizer {config.MOONSHINE_MODEL} loaded in {time.time() - t0:.1f} s")
            except Exception as e:
                print(f"[voice] the better recognizer is not available ({e}); using the small Vosk model")
        self.speaker = Speaker()
        self._calibrated = 0.0
        # Until then everything heard is taken as a request (main sets it after an
        # answer, for the follow-up time), so Google may write it down
        self.conversation_until = 0.0

    def pick_microphone(self) -> None:
        """Called at startup and again after a failed listen, so a USB microphone
        plugged in later (or one that got a new index) is found."""
        try:
            with quiet_stderr():
                names = self.sr.Microphone.list_microphone_names()
        except Exception:
            names = []
        # this runs every few seconds while no microphone is plugged in: say it once
        self.mic_index = pick_microphone(names, config.MIC_NAME, warn=names != self._mic_names)
        self._mic_names = names

    @contextlib.contextmanager
    def _microphone(self, during_motors: bool = False):
        import shutil
        device = arecord_device(config.MIC_NAME) if shutil.which("arecord") else None
        if device:  # the Pi: see arecord_microphone for why
            with arecord_microphone(self.sr, device, during_motors) as source:
                yield source
            return
        # chunk_size 8192: SunFounder's note, smaller chunks can freeze the Pi.
        with quiet_stderr():  # creating it and opening it each start the sound libraries
            mic = self.sr.Microphone(device_index=self.mic_index, chunk_size=8192)
            source = mic.__enter__()
        try:
            yield source
        finally:
            mic.__exit__(None, None, None)

    def listen(self, timeout: float | None = None) -> str:
        """Block until one phrase is heard. Returns lowercase text, '' if nothing.
        The room-noise calibration runs only while waiting for the wake word, at
        most once a minute; a follow-up listen (with a timeout, right after "Yes?")
        starts recording at once, so the first words are not taken for noise."""
        with self._microphone() as source:
            if timeout is None and time.time() - self._calibrated > 60:
                from .car import motor_noise
                before, t0 = self.recognizer.energy_threshold, time.time()
                self.recognizer.adjust_for_ambient_noise(source, duration=1.0)
                # never deaf: a measurement taken while someone talks would be far too high
                self.recognizer.energy_threshold = max(config.MIC_START_LEVEL_MIN,
                                                       min(self.recognizer.energy_threshold, config.MIC_START_LEVEL_MAX))
                if motor_noise(since=t0):
                    # the microphone was shut off for the motors: that second measured
                    # nothing, and a level near zero would record every rustle
                    self.recognizer.energy_threshold = before
                else:
                    self._calibrated = time.time()
                from . import selfcheck
                selfcheck.log_computer()  # once a minute while waiting
            config.log("ears", ("listening for your answer" if timeout else "listening")
                       + f" (a sound louder than {self.recognizer.energy_threshold:.0f} starts a recording)")
            try:
                audio = self.recognizer.listen(source, timeout=timeout, phrase_time_limit=10)
            except self.sr.WaitTimeoutError:
                config.log("ears", "nothing said")
                return ""
        pcm = audio.get_raw_data(convert_rate=16000, convert_width=2)
        t0 = time.time()
        self._note_recording(pcm)
        end = self._wake_end(pcm)
        if end is not None:  # the name was said: the request is what comes after it
            cut = max(0, int((end - 0.1) * 16000)) * 2  # a little early, so the next word is whole
            text = f"{config.WAKE_WORDS[0]} {self._transcribe(pcm[cut:], for_me=True)}".strip()
        else:
            # "Yes?" was just asked, or a conversation is going on: it is meant for the robot
            text = self._transcribe(pcm, for_me=timeout is not None or time.time() < self.conversation_until)
        config.log("ears", f"heard {text!r} ({len(pcm) / 32000:.1f} s of sound, {time.time() - t0:.1f} s to understand)")
        return text

    def _recognizer(self, words: tuple = ()):
        """A new Vosk recognizer limited to these words, or a free one for (). A
        recognizer that has given its result cannot be relied on for a second
        recording (reusing one after Reset() returned empty text in testing)."""
        from vosk import KaldiRecognizer
        rec = KaldiRecognizer(self.vosk_model, 16000, json.dumps(list(words))) if words else KaldiRecognizer_cached(self.vosk_model)
        rec.SetWords(True)
        return rec

    def _note_recording(self, pcm: bytes) -> None:
        """Progress line about what the microphone recorded, and the recording
        itself as a sound file (see KEEP_RECORDINGS in config)."""
        try:
            peak, average = loudness(pcm)
            saved = ""
            if config.KEEP_RECORDINGS and config.SHOW_PROGRESS:
                import wave
                folder = memory.make_dir(config.RECORDINGS_DIR)
                path = folder / f"{time.strftime('%Y%m%d-%H%M%S')}.wav"
                with wave.open(str(path), "wb") as out:
                    out.setnchannels(1); out.setsampwidth(2); out.setframerate(16000)
                    out.writeframes(pcm)
                memory.own(path)
                memory.prune(folder, "*.wav", config.KEEP_RECORDINGS)
                saved = f", saved as recordings/{path.name}"
            config.log("ears", f"recorded {len(pcm) / 32000:.1f} s (loudest point {peak} of 32768, average {average}){saved}")
        except Exception as e:  # a full SD card must not stop the robot hearing
            config.log("ears", f"could not note the recording: {e}")

    def _transcribe(self, pcm: bytes, for_me: bool = False) -> str:
        """The words in a recording. With LISTEN_ENGINE = "google", only speech meant
        for the robot (for_me: after its name, after "Yes?", or in a conversation)
        goes to Google; the room's other talk and the television stay on the Pi."""
        if for_me and config.LISTEN_ENGINE == "google":
            from . import google_speech
            try:
                t0 = time.time()
                speech, _ = trim_quiet(pcm)
                if len(speech) / 32000 < 0.3:
                    return ""
                wrote = google_speech.transcribe(speech, config.GOOGLE_LISTEN_LANGUAGE[config.LANGUAGE], [config.NAME, *config.WAKE_WORDS])
                config.log("ears", f"Google wrote {wrote!r} in {time.time() - t0:.1f} s ({len(speech) / 32000:.1f} s of sound)")
                return spell_name(wrote)
            except google_speech.NotAvailable:
                pass
            except Exception as e:  # offline, quota, a wrong key: the Pi listens itself this time
                print(f"[voice] Google's recognizer failed ({str(e)[:100]}); using the one on the Pi")
        if self.moonshine is not None:
            try:
                t0 = time.time()
                speech, removed = trim_quiet(pcm)
                wrote = self.moonshine.text(speech)
                config.log("ears", f"{config.MOONSHINE_MODEL} wrote {wrote!r} in {time.time() - t0:.1f} s"
                           f" ({len(speech) / 32000:.1f} s of sound after {removed:.1f} s of quiet was cut off)")
                # Nothing written means noise (a door, the motors). The small Vosk model
                # is not asked as well: it took up to 4 s per noise, in which the robot
                # heard nobody, and then wrote words nobody had said.
                return spell_name(wrote)
            except Exception as e:
                print(f"[voice] the better recognizer failed ({e}); using the small Vosk model")
                self.moonshine = None
        t0 = time.time()
        rec = self._recognizer()
        rec.AcceptWaveform(pcm)
        text = json.loads(rec.FinalResult()).get("text", "").strip().lower()
        config.log("ears", f"the small Vosk model wrote {text!r} in {time.time() - t0:.1f} s")
        return text

    def _wake_end(self, pcm: bytes) -> float | None:
        """See WAKE_SOUNDS_LIKE in config: a second pass that knows only the name."""
        if not config.WAKE_SOUNDS_LIKE:
            return None
        t0 = time.time()
        rec = self._recognizer((config.WAKE_SOUNDS_LIKE, "hey", "[unk]"))
        rec.AcceptWaveform(pcm)
        words = json.loads(rec.FinalResult()).get("result", [])
        end = wake_end(words, config.WAKE_SOUNDS_LIKE)
        # "[unk]" stands for any speech that is not one of the name's words
        config.log("ears", f"name check heard {' '.join(w['word'] for w in words)!r} in {time.time() - t0:.1f} s: "
                   + ("my name is not at the start" if end is None else f"my name ends at {end:.1f} s"))
        return end

    def hear_stop(self, timeout: float = 1.0) -> bool:
        """Listen briefly for a stop word only (used while a request runs). Vosk with a
        small grammar is quick and does not mistake other words for "stop". Only a
        command counts (see is_stop_phrase): the robot's own speech and the
        television say "I will stop at the door" too. Unlike listen(), this hears
        while the motors run: that is when "stop" matters most."""
        with self._microphone(during_motors=True) as source:
            try:
                audio = self.recognizer.listen(source, timeout=timeout, phrase_time_limit=2)
            except self.sr.WaitTimeoutError:
                return False
        rec = self._recognizer((*config.STOP_WORDS, "[unk]"))
        rec.AcceptWaveform(audio.get_raw_data(convert_rate=16000, convert_width=2))
        return is_stop_phrase(json.loads(rec.FinalResult()).get("result", []))

    @property
    def face(self):
        return self.speaker.face

    @face.setter
    def face(self, f):
        self.speaker.face = f

    def say(self, text: str) -> None:
        self.speaker.say(text)

    def prepare(self, text: str) -> None:
        self.speaker.prepare(text)


def KaldiRecognizer_cached(model):
    from vosk import KaldiRecognizer
    return KaldiRecognizer(model, 16000)


class KeyboardVoice:
    """Type instead of talk. Still speaks through the same Speaker as the robot,
    so the voice heard on the Mac is the voice the robot will have."""

    def __init__(self):
        self.speaker = Speaker()

    def listen(self, timeout=None) -> str:
        try:
            return input("you: ").strip().lower()
        except EOFError:
            sys.exit(0)

    @property
    def face(self):
        return self.speaker.face

    @face.setter
    def face(self, f):
        self.speaker.face = f

    def say(self, text: str) -> None:
        self.speaker.say(text)

    def prepare(self, text: str) -> None:
        self.speaker.prepare(text)


class SpeakOnlyVoice:
    """Stands in when the ears cannot start (speech model or a package missing).
    The robot can still say what is wrong instead of restarting in silence."""

    def __init__(self, reason: str):
        self.reason = reason
        self.cannot_hear = "I cannot listen. My speech model or one of my programs is missing."
        self.speaker = Speaker()

    def listen(self, timeout=None) -> str:
        raise RuntimeError(self.reason)

    @property
    def face(self):
        return self.speaker.face

    @face.setter
    def face(self, f):
        self.speaker.face = f

    def say(self, text: str) -> None:
        self.speaker.say(text)

    def prepare(self, text: str) -> None:
        self.speaker.prepare(text)


def make_voice(keyboard: bool):
    if keyboard:
        return KeyboardVoice()
    try:
        return Voice()
    except Exception as e:
        print(f"[voice] ears not working ({e}), speaking only")
        return SpeakOnlyVoice(str(e))
