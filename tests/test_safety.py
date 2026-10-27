"""Safety and plumbing tests that run on the Mac: python -m unittest -v"""
import json
import unittest

from robo import config
from robo.brain import SCHEMAS, TOOL_NAMES, _family_section, system_prompt
from robo.car import MockCar
from robo.main import heard_wake_word


class CarLimits(unittest.TestCase):
    def setUp(self):
        # the car refuses to drive at night; tests must not depend on the clock
        from unittest.mock import patch
        self._day = patch("robo.assistant.is_night", return_value=False); self._day.start()

    def tearDown(self):
        self._day.stop()

    def test_speed_and_time_are_capped(self):
        car = MockCar()
        out = car.drive("forward", 999, 99, 0)
        self.assertIn(f"forward {config.MAX_SPEED}%", out)
        self.assertIn(f"for {config.MAX_MOVE_SECONDS:.1f}s", out)

    def test_forward_stops_near_obstacle(self):
        car = MockCar()
        car._distance = 40.0
        out = car.drive("forward", 30, 3.0, 0)
        self.assertIn("stopped: obstacle", out)

    def test_backward_is_not_blocked_by_front_sensor(self):
        car = MockCar()
        car._distance = 5.0
        out = car.drive("backward", 30, 1.0, 0)
        self.assertIn("completed", out)


class ToolSchemas(unittest.TestCase):
    def test_every_tool_schema_is_closed(self):
        self.assertEqual(set(TOOL_NAMES), {"look", "drive", "get_distance", "say", "express", "stop", "patrol", "review_patrol", "sing",
                                           "get_time", "get_weather", "get_pollen", "set_timer", "list_timers", "get_battery",
                                           "play_sound", "read_diary", "set_name", "do_trick", "dance", "set_voice_style",
                                           "self_check", "get_status", "explain_myself",
                                           "freeze_dance", "copy_my_dance", "name_that_tune", "become_character",
                                           "hide_and_seek", "simon_says", "color_hunt"})
        for name, schema in SCHEMAS.items():
            self.assertFalse(schema["additionalProperties"], name)
            json.dumps(schema)  # must be serialisable

    def test_drive_tool_cannot_exceed_config_limits(self):
        props = SCHEMAS["drive"]["properties"]
        self.assertEqual(props["speed"]["maximum"], config.MAX_SPEED)
        self.assertEqual(props["seconds"]["maximum"], config.MAX_MOVE_SECONDS)


class WakeWord(unittest.TestCase):
    def test_variants(self):
        self.assertEqual(heard_wake_word("hey r2-d2 what do you see"), "what do you see")
        self.assertEqual(heard_wake_word("hey r2-d2"), "")
        self.assertIsNone(heard_wake_word("what is the weather"))


class FamilyProfile(unittest.TestCase):
    def test_profile_reaches_system_prompt(self):
        from unittest.mock import patch
        example = config.ROOT / "robo" / "family.example.yaml"
        with patch.object(config, "FAMILY_FILE", example):
            self.assertIn("Mia", _family_section())
            self.assertIn("Leo", system_prompt())
            self.assertIn("I spy", system_prompt())


class Assistant(unittest.TestCase):
    def test_timer_speaks_when_due(self):
        from robo.assistant import Timers
        spoken = []
        t = Timers(speak=spoken.append)
        self.assertIn("timer 1", t.add(0.01, "pizza"))   # 0.6 s
        self.assertIn("pizza", t.list())
        import time
        time.sleep(1.2)
        self.assertEqual(spoken, ["Timer: pizza"])
        self.assertEqual(t.list(), "no timers running")

    def test_daily_cap(self):
        from robo.assistant import DailyCap
        cap = DailyCap(2)
        self.assertTrue(cap.allow()); self.assertTrue(cap.allow()); self.assertFalse(cap.allow())

    def test_pollen_bands(self):
        from robo.assistant import POLLEN_BANDS
        band = lambda v: next(b for limit, b in POLLEN_BANDS if v < limit)
        self.assertEqual([band(0), band(3), band(30), band(300)], ["none", "low", "moderate", "high"])


class FaceRenderer(unittest.TestCase):
    def test_every_expression_renders_and_differs(self):
        from robo.face import EXPRESSIONS, render
        frames = {e: render(e).tobytes() for e in EXPRESSIONS}
        self.assertEqual(len(set(frames.values())), len(EXPRESSIONS), "two expressions look identical")
        self.assertNotEqual(render("neutral", gaze=1.0).tobytes(), render("neutral", gaze=-1.0).tobytes())
        self.assertNotEqual(render("neutral", blink=True).tobytes(), render("neutral").tobytes())

    def test_previews_are_written(self):
        import tempfile
        from pathlib import Path

        from robo.face import save_previews
        with tempfile.TemporaryDirectory() as d:
            files = save_previews(Path(d))
            self.assertTrue(all(f.exists() and f.stat().st_size > 200 for f in files))


class Extras(unittest.TestCase):
    def test_sounds_synthesise(self):
        from robo import sounds
        for n in sounds.NAMES:
            self.assertGreater(sounds.path_for(n).stat().st_size, 1000, n)

    def test_night_window(self):
        from datetime import datetime
        from unittest.mock import patch

        from robo import assistant
        with patch("robo.assistant.datetime") as dt:
            dt.now.return_value = datetime(2026, 10, 7, 21, 30); self.assertTrue(assistant.is_night())
            dt.now.return_value = datetime(2026, 10, 7, 6, 59); self.assertTrue(assistant.is_night())
            dt.now.return_value = datetime(2026, 10, 7, 12, 0); self.assertFalse(assistant.is_night())

    def test_rename_and_diary_persist(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import patch

        from robo import config, memory
        old = (config.NAME, list(config.WAKE_WORDS), config.WAKE_SOUNDS_LIKE)
        with tempfile.TemporaryDirectory() as d, patch.object(memory, "STATE", Path(d) / "s.json"), patch.object(memory, "DIARY", Path(d) / "diary"):
            memory.apply_name("ziggy"); memory.save_state(name=config.NAME)
            config.NAME = "Robo"; memory.restore_name()
            self.assertEqual(config.NAME, "Ziggy"); self.assertIn("hey ziggy", config.WAKE_WORDS)
            memory.diary_add("play a game", "Let's play I spy!")
            self.assertIn("I spy", memory.diary_today())
        config.NAME, config.WAKE_WORDS, config.WAKE_SOUNDS_LIKE = old


class Fun(unittest.TestCase):
    def setUp(self):
        from unittest.mock import patch
        self._day = patch("robo.assistant.is_night", return_value=False); self._day.start()

    def tearDown(self):
        self._day.stop()

    def test_tricks_and_dance_on_mock(self):
        from robo.car import TRICKS, MockCar
        from robo.face import MockFace
        car = MockCar(); car.face = MockFace(quiet=True)
        for t in TRICKS:
            self.assertIn(t, car.trick(t))
        self.assertIn("bowed", car.dance(8))
        self.assertIn("unknown trick", car.trick("moonwalk"))

    def test_voice_styles_reset(self):
        from robo import config
        from robo.voice import set_voice_style
        self.assertIn("giant", set_voice_style("giant")); self.assertEqual(config.VOICE_PITCH, "-40Hz")
        set_voice_style("normal"); self.assertEqual(config.VOICE_PITCH, "+0Hz")

    def test_birthday_lookup(self):
        from datetime import date
        from unittest.mock import patch

        from robo import memory
        example = memory.config.ROOT / "robo" / "family.example.yaml"
        with patch("robo.memory.date") as d, patch.object(memory.config, "FAMILY_FILE", example):
            d.today.return_value = date(2026, 5, 30); self.assertEqual(memory.birthday_today(), "Leo")
            d.today.return_value = date(2026, 10, 7); self.assertIsNone(memory.birthday_today())

    def test_new_sounds_synthesise(self):
        from robo import sounds
        self.assertGreater(sounds.path_for("birthday").stat().st_size, 100000)
        self.assertGreater(sounds.path_for("dance").stat().st_size, 50000)


class SelfKnowledge(unittest.TestCase):
    def test_self_check_runs_on_mocks(self):
        from robo import selfcheck
        from robo.camera import MockCamera
        from robo.car import MockCar
        from robo.face import MockFace
        res = selfcheck.run(MockCar(), MockCamera(), None, MockFace(quiet=True), None)
        names = [n for n, _, _ in res]
        for n in ("battery", "distance sensor", "camera", "internet", "Claude", "disk"):
            self.assertIn(n, names)
        self.assertIn("checks passed", selfcheck.spoken([("x", True, "")]))
        self.assertIn("need help", selfcheck.spoken([("x", False, "broken")]))

    def test_explanations_exist_for_every_topic_and_level(self):
        from robo.explain import TOPICS, explain
        for t in TOPICS:
            for lvl in ("5", "10", "p"):
                self.assertGreater(len(explain(t, lvl)), 20, f"{t}/{lvl}")
        self.assertIn("stairs", explain("overview", "5"))


class DirectApi(unittest.TestCase):
    """The direct brain against a scripted stand-in for the API (no key needed)."""

    def _brain(self, replies):
        from types import SimpleNamespace as NS

        from robo.brain_api import DirectBrain
        from robo.camera import MockCamera
        from robo.car import MockCar
        from robo.face import MockFace
        from robo.voice import KeyboardVoice
        calls = []
        class Msgs:
            def create(self, **kw):
                calls.append(kw); return replies[min(len(calls) - 1, len(replies) - 1)]
        brain = DirectBrain(MockCar(), MockCamera(), KeyboardVoice(), MockFace(quiet=True), client=NS(messages=Msgs()))
        return brain, calls, NS

    def test_tool_round_trip_sends_photo_back(self):
        import tempfile
        from pathlib import Path
        from types import SimpleNamespace as NS
        from unittest.mock import patch

        from robo import memory
        tool_use = NS(content=[NS(type="tool_use", id="t1", name="look", input={"pan": 0, "tilt": 0})], stop_reason="tool_use")
        done = NS(content=[NS(type="text", text="I see a sofa.")], stop_reason="end_turn")
        brain, calls, _ = self._brain([tool_use, done])
        with tempfile.TemporaryDirectory() as d, patch.object(memory, "DIARY", Path(d)), patch("robo.assistant.is_night", return_value=False):
            reply = brain.handle("what do you see?")
        self.assertEqual(reply, "I see a sofa.")
        sent = calls[1]["messages"][-1]["content"][0]
        self.assertEqual(sent["type"], "tool_result"); self.assertEqual(sent["tool_use_id"], "t1")
        self.assertEqual([b["type"] for b in sent["content"]], ["text", "image"])
        self.assertEqual(calls[0]["model"], config.MODEL)
        self.assertEqual([t["name"] for t in calls[0]["tools"]], [*TOOL_NAMES, "web_search"])   # the robot's own, and the web

    def test_photo_goes_with_a_question_about_seeing(self):
        import tempfile
        from pathlib import Path
        from types import SimpleNamespace as NS
        from unittest.mock import patch

        from robo import memory
        from robo.brain_api import about_seeing
        self.assertTrue(about_seeing("What do you see?"))
        self.assertTrue(about_seeing("what colour is my shirt"))
        self.assertFalse(about_seeing("tell me a story about the sea"))
        self.assertFalse(about_seeing("how far is the wall"))
        done = NS(content=[NS(type="text", text="A sofa.")], stop_reason="end_turn")
        brain, calls, _ = self._brain([done, done])
        with tempfile.TemporaryDirectory() as d, patch.object(memory, "DIARY", Path(d)), patch("robo.assistant.is_night", return_value=False):
            brain.handle("what do you see?")
            first = calls[0]["messages"][0]["content"]
            self.assertEqual([b["type"] for b in first], ["image", "text"])
            self.assertTrue(first[1]["text"].endswith("what do you see?"))
            brain.handle("tell me a joke")
        # the photo itself is not kept in the conversation, only a note that there was one
        kept = calls[1]["messages"][0]["content"]
        self.assertEqual([b["type"] for b in kept], ["text", "text"])
        self.assertIn("photo was attached", kept[0]["text"])
        self.assertTrue(calls[1]["messages"][2]["content"][-1]["text"].endswith(") tell me a joke"))   # after the note of the time

    def test_tool_calls_stay_in_the_conversation_without_their_photos(self):
        import tempfile
        from pathlib import Path
        from types import SimpleNamespace as NS
        from unittest.mock import patch

        from robo import memory
        tool_use = NS(content=[NS(type="thinking", thinking="hm", signature="s"),
                               NS(type="tool_use", id="t1", name="look", input={"pan": 20, "tilt": 0})], stop_reason="tool_use")
        done = NS(content=[NS(type="thinking", thinking="hm", signature="s"), NS(type="text", text="A sofa.")], stop_reason="end_turn")
        brain, _, _ = self._brain([tool_use, done, done] + [done] * config.HISTORY_TURNS)
        with tempfile.TemporaryDirectory() as d, patch.object(memory, "DIARY", Path(d)), patch("robo.assistant.is_night", return_value=False):
            brain.handle("turn your head and tell me what is there")
            self.assertEqual([m["role"] for m in brain.history], ["user", "assistant", "user", "assistant"])
            # Claude's signed reasoning is not kept: the API rejects it once the photo before it is replaced
            self.assertEqual([[b.type for b in m["content"]] for m in brain.history if m["role"] == "assistant"], [["tool_use"], ["text"]])
            result = brain.history[2]["content"][0]
            self.assertEqual(result["type"], "tool_result")
            self.assertEqual([b["type"] for b in result["content"]], ["text", "text"])   # the photo became a note
            for i in range(config.HISTORY_TURNS):
                brain.handle(f"joke {i}")
        # the oldest exchange is dropped whole, tool call and result together
        self.assertTrue(brain.history[0]["content"].endswith(") joke 0"))
        self.assertEqual(len(brain.history), 2 * config.HISTORY_TURNS)

    def test_words_before_a_tool_call_are_spoken(self):
        import tempfile
        from pathlib import Path
        from types import SimpleNamespace as NS
        from unittest.mock import patch

        from robo import memory
        joke = NS(content=[NS(type="text", text="Why did the robot cross the road?"),
                           NS(type="tool_use", id="t1", name="get_distance", input={})], stop_reason="tool_use")
        done = NS(content=[NS(type="text", text="To recharge on the other side!")], stop_reason="end_turn")
        brain, _, _ = self._brain([joke, done])
        said = []
        brain.voice = NS(say=said.append)
        with tempfile.TemporaryDirectory() as d, patch.object(memory, "DIARY", Path(d)), patch("robo.assistant.is_night", return_value=False):
            reply = brain.handle("tell me a joke")
            diary = next(Path(d).glob("*.jsonl")).read_text()
        self.assertEqual(said, ["Why did the robot cross the road?"])      # said at once, not dropped
        self.assertEqual(reply, "To recharge on the other side!")
        self.assertIn("Why did the robot cross the road? To recharge", diary)

    def test_web_search_is_carried_on_and_not_kept_in_the_conversation(self):
        import tempfile
        from pathlib import Path
        from types import SimpleNamespace as NS
        from unittest.mock import patch

        from robo import memory
        paused = NS(content=[NS(type="server_tool_use", id="s1", name="web_search", input={"query": "news today"})], stop_reason="pause_turn")
        answer = NS(content=[NS(type="server_tool_use", id="s2", name="web_search", input={"query": "news for children"}),
                             NS(type="web_search_tool_result", tool_use_id="s2", content=[]),
                             NS(type="text", text="Three things happened: "), NS(type="text", text="a rocket flew, "), NS(type="text", text="and it rained.")],
                    stop_reason="end_turn")
        done = NS(content=[NS(type="text", text="Goodbye.")], stop_reason="end_turn")
        brain, calls, _ = self._brain([paused, answer, done])
        with tempfile.TemporaryDirectory() as d, patch.object(memory, "DIARY", Path(d)), patch("robo.assistant.is_night", return_value=False):
            reply = brain.handle("what is in the news?")
            self.assertEqual(reply, "Three things happened: a rocket flew, and it rained.")
            # the paused search was sent back as it was, with no extra message from the robot
            # (the list is shared, so the answer that followed sits at its end)
            self.assertEqual([m["role"] for m in calls[1]["messages"]], ["user", "assistant", "assistant"])
            brain.handle("bye then")
        # what the search read is not sent along again: only the question and the answer are kept
        self.assertEqual(calls[2]["messages"][:2], [{"role": "user", "content": "what is in the news?"},
                                                    {"role": "assistant", "content": "Three things happened: a rocket flew, and it rained."}])

    def test_every_request_carries_the_date_and_time(self):
        from unittest.mock import patch

        from robo.brain import decorate
        with patch("robo.assistant.is_night", return_value=False):
            text, _ = decorate("who is the world champion?")
        self.assertRegex(text, r"^\(now: \w+ \d\d \w+ \d{4}, \d\d:\d\d\) who is the world champion\?$")

    def test_web_search_can_be_switched_off_or_limited(self):
        from types import SimpleNamespace as NS
        from unittest.mock import patch

        from robo.brain_api import DirectBrain
        from robo.car import MockCar
        with patch.object(config, "WEB_SEARCH", False):
            self.assertNotIn("web_search", [t["name"] for t in DirectBrain(MockCar(), None, NS(say=print), client=NS()).tools])
        with patch.object(config, "WEB_SEARCH_ONLY_SITES", ["bbc.co.uk"]):
            tool = DirectBrain(MockCar(), None, NS(say=print), client=NS()).tools[-1]
        self.assertEqual(tool["allowed_domains"], ["bbc.co.uk"])
        self.assertEqual(tool["max_uses"], config.WEB_SEARCH_MAX_PER_REQUEST)

    def test_endless_tool_loop_is_cut_and_motors_stopped(self):
        import tempfile
        from pathlib import Path
        from types import SimpleNamespace as NS
        from unittest.mock import patch

        from robo import memory
        loop = NS(content=[NS(type="tool_use", id="t", name="get_distance", input={})], stop_reason="tool_use")
        brain, calls, _ = self._brain([loop])
        with tempfile.TemporaryDirectory() as d, patch.object(memory, "DIARY", Path(d)), patch("robo.assistant.is_night", return_value=False):
            reply = brain.handle("go forever")
        self.assertIn("too many steps", reply); self.assertEqual(len(calls), config.MAX_TOOL_ROUNDS + 1)

    def test_toolbox_errors_become_results(self):
        from robo.camera import MockCamera
        from robo.car import MockCar
        from robo.face import MockFace
        from robo.tools import Toolbox
        from robo.voice import KeyboardVoice
        tb = Toolbox(MockCar(), MockCamera(), KeyboardVoice(), MockFace(quiet=True))
        r = tb.run("no_such_tool", {})
        self.assertTrue(r["is_error"]); self.assertIn("error", r["content"][0]["text"])
        self.assertTrue(tb.run("review_patrol", {})["is_error"])
        self.assertEqual(tb.run("get_distance", {})["content"][0]["text"], "120 cm")


if __name__ == "__main__":
    unittest.main()
