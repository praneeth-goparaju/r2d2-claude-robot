#!/usr/bin/env python3
"""Ask how this robot should be set up and write the answers down.

setup_pi.sh runs this first; run it again any time to change an answer:
    python3 setup_questions.py
It writes ~/.robo.env (keys, language, microphone, town) and robo/family.yaml
(your household). Both stay on the Pi and never go into git. Pressing Enter
keeps the value in brackets. Only the Python that comes with the Pi is used,
because this runs before anything else is installed.
"""
import getpass
import json
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent
ENV_FILE = Path.home() / ".robo.env"
FAMILY_FILE = REPO / "robo" / "family.yaml"
EXAMPLE_FILE = REPO / "robo" / "family.example.yaml"


def ask(question: str, default: str = "") -> str:
    shown = f" [{default}]" if default else ""
    answer = input(f"{question}{shown}: ").strip()
    return answer or default


def ask_yes(question: str, default: bool) -> bool:
    answer = ask(question + (" (Y/n)" if default else " (y/N)")).lower()
    return default if not answer else answer.startswith(("y", "j"))


def ask_secret(question: str, have: bool) -> str | None:
    """A key, typed without showing it. None keeps the one already there."""
    note = "Enter keeps the one you have" if have else "Enter to skip"
    answer = getpass.getpass(f"{question} ({note}, typing is hidden): ").strip()
    return answer or None


def read_env() -> dict[str, str]:
    """The values already in ~/.robo.env, ignoring comments and the setup script's examples."""
    values = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                if value.strip() and "paste" not in value.lower():
                    values[key.strip()] = value.strip()
    return values


def update_env(text: str, changes: dict[str, str | None]) -> str:
    """Set each key in the text of an env file. A key that is set already, or
    waits commented out ("# KEY=..."), is replaced where it is; a new one goes
    at the end. None removes the key. Every other line is kept as it was."""
    lines = text.splitlines()
    for key, value in changes.items():
        line_re = re.compile(rf"^\s*#?\s*{re.escape(key)}=")
        at = next((i for i, line in enumerate(lines) if line_re.match(line)), None)
        new = None if value is None else f"{key}={value}"
        if at is None:
            if new:
                lines.append(new)
        elif new:
            lines[at] = new
        else:
            del lines[at]
    return "\n".join(lines) + "\n"


def find_town(name: str) -> tuple[str, float, float] | None:
    """The town's name and coordinates from Open-Meteo's free place search, or None."""
    url = "https://geocoding-api.open-meteo.com/v1/search?count=1&name=" + urllib.parse.quote(name)
    try:
        with urllib.request.urlopen(url, timeout=10) as reply:
            found = (json.load(reply).get("results") or [None])[0]
    except (OSError, ValueError):
        return None
    if not found:
        return None
    where = ", ".join(p for p in (found["name"], found.get("admin1"), found.get("country")) if p)
    return where, round(found["latitude"], 2), round(found["longitude"], 2)


def family_yaml(people: list[dict], birthdays: dict[str, str], languages: list[str]) -> str:
    """robo/family.yaml for these people, with the rules and games of the example
    file. Strings are written in JSON quoting, which YAML reads as it is."""
    out = ["# Your household. Written by setup_questions.py; edit it freely.",
           "# Keep it to things the robot may say out loud to anyone in the house.",
           'home: "a family home"',
           f"languages: {json.dumps(languages)}",
           "people:"]
    for p in people:
        out.append(f"  - name: {json.dumps(p['name'])}")
        out.append(f"    role: {json.dumps(p['role'])}")
        if p.get("notes"):
            out.append(f"    notes: {json.dumps(p['notes'])}")
    out.append("birthdays:   # month-day; the robot sings and celebrates on the day")
    out += [f"  {json.dumps(name)}: {json.dumps(day)}" for name, day in birthdays.items()]
    example = EXAMPLE_FILE.read_text()
    out.append(example[example.index("\nrules:") + 1:].rstrip())
    return "\n".join(out) + "\n"


def ask_family(languages: list[str]) -> None:
    if FAMILY_FILE.exists() and ask_yes(f"\nKeep your household in {FAMILY_FILE.name}?", True):
        return
    print("\nWho lives with the robot? Claude uses this to know who it talks to.\n"
          "Only write what the robot may say out loud. An empty name ends the list.\n"
          "Skip it entirely and the robot uses the example family in family.example.yaml.")
    people, birthdays = [], {}
    while name := ask(f"Person {len(people) + 1}, name"):
        role = ask("  Who they are, e.g. dad, mum, daughter 8 years old", "family member")
        notes = ask("  Anything the robot should know, e.g. loves dinosaurs (Enter to skip)")
        day = ask("  Birthday as month-day, e.g. 05-30 (Enter to skip)")
        if day and not re.fullmatch(r"(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])", day):
            print("  Not month-day (like 05-30), so no birthday for now.")
            day = ""
        people.append({"name": name, "role": role, "notes": notes})
        if day:
            birthdays[name] = day
    if people:
        FAMILY_FILE.write_text(family_yaml(people, birthdays, languages))
        print(f"Wrote {FAMILY_FILE}")


def main() -> None:
    if not sys.stdin.isatty():
        print("setup_questions.py needs someone at the keyboard; skipped.")
        return
    env = read_env()
    changes: dict[str, str | None] = {}
    print("A few questions to set up the robot. Enter keeps the value in brackets.\n")

    print("1. Claude, the brain. An Anthropic API key (console.anthropic.com) is the\n"
          "   quickest. Without one the robot uses the Claude Code login instead:\n"
          "   run  claude  once on the Pi and log in.")
    if key := ask_secret("   Anthropic API key", "ANTHROPIC_API_KEY" in env):
        changes["ANTHROPIC_API_KEY"] = key

    print("\n2. Voice and ears. With a Google Cloud key the robot speaks with Google's\n"
          "   voice and Google writes down what it hears: quicker and better with\n"
          "   children (README, \"Google voice and ears\", a few dollars a month).\n"
          "   Without it, a free voice and a recognizer on the Pi itself.")
    if key := ask_secret("   Google Cloud API key", "GOOGLE_API_KEY" in env):
        changes["GOOGLE_API_KEY"] = key

    language = ask("\n3. Language the robot speaks and listens in, en or de",
                   env.get("ROBO_LANGUAGE", "en")).lower()
    language = language if language in ("en", "de") else "en"
    changes["ROBO_LANGUAGE"] = language

    print("\n4. The microphone. The version is printed on the Robot HAT. V5 has a\n"
          "   microphone on board; V4 has none, so plug in a USB microphone.")
    hat = ask("   Robot HAT version, 4 or 5", "5" if env.get("ROBO_MIC_NAME") == "default" else "4")
    changes["ROBO_MIC_NAME"] = "default" if hat.strip().lstrip("vV") == "5" else "USB"

    print("\n5. Where you live, for the weather and pollen.")
    town = ask("   Town or city", env.get("ROBO_PLACE", ""))
    if town and town != env.get("ROBO_PLACE"):
        found = find_town(town)
        if found and ask_yes(f"   Found {found[0]} ({found[1]}, {found[2]}). Right?", True):
            changes.update(ROBO_PLACE=town, ROBO_LAT=str(found[1]), ROBO_LON=str(found[2]))
        else:
            print("   Not found or not right. Type the coordinates (a map app shows them).")
            lat, lon = ask("   Latitude, e.g. 52.52"), ask("   Longitude, e.g. 13.41")
            try:
                changes.update(ROBO_PLACE=town, ROBO_LAT=str(float(lat)), ROBO_LON=str(float(lon)))
            except ValueError:
                print("   Those are not numbers; the weather stays on Berlin for now.")

    old = ENV_FILE.read_text() if ENV_FILE.exists() else ""
    ENV_FILE.write_text(update_env(old, changes))
    ENV_FILE.chmod(0o600)
    print(f"\nWrote {ENV_FILE}")

    ask_family(["English", "German"] if language == "en" else ["German", "English"])
    print("\nDone. Run this again any time to change an answer, then restart the robot.")


if __name__ == "__main__":
    try:
        main()
    except (KeyboardInterrupt, EOFError):
        print("\nStopped; nothing more was written.")
