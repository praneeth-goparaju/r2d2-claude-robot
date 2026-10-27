"""Safe wrapper around the PiCar-X body, plus a mock for development on the Mac.

Claude never sees Picarx directly. Every method here clamps speed and duration,
polls the ultrasonic sensor while moving forward, and stops on a cliff reading.
"""
import threading
import time

from . import config

# Set by the stop watcher in main.py when someone says "stop" mid-request. Every
# move checks it, and nothing moves again until the next request clears it.
STOP = threading.Event()

# One lock for the servos and motors, so the idle thread, tricks and the brain
# never send the car two moves at once. Re-entrant: a trick calls look().
BODY = threading.RLock()


# The motors are a few centimetres from the microphone. While they run, and for
# a moment after, the ears take what the microphone hears as silence: otherwise
# every drive became a 10 second recording of motor noise, and the robot heard
# nobody until it had worked through it.
MOTOR_NOISE_AFTER_S = 0.4
_motors_on = False
_motors_off_at = 0.0


def motors(on: bool) -> None:
    global _motors_on, _motors_off_at
    if _motors_on and not on:
        _motors_off_at = time.time()
    _motors_on = on


def motor_noise(since: float | None = None) -> bool:
    """Are the motors audible now, or (with since) have they been at any moment from then on?"""
    return _motors_on or (time.time() if since is None else since) - _motors_off_at < MOTOR_NOISE_AFTER_S


# One lock for everything on the I2C bus: the Robot HAT (servos, motors, sensors)
# and the face screen, which hangs on the same two wires.
I2C_BUS = threading.RLock()


def one_i2c_message_at_a_time(i2c_class, adc_class) -> None:
    """The controller thread reads the sensors while the brain or the idle thread
    moves a servo. All of that goes over one I2C bus to the Robot HAT, and reading
    a sensor is two messages (which sensor, then its value): a servo command from
    another thread in between would give a wrong reading or leave the HAT out of
    step. This makes SunFounder's classes take one lock around every exchange."""
    import functools
    if getattr(i2c_class, "_robo_locked", False):
        return
    lock = I2C_BUS

    def locked(fn):
        @functools.wraps(fn)
        def one_at_a_time(*args, **kwargs):
            with lock:
                return fn(*args, **kwargs)
        return one_at_a_time

    for name in ("write", "read", "mem_write", "mem_read"):
        setattr(i2c_class, name, locked(getattr(i2c_class, name)))
    adc_class.read = locked(adc_class.read)
    i2c_class._robo_locked = True


def reset_hat_mcu() -> bool:
    """Reset the Robot HAT's microcontroller (GPIO5). An I2C transfer cut off
    mid-way can leave it out of sync, so servos freeze and readings fail until
    it is reset. Harmless when it is fine. Returns False off the Pi."""
    try:
        from robot_hat import reset_mcu  # also run by: robot_hat reset_mcu
        reset_mcu()
        time.sleep(0.2)
        return True
    except Exception:
        return False


def preflight(car, direction: str, speed, seconds) -> tuple[str | None, int, float]:
    """Checks shared by the real car and the mock. Returns (refusal or None, speed, seconds)."""
    from .assistant import is_night
    if direction not in ("forward", "backward"):
        return f"refused: unknown direction {direction!r}, use forward or backward", 0, 0.0
    if STOP.is_set():
        return "stopped: someone said stop", 0, 0.0
    if is_night():
        return f"night mode: no driving between {config.night_hours()}", 0, 0.0
    v = car.battery_volts()
    if 0 <= v < config.BATTERY_EMPTY_V:
        return f"refused: battery empty ({v:.1f} V), please charge me", 0, 0.0
    speed = max(0, min(config.MAX_SPEED, int(speed)))
    seconds = max(0.0, min(config.MAX_MOVE_SECONDS, float(seconds)))
    if direction == "backward":  # no rear sensor: slower and shorter
        speed = min(speed, config.REVERSE_MAX_SPEED)
        seconds = min(seconds, config.REVERSE_MAX_SECONDS)
    if 0 <= v < config.BATTERY_HUNGRY_V:
        seconds = min(seconds, 1.0)  # hungry: short moves only
    return None, speed, seconds


class Car:
    face = None  # set by main so the eyes follow the camera

    def __init__(self):
        import os
        import pwd
        # Picarx() calls os.getlogin(), which raises under systemd (no login session)
        os.getlogin = lambda: os.environ.get("SUDO_USER") or pwd.getpwuid(os.getuid()).pw_name
        from picarx import Picarx  # SunFounder library, Pi only
        from robot_hat import ADC, I2C
        one_i2c_message_at_a_time(I2C, ADC)
        reset_hat_mcu()
        self.px = Picarx()
        # the library's own steering limit is 30 degrees; ours is TURN_ANGLE_LIMIT
        self.px.DIR_MIN, self.px.DIR_MAX = -config.TURN_ANGLE_LIMIT, config.TURN_ANGLE_LIMIT
        time.sleep(0.5)
        self.px.reset()
        if config.CLIFF_REFERENCE is not None:
            self.px.set_cliff_reference(list(config.CLIFF_REFERENCE))
        self._moving = None  # direction while hold() keeps the motors running

    # Sensors
    def distance_cm(self, quick: bool = False) -> float:
        """Distance ahead. No reading at all (None or an error) counts as 0 cm, so
        forward drives refuse instead of driving blind. The SunFounder library
        returns -1 both for "nothing in range" and for an unplugged sensor, so -1
        stays "far"; the startup self-check warns when every reading is -1. The
        HC-SR04 also misses small or soft things, so the cliff stop and the speed
        and time caps are the real safety net, not this reading alone.

        quick is for the checks while moving: with nothing in range the library
        retries 10 times at 20 ms each, and the cliff sensor is not read meanwhile.
        Three tries keep that wait near 60 ms."""
        try:
            sensor = getattr(self.px, "ultrasonic", None) if quick else None
            d = sensor.read(times=3) if sensor is not None else self.px.get_distance()
        except Exception:
            return 0.0
        if d is None:
            return 0.0
        return float(d) if d >= 0 else 999.0

    def cliff(self) -> bool:
        return bool(self.px.get_cliff_status(self.px.get_grayscale_data()))

    def battery_volts(self) -> float:
        """Two 18650 cells in series, read by the HAT on A4: 8.4 V full, the pack
        cuts out at 6.0 V. See BATTERY_* in config."""
        try:
            from robot_hat import utils
            return float(utils.get_battery_voltage())
        except Exception:
            return -1.0

    # Motion
    def stop(self) -> None:
        self._moving = None
        self.px.stop()
        motors(False)

    def steer(self, angle: int) -> None:
        angle = max(-config.TURN_ANGLE_LIMIT, min(config.TURN_ANGLE_LIMIT, int(angle)))
        with BODY:
            self.px.set_dir_servo_angle(angle)

    def _blocked(self, direction: str) -> str | None:
        if STOP.is_set():
            return "stopped: someone said stop"
        # The cliff sensor is at the front. Backward is not checked against it, so
        # the car can still back away from an edge it has just stopped at.
        if direction == "forward":
            if self.cliff():
                return "stopped: cliff detected"
            d = self.distance_cm(quick=True)
            if d < config.STOP_DISTANCE_CM:
                return f"stopped: obstacle at {d:.0f} cm"
            if self.cliff():  # again: the distance reading above takes a moment
                return "stopped: cliff detected"
        return None

    def drive(self, direction: str, speed: int, seconds: float, steer_angle: int = 0) -> str:
        """Move for a bounded time. Returns a short status string for the brain."""
        refusal, speed, seconds = preflight(self, direction, speed, seconds)
        if refusal:
            return refusal
        with BODY:
            self.steer(steer_angle)
            reason = self._blocked(direction)  # do not even start toward an obstacle
            t0 = time.time()
            if reason is None:
                motors(True)
                (self.px.forward if direction == "forward" else self.px.backward)(speed)
                reason = "completed"
            try:
                while reason == "completed" and time.time() - t0 < seconds:
                    reason = self._blocked(direction) or "completed"
                    if reason == "completed":
                        time.sleep(0.05)
            finally:
                self.stop()
                self.steer(0)
        return f"{direction} {speed}% for {time.time() - t0:.1f}s, {reason}"

    def hold(self, direction: str, speed: int, steer_angle: int = 0, seconds: float = 0.1) -> str:
        """For the controller: keep moving for one short tick without stopping at the
        end, so holding a trigger is smooth. Safety checks run every tick; the caller
        must call stop() when the trigger is released."""
        refusal, speed, _ = preflight(self, direction, speed, seconds)
        if refusal:
            self.stop()
            return refusal
        with BODY:
            self.steer(steer_angle)
            reason = self._blocked(direction)
            if reason:
                self.stop()
                return reason
            if self._moving != (direction, speed):
                motors(True)
                (self.px.forward if direction == "forward" else self.px.backward)(speed)
                self._moving = (direction, speed)
        t0 = time.time()
        while time.time() - t0 < seconds:
            reason = self._blocked(direction)
            if reason:
                self.stop()
                return reason
            time.sleep(0.03)
        return "moving"

    # Camera gimbal
    def look(self, pan: int, tilt: int, settle: bool = True) -> None:
        """settle waits for the servos before a photo; tricks and the controller skip it."""
        pan = max(-config.CAM_PAN_LIMIT, min(config.CAM_PAN_LIMIT, int(pan)))
        tilt = max(-config.CAM_TILT_LIMIT, min(config.CAM_TILT_LIMIT, int(tilt)))
        with BODY:
            self.px.set_cam_pan_angle(pan)
            self.px.set_cam_tilt_angle(tilt)
        if self.face is not None:
            self.face.look_at(pan)
        if settle:
            time.sleep(0.4)

    def reset(self) -> None:
        self._moving = None
        with BODY:
            self.px.reset()

    # Tricks: camera and steering only, so they are allowed at night too
    def trick(self, name: str) -> str:
        with BODY:
            return _do_trick(self, name)

    def dance(self, seconds: float = 8.0) -> str:
        with BODY:
            return _do_dance(self, seconds)

    def gesture(self, feeling: str) -> None:
        """A short movement of the camera head to go with a face, while the robot
        talks. It runs on its own thread so the sentence is not held up, and is
        skipped when the body is busy with something else."""
        moves = GESTURES.get(feeling)
        if not moves:
            return

        def run():
            if not BODY.acquire(blocking=False):
                return
            try:
                for pan, tilt, wait in moves:
                    self.look(pan, tilt, settle=False); time.sleep(wait)
                self.look(0, 0, settle=False)
            except Exception as e:
                print(f"[gesture] {e}")
            finally:
                BODY.release()

        threading.Thread(target=run, daemon=True, name="gesture").start()


class MockCar:
    """Prints what the real car would do. Distance shrinks as it drives forward."""
    face = None

    def __init__(self):
        self._distance = 120.0
        self._volts = 7.9
        print("[mock car] ready")

    def battery_volts(self) -> float:
        return self._volts

    def distance_cm(self) -> float:
        return self._distance

    def cliff(self) -> bool:
        return False

    def stop(self) -> None:
        print("[mock car] stop")

    def steer(self, angle: int) -> None:
        print(f"[mock car] steer {angle}")

    def drive(self, direction, speed, seconds, steer_angle=0) -> str:
        refusal, speed, seconds = preflight(self, direction, speed, seconds)
        if refusal:
            return refusal
        print(f"[mock car] {direction} speed={speed} steer={steer_angle} for {seconds}s")
        if direction == "forward":
            self._distance = max(10.0, self._distance - 30 * seconds)
            if self._distance < config.STOP_DISTANCE_CM:
                return f"forward {speed}% stopped: obstacle at {self._distance:.0f} cm"
        else:
            self._distance += 30 * seconds
        return f"{direction} {speed}% for {seconds:.1f}s, completed"

    def hold(self, direction, speed, steer_angle=0, seconds=0.1) -> str:
        refusal, speed, _ = preflight(self, direction, speed, seconds)
        if refusal:
            return refusal
        print(f"[mock car] holding {direction} speed={speed} steer={steer_angle}")
        return "moving"

    def look(self, pan, tilt, settle=True) -> None:
        print(f"[mock car] camera pan={pan} tilt={tilt}")
        if self.face is not None:
            self.face.look_at(pan)

    def reset(self) -> None:
        print("[mock car] reset")

    def trick(self, name: str) -> str:
        return _do_trick(self, name, fast=True)

    def gesture(self, feeling: str) -> None:
        if feeling in GESTURES:
            print(f"[mock car] gesture for {feeling}")

    def dance(self, seconds: float = 8.0) -> str:
        _do_dance(self, min(seconds, 1.0), fast=True)
        return f"danced for {seconds:g} seconds and bowed"


# The movement of the camera head that goes with each face while the robot
# talks: (pan, tilt, seconds to wait) steps, at most about a second in all, and
# the head goes back to the middle afterwards. Head only: nothing drives.
_P, _T = config.CAM_PAN_LIMIT, config.CAM_TILT_LIMIT
GESTURES = {
    "happy":      [(0, 12, 0.18), (0, -4, 0.18), (0, 10, 0.18)],                      # a little nod
    "sad":        [(0, -_T // 2, 0.9)],                                                # the head sinks
    "surprised":  [(0, _T * 2 // 3, 0.6)],                                             # the head goes up
    "love":       [(-10, 8, 0.3), (10, 8, 0.3), (0, 12, 0.3)],                         # a sway
    "sleepy":     [(0, -8, 0.4), (0, -_T * 2 // 3, 0.6)],                              # nodding off
    "thinking":   [(_P // 2, _T // 2, 0.9)],                                           # looks up and aside
    "wink":       [(12, 6, 0.25), (0, 0, 0.1)],
    "hungry":     [(0, -_T // 2, 0.7)],
    "angry":      [(-15, 0, 0.12), (15, 0, 0.12), (-15, 0, 0.12), (15, 0, 0.12)],     # a sharp shake
    "laughing":   [(0, 12, 0.1), (0, -6, 0.1), (0, 12, 0.1), (0, -6, 0.1), (0, 12, 0.1)],   # shaking with laughter
    "silly":      [(_P // 2, _T // 3, 0.2), (-_P // 2, -_T // 3, 0.2), (_P // 3, -_T // 3, 0.2)],
    "cool":       [(-_P // 2, 4, 0.5), (_P // 2, 4, 0.5)],                             # a slow look across
    "dizzy":      [(_P // 2, 0, 0.14), (0, _T // 2, 0.14), (-_P // 2, 0, 0.14), (0, -_T // 2, 0.14), (_P // 2, 0, 0.14)],
    "crying":     [(0, -_T * 2 // 3, 0.4), (0, -_T // 2, 0.2), (0, -_T * 2 // 3, 0.3)],  # a sob
    "starstruck": [(0, _T * 2 // 3, 0.35), (-8, _T * 2 // 3, 0.2), (8, _T * 2 // 3, 0.2)],
    "shy":        [(-_P * 2 // 3, -_T // 2, 0.9)],                                     # looks down and away
    "kiss":       [(0, -8, 0.3), (0, 10, 0.4)],                                        # leans in
    "confused":   [(_P // 3, _T // 2, 0.4), (-_P // 3, _T // 2, 0.5)],                 # tilts one way, then the other
    "scared":     [(0, _T * 2 // 3, 0.15), (4, _T // 2, 0.06), (-4, _T // 2, 0.06), (4, _T // 2, 0.06), (-4, _T // 2, 0.06), (0, -_T // 3, 0.3)],
    "robot":      [(-_P // 2, 0, 0.3), (0, 0, 0.15), (_P // 2, 0, 0.3)],               # stiff, in steps
    "singing":    [(-12, 6, 0.3), (12, 6, 0.3), (-12, 6, 0.3)],
}


TRICKS = ["nod", "shake", "wiggle", "peekaboo", "bow", "twirl", "look_around",
          # little acts with a face and a sound to go with the movement
          "sneeze", "dizzy", "shy", "curious", "celebrate", "fall_asleep", "wake_up",
          "double_take", "laugh", "scan", "scared", "cool", "kiss", "cry", "silly"]


def _do_trick(car, name: str, fast: bool = False) -> str:
    """Little physical gestures. Shared by the real car and the mock."""
    z = 0.02 if fast else 1.0  # time scale, so tests run quickly
    face = getattr(car, "face", None)
    if name == "nod":            # yes
        for _ in range(2):
            car.look(0, 20, settle=False); time.sleep(0.25 * z); car.look(0, -10, settle=False); time.sleep(0.25 * z)
        car.look(0, 0, settle=False)
    elif name == "shake":        # no
        for _ in range(2):
            car.look(-35, 0, settle=False); time.sleep(0.25 * z); car.look(35, 0, settle=False); time.sleep(0.25 * z)
        car.look(0, 0, settle=False)
    elif name == "wiggle":       # wheels left-right in place
        for _ in range(4):
            car.steer(-25); time.sleep(0.15 * z); car.steer(25); time.sleep(0.15 * z)
        car.steer(0)
    elif name == "peekaboo":
        car.look(0, -30, settle=False)
        if face: face.show("sleepy", hold=None)
        time.sleep(1.2 * z)
        car.look(0, 15, settle=False)
        if face: face.show("surprised")
    elif name == "bow":
        car.look(0, -30, settle=False); time.sleep(1.0 * z); car.look(0, 0, settle=False)
    elif name == "twirl":        # a curve out and back; obeys the night rule
        out = car.drive("forward", 30, 1.5, 30); back = car.drive("backward", 30, 1.5, 30)
        return f"twirl: {out}; {back}"
    elif name == "look_around":
        for pan in (-config.CAM_PAN_LIMIT, config.CAM_PAN_LIMIT, 0):
            car.look(pan, 5, settle=False); time.sleep(0.4 * z)
    elif name in _ACTS:
        from . import sounds

        def show(feeling, hold=4.0):
            if face: face.show(feeling, hold=hold)

        def sound(which):
            if not fast:  # the mock and the tests stay silent
                try:
                    sounds.play(which)
                except Exception as e:
                    print(f"[sounds] {e}")

        def move(pan, tilt, wait=0.25):
            car.look(pan, tilt, settle=False); time.sleep(wait * z)

        _ACTS[name](car, show, sound, move, z)
        car.look(0, 0, settle=False); car.steer(0)
    else:
        return f"unknown trick {name}; choose from {', '.join(TRICKS)}"
    return f"did {name}"


# The acts: each gets the car, show(feeling), sound(name), move(pan, tilt, wait)
# and the time scale z. Camera head and steering only, so they are allowed at
# night too. Head and wheels are put straight again afterwards.
PAN, TILT = config.CAM_PAN_LIMIT, config.CAM_TILT_LIMIT


def _sneeze(car, show, sound, move, z):
    show("surprised")
    for tilt in (8, 16, 24):          # ah... ah... ah...
        move(0, tilt, 0.3)
    show("silly"); sound("oops")
    move(0, -TILT, 0.15)              # ...choo
    move(0, 0, 0.4)


def _dizzy(car, show, sound, move, z):
    show("dizzy", hold=6.0); sound("whistle_down")
    for _ in range(2):                # the head goes round in circles
        for pan, tilt in ((PAN, 0), (PAN * 2 // 3, TILT * 2 // 3), (0, TILT), (-PAN * 2 // 3, TILT * 2 // 3),
                          (-PAN, 0), (-PAN * 2 // 3, -TILT * 2 // 3), (0, -TILT), (PAN * 2 // 3, -TILT * 2 // 3)):
            move(pan, tilt, 0.12)
    for angle in (20, -20, 10, -10):  # and the wheels wobble
        car.steer(angle); time.sleep(0.12 * z)


def _shy(car, show, sound, move, z):
    show("shy", hold=5.0)
    move(-PAN, -TILT * 2 // 3, 1.2)   # looks down and away
    move(-PAN // 2, -TILT // 3, 0.5)  # peeks back
    move(-PAN, -TILT * 2 // 3, 0.8)


def _curious(car, show, sound, move, z):
    show("confused", hold=5.0); sound("whistle_up")
    move(PAN // 2, TILT * 2 // 3, 0.7); move(-PAN // 2, TILT * 2 // 3, 0.7); move(0, TILT // 2, 0.5)


def _celebrate(car, show, sound, move, z):
    show("starstruck", hold=6.0); sound("tada")
    for _ in range(3):
        car.steer(25); move(PAN // 2, TILT // 2, 0.15)
        car.steer(-25); move(-PAN // 2, -TILT // 4, 0.15)
    sound("chirp")


def _fall_asleep(car, show, sound, move, z):
    show("sleepy", hold=None); sound("whistle_down")
    for tilt in (-5, -12, -20, -TILT):   # the head sinks, with one start awake on the way
        move(0, tilt, 0.6)
        if tilt == -12:
            move(0, 0, 0.25)


def _wake_up(car, show, sound, move, z):
    show("sleepy", hold=None); move(0, -TILT, 0.5)
    show("surprised"); sound("chirp")
    move(0, TILT // 2, 0.3); move(-PAN // 2, 0, 0.3); move(PAN // 2, 0, 0.3)
    show("happy")


def _double_take(car, show, sound, move, z):
    move(PAN, 0, 0.7)                 # looks away...
    move(PAN // 2, 0, 0.25)           # ...starts to turn back, stops...
    show("surprised"); sound("beep")
    move(-PAN // 3, 5, 0.12); move(0, 5, 0.8)   # ...and snaps round


def _laugh(car, show, sound, move, z):
    show("laughing", hold=5.0); sound("laugh")
    for _ in range(4):                # shaking with laughter
        move(0, 12, 0.1); move(0, -6, 0.1)
    sound("laugh")


def _scan(car, show, sound, move, z):
    show("robot", hold=6.0)
    for pan in range(-PAN, PAN + 1, PAN // 3 or 1):   # a slow sweep with a beep at each stop
        move(pan, 0, 0.2); sound("beep")
    sound("boop")


def _scared(car, show, sound, move, z):
    show("scared", hold=5.0); sound("alarm")
    move(0, TILT, 0.2)                # the head jerks back
    for _ in range(6):                # and trembles
        move(4, TILT - 3, 0.05); move(-4, TILT - 3, 0.05)
    move(0, -TILT // 2, 0.5)          # then it ducks


def _cool(car, show, sound, move, z):
    show("cool", hold=6.0)
    move(-PAN // 2, 5, 0.6); move(PAN // 2, 5, 0.9)   # a slow look across the room
    move(PAN // 2, 12, 0.2); move(PAN // 2, 2, 0.3)   # and one small nod
    sound("boop")


def _kiss(car, show, sound, move, z):
    show("kiss", hold=5.0)
    move(0, -8, 0.3); sound("chirp"); move(0, 10, 0.5)   # leans in, then throws it


def _cry(car, show, sound, move, z):
    show("crying", hold=6.0); sound("whistle_down")
    move(0, -TILT * 2 // 3, 0.6)
    for _ in range(3):                # sobbing
        move(0, -TILT // 2, 0.18); move(0, -TILT * 2 // 3, 0.25)
    sound("oops")


def _silly(car, show, sound, move, z):
    show("silly", hold=5.0); sound("chatter")
    for pan, tilt in ((PAN, TILT // 2), (-PAN, -TILT // 2), (PAN // 2, -TILT // 2), (-PAN // 2, TILT // 2)):
        car.steer(20 if pan > 0 else -20); move(pan, tilt, 0.2)


_ACTS = {"sneeze": _sneeze, "dizzy": _dizzy, "shy": _shy, "curious": _curious, "celebrate": _celebrate,
         "fall_asleep": _fall_asleep, "wake_up": _wake_up, "double_take": _double_take, "laugh": _laugh,
         "scan": _scan, "scared": _scared, "cool": _cool, "kiss": _kiss, "cry": _cry, "silly": _silly}


def _do_dance(car, seconds: float, fast: bool = False) -> str:
    from . import sounds
    z = 0.02 if fast else 1.0
    face = getattr(car, "face", None)
    proc = sounds.play_background("dance")
    if face: face.show("happy", hold=None)
    t0, beat, i = time.time(), 0.3, 0
    while time.time() - t0 < seconds * z and not STOP.is_set():
        car.steer(25 if i % 2 else -25)
        car.look(30 if i % 4 < 2 else -30, 15 if i % 2 else -5, settle=False)
        time.sleep(beat * z); i += 1
    car.steer(0); car.look(0, 0, settle=False)
    if proc: proc.terminate()
    car.trick("bow")
    if face: face.show("love")
    return f"danced for {seconds:g} seconds and bowed"


def make_car(mock: bool):
    return MockCar() if mock else Car()


def exit_on_signals() -> None:
    """Make `systemctl stop` (SIGTERM) and a dropped SSH session (SIGHUP) end the
    program through its `finally` block, which stops the motors. By default Python
    dies on these at once, and the HAT keeps the motors at their last speed."""
    import signal
    import sys
    for sig in (signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, lambda *_: sys.exit(0))
