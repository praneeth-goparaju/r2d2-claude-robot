"""Robo's face on a 0.96 inch I2C OLED (SSD1306, 128x64).

Wiring to the Robot HAT's I2C header: GND to GND, VCC to 3V3, SCL to SCL, SDA to SDA.
Pi side: `sudo pip3 install luma.oled --break-system-packages`, I2C enabled in
raspi-config (Interface Options). Without the screen, MockFace prints state changes.

The face is drawn with Pillow into a 128x64 one-bit image. The same renderer
makes the preview PNGs in docs/faces/ and drives the real screen, so previews
are exact. The face also blinks on its own, keeps its gaze on where the camera
points, and moves its mouth while the robot talks.
"""
import random
import threading
import time
from pathlib import Path

from PIL import Image, ImageDraw

W, H = 128, 64
EXPRESSIONS = ["neutral", "happy", "sad", "surprised", "love", "sleepy", "thinking",
               "listening", "talking", "wink", "hungry", "angry",
               # the funny ones, each drawn by its own function below
               "laughing", "silly", "cool", "dizzy", "crying", "starstruck", "shy",
               "kiss", "confused", "scared", "robot", "singing"]


def render(state: str, gaze: float = 0.0, blink: bool = False, mouth_open: bool = False) -> Image.Image:
    """Draw one frame. gaze is -1 (left) to 1 (right). Returns a 1-bit image."""
    img = Image.new("1", (W, H), 0)
    d = ImageDraw.Draw(img)
    dx = int(gaze * 10)
    if state in FUNNY:
        FUNNY[state](d, dx, blink, mouth_open)
        return img
    # eye boxes: (x, y, w, h)
    eyes = {
        "neutral":   ((28, 18, 24, 24), (76, 18, 24, 24)),
        "happy":     ((28, 22, 24, 16), (76, 22, 24, 16)),
        "sad":       ((28, 26, 24, 12), (76, 26, 24, 12)),
        "surprised": ((24, 12, 30, 30), (74, 12, 30, 30)),
        "love":      ((28, 18, 24, 24), (76, 18, 24, 24)),
        "sleepy":    ((28, 30, 24, 5),  (76, 30, 24, 5)),
        "thinking":  ((28, 18, 24, 24), (80, 14, 20, 20)),
        "listening": ((26, 14, 28, 28), (74, 14, 28, 28)),
        "talking":   ((28, 18, 24, 24), (76, 18, 24, 24)),
        "wink":      ((28, 18, 24, 24), (76, 29, 24, 4)),
        "hungry":    ((28, 24, 24, 14), (76, 24, 24, 14)),
        "angry":     ((28, 22, 24, 18), (76, 22, 24, 18)),
    }.get(state, ((28, 18, 24, 24), (76, 18, 24, 24)))
    for i, (x, y, w, h) in enumerate(eyes):
        if blink:
            y, h = y + h // 2 - 2, 4
        if state == "love":
            _heart(d, x + dx + w // 2, y + h // 2, 12)
            continue
        d.rounded_rectangle((x + dx, y, x + dx + w, y + h), radius=min(6, h // 2), fill=1)
        if state == "angry":  # slanted brows
            d.polygon([(x + dx - 2, y - 4), (x + dx + w + 2, y + 4), (x + dx + w + 2, y - 10), (x + dx - 2, y - 10)] if i == 0
                      else [(x + dx - 2, y + 4), (x + dx + w + 2, y - 4), (x + dx + w + 2, y - 10), (x + dx - 2, y - 10)], fill=0)
    # mouth
    mouth = {"happy": "smile", "love": "smile", "wink": "smile", "sad": "frown", "hungry": "frown",
             "surprised": "o", "talking": "o", "angry": "flat"}.get(state, "flat")
    if mouth_open and state not in ("sleepy",):
        mouth = "o"
    if mouth == "smile":
        d.arc((50, 38, 78, 60), 10, 170, fill=1, width=2)
    elif mouth == "frown":
        d.arc((50, 50, 78, 72), 190, 350, fill=1, width=2)
    elif mouth == "o":
        d.ellipse((58, 48, 70, 60), outline=1, width=2)
    else:
        d.line((54, 54, 74, 54), fill=1, width=2)
    # extras
    if state == "sleepy":
        for x, y, s in ((100, 6, 6), (108, 2, 8)):
            d.line((x, y, x + s, y), fill=1); d.line((x + s, y, x, y + s), fill=1); d.line((x, y + s, x + s, y + s), fill=1)
    if state == "thinking":
        d.ellipse((106, 4, 110, 8), fill=1); d.ellipse((112, 0, 118, 6), fill=1)
    if state == "hungry":
        d.rectangle((4, 50, 24, 60), outline=1); d.rectangle((24, 53, 26, 57), fill=1); d.rectangle((6, 52, 10, 58), fill=1)
    return img


def _heart(d: ImageDraw.ImageDraw, cx: int, cy: int, r: int) -> None:
    d.ellipse((cx - r, cy - r, cx, cy), fill=1)
    d.ellipse((cx, cy - r, cx + r, cy), fill=1)
    d.polygon([(cx - r, cy - r // 3), (cx + r, cy - r // 3), (cx, cy + r)], fill=1)


# The funny faces. Each function draws the whole face: d is the drawing, dx how
# far the eyes are shifted to follow the camera, blink and mouth_open as in render().
LEFT, RIGHT = 40, 88   # the middle of each eye


def _closed_eyes(d, dx, y=30):
    for cx in (LEFT, RIGHT):
        d.line((cx + dx - 12, y, cx + dx + 12, y), fill=1, width=3)


def _star(d, cx, cy, r):
    import math
    points = []
    for i in range(10):
        a = math.pi * i / 5 - math.pi / 2
        k = r if i % 2 == 0 else r * 0.45
        points.append((cx + k * math.cos(a), cy + k * math.sin(a)))
    d.polygon(points, fill=1)


def _laughing(d, dx, blink, mouth_open):
    for cx in (LEFT, RIGHT):   # eyes squeezed into arches
        d.arc((cx + dx - 13, 18, cx + dx + 13, 44), 200, 340, fill=1, width=4)
    d.chord((44, 34, 84, 62), 0, 180, fill=1)                    # wide open mouth
    if not mouth_open:
        d.chord((52, 50, 76, 64), 180, 360, fill=0)              # tongue line


def _silly(d, dx, blink, mouth_open):
    if blink:
        _closed_eyes(d, dx)
    else:
        d.ellipse((LEFT + dx - 15, 10, LEFT + dx + 15, 40), fill=1)       # one big eye
        d.ellipse((LEFT + dx - 2, 22, LEFT + dx + 6, 30), fill=0)
        d.ellipse((RIGHT + dx - 8, 20, RIGHT + dx + 8, 36), fill=1)       # one small eye
        d.ellipse((RIGHT + dx - 4, 24, RIGHT + dx + 2, 30), fill=0)
    d.line((50, 46, 78, 46), fill=1, width=2)                            # mouth
    d.rounded_rectangle((62, 46, 76, 58 if mouth_open else 62), radius=6, fill=1)   # tongue out
    d.line((69, 48, 69, 56), fill=0)


def _cool(d, dx, blink, mouth_open):
    d.line((14, 20, 114, 20), fill=1, width=3)                   # sunglasses
    for cx in (LEFT, RIGHT):
        d.rounded_rectangle((cx + dx - 17, 18, cx + dx + 17, 38), radius=6, fill=1)
        d.line((cx + dx - 10, 23, cx + dx - 2, 31), fill=0, width=2)   # a glint
    if mouth_open:
        d.ellipse((58, 46, 70, 58), outline=1, width=2)
    else:
        d.arc((56, 40, 86, 58), 20, 120, fill=1, width=2)        # a smirk to one side


def _dizzy(d, dx, blink, mouth_open):
    for cx in (LEFT, RIGHT):                                     # spirals for eyes
        for r in (13, 8, 3):
            d.arc((cx + dx - r, 28 - r, cx + dx + r, 28 + r), 0 if r != 8 else 180, 300 if r != 8 else 120, fill=1, width=2)
    for i in range(4):                                           # a wobbly mouth
        d.arc((46 + i * 9, 50, 55 + i * 9, 58), 180 if i % 2 == 0 else 0, 360 if i % 2 == 0 else 180, fill=1, width=2)
    _star(d, 112, 10, 6); _star(d, 14, 14, 4)


def _crying(d, dx, blink, mouth_open):
    for cx in (LEFT, RIGHT):
        if blink:
            d.line((cx + dx - 12, 28, cx + dx + 12, 28), fill=1, width=3)
        else:
            d.chord((cx + dx - 13, 14, cx + dx + 13, 40), 0, 180, fill=1)   # heavy lids
        d.polygon([(cx + dx - 6, 36), (cx + dx - 10, 48), (cx + dx - 2, 48)], fill=1)   # tears
        d.ellipse((cx + dx - 10, 44, cx + dx - 2, 52), fill=1)
    if mouth_open:
        d.ellipse((56, 48, 72, 62), outline=1, width=2)
    else:
        d.arc((50, 50, 78, 70), 200, 340, fill=1, width=2)


def _starstruck(d, dx, blink, mouth_open):
    if blink:
        _closed_eyes(d, dx)
    else:
        _star(d, LEFT + dx, 26, 15); _star(d, RIGHT + dx, 26, 15)
    d.chord((50, 38, 78, 62), 0, 180, fill=1)


def _shy(d, dx, blink, mouth_open):
    for cx in (LEFT, RIGHT):                                     # small eyes looking down and away
        if blink:
            d.line((cx - 16, 30, cx - 2, 30), fill=1, width=3)
        else:
            d.ellipse((cx - 16, 22, cx - 2, 36), fill=1)
        for i in range(3):                                       # blush
            d.line((cx - 8 + i * 6, 44, cx - 12 + i * 6, 50), fill=1)
    d.arc((56, 46, 72, 58), 20, 160, fill=1, width=2)


def _kiss(d, dx, blink, mouth_open):
    d.arc((LEFT + dx - 13, 18, LEFT + dx + 13, 40), 200, 340, fill=1, width=3)    # one eye shut
    if blink:
        d.arc((RIGHT + dx - 13, 18, RIGHT + dx + 13, 40), 200, 340, fill=1, width=3)
    else:
        d.rounded_rectangle((RIGHT + dx - 12, 18, RIGHT + dx + 12, 40), radius=6, fill=1)
    d.arc((58, 42, 68, 52), 270, 90, fill=1, width=2)            # lips drawn as a small 3
    d.arc((58, 50, 68, 60), 270, 90, fill=1, width=2)
    _heart(d, 100, 50, 7 if mouth_open else 6)


def _confused(d, dx, blink, mouth_open):
    if blink:
        _closed_eyes(d, dx)
    else:
        d.rounded_rectangle((LEFT + dx - 12, 22, LEFT + dx + 12, 40), radius=6, fill=1)
        d.rounded_rectangle((RIGHT + dx - 10, 12, RIGHT + dx + 10, 36), radius=6, fill=1)
    d.line((LEFT + dx - 14, 12, LEFT + dx + 14, 16), fill=1, width=2)   # one brow low, one high
    d.line((RIGHT + dx - 12, 6, RIGHT + dx + 12, 2), fill=1, width=2)
    d.line((52, 56, 60, 52), fill=1, width=2); d.line((60, 52, 68, 56), fill=1, width=2); d.line((68, 56, 76, 52), fill=1, width=2)
    d.arc((108, 2, 120, 14), 180, 90, fill=1, width=2); d.line((114, 14, 114, 18), fill=1, width=2); d.point((114, 22), fill=1)   # a question mark


def _scared(d, dx, blink, mouth_open):
    for cx in (LEFT, RIGHT):                                     # wide eyes with tiny pupils
        d.ellipse((cx - 16, 10, cx + 16, 42), outline=1, width=2)
        if not blink:
            d.ellipse((cx + dx - 3, 23, cx + dx + 3, 29), fill=1)
    for i in range(5):                                           # chattering mouth
        d.line((46 + i * 8, 52 if i % 2 else 58, 54 + i * 8, 58 if i % 2 else 52), fill=1, width=2)
    d.polygon([(118, 8), (114, 18), (122, 18)], fill=1); d.ellipse((114, 14, 122, 22), fill=1)   # a drop of sweat


def _robot(d, dx, blink, mouth_open):
    d.line((64, 0, 64, 6), fill=1, width=2); d.ellipse((60, 0, 68, 4), fill=1)   # antenna
    for cx in (LEFT, RIGHT):
        d.rectangle((cx - 14, 14, cx + 14, 38), outline=1, width=2)
        if blink:
            d.line((cx - 10, 26, cx + 10, 26), fill=1, width=2)
        else:
            d.rectangle((cx + dx - 6, 20, cx + dx + 6, 32), fill=1)
    d.rectangle((44, 46, 84, 60), outline=1, width=2)            # a grille for a mouth
    for x in range(52, 84, 8):
        d.line((x, 46, x, 60), fill=1)
    if mouth_open:
        d.rectangle((46, 52, 82, 54), fill=1)


def _singing(d, dx, blink, mouth_open):
    for cx in (LEFT, RIGHT):                                     # happy closed eyes
        d.arc((cx + dx - 12, 22, cx + dx + 12, 42), 200, 340, fill=1, width=3)
    if mouth_open:
        d.ellipse((54, 42, 74, 62), fill=1)
    else:
        d.ellipse((58, 46, 70, 58), outline=1, width=2)
    for x, y in ((104, 8), (16, 34)):                            # notes in the air
        d.ellipse((x, y + 10, x + 6, y + 15), fill=1); d.line((x + 6, y, x + 6, y + 12), fill=1, width=2); d.line((x + 6, y, x + 12, y + 3), fill=1, width=2)


FUNNY = {"laughing": _laughing, "silly": _silly, "cool": _cool, "dizzy": _dizzy, "crying": _crying,
         "starstruck": _starstruck, "shy": _shy, "kiss": _kiss, "confused": _confused, "scared": _scared,
         "robot": _robot, "singing": _singing}


# Stage directions in a reply. Claude may write [face:laughing] or [sound:tada]
# in its reply. Neither is spoken: at that point in the sentence the robot puts
# the face on (with the matching head gesture) or plays the sound. Unlike the
# express and play_sound tools this costs no extra round trip to Claude.
def stage_directions(text: str) -> list[tuple[str, str]]:
    """Cut a reply into what to do in order: ("say", words), ("face", name) and
    ("sound", name). A face or sound that does not exist is dropped."""
    import re

    from . import sounds
    out = []
    for piece in re.split(r"(\[\s*(?:face|sound)\s*:\s*[A-Za-z_ ]+?\s*\])", text or ""):
        tag = re.fullmatch(r"\[\s*(face|sound)\s*:\s*([A-Za-z_ ]+?)\s*\]", piece)
        if tag is None:
            if piece.strip():
                out.append(("say", piece.strip()))
            continue
        kind, name = tag.group(1), tag.group(2).strip().lower().replace(" ", "_")
        if name in (EXPRESSIONS if kind == "face" else sounds.NAMES):
            out.append((kind, name))
    return out


def without_faces(text: str) -> str:
    """The reply as plain words, for the screen, the log and the diary."""
    return " ".join(value for kind, value in stage_directions(text) if kind == "say")


def _font(size: int):
    from PIL import ImageFont
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # an older Pillow has only the one small size
        return ImageFont.load_default()


def render_text(text: str, title: str = "") -> Image.Image:
    """A frame of plain text for the screen, with an optional small heading.
    The words are wrapped to the width, and the largest of three letter sizes
    that fits the whole text is used; a text too long even for the smallest is
    cut off with three dots."""
    img = Image.new("1", (W, H), 0)
    d = ImageDraw.Draw(img)
    top = 0
    if title:
        d.text((0, 0), title, font=_font(10), fill=1)
        d.line((0, 12, W, 12), fill=1)
        top = 15
    lines, font, line_height = [], None, 0
    for size in (16, 13, 10):
        font, line_height = _font(size), size + 2
        lines, line = [], ""
        for word in text.split():
            trial = f"{line} {word}".strip()
            if d.textlength(trial, font=font) <= W or not line:
                line = trial
            else:
                lines.append(line); line = word
        if line:
            lines.append(line)
        if len(lines) * line_height <= H - top:
            break
    room = max(1, (H - top) // line_height)
    if len(lines) > room:
        lines = lines[:room]
        while lines[-1] and d.textlength(lines[-1] + "...", font=font) > W:
            lines[-1] = lines[-1][:-1]
        lines[-1] += "..."
    for i, line in enumerate(lines):
        d.text((0, top + i * line_height), line, font=font, fill=1)
    return img


def render_battery(volts: float, empty: float, full: float) -> Image.Image:
    """A large battery, filled as far as it is charged, with the request to charge."""
    img = Image.new("1", (W, H), 0)
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((20, 4, 100, 36), radius=4, outline=1, width=3)
    d.rectangle((100, 14, 106, 26), fill=1)
    from . import config
    percent = config.battery_percent(volts)
    if percent > 2:
        d.rectangle((25, 9, 25 + int(70 * percent / 100), 31), fill=1)
    text = f"Charge me!  {percent}%"
    font = _font(13)
    d.text(((W - d.textlength(text, font=font)) / 2, 44), text, font=font, fill=1)
    return img


def save_previews(folder: Path, scale: int = 3) -> list[Path]:
    """Write one PNG per expression plus a contact sheet. Used for docs and tests."""
    folder.mkdir(parents=True, exist_ok=True)
    out = []
    rows = -(-len(EXPRESSIONS) // 4)
    sheet = Image.new("L", (W * scale * 4 + 50, (H * scale + 30) * rows + 10), 40)
    for i, state in enumerate(EXPRESSIONS):
        img = render(state, gaze=0.3 if state == "thinking" else 0.0).convert("L").resize((W * scale, H * scale), Image.NEAREST)
        p = folder / f"{state}.png"; img.save(p); out.append(p)
        x, y = 10 + (i % 4) * (W * scale + 10), 10 + (i // 4) * (H * scale + 30)
        sheet.paste(img, (x, y))
        ImageDraw.Draw(sheet).text((x, y + H * scale + 6), state, fill=230)
    p = folder / "all-faces.png"; sheet.save(p); out.append(p)
    return out


class _BaseFace:
    """Shared state machine: current expression, gaze, blinking, talking."""

    notice, notice_until = None, 0.0   # a picture shown in place of the face for a while

    def __init__(self):
        self.state, self.gaze, self.talking = "neutral", 0.0, False
        self._lock = threading.Lock()
        self._revert: threading.Timer | None = None
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._animate, daemon=True)
        self._thread.start()

    def show(self, state: str, hold: float | None = 3.0) -> None:
        with self._lock:
            self.state = state if state in EXPRESSIONS else "neutral"
        self._draw()
        if self._revert:
            self._revert.cancel()
        if hold:
            self._revert = threading.Timer(hold, lambda: self.show("neutral", hold=None))
            self._revert.daemon = True; self._revert.start()

    def show_notice(self, picture: Image.Image, seconds: float) -> None:
        """Put a picture on the screen in place of the face; the face comes back
        by itself after `seconds`."""
        self.notice, self.notice_until = picture, time.time() + seconds
        self._draw()
        back = threading.Timer(seconds + 0.05, self._draw)
        back.daemon = True; back.start()

    def show_text(self, text: str, seconds: float = 4.0, title: str = "") -> None:
        self.show_notice(render_text(text, title), seconds)

    def show_battery(self, volts: float, seconds: float = 6.0) -> None:
        from . import config
        self.show_notice(render_battery(volts, config.BATTERY_EMPTY_V, config.BATTERY_FULL_V), seconds)

    def frame(self, blink: bool = False, mouth_open: bool = False) -> Image.Image:
        """What belongs on the screen now: a notice while one is up, else the face."""
        if self.notice is not None:
            if time.time() < self.notice_until:
                return self.notice
            self.notice = None
        return render(self.state, self.gaze, blink, mouth_open)

    def look_at(self, pan_degrees: float) -> None:
        """Called by the car when the camera pans, so the eyes follow."""
        self.gaze = max(-1.0, min(1.0, pan_degrees / 60.0))
        self._draw()

    def set_talking(self, on: bool) -> None:
        self.talking = on
        if not on:
            self._draw()

    def _animate(self) -> None:
        while not self._stop.is_set():
            if self.talking:
                self._draw(mouth_open=random.random() < 0.5); time.sleep(0.15)
            else:
                time.sleep(random.uniform(2.5, 5.5))
                if self.state not in ("sleepy", "wink"):
                    self._draw(blink=True); time.sleep(0.12); self._draw()

    def _draw(self, blink: bool = False, mouth_open: bool = False) -> None:
        raise NotImplementedError

    def close(self) -> None:
        self._stop.set()


class Face(_BaseFace):
    def __init__(self):
        from luma.core.interface.serial import i2c
        from luma.oled.device import ssd1306

        from . import config
        # rotate counts quarter turns: 2 is upside down (FACE_UPSIDE_DOWN in config)
        self.device = ssd1306(i2c(port=1, address=0x3C), rotate=2 if config.FACE_UPSIDE_DOWN else 0)
        super().__init__()
        self._draw()

    failed = 0  # frames that did not reach the screen

    def _draw(self, blink: bool = False, mouth_open: bool = False) -> None:
        """One frame to the screen. The screen shares its two wires with the Robot
        HAT, so a frame takes its turn with servo commands and sensor readings.
        A frame that still fails (a loose jumper wire, a glitch while a servo
        moves) is tried once more and then left out: the next one follows within
        seconds, and a lost blink must not end the blinking for good."""
        from .car import I2C_BUS
        # the blink thread and the main thread both draw: one I2C write at a time
        with self._lock:
            frame = self.frame(blink, mouth_open)
            for attempt in (1, 2):
                try:
                    with I2C_BUS:
                        self.device.display(frame)
                    return
                except OSError as e:
                    if attempt == 2:
                        self.failed += 1
                        if self.failed in (1, 10, 100, 1000):  # say it, but not for every frame
                            print(f"[face] {self.failed} frame(s) did not reach the screen ({e}); check its four wires if this keeps growing")
                    else:
                        time.sleep(0.05)


class MockFace(_BaseFace):
    def __init__(self, quiet: bool = False):
        self.quiet = quiet
        self.frames = 0
        super().__init__()

    def show(self, state, hold=3.0):
        if not self.quiet:
            print(f"[face] {state}")
        super().show(state, hold)

    def _draw(self, blink: bool = False, mouth_open: bool = False) -> None:
        with self._lock:
            self.last = self.frame(blink, mouth_open)  # exercise the renderer
        self.frames += 1


def make_face(mock: bool):
    if mock:
        return MockFace()
    try:
        return Face()
    except Exception as e:  # no screen wired yet: carry on without a face
        print(f"[face] no OLED found ({e}), using MockFace")
        return MockFace(quiet=True)
