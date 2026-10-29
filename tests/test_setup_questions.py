"""Tests for setup_questions.py, the questions setup_pi.sh asks first: python -m unittest -v"""
import importlib
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

from robo import config

sys.path.insert(0, str(config.ROOT))
import setup_questions as sq


class EnvFile(unittest.TestCase):
    def test_commented_example_is_replaced_where_it_is(self):
        old = "# ANTHROPIC_API_KEY=paste-the-key-from-your-Console-org-here\n# GOOGLE_API_KEY=paste-your-google-key-here\n"
        new = sq.update_env(old, {"ANTHROPIC_API_KEY": "sk-1"})
        self.assertEqual(new.splitlines(), ["ANTHROPIC_API_KEY=sk-1", "# GOOGLE_API_KEY=paste-your-google-key-here"])

    def test_set_value_is_replaced_and_new_one_appended_other_lines_kept(self):
        old = "ROBO_PLACE=Berlin\nROBO_CAMERA_WEB_VIEW=1\n"
        new = sq.update_env(old, {"ROBO_PLACE": "Hamburg", "ROBO_LANGUAGE": "de"})
        self.assertEqual(new.splitlines(), ["ROBO_PLACE=Hamburg", "ROBO_CAMERA_WEB_VIEW=1", "ROBO_LANGUAGE=de"])

    def test_similar_key_names_are_not_confused(self):
        new = sq.update_env("ROBO_LAT=1\nROBO_LATE_NIGHT=2026-10-11 22\n", {"ROBO_LAT": "2"})
        self.assertIn("ROBO_LATE_NIGHT=2026-10-11 22", new)
        self.assertIn("ROBO_LAT=2", new)


class FamilyFile(unittest.TestCase):
    def test_written_file_reads_back_with_example_rules_and_games(self):
        people = [{"name": 'Zoë "Z"', "role": "daughter, 8 years old", "notes": "likes: space"},
                  {"name": "Ben", "role": "dad", "notes": ""}]
        text = sq.family_yaml(people, {'Zoë "Z"': "05-30"}, ["English", "German"])
        fam = yaml.safe_load(text)
        self.assertEqual(fam["people"][0]["name"], 'Zoë "Z"')
        self.assertEqual(fam["people"][0]["notes"], "likes: space")
        self.assertNotIn("notes", fam["people"][1])
        self.assertEqual(fam["birthdays"], {'Zoë "Z"': "05-30"})
        example = yaml.safe_load(sq.EXAMPLE_FILE.read_text())
        self.assertEqual(fam["rules"], example["rules"])
        self.assertEqual(fam["games"], example["games"])

    def test_robot_reads_the_written_file(self):
        from robo.brain import _family_section
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "family.yaml"
            f.write_text(sq.family_yaml([{"name": "Ben", "role": "dad", "notes": ""}], {}, ["English"]))
            with patch.object(config, "FAMILY_FILE", f):
                self.assertIn("Ben", _family_section())


class ConfigFromEnv(unittest.TestCase):
    def reload(self, **env):
        # reload re-reads ~/.robo.env, so point it at a home folder that has none
        with patch.dict(os.environ, env), patch("pathlib.Path.home", return_value=Path("/nonexistent")):
            return importlib.reload(config)

    def tearDown(self):
        with patch("pathlib.Path.home", return_value=Path("/nonexistent")):
            importlib.reload(config)

    def test_language_and_microphone(self):
        c = self.reload(ROBO_LANGUAGE="de", ROBO_MIC_NAME="default")
        self.assertEqual((c.LANGUAGE, c.MIC_NAME), ("de", None))
        c = self.reload(ROBO_LANGUAGE="fr", ROBO_MIC_NAME="Blue Snowball")
        self.assertEqual((c.LANGUAGE, c.MIC_NAME), ("en", "Blue Snowball"))


if __name__ == "__main__":
    unittest.main()
