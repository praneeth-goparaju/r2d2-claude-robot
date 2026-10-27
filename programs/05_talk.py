"""Program 5: the full assistant. Same as `python -m robo.main`.

Say "Hey R2-D2, what do you see?" or "Hey R2-D2, drive to the sofa and tell me
what is there." Say "stop" at any time.
"""
from _common import args  # noqa: F401  (sets sys.path)

from robo.main import parse_args, run

run(parse_args())
