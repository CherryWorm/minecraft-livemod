"""What the gates and the bundler make of projectiles, vehicles and props. No servers needed.

Usage: python3 -m unittest broker.tests.test_entities
"""
import json
import pathlib
import tempfile
import unittest

from broker import bundles
from broker.gates import GateFailed, advice, balance, bytecode, progression, static
from broker.tests.test_balance import feature
from orchestrator import tuning

POOL = {"families": {"stone": {"first": 0, "count": 4}}, "item_count": 4, "mobs": {"monster": 2, "creature": 2},
        "entities": {"projectiles": 5, "vehicles": 5, "props": 5}}
EARLY = {"goal": "g", "nodes": {"start": {"stage": "early", "name": "s", "requires": [], "opens_with": "", "holds": "h"}}}
LATER = {"goal": "g", "nodes": {"start": {"stage": "mid", "name": "s", "requires": [], "opens_with": "", "holds": "h"}}}


def shot(**fields):
    return {"display": "Bolt", "model": "m", "tier": "iron", "damage": 5, "speed": 30, "gravity": 12, "lifetime": 5, "width": 0.5, "height": 0.5, "shots_per_second": 1, **fields}


def boat(**fields):
    return {"display": "Boat", "model": "m", "tier": "iron", "moves": "water", "speed": 12, "seat": 0.5, "width": 1.5, "height": 0.6, **fields}


def prop(**fields):
    return {"display": "Prop", "model": "m", "width": 1, "height": 2, **fields}


def with_model(root, feature_id="f", **manifest):
    """A feature on disk with a model file, which is the one thing here that has to be really there."""
    folder = root / feature_id
    (folder / "assets" / "models").mkdir(parents=True)
    (folder / "assets" / "models" / "m.bbmodel").write_text("{}", encoding="utf-8")
    return {feature_id: {"manifest": {"id": feature_id, **manifest}, "dir": folder}}


class Slots(unittest.TestCase):
    def assign(self, ledger=None, **manifest):
        return bundles.assign_slots({"f": {"manifest": manifest}}, ledger or bundles.empty_ledger(), POOL)

    def test_each_pool_numbers_its_own_slots(self):
        ledger = self.assign(projectiles={"a": {}, "b": {}}, vehicles={"c": {}}, props={"d": {}})
        self.assertEqual(ledger["projectiles"]["f/a"]["slot"], "p0001")
        self.assertEqual(ledger["projectiles"]["f/b"]["slot"], "p0002")
        self.assertEqual(ledger["vehicles"]["f/c"]["slot"], "v0001")
        self.assertEqual(ledger["props"]["f/d"]["slot"], "o0001")

    def test_mobs_keep_their_slots_beside_these(self):
        mob = {"category": "monster"}
        ledger = self.assign(mobs={"m": mob}, projectiles={"a": {}})
        self.assertEqual(ledger["mobs"]["f/m"]["slot"], "e0001")
        again = self.assign(json.loads(json.dumps(ledger)), mobs={"m": mob, "n": mob}, projectiles={"a": {}, "b": {}})
        self.assertEqual(again["mobs"]["f/m"]["slot"], "e0001")
        self.assertEqual(again["mobs"]["f/n"]["slot"], "e0002")
        self.assertEqual(again["projectiles"]["f/a"]["slot"], "p0001")

    def test_a_ledger_from_before_these_gets_them(self):
        old = {"blocks": {}, "items": {}, "mobs": {}, "patches": []}
        self.assertEqual(self.assign(old, vehicles={"c": {}})["vehicles"]["f/c"]["slot"], "v0001")

    def test_an_empty_pool_says_so(self):
        with self.assertRaisesRegex(bundles.BundleError, "no free vehicles slots"):
            self.assign(vehicles={name: {} for name in "abcdef"})

    def test_a_slot_can_never_change_or_go(self):
        old = self.assign(vehicles={"c": {}})
        with self.assertRaisesRegex(GateFailed, "removed from the ledger"):
            static.check_ledger_append_only(old, {**old, "vehicles": {}})
        with self.assertRaisesRegex(GateFailed, "moved from v0001"):
            static.check_ledger_append_only(old, {**old, "vehicles": {"f/c": {"slot": "v0002"}}})
        with self.assertRaisesRegex(GateFailed, "no feature declares"):
            static.check_kept_names({"f": feature()}, old)

    def test_the_budget_keeps_a_reserve(self):
        ledger = self.assign(props={name: {} for name in "abcde"})
        with self.assertRaisesRegex(GateFailed, "5 props would be in use, over the limit of 4"):
            static.check_slot_budget(ledger, POOL)
        ledger["props"].pop("f/e")
        static.check_slot_budget(ledger, POOL)

    def test_the_pool_is_read_from_the_mod_itself(self):
        pool = bundles.read_pool(pathlib.Path(__file__).resolve().parents[2])
        self.assertEqual(set(pool["entities"]), set(bundles.ENTITY_TABLES))
        self.assertTrue(all(count > 0 for count in pool["entities"].values()))
        # Taken from what's already in released worlds, so these can't ever shrink.
        self.assertEqual(pool["mobs"], {"monster": 240, "creature": 480})


class Render(unittest.TestCase):
    def render(self, manifest):
        with tempfile.TemporaryDirectory() as folder:
            root = pathlib.Path(folder)
            features = with_model(root, **manifest)
            ledger = bundles.assign_slots(features, bundles.empty_ledger(), POOL)
            out = root / "out"
            bundles.render(features, ledger, out, 15)
            read = lambda *path: json.loads(out.joinpath(*path).read_text(encoding="utf-8"))  # noqa: E731
            return ledger, read("config", "entities.json"), read("pack", "assets", "gm", "lang", "en_us.json"), read("config", "bindings.json"), read("config", "item_defaults.json")

    def test_a_definition_says_nothing_of_what_it_is(self):
        ledger, entities, lang, bindings, _ = self.render({"projectiles": {"bolt": shot(sounds={"hit": "minecraft:entity.arrow.hit"})}})
        definition = entities["projectiles"]["gm:p0001"]
        self.assertEqual(definition["damage"], 5)
        self.assertEqual(definition["sounds"], {"hit": "minecraft:entity.arrow.hit"})
        self.assertRegex(definition["model"], r"^m[0-9a-f]{16}$")
        self.assertNotIn("display", definition)
        self.assertEqual(lang["entity.gm.p0001"], "Bolt")
        self.assertEqual(bindings["f/bolt"], "p0001")

    def test_shots_have_a_rate_even_if_none_is_given(self):
        fields = shot()
        del fields["shots_per_second"]
        _, entities, *_ = self.render({"projectiles": {"bolt": fields}})
        self.assertEqual(entities["projectiles"]["gm:p0001"]["shots_per_second"], bundles.DEFAULT_SHOTS_PER_SECOND)

    def test_an_item_that_places_a_vehicle_is_what_it_breaks_back_into(self):
        with tempfile.TemporaryDirectory() as folder:
            root = pathlib.Path(folder)
            features = with_model(root, vehicles={"skiff": boat()}, items={"kit": {"display": "Kit", "texture": "kit", "places_vehicle": "skiff"}})
            (features["f"]["dir"] / "assets" / "textures").mkdir()
            (features["f"]["dir"] / "assets" / "textures" / "kit.png").write_bytes(b"")
            ledger = bundles.assign_slots(features, bundles.empty_ledger(), POOL)
            bundles.render(features, ledger, root / "out", 15)
            entities = json.loads((root / "out" / "config" / "entities.json").read_text(encoding="utf-8"))
            defaults = json.loads((root / "out" / "config" / "item_defaults.json").read_text(encoding="utf-8"))
        self.assertEqual(entities["vehicles"]["gm:v0001"]["item"], "gm:i0001")
        self.assertEqual(defaults["gm:i0001"]["vehicle"], "gm:v0001")

    def test_tokens_reach_these_as_well(self):
        self.assertEqual(bundles._resolve_tokens("$vehicle:c", "f", {"blocks": {}, "items": {}, "vehicles": {"f/c": {"slot": "v0009"}}}), "gm:v0009")
        self.assertEqual(bundles._resolve_tokens("$projectile:other/c", "f", {"blocks": {}, "items": {}, "projectiles": {"other/c": {"slot": "p0009"}}}), "gm:p0009")


class Instant(unittest.TestCase):
    """Each one on its own, so a mistake here gets found in seconds, with a message that says what to do."""

    def problem(self, check, **manifest):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(GateFailed) as caught:
                check(with_model(pathlib.Path(folder), **manifest))
        return caught.exception.message if hasattr(caught.exception, "message") else str(caught.exception)

    def passes(self, check, **manifest):
        with tempfile.TemporaryDirectory() as folder:
            check(with_model(pathlib.Path(folder), **manifest))

    def test_a_good_projectile_passes(self):
        self.passes(static.check_projectiles, projectiles={"a": shot(trail="minecraft:flame")})

    def test_a_projectile_needs_sensible_numbers(self):
        for fields, expected in (({"speed": 0}, "speed"), ({"speed": 1000}, "speed"), ({"gravity": -1}, "gravity"), ({"lifetime": 0}, "lifetime"),
                                 ({"lifetime": 600}, "lifetime"), ({"shots_per_second": 0}, "shots_per_second"), ({"width": 0}, "width"), ({"model": "absent"}, "absent.bbmodel"),
                                 ({"trail": "minecraft:dust"}, "trail"), ({"trail": "flame"}, "trail"), ({"display": ""}, "display")):
            self.assertIn(expected, self.problem(static.check_projectiles, projectiles={"a": shot(**fields)}))

    def test_a_good_vehicle_passes(self):
        self.passes(static.check_vehicles, vehicles={"a": boat(steering="look", land_speed=0.2, turn=60)})

    def test_a_vehicle_needs_sensible_numbers(self):
        for fields, expected in (({"moves": "underground"}, "moves"), ({"speed": 0}, "speed"), ({"speed": 500}, "speed"), ({"steering": "reins"}, "steering"), ({"seat": -1}, "seat"),
                                 ({"acceleration": 0}, "could never start"), ({"turn": -1}, "turn"), ({"climb": 3}, "only means something"), ({"water_speed": 0.5}, "only means something")):
            self.assertIn(expected, self.problem(static.check_vehicles, vehicles={"a": boat(**fields)}))

    def test_an_item_can_only_place_a_vehicle_that_exists(self):
        self.assertIn("no feature declares", self.problem(static.check_vehicles, items={"kit": {"places_vehicle": "nothing"}}))

    def test_only_one_item_places_a_vehicle(self):
        found = self.problem(static.check_vehicles, vehicles={"a": boat()}, items={"kit": {"places_vehicle": "a"}, "kit2": {"places_vehicle": "a"}})
        self.assertIn("both place", found)

    def test_a_name_can_only_mean_one_thing(self):
        found = self.problem(static.check_entity_names, vehicles={"skiff": boat()}, items={"skiff": {"places_vehicle": "skiff"}})
        self.assertIn("share one set of names", found)
        self.passes(static.check_entity_names, vehicles={"skiff": boat()}, items={"skiff_kit": {"places_vehicle": "skiff"}})

    def test_a_good_prop_passes(self):
        self.passes(static.check_props, props={"a": prop(clickable=True)})

    def test_a_prop_needs_a_size(self):
        self.assertIn("width", self.problem(static.check_props, props={"a": prop(width=100)}))

    def test_their_sounds_are_checked_like_a_mobs(self):
        self.assertIn("sounds", self.problem(static.check_mob_sounds, projectiles={"a": shot(sounds={"moo": "minecraft:x"})}))
        self.assertIn("no feature lists", self.problem(static.check_mob_sounds, vehicles={"a": boat(sounds={"hurt": "$sound:absent"})}))
        self.passes(static.check_mob_sounds, sounds=["bang"], projectiles={"a": shot(sounds={"hit": "$sound:bang"})})

    def test_a_shot_can_only_afford_a_few_moving_parts(self):
        with tempfile.TemporaryDirectory() as folder:
            root = pathlib.Path(folder)
            features = with_model(root, projectiles={"a": shot()})
            cubes = [{"uuid": str(index)} for index in range(6)]
            model = {"elements": cubes, "outliner": [{"children": [{"children": [str(index)]} for index in range(6)]}]}
            (features["f"]["dir"] / "assets" / "models" / "m.bbmodel").write_text(json.dumps(model), encoding="utf-8")
            with self.assertRaisesRegex(GateFailed, "moving parts"):
                static.check_model_costs(features)


class Power(unittest.TestCase):
    """Nothing fired or driven gets past what its stage allows, however it's described."""

    def problems(self, **manifest):
        features = {"f": feature(**manifest)}
        return balance.check_projectiles(features) + balance.check_vehicles(features)

    def test_a_shot_at_its_tier_passes(self):
        self.assertEqual(self.problems(projectiles={"a": shot(damage=9.9, shots_per_second=1)}), [])

    def test_a_shot_harder_than_its_tier_fails(self):
        found = self.problems(projectiles={"a": shot(damage=10)})
        self.assertEqual(len(found), 1)
        self.assertIn("limit of 9.9", found[0])

    def test_firing_faster_counts_up_to_what_a_target_can_take(self):
        self.assertIn("damage a second", self.problems(projectiles={"a": shot(damage=9, shots_per_second=2)})[0])
        # A target can only take two hits a second, so twenty shots a second of a small one comes to the same as two.
        self.assertEqual(self.problems(projectiles={"a": shot(damage=5, shots_per_second=20)}), [])

    def test_damage_needs_a_tier(self):
        fields = shot()
        del fields["tier"]
        self.assertIn("no tier", self.problems(projectiles={"a": fields})[0])
        self.assertEqual(self.problems(projectiles={"a": {**fields, "damage": 0}}), [])

    def test_damage_has_to_be_a_number(self):
        for bad in (None, "lots", -1, float("nan"), True):
            self.assertIn("number for damage", self.problems(projectiles={"a": shot(damage=bad)})[0], bad)

    def test_a_tier_has_to_be_real(self):
        self.assertIn("declares tier", self.problems(projectiles={"a": shot(tier="ultra")})[0])
        self.assertIn("needs a \"tier\"", self.problems(vehicles={"a": boat(tier="ultra")})[0])

    def test_mythic_has_no_ceiling(self):
        self.assertEqual(self.problems(projectiles={"a": shot(tier="mythic", damage=500, shots_per_second=20)}, vehicles={"b": boat(tier="mythic", speed=60)}), [])

    def test_a_vehicle_answers_to_its_tier(self):
        self.assertEqual(self.problems(vehicles={"a": boat(tier="wood", speed=8.8)}), [])
        self.assertIn("limit of 8.8", self.problems(vehicles={"a": boat(tier="wood", speed=9)})[0])
        self.assertIn("goes 40", self.problems(vehicles={"a": boat(reverse=40)})[0])

    def test_a_vehicle_has_to_say_its_tier(self):
        fields = boat()
        del fields["tier"]
        self.assertIn("needs a \"tier\"", self.problems(vehicles={"a": fields})[0])

    def test_the_balance_gate_runs_these(self):
        with self.assertRaisesRegex(GateFailed, "limit of 9.9"):
            balance.run({"f": feature(projectiles={"a": shot(damage=10)})})


class Stages(unittest.TestCase):
    """The tier a thing says it is has to fit where it sits in the world."""

    def problems(self, doc, **manifest):
        features = {"f": feature(node="start", **manifest)}
        return progression._check_tiers(features, doc, []) + progression._check_mobs(features, doc)

    def test_a_late_shot_cant_sit_in_the_early_game(self):
        self.assertIn("strongest allowed is iron", self.problems(EARLY, projectiles={"a": shot(tier="netherite", damage=1)})[0])

    def test_a_late_vehicle_cant_sit_in_the_early_game(self):
        self.assertIn("strongest allowed is iron", self.problems(EARLY, vehicles={"a": boat(tier="diamond")})[0])

    def test_a_shot_can_do_no_more_than_a_mob_of_that_stage(self):
        # A mob can fire it, so it's held to what the mob is, even with a tier that would otherwise allow it.
        self.assertIn("because a mob could fire it", self.problems(EARLY, projectiles={"a": shot(damage=9)})[0])
        self.assertEqual(self.problems(EARLY, projectiles={"a": shot(damage=6)}), [])
        self.assertEqual(self.problems(LATER, projectiles={"a": shot(tier="beyond", damage=15)}), [])

    def test_mythic_needs_an_endgame(self):
        features = {"f": feature(projectiles={"a": shot(tier="mythic")})}
        self.assertIn("mythic", progression._mythic_without_a_place(features, [])[0])


class Advice(unittest.TestCase):
    def notes(self, **manifest):
        with tempfile.TemporaryDirectory() as folder:
            return advice.run(with_model(pathlib.Path(folder), knowledge={"k": {}}, **manifest))

    def test_nothing_can_fire_a_shot_without_a_module(self):
        self.assertTrue(any("only a module can fire" in note for note in self.notes(projectiles={"a": shot()})))

    def test_nothing_can_place_a_prop_without_a_module(self):
        self.assertTrue(any("only a module can place" in note for note in self.notes(props={"a": prop()})))

    def test_a_vehicle_needs_an_item_or_a_module(self):
        self.assertTrue(any("places_vehicle" in note for note in self.notes(vehicles={"a": boat()})))
        self.assertFalse(any("places_vehicle" in note for note in self.notes(vehicles={"a": boat()}, items={"kit": {"places_vehicle": "a"}})))


class Tuning(unittest.TestCase):
    def test_their_numbers_can_be_tuned_later(self):
        manifest = {"projectiles": {"a": shot()}, "vehicles": {"b": boat()}}
        tuning.apply(manifest, "projectiles", "a", "damage", 3, "Players said it hit far too hard in the first fights.")
        tuning.apply(manifest, "vehicles", "b", "speed", 10, "Players said it outran the land loading on a slow connection.")
        self.assertEqual(manifest["projectiles"]["a"]["damage"], 3)
        self.assertEqual(manifest["vehicles"]["b"]["speed"], 10)

    def test_but_not_what_else_they_are(self):
        with self.assertRaises(tuning.TuneError):
            tuning.apply({"vehicles": {"b": boat()}}, "vehicles", "b", "moves", 1, "A number that a tune has no business changing at all.")


class Modules(unittest.TestCase):
    def test_modules_are_allowed_what_theyre_handed(self):
        for name in ("SlotProjectile", "SlotVehicle", "SlotProp"):
            self.assertIsNone(bytecode._class_problem(f"gm/conduit/entities/{name}", "server"))

    def test_but_not_the_host_behind_them(self):
        for name in ("SlotEntities", "Beams", "VehicleHolder"):
            self.assertIsNotNone(bytecode._class_problem(f"gm/conduit/entities/{name}", "server"))

    def test_client_modules_get_none_of_it(self):
        self.assertIsNotNone(bytecode._class_problem("gm/conduit/entities/SlotVehicle", "client"))


class Docs(unittest.TestCase):
    def test_builders_are_told_every_field(self):
        docs = (pathlib.Path(__file__).resolve().parents[2] / "docs" / "content-types.md").read_text(encoding="utf-8")
        for fields in bundles.ENTITY_FIELDS.values():
            for field in fields:
                self.assertIn(f"`{field}`", docs)


if __name__ == "__main__":
    unittest.main()
