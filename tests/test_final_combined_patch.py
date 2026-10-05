import unittest
from pathlib import Path

from scripts.apply_final_combined_patch import ANCHOR, HELPER, REPLACEMENT, patch_html


class FinalCombinedPatchTest(unittest.TestCase):
    def test_injects_published_ensemble_precedence(self):
        source = "prefix\n" + ANCHOR + "\npost"
        patched, changed = patch_html(source)
        self.assertTrue(changed)
        self.assertIn(HELPER.strip(), patched)
        self.assertIn(REPLACEMENT, patched)
        self.assertIn("const published = getPublishedFinalCombined(game, market);", patched)

    def test_patch_is_idempotent(self):
        source = "prefix\n" + ANCHOR + "\npost"
        patched, changed = patch_html(source)
        again, changed_again = patch_html(patched)
        self.assertTrue(changed)
        self.assertFalse(changed_again)
        self.assertEqual(patched, again)


if __name__ == "__main__":
    unittest.main()
