"""The robot checks its own body and brain and says what works. Used at startup, by
the self_check tool ("R2-D2, are you okay?"), and by programs/00_self_check.py."""
import os
import shutil
import time
import urllib.request

from . import config

START = time.time()


def _cpu_temp() -> float | None:
    try:
        return int(open("/sys/class/thermal/thermal_zone0/temp").read()) / 1000
    except Exception:
        return None


def _power_text() -> str:
    """What the Pi itself says about its power supply (vcgencmd get_throttled)."""
    import subprocess
    try:
        out = subprocess.run(["vcgencmd", "get_throttled"], capture_output=True, text=True, timeout=2).stdout
        bits = int(out.strip().split("=")[1], 16)
    except Exception:
        return ""
    now = [text for bit, text in ((0, "voltage too low"), (1, "processor slowed down"), (2, "processor held back"), (3, "too hot")) if bits & 1 << bit]
    if now:
        return ", power: " + " and ".join(now) + " RIGHT NOW"
    return ", power: voltage was too low earlier" if bits & 1 << 16 else ", power: fine"


def computer_text(meminfo: str = "/proc/meminfo", status: str = "/proc/self/status") -> str | None:
    """One line about the Pi: memory in use, how busy and how warm the processor
    is, and its power supply. None where there is no /proc (a Mac)."""
    try:
        with open(meminfo) as f:
            kb = {line.split(":")[0]: int(line.split()[1]) for line in f if ":" in line}
        with open(status) as f:
            mine = next(int(line.split()[1]) for line in f if line.startswith("VmRSS"))
    except Exception:
        return None
    gb = 1024 * 1024
    used = (kb["MemTotal"] - kb["MemAvailable"]) / gb
    swap = (kb.get("SwapTotal", 0) - kb.get("SwapFree", 0)) / gb
    text = (f"memory {used:.1f} of {kb['MemTotal'] / gb:.1f} GB in use (this program {mine / gb:.1f} GB), "
            f"{swap:.1f} GB moved to the SD card")
    try:
        text += f"; processor load {os.getloadavg()[0]:.1f} of {os.cpu_count()}"
    except OSError:
        pass
    t = _cpu_temp()
    if t is not None:
        text += f", {t:.0f} degrees"
    return text + _power_text()


def log_computer() -> None:
    text = computer_text()
    if text:
        config.log("pi", text)


def capture_devices(root: str = "/proc/asound") -> list[str] | None:
    """Names of the sound cards that can record. Robot HAT V5 has a microphone on
    board; V4 has only a speaker, so a V4 car needs a USB microphone. None when
    the system has no ALSA (a Mac)."""
    import glob
    if not os.path.isdir(root):
        return None
    names = []
    for card in sorted({os.path.dirname(p) for p in glob.glob(os.path.join(root, "card*", "pcm*c"))}):
        try:
            with open(os.path.join(card, "id")) as f:
                names.append(f.read().strip())
        except OSError:
            names.append(os.path.basename(card))
    return names


def google_check() -> tuple[str, bool, str]:
    """Does the Google key work? Without one the robot uses its other voice and
    ears, which is fine. With one, two words are made, so a key that is wrong or
    whose APIs are not switched on shows up here and not as a silent fallback."""
    from . import google_speech
    try:
        google_speech.key()
    except google_speech.NotAvailable:
        return ("Google speech", True, "no key, so the Microsoft voice and the Pi's own ears are used")
    try:
        google_speech.synthesize("All good.", config.GOOGLE_VOICE[config.LANGUAGE])
        return ("Google speech", True, f"key works, voice {config.GOOGLE_VOICE[config.LANGUAGE]}")
    except Exception as e:
        return ("Google speech", False, str(e)[:120])


def run(car=None, camera=None, voice=None, face=None, brain=None) -> list[tuple[str, bool, str]]:
    """Each entry: (what, ok, detail). Never raises; a failing check is a result."""
    out = []
    # power
    if car is not None:
        v = car.battery_volts()
        if v < 0: out.append(("battery", False, "no reading from the HAT"))
        else:
            hungry = v < config.BATTERY_HUNGRY_V
            out.append(("battery", not hungry, f"about {config.battery_percent(v)} percent ({v:.1f} volts)" + (", hungry" if hungry else "")))
        try:
            d = car.distance_cm()
            detail = f"no echo: unplugged, or nothing within {config.ULTRASONIC_MAX_CM // 100} m" if d >= 999 else "no reading" if d <= 0 else f"{d:.0f} cm ahead"
            out.append(("distance sensor", 0 < d < 999, detail))
        except Exception as e: out.append(("distance sensor", False, str(e)))
        try:
            out.append(("edge sensor", True, "cliff" if car.cliff() else "floor under me"))
        except Exception as e: out.append(("edge sensor", False, str(e)))
    # senses
    if camera is not None:
        try:
            n = len(camera.snapshot()); out.append(("camera", n > 1000, f"photo of {n // 1000} KB"))
        except Exception as e: out.append(("camera", False, str(e)))
    model_dir = config.MODELS_DIR / config.VOSK_MODELS[config.LANGUAGE]
    if type(voice).__name__ != "KeyboardVoice":
        mics = capture_devices()
        if mics is not None:  # None: not Linux, nothing to look at
            out.append(("microphone", bool(mics), ", ".join(mics) if mics else
                        "none found: Robot HAT V4 has no microphone, plug in a USB one"))
    if type(voice).__name__ == "SpeakOnlyVoice":  # the model may be there, but the ears did not start
        out.append(("ears (speech model)", False, voice.reason))
    else:
        out.append(("ears (speech model)", model_dir.exists() or type(voice).__name__ == "KeyboardVoice", "ready" if model_dir.exists() else "model folder missing"))
    out.append(("face screen", True, "OLED connected" if face is not None and type(face).__name__ == "Face" else "no screen, that is optional"))
    # world
    try:
        urllib.request.urlopen(f"https://api.open-meteo.com/v1/forecast?latitude={config.LAT}&longitude={config.LON}&current=temperature_2m", timeout=5)
        out.append(("internet", True, "weather service reachable"))
    except Exception as e: out.append(("internet", False, f"cannot reach the internet: {e.__class__.__name__}"))
    if brain is None: out.append(("Claude", True, "not part of this check"))
    else:
        ping = getattr(brain, "ping", None)
        if ping is None:
            out.append(("Claude", False, "mock brain, no Claude"))
        else:  # actually ask, so a bad key or a dead login shows up here
            try:
                ok, detail = ping()
            except Exception as e:
                ok, detail = False, f"check failed: {e}"
            out.append(("Claude", ok, detail))
    if "google" in (config.VOICE_ENGINE, config.LISTEN_ENGINE):
        out.append(google_check())
    out.append(("voice", any(shutil.which(c) for c in ("afplay", "mpg123", "aplay")), "player found" if any(shutil.which(c) for c in ("afplay", "mpg123", "aplay")) else "no audio player"))
    # body of the computer
    t = _cpu_temp()
    if t is not None: out.append(("temperature", t < 75, f"{t:.0f} degrees"))
    free = shutil.disk_usage(config.ROOT).free / 1e9; out.append(("disk", free > 0.5, f"{free:.1f} GB free"))
    out.append(("uptime", True, f"{(time.time() - START) / 60:.0f} minutes since I woke up"))
    return out


def spoken(results) -> str:
    """One or two sentences a child understands."""
    bad = [f"{n}: {d}" for n, ok, d in results if not ok]
    good = sum(1 for _, ok, _ in results if ok)
    if not bad:
        return f"All {good} checks passed. I feel great!"
    return f"{good} things work. {len(bad)} need help: " + "; ".join(bad) + "."


def text(results) -> str:
    return "\n".join(f"{'OK ' if ok else 'BAD'} {n}: {d}" for n, ok, d in results)
