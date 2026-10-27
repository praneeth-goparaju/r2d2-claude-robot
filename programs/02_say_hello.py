"""Program 2: prove audio works. Speaks, then repeats back what it hears.

On the Pi run with sudo -E, otherwise the speaker is silent. Say "bye" to end.
"""
from _common import args

from robo import config
from robo.voice import make_voice

a = args(listen=True)
voice = make_voice(a.keyboard)
voice.say(f"Hello, I am {config.NAME}. Say something and I will repeat it.")
while True:
    text = voice.listen()
    if not text:
        continue
    if text in ("bye", "goodbye", "tschüss"):
        voice.say("Bye!")
        break
    voice.say(f"You said: {text}")
