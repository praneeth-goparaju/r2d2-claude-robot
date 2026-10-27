"""Tests for the bugs found in the October 2026 repo review: python -m unittest -v"""
import os
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch

from robo import config


class FakePx:
    """Stands in for picarx.Picarx so the real Car's safety code runs without hardware."""

    def __init__(self, distance=100.0, cliff=False):
        self.distance, self.cliff_now, self.log = distance, cliff, []

    def get_distance(self):
        if isinstance(self.distance, Exception):
            raise self.distance
        return self.distance

    def get_grayscale_data(self):
        return [1000, 1000, 1000]

    def get_cliff_status(self, data):
        return self.cliff_now

    def forward(self, speed): self.log.append(("forward", speed))
    def backward(self, speed): self.log.append(("backward", speed))
    def stop(self): self.log.append(("stop",))
    def set_dir_servo_angle(self, a): self.log.append(("steer", a))
    def set_cam_pan_angle(self, a): self.log.append(("pan", a))
    def set_cam_tilt_angle(self, a): self.log.append(("tilt", a))
    def reset(self): self.log.append(("reset",))


def real_car(px, volts=8.0):
    from robo.car import Car
    car = Car.__new__(Car)  # skip __init__: it imports picarx
    car.px, car._moving = px, None
    car.battery_volts = lambda: volts
    return car


class Daytime(unittest.TestCase):
    def setUp(self):
        from robo.car import STOP
        STOP.clear()
        self._day = patch("robo.assistant.is_night", return_value=False); self._day.start()

    def tearDown(self):
        from robo.car import STOP
        STOP.clear()
        self._day.stop()


class WakeWords(unittest.TestCase):
    def test_whole_words_longest_first(self):
        from robo.main import heard_wake_word
        self.assertEqual(heard_wake_word("hey robot come here"), "come here")
        self.assertEqual(heard_wake_word("hey robot"), "")
        self.assertIsNone(heard_wake_word("i love my robot toy"))
        self.assertEqual(heard_wake_word("r2-d2 what time is it"), "what time is it")
        self.assertEqual(heard_wake_word("hey r2-d2"), "")

    def test_a_name_the_recognizer_cannot_spell_is_found_by_its_sound(self):
        from robo.voice import wake_end
        w = lambda *words: [{"word": x, "end": i + 1.0} for i, x in enumerate(words)]
        self.assertEqual(wake_end(w("hey", "are", "two", "d", "two", "[unk]"), "are two d two"), 5.0)
        self.assertEqual(wake_end(w("two", "d", "two", "[unk]"), "are two d two"), 3.0)  # "are" is often lost
        self.assertIsNone(wake_end(w("[unk]", "are", "two", "[unk]"), "are two d two"))
        self.assertIsNone(wake_end([], "are two d two"))
        # the name has to open the phrase: "who is r2-d2 in the film" is a normal sentence
        self.assertIsNone(wake_end([{"word": "[unk]", "start": 0.0, "end": 0.9}, *w("are", "two", "d", "two")], "are two d two"))
        # ordinary talk heard as the name's own words running on is not the name
        self.assertIsNone(wake_end(w("two", "d", "two", "d", "hey"), "are two d two"))

    def test_every_spelling_of_the_name_is_read_as_the_name(self):
        from robo.main import heard_wake_word
        from robo.voice import spell_name
        for heard in ("Hey are 2d2, what do you see?", "Hey R2D2, what do you see?", "Hey, r, two, D, two. What do you see?",
                      "R2-D2 what do you see", "Kr2d2, what do you see?"):
            self.assertEqual(heard_wake_word(spell_name(heard)), "what do you see", heard)
        self.assertIsNone(heard_wake_word(spell_name("What are you two doing today?")))
        self.assertIsNone(heard_wake_word(spell_name("There are two dogs in the garden.")))

    def test_one_word_goodbyes_end_the_conversation(self):
        from robo.main import ends_conversation
        for said in ("bye", "Goodbye.", "thanks!", "thank you", "That's all."):
            self.assertTrue(ends_conversation(said), said)
        self.assertFalse(ends_conversation("thanks for the story, tell me another"))

    def test_the_name_is_optional_after_yes_and_with_the_button(self):
        from robo.main import is_stop, without_wake_word
        self.assertEqual(without_wake_word("hey r2-d2 stop"), "stop")
        self.assertEqual(without_wake_word("what do you see"), "what do you see")
        self.assertTrue(is_stop(without_wake_word("hey r2-d2 stop")))
        self.assertTrue(is_stop("stop stop stop stop"))
        self.assertFalse(is_stop("i will stop when i get to the door"))

    def test_stop_inside_a_sentence_is_not_a_stop_command(self):
        from robo.voice import is_stop_phrase

        def w(*parts):  # ("[unk]", 0.9), ("stop", 0.4) -> Vosk word dicts, one after another
            out, t = [], 0.0
            for word, secs in parts:
                out.append({"word": word, "start": t, "end": t + secs}); t += secs
            return out
        self.assertTrue(is_stop_phrase(w(("stop", 0.4))))
        self.assertTrue(is_stop_phrase(w(("[unk]", 1.08), ("stop", 0.4))))        # "hey r2-d2 stop"
        self.assertTrue(is_stop_phrase(w(("stop", 0.4), ("[unk]", 0.66))))        # "stop right there"
        self.assertTrue(is_stop_phrase(w(("stop", 0.3), ("stop", 0.3), ("stop", 0.3))))
        self.assertFalse(is_stop_phrase(w(("[unk]", 0.4), ("stop", 0.4), ("[unk]", 0.74))))  # "I will stop when I get to the door"
        self.assertFalse(is_stop_phrase(w(("[unk]", 1.5), ("stop", 0.4))))        # the end of a long sentence
        self.assertFalse(is_stop_phrase(w(("[unk]", 2.0))))
        self.assertFalse(is_stop_phrase([]))

    def test_rename_keeps_a_way_to_wake_the_robot(self):
        from robo import memory
        old = (config.NAME, list(config.WAKE_WORDS), config.WAKE_SOUNDS_LIKE)
        try:
            memory.apply_name("C-3PO")  # the recognizer cannot spell this
            self.assertIn("hey robot", config.WAKE_WORDS)
            self.assertIsNone(config.WAKE_SOUNDS_LIKE)
            with self.assertRaises(ValueError):
                memory.apply_name("   ")
            memory.apply_name(old[0])  # back to the built-in name: its settings return
            self.assertEqual((config.NAME, config.WAKE_WORDS, config.WAKE_SOUNDS_LIKE), old)
        finally:
            config.NAME, config.WAKE_WORDS, config.WAKE_SOUNDS_LIKE = old

    def test_renamed_robot_needs_its_whole_name(self):
        from robo import memory
        from robo.main import heard_wake_word
        old = (config.NAME, list(config.WAKE_WORDS), config.WAKE_SOUNDS_LIKE)
        try:
            memory.apply_name("Ziggy")
            self.assertIsNone(heard_wake_word("i love ziggyboo"))
            self.assertEqual(heard_wake_word("hey ziggy dance"), "dance")
        finally:
            config.NAME, config.WAKE_WORDS, config.WAKE_SOUNDS_LIKE = old

    def test_stop_phrases(self):
        from robo.main import is_stop
        for t in ("stop", "please stop", "robo halt"):
            self.assertTrue(is_stop(t), t)
        for t in ("", "what is a bus stop near the school", "drive forward"):
            self.assertFalse(is_stop(t), t)


class CarSafety(Daytime):
    def test_no_distance_reading_blocks_forward(self):
        for bad in (None, OSError("i2c")):
            px = FakePx(distance=bad)
            out = real_car(px).drive("forward", 30, 1.0, 0)
            self.assertIn("stopped: obstacle at 0 cm", out)
            self.assertNotIn(("forward", 30), px.log)  # never started the motors

    def test_out_of_range_still_counts_as_clear(self):
        car = real_car(FakePx(distance=-1))
        self.assertEqual(car.distance_cm(), 999.0)

    def test_unknown_direction_is_refused(self):
        px = FakePx()
        self.assertIn("refused: unknown direction", real_car(px).drive("forwards", 30, 1.0, 0))
        self.assertEqual(px.log, [])

    def test_reverse_is_slower_and_shorter(self):
        px = FakePx()
        out = real_car(px).drive("backward", 40, 3.0, 0)
        self.assertIn(("backward", config.REVERSE_MAX_SPEED), px.log)
        self.assertLess(float(out.split(" for ")[1].split("s,")[0]), config.REVERSE_MAX_SECONDS + 0.2)

    def test_battery_limits_are_enforced_by_the_car(self):
        px = FakePx()
        self.assertIn("battery empty", real_car(px, volts=6.5).drive("forward", 30, 1.0, 0))
        self.assertEqual(px.log, [])
        out = real_car(FakePx(), volts=6.9).drive("forward", 30, 3.0, 0)
        self.assertLess(float(out.split(" for ")[1].split("s,")[0]), 1.2)  # hungry: 1 s moves

    def test_stop_event_ends_a_drive_early(self):
        import threading

        from robo.car import STOP
        car = real_car(FakePx())
        threading.Timer(0.2, STOP.set).start()
        t0 = time.time()
        out = car.drive("forward", 30, 3.0, 0)
        self.assertLess(time.time() - t0, 1.0)
        self.assertIn("someone said stop", out)
        self.assertIn("someone said stop", car.drive("forward", 30, 1.0, 0))  # stays stopped

    def test_hold_keeps_moving_without_stutter(self):
        px = FakePx()
        car = real_car(px)
        for _ in range(3):
            self.assertEqual(car.hold("forward", 30, 0, seconds=0.01), "moving")
        self.assertEqual(px.log.count(("forward", 30)), 1)  # motors started once
        self.assertNotIn(("stop",), px.log)
        px.distance = 10
        self.assertIn("obstacle", car.hold("forward", 30, 0, seconds=0.01))
        self.assertIn(("stop",), px.log)

    def test_tricks_do_not_wait_for_photo_settling(self):
        car = real_car(FakePx())
        t0 = time.time(); car.trick("nod")
        self.assertLess(time.time() - t0, 1.6)  # 4 x 0.25 s pauses; was about 3 s


class Brains(Daytime):
    def _direct(self, replies, client_extra=None):
        from robo.brain_api import DirectBrain
        from robo.camera import MockCamera
        from robo.car import MockCar
        from robo.face import MockFace
        from robo.voice import KeyboardVoice
        calls = []

        class Msgs:
            def create(self, **kw):
                calls.append(kw)
                r = replies[min(len(calls) - 1, len(replies) - 1)]
                if isinstance(r, Exception):
                    raise r
                return r
        client = NS(messages=Msgs(), **(client_extra or {}))
        return DirectBrain(MockCar(), MockCamera(), KeyboardVoice(), MockFace(quiet=True), client=client), calls

    def test_placeholder_key_falls_back_to_the_login(self):
        from robo.brain import make_brain
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "paste-the-key-from-your-Console-org-here", "ROBO_BRAIN": "auto"}), \
                patch("robo.brain.Brain") as agent:
            make_brain(None, None, None)
            agent.assert_called_once()
        self.assertTrue(config.is_placeholder("paste-the-key-from-your-Console-org-here"))
        self.assertFalse(config.is_placeholder("sk-ant-api03-abc"))

    def test_rename_reaches_the_system_prompt(self):
        from robo import memory
        done = NS(content=[NS(type="text", text="Hi")], stop_reason="end_turn")
        brain, calls = self._direct([done])
        old = (config.NAME, list(config.WAKE_WORDS), config.WAKE_SOUNDS_LIKE)
        try:
            with tempfile.TemporaryDirectory() as d, patch.object(memory, "DIARY", Path(d)), \
                    patch.object(memory, "STATE", Path(d) / "s.json"):
                brain.handle("hello")
                memory.apply_name("Ziggy")
                brain.handle("hello again")
        finally:
            config.NAME, config.WAKE_WORDS, config.WAKE_SOUNDS_LIKE = old
        self.assertIn("You are R2-D2", calls[0]["system"][0]["text"])
        self.assertIn("You are Ziggy", calls[1]["system"][0]["text"])

    def test_birthday_is_kept_for_later_when_the_call_fails(self):
        import anthropic

        from robo import memory
        err = anthropic.APIConnectionError(request=NS(method="POST", url="x", headers={}))
        brain, _ = self._direct([err])
        with tempfile.TemporaryDirectory() as d, patch.object(memory, "STATE", Path(d) / "s.json"), \
                patch.object(memory, "DIARY", Path(d)), patch("robo.memory.birthday_today", return_value="Leo"):
            brain.handle("hello")
            self.assertFalse(memory.celebrated_today("Leo"))

    def test_stop_ends_the_tool_loop(self):
        from robo import memory
        from robo.car import STOP
        loop = NS(content=[NS(type="tool_use", id="t", name="get_distance", input={})], stop_reason="tool_use")
        brain, calls = self._direct([loop])
        STOP.set()
        with tempfile.TemporaryDirectory() as d, patch.object(memory, "DIARY", Path(d)):
            self.assertEqual(brain.handle("drive around"), "Okay, I stopped.")
        self.assertEqual(calls, [])

    def test_timeout_is_set_and_reported(self):
        import anthropic

        from robo import memory
        brain, _ = self._direct([anthropic.APITimeoutError(request=NS(method="POST", url="x", headers={}))])
        with tempfile.TemporaryDirectory() as d, patch.object(memory, "DIARY", Path(d)):
            self.assertIn("took too long", brain.handle("hello"))
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-test"}):
            from robo.brain_api import DirectBrain
            from robo.car import MockCar
            real = DirectBrain(MockCar(), None, NS(say=print))
            self.assertEqual(real.client.timeout, config.CLAUDE_TIMEOUT_S)

    def test_self_check_really_asks_claude(self):
        import anthropic

        from robo import selfcheck

        def bad(model):
            raise anthropic.AuthenticationError("no", response=NS(status_code=401, headers={}, request=None), body=None)
        brain, _ = self._direct([], client_extra={"models": NS(retrieve=bad)})
        res = {n: (ok, d) for n, ok, d in selfcheck.run(brain=brain)}
        self.assertEqual(res["Claude"], (False, "the API key was rejected"))

    def test_offline_brain_explains_itself(self):
        from robo.brain import OfflineBrain
        b = OfflineBrain("not logged in")
        self.assertIn("not connected", b.handle("hi"))
        self.assertFalse(b.ping()[0])

    def test_turns_reset_each_day(self):
        from datetime import date, timedelta

        from robo.car import MockCar
        from robo.tools import Toolbox
        tb = Toolbox(MockCar(), None, NS(say=print), None)
        tb.turns_today, tb._turns_day = 50, date.today() - timedelta(days=1)
        tb.count_turn()
        self.assertEqual(tb.turns_today, 1)


class Housekeeping(unittest.TestCase):
    def test_prune_keeps_the_newest(self):
        from robo import memory
        with tempfile.TemporaryDirectory() as d:
            for i in range(5):
                p = Path(d) / f"{i}.jpg"; p.write_bytes(b"x"); os.utime(p, (i, i))
            self.assertEqual(memory.prune(Path(d), "*.jpg", 2), 3)
            self.assertEqual(sorted(p.name for p in Path(d).iterdir()), ["3.jpg", "4.jpg"])

    def test_diary_keeps_a_limited_number_of_days(self):
        from robo import memory
        with tempfile.TemporaryDirectory() as d, patch.object(memory, "DIARY", Path(d)), \
                patch.object(config, "KEEP_DIARY_DAYS", 2):
            for day in ("2026-01-01", "2026-01-02", "2026-01-03"):
                p = Path(d) / f"{day}.jsonl"; p.write_text("{}\n")
                os.utime(p, (time.time() - 1000, time.time() - 1000))
            memory.diary_add("hi", "hello")
            self.assertEqual(len(list(Path(d).glob("*.jsonl"))), 2)

    def test_quiet_sounds_at_night(self):
        from robo import sounds
        loud, quiet = sounds.path_for("beep"), sounds.path_for("beep", quiet=True)
        self.assertNotEqual(loud, quiet)
        import struct
        peak = lambda p: max(abs(v) for v in struct.unpack(f"<{(p.stat().st_size - 44) // 2}h", p.read_bytes()[44:]))
        self.assertLess(peak(quiet), peak(loud) / 3)

    def test_missing_forecast_values_are_spoken_as_unknown(self):
        from robo.assistant import _num
        self.assertEqual(_num(None, "%"), "unknown")
        self.assertEqual(_num(42.4, "%"), "42%")


if __name__ == "__main__":
    unittest.main()


try:
    import numpy as _numpy
except ImportError:  # the Pi has it; a bare test machine may not
    _numpy = None


@unittest.skipIf(_numpy is None, "numpy not installed")
class TrimQuiet(unittest.TestCase):
    """Moonshine writes nothing for a recording that starts with a long quiet."""

    def _recording(self, before: float, after: float) -> bytes:
        import numpy
        rng = numpy.random.default_rng(1)
        parts = [rng.normal(0, 30, int(before * 16000)), rng.normal(0, 3000, 16000), rng.normal(0, 30, int(after * 16000))]
        return numpy.concatenate(parts).astype(numpy.int16).tobytes()

    def test_quiet_is_cut_from_both_ends(self):
        from robo.voice import QUIET_KEPT_S, trim_quiet
        rest, removed = trim_quiet(self._recording(2.0, 1.5))
        self.assertAlmostEqual(len(rest) / 32000, 1.0 + 2 * QUIET_KEPT_S, delta=0.05)
        self.assertAlmostEqual(removed, 3.5 - 2 * QUIET_KEPT_S, delta=0.05)

    def test_recording_without_quiet_is_left_alone(self):
        from robo.voice import trim_quiet
        pcm = self._recording(0, 0)
        self.assertEqual(trim_quiet(pcm), (pcm, 0.0))
        self.assertEqual(trim_quiet(b""), (b"", 0.0))


class ComputerText(unittest.TestCase):
    def test_reads_memory_from_proc_files(self):
        import tempfile

        from robo import selfcheck
        with tempfile.TemporaryDirectory() as d:
            meminfo, status = Path(d) / "meminfo", Path(d) / "status"
            meminfo.write_text("MemTotal:  4194304 kB\nMemAvailable:  3145728 kB\nSwapTotal:  2097152 kB\nSwapFree:  1048576 kB\n")
            status.write_text("Name:\tpython3\nVmRSS:\t  524288 kB\n")
            text = selfcheck.computer_text(str(meminfo), str(status))
        self.assertIn("memory 1.0 of 4.0 GB in use (this program 0.5 GB), 1.0 GB moved to the SD card", text)

    def test_none_without_proc(self):
        from robo import selfcheck
        self.assertIsNone(selfcheck.computer_text("/nonexistent/meminfo"))


class ArecordDevice(unittest.TestCase):
    """The Pi records with the arecord command; this picks the sound card for it."""

    def _asound(self, d: str) -> str:
        Path(d, "cards").write_text(
            " 2 [Headphones     ]: bcm2835_headpho - bcm2835 Headphones\n"
            "                      bcm2835 Headphones\n"
            " 3 [Device         ]: USB-Audio - USB PnP Sound Device\n"
            "                      C-Media Electronics Inc. USB PnP Sound Device at usb-0000:01:00.0-1.2\n"
            " 5 [Webcam         ]: Other - Camera microphone\n"
            "                      Camera microphone\n")
        for card, pcm in (("card2", "pcm0p"), ("card3", "pcm0c"), ("card5", "pcm0c")):
            Path(d, card, pcm).mkdir(parents=True)
        return d

    def test_picks_the_recording_card_by_name(self):
        from robo.voice import arecord_device
        with tempfile.TemporaryDirectory() as d:
            root = self._asound(d)
            self.assertEqual(arecord_device("USB", root), "plughw:3,0")
            self.assertEqual(arecord_device("webcam", root), "plughw:5,0")
            self.assertEqual(arecord_device("no such name", root), "plughw:3,0")  # first that can record
            self.assertEqual(arecord_device(None, root), "plughw:3,0")

    def test_none_without_a_recording_card(self):
        from robo.voice import arecord_device
        self.assertIsNone(arecord_device("USB", "/nonexistent"))
        with tempfile.TemporaryDirectory() as d:
            Path(d, "cards").write_text(" 2 [Headphones     ]: bcm2835_headpho - bcm2835 Headphones\n")
            Path(d, "card2", "pcm0p").mkdir(parents=True)
            self.assertIsNone(arecord_device("USB", d))


class FakePad:
    """A controller at rest: sticks at 0, triggers released (-1), no button."""

    def __init__(self):
        self.axes = {0: 0.0, 1: 0.0, 2: 0.0, 3: 0.0, 4: -1.0, 5: -1.0}
        self.buttons = set()

    def get_axis(self, i):
        return self.axes[i]

    def get_button(self, i):
        return i in self.buttons


class FakeCar:
    def __init__(self):
        self.calls = []

    def hold(self, direction, speed, steer):
        self.calls.append(("hold", direction, speed, steer))
        return "moving"

    def stop(self):
        self.calls.append(("stop",))

    def reset(self):
        self.calls.append(("reset",))

    def look(self, pan, tilt, settle=True):
        self.calls.append(("look", pan, tilt))

    def steer(self, angle):
        self.calls.append(("steer", angle))


class ControllerDriving(unittest.TestCase):
    """The controller drives the car while the robot talks (robo/controller.py)."""

    def setUp(self):
        from robo import controller
        from robo.car import STOP
        STOP.clear()
        self.controller, self.STOP = controller, STOP
        self.car, self.pad, self.busy = FakeCar(), FakePad(), False
        self.control = controller.Controller(self.car, None, self.pad, busy=lambda: self.busy)
        self.control._removed = lambda: False
        patcher = patch("time.sleep"); patcher.start(); self.addCleanup(patcher.stop)
        self.addCleanup(STOP.clear)

    def test_untouched_controller_does_not_stop_the_brains_drive(self):
        for _ in range(3):
            self.assertTrue(self.control.tick())
        self.assertEqual(self.car.calls, [])

    def test_right_trigger_drives_forward_and_release_stops_once(self):
        self.control.tick()                       # triggers seen released: now they count
        self.pad.axes[self.controller.AXIS_FORWARD] = 1.0
        self.pad.axes[self.controller.AXIS_STEER] = -1.0
        self.control.tick()
        self.assertEqual(self.car.calls, [("steer", -config.TURN_ANGLE_LIMIT),
                                          ("hold", "forward", config.MAX_SPEED, -config.TURN_ANGLE_LIMIT)])
        self.pad.axes[self.controller.AXIS_FORWARD] = -1.0
        self.control.tick(); self.control.tick()
        self.assertEqual(self.car.calls[2:], [("stop",)])

    def test_left_stick_steers_without_driving_and_straightens_on_release(self):
        self.pad.axes[self.controller.AXIS_STEER] = 1.0
        self.control.tick(); self.control.tick()
        self.pad.axes[self.controller.AXIS_STEER] = 0.05   # let go: a stick never rests at exactly 0
        self.control.tick()
        self.assertEqual(self.car.calls, [("steer", config.TURN_ANGLE_LIMIT), ("steer", 0)])

    def test_trigger_reported_half_pressed_at_start_does_not_drive(self):
        self.pad.axes[self.controller.AXIS_FORWARD] = 0.0   # some drivers, until first pulled
        self.control.tick()
        self.assertEqual(self.car.calls, [])

    def test_b_stops_and_ends_a_running_request(self):
        self.pad.buttons = {self.controller.BUTTON_B}
        self.control.tick()
        self.assertEqual(self.car.calls, [("stop",), ("reset",)])
        self.assertFalse(self.STOP.is_set())      # nothing was running: nothing to end
        self.busy, self.car.calls = True, []
        self.control.tick()
        self.assertEqual(self.car.calls, [("stop",)])
        self.assertTrue(self.STOP.is_set())

    def test_b_during_a_request_asks_once_for_it_to_end(self):
        ended = []
        self.control.end_request = lambda: (ended.append(1), self.STOP.set())
        self.busy, self.pad.buttons = True, {self.controller.BUTTON_B}
        self.control.tick(); self.control.tick()   # held for two ticks
        self.assertEqual(ended, [1])
        self.assertTrue(self.STOP.is_set())

    def test_right_stick_turns_the_camera(self):
        self.pad.axes[self.controller.AXIS_PAN] = 1.0
        self.control.tick()
        self.assertEqual(self.car.calls, [("look", config.CAM_PAN_LIMIT, 0)])

    def test_disconnect_stops_the_car_it_was_driving(self):
        self.control.tick()
        self.pad.axes[self.controller.AXIS_FORWARD] = 1.0
        self.control.tick()
        self.control._removed = lambda: True
        self.assertFalse(self.control.tick())
        self.assertEqual(self.car.calls[-1], ("stop",))


class OneI2cMessageAtATime(unittest.TestCase):
    def test_wraps_once_and_still_returns_values(self):
        from robo.car import one_i2c_message_at_a_time

        class I2C:
            def write(self, data): return ("w", data)
            def read(self, n=1): return [7] * n
            def mem_write(self, data, addr): return None
            def mem_read(self, n, addr): return [1] * n

        class ADC(I2C):
            def read(self):
                self.write([0, 0, 0])
                return sum(super().read(2))   # takes the lock a second time: must not hang

        one_i2c_message_at_a_time(I2C, ADC)
        first = I2C.write
        one_i2c_message_at_a_time(I2C, ADC)
        self.assertIs(I2C.write, first)
        self.assertEqual(ADC().read(), 14)
        self.assertEqual(I2C().read(3), [7, 7, 7])


class SpeakableParts(unittest.TestCase):
    def test_sentences_and_long_sentences_in_pieces(self):
        from robo.voice import LONG_SENTENCE, speakable_parts
        self.assertEqual(speakable_parts("Hello there! How are you?  Fine."), ["Hello there!", "How are you?", "Fine."])
        long = ("Here are three moon facts: it is about 384,000 km away, it drifts roughly 3.8 cm farther from Earth "
                "each year, and we always see the same side because it spins once for each orbit.")
        parts = speakable_parts(long)
        self.assertGreater(len(parts), 1)
        self.assertEqual(" ".join(parts), long)                       # nothing lost, nothing reordered
        self.assertTrue(all(len(p) <= LONG_SENTENCE for p in parts))
        self.assertEqual(speakable_parts(""), [])


class ThinkingSound(unittest.TestCase):
    def test_chirps_at_once_then_beeps_until_the_answer_is_ready(self):
        from robo.main import Thinking
        played = []
        with patch.object(config, "THINKING_SOUND_EVERY_S", 0.02):
            with Thinking(play=played.append):
                time.sleep(0.15)
            count = len(played)
            time.sleep(0.08)
        from robo import sounds
        self.assertEqual(played[0], "chirp")
        self.assertGreaterEqual(len(played), 3)
        self.assertTrue(all(name in sounds.THINKING for name in played[1:]))
        from itertools import pairwise
        self.assertTrue(all(a != b for a, b in pairwise(played[1:])))   # never the same one twice running
        self.assertEqual(len(played), count)   # silent once the answer is ready

    def test_can_be_switched_off(self):
        from robo.main import Thinking
        played = []
        with patch.object(config, "THINKING_SOUND", False), Thinking(play=played.append):
            time.sleep(0.05)
        self.assertEqual(played, [])


class LiveViewOverIpv6(unittest.TestCase):
    def test_passes_a_connection_on_to_the_ipv4_server(self):
        import socket
        import threading

        from robo.camera import also_over_ipv6
        if not socket.has_ipv6:
            self.skipTest("no IPv6 on this machine")
        server = socket.socket(); server.bind(("127.0.0.1", 0)); server.listen(1)
        port = server.getsockname()[1]

        def answer():
            c, _ = server.accept()
            c.sendall(b"frame:" + c.recv(100)); c.close()
        threading.Thread(target=answer, daemon=True).start()
        also_over_ipv6(port)
        deadline = time.time() + 3
        while True:
            try:
                viewer = socket.create_connection(("::1", port), timeout=2); break
            except OSError:
                if time.time() > deadline:
                    raise
                time.sleep(0.05)
        viewer.sendall(b"GET /mjpg")
        self.assertEqual(viewer.recv(100), b"frame:GET /mjpg")
        viewer.close(); server.close()


class MotorNoise(unittest.TestCase):
    """While the motors run the ears take the microphone as silent (robo/car.py)."""

    def test_noise_while_running_and_shortly_after(self):
        from robo import car
        self.addCleanup(car.motors, False)
        with patch("robo.car.time.time", return_value=1000.0):
            car.motors(True)
            self.assertTrue(car.motor_noise())
            car.motors(False)
            self.assertTrue(car.motor_noise())                  # still spinning down
        with patch("robo.car.time.time", return_value=1000.0 + car.MOTOR_NOISE_AFTER_S + 0.1):
            self.assertFalse(car.motor_noise())
            self.assertTrue(car.motor_noise(since=999.5))       # they did run during that stretch
            car.motors(False)                                   # a second stop is not a new noise
            self.assertFalse(car.motor_noise())


@unittest.skipIf(_numpy is None, "numpy not installed")
class WithoutRumbleFilter(unittest.TestCase):
    def _level(self, hz: float, force_plain: bool = False) -> float:
        from robo.voice import WithoutRumble
        t = _numpy.arange(16000) / 16000
        pcm = (_numpy.sin(2 * _numpy.pi * hz * t) * 10000).astype(_numpy.int16).tobytes()
        clean = WithoutRumble()
        with patch.dict("sys.modules", {"scipy.signal": None} if force_plain else {}):
            out = b"".join(clean(pcm[i:i + 3200]) for i in range(0, len(pcm), 3200))   # in pieces, as it arrives
        a = _numpy.frombuffer(out, dtype=_numpy.int16).astype(_numpy.float64)[4000:]
        return float(_numpy.sqrt((a ** 2).mean()) / (10000 / 2 ** 0.5))

    def test_rumble_goes_and_voice_stays(self):
        for plain in (False, True):
            self.assertLess(self._level(50, plain), 0.1)       # a thump: under a tenth is left
            self.assertGreater(self._level(1000, plain), 0.95)  # the middle of a voice: untouched
            self.assertGreater(self._level(300, plain), 0.85)


class AnswerToTheRobotsQuestion(unittest.TestCase):
    def test_ends_with_question(self):
        from robo.main import ends_with_question
        self.assertTrue(ends_with_question("Question one: what is the largest planet in our solar system?"))
        self.assertTrue(ends_with_question('Shall I say "go"? '))
        self.assertFalse(ends_with_question("What a question! Jupiter is the largest planet."))
        self.assertFalse(ends_with_question(""))
        self.assertFalse(ends_with_question(None))
        self.assertTrue(ends_with_question("What is the largest planet? [face:thinking]"))


class LateNightForOneDay(unittest.TestCase):
    def test_only_on_the_named_date(self):
        from datetime import date
        with patch.dict(os.environ, {"ROBO_LATE_NIGHT": "2026-10-11 22"}):
            self.assertEqual(config.night_start(date(2026, 10, 11)), 22.0)
            self.assertEqual(config.night_start(date(2026, 10, 12)), config.NIGHT_START)
        with patch.dict(os.environ, {"ROBO_LATE_NIGHT": "nonsense"}):
            self.assertEqual(config.night_start(date(2026, 10, 11)), config.NIGHT_START)
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ROBO_LATE_NIGHT", None)
            self.assertEqual(config.night_start(date(2026, 10, 11)), config.NIGHT_START)


class NightNeedsTheRightTime(unittest.TestCase):
    """Switched on in the morning, the Pi first believes it is still the evening
    it was switched off: no night volume until the clock has been set."""

    def test_no_night_mode_before_the_clock_is_set(self):
        import tempfile
        from datetime import datetime as real

        from robo import assistant

        class Evening(real):
            @classmethod
            def now(cls, tz=None):
                return real(2026, 10, 23, 21, 30)
        with tempfile.TemporaryDirectory() as d, patch.object(assistant, "TIMESYNC", Path(d)), \
                patch.object(assistant, "datetime", Evening):
            self.assertFalse(assistant.is_night())  # timesyncd has not reached a time server yet
            (Path(d) / "synchronized").touch()
            self.assertTrue(assistant.is_night())
        with patch.object(assistant, "TIMESYNC", Path("/no/timesyncd/here")), patch.object(assistant, "datetime", Evening):
            self.assertTrue(assistant.is_night())  # no timesyncd (the Mac): the clock is taken as right


class LouderLocalVoice(unittest.TestCase):
    """Piper stands in whenever an online voice refuses a sentence; it used to
    play at a third of their loudness."""

    def write(self, path, samples):
        import array
        import wave
        with wave.open(str(path), "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(22050)
            w.writeframes(array.array("h", samples).tobytes())

    def read(self, path):
        import array
        import wave
        with wave.open(str(path)) as w:
            return array.array("h", w.readframes(w.getnframes()))

    def test_quiet_parts_three_times_louder_and_peaks_never_past_the_top(self):
        import math
        import tempfile

        from robo.voice import louder
        speech = [int(3000 * math.sin(i / 7)) for i in range(2000)] + [32767, -32768, 30000]
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "s.wav"
            self.write(p, speech)
            louder(p, 3.0)
            out = self.read(p)
        self.assertEqual(len(out), len(speech))
        quiet_in = max(abs(v) for v in speech[:2000]); quiet_out = max(abs(v) for v in out[:2000])
        self.assertGreater(quiet_out / quiet_in, 2.6)
        self.assertLessEqual(max(abs(v) for v in out), 32767)

    def test_no_gain_leaves_the_file_alone(self):
        import tempfile

        from robo.voice import louder
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "s.wav"
            self.write(p, [100, -2000, 32767])
            louder(p, 1.0)
            self.assertEqual(list(self.read(p)), [100, -2000, 32767])


class ThinkingSoundFiles(unittest.TestCase):
    def test_every_pattern_becomes_a_sound_file_and_is_not_offered_to_claude(self):
        import wave

        from robo import sounds
        with tempfile.TemporaryDirectory() as d:
            for name, notes in sounds.THINKING.items():
                self.assertNotIn(name, sounds.NAMES)
                path = Path(d) / f"{name}.wav"
                sounds._synth(notes, path)
                with wave.open(str(path)) as w:
                    secs = w.getnframes() / w.getframerate()
                self.assertTrue(0.4 < secs < 1.6, f"{name} lasts {secs:.2f} s")


class PatrolByVoice(unittest.TestCase):
    """"R2-D2, go on patrol": the patrol tool of the talking robot (robo/patrol.py)."""

    def _toolbox(self):
        from robo.camera import MockCamera
        from robo.car import MockCar
        from robo.tools import Toolbox
        said = []
        return Toolbox(MockCar(), MockCamera(), NS(say=said.append), None), said

    def test_roams_and_returns_at_most_six_photos(self):
        from robo.car import STOP
        STOP.clear()
        tb, said = self._toolbox()
        clock = [1000.0]

        def drive(direction, speed, seconds, steer=0):
            clock[0] += seconds
            return f"{direction} {speed}% for {seconds}s, completed"
        tb.car.drive = drive
        with patch("robo.patrol.time.time", lambda: clock[0]), patch("robo.assistant.is_night", return_value=False):
            out = tb.run("patrol", {"seconds": 400})          # more than allowed: cut to the longest patrol
        self.assertFalse(out["is_error"])
        self.assertEqual(said, ["Patrol starting."])
        kinds = [b["type"] for b in out["content"]]
        self.assertEqual(kinds[0], "text")
        self.assertIn(f"roamed for {config.PATROL_MAX_SECONDS}", out["content"][0]["text"])
        self.assertTrue(1 <= kinds.count("image") <= 6)
        self.assertGreater(len(tb.patrol_photos), 6)   # all of them are kept for review_patrol

    def test_stop_ends_the_patrol_at_once(self):
        from robo.car import STOP
        tb, _ = self._toolbox()
        STOP.set(); self.addCleanup(STOP.clear)
        with patch("robo.assistant.is_night", return_value=False):
            out = tb.run("patrol", {})
        self.assertIn("someone said stop", out["content"][0]["text"])
        self.assertIn("0 stretches forward", out["content"][0]["text"])


class ScreenOnTheSharedBus(unittest.TestCase):
    """The face screen shares the I2C wires with the Robot HAT (robo/face.py)."""

    def _face(self, display):
        import threading

        from robo.face import Face
        face = Face.__new__(Face)
        face._lock, face.state, face.gaze = threading.RLock(), "neutral", 0.0
        face.device = NS(display=display)
        return face

    def test_a_failed_frame_is_tried_again_and_then_left_out(self):
        calls = []

        def display(frame):
            calls.append(frame)
            raise OSError(5, "Input/output error")
        face = self._face(display)
        with patch("robo.face.time.sleep"):
            face._draw()                       # must not raise: the blink thread lives on
        self.assertEqual(len(calls), 2)
        self.assertEqual(face.failed, 1)

    def test_a_frame_takes_the_bus_lock(self):
        from robo.car import I2C_BUS
        held = []
        face = self._face(lambda frame: held.append(I2C_BUS._is_owned()))
        face._draw()
        self.assertEqual(held, [True])
        self.assertEqual(face.failed, 0)


class FacesSongsAndActs(unittest.TestCase):
    def test_every_song_is_a_playable_tune(self):
        from robo import sounds
        self.assertGreaterEqual(len(sounds.SONGS), 9)
        for name, notes in sounds.SONGS.items():
            secs = sum(n[-1] for n in notes)
            self.assertTrue(6 < secs < 25, f"{name} lasts {secs:.1f} s")
            self.assertTrue(all(n[0] == 0 or 100 < n[0] < 2000 for n in notes), name)
            self.assertIn(f"song_{name}", sounds.SOUNDS)
            self.assertNotIn(f"song_{name}", sounds.NAMES)     # sung with the sing tool, not play_sound

    def test_melody_notes(self):
        from robo.sounds import _melody
        notes = _melody("A4:1 -:0.5 C4:2", 0.5)
        self.assertEqual([n[0] for n in notes], [440, 0, 0, 262, 0])
        self.assertAlmostEqual(sum(n[1] for n in notes), 1.75)

    def test_sing_tool_shows_the_singing_face_and_stops_on_stop(self):
        from robo import sounds
        from robo.camera import MockCamera
        from robo.car import MockCar
        from robo.tools import Toolbox
        shown, talking = [], []
        face = NS(show=lambda f, hold=3.0: shown.append(f), set_talking=talking.append)
        tb = Toolbox(MockCar(), MockCamera(), NS(say=print), face)
        with patch.object(sounds, "play_song", lambda song, on_beat=None, stop=None: (on_beat(), f"sang {song}")[1]):
            out = tb.run("sing", {"song": "twinkle_twinkle"})
        self.assertEqual(out["content"][0]["text"], "sang twinkle_twinkle")
        self.assertEqual(shown, ["singing", "happy"])
        self.assertEqual(talking, [True, False])
        self.assertTrue(tb.run("sing", {"song": "no such song"})["content"][0]["text"].startswith("unknown song"))

    def test_every_act_shows_a_face_that_exists(self):
        from robo import car as car_mod
        from robo.face import EXPRESSIONS
        shown = []
        car = car_mod.MockCar()
        car.face = NS(show=lambda f, hold=3.0: shown.append(f), look_at=lambda pan: None)
        for name in car_mod._ACTS:
            self.assertEqual(car_mod._do_trick(car, name, fast=True), f"did {name}")
        self.assertTrue(set(shown) <= set(EXPRESSIONS), set(shown) - set(EXPRESSIONS))

    def test_claude_is_offered_every_face_trick_and_song(self):
        from robo import sounds
        from robo.brain import SCHEMAS
        from robo.car import TRICKS
        from robo.face import FUNNY
        self.assertTrue(set(FUNNY) <= set(SCHEMAS["express"]["properties"]["feeling"]["enum"]))
        self.assertEqual(SCHEMAS["do_trick"]["properties"]["name"]["enum"], TRICKS)
        self.assertEqual(SCHEMAS["sing"]["properties"]["song"]["enum"], list(sounds.SONGS))


class MusicGames(unittest.TestCase):
    """Freeze Dance, Copy My Dance, Name That Tune and the dramatic sounds (robo/games.py)."""

    def setUp(self):
        from robo.car import STOP
        STOP.clear()
        self.addCleanup(STOP.clear)

    def _toolbox(self):
        from robo.camera import MockCamera
        from robo.car import MockCar
        from robo.face import MockFace
        from robo.tools import Toolbox
        return Toolbox(MockCar(), MockCamera(), NS(say=print), MockFace(quiet=True))

    def test_dramatic_sounds_are_offered_and_short(self):
        from robo import sounds
        for name in ("drumroll", "suspense", "ticking", "fanfare", "sad_trombone", "spooky", "heartbeat", "countdown", "record_scratch"):
            self.assertIn(name, sounds.NAMES)
            self.assertTrue(0.3 < sum(n[-1] for n in sounds.SOUNDS[name]) < 5, name)
        self.assertFalse([n for n in sounds.NAMES if n.startswith("step_")])   # the move notes are the game's own

    def test_every_song_has_a_dance_style(self):
        from robo import games, sounds
        self.assertEqual(set(games.SONG_STYLE), set(sounds.SONGS))
        self.assertTrue(set(games.SONG_STYLE.values()) <= set(games.STEPS))

    def test_play_song_stops_after_max_seconds(self):
        from robo import sounds

        class Endless:
            def poll(self): return None
            def terminate(self): self.stopped = True
        proc = Endless()
        with patch.object(sounds, "path_for", lambda *a, **k: "x.wav"), patch("shutil.which", lambda c: "/usr/bin/aplay"), \
                patch("subprocess.Popen", lambda *a, **k: proc), patch.object(sounds, "enable_speaker", lambda: None), \
                patch("time.sleep", lambda s: None):
            out = sounds.play_song("twinkle_twinkle", max_seconds=0)
        self.assertEqual(out, "played the first 0 seconds of twinkle_twinkle")
        self.assertTrue(proc.stopped)

    def test_freeze_dance_returns_two_photos_and_a_new_song_each_round(self):
        tb = self._toolbox()
        seen = set()
        for _ in range(6):
            last = tb.freeze_song
            out = tb.run("freeze_dance", {})
            self.assertFalse(out["is_error"])
            self.assertEqual([b["type"] for b in out["content"]], ["text", "image", "image"])
            self.assertNotEqual(tb.freeze_song, last)
            seen.add(tb.freeze_song)
        self.assertGreater(len(seen), 1)

    def test_freeze_dance_without_a_camera_asks_instead(self):
        from robo.camera import NoCamera
        tb = self._toolbox(); tb.camera = NoCamera("unplugged")
        out = tb.run("freeze_dance", {})
        self.assertEqual(len(out["content"]), 1)
        self.assertIn("Ask who wobbled", out["content"][0]["text"])

    def test_copy_my_dance_grows_one_move_a_round_and_restarts(self):
        from robo import games
        tb = self._toolbox()
        self.assertIn("Round 1", tb.run("copy_my_dance", {"new_game": True})["content"][0]["text"])
        self.assertEqual(len(tb.dance_moves), 2)
        tb.run("copy_my_dance", {"new_game": False})
        self.assertEqual(len(tb.dance_moves), 3)
        self.assertTrue(all(a != b for a, b in zip(tb.dance_moves, tb.dance_moves[1:], strict=False)))   # never the same move twice in a row
        self.assertTrue(set(tb.dance_moves) <= set(games.MOVES))
        tb.run("copy_my_dance", {"new_game": True})
        self.assertEqual(len(tb.dance_moves), 2)

    def test_name_that_tune_keeps_the_song_secret_and_hints_with_the_same_one(self):
        tb = self._toolbox()
        text = tb.run("name_that_tune", {})["content"][0]["text"]
        song = tb.tunes_played[-1]
        self.assertIn("do not say the name", text)
        hint = tb.run("name_that_tune", {"hint": True})["content"][0]["text"]
        self.assertIn("first 10 seconds of " + song.replace("_", " "), hint)
        self.assertEqual(len(tb.tunes_played), 1)
        for _ in range(4):
            tb.run("name_that_tune", {})
        self.assertEqual(len(set(tb.tunes_played)), 5)   # no song again within five rounds

    def test_games_stop_on_stop(self):
        from robo.car import STOP
        tb = self._toolbox()
        STOP.set()
        for name, args in (("freeze_dance", {}), ("copy_my_dance", {"new_game": True}), ("name_that_tune", {})):
            self.assertIn("stopped", tb.run(name, args)["content"][0]["text"], name)

    def test_claude_is_offered_the_games(self):
        from robo.brain import SCHEMAS, system_prompt
        from robo.tools import DESCRIPTIONS
        for name in ("freeze_dance", "copy_my_dance", "name_that_tune"):
            self.assertIn(name, SCHEMAS); self.assertIn(name, DESCRIPTIONS)
        prompt = system_prompt()
        self.assertIn("Freeze Dance", prompt); self.assertIn("drumroll", prompt)


class CharacterModes(unittest.TestCase):
    """Film robot characters: be WALL-E, be yourself (robo/characters.py)."""

    def setUp(self):
        from robo.car import STOP
        saved = config.CHARACTER, config.VOICE_PITCH, config.VOICE_RATE
        self.addCleanup(lambda: setattr(config, "CHARACTER", saved[0]))
        self.addCleanup(lambda: setattr(config, "VOICE_PITCH", saved[1]))
        self.addCleanup(lambda: setattr(config, "VOICE_RATE", saved[2]))
        self.addCleanup(STOP.clear)

    def _toolbox(self):
        from robo.camera import MockCamera
        from robo.car import MockCar
        from robo.face import MockFace
        from robo.tools import Toolbox
        return Toolbox(MockCar(), MockCamera(), NS(say=print), MockFace(quiet=True))

    def test_every_character_uses_real_sounds_faces_and_voices(self):
        from robo import characters, sounds
        from robo.brain import FACES
        for name, c in characters.CHARACTERS.items():
            self.assertTrue(set(c["sounds"]) <= set(sounds.NAMES), name)
            self.assertIn(c["face"], FACES, name)
            self.assertRegex(c["voice"][0], r"^[+-]\d+Hz$"); self.assertRegex(c["voice"][1], r"^[+-]\d+%$")
            for pan, tilt, _ in c["moves"]:
                self.assertLessEqual(abs(pan), config.CAM_PAN_LIMIT); self.assertLessEqual(abs(tilt), config.CAM_TILT_LIMIT)
            for which in c["sounds"]:
                self.assertTrue(0.3 < sum(n[-1] for n in sounds.SOUNDS[which]) < 5, which)

    def test_become_changes_voice_and_notes_each_request_until_yourself(self):
        from robo.brain import decorate
        tb = self._toolbox()
        out = tb.run("become_character", {"name": "walle"})
        self.assertFalse(out["is_error"])
        self.assertIn("WALL-E", out["content"][0]["text"])
        self.assertEqual((config.VOICE_PITCH, config.VOICE_RATE), ("+20Hz", "-25%"))
        self.assertIn("playing WALL-E", decorate("hello")[0])
        tb.run("become_character", {"name": "yourself"})
        self.assertIsNone(config.CHARACTER)
        self.assertEqual(config.VOICE_PITCH, "+0Hz")
        self.assertNotIn("character mode", decorate("hello")[0])

    def test_unknown_character_is_refused(self):
        from robo import characters
        self.assertIn("unknown character", characters.become(None, None, "terminator", fast=True))
        self.assertIsNone(config.CHARACTER)

    def test_villain_stays_kind(self):
        from robo import characters
        play = characters.CHARACTERS["dalek"]["play"]
        self.assertIn("Never threaten", play); self.assertIn("scared", play)

    def test_claude_is_offered_the_characters(self):
        from robo.brain import SCHEMAS, system_prompt
        self.assertEqual(SCHEMAS["become_character"]["properties"]["name"]["enum"], ["walle", "eve", "r2d2", "dalek", "yourself"])
        self.assertIn("become_character", system_prompt())


class CameraGames(unittest.TestCase):
    """Hide and seek, Simon Says and Color Hunt (robo/games.py)."""

    def setUp(self):
        from robo.car import STOP
        self.addCleanup(STOP.clear)

    def _toolbox(self, said=None):
        from robo.camera import MockCamera
        from robo.car import MockCar
        from robo.face import MockFace
        from robo.tools import Toolbox
        return Toolbox(MockCar(), MockCamera(), NS(say=(said.append if said is not None else print)), MockFace(quiet=True))

    def test_hide_and_seek_counts_then_looks_three_ways(self):
        tb = self._toolbox()
        count = tb.run("hide_and_seek", {"phase": "count", "seconds": 5})["content"]
        self.assertEqual(len(count), 1); self.assertIn("Ready or not", count[0]["text"])
        seek = tb.run("hide_and_seek", {"phase": "seek"})["content"]
        self.assertEqual([b["type"] for b in seek], ["text", "image", "image", "image"])

    def test_simon_says_speaks_the_order_and_knows_the_rule(self):
        said = []
        tb = self._toolbox(said)
        out = tb.run("simon_says", {"command": "touch your nose", "simon": True})["content"]
        self.assertEqual(said, ["Simon says, touch your nose"])
        self.assertIn("NOT doing", out[0]["text"]); self.assertEqual(out[1]["type"], "image")
        out = tb.run("simon_says", {"command": "jump", "simon": False})["content"]
        self.assertEqual(said[-1], "jump"); self.assertIn("did NOT say it", out[0]["text"])

    def test_color_hunt_picks_fresh_colours_and_checks_the_last(self):
        from robo import games
        tb = self._toolbox()
        for _ in range(4):
            self.assertIn("Bring me something", tb.run("color_hunt", {"check": False})["content"][0]["text"])
        self.assertEqual(len(set(tb.hunt_colors[-4:])), 4)
        self.assertTrue(set(tb.hunt_colors) <= set(games.COLORS))
        out = tb.run("color_hunt", {"check": True})["content"]
        self.assertIn(f"something {tb.hunt_colors[-1]}", out[0]["text"]); self.assertEqual(out[1]["type"], "image")

    def test_games_without_a_camera_ask_instead(self):
        from robo.camera import NoCamera
        tb = self._toolbox(); tb.camera = NoCamera("unplugged")
        for name, args in (("hide_and_seek", {"phase": "seek"}), ("simon_says", {"command": "clap", "simon": True})):
            out = tb.run(name, args)
            self.assertFalse(out["is_error"]); self.assertEqual(len(out["content"]), 1)
            self.assertIn("camera is not working", out["content"][0]["text"], name)

    def test_claude_is_offered_the_camera_games(self):
        from robo.brain import SCHEMAS, system_prompt
        from robo.tools import DESCRIPTIONS
        for name in ("hide_and_seek", "simon_says", "color_hunt"):
            self.assertIn(name, SCHEMAS); self.assertIn(name, DESCRIPTIONS); self.assertIn(name, system_prompt())


class ScreenNotices(unittest.TestCase):
    """Text and the battery warning on the face screen (robo/face.py)."""

    def test_text_is_drawn_and_long_text_is_cut_with_dots(self):
        from robo.face import H, W, render, render_text
        short = render_text("what do you see", title="I heard:")
        self.assertEqual(short.size, (W, H))
        self.assertNotEqual(short.tobytes(), render("neutral").tobytes())
        self.assertGreater(sum(short.tobytes()), 0)
        long = render_text("tell me a very long story about a dragon " * 12)
        self.assertNotEqual(long.tobytes(), short.tobytes())
        self.assertEqual(render_text("").size, (W, H))        # nothing heard: an empty screen, no error

    def test_notice_replaces_the_face_and_the_face_comes_back(self):
        from robo.face import MockFace, render, render_text
        face = MockFace(quiet=True); self.addCleanup(face.close)
        clock = [1000.0]
        with patch("robo.face.time.time", lambda: clock[0]), patch("robo.face.threading.Timer"):
            face.show_text("hello there", seconds=4)
            self.assertEqual(face.frame().tobytes(), render_text("hello there").tobytes())
            clock[0] += 4.1
            self.assertEqual(face.frame().tobytes(), render("neutral").tobytes())

    def test_battery_picture_fills_with_the_charge(self):
        from robo.face import render_battery
        low, high = render_battery(6.9, 6.8, 8.4), render_battery(8.3, 6.8, 8.4)
        self.assertGreater(sum(high.tobytes()), sum(low.tobytes()))

    def test_battery_watch_shows_the_notice_and_speaks_once(self):
        from robo.main import BatteryWatch
        shown, said = [], []
        car = NS(battery_volts=lambda: 7.0)
        watch = BatteryWatch(car, NS(show_battery=shown.append), NS(say=said.append))
        with patch("robo.assistant.is_night", return_value=False):
            self.assertTrue(watch.check()); self.assertTrue(watch.check())
            self.assertEqual(shown, [7.0, 7.0])
            self.assertEqual(len(said), 1)                     # on the screen every time, aloud once
            car.battery_volts = lambda: 8.2
            self.assertFalse(watch.check())                    # charged: nothing shown
            car.battery_volts = lambda: -1.0
            self.assertFalse(watch.check())                    # no reading is not a low battery
        self.assertEqual(shown, [7.0, 7.0])


class BatteryPercent(unittest.TestCase):
    def test_follows_the_curve_in_steps_of_five(self):
        self.assertEqual(config.battery_percent(8.4), 100)
        self.assertEqual(config.battery_percent(9.0), 100)        # on the charger
        self.assertEqual(config.battery_percent(7.6), 45)
        self.assertEqual(config.battery_percent(7.5), 35)         # between two points of the curve
        self.assertEqual(config.battery_percent(config.BATTERY_EMPTY_V), 0)
        self.assertEqual(config.battery_percent(6.0), 0)
        readings = [config.battery_percent(v / 100) for v in range(680, 841)]
        self.assertEqual(readings, sorted(readings))              # never goes up as the voltage falls
        self.assertTrue(all(p % 5 == 0 for p in readings))

    def test_the_battery_tool_answers_in_percent(self):
        from robo.camera import MockCamera
        from robo.car import MockCar
        from robo.tools import Toolbox
        car = MockCar(); car._volts = 7.6
        tb = Toolbox(car, MockCamera(), NS(say=print), None)
        self.assertEqual(tb.run("get_battery", {})["content"][0]["text"], "about 45 percent (7.60 V), fine")
        car._volts = 7.0
        self.assertIn("hungry", tb.run("get_battery", {})["content"][0]["text"])


class FacesWhileTalking(unittest.TestCase):
    """[face:...] tags in a reply: not spoken, they change the face and move the head."""

    def test_split_and_strip(self):
        from robo.face import stage_directions, without_faces
        reply = "[face:surprised] Oh! [face: Laughing ]That is funny. [sound:laugh] [face:no_such_face] Really. [sound:no_such] [face:shy]"
        self.assertEqual(stage_directions(reply), [("face", "surprised"), ("say", "Oh!"), ("face", "laughing"), ("say", "That is funny."),
                                                   ("sound", "laugh"), ("say", "Really."), ("face", "shy")])
        self.assertEqual(without_faces(reply), "Oh! That is funny. Really.")
        self.assertEqual(stage_directions("Just words."), [("say", "Just words.")])
        self.assertEqual(stage_directions(""), [])
        self.assertEqual(stage_directions(None), [])
        self.assertEqual(stage_directions("[sound:think_burble] hm"), [("say", "hm")])   # the thinking mutters are not Claude's to play

    def test_speaker_shows_each_face_and_never_speaks_a_tag(self):
        import threading

        from robo.voice import Speaker
        sp = Speaker.__new__(Speaker)
        sp._lock = threading.Lock()
        sp._prepared, sp._prepared_lock = {}, threading.Lock()
        made = []
        sp._start_making = lambda text: made.append(text) or ([], None, threading.Event())
        spoken, shown, moved = [], [], []
        sp._say = spoken.append
        sp.face = NS(show=lambda f, hold=3.0: shown.append(f))
        sp.gesture = moved.append
        from robo import sounds
        played = []
        with patch("builtins.print"), patch.object(sounds, "play", lambda name, speaker_is_ours=False: played.append((name, speaker_is_ours))):
            sp.say("Hello. [face:laughing] Ha ha! [sound:laugh] [face:cool] Anyway.")
        self.assertEqual(spoken, ["Hello.", "Ha ha!", "Anyway."])
        self.assertEqual(shown, ["laughing", "cool"])
        self.assertEqual(moved, ["laughing", "cool"])
        self.assertEqual(played, [("laugh", True)])        # the voice already holds the speaker
        self.assertEqual(made, ["Hello.", "Ha ha!", "Anyway."])  # all of it is made before the first face or sound
        sp.gesture = lambda f: 1 / 0                        # a broken gesture must not cost the words
        spoken.clear()
        with patch("builtins.print"):
            sp.say("[face:happy] Still talking.")
        self.assertEqual(spoken, ["Still talking."])

    def test_every_gesture_belongs_to_a_face_and_stays_in_range(self):
        from robo import car as car_mod
        from robo.face import EXPRESSIONS
        self.assertTrue(set(car_mod.GESTURES) <= set(EXPRESSIONS))
        for name, moves in car_mod.GESTURES.items():
            self.assertLess(sum(w for _, _, w in moves), 1.3, name)
            for pan, tilt, _ in moves:
                self.assertLessEqual(abs(pan), config.CAM_PAN_LIMIT, name)
                self.assertLessEqual(abs(tilt), config.CAM_TILT_LIMIT, name)

    def test_gesture_moves_the_head_and_brings_it_back(self):
        from robo import car as car_mod
        looks = []
        car = car_mod.Car.__new__(car_mod.Car)
        car.look = lambda pan, tilt, settle=True: looks.append((pan, tilt))
        with patch("robo.car.time.sleep"):
            car.gesture("laughing")
            for t in __import__("threading").enumerate():
                if t.name == "gesture":
                    t.join(2)
        self.assertEqual(looks[-1], (0, 0))
        self.assertEqual(len(looks), len(car_mod.GESTURES["laughing"]) + 1)

    def test_diary_keeps_the_words_only(self):
        from robo import memory
        with tempfile.TemporaryDirectory() as d, patch.object(memory, "DIARY", Path(d)):
            memory.diary_add("tell me a joke", "[face:laughing] Why did the robot cross the road?")
            self.assertNotIn("face:", next(Path(d).glob("*.jsonl")).read_text())


class FasterReplies(unittest.TestCase):
    """The words of a reply are made while the robot still beeps, and the
    conversation is kept at Anthropic between requests."""

    def _speaker(self, made_in=0.3):
        import threading

        from robo.voice import Speaker
        sp = Speaker.__new__(Speaker)
        sp._lock = threading.Lock()
        sp._prepared, sp._prepared_lock = {}, threading.Lock()
        sp.face = sp.gesture = None
        sp.espeak, sp.mac_say = None, False
        sp.events = []

        def clip(sentence):
            sp.events.append(("make", sentence, time.time()))
            time.sleep(made_in)
            return ["play", sentence]
        sp._clip = clip
        return sp

    def test_words_are_made_while_the_sound_plays(self):
        from robo import sounds
        sp = self._speaker()
        events = sp.events

        def beep(name, speaker_is_ours=False):
            events.append(("sound", name, time.time()))
            time.sleep(0.3)
        with patch("builtins.print"), patch.object(sounds, "play", beep), \
                patch("subprocess.run", lambda cmd, **kw: events.append(("play", cmd[1], time.time()))):
            t0 = time.time()
            sp.say("[sound:chatter] He says he is very brave!")
        took = time.time() - t0
        self.assertEqual([e[:2] for e in events if e[0] != "make"], [("sound", "chatter"), ("play", "He says he is very brave!")])
        self.assertLess(took, 0.5)   # 0.3 s of beeps and 0.3 s of making, side by side; one after the other was 0.6 s
        self.assertEqual(sp._prepared, {})

    def test_a_prepared_reply_is_used_and_a_stale_one_dropped(self):
        sp = self._speaker(made_in=0.01)
        with patch("builtins.print"), patch("subprocess.run", lambda cmd, **kw: None):
            sp.prepare("Never said.")
            stale = sp._prepared["Never said."][2]
            sp.prepare("Hello there.")
            self.assertTrue(stale.is_set())
            sp.say("Hello there.")
        self.assertEqual([e[1] for e in sp.events if e[1] == "Hello there."], ["Hello there."])  # made once, not twice
        self.assertEqual(sp._prepared, {})

    def test_the_newest_message_carries_the_cache_mark(self):
        from robo.brain_api import with_breakpoint
        mark = {"type": "ephemeral"}
        history = [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "Hello!"}]
        sent = with_breakpoint([*history, {"role": "user", "content": "tell me a joke"}])
        self.assertEqual(sent[-1]["content"], [{"type": "text", "text": "tell me a joke", "cache_control": mark}])
        self.assertEqual(sent[:2], history)
        results = [{"type": "tool_result", "tool_use_id": "a", "content": []}, {"type": "tool_result", "tool_use_id": "b", "content": []}]
        sent = with_breakpoint([{"role": "user", "content": results}])
        self.assertNotIn("cache_control", sent[0]["content"][0])
        self.assertEqual(sent[0]["content"][1]["cache_control"], mark)
        self.assertNotIn("cache_control", results[1])   # the kept messages are not changed
        self.assertEqual(with_breakpoint([]), [])

    def test_never_more_than_two_cache_marks_in_a_long_conversation(self):
        import json

        from robo import memory
        done = NS(content=[NS(type="text", text="Beep!")], stop_reason="end_turn")
        brain, calls = Brains._direct(None, [done])
        with tempfile.TemporaryDirectory() as d, patch.object(memory, "DIARY", Path(d)), \
                patch.object(memory, "STATE", Path(d) / "s.json"):
            for i in range(10):
                brain.handle(f"question {i}")
        for kw in calls:
            marks = json.dumps(kw["messages"], default=str).count("cache_control") + json.dumps(kw["system"]).count("cache_control")
            self.assertEqual(marks, 2)


class GoogleSpeech(unittest.TestCase):
    """Google's voice and ears, with the old ones as stand-ins."""

    def _answer(self, sent, reply):
        import io
        import json

        def urlopen(request, timeout):
            sent.append((request.full_url, json.loads(request.data), timeout))
            return io.BytesIO(json.dumps(reply).encode())
        return urlopen

    def test_edge_pitch_and_rate_become_googles(self):
        from robo.google_speech import semitones, speaking_rate
        self.assertEqual(semitones("+0Hz"), 0.0)
        self.assertEqual(semitones("+40Hz"), 3.2)        # R2-D2
        self.assertEqual(semitones("-40Hz"), -3.9)       # giant
        self.assertEqual(speaking_rate("+20%"), 1.2)
        self.assertEqual(speaking_rate("-30%"), 0.7)

    def test_a_sentence_is_asked_for_with_the_key_and_the_voice(self):
        import base64

        from robo import google_speech
        sent = []
        with patch.dict(os.environ, {"GOOGLE_API_KEY": "k1"}), \
                patch("urllib.request.urlopen", self._answer(sent, {"audioContent": base64.b64encode(b"mp3").decode()})):
            self.assertEqual(google_speech.synthesize("Beep!", "en-GB-Neural2-A", "+20%", "+40Hz"), b"mp3")
            google_speech.synthesize("Beep!", "en-GB-Chirp3-HD-Kore", "+20%", "+40Hz", quiet=True)
        url, body, _ = sent[0]
        self.assertTrue(url.endswith("text:synthesize?key=k1"))
        self.assertEqual(body["voice"], {"languageCode": "en-GB", "name": "en-GB-Neural2-A"})
        self.assertEqual(body["audioConfig"]["pitch"], 3.2)
        self.assertNotIn("pitch", sent[1][1]["audioConfig"])   # Chirp 3 HD has none
        self.assertLess(sent[1][1]["audioConfig"]["volumeGainDb"], 0)

    def test_no_key_means_not_available(self):
        from robo import google_speech
        for value in ("", "paste-your-google-key-here"):
            with patch.dict(os.environ, {"GOOGLE_API_KEY": value}), self.assertRaises(google_speech.NotAvailable):
                google_speech.key()

    def test_googles_complaint_is_kept(self):
        import io
        import urllib.error

        from robo import google_speech

        def refuse(request, timeout):
            raise urllib.error.HTTPError(request.full_url, 403, "Forbidden", {},
                                         io.BytesIO(b'{"error": {"message": "Cloud Text-to-Speech API has not been used"}}'))
        with patch.dict(os.environ, {"GOOGLE_API_KEY": "k1"}), patch("urllib.request.urlopen", refuse), \
                self.assertRaisesRegex(RuntimeError, "403: Cloud Text-to-Speech API has not been used"):
            google_speech.synthesize("hi", "en-GB-Neural2-A")

    def test_words_come_back_from_the_recognizer(self):
        from robo import google_speech
        sent = []
        reply = {"results": [{"alternatives": [{"transcript": "what do you see"}]}, {"alternatives": [{"transcript": "today"}]}]}
        with patch.dict(os.environ, {"GOOGLE_API_KEY": "k1"}), patch("urllib.request.urlopen", self._answer(sent, reply)):
            self.assertEqual(google_speech.transcribe(b"\0\0" * 16000, "en-GB", ["R2-D2"]), "what do you see today")
        with patch.dict(os.environ, {"GOOGLE_API_KEY": "k1"}), patch("urllib.request.urlopen", self._answer([], {})):
            self.assertEqual(google_speech.transcribe(b"\0\0", "en-GB"), "")   # nothing understood
        config_sent = sent[0][1]["config"]
        self.assertEqual((config_sent["languageCode"], config_sent["sampleRateHertz"]), ("en-GB", 16000))
        self.assertEqual(config_sent["speechContexts"][0]["phrases"], ["R2-D2"])

    def test_without_a_key_the_next_voice_speaks_quietly(self):
        from robo.voice import Speaker
        sp = Speaker.__new__(Speaker)
        sp.player = "mpg123"
        sp._edge_clip = lambda text: ["edge", text]
        sp._piper_command = lambda text: ["piper", text]
        with patch.dict(os.environ, {"GOOGLE_API_KEY": ""}), patch.object(config, "VOICE_ENGINE", "google"), \
                patch("builtins.print") as printed:
            self.assertEqual(sp._clip("Hello."), ["edge", "Hello."])
        printed.assert_not_called()   # no key is a setting, not a failure

    def test_only_speech_meant_for_the_robot_goes_to_google(self):
        import numpy

        from robo import google_speech
        from robo.voice import Voice
        v = Voice.__new__(Voice)
        v.moonshine = NS(text=lambda pcm: "on the pi")
        asked = []
        tone = (numpy.sin(numpy.arange(16000) / 3) * 8000).astype(numpy.int16)
        pcm = numpy.concatenate([numpy.zeros(8000, numpy.int16), tone, numpy.zeros(8000, numpy.int16)]).tobytes()
        with patch.object(config, "LISTEN_ENGINE", "google"), patch("builtins.print"), \
                patch.object(google_speech, "transcribe", lambda pcm, language, phrases: asked.append(language) or "from google"):
            self.assertEqual(v._transcribe(pcm), "on the pi")              # the room, the television
            self.assertEqual(v._transcribe(pcm, for_me=True), "from google")
            self.assertEqual(asked, ["en-GB"])
        def down(*a):
            raise RuntimeError("no internet")
        with patch.object(config, "LISTEN_ENGINE", "google"), patch("builtins.print"), patch.object(google_speech, "transcribe", down):
            self.assertEqual(v._transcribe(pcm, for_me=True), "on the pi")  # the Pi listens itself instead
        with patch.object(config, "LISTEN_ENGINE", "moonshine"), patch.object(google_speech, "transcribe", down):
            self.assertEqual(v._transcribe(pcm, for_me=True), "on the pi")

    def test_self_check_is_fine_without_a_key(self):
        from robo import selfcheck
        with patch.dict(os.environ, {"GOOGLE_API_KEY": ""}):
            _, ok, detail = selfcheck.google_check()
        self.assertTrue(ok)
        self.assertIn("no key", detail)
