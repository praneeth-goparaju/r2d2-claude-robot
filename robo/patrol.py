"""Roaming on its own: the car wanders with the obstacle and edge stops, and
takes a photo every few seconds. Claude is not in the driving loop; it gets the
photos afterwards. Used by programs/04_patrol.py and by the talking robot's
patrol tool ("R2-D2, go on patrol")."""
import random
import time

from . import config


def roam(car, camera, seconds: float, photo_every: float = 5.0, mock: bool = False) -> tuple[list[bytes], str]:
    """Wander for `seconds`. Returns (photos oldest first, one sentence on how it
    went). Ends early when someone says stop, at night, or with an empty battery;
    every move goes through the car's own safety checks."""
    photos: list[bytes] = []
    t0 = time.time()
    last_photo, stretches, obstacles, ended = 0.0, 0, 0, "the time was up"
    try:
        while time.time() - t0 < seconds:
            if time.time() - last_photo > photo_every:
                car.look(0, 0)
                try:
                    photos.append(camera.snapshot())
                except Exception as e:  # patrol on without photos
                    print(f"no photo: {e}")
                last_photo = time.time()
            result = car.drive("forward", 30, 1.5, random.choice([-15, 0, 0, 15]))
            # battery, clock, or someone said stop: end the patrol
            if "refused" in result or "night" in result or "someone said stop" in result:
                ended = result
                break
            stretches += 1
            if "stopped" in result:
                obstacles += 1
                car.drive("backward", 30, 0.8, 0)
                car.drive("forward", 30, 1.0, random.choice([-30, 30]))
            if mock:
                car._distance = 120.0  # mock: pretend the way clears again
    finally:
        car.stop(); car.reset()
    report = (f"roamed for {time.time() - t0:.0f} s: {stretches} stretches forward, turned away from something "
              f"{obstacles} times, {len(photos)} photos; ended because {ended}")
    config.log("patrol", report)
    return photos, report
