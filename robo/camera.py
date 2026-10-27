"""Camera access. One job: hand back a JPEG the brain can send to Claude."""
import time
from pathlib import Path

from . import config, memory

MAX_SIDE = 640      # photos sent to Claude are shrunk to this longest side
JPEG_QUALITY = 75   # keeps a frame around 50 to 100 KB; the SDK limit is 1 MB


def shrink(jpeg: bytes) -> bytes:
    """Downscale and recompress a JPEG so it is cheap to send and under the SDK limit."""
    try:
        from io import BytesIO

        from PIL import Image
        img = Image.open(BytesIO(jpeg))
        img.thumbnail((MAX_SIDE, MAX_SIDE))
        out = BytesIO()
        img.convert("RGB").save(out, format="JPEG", quality=JPEG_QUALITY)
        return out.getvalue()
    except Exception:
        return jpeg  # no Pillow: send as is


START_TIMEOUT_S = 10  # vilib waits forever if the camera never starts; we do not


WEB_VIEW_PORT = 9000  # vilib's own choice


def also_over_ipv6(port: int) -> None:
    """vilib's live view listens on IPv4 only. A browser that reaches the Pi by its
    name (r2d2.local) may get the IPv6 address, and on this home network that was
    the only one that worked from the Mac: the page did not load. This listens on
    the same port for IPv6 and passes every connection on to vilib's server."""
    import socket
    import threading

    def pipe(a, b):
        try:
            while data := a.recv(65536):
                b.sendall(data)
        except OSError:
            pass
        finally:
            a.close(); b.close()

    def serve():
        try:
            server = socket.socket(socket.AF_INET6)
            server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)  # IPv4 stays with vilib
            server.bind(("::", port))
            server.listen(5)
        except OSError as e:
            print(f"[camera] live view over IPv6 not available ({e})")
            return
        while True:
            try:
                viewer, _ = server.accept()
                source = socket.create_connection(("127.0.0.1", port), timeout=5)
                source.settimeout(None)
            except OSError:
                continue
            threading.Thread(target=pipe, args=(viewer, source), daemon=True).start()
            threading.Thread(target=pipe, args=(source, viewer), daemon=True).start()

    threading.Thread(target=serve, daemon=True, name="live-view-ipv6").start()


class Camera:
    def __init__(self):
        import os
        import threading
        # vilib's welcome banner imports pkg_resources, which newer setuptools dropped
        os.environ.setdefault("VILIB_WELCOME", "False")
        from vilib import Vilib  # SunFounder library, Pi only
        self.Vilib = Vilib
        # camera_start() loops until the camera thread reports it is running. When
        # that thread fails it only exits itself, so start it with a time limit.
        starter = threading.Thread(target=Vilib.camera_start, kwargs={"vflip": False, "hflip": False}, daemon=True)
        starter.start()
        starter.join(START_TIMEOUT_S)
        if starter.is_alive():
            raise RuntimeError(f"camera did not start within {START_TIMEOUT_S} seconds")
        if config.CAMERA_WEB_VIEW:  # live view at http://<pi>:9000/mjpg, no password
            Vilib.display(local=False, web=True)
            also_over_ipv6(WEB_VIEW_PORT)
        time.sleep(1.5)  # first frames take a moment

    def snapshot(self) -> bytes:
        import cv2
        frame = self.Vilib.img
        # before the first frame vilib holds a placeholder list here, not None
        if not hasattr(frame, "shape"):
            raise RuntimeError("camera returned no frame")
        thread = getattr(self.Vilib, "camera_thread", None)
        if thread is not None and not thread.is_alive():
            raise RuntimeError("camera stopped working")  # Vilib.img would be the last, stale frame
        h, w = frame.shape[:2]
        if max(h, w) > MAX_SIDE:
            scale = MAX_SIDE / max(h, w)
            frame = cv2.resize(frame, (int(w * scale), int(h * scale)))
        ok, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), JPEG_QUALITY])
        if not ok:
            raise RuntimeError("could not encode frame")
        data = buf.tobytes()
        self._save(data)
        return data

    def close(self) -> None:
        self.Vilib.camera_close()

    @staticmethod
    def _save(data: bytes) -> None:
        """Keep the newest KEEP_SNAPSHOTS photos for debugging; older ones are deleted."""
        memory.make_dir(config.SNAPSHOT_DIR)
        path = config.SNAPSHOT_DIR / f"{time.strftime('%Y%m%d-%H%M%S')}.jpg"
        path.write_bytes(data)
        memory.own(path)
        memory.prune(config.SNAPSHOT_DIR, "*.jpg", config.KEEP_SNAPSHOTS)


class MockCamera:
    """Returns a fixed test image so the brain can be exercised on the Mac.

    Put any JPEG at tests/mock_view.jpg to control what Claude 'sees'.
    """

    def __init__(self):
        self.path = Path(config.ROOT / "tests" / "mock_view.jpg")
        print(f"[mock camera] using {self.path}")

    def snapshot(self) -> bytes:
        if self.path.exists():
            return shrink(self.path.read_bytes())
        return _tiny_jpeg()

    def close(self) -> None:
        pass


def _tiny_jpeg() -> bytes:
    """A valid 1x1 grey JPEG so the API call shape can be tested without a file."""
    import base64
    return base64.b64decode(
        "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8UHRofHh0a"
        "HBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/wAALCAABAAEBAREA/8QAFAABAAAAAAAA"
        "AAAAAAAAAAAACf/EABQQAQAAAAAAAAAAAAAAAAAAAAD/2gAIAQEAAD8AKp//2Q=="
    )


class NoCamera:
    """Stands in when the real camera fails to start (loose ribbon cable, vilib
    not installed), so the robot still drives and talks. Every snapshot raises,
    which the self-check and the look tool report as a camera problem."""

    def __init__(self, reason: str):
        self.reason = reason

    def snapshot(self) -> bytes:
        raise RuntimeError(f"camera not working ({self.reason})")

    def close(self) -> None:
        pass


def make_camera(mock: bool):
    if mock:
        return MockCamera()
    try:
        return Camera()
    except Exception as e:
        print(f"[camera] not working ({e}), carrying on without it")
        return NoCamera(str(e))
