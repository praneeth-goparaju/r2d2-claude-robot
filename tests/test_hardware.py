"""Limits taken from the PiCar-X v2.0 hardware docs: python -m unittest -v"""
import os
import sys
import tempfile
import unittest
from types import ModuleType
from unittest.mock import patch

from robo import config
from tests.test_fixes import Daytime, FakePx, real_car


class Camera(Daytime):
    def test_pan_stays_inside_the_mount_range(self):
        self.assertLessEqual(config.CAM_PAN_LIMIT, 35)  # SunFounder's examples clamp to ±35
        px = FakePx()
        car = real_car(px)
        car.look(90, 90, settle=False); car.look(-90, -90, settle=False)
        pans = [a for k, a in px.log if k == "pan"]
        tilts = [a for k, a in px.log if k == "tilt"]
        self.assertEqual(pans, [config.CAM_PAN_LIMIT, -config.CAM_PAN_LIMIT])
        self.assertEqual(tilts, [config.CAM_TILT_LIMIT, -config.CAM_TILT_LIMIT])

    def test_tricks_never_ask_for_more_than_the_limit(self):
        from robo import car as car_mod
        asked = []
        car = car_mod.MockCar()
        car.look = lambda pan, tilt, settle=True: asked.append((pan, tilt))
        for t in car_mod.TRICKS:
            if t != "twirl":
                car_mod._do_trick(car, t, fast=True)
        car_mod._do_dance(car, 0.1, fast=True)
        self.assertTrue(asked)
        for pan, tilt in asked:
            self.assertLessEqual(abs(pan), config.CAM_PAN_LIMIT)
            self.assertLessEqual(abs(tilt), config.CAM_TILT_LIMIT)

    def test_look_tool_schema_matches_the_limit(self):
        from robo.brain import SCHEMAS
        pan = SCHEMAS["look"]["properties"]["pan"]
        self.assertEqual(pan["maximum"], config.CAM_PAN_LIMIT)
        self.assertIn(str(config.CAM_PAN_LIMIT), pan["description"])


class Battery(Daytime):
    def test_hungry_where_the_hat_leds_go_dark(self):
        self.assertEqual(config.BATTERY_HUNGRY_V, 7.15)  # both battery LEDs off below 7.15 V
        self.assertGreater(config.BATTERY_EMPTY_V, 6.0)  # pack protection cuts out at 6.0 V
        out = real_car(FakePx(), volts=7.1).drive("forward", 30, 3.0, 0)
        self.assertLess(float(out.split(" for ")[1].split("s,")[0]), 1.2)  # hungry: 1 s moves

    def test_battery_texts_follow_config(self):
        from robo import explain, tools
        from robo.brain import system_prompt
        hungry = f"{config.battery_percent(config.BATTERY_HUNGRY_V)} percent"   # people are told percentages
        self.assertIn(hungry, system_prompt())
        self.assertIn(hungry, tools.DESCRIPTIONS["get_battery"])
        self.assertIn(str(config.BATTERY_HUNGRY_V), explain.TOPICS["battery"]["p"])

    def test_self_check_uses_the_same_threshold(self):
        from robo import selfcheck
        from robo.car import MockCar
        car = MockCar(); car._volts = 7.1
        res = {n: (ok, d) for n, ok, d in selfcheck.run(car=car)}
        self.assertEqual(res["battery"], (False, "about 10 percent (7.1 volts), hungry"))


class Startup(unittest.TestCase):
    def _make_car(self):
        fake = ModuleType("picarx")
        px = FakePx()
        px.set_cliff_reference = lambda ref: px.log.append(("cliff_ref", ref))
        fake.Picarx = lambda: px
        resets = []
        hat = ModuleType("robot_hat")
        hat.I2C = type("I2C", (), {name: (lambda self, *a: None) for name in ("write", "read", "mem_write", "mem_read")})
        hat.ADC = type("ADC", (hat.I2C,), {})
        with patch.dict(sys.modules, {"picarx": fake, "robot_hat": hat}), \
                patch("robo.car.reset_hat_mcu", lambda: resets.append(1)), \
                patch("robo.car.time.sleep"):
            from robo.car import Car
            Car()
        return px, resets

    def test_hat_mcu_is_reset_before_the_car_starts(self):
        _, resets = self._make_car()
        self.assertEqual(resets, [1])

    def test_cliff_reference_is_left_to_the_calibration_by_default(self):
        px, _ = self._make_car()
        self.assertFalse([e for e in px.log if e[0] == "cliff_ref"])

    def test_cliff_reference_override(self):
        with patch.object(config, "CLIFF_REFERENCE", (200, 200, 200)):
            px, _ = self._make_car()
        self.assertIn(("cliff_ref", [200, 200, 200]), px.log)

    def test_mcu_reset_is_harmless_off_the_pi(self):
        from robo.car import reset_hat_mcu
        with patch.dict(sys.modules, {"robot_hat": None, "robot_hat.utils": None}):
            self.assertFalse(reset_hat_mcu())


class Microphone(unittest.TestCase):
    def _asound(self, cards):
        root = tempfile.mkdtemp()
        for i, (name, pcms) in enumerate(cards):
            card = os.path.join(root, f"card{i}")
            os.makedirs(card)
            with open(os.path.join(card, "id"), "w") as f:
                f.write(name + "\n")
            for pcm in pcms:
                os.makedirs(os.path.join(card, pcm))
        return root

    def test_finds_only_cards_that_record(self):
        from robo.selfcheck import capture_devices
        root = self._asound([("sndrpihifiberry", ["pcm0p"]), ("Device", ["pcm0p", "pcm0c"])])
        self.assertEqual(capture_devices(root), ["Device"])

    def test_v4_hat_alone_has_no_microphone(self):
        from robo.selfcheck import capture_devices
        self.assertEqual(capture_devices(self._asound([("sndrpihifiberry", ["pcm0p"])])), [])

    def test_no_alsa_means_nothing_to_check(self):
        from robo.selfcheck import capture_devices
        self.assertIsNone(capture_devices("/no/such/dir"))

    def test_self_check_says_to_plug_in_a_usb_mic(self):
        from robo import selfcheck
        with patch("robo.selfcheck.capture_devices", return_value=[]):
            res = {n: (ok, d) for n, ok, d in selfcheck.run()}
        ok, detail = res["microphone"]
        self.assertFalse(ok)
        self.assertIn("USB", detail)

    def test_keyboard_voice_skips_the_microphone(self):
        from robo import selfcheck
        from robo.voice import KeyboardVoice
        with patch("robo.selfcheck.capture_devices", return_value=[]):
            names = [n for n, _, _ in selfcheck.run(voice=KeyboardVoice.__new__(KeyboardVoice))]
        self.assertNotIn("microphone", names)


class MicrophonePick(unittest.TestCase):
    def test_usb_microphone_is_picked_by_name(self):
        from robo.voice import pick_microphone
        names = ["snd_rpi_hifiberry_dac: HifiBerry DAC HiFi pcm5102a-hifi-0 (hw:0,0)",
                 "USB PnP Sound Device: Audio (hw:1,0)", "default"]
        self.assertEqual(pick_microphone(names, "usb"), 1)

    def test_falls_back_to_the_default(self):
        from robo.voice import pick_microphone
        self.assertIsNone(pick_microphone(["default"], "USB"))
        self.assertIsNone(pick_microphone(["USB mic"], None))
        self.assertIsNone(pick_microphone([None, "x"], "USB"))


class NoMicrophone(unittest.TestCase):
    def test_missing_mic_is_said_once_and_retried(self):
        from robo.main import Ears
        said, waits = [], []

        class Deaf:
            fail = True
            def listen(self, timeout=None):
                if self.fail:
                    raise OSError("No Default Input Device Available")
                return "hey robo"
            def say(self, text): said.append(text)

        v = Deaf()
        ears = Ears(v, sleep=waits.append)
        self.assertEqual(ears.listen(), "")
        self.assertEqual(ears.listen(timeout=6), "")
        self.assertEqual(len(said), 1)
        self.assertIn("USB microphone", said[0])
        self.assertEqual(waits, [Ears.RETRY_S, Ears.RETRY_S])
        v.fail = False  # someone plugs one in
        self.assertEqual(ears.listen(), "hey robo")
        self.assertEqual(said[-1], "I can hear you now.")
        self.assertEqual(ears.listen(), "hey robo")
        self.assertEqual(len(said), 2)


class Ultrasonic(unittest.TestCase):
    def test_no_echo_detail_names_the_real_range(self):
        from robo import selfcheck
        from robo.car import MockCar
        car = MockCar(); car._distance = 999.0
        res = {n: (ok, d) for n, ok, d in selfcheck.run(car=car)}
        self.assertIn("4 m", res["distance sensor"][1])


if __name__ == "__main__":
    unittest.main()
