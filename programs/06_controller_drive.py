"""Program 6: drive with the Xbox controller over Bluetooth. No Claude.

Pair the controller first (bluetoothctl: scan on, pair, trust, connect).
Left stick left/right steers. Right trigger drives forward, left trigger
backward. Right stick pans and tilts the camera. B stops. A takes a photo
into snapshots/. Needs: sudo apt install python3-pygame

The talking robot (05_talk.py) can be driven with the controller as well, so
this program is for driving without Claude, and for --axes: with the wheels
off the ground it prints what each stick and trigger reports and does not move
the car. Other controllers or drivers may number them differently from the
AXIS_ values in robo/controller.py; change the numbers there to match.

Speed and steering go through the same safety wrapper as the brain, so the
car still refuses to drive into a wall or off a step.
"""
import time

from _common import args

from robo.camera import make_camera
from robo.car import make_car
from robo.controller import Controller, open_pad

a = args(extra={"--axes": "print what the sticks and triggers report; the car does not move"})
car, camera = make_car(a.mock), make_camera(a.mock)

if a.mock:
    print("mock: pretending the right trigger is held for 2 seconds")
    print(car.drive("forward", 30, 2.0, 10)); car.look(20, 5)
    car.stop(); car.reset(); camera.close(); raise SystemExit

pad = open_pad()
if pad is None:
    car.reset(); camera.close()
    raise SystemExit("no controller found; pair it over Bluetooth first")
print(f"controller: {pad.get_name()}")

try:
    if a.axes:
        import pygame
        while True:
            pygame.event.pump()
            print("  ".join(f"{i}:{pad.get_axis(i):+.2f}" for i in range(pad.get_numaxes())),
                  " buttons:", [i for i in range(pad.get_numbuttons()) if pad.get_button(i)])
            time.sleep(0.3)
    control = Controller(car, camera, pad)
    while control.tick():
        pass
    print("controller disconnected, stopping")
except KeyboardInterrupt:
    pass
finally:
    car.stop(); car.reset(); camera.close()
