"""The robot's tools, written once. Both brains (the Agent SDK one and the direct
Messages API one) call Toolbox.run(); neither touches hardware directly.

Tool results use one neutral shape: {"content": [blocks], "is_error": bool}
where a block is {"type": "text", "text": ...} or
{"type": "image", "data": base64, "mimeType": "image/jpeg"}.
"""
import base64
import time
from datetime import date

from . import assistant, config, explain, memory, selfcheck, sounds

DESCRIPTIONS = {
    "look": "Point the camera and return a photo of what the robot sees. Use pan 0, tilt 0 for straight ahead.",
    "drive": "Move the car for a bounded time. Forward motion stops automatically near obstacles. Returns what happened.",
    "get_distance": "Distance in cm from the front ultrasonic sensor to the nearest object.",
    "say": "Speak a short sentence aloud right now, for example before starting to move.",
    "express": "Show a face on the face screen for a few seconds: a feeling, or one of the funny faces.",
    "stop": "Stop all motion immediately and centre the wheels and camera.",
    "patrol": "Roam the room on your own for a while, stopping for obstacles and edges, and return the photos taken on the way. Only when someone asks you to patrol, explore or have a look around. Describe afterwards what you saw.",
    "review_patrol": "Return the photos taken during the last patrol so you can describe what you saw.",
    "get_time": "Current date and time.",
    "get_weather": f"Current weather and today's and tomorrow's forecast for {config.PLACE}.",
    "get_pollen": f"Current pollen levels for {config.PLACE}.",
    "set_timer": "Start a timer that speaks a message aloud when it ends.",
    "list_timers": "List running timers.",
    "get_battery": f"How full the car's battery is, as a percentage, with the voltage behind it. {config.battery_percent(config.BATTERY_HUNGRY_V)} percent or less is hungry, 0 percent is empty.",
    "play_sound": "Play a short robot sound through the speaker.",
    "read_diary": "Everything the robot heard and said today, oldest first.",
    "do_trick": "Do a little act with the camera head, the wheels, the face and a sound: a gesture such as nod, or a small performance such as sneeze, dizzy or celebrate.",
    "sing": "Sing one of the songs you know, swaying your head to it. Only when asked to sing or play a song.",
    "dance": "Play a tune and dance in place, then bow.",
    "freeze_dance": "One round of Freeze Dance: dance to a random song, stop the music without warning, and return two photos taken while everyone should be frozen, to see who moved.",
    "copy_my_dance": "One round of Copy My Dance: add a move to the dance and perform the whole sequence, each move with its own note, for the players to copy.",
    "name_that_tune": "One round of Name That Tune: play and dance to the opening of a secret song for the players to guess.",
    "hide_and_seek": "Hide and seek: count with eyes shut while the players hide, or seek by taking photos to the left, ahead and right.",
    "simon_says": "One order of Simon Says: say it aloud (with 'Simon says' when simon is true), wait while they do it, and return a photo of the players.",
    "color_hunt": "Color Hunt: pick a colour for the players to find, or check with a photo what they brought.",
    "set_voice_style": "Change the speaking voice style.",
    "become_character": "Become a famous film robot (voice, face, sounds, personality) with a little entrance, or go back to being yourself.",
    "self_check": "Test the body and the brain: battery, sensors, camera, ears, internet, Claude, voice, temperature, disk.",
    "get_status": "Name, model, battery, night mode, turns today, running timers, uptime.",
    "explain_myself": "A true, short explanation of how one part of the robot works, at the listener's level.",
    "set_name": "Rename the robot. Only after the person confirmed the new name.",
}
READ_ONLY = {"look", "get_distance", "review_patrol", "get_time", "get_weather", "get_pollen", "list_timers",
             "get_battery", "read_diary", "self_check", "get_status", "explain_myself"}


def text_block(s: str) -> dict:
    return {"type": "text", "text": s}


def image_block(jpeg: bytes) -> dict:
    return {"type": "image", "data": base64.b64encode(jpeg).decode("ascii"), "mimeType": "image/jpeg"}


class Toolbox:
    def __init__(self, car, camera, voice, face):
        self.car, self.camera, self.voice, self.face = car, camera, voice, face
        self.timers = assistant.Timers(speak=voice.say)
        self.patrol_photos: list[bytes] = []
        self.freeze_song, self.dance_moves, self.tunes_played, self.hunt_colors = None, [], [], []  # game state between rounds
        self.turns_today, self._turns_day = 0, date.today()
        self.brain = None  # set by the brain that owns this toolbox

    def count_turn(self) -> None:
        """One more answered request; the count starts again each day."""
        if self._turns_day != date.today():
            self.turns_today, self._turns_day = 0, date.today()
        self.turns_today += 1

    def run(self, name: str, args: dict) -> dict:
        """Run one tool. Never raises: a failure becomes an error result Claude can read,
        and the motors are stopped first."""
        t0 = time.time()
        try:
            out = getattr(self, "t_" + name)(**args)
        except Exception as e:
            try:
                self.car.stop()
            except Exception:
                pass
            config.log("tool", f"{name} failed after {time.time() - t0:.1f} s: {e}")
            return {"content": [text_block(f"error: {e}")], "is_error": True}
        if isinstance(out, str):
            out = [text_block(out)]
        said = next((b["text"] for b in out if b["type"] == "text"), "")
        config.log("tool", f"{name} took {time.time() - t0:.1f} s: {said[:100]}")
        return {"content": out, "is_error": False}

    # sight, motion, voice
    def t_look(self, pan, tilt):
        self.car.look(pan, tilt)
        jpeg = self.camera.snapshot()
        return [text_block(f"photo at pan={pan} tilt={tilt}, distance ahead {self.car.distance_cm():.0f} cm"), image_block(jpeg)]

    def t_drive(self, direction, speed, seconds, steer):
        return self.car.drive(direction, speed, seconds, steer)

    def t_get_distance(self):
        return f"{self.car.distance_cm():.0f} cm"

    def t_say(self, text):
        self.voice.say(text); return "said"

    def t_express(self, feeling):
        self.face.show(feeling); return f"face shows {feeling}"

    def t_stop(self):
        self.car.stop(); self.car.reset(); return "stopped"

    def t_patrol(self, seconds=None):
        from . import patrol
        seconds = max(10, min(config.PATROL_MAX_SECONDS, float(seconds or config.PATROL_SECONDS)))
        self.voice.say("Patrol starting.")
        photos, report = patrol.roam(self.car, self.camera, seconds)
        self.patrol_photos = photos
        # at most six photos go back: the first, the last and those evenly between
        step = max(1, -(-len(photos) // 6))
        shown = photos[::step][:5] + photos[-1:] if len(photos) > 6 else photos
        return [text_block(f"{report}. {len(shown)} of the photos, oldest first:")] + [image_block(p) for p in shown]

    def t_review_patrol(self):
        if not self.patrol_photos:
            raise RuntimeError("no patrol photos stored")
        return [text_block(f"{len(self.patrol_photos)} photos, oldest first")] + [image_block(p) for p in self.patrol_photos]

    # world
    def t_get_time(self):
        return assistant.now_text()

    def t_get_weather(self):
        return assistant.weather_text()

    def t_get_pollen(self):
        return assistant.pollen_text()

    def t_set_timer(self, minutes, message):
        return self.timers.add(minutes, message)

    def t_list_timers(self):
        return self.timers.list()

    # body, fun, memory
    def t_get_battery(self):
        v = self.car.battery_volts()
        if v < 0:
            return "battery reading unavailable"
        state = "empty" if v < config.BATTERY_EMPTY_V else "hungry, needs charging" if v < config.BATTERY_HUNGRY_V else "fine"
        return f"about {config.battery_percent(v)} percent ({v:.2f} V), {state}"

    def t_play_sound(self, name):
        return sounds.play(name)

    def t_read_diary(self):
        return memory.diary_today()

    def t_do_trick(self, name):
        return self.car.trick(name)

    def t_sing(self, song):
        from .car import STOP
        self.face.show("singing", hold=None)
        self.face.set_talking(True)   # the mouth moves with the song
        side = [1]

        def sway():
            side[0] = -side[0]
            self.car.look(12 * side[0], 6, settle=False)
        try:
            return sounds.play_song(song, on_beat=sway, stop=STOP.is_set)
        finally:
            self.face.set_talking(False)
            self.face.show("happy")
            self.car.look(0, 0, settle=False)

    def t_dance(self, seconds):
        return self.car.dance(seconds)

    # games
    def _fast(self) -> bool:
        from .car import MockCar
        return isinstance(self.car, MockCar)

    def t_freeze_dance(self):
        from . import games
        self.freeze_song, text, photos = games.freeze_dance(self.car, self.camera, self.face, self.freeze_song, self._fast())
        return [text_block(text)] + [image_block(p) for p in photos]

    def t_copy_my_dance(self, new_game):
        from . import games
        return games.copy_my_dance(self.car, self.face, self.dance_moves, new_game, self._fast())

    def t_name_that_tune(self, hint=False):
        from . import games
        return games.name_that_tune(self.car, self.face, self.tunes_played, hint, self._fast())[1]

    def t_hide_and_seek(self, phase, seconds=20):
        from . import games
        text, photos = games.hide_and_seek(self.car, self.camera, self.face, phase, seconds, self._fast())
        return [text_block(text)] + [image_block(p) for p in photos]

    def t_simon_says(self, command, simon):
        from . import games
        text, photos = games.simon_says(self.car, self.camera, self.face, self.voice, command, simon, self._fast())
        return [text_block(text)] + [image_block(p) for p in photos]

    def t_color_hunt(self, check):
        from . import games
        text, photos = games.color_hunt(self.car, self.camera, self.face, self.hunt_colors, check, self._fast())
        return [text_block(text)] + [image_block(p) for p in photos]

    def t_set_voice_style(self, style):
        from .voice import set_voice_style
        return set_voice_style(style)

    def t_become_character(self, name):
        from . import characters
        return characters.become(self.car, self.face, name, self._fast())

    def t_self_check(self):
        return selfcheck.text(selfcheck.run(self.car, self.camera, self.voice, self.face, self.brain))

    def t_get_status(self):
        if self._turns_day != date.today():
            self.turns_today, self._turns_day = 0, date.today()
        v = self.car.battery_volts()
        return (f"name {config.NAME}; model {config.MODEL}; battery {'unknown' if v < 0 else f'about {config.battery_percent(v)} percent ({v:.1f} V)'}; "
                f"night mode {'on' if assistant.is_night() else 'off'}; turns today {self.turns_today}; "
                f"timers: {self.timers.list()}; uptime {(time.time() - selfcheck.START) / 60:.0f} min")

    def t_explain_myself(self, topic, level):
        return explain.explain(topic, level)

    def t_set_name(self, name):
        try:
            memory.apply_name(name)
        except ValueError as e:
            return f"not renamed: {e}"
        memory.save_state(name=config.NAME)
        return f"renamed: you are now {config.NAME}, wake words {config.WAKE_WORDS}"
