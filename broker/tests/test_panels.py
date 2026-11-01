"""What the release gates and the bundler make of panels, and the template that starts one. No servers needed.

Usage: python3 -m unittest broker.tests.test_panels
"""
import json
import pathlib
import tempfile
import unittest

from PIL import Image

from broker import bundles, promote
from broker.gates import GateFailed, static
from orchestrator import templates


def panel(*widgets, **fields):
    return {"title": "Kiln", "width": 176, "height": 166, "widgets": list(widgets), **fields}


def slot(x=8, y=8, number=0, **fields):
    return {"type": "slot", "x": x, "y": y, "slot": number, **fields}


class Rules(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = pathlib.Path(self.folder.name)
        (self.root / "assets" / "panels").mkdir(parents=True)
        for name in ("back", "bright"):
            Image.new("RGBA", (16, 16), (1, 2, 3, 255)).save(self.root / "assets" / "panels" / f"{name}.png")

    def check(self, shown):
        static.check_panels({"f": {"manifest": {"panels": {"kiln": shown}}, "dir": self.root}})

    def refused(self, shown, *mentions):
        with self.assertRaises(GateFailed) as caught:
            self.check(shown)
        for mention in mentions:
            self.assertIn(mention, caught.exception.message)

    def test_everything_a_panel_can_have(self):
        self.write_art("framed", [(8, 8)])
        self.check(panel(
            slot(page="main"),
            {"type": "label", "id": "state", "x": 8, "y": 20, "text": "Cold"},
            {"type": "icon", "x": 30, "y": 30, "icon": "minecraft:coal"},
            {"type": "image", "x": 50, "y": 30, "width": 16, "height": 16, "image": "bright"},
            {"type": "bar", "id": "heat", "x": 70, "y": 30, "width": 20, "height": 10, "color": "#ff0000", "direction": "up"},
            {"type": "button", "id": "go", "x": 8, "y": 50, "width": 40, "height": 18, "image": "back", "hover_image": "bright", "disabled_image": "back"},
            {"type": "tabs", "id": "tabs", "x": 60, "y": 4, "tabs": [{"id": "main", "text": "Main"}]},
            {"type": "list", "id": "offers", "x": 8, "y": 80, "width": 100, "height": 40, "max_rows": 9},
            {"type": "mob", "x": 120, "y": 80, "width": 40, "height": 40, "mob": "minecraft:pig"},
            {"type": "mob", "x": 120, "y": 120, "width": 40, "height": 40, "mob": "$mob:x", "portrait": "bright"},
            {"type": "text_field", "id": "name", "x": 8, "y": 130, "width": 60, "height": 14, "max_length": 12},
            background="framed", inventory=False))

    def test_a_panel_must_fit_on_a_small_screen(self):
        self.refused(panel(width=900), "900", "at most")
        self.refused(panel(height=400), "400", "at most")

    def test_missing_art_is_found_at_once(self):
        self.refused(panel(background="nope"), "assets/panels/nope.png")
        self.refused(panel({"type": "image", "x": 0, "y": 0, "width": 8, "height": 8, "image": "gone"}), "assets/panels/gone.png")
        self.refused(panel({"type": "button", "id": "b", "x": 0, "y": 0, "width": 8, "height": 8, "hover_image": "gone"}), "assets/panels/gone.png")

    def test_nothing_can_go_outside_it(self):
        self.refused(panel(slot(x=170)), "goes outside")
        self.refused(panel({"type": "bar", "id": "b", "x": 150, "y": 0, "width": 40, "height": 8, "color": "#ffffff"}), "goes outside")
        self.refused(panel(inventory={"x": 100, "y": 84}), "doesn't fit")

    def test_widgets_have_to_make_sense(self):
        self.refused(panel({"type": "window", "x": 0, "y": 0}), "window")
        self.refused(panel({"type": "button", "x": 0, "y": 0, "width": 8, "height": 8}), "needs an id")
        self.refused(panel({"type": "text_field", "id": "t", "x": 0, "y": 0, "width": 8, "height": 8}), "max_length")
        self.refused(panel({"type": "bar", "id": "b", "x": 0, "y": 0, "width": 8, "height": 8}), "image or a color")
        self.refused(panel(slot(number=-1)), "\"slot\"")
        self.refused(panel(slot(page="elsewhere")), "elsewhere")
        self.refused(panel({"type": "label", "id": "a", "x": 0, "y": 0}, {"type": "label", "id": "a", "x": 0, "y": 9}), "two widgets")

    def test_this_worlds_mobs_need_a_picture(self):
        self.refused(panel({"type": "mob", "x": 0, "y": 0, "width": 8, "height": 8, "mob": "$mob:x"}), "portrait")

    def test_it_has_to_fit_in_a_plain_chest_too(self):
        many = [slot(x=0, y=0, number=index) for index in range(55)]
        self.refused(panel(*many), "55 places")
        self.check(panel(*many[:54]))

    def test_text_cant_land_on_text(self):
        self.refused(panel({"type": "label", "x": 12, "y": 6, "text": "Kiln"}), "its title", "overlap")
        self.refused(panel({"type": "label", "x": 8, "y": 70, "text": "Load a charge"}, inventory={"x": 8, "y": 84}), "Inventory", "overlap")
        self.refused(panel({"type": "label", "x": 8, "y": 30, "text": "First"}, {"type": "label", "x": 10, "y": 32, "text": "Second"}), "First", "Second")
        self.refused(panel({"type": "label", "x": 8, "y": 30, "width": 20, "text": "A long line that wraps"}, {"type": "label", "x": 8, "y": 40, "text": "Under"}), "overlap")

    def test_text_is_fine_apart_or_on_other_pages(self):
        self.check(panel({"type": "label", "x": 8, "y": 20, "text": "Kiln"}, {"type": "label", "x": 8, "y": 30, "text": "Lit"}))
        self.check(panel({"type": "label", "x": 8, "y": 30, "text": "First", "page": "a"}, {"type": "label", "x": 10, "y": 32, "text": "Second", "page": "b"},
                         {"type": "tabs", "id": "t", "x": 60, "y": 4, "tabs": [{"id": "a", "text": "A"}, {"id": "b", "text": "B"}]}))
        self.check(panel({"type": "label", "x": 8, "y": 72, "text": "Over where it would be"}, inventory=False))
        self.check(panel({"type": "label", "id": "state", "x": 8, "y": 6}))

    def write_art(self, name, frames=()):
        art = Image.new("RGBA", (176, 166), (198, 198, 198, 255))
        for x, y in frames:
            art.paste((139, 139, 139, 255), (x - 1, y - 1, x + 17, y + 17))
        art.save(self.root / "assets" / "panels" / f"{name}.png")

    def test_art_has_to_show_the_players_slots(self):
        self.write_art("flat")
        self.refused(panel(background="flat"), "player's inventory", "float")
        self.refused(panel(background="flat", inventory={"x": 8, "y": 84}), "player's inventory", "8, 84")
        self.check(panel(background="flat", inventory=False))

    def test_art_has_to_show_each_slot(self):
        self.write_art("flat")
        self.refused(panel(slot(x=56, y=35), background="flat", inventory=False), "item slot at 56, 35")
        self.write_art("framed", [(56, 35)])
        self.check(panel(slot(x=56, y=35), background="framed", inventory=False))

    def test_a_big_frame_of_its_own_is_fine(self):
        art = Image.new("RGBA", (176, 166), (198, 198, 198, 255))
        art.paste((139, 139, 139, 255), (100, 30, 128, 58))
        art.save(self.root / "assets" / "panels" / "big.png")
        self.check(panel(slot(x=106, y=36), background="big", inventory=False))

    def test_panel_back_has_everything_the_check_wants(self):
        from assetkit import textures
        textures.panel_back(176, 166, slots=[(56, 35)]).save(self.root / "assets" / "panels" / "started.png")
        self.check(panel(slot(x=56, y=35), background="started", inventory={"x": 8, "y": 84}))

    def test_everything_wrong_is_said_at_once(self):
        self.refused(panel(slot(x=170), {"type": "image", "x": 0, "y": 0, "width": 8, "height": 8, "image": "gone"}), "goes outside", "gone.png")


class Bundling(unittest.TestCase):
    def test_a_panel_gets_its_places_in_the_chest_in_order(self):
        shown = panel(slot(), {"type": "image", "x": 0, "y": 0, "width": 1, "height": 1, "image": "a"}, {"type": "label", "x": 0, "y": 0, "text": "Just words"},
                      {"type": "button", "id": "go"}, {"type": "tabs", "id": "t", "tabs": [{"id": "a"}, {"id": "b"}]}, {"type": "list", "id": "l", "max_rows": 3}, {"type": "list", "id": "m"})
        self.assertEqual(bundles.panel_chest_slots(shown), 16)
        widgets = shown["widgets"]
        self.assertEqual((widgets[0]["chest_slot"], widgets[0]["chest_size"]), (0, 1))
        self.assertNotIn("chest_slot", widgets[1])
        self.assertNotIn("chest_slot", widgets[2])
        self.assertEqual(widgets[3]["chest_slot"], 1)
        self.assertEqual((widgets[4]["chest_slot"], widgets[4]["chest_size"]), (2, 2))
        self.assertEqual((widgets[5]["chest_slot"], widgets[5]["chest_size"]), (4, 3))
        self.assertEqual((widgets[6]["chest_slot"], widgets[6]["chest_size"]), (7, bundles.DEFAULT_LIST_ROWS))

    def test_a_rendered_panel_hides_its_names_and_has_its_art(self):
        with tempfile.TemporaryDirectory() as folder:
            root = pathlib.Path(folder)
            (root / "assets" / "panels").mkdir(parents=True)
            Image.new("RGBA", (16, 16), (1, 2, 3, 255)).save(root / "assets" / "panels" / "secret_name.png")
            manifest = {"panels": {"kiln": panel(slot(), {"type": "button", "id": "go", "x": 0, "y": 0, "width": 8, "height": 8, "icon": "$item:thing", "image": "secret_name"}, background="secret_name")}}
            ledger = {"blocks": {}, "items": {"f/thing": {"slot": "item_7"}}, "mobs": {}}
            rendered = bundles._render_panels({"manifest": manifest, "dir": root}, "f", ledger, root / "pack")
            shown = rendered["f/kiln"]
            self.assertNotIn("secret_name", json.dumps(rendered))
            self.assertTrue(shown["background"].startswith("gm:textures/gui/p"))
            self.assertEqual(shown["chest_rows"], 1)
            self.assertEqual(shown["widgets"][1]["icon"], "gm:item_7")
            self.assertEqual(shown["widgets"][1]["chest_slot"], 1)
            self.assertEqual(len(list((root / "pack" / "assets/gm/textures/gui").glob("*.png"))), 1)


class Photographs(unittest.TestCase):
    def write(self, folder, panels, art=None):
        (folder / "config").mkdir(parents=True, exist_ok=True)
        (folder / "config" / "panels.json").write_text(json.dumps(panels), encoding="utf-8")
        if art:
            (folder / "pack/assets/gm/textures/gui").mkdir(parents=True, exist_ok=True)
            (folder / "pack/assets/gm/textures/gui/p.png").write_bytes(art)

    def test_only_what_would_look_different_is_photographed(self):
        with tempfile.TemporaryDirectory() as folder:
            new, old = pathlib.Path(folder, "new"), pathlib.Path(folder, "old")
            self.write(old, {"f/same": {"width": 1}, "f/moved": {"width": 1}}, b"a")
            self.write(new, {"f/same": {"width": 1}, "f/moved": {"width": 2}, "f/added": {"width": 1}}, b"a")
            self.assertEqual(promote.changed_panels(new, old), ["f/added", "f/moved"])
            self.write(new, {"f/same": {"width": 1}}, b"b")
            self.assertEqual(promote.changed_panels(new, old), ["f/same"])

    def test_a_first_release_has_nothing_to_compare_with(self):
        with tempfile.TemporaryDirectory() as folder:
            new = pathlib.Path(folder, "new")
            self.write(new, {"f/added": {"width": 1}})
            self.assertEqual(promote.changed_panels(new, pathlib.Path(folder, "missing")), ["f/added"])


class Template(unittest.TestCase):
    def test_a_machine_can_start_with_a_working_panel(self):
        with tempfile.TemporaryDirectory() as folder:
            root = pathlib.Path(folder)
            templates.new_machine(root, name="kiln", display="Kiln", casing="#555566", accent="#cc8844", panel=True)
            manifest = json.loads((root / "feature.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["blocks"]["kiln"]["inventory"], {"inputs": 1, "outputs": 1})
            feature = {"manifest": manifest, "dir": root}
            self.assertEqual(static._panel_problems(feature, manifest["panels"]["kiln"]), [])
            self.assertTrue((root / "assets" / "panels" / "kiln_back.png").exists())
            module = next((root / "server").rglob("*.java")).read_text(encoding="utf-8")
            self.assertIn("openPanel", module)
            self.assertNotIn("@", module.replace("@Override", ""))

    def test_without_one_it_is_as_it_was(self):
        with tempfile.TemporaryDirectory() as folder:
            root = pathlib.Path(folder)
            templates.new_machine(root, name="kiln", display="Kiln", casing="#555566", accent="#cc8844")
            manifest = json.loads((root / "feature.json").read_text(encoding="utf-8"))
            self.assertNotIn("panels", manifest)
            self.assertNotIn("inventory", manifest["blocks"]["kiln"])


if __name__ == "__main__":
    unittest.main()
