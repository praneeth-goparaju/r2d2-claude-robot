"""Program 3: first brain test. One photo, one Claude call, spoken description.

Point the car at something interesting. Needs Claude Code logged in on this machine.
"""
from _common import args

from robo.brain import make_brain
from robo.camera import make_camera
from robo.car import make_car
from robo.voice import make_voice

a = args()
car, camera, voice = make_car(a.mock), make_camera(a.mock), make_voice(keyboard=True)
brain = make_brain(car, camera, voice, mock_brain=a.mock_brain)
try:
    reply = brain.handle("Describe what you see in front of you in two sentences. Do not move.")
    voice.say(reply)
finally:
    car.stop(); car.reset(); camera.close(); brain.close()
