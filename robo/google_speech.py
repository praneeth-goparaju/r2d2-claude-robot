"""Google Cloud speech: its voice (Text-to-Speech) and its ears (Speech-to-Text),
through their plain web APIs with an API key, so nothing extra is installed.

The key is GOOGLE_API_KEY in ~/.robo.env. Without one, both raise NotAvailable
and the robot uses its other voices and its own recognizer, as before.
Only the request goes to Google, never the room: see Voice._transcribe."""
import base64
import json
import math
import os
import urllib.error
import urllib.request

TTS_URL = "https://texttospeech.googleapis.com/v1/text:synthesize"
STT_URL = "https://speech.googleapis.com/v1/speech:recognize"


class NotAvailable(Exception):
    """No key: a reason to use the next voice or recognizer, not worth a message."""


def key() -> str:
    from . import config
    value = os.environ.get("GOOGLE_API_KEY", "")
    if config.is_placeholder(value):
        raise NotAvailable("no GOOGLE_API_KEY in ~/.robo.env")
    return value


def _post(url: str, body: dict, timeout: float) -> dict:
    request = urllib.request.Request(f"{url}?key={key()}", data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as e:
        # the reason is in the body: "API not enabled", "key not valid", "quota"
        try:
            reason = json.loads(e.read())["error"]["message"]
        except Exception:
            reason = e.reason
        raise RuntimeError(f"Google said {e.code}: {str(reason)[:120]}") from None


def semitones(hz_offset: str, base_hz: float = 200.0) -> float:
    """An edge-tts pitch such as "+40Hz" as Google's pitch in semitones (-20 to
    20), for a voice of about base_hz: "+40Hz" -> 3.2, "-40Hz" -> -3.9."""
    hz = float(hz_offset.rstrip("Hz") or 0)
    return max(-20.0, min(20.0, round(12 * math.log2(max(20.0, base_hz + hz) / base_hz), 1)))


def speaking_rate(rate: str) -> float:
    """An edge-tts rate such as "+20%" as Google's speaking rate: 1.2."""
    return max(0.25, min(2.0, 1 + float(rate.rstrip("%") or 0) / 100))


def synthesize(text: str, voice: str, rate: str = "+0%", pitch: str = "+0Hz", quiet: bool = False,
               timeout: float = 4.0) -> bytes:
    """One sentence as MP3. Chirp 3 HD voices have no pitch setting, so the
    silly voices and characters keep only their speed there."""
    audio = {"audioEncoding": "MP3", "speakingRate": speaking_rate(rate), "volumeGainDb": -6.0 if quiet else 0.0}
    if "Chirp" not in voice:
        audio["pitch"] = semitones(pitch)
    body = {"input": {"text": text}, "voice": {"languageCode": "-".join(voice.split("-")[:2]), "name": voice},
            "audioConfig": audio}
    return base64.b64decode(_post(TTS_URL, body, timeout)["audioContent"])


def transcribe(pcm: bytes, language: str, phrases: list[str] = (), timeout: float = 5.0) -> str:
    """16 kHz 16-bit mono sound as text, "" when nothing was understood.
    phrases are words to expect, such as the robot's name."""
    body = {"config": {"encoding": "LINEAR16", "sampleRateHertz": 16000, "languageCode": language,
                       "model": "latest_short", "enableAutomaticPunctuation": True},
            "audio": {"content": base64.b64encode(pcm).decode()}}
    if phrases:
        body["config"]["speechContexts"] = [{"phrases": list(phrases), "boost": 15}]
    found = _post(STT_URL, body, timeout).get("results", [])
    return " ".join(r["alternatives"][0].get("transcript", "") for r in found if r.get("alternatives")).strip()
