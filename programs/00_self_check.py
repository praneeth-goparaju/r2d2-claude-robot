"""Program 0: the robot checks itself and says what works. Run this first on Saturday.
sudo -E python3 programs/00_self_check.py        (add --mock on the Mac)
"""
from _common import args

from robo import selfcheck
from robo.camera import make_camera
from robo.car import make_car
from robo.face import make_face
from robo.voice import make_voice

a = args()
car, camera, voice, face = make_car(a.mock), make_camera(a.mock), make_voice(keyboard=True), make_face(a.mock)
try:
    results = selfcheck.run(car, camera, voice, face, brain=None)
    print(selfcheck.text(results))
    voice.say(selfcheck.spoken(results))
finally:
    car.stop(); car.reset(); camera.close(); face.close()
