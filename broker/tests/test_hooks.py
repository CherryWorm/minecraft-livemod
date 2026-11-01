"""What the release gates and the bundler make of the engine's newer hooks: sounds by name. No servers needed.

Usage: python3 -m unittest broker.tests.test_hooks
"""
import json
import pathlib
import tempfile
import unittest

from broker import bundles


class SoundsByName(unittest.TestCase):
    def render(self, manifest, sounds=("chime",)):
        with tempfile.TemporaryDirectory() as folder:
            root = pathlib.Path(folder)
            feature = root / "feature"
            (feature / "assets" / "sounds").mkdir(parents=True)
            for name in sounds:
                (feature / "assets" / "sounds" / f"{name}.ogg").write_bytes(b"OggS")
            (feature / "assets" / "textures").mkdir()
            (feature / "assets" / "textures" / "chime.png").write_bytes(b"png")
            found = {"f": {"manifest": manifest, "dir": feature}}
            ledger = bundles.assign_slots(found, bundles.empty_ledger(), {"families": {"stone": {"first": 0, "count": 4}}, "item_count": 4, "mobs": {"monster": 1, "creature": 1}})
            bundles.render(found, ledger, root / "out", 1)
            return json.loads((root / "out" / "config" / "bindings.json").read_text(encoding="utf-8"))

    def test_a_module_can_find_it_by_name(self):
        bindings = self.render({"id": "f", "sounds": ["chime"]})
        # The same name the pack's own sounds.json uses, so what a module plays is what the pack has.
        self.assertEqual(bindings["sound:f/chime"], bundles._sound_id("f", "chime"))

    def test_it_can_share_a_name_with_a_block(self):
        bindings = self.render({"id": "f", "sounds": ["chime"], "blocks": {"chime": {"family": "stone", "display": "Chime"}}})
        self.assertEqual(bindings["f/chime"], "s0000")
        self.assertEqual(bindings["sound:f/chime"], bundles._sound_id("f", "chime"))


if __name__ == "__main__":
    unittest.main()
