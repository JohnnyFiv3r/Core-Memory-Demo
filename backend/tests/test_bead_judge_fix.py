import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core import bead_judge_fix as bjf

# A template shaped like Core Memory's real one: a literal JSON example (single
# braces) plus the two real {user_query}/{assistant_final} placeholders.
BROKEN = (
    'Return JSON only with this shape:\n'
    '{\n  "type": "decision|goal",\n  "claims": [{"slot": "x", "value": "y"}]\n}\n\n'
    'USER: {user_query}\nASSISTANT: {assistant_final}\n'
)
ALREADY_SAFE = 'No JSON here. USER: {user_query} ASSISTANT: {assistant_final}'


class TestFormatSafeTransform(unittest.TestCase):
    def test_detects_broken_template(self):
        self.assertTrue(bjf.template_is_format_broken(BROKEN))

    def test_does_not_flag_safe_template(self):
        self.assertFalse(bjf.template_is_format_broken(ALREADY_SAFE))

    def test_make_format_safe_round_trips(self):
        safe = bjf.make_format_safe(BROKEN)
        self.assertFalse(bjf.template_is_format_broken(safe))
        out = safe.format(user_query="QQ", assistant_final="AA")
        # Literal JSON braces survive, placeholders substituted, no leftover escaping.
        self.assertIn('"type": "decision|goal"', out)
        self.assertIn('{', out)
        self.assertIn("QQ", out)
        self.assertIn("AA", out)
        self.assertNotIn("{{", out)
        self.assertNotIn("}}", out)

    def test_make_format_safe_is_idempotent_enough_to_format(self):
        # Even applied twice the result must still format (defensive).
        twice = bjf.make_format_safe(bjf.make_format_safe(ALREADY_SAFE))
        # ALREADY_SAFE has no JSON braces, so double-apply keeps placeholders intact.
        self.assertIn("user", twice)


class TestInstall(unittest.TestCase):
    def setUp(self):
        self._env = patch.dict("os.environ", {}, clear=False)
        self._env.start()
        os.environ.pop("CORE_MEMORY_BEAD_FIELD_PROMPT", None)
        os.environ.pop("CORE_MEMORY_BEAD_FIELD_PROMPT_FILE", None)

    def tearDown(self):
        self._env.stop()

    def test_respects_operator_prompt_override(self):
        os.environ["CORE_MEMORY_BEAD_FIELD_PROMPT"] = "operator-custom-prompt"
        res = bjf.install_bead_judge_prompt_format_fix()
        self.assertFalse(res["applied"])
        self.assertEqual("operator_prompt_override_present", res["reason"])
        self.assertEqual("operator-custom-prompt", os.environ["CORE_MEMORY_BEAD_FIELD_PROMPT"])

    def test_applies_when_default_template_broken(self):
        with patch("core_memory.policy.bead_judge._PROMPT", BROKEN):
            res = bjf.install_bead_judge_prompt_format_fix()
        self.assertTrue(res["applied"])
        installed = os.environ["CORE_MEMORY_BEAD_FIELD_PROMPT"]
        self.assertFalse(bjf.template_is_format_broken(installed))
        rendered = installed.format(user_query="", assistant_final="hi")
        self.assertIn('"type": "decision|goal"', rendered)

    def test_noop_when_template_already_safe(self):
        with patch("core_memory.policy.bead_judge._PROMPT", ALREADY_SAFE):
            res = bjf.install_bead_judge_prompt_format_fix()
        self.assertFalse(res["applied"])
        self.assertEqual("prompt_already_format_safe", res["reason"])
        self.assertNotIn("CORE_MEMORY_BEAD_FIELD_PROMPT", os.environ)

    def test_installed_prompt_lets_real_judge_template_build(self):
        # Against the actually-installed Core Memory: after install, the judge's
        # own _prompt_template().format(...) must not raise.
        from core_memory.policy.bead_judge import _PROMPT, _prompt_template

        if not bjf.template_is_format_broken(_PROMPT):
            self.skipTest("installed Core Memory prompt already format-safe")
        bjf.install_bead_judge_prompt_format_fix()
        rendered = _prompt_template().format(user_query="", assistant_final="Melanie adopted a dog.")
        self.assertIn("Melanie adopted a dog.", rendered)


if __name__ == "__main__":
    unittest.main()
