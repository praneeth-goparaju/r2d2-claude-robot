"""Driving with the Xbox controller over Bluetooth.

Left stick left/right steers. Right trigger drives forward, left trigger
backward. Right stick pans and tilts the camera. B stops. A takes a photo
into snapshots/.

Used on its own by programs/06_controller_drive.py and, in the background, by
the talking robot (robo/main.py), so the car can be driven while it listens
and answers. Speed and steering go through the same safety wrapper as the
brain, so the car still refuses to drive into a wall or off a step.
"""
import os
import threading
import time

from . import config
from .car import STOP

# As this car's Xbox Series controller reports them over Bluetooth (checked with
# it). Other controllers or drivers may number them differently: run
# programs/06_controller_drive.py --axes to see, and change the numbers to match.
AXIS_STEER = 0                       # left stick, left/right
AXIS_BACK, AXIS_FORWARD = 4, 5       # left and right trigger
AXIS_PAN, AXIS_TILT = 2, 3           # right stick
BUTTON_A, BUTTON_B = 0, 1

DEAD = 0.15          # a stick or trigger moved less than this counts as untouched
SEARCH_EVERY_S = 3   # how often a controller that is not connected is looked for


def open_pad():
    """The first connected controller as a pygame joystick, or None. Call it from
    the thread that will read the controller."""
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")  # no screen over SSH; pygame's events need one
    os.environ.setdefault("SDL_JOYSTICK_ALLOW_BACKGROUND_EVENTS", "1")  # there is no window to have the focus
    os.environ.setdefault("SDL_NO_SIGNAL_HANDLERS", "1")  # Ctrl+C and systemctl stop stay with the robot
    os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
    import pygame
    if not pygame.get_init():
        pygame.init()
    pygame.joystick.quit(); pygame.joystick.init()  # look again: one may have connected since
    if pygame.joystick.get_count() == 0:
        return None
    pad = pygame.joystick.Joystick(0)
    pad.init()
    return pad


class Controller:
    """Turns what the controller reports into car movements, one tick at a time.

    busy: a function that says whether the brain is carrying out a request right
    now; B then also ends that request through end_request (by default it only
    sets STOP; the talking robot also asks Claude to stop, as a spoken "stop"
    does). on_use: called whenever the controller moves the car or the camera."""

    def __init__(self, car, camera, pad, busy=None, on_use=None, end_request=None):
        self.car, self.camera, self.pad = car, camera, pad
        self.busy, self.on_use = busy or (lambda: False), on_use or (lambda: None)
        self.end_request = end_request or STOP.set
        # Some Linux drivers report a trigger as 0 (half pressed) until it is first
        # pulled. A trigger only counts once it has been seen fully released, so the
        # car cannot set off on its own when the program starts.
        self.armed = {AXIS_BACK: False, AXIS_FORWARD: False}
        self.reverse_since = None  # there is no sensor at the back: one pull reverses for a limited time
        self.driving = False       # the controller, not the brain, set the motors going
        self.steered = 0           # the angle the left stick last turned the front wheels to
        self.refused = None

    def _trigger(self, axis: int) -> float:
        v = self.pad.get_axis(axis)
        if v < -0.9:
            self.armed[axis] = True
        return (v + 1) / 2 if self.armed[axis] else 0.0

    def _removed(self) -> bool:
        import pygame
        return any(e.type == pygame.JOYDEVICEREMOVED for e in pygame.event.get())

    def _release(self) -> None:
        """Stop the motors only if the controller started them: an untouched
        controller must not stop a drive the brain is doing."""
        if self.driving:
            self.car.stop()
            self.driving = False

    def _hold(self, direction: str, amount: float, steer: float) -> None:
        self.driving = True
        self.on_use()
        said = self.car.hold(direction, int(amount * config.MAX_SPEED), int(steer * config.TURN_ANGLE_LIMIT))
        # the kind of refusal without its number ("obstacle at 17 cm"), so it is
        # printed once and not ten times a second while the trigger is held
        refused = said.split(" at ")[0] if said != "moving" else None
        if refused and refused != self.refused:
            config.log("controller", said)
        self.refused = refused

    def tick(self) -> bool:
        """Read the controller once and act on it. False when it has disconnected."""
        # a controller that drops out (range, empty battery) keeps its last values
        if self._removed():
            self._release()
            return False
        car, pad = self.car, self.pad
        steer = pad.get_axis(AXIS_STEER)
        fwd, back = self._trigger(AXIS_FORWARD), self._trigger(AXIS_BACK)   # 0..1
        pan, tilt = pad.get_axis(AXIS_PAN), pad.get_axis(AXIS_TILT)
        if back <= DEAD:
            self.reverse_since = None
        # The left stick turns the front wheels whether or not the car is driving,
        # and lets them go back to straight when it is released.
        angle = int(steer * config.TURN_ANGLE_LIMIT) if abs(steer) > DEAD else 0
        if abs(angle - self.steered) >= 2:
            car.steer(angle)
            self.steered = angle
            self.on_use()
        if abs(pan) > DEAD or abs(tilt) > DEAD:
            # no settle wait: that is only for photos, and would pause driving
            car.look(int(pan * config.CAM_PAN_LIMIT), int(-tilt * config.CAM_TILT_LIMIT), settle=False)
            self.on_use()
        if pad.get_button(BUTTON_B):
            if self.busy() and not STOP.is_set():
                self.end_request()  # the same as saying "stop": ends what the brain is doing
            car.stop(); self.driving = False
            if not self.busy():
                car.reset()
            time.sleep(0.05)
        elif pad.get_button(BUTTON_A):
            self._release()
            try:
                self.camera.snapshot(); print("photo saved")
            except Exception as e:  # a camera that is not working must not end the drive
                print(f"no photo: {e}")
            time.sleep(0.3)
        elif fwd > DEAD:
            # hold() keeps the motors running between ticks (no stop-start stutter);
            # the obstacle and cliff checks still run every tick
            self._hold("forward", fwd, steer)
        elif back > DEAD:
            self.reverse_since = self.reverse_since or time.time()
            if time.time() - self.reverse_since > config.REVERSE_MAX_SECONDS:
                self._release(); time.sleep(0.05)    # release the trigger to reverse again
            else:
                self._hold("backward", back, steer)
        else:
            self._release()
            self.refused = None
            time.sleep(0.05)
        return True


def run_in_background(car, camera, busy=None, on_use=None, end_request=None) -> threading.Thread:
    """For the talking robot: drive with the controller whenever one is connected.
    It may be switched on later, or go out of range and come back."""

    def loop():
        try:
            import pygame  # noqa: F401
        except ImportError:
            config.log("controller", "pygame is not installed, so no controller driving")
            return
        while True:
            try:
                pad = open_pad()
                if pad is None:
                    time.sleep(SEARCH_EVERY_S)
                    continue
                config.log("controller", f"{pad.get_name()} connected: RT forward, LT backward, left stick steers, B stops")
                control = Controller(car, camera, pad, busy, on_use, end_request)
                while control.tick():
                    pass
                config.log("controller", "disconnected, motors stopped")
            except Exception as e:  # the controller must never take the talking robot down
                config.log("controller", f"stopped working ({e!r}), trying again")
                try:
                    car.stop()
                except Exception:
                    pass
                time.sleep(SEARCH_EVERY_S)

    thread = threading.Thread(target=loop, daemon=True, name="controller")
    thread.start()
    return thread
