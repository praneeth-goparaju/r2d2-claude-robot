"""The direct Messages API brain. No Claude Code process in between, so replies
are faster and cheaper than through the Agent SDK. Paid from the Max plan's
monthly API credit when ANTHROPIC_API_KEY comes from the linked Console
organisation. Same tools, same prompt, same safety wrapper as the other brain.
"""
import time
from datetime import date

import anthropic

from . import config, memory
from .brain import SCHEMAS, TOOL_NAMES, decorate, system_prompt
from .car import STOP
from .tools import DESCRIPTIONS, Toolbox


def _to_api(blocks: list[dict]) -> list[dict]:
    """Neutral tool-result blocks to Messages API content blocks."""
    out = []
    for b in blocks:
        if b["type"] == "image":
            out.append({"type": "image", "source": {"type": "base64", "media_type": b.get("mimeType", "image/jpeg"), "data": b["data"]}})
        else:
            out.append({"type": "text", "text": b["text"]})
    return out


# A request with one of these words is about what the camera shows. The photo
# then goes along with the request, which saves a whole round trip to Claude
# (asking, being told "look", sending the photo, asking again): 1.5 to 6 s.
SEEING_WORDS = ("see", "look", "looking", "watch", "show", "showing", "holding", "wearing", "colour", "color", "read")


def about_seeing(text: str) -> bool:
    import re
    words = set(re.findall(r"[a-z]+", text.lower()))
    return any(w in words for w in SEEING_WORDS) or "what is this" in text.lower() or "what is that" in text.lower()


PHOTO_GONE = {"type": "text", "text": "(a photo was attached here; it has been put away)"}


def without_photos(message: dict) -> dict:
    """A message for the kept conversation: the same, with every photo replaced by
    a note (photos are large, and an old one says nothing about the room now) and
    without Claude's private reasoning."""
    content = message["content"]
    if isinstance(content, str):
        return message
    if message["role"] == "assistant":
        # Claude's private reasoning is signed for the exact conversation it was
        # written in. With the photo before it replaced, the API rejects it
        # ("Invalid signature in thinking block"), and it is not needed afterwards.
        rest = [b for b in content if getattr(b, "type", None) not in ("thinking", "redacted_thinking")]
        return {**message, "content": rest or [{"type": "text", "text": "(no reply)"}]}
    kept = []
    for block in content:
        if block.get("type") == "image":
            block = PHOTO_GONE
        elif block.get("type") == "tool_result" and isinstance(block.get("content"), list):
            block = {**block, "content": [PHOTO_GONE if b.get("type") == "image" else b for b in block["content"]]}
        kept.append(block)
    return {**message, "content": kept}


def with_breakpoint(messages: list[dict]) -> list[dict]:
    """The messages to send, with a cache mark on the last block of the newest one.
    Anthropic then keeps the whole conversation up to there, not only the
    instructions: the next tool round and the next request of the conversation
    read it from memory, which is quicker and a tenth of the price. The kept
    messages themselves stay unmarked, so there are never more than two marks
    (this one and the instructions'); the API allows four."""
    if not messages:
        return messages
    last = messages[-1]
    content = last["content"]
    if isinstance(content, str):
        content = [{"type": "text", "text": content}]
    if not content or not isinstance(content[-1], dict):
        return messages
    return [*messages[:-1], {**last, "content": [*content[:-1], {**content[-1], "cache_control": {"type": "ephemeral"}}]}]


class DirectBrain:
    def __init__(self, car, camera, voice, face=None, client=None):
        from .face import MockFace
        self.car, self.camera, self.voice = car, camera, voice
        self.face = face or MockFace(quiet=True)
        self.toolbox = Toolbox(car, camera, voice, self.face); self.toolbox.brain = self
        # reads ANTHROPIC_API_KEY; a stuck call gives up instead of freezing the robot
        self.client = client or anthropic.Anthropic(timeout=config.CLAUDE_TIMEOUT_S, max_retries=1)
        self.history: list[dict] = []
        self.turn_sizes: list[int] = []  # how many messages of history each spoken exchange takes
        self.history_day = date.today()
        self.tools = [{"name": n, "description": DESCRIPTIONS[n], "input_schema": SCHEMAS[n]} for n in TOOL_NAMES]
        if config.WEB_SEARCH:
            # a tool that runs at Anthropic: there is nothing for the robot to carry out
            search = {"type": "web_search_20260209", "name": "web_search", "max_uses": config.WEB_SEARCH_MAX_PER_REQUEST}
            if config.WEB_SEARCH_ONLY_SITES:
                search["allowed_domains"] = list(config.WEB_SEARCH_ONLY_SITES)
            self.tools.append(search)
        self._system_for = None

    @property
    def patrol_photos(self):
        return self.toolbox.patrol_photos

    @patrol_photos.setter
    def patrol_photos(self, photos):
        self.toolbox.patrol_photos = photos

    @property
    def system(self) -> list[dict]:
        """Rebuilt when the robot is renamed, so the prompt always has the current name."""
        if self._system_for != config.NAME:
            self._system = [{"type": "text", "text": system_prompt(), "cache_control": {"type": "ephemeral"}}]
            self._system_for = config.NAME
        return self._system

    def _with_photo(self, text: str):
        """The request, with a photo from where the camera points now when it is
        about seeing something. Without a working camera it is just the request."""
        if not about_seeing(text):
            return text
        try:
            import base64
            t0 = time.time()
            jpeg = self.camera.snapshot()
            note = (f"(A photo from my camera, taken just now, is attached; the nearest thing ahead is "
                    f"{self.car.distance_cm():.0f} cm away. Use the look tool only to see in another direction.) ")
            config.log("claude", f"photo taken in {time.time() - t0:.1f} s and sent with the request")
            return [{"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": base64.b64encode(jpeg).decode()}},
                    {"type": "text", "text": note + text}]
        except Exception as e:
            config.log("claude", f"no photo with the request ({e})")
            return text

    def handle(self, text: str, with_image: bool = True) -> str:
        """Run one spoken request. Returns the final spoken reply; never raises."""
        asked = text
        if self.history_day != date.today():  # the conversation lasts one day
            self.history, self.turn_sizes, self.history_day = [], [], date.today()
        decorated, who = decorate(text)
        messages = [*self.history, {"role": "user", "content": self._with_photo(decorated) if with_image else decorated}]
        final = ""
        spoken: list[str] = []  # said aloud on the way, before the final reply
        searched = False        # Claude looked something up on the web
        try:
            for _ in range(config.MAX_TOOL_ROUNDS + 1):
                if STOP.is_set():  # someone said stop: no more Claude rounds
                    self.car.stop()
                    return "Okay, I stopped."
                config.log("claude", "asking Claude")
                t0 = time.time()
                resp = self.client.messages.create(
                    model=config.MODEL, max_tokens=config.MAX_REPLY_TOKENS, system=self.system, tools=self.tools,
                    output_config={"effort": config.EFFORT}, messages=with_breakpoint(messages))
                messages.append({"role": "assistant", "content": resp.content})
                # an answer from the web arrives in many pieces of text, cut wherever a source is named
                final = " ".join("".join(b.text for b in resp.content if b.type == "text").split())
                wants = [f"{b.name}({', '.join(f'{k}={v!r}' for k, v in dict(b.input).items())})" for b in resp.content if b.type == "tool_use"]
                for b in resp.content:
                    if b.type == "server_tool_use":
                        searched = True
                        query = dict(b.input).get("query")
                        if query:  # the other steps are Anthropic sifting through the results
                            config.log("claude", f"searched the web for {query!r}")
                u = getattr(resp, "usage", None)  # "from memory": the part of the prompt Anthropic had kept from the last call
                sizes = (f" (read {u.input_tokens + (u.cache_creation_input_tokens or 0)} tokens new, "
                         f"{u.cache_read_input_tokens or 0} from memory, wrote {u.output_tokens})") if u else ""
                config.log("claude", f"replied in {time.time() - t0:.1f} s: " + ("wants " + "; ".join(wants) if wants else "final answer") + sizes)
                if resp.stop_reason == "refusal":
                    final = final or "I would rather not do that."
                    break
                if resp.stop_reason == "pause_turn":
                    # a long web search stopped half-way: asking again with what came so far carries it on
                    continue
                if resp.stop_reason != "tool_use":
                    if resp.stop_reason == "max_tokens" and not final:
                        final = "I lost my thread there. Ask me again?"
                    break
                if final:
                    # Words that come together with a tool call (the joke, before the
                    # laugh) are said now. Only the last reply is returned, and these
                    # used to be dropped: the robot laughed without telling the joke.
                    self.voice.say(final)
                    spoken.append(final)
                    final = ""
                results = []  # all results of one turn go back in a single user message
                for b in resp.content:
                    if b.type != "tool_use":
                        continue
                    r = self.toolbox.run(b.name, dict(b.input))
                    item = {"type": "tool_result", "tool_use_id": b.id, "content": _to_api(r["content"])}
                    if r["is_error"]:
                        item["is_error"] = True
                    results.append(item)
                messages.append({"role": "user", "content": results})
            else:
                self.car.stop()
                final = final or "I stopped, that was taking too many steps."
        except anthropic.AuthenticationError as e:
            self.car.stop(); print(f"[brain] key rejected: {e}")
            return "My key is not working. Please check it."
        except anthropic.RateLimitError as e:
            self.car.stop(); print(f"[brain] rate limit or credit: {e}")
            return "I need a short rest. Ask me again in a minute."
        except anthropic.APITimeoutError as e:
            self.car.stop(); print(f"[brain] timed out: {e}")
            return "That took too long, so I stopped. Ask me again?"
        except anthropic.APIConnectionError as e:
            self.car.stop(); print(f"[brain] no connection: {e}")
            return "I cannot reach the internet right now."
        except anthropic.APIStatusError as e:
            self.car.stop(); print(f"[brain] API error {e.status_code}: {e}")
            return "Sorry, my brain hiccuped. Say that again?"
        except Exception as e:  # a missing key raises TypeError here; a tool or the SDK may raise anything
            self.car.stop(); print(f"[brain] error: {e!r}")
            return "Sorry, my brain hiccuped. Say that again?"
        try:
            if who:
                memory.mark_celebrated(who)  # only once Claude has actually answered
            self.toolbox.count_turn()
            memory.diary_add(asked, " ".join([*spoken, final]))
        except Exception as e:  # a full or read-only SD card must not swallow the answer
            print(f"[brain] could not save: {e}")
        # The exchange is kept with its tool calls and their results. Kept as the two
        # sentences only, Claude saw answers with nothing behind them in the next
        # request and took them back ("I hadn't actually looked").
        turn = [without_photos(m) for m in messages[len(self.history):]]
        # Also after a web search: the pages it read are long, and would be sent
        # along (and paid for) again with every later request of the conversation.
        if not final or searched or turn[-1]["role"] != "assistant":  # cut off or refused: keep it simple and well-formed
            turn = [{"role": "user", "content": asked}, {"role": "assistant", "content": " ".join([*spoken, final]).strip() or "(no reply)"}]
        self.history += turn
        self.turn_sizes.append(len(turn))
        while len(self.turn_sizes) > config.HISTORY_TURNS:
            del self.history[:self.turn_sizes.pop(0)]
        return final

    def ping(self) -> tuple[bool, str]:
        """For the self-check: does the key work? Looks up the model, which costs no tokens."""
        try:
            self.client.models.retrieve(config.MODEL)
            return True, f"API key works, model {config.MODEL}"
        except anthropic.AuthenticationError:
            return False, "the API key was rejected"
        except anthropic.NotFoundError:
            return False, f"model {config.MODEL} not found"
        except Exception as e:
            return False, f"cannot reach Claude: {e.__class__.__name__}"

    def close(self) -> None:
        pass
