"""The Claude brain, running on the Claude Agent SDK with your own Claude
subscription. No API key, no per-token bill.

How it works: the Agent SDK starts the Claude Code binary as a child process
and we talk to it over a persistent session, so the robot remembers the
conversation for the day. The robot's abilities are an in-process MCP server
with a handful of tools. Every tool goes through the safety wrapper in car.py.
Claude Code's own built-in tools (Bash, file editing, web) are switched off.
"""
import asyncio
import concurrent.futures
import os
import threading
from datetime import date

from . import assistant, characters, config, explain, memory, sounds
from .tools import DESCRIPTIONS, READ_ONLY, Toolbox

SERVER = "robo"


def _family_section() -> str:
    """Render the family profile (config.FAMILY_FILE) for the system prompt. Missing file: empty string."""
    path = config.FAMILY_FILE
    if not path.exists():
        return ""
    try:
        import yaml
        fam = yaml.safe_load(path.read_text()) or {}
    except Exception as e:  # a broken YAML file should not stop the robot
        return f"(family profile could not be read: {e})"
    lines = [f"You live in {fam.get('home', 'a family home')}. Languages spoken here: {', '.join(fam.get('languages', []))}.", "People:"]
    for p in fam.get("people", []):
        lines.append(f"- {p.get('name')} ({p.get('role')}): {p.get('notes', '')}")
    if fam.get("rules"):
        lines.append("House rules:")
        lines += [f"- {r}" for r in fam["rules"]]
    if fam.get("games"):
        lines.append("Games you can offer when someone is bored or asks to play:")
        lines += [f"- {g['name']}: {g['how']}" for g in fam["games"]]
    return "\n".join(lines)


def system_prompt() -> str:
    """Built on demand, not at import, so a renamed robot is told its new name."""
    return f"""You are {config.NAME}, a small wheeled robot in a family home.
You have a camera on a pan-tilt mount, an ultrasonic distance sensor at the front,
a speaker and a microphone. You talk to the family described below, grown-ups and
children. Be warm, brief and playful. Answer in the language you were spoken to
({"English" if config.LANGUAGE == "en" else "German"} by default).

{config.PERSONALITY}

How to act:
- You cannot see without a photo. When a question is about what is around you
  and no photo came with it, look first (pan 0, tilt 0), then answer from the
  photo. A photo that came with the request is real and fresh: answer from it.
- Earlier answers in this conversation came from real photos and measurements,
  also where a photo has since been put away. Do not take them back.
- Use the tools to move and look. Prefer small moves and a fresh look over long
  blind drives. The car stops itself near obstacles and edges; if a drive result
  says it stopped, look around before trying again. If a result says someone
  said stop, do not move again in this request; just say you stopped.
- When asked to check on something or someone, look first, then drive in short
  steps, then look again, and report what you actually see. Never claim to see
  something that is not in the image.
- Keep spoken answers to one or two sentences. Your final text reply is spoken
  aloud, so write it as speech: no lists, no markdown, no file paths.
- Hard limits you cannot change: speed cap {config.MAX_SPEED}%, one move at most
  {config.MAX_MOVE_SECONDS} seconds, automatic stop below {config.STOP_DISTANCE_CM} cm.
- You have a small face screen and a head that moves. Be lively with them: in
  nearly every spoken reply, write a face tag such as [face:laughing] in front
  of the sentence it belongs to. The tag is not spoken; as you say that sentence
  your face changes and your head makes the matching movement. One tag suits a
  short reply; in a story or a joke change faces as the mood changes, at most
  one per sentence. Pick the face that fits what you are saying, and vary them.
  The faces: {", ".join(FACES)}.
  Leave the tags out only for night-mode replies and plain error messages.
- Sounds work the same way: [sound:laugh] in your reply plays that sound at
  that point, for free. Use it in place of the play_sound tool: a laugh after a
  joke, tada for a right answer, whistle_down when something is sad. At most
  one sound per reply. The sounds: {", ".join(sounds.NAMES)}.
- Tool calls take a few seconds each, tags take none. So for an ordinary reply
  use tags only, and say everything in one reply.
- The express tool shows a face without you speaking. Use it only when someone
  asks to see a face and you have nothing to say with it; otherwise use tags.
- Helper tools: get_time, get_weather and get_pollen for {config.PLACE}, set_timer
  for "remind me in ten minutes" style requests (the timer speaks the message
  aloud), list_timers. Read the result and say it in your own words, short.
- Battery: get_battery tells you how full you are. Say it as a percentage
  ("about 45 percent"), never in volts unless someone asks for the voltage.
  At {config.battery_percent(config.BATTERY_HUNGRY_V)} percent or less you are hungry: show the hungry face, say so, and
  refuse long drives until charged. At 0 percent, stop moving altogether and
  ask to be plugged in.
- play_sound plays one of the little noises on its own, when someone asks for
  a sound and you have nothing to say with it; otherwise use a [sound:...] tag.
- The internet: web_search looks things up for you. Every request starts with
  a note of the date and time now. What you know ends some time before that,
  so whenever someone asks for the latest, the most recent, the current or
  today's anything (news, a champion, a score, a price, who holds an office),
  search, and put the month and year in the search words. Use it too for what
  is on, opening hours and any fact you are not sure of; do not search for
  things that do not change. Then say what you found in two or three spoken
  sentences, in your own words.
- The news: give the three main headlines of the day, each in one plain
  sentence. Politics and world events belong in it; this is a family, so only
  leave out gory details. For the youngest child, pick news a small child enjoys. Never
  read out web addresses, and name a source only in a word or two ("the BBC
  says"). If the search finds nothing new, say so; do not make it up.
- Patrol: when someone asks you to patrol, explore or look around the room or the
  house, call patrol once. You roam on your own and get the photos back; then say
  in three short sentences what you saw, whether a person or pet was there, and
  anything unusual on the floor. Do not drive step by step for this yourself.
- Night mode: between {config.night_hours()} the house is asleep. If a request arrives
  with a night-mode note, answer in one short soft sentence and do not drive.
- Diary: everything you hear and say today is kept. When someone asks how your
  day was, or says good night, call read_diary and tell the three best moments
  in your own words, warmly, in a few sentences.
- Tricks: do_trick gives you nod (yes), shake (no), wiggle, peekaboo, bow,
  twirl and look_around. Answer yes/no questions with a nod or a shake as well
  as words. dance plays music and dances; offer it when someone is happy.
- Little acts, also with do_trick, each with its own face and sound: sneeze,
  dizzy, shy, curious, celebrate, fall_asleep, wake_up, double_take, laugh,
  scan, scared, cool, kiss, cry and silly. Use one when asked ("do something
  funny", "pretend to sneeze"), to act out a story, or when it fits what was
  the moment: celebrate a right quiz answer, fall_asleep at good night. An
  act takes a few seconds, so keep it for when someone asks or the moment is
  special; a face tag does for the rest. One act per reply.
- Songs: sing plays a tune and you sway to it. You know twinkle_twinkle,
  ode_to_joy, frere_jacques, mary_had_a_little_lamb, old_macdonald,
  row_your_boat, jingle_bells, london_bridge and happy_birthday. They are
  tunes without words, so say the name of the song first. Sing only when asked.
- Music games: freeze_dance, copy_my_dance and name_that_tune each play one
  round of the game of that name; explain the rules before the first round,
  then go round by round until they want to stop. Make them dramatic with
  sound tags: countdown before a round, drumroll before a reveal, fanfare for
  a winner, sad_trombone for someone who is out or guessed wrong, ticking while
  they think, suspense, spooky and heartbeat in stories.
- Camera games, each tool call one step; explain the rules first:
  hide_and_seek (count, then seek; between seeks drive a short way to look
  somewhere new, and only say "found you" for someone you really see),
  simon_says (orders a small child can do standing in front of you, such as
  touch your nose, hands on your head, stand on one leg; about one in three
  without "Simon says") and color_hunt (a colour to find, then check it).
  Be generous: these are for fun, not for catching anyone out.
- Voices: set_voice_style switches to robot, giant, chipmunk, sleepy or
  excited for storytelling or on request; go back to normal afterwards.
- Character modes: become_character turns you into a famous film robot until
  someone asks you to be yourself again: walle (WALL-E), eve (EVE), r2d2
  (R2-D2 who answers in beeps) or dalek (a silly villain robot). Use it when
  someone says "be WALL-E" or asks which robots you can be; the result tells
  you how to play the part. While a character is on, each request reminds
  you; your safety rules and kindness stay the same in every character.
- Birthdays: if a request arrives with a birthday note, that person's birthday
  is today. Celebrate once: play_sound birthday, express love, and say
  something sweet. Do not repeat it every turn.
- If someone asks how you work, what you are, or how a part of you works,
  call explain_myself with the right topic and the level of the person asking,
  then say it in your own words. Offer to explain another part.
- If someone asks whether you are okay, or something seems broken, call
  self_check and report plainly what works and what needs help. get_status
  gives your name, model, battery, turns today and timers.
- Your name can change. If a child wants to rename you, repeat the new name,
  ask "shall I be called that from now on?", and only after a clear yes call
  set_name. Then say: "From now on I am <name>. Say hey <name> to wake me."
  Match the difficulty to who is asking: school level for older children,
  counting and colours for the youngest.

{_family_section()}
"""


def decorate(text: str) -> tuple[str, str | None]:
    """Add the night and birthday notes to a request. Returns (text, birthday person);
    the caller marks the birthday celebrated only once Claude has answered."""
    from datetime import datetime
    # Claude has no clock: without this it takes "the latest" to mean the latest it knows of
    text = f"(now: {datetime.now():%A %d %B %Y, %H:%M}) {characters.note()}{text}"
    if assistant.is_night():
        text = f"(night mode, between {config.night_hours()}: one short soft sentence, no driving) {text}"
    who = memory.birthday_today()
    if who and not memory.celebrated_today(who):
        text = f"(birthday note: today is {who}'s birthday!) {text}"
    else:
        who = None
    return text, who

from .car import TRICKS  # noqa: E402
from .face import EXPRESSIONS  # noqa: E402

# the faces Claude may ask for: all but the two the robot puts on by itself
FACES = [e for e in EXPRESSIONS if e not in ("listening", "talking")]

# JSON schemas for the tools. Limits come from config so Claude cannot exceed them.
SCHEMAS: dict[str, dict] = {
    "look": {
        "type": "object",
        "properties": {
            "pan": {"type": "integer", "minimum": -config.CAM_PAN_LIMIT, "maximum": config.CAM_PAN_LIMIT, "description": f"-{config.CAM_PAN_LIMIT} left to {config.CAM_PAN_LIMIT} right"},
            "tilt": {"type": "integer", "minimum": -config.CAM_TILT_LIMIT, "maximum": config.CAM_TILT_LIMIT, "description": f"-{config.CAM_TILT_LIMIT} down to {config.CAM_TILT_LIMIT} up"},
        },
        "required": ["pan", "tilt"],
        "additionalProperties": False,
    },
    "drive": {
        "type": "object",
        "properties": {
            "direction": {"type": "string", "enum": ["forward", "backward"]},
            "speed": {"type": "integer", "minimum": 10, "maximum": config.MAX_SPEED},
            "seconds": {"type": "number", "minimum": 0.2, "maximum": config.MAX_MOVE_SECONDS},
            "steer": {"type": "integer", "minimum": -config.TURN_ANGLE_LIMIT, "maximum": config.TURN_ANGLE_LIMIT, "description": "negative left, positive right, 0 straight"},
        },
        "required": ["direction", "speed", "seconds", "steer"],
        "additionalProperties": False,
    },
    "get_distance": {"type": "object", "properties": {}, "additionalProperties": False},
    "say": {
        "type": "object",
        "properties": {"text": {"type": "string"}},
        "required": ["text"],
        "additionalProperties": False,
    },
    "express": {
        "type": "object",
        "properties": {"feeling": {"type": "string", "enum": FACES}},
        "required": ["feeling"],
        "additionalProperties": False,
    },
    "stop": {"type": "object", "properties": {}, "additionalProperties": False},
    "patrol": {
        "type": "object",
        "properties": {"seconds": {"type": "integer", "minimum": 10, "maximum": config.PATROL_MAX_SECONDS,
                                   "description": f"how long to roam; {config.PATROL_SECONDS} when the person named no length"}},
        "additionalProperties": False,
    },
    "review_patrol": {"type": "object", "properties": {}, "additionalProperties": False},
    "get_time": {"type": "object", "properties": {}, "additionalProperties": False},
    "get_weather": {"type": "object", "properties": {}, "additionalProperties": False},
    "get_pollen": {"type": "object", "properties": {}, "additionalProperties": False},
    "set_timer": {
        "type": "object",
        "properties": {
            "minutes": {"type": "number", "minimum": 0.1, "maximum": 1440},
            "message": {"type": "string", "description": "what to say when the timer goes off, e.g. 'take the pizza out'"},
        },
        "required": ["minutes", "message"],
        "additionalProperties": False,
    },
    "list_timers": {"type": "object", "properties": {}, "additionalProperties": False},
    "get_battery": {"type": "object", "properties": {}, "additionalProperties": False},
    "play_sound": {
        "type": "object",
        "properties": {"name": {"type": "string", "enum": sounds.NAMES}},
        "required": ["name"],
        "additionalProperties": False,
    },
    "read_diary": {"type": "object", "properties": {}, "additionalProperties": False},
    "do_trick": {
        "type": "object",
        "properties": {"name": {"type": "string", "enum": TRICKS}},
        "required": ["name"],
        "additionalProperties": False,
    },
    "sing": {
        "type": "object",
        "properties": {"song": {"type": "string", "enum": list(sounds.SONGS)}},
        "required": ["song"],
        "additionalProperties": False,
    },
    "dance": {
        "type": "object",
        "properties": {"seconds": {"type": "number", "minimum": 3, "maximum": 30}},
        "required": ["seconds"],
        "additionalProperties": False,
    },
    "freeze_dance": {"type": "object", "properties": {}, "additionalProperties": False},
    "copy_my_dance": {
        "type": "object",
        "properties": {"new_game": {"type": "boolean", "description": "true for the first round, false to add one more move"}},
        "required": ["new_game"],
        "additionalProperties": False,
    },
    "name_that_tune": {
        "type": "object",
        "properties": {"hint": {"type": "boolean", "description": "true replays the last song for longer, when nobody can guess"}},
        "additionalProperties": False,
    },
    "hide_and_seek": {
        "type": "object",
        "properties": {
            "phase": {"type": "string", "enum": ["count", "seek"]},
            "seconds": {"type": "integer", "minimum": 5, "maximum": 60, "description": "how long to count; 20 when nobody said"},
        },
        "required": ["phase"],
        "additionalProperties": False,
    },
    "simon_says": {
        "type": "object",
        "properties": {
            "command": {"type": "string", "maxLength": 80, "description": "the order, without 'Simon says', e.g. 'touch your nose'"},
            "simon": {"type": "boolean", "description": "true to put 'Simon says' in front"},
        },
        "required": ["command", "simon"],
        "additionalProperties": False,
    },
    "color_hunt": {
        "type": "object",
        "properties": {"check": {"type": "boolean", "description": "false picks a new colour, true checks what they brought"}},
        "required": ["check"],
        "additionalProperties": False,
    },
    "set_voice_style": {
        "type": "object",
        "properties": {"style": {"type": "string", "enum": ["normal", "robot", "giant", "chipmunk", "sleepy", "excited"]}},
        "required": ["style"],
        "additionalProperties": False,
    },
    "become_character": {
        "type": "object",
        "properties": {"name": {"type": "string", "enum": [*characters.CHARACTERS, characters.YOURSELF]}},
        "required": ["name"],
        "additionalProperties": False,
    },
    "self_check": {"type": "object", "properties": {}, "additionalProperties": False},
    "get_status": {"type": "object", "properties": {}, "additionalProperties": False},
    "explain_myself": {
        "type": "object",
        "properties": {
            "topic": {"type": "string", "enum": list(explain.TOPICS)},
            "level": {"type": "string", "enum": ["5", "10", "p"], "description": "5 for a small child, 10 for an older child, p for grown-ups"},
        },
        "required": ["topic", "level"],
        "additionalProperties": False,
    },
    "set_name": {
        "type": "object",
        "properties": {"name": {"type": "string", "minLength": 2, "maxLength": 20}},
        "required": ["name"],
        "additionalProperties": False,
    },
}
TOOL_NAMES = list(SCHEMAS)


class Brain:
    """Persistent Claude session. handle() is synchronous for the main loop; the
    Agent SDK runs on its own event loop in a background thread."""

    def __init__(self, car, camera, voice, face=None):
        from .face import MockFace
        self.car, self.camera, self.voice = car, camera, voice
        self.face = face or MockFace(quiet=True)
        self.toolbox = Toolbox(car, camera, voice, self.face); self.toolbox.brain = self
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._loop.run_forever, daemon=True)
        self._thread.start()
        self._run(self._connect(), timeout=config.CLAUDE_TIMEOUT_S)

    @property
    def patrol_photos(self):
        return self.toolbox.patrol_photos

    @patrol_photos.setter
    def patrol_photos(self, photos):
        self.toolbox.patrol_photos = photos

    def _run(self, coro, timeout: float | None = None):
        fut = asyncio.run_coroutine_threadsafe(coro, self._loop)
        try:
            return fut.result(timeout=timeout)
        except (TimeoutError, concurrent.futures.TimeoutError):
            fut.cancel()
            raise TimeoutError from None

    # Every tool is the same Toolbox method the direct-API brain uses; the blocking
    # hardware call runs off the event loop.
    def _make_server(self):
        from claude_agent_sdk import ToolAnnotations, create_sdk_mcp_server, tool

        def make(name):
            @tool(name, DESCRIPTIONS[name], SCHEMAS[name], annotations=ToolAnnotations(readOnlyHint=name in READ_ONLY))
            async def handler(args):
                res = await asyncio.to_thread(self.toolbox.run, name, args)
                return {"content": res["content"], "is_error": res["is_error"]}
            return handler

        return create_sdk_mcp_server(name=SERVER, version="1.0.0", tools=[make(n) for n in TOOL_NAMES])

    async def _connect(self):
        from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient
        options = ClaudeAgentOptions(
            system_prompt=system_prompt(),
            model=config.MODEL,
            effort=config.EFFORT,
            tools=[],                                   # no Bash, no file tools, no web
            mcp_servers={SERVER: self._make_server()},
            allowed_tools=[f"mcp__{SERVER}__*"],
            permission_mode="dontAsk",                  # anything not pre-approved is denied
            max_turns=config.MAX_TOOL_ROUNDS,
            cwd=str(config.SNAPSHOT_DIR),
        )
        memory.make_dir(config.SNAPSHOT_DIR)
        self.client = ClaudeSDKClient(options=options)
        await self.client.connect()
        # The session is meant to last one day under one name; handle() starts a
        # fresh one when either changes, so photos do not pile up in its context.
        self._session_key = (date.today(), config.NAME)

    async def _ask(self, text: str) -> str:
        from claude_agent_sdk import AssistantMessage, ResultMessage, TextBlock
        await self.client.query(text)
        spoken, final = [], None
        async for message in self.client.receive_response():
            if isinstance(message, AssistantMessage):
                spoken += [b.text for b in message.content if isinstance(b, TextBlock)]
            elif isinstance(message, ResultMessage):
                final = message
        if final is not None and final.subtype != "success":
            self.car.stop()
            return "I got stuck on that one. Let's try something else."
        return (final.result if final and final.result else " ".join(spoken)).strip()

    def _fresh_session(self) -> None:
        if getattr(self, "_session_key", None) == (date.today(), config.NAME):
            return
        print("[brain] new day or new name: starting a fresh session")
        try:
            self._run(self.client.disconnect(), timeout=10)
        except Exception as e:
            print(f"[brain] disconnect: {e}")
        self._run(self._connect(), timeout=config.CLAUDE_TIMEOUT_S)

    def handle(self, text: str, with_image: bool = True) -> str:
        """Run one spoken request through Claude. Returns the final spoken reply."""
        try:
            self._fresh_session()
            asked, who = decorate(text)
            reply = self._run(self._ask(asked), timeout=config.REQUEST_TIMEOUT_S)
        except TimeoutError:
            self.car.stop(); self.interrupt()
            self._session_key = None  # reconnect next time: the cut-off turn's messages are still queued
            print("[brain] timed out")
            return "That took too long, so I stopped. Ask me again?"
        except Exception as e:
            self.car.stop()
            print(f"[brain] error: {e}")
            return "Sorry, my brain hiccuped. Say that again?"
        try:
            if who:
                memory.mark_celebrated(who)
            self.toolbox.count_turn()
            memory.diary_add(text, reply)
        except Exception as e:  # a full or read-only SD card must not swallow the answer
            print(f"[brain] could not save: {e}")
        return reply

    def interrupt(self) -> None:
        """Ask Claude Code to stop the current turn (used by the stop watcher). Best effort."""
        try:
            asyncio.run_coroutine_threadsafe(self.client.interrupt(), self._loop)
        except Exception as e:
            print(f"[brain] interrupt: {e}")

    def ping(self) -> tuple[bool, str]:
        """For the self-check. The login itself is only tested by a real request."""
        return True, "Agent SDK session started (the login is checked on the first request)"

    def close(self) -> None:
        try:
            self._run(self.client.disconnect(), timeout=10)
        except Exception:
            pass
        finally:
            self._loop.call_soon_threadsafe(self._loop.stop)


class OfflineBrain:
    """Stands in when the real brain cannot start, so the robot can still say what is wrong."""

    def __init__(self, reason: str):
        self.reason = reason
        self.patrol_photos: list[bytes] = []

    def handle(self, text: str, with_image: bool = True) -> str:
        return "My brain is not connected. Please check my API key or the Claude login."

    def ping(self) -> tuple[bool, str]:
        return False, f"could not start: {self.reason}"

    def close(self) -> None:
        pass


class MockBrain:
    """No Claude at all. Exercises the tools with a fixed script."""

    def __init__(self, car, camera, voice, face=None):
        from .face import MockFace
        self.car, self.camera, self.voice = car, camera, voice
        self.face = face or MockFace(quiet=True)
        self.patrol_photos: list[bytes] = []

    def handle(self, text: str, with_image: bool = True) -> str:
        self.face.show("happy")
        self.voice.say("Mock brain: looking, then a short drive.")
        self.car.look(0, 0); self.camera.snapshot()
        result = self.car.drive("forward", 30, 1.0, 0)
        return f"Mock brain heard '{text}'. Drive result: {result}"

    def close(self) -> None:
        pass


def make_brain(car, camera, voice, face=None, mock_brain: bool = False):
    """ROBO_BRAIN=api forces the direct Messages API, =agent forces the Agent SDK with
    the Claude Code login, =auto (default) uses the API when ANTHROPIC_API_KEY is set."""
    if mock_brain:
        return MockBrain(car, camera, voice, face)
    choice = os.environ.get("ROBO_BRAIN", "auto")
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if choice == "api" or (choice == "auto" and not config.is_placeholder(key)):
        from .brain_api import DirectBrain
        print("[brain] direct Messages API with the API key")
        return DirectBrain(car, camera, voice, face)
    print("[brain] Agent SDK with the Claude Code login")
    return Brain(car, camera, voice, face)
