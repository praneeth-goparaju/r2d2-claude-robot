"""Shared argument parsing so every program takes the same flags."""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # make `robo` importable


def args(listen: bool = False, extra: dict | None = None):
    """extra: flags only one program has, as {"--flag": "help text"}."""
    from robo.car import exit_on_signals
    exit_on_signals()  # every program stops the motors in a finally block
    p = argparse.ArgumentParser()
    p.add_argument("--mock", action="store_true", help="fake car and camera (Mac)")
    p.add_argument("--mock-brain", action="store_true", help="no Claude call")
    if listen:
        p.add_argument("--keyboard", action="store_true", help="type instead of speaking")
    for flag, text in (extra or {}).items():
        p.add_argument(flag, action="store_true", help=text)
    a = p.parse_args()
    if not listen:
        a.keyboard = True
    return a
