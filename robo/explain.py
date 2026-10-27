"""How Robo explains itself. Short, true, and the same every time, so the kids
learn the real picture. Claude picks the level from who is asking."""
from . import config

TOPICS = {
    "overview": {
        "5": "I have ears, eyes, a brain and wheels. My ears hear you, my eyes take a photo, my brain asks Claude what to do, and my wheels do it. And I never ever go near the stairs.",
        "10": "When you say Hey Robo, a tiny computer inside me turns your words into text. It sends the text to Claude, a big computer far away that is very good at thinking. Claude cannot see or move, so it asks me to use my tools: look, drive, say. My computer checks every move is safe before doing it, then speaks the answer with my voice.",
        "p": "A Raspberry Pi runs offline speech recognition and a safety wrapper around the motors. Claude, reached through the Messages API, decides step by step using a small set of bounded tools. Reflexes like the obstacle stop and the edge stop never wait for Claude.",
    },
    "ears": {"5": "I listen for my name. When you say Hey Robo, I wake up.", "10": "My microphone records your voice and a program on my own computer turns it into words, without the internet. Only the words after Hey Robo are the question.", "p": "Vosk speech recognition on the Pi; the wake word gates every request; a daily cap is enforced before any model call."},
    "eyes": {"5": "My camera takes a photo when I need to look.", "10": "I cannot see all the time. When Claude needs to know what is in front of me, it calls my look tool, my camera turns and takes a photo, and Claude reads the photo.", "p": "A 5 MP camera on pan and tilt servos; frames are shrunk to 640 px and sent only on a look call, so turns that need no photo stay fast."},
    "brain": {"5": "Claude is my thinking friend who lives in the cloud.", "10": "Claude only gets my words and a list of my tools. It picks a tool, I do it, I tell it what happened, and it picks the next one, up to eight times, then it answers.", "p": "Claude Haiku 5.5 through the Messages API with an API key (the Agent SDK on the Claude Code login is the fallback), one shared set of bounded tools, max eight tool rounds, paid from the Max plan's API credit."},
    "safety": {"5": "I have a rule: never bump, never fall. Even if someone tells me to.", "10": "Before every move my computer checks: too fast, too long, something close, an edge? If yes, I stop and tell Claude why. Claude cannot switch this off. Falling takes less than a second and asking Claude takes a few, so the stop lives in me, not in Claude.", "p": "Closed tool schemas with config limits, SDK permissions that remove shell and file tools, a wrapper that polls ultrasonic and cliff sensors at 20 Hz, night mode and battery thresholds."},
    "voice": {"5": "My voice is called Sonia.", "10": "My words are turned into a real voice by a free service on the internet. If the Wi-Fi is down I use a simpler voice that lives inside me.", "p": "Edge neural TTS with the Robot HAT's offline voice as fallback; speech cached by hash so repeated phrases play instantly."},
    "face": {"5": "My little screen shows my eyes. I blink!", "10": "A tiny screen shows my eyes and mouth. I blink on my own, my eyes follow my camera, and my mouth moves when I talk. Claude can show feelings like happy or surprised.", "p": "SSD1306 OLED over I2C, Pillow renderer shared with the preview images, a blink thread and a talking animation."},
    "battery": {"5": "When my battery is low I get hungry and need charging.", "10": "Two rechargeable cells power me for about an hour and a half. When my battery lights go dark, a bit above seven volts, I say I am hungry and stop long drives; below six point eight I stop moving and ask to be plugged in.", "p": f"Two 18650 cells in series (2000 mAh, {config.BATTERY_FULL_V} V full) read through the HAT ADC; thresholds {config.BATTERY_HUNGRY_V} V and {config.BATTERY_EMPTY_V} V in config, matching the HAT's charge LEDs."},
    "night": {"5": "At night I whisper and do not drive, so nobody wakes up.", "10": "From eight in the evening to seven in the morning I speak softly, answer in one sentence and refuse to drive.", "p": "Night window in config; the drive tool returns a refusal and the prompt is prefixed with a night note."},
    "memory": {"5": "I remember what we did today.", "10": "I write down what I hear and say each day. Ask me how my day was and I tell you the best bits. I also remember my name if you rename me.", "p": "A JSONL diary per day (the last 30 days are kept) and a state file for the name; the brain keeps the day's conversation."},
}
LEVELS = {"5": "a five-year-old", "10": "a ten-year-old", "p": "a grown-up"}


def explain(topic: str, level: str) -> str:
    from . import config
    t = TOPICS.get(topic, TOPICS["overview"]); lvl = level if level in LEVELS else "10"
    return t[lvl].replace("Robo", config.NAME)  # a renamed robot explains itself by its new name
