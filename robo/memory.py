"""Things the robot keeps between restarts: its name, and a diary of the day."""
import json
import os
import time
from datetime import date
from pathlib import Path

from . import config

STATE = config.ROOT / "state.json"
DIARY = config.ROOT / "diary"


def own(path: Path) -> None:
    """The systemd service runs as root (the HAT speaker needs it). Hand every file it
    writes back to the owner of the repo, so later runs as the normal user still work."""
    if not hasattr(os, "geteuid") or os.geteuid() != 0:
        return
    try:
        st = config.ROOT.stat()
        os.chown(path, st.st_uid, st.st_gid)
    except OSError:
        pass


def make_dir(path: Path) -> Path:
    path.mkdir(exist_ok=True)
    own(path)
    return path


def prune(folder: Path, pattern: str, keep: int) -> int:
    """Delete all but the newest `keep` files matching pattern. Returns how many went."""
    if not folder.exists():
        return 0
    files = sorted(folder.glob(pattern), key=lambda p: (p.stat().st_mtime, p.name))
    gone = files[:-keep] if keep > 0 else files
    for p in gone:
        p.unlink(missing_ok=True)
    return len(gone)


def load_state() -> dict:
    try:
        return json.loads(STATE.read_text())
    except Exception:
        return {}


def save_state(**changes) -> dict:
    s = load_state(); s.update(changes)
    part = STATE.with_suffix(".part")  # renamed when complete: a power cut cannot leave half a file
    part.write_text(json.dumps(s, indent=2))
    part.replace(STATE)
    own(STATE)
    return s


_BUILT_IN = (config.NAME, list(config.WAKE_WORDS), config.WAKE_SOUNDS_LIKE)


def apply_name(name: str) -> None:
    """Rename the robot for this process: wake words follow the name. "hey robot"
    always stays, so a name the speech recognizer cannot spell (digits, made-up
    words) never leaves the robot impossible to wake."""
    name = name.strip()[:20]
    if not name:
        raise ValueError("a name needs at least one letter")
    if name.lower() == _BUILT_IN[0].lower():  # back to the name in config.py
        config.NAME, config.WAKE_WORDS, config.WAKE_SOUNDS_LIKE = _BUILT_IN[0], list(_BUILT_IN[1]), _BUILT_IN[2]
        return
    config.NAME = name.title()
    config.WAKE_WORDS = [f"hey {name.lower()}", name.lower(), "hey robot"]
    config.WAKE_SOUNDS_LIKE = None


def restore_name() -> None:
    n = load_state().get("name")
    if isinstance(n, str) and n.strip():
        apply_name(n)


def diary_add(request: str, reply: str) -> None:
    from .face import without_faces
    reply = without_faces(reply)  # the [face:...] tags are stage directions, not what was said
    make_dir(DIARY)
    path = DIARY / f"{date.today().isoformat()}.jsonl"
    new = not path.exists()
    with open(path, "a") as f:
        f.write(json.dumps({"t": time.strftime("%H:%M"), "heard": request, "said": reply}) + "\n")
    if new:
        own(path)
        prune(DIARY, "*.jsonl", config.KEEP_DIARY_DAYS)


def diary_today(limit: int = 40) -> str:
    p = DIARY / f"{date.today().isoformat()}.jsonl"
    if not p.exists():
        return "nothing in the diary yet today"
    rows = []
    for line in p.read_text().splitlines():
        try:
            rows.append(json.loads(line))
        except ValueError:
            pass  # a line cut off by a power cut
    rows = [r for r in rows if isinstance(r, dict) and {"t", "heard", "said"} <= r.keys()][-limit:]
    return "\n".join(f"{r['t']} heard: {r['heard']} | said: {r['said'][:160]}" for r in rows)


def birthday_today() -> str | None:
    """Name of whoever has a birthday today, from family.yaml, else None."""
    try:
        import yaml
        fam = yaml.safe_load(config.FAMILY_FILE.read_text()) or {}
        today = date.today().strftime("%m-%d")
        return next((n for n, d in (fam.get("birthdays") or {}).items() if d == today), None)
    except Exception:
        return None


def celebrated_today(who: str) -> bool:
    return load_state().get("celebrated") == f"{date.today().isoformat()}:{who}"


def mark_celebrated(who: str) -> None:
    save_state(celebrated=f"{date.today().isoformat()}:{who}")
