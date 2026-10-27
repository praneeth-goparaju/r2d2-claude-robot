"""Program 1: prove the body works. No Claude, no microphone.

Drives forward, backward, steers, pans the camera and prints the distance.
Put the car on the floor with a metre of free space in front.
"""
import time

from _common import args

from robo.car import make_car

a = args()
car = make_car(a.mock)
try:
    print(f"distance ahead: {car.distance_cm():.0f} cm")
    print(car.drive("forward", 30, 1.0, 0))
    time.sleep(0.5)
    print(car.drive("backward", 30, 1.0, 0))
    time.sleep(0.5)
    print(car.drive("forward", 30, 1.0, 25))   # curve right
    print(car.drive("backward", 30, 1.0, 25))  # and back
    for pan in (-35, 0, 35, 0):
        car.look(pan, 0)
        print(f"camera pan {pan}: distance {car.distance_cm():.0f} cm")
    print("cliff sensor says:", "DANGER" if car.cliff() else "safe")
finally:
    car.stop(); car.reset()
    print("done")
