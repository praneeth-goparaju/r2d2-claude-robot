"""The assistant loop: wait for the wake word, listen, think, act, speak."""
import argparse
import re
import threading
import time

from . import config, memory
from .assistant import DailyCap
from .brain import OfflineBrain, make_brain
from .camera import make_camera
from .car import BODY, STOP, exit_on_signals, make_car
from .face import make_face
from .voice import make_voice


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=f"{config.NAME} assistant")
    p.add_argument("--mock", action="store_true", help="fake car and camera (Mac)")
    p.add_argument("--keyboard", action="store_true", help="type instead of speaking")
    p.add_argument("--mock-brain", action="store_true", help="no Claude at all, scripted replies")
    p.add_argument("--no-wake", action="store_true", help="skip the wake word")
    p.add_argument("--button", action="store_true",
                   help="push-to-talk: wait for the button on Robot HAT pin D0 instead of a wake word")
    return p.parse_args(argv)


def heard_wake_word(text: str) -> str | None:
    """Return the request after the wake word, or None. Whole words only, longest
    wake word first, so "hey robot, come here" gives "come here" (not "t, come here")
    and "my robot toy" does not wake the robot at all."""
    for w in sorted(config.WAKE_WORDS, key=len, reverse=True):
        m = re.search(rf"\b{re.escape(w)}\b", text)
        if m:
            return text[m.end():].strip(" ,.!?")
    return None


def is_stop(text: str) -> bool:
    """"stop", "please stop", "stop stop stop stop": a stop word with at most two
    other words around it."""
    words = re.findall(r"[^\W\d_]+", text.lower())
    stops = sum(w in config.STOP_WORDS for w in words)
    return stops > 0 and len(words) - stops <= 2


def without_wake_word(text: str) -> str:
    """For push-to-talk and the follow-up after "Yes?": the name is not needed
    there, but people say it anyway ("r2-d2, stop")."""
    rest = heard_wake_word(text)
    return text if rest is None else rest


def ends_conversation(text: str) -> bool:
    """"Bye", "thank you.", "That's all!": the follow-up window closes. Checked
    before the two-word minimum for a follow-up, since most of these are one word."""
    return text.lower().strip(" ,.!?") in config.FOLLOW_UP_END_WORDS


def ends_with_question(reply: str) -> bool:
    """Did the robot's answer end by asking something back?"""
    from .face import without_faces
    return without_faces(reply).strip().rstrip("\"')*_ ").endswith("?")


class Ears:
    """voice.listen() that survives a missing microphone. The Robot HAT V4 has
    none, so without a USB microphone every listen fails. Instead of crashing (and
    systemd restarting it in a loop), the robot says once that it cannot hear,
    then quietly tries again every few seconds, so plugging one in just works."""
    RETRY_S = 10

    def __init__(self, voice, sleep=time.sleep):
        self.voice, self.sleep, self.deaf = voice, sleep, False

    def listen(self, timeout: float | None = None) -> str:
        try:
            text = self.voice.listen(timeout=timeout) if timeout is not None else self.voice.listen()
        except Exception as e:
            if not self.deaf:
                print(f"[voice] cannot listen: {e}")
                self.voice.say(getattr(self.voice, "cannot_hear", "I cannot hear anything. Please plug a USB microphone into me."))
                self.deaf = True
            self.sleep(self.RETRY_S)
            repick = getattr(self.voice, "pick_microphone", None)
            if repick:
                repick()  # it may have been plugged in since
            return ""
        if self.deaf:
            self.deaf = False
            self.voice.say("I can hear you now.")
        return text


class StopWatcher:
    """While a request runs, listen for a stop word and watch the push-to-talk
    button on background threads. A hit sets car.STOP and stops the motors at
    once, without waiting for Claude. Use as a context manager around handle()."""

    def __init__(self, car, voice, button=None, brain=None):
        self.car, self.voice, self.button, self.brain = car, voice, button, brain
        self.active = threading.Event()
        self.threads: list[threading.Thread] = []

    def __enter__(self):
        STOP.clear()
        self.active.set()
        jobs = []
        if hasattr(self.voice, "hear_stop"):
            jobs.append(self._listen)
        if self.button is not None:
            jobs.append(self._watch_button)
        self.threads = [threading.Thread(target=j, daemon=True) for j in jobs]
        for t in self.threads:
            t.start()
        return self

    def __exit__(self, *exc):
        self.active.clear()
        for t in self.threads:
            t.join(timeout=5)  # the microphone must be free before the next listen()
        return False

    def _hit(self, why: str) -> None:
        if STOP.is_set():
            return
        STOP.set()
        print(f"[stop] {why}")
        try:
            self.car.stop()
        except Exception as e:
            print(f"[stop] {e}")
        interrupt = getattr(self.brain, "interrupt", None)
        if interrupt:
            interrupt()

    def _listen(self) -> None:
        while self.active.is_set() and not STOP.is_set():
            try:
                if self.voice.hear_stop(timeout=1):
                    self._hit("heard a stop word")
            except Exception as e:
                print(f"[stop] listener off: {e}")
                return

    def _watch_button(self) -> None:
        while self.active.is_set() and not STOP.is_set():
            if self.button.value() == 0:
                self._hit("button pressed")
            time.sleep(0.03)


class Thinking:
    """Sounds while a request is worked on (see THINKING_SOUND in config). Use as a
    context manager around handle(); leaving it waits for the sound that is
    playing, so the answer does not start on top of it."""

    def __init__(self, play=None):
        from . import sounds
        self.play = play or sounds.play
        self.done = threading.Event()
        self.thread = None

    def _sounds(self) -> None:
        import random

        from . import sounds
        try:
            self.play("chirp")
            last = None
            # a different mutter each time, with pauses of uneven length, like someone thinking aloud
            while not self.done.wait(config.THINKING_SOUND_EVERY_S * random.uniform(0.6, 1.2)):
                last = random.choice([n for n in sounds.THINKING if n != last])
                self.play(last)
        except Exception as e:  # a sound that cannot be played must not end the request
            print(f"[sounds] {e}")

    def __enter__(self):
        if config.THINKING_SOUND:
            self.thread = threading.Thread(target=self._sounds, daemon=True)
            self.thread.start()
        return self

    def __exit__(self, *exc):
        self.done.set()
        if self.thread is not None:
            self.thread.join(timeout=3)
        return False


def _make_button():
    """A momentary button between Robot HAT pin D0 and GND. Pi only."""
    from robot_hat import Pin
    return Pin("D0", mode=Pin.IN, pull=Pin.PULL_UP)


def _wait_for_press(button) -> None:
    print("[button] waiting for press")
    while button.value() == 1:   # pulled up, pressed reads 0
        time.sleep(0.05)
    while button.value() == 0:   # wait for release so one press is one turn
        time.sleep(0.05)


class BatteryWatch:
    """Keeps an eye on the battery in the background. Below BATTERY_HUNGRY_V the
    screen shows a battery with "Charge me!" every BATTERY_NOTICE_EVERY_S seconds,
    and the robot says once that it needs charging (not at night)."""

    def __init__(self, car, face, voice, sleep=time.sleep):
        self.car, self.face, self.voice, self.sleep = car, face, voice, sleep
        self.said = False

    def check(self) -> bool:
        """One look at the battery. True when the notice was shown."""
        from .assistant import is_night
        volts = self.car.battery_volts()
        if not 0 < volts < config.BATTERY_HUNGRY_V:   # fine, or no reading at all
            self.said = self.said and volts < config.BATTERY_HUNGRY_V + 0.3   # charged again: may say it next time
            return False
        config.log("battery", f"{volts:.2f} V, below {config.BATTERY_HUNGRY_V} V: asking to be charged")
        self.face.show_battery(volts)
        if not self.said and not is_night():
            self.said = True
            self.voice.say("My battery is getting low. Please charge me soon.")
        return True

    def start(self) -> None:
        def loop():
            while True:
                self.sleep(config.BATTERY_NOTICE_EVERY_S)
                try:
                    self.check()
                except Exception as e:
                    print(f"[battery] {e}")
        threading.Thread(target=loop, daemon=True, name="battery").start()


class Idle:
    """When nobody has talked for a while, the robot looks around, blinks and
    occasionally hums, so it feels alive instead of switched off. Pauses while
    a request is being handled and at night."""

    def __init__(self, car, face):
        import random
        import threading

        from . import sounds
        from .assistant import is_night
        self.car, self.face, self.busy = car, face, False
        self.last_activity = time.time()
        def loop():
            while True:
                time.sleep(random.uniform(25, 70))
                if self.busy or is_night() or time.time() - self.last_activity < 20:
                    continue
                choice = random.choice(["look_around", "look_around", "nod", "wiggle", "hum"])
                if choice == "hum":
                    try:
                        sounds.play("think")
                    except Exception as e:
                        print(f"[idle] {e}")
                    continue
                if not BODY.acquire(blocking=False):  # the brain is using the body
                    continue
                try:
                    if not self.busy:
                        self.face.show("thinking", hold=2)
                        self.car.trick(choice)
                except Exception as e:
                    print(f"[idle] {e}")
                finally:
                    BODY.release()
        threading.Thread(target=loop, daemon=True).start()


def run(args) -> None:
    exit_on_signals()  # systemctl stop must reach the finally below, which stops the motors
    memory.restore_name()  # a renamed robot keeps its name after a restart
    from . import selfcheck, sounds

    def started(part: str, make):
        t0 = time.monotonic()  # the clock jumps when the Pi gets the time from the internet
        made = make()
        config.log("start", f"{part} ready in {time.monotonic() - t0:.1f} s")
        return made

    selfcheck.log_computer()
    car = started("car", lambda: make_car(args.mock))
    camera = started("camera", lambda: make_camera(args.mock))
    voice = started("ears and voice", lambda: make_voice(args.keyboard))
    face = make_face(args.mock)
    car.face = face  # eyes follow the camera
    voice.face = face  # mouth moves while talking
    voice.speaker.gesture = car.gesture  # and the head moves to suit the face it puts on
    try:
        brain = make_brain(car, camera, voice, face, mock_brain=args.mock_brain)
    except Exception as e:  # keep running and say so, instead of a silent restart loop
        print(f"[brain] could not start: {e}")
        brain = OfflineBrain(str(e))
    button = _make_button() if args.button and not args.mock else None
    cap = DailyCap(config.MAX_TURNS_PER_DAY)
    idle = Idle(car, face)
    ears = Ears(voice)
    if not args.mock:
        BatteryWatch(car, face, voice).start()
    if not args.mock:  # drive with the Xbox controller while the robot listens and talks

        def controller_used():
            idle.last_activity = time.time()  # no looking around on its own while someone drives

        def end_request():  # B on the controller: like a spoken "stop", Claude is asked to stop too
            STOP.set()
            interrupt = getattr(brain, "interrupt", None)
            if interrupt:
                interrupt()

        from . import controller
        controller.run_in_background(car, camera, busy=lambda: idle.busy, on_use=controller_used,
                                     end_request=end_request)

    awake_until = 0.0  # until then a sentence without the name is taken as a request too
    asked_question = False  # the robot's last sentence was a question: a one-word answer counts
    face.show("happy")
    sounds.play("hello")
    checks = started("self-check", lambda: selfcheck.run(car, camera, voice, face, brain))
    print(selfcheck.text(checks))
    selfcheck.log_computer()
    bad = [n for n, ok, _ in checks if not ok]
    voice.say(f"{config.NAME} is ready." if not bad else f"{config.NAME} is ready, but please check my " + " and ".join(bad) + ".")
    try:
        while True:
            if button is not None:
                _wait_for_press(button)
                face.show("listening", hold=None)
                voice.say("Yes?")
                text = ears.listen(timeout=6)
                face.show("neutral", hold=None)
                if not text:
                    continue
                request = without_wake_word(text)
                if not request:
                    continue
            else:
                text = ears.listen()
                if not text:
                    continue
                request = None
            if request is not None:
                pass
            elif args.no_wake or args.keyboard:
                request = text
            else:
                request = heard_wake_word(text)
                if request is None and time.time() < awake_until:
                    if ends_conversation(text):
                        awake_until = 0.0
                        if hasattr(voice, "conversation_until"):
                            voice.conversation_until = 0.0
                        config.log("wake", "conversation ended; say my name to wake me")
                        voice.say("Okay.")
                        continue
                    if len(text.split()) >= (1 if asked_question else 2):
                        request = text  # still in conversation: no name needed
                if request is None:
                    config.log("wake", "my name was not in that, ignored")
                    continue
                if request == "":
                    voice.say("Yes?")
                    request = without_wake_word(ears.listen(timeout=6))
                    if not request:
                        continue
            if is_stop(request):
                car.stop(); car.reset()
                voice.say("Stopped.")
                continue
            if not cap.allow():
                voice.say("I have talked a lot today. Let's play again tomorrow.")
                continue
            t0 = time.monotonic()
            reply = ""
            idle.busy = True
            config.log("wake", f"request: {request!r}")
            try:
                face.show("thinking", hold=None)
                if config.SCREEN_SHOWS_REQUEST_S:
                    face.show_text(request, config.SCREEN_SHOWS_REQUEST_S, title="I heard:")
                with StopWatcher(car, voice, button, brain), Thinking():
                    reply = brain.handle(request)
                    if hasattr(voice, "prepare") and not STOP.is_set():
                        voice.prepare(reply)  # the words are made while the thinking sound ends
                if STOP.is_set():
                    car.stop(); reply = "Okay, I stopped."
                config.log("brain", f"answer ready after {time.monotonic() - t0:.1f} s in total")
                voice.say(reply)
                face.show("neutral", hold=None)
            except Exception as e:  # one bad request must not end the robot
                print(f"[main] request failed: {e!r}")
                car.stop()
                voice.say("Something went wrong with that. Ask me again?")
            finally:
                idle.busy = False; idle.last_activity = time.time()
                STOP.clear()  # a "stop" ends that request only; the controller can drive again
                selfcheck.log_computer()
            if config.FOLLOW_UP_SECONDS and button is None and not (args.no_wake or args.keyboard):
                asked_question = ends_with_question(reply)
                wait = config.FOLLOW_UP_AFTER_QUESTION_SECONDS if asked_question else config.FOLLOW_UP_SECONDS
                awake_until = time.time() + wait
                if hasattr(voice, "conversation_until"):
                    voice.conversation_until = awake_until
                config.log("wake", f"for the next {wait} s you can talk to me without my name"
                           + (" (I asked something: one word is enough)" if asked_question else ""))
    except KeyboardInterrupt:
        pass
    finally:
        car.stop(); car.reset(); camera.close(); brain.close(); face.close()


if __name__ == "__main__":
    run(parse_args())
