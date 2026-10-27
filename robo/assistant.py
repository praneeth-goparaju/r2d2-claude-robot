"""Tier-one assistant abilities that need nothing but the Pi and the internet:
time, weather and pollen for config.PLACE (Open-Meteo, free, no key), and spoken
timers. Pure functions here; brain.py wraps them as tools.
"""
import json
import threading
import time
import urllib.request
from datetime import datetime
from pathlib import Path

from . import config

WMO = {0: "clear sky", 1: "mostly clear", 2: "partly cloudy", 3: "overcast", 45: "fog", 48: "fog",
       51: "light drizzle", 53: "drizzle", 55: "heavy drizzle", 61: "light rain", 63: "rain", 65: "heavy rain",
       71: "light snow", 73: "snow", 75: "heavy snow", 80: "rain showers", 81: "rain showers", 82: "heavy showers",
       95: "thunderstorm", 96: "thunderstorm with hail", 99: "thunderstorm with hail"}

# Pollen levels in grains per cubic metre, rough bands used by German forecasts
POLLEN_BANDS = [(0.5, "none"), (10, "low"), (50, "moderate"), (10**9, "high")]


def _get(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=8) as r:
        return json.load(r)


def _num(v, unit: str = "") -> str:
    """A forecast value for speech; Open-Meteo sends null when it has none."""
    return "unknown" if v is None else f"{v:.0f}{unit}"


def now_text() -> str:
    n = datetime.now()
    return n.strftime("It is %A %d %B %Y, %H:%M.")


def weather_text() -> str:
    lat, lon = config.LAT, config.LON
    w = _get(f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}"
             "&current=temperature_2m,apparent_temperature,precipitation,weather_code,wind_speed_10m"
             "&daily=temperature_2m_max,temperature_2m_min,precipitation_probability_max,weather_code"
             "&timezone=Europe%2FBerlin&forecast_days=2")
    c, d = w["current"], w["daily"]
    sky = WMO.get(c["weather_code"], "mixed")
    parts = [f"Now in {config.PLACE}: {_num(c['temperature_2m'])} degrees, feels like {_num(c['apparent_temperature'])}, {sky}, wind {_num(c['wind_speed_10m'])} km/h.",
             f"Today: high {_num(d['temperature_2m_max'][0])}, low {_num(d['temperature_2m_min'][0])}, rain chance {_num(d['precipitation_probability_max'][0], '%')}, {WMO.get(d['weather_code'][0], 'mixed')}.",
             f"Tomorrow: high {_num(d['temperature_2m_max'][1])}, low {_num(d['temperature_2m_min'][1])}, rain chance {_num(d['precipitation_probability_max'][1], '%')}, {WMO.get(d['weather_code'][1], 'mixed')}."]
    return " ".join(parts)


def pollen_text() -> str:
    lat, lon = config.LAT, config.LON
    p = _get(f"https://air-quality-api.open-meteo.com/v1/air-quality?latitude={lat}&longitude={lon}"
             "&current=alder_pollen,birch_pollen,grass_pollen,mugwort_pollen,olive_pollen,ragweed_pollen&timezone=Europe%2FBerlin")
    c = p["current"]
    out = []
    for key, name in (("birch_pollen", "birch"), ("alder_pollen", "alder"), ("grass_pollen", "grass"),
                      ("mugwort_pollen", "mugwort"), ("ragweed_pollen", "ragweed")):
        val = c.get(key) or 0.0
        band = next(b for limit, b in POLLEN_BANDS if val < limit)
        out.append(f"{name} {band}")
    note = " Open-Meteo has no data for ash, hazel, oak or beech, which also cause allergies for some people."
    return "Pollen in " + config.PLACE + " right now: " + ", ".join(out) + "." + note


TIMESYNC = Path("/run/systemd/timesync")


def clock_is_set() -> bool:
    """False while the Pi still runs on the time it had when it was switched off.
    It has no clock battery: until systemd-timesyncd reaches a time server
    (minutes after switching on, once the Wi-Fi is up) the clock can be hours or
    days wrong. timesyncd creates the file `synchronized` once it has the time.
    Without timesyncd (the Mac) the clock is taken as right."""
    return not TIMESYNC.is_dir() or (TIMESYNC / "synchronized").exists()


def is_night() -> bool:
    """True between config.NIGHT_START and config.NIGHT_END (wraps past midnight).
    Never while the clock is not set: a robot switched off in the evening would
    otherwise wake up the next morning believing it is still night, and speak at
    the night volume and refuse to drive until the clock catches up."""
    if not clock_is_set():
        return False
    h = datetime.now().hour + datetime.now().minute / 60
    start, end = config.night_start(), config.NIGHT_END
    return (h >= start or h < end) if start > end else (start <= h < end)


class Timers:
    """Spoken timers. A timer fires on a background thread and calls speak()."""

    def __init__(self, speak):
        self.speak = speak
        self.active: dict[int, tuple[float, str]] = {}
        self._next = 1
        self._lock = threading.Lock()

    def add(self, minutes: float, message: str) -> str:
        minutes = max(0.01, min(float(minutes), 24 * 60))
        with self._lock:
            tid = self._next; self._next += 1
            self.active[tid] = (time.time() + minutes * 60, message)
        t = threading.Timer(minutes * 60, self._fire, args=(tid,))
        t.daemon = True; t.start()
        return f"timer {tid} set for {minutes:g} minutes: {message}"

    def _fire(self, tid: int) -> None:
        with self._lock:
            item = self.active.pop(tid, None)
        if item:
            self.speak(f"Timer: {item[1]}")

    def list(self) -> str:
        with self._lock:
            if not self.active:
                return "no timers running"
            now = time.time()
            return "; ".join(f"timer {tid}: {msg} in {max(0, (due - now) / 60):.0f} minutes" for tid, (due, msg) in self.active.items())


class DailyCap:
    """Counts spoken turns per calendar day so the robot cannot use up the
    household's Claude plan. Resets at midnight."""

    def __init__(self, limit: int):
        self.limit, self.day, self.count = limit, datetime.now().date(), 0

    def allow(self) -> bool:
        today = datetime.now().date()
        if today != self.day:
            self.day, self.count = today, 0
        if self.count >= self.limit:
            return False
        self.count += 1
        return True
