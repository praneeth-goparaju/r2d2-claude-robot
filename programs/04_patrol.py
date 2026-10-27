"""Program 4: roam for a while, then let Claude summarise what the camera saw.

Claude is NOT in the driving loop here. The car wanders with obstacle and cliff
stops, takes a photo every few seconds, and at the end Claude gets the photos
and writes a short report. Good for "go and have a look around".
"""
from _common import args

from robo.assistant import is_night
from robo.brain import make_brain
from robo.camera import make_camera
from robo.car import make_car
from robo.patrol import roam
from robo.voice import make_voice

PATROL_SECONDS = 30
PHOTO_EVERY = 5

a = args()
if is_night():
    raise SystemExit("It is night time (see NIGHT_START in robo/config.py), so no patrol now.")
car, camera, voice = make_car(a.mock), make_camera(a.mock), make_voice(keyboard=True)
brain = make_brain(car, camera, voice, mock_brain=a.mock_brain)
try:
    voice.say("Patrol starting.")
    photos, _ = roam(car, camera, PATROL_SECONDS, PHOTO_EVERY, mock=a.mock)
    voice.say("Patrol done, thinking about what I saw.")
    brain.patrol_photos = photos
    reply = brain.handle(f"You just finished a {PATROL_SECONDS} second patrol of the room. Call review_patrol to see the photos, then say in three short sentences what the room looks like, whether any person or pet is visible, and anything unusual on the floor.", with_image=False)
    voice.say(reply)
finally:
    car.stop(); car.reset(); camera.close(); brain.close()
