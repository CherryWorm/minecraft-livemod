"""Tests for assetkit/sculpt.py and the depth-buffered preview in bbmodel.py. Run with: python3 -m unittest assetkit.test_sculpt"""
import json
import math
import os
import pathlib
import tempfile
import unittest
from unittest import mock

import numpy as np

from assetkit import bbmodel as bb
from assetkit import sculpt

RED, GREEN, BLUE = "#dd2222", "#22dd22", "#2222dd"
LEGS = ["leg_r", "leg_l"]


def voxels(part):
    """The solid voxels of a part as a set of index triples."""
    return {tuple(int(v) for v in i + part.lo) for i in np.argwhere(part.solid_grid)}


def color_at(part, index):
    return tuple(int(v) for v in part.rgba[tuple(np.array(index) - part.lo)][:3])


def rainbow(x, y, z):
    """A different colour on nearly every voxel, so a texel in the wrong place shows up."""
    return np.stack([(x * 37 + 90) % 256, (y * 53 + 60) % 256, (z * 71 + 30) % 256], axis=1)


def creature(name="thing", grain=1):
    """Something small and complete enough to pass every check."""
    m = sculpt.Model(name, grain=grain)
    body = m.part("body", pivot=(0, 4, 0))
    body.ball((0, 6, 0), (6, 6, 6), GREEN)
    head = m.part("head", parent=body, pivot=(0, 11, -2))
    head.ball((0, 14, -3), (4, 4, 4), GREEN)
    head.decal(["k.k"], {"k": "#111111"}, at=(0, 15, 0))
    leg = m.part("leg_r", parent=body, pivot=(3, 3, 0))
    leg.taper((3, 3, 0), (3, 1, 0), 1.5, 1.5, GREEN)
    m.mirror(leg)
    m.animate("idle", 2.0, sculpt.bob(body, 0.5), sculpt.swing("head", 3), sculpt.plant(LEGS))
    m.animate("walk", 1.0, sculpt.gait(LEGS, stride=3, lift=2, body=body, drop=0.3))
    m.animate("hurt", 0.4, sculpt.flinch(body), sculpt.plant(LEGS), loop="once")
    m.animate("death", 1.0, sculpt.collapse(body, limbs={"head": (10, 0, 0)}), loop="hold")
    return m


class Shapes(unittest.TestCase):
    def setUp(self):
        self.m = sculpt.Model("shapes")
        self.p = self.m.part("p")

    def test_box_fills_exactly_its_corners(self):
        self.p.box((-2, 0, 1), (2, 3, 2), RED)
        self.assertEqual(voxels(self.p), {(x, y, 1) for x in range(-2, 2) for y in range(3)})

    def test_ball_is_what_its_equation_says(self):
        self.p.ball((0, 5, 0), (4, 3, 2), RED)
        want = {(x, y, z) for x in range(-6, 6) for y in range(0, 10) for z in range(-4, 4)
                if ((x + 0.5) / 4) ** 2 + ((y + 0.5 - 5) / 3) ** 2 + ((z + 0.5) / 2) ** 2 <= 1}
        self.assertEqual(voxels(self.p), want)

    def test_a_higher_power_fills_more_of_the_box(self):
        round_one = sculpt.Model("a").part("p").ball((0, 0, 0), 6, RED)
        boxy = sculpt.Model("b").part("p").ball((0, 0, 0), 6, RED, power=4)
        self.assertGreater(len(voxels(boxy)), len(voxels(round_one)))

    def test_capsule_has_round_ends_and_cylinder_flat_ones(self):
        self.p.capsule((0, 0, 0), (0, 10, 0), 3, RED)
        top = max(v[1] for v in voxels(self.p))
        self.assertEqual(top, 12)
        flat = sculpt.Model("f").part("p")
        flat.cylinder((0, 0, 0), (0, 10, 0), 3, RED)
        self.assertEqual(max(v[1] for v in voxels(flat)), 9)

    def test_taper_narrows_toward_its_second_radius(self):
        self.p.taper((0, 0, 0), (0, 20, 0), 6, 1, RED)
        width = lambda y: sum(1 for v in voxels(self.p) if v[1] == y and v[2] == 0)
        self.assertGreater(width(2), width(10))
        self.assertGreater(width(10), width(18))

    def test_taper_can_point_any_way(self):
        self.p.taper((0, 0, 0), (10, 10, 10), 2, 1, RED)
        found = np.array(sorted(voxels(self.p)), float) + 0.5
        # Everything lies close to the line, and it gets to both ends.
        off = found - (found @ np.ones(3) / 3)[:, None]
        self.assertLess(np.linalg.norm(off, axis=1).max(), 2.5)
        self.assertLess(found.sum(axis=1).min(), 3)
        self.assertGreater(found.sum(axis=1).max(), 27)

    def test_a_thin_limb_doesnt_vanish(self):
        self.p.taper((0.5, 0.5, 0.5), (0.5, 12.5, 0.5), 0.3, 0.05, RED)
        self.assertEqual({v[1] for v in voxels(self.p)}, set(range(0, 13)))
        self.assertEqual(len(sculpt._components(self.p.solid_grid)), 1)

    def test_solid_takes_any_function_of_position(self):
        self.p.solid(lambda x, y, z: (x + y + z) > 0, (-3, -3, -3), (3, 3, 3), RED)
        for v in voxels(self.p):
            self.assertGreater(sum(c + 0.5 for c in v), 0)
        self.assertTrue(voxels(self.p))

    def test_solid_works_with_a_function_written_for_single_numbers(self):
        def inside(x, y, z):
            if math.hypot(x, y) < 3:  # both math and `if` refuse an array
                return abs(z) < 1
            return False

        self.p.solid(inside, (-4, -4, -2), (4, 4, 2), RED)
        self.assertEqual({v[2] for v in voxels(self.p)}, {-1, 0})
        self.assertIn((0, 0, 0), voxels(self.p))

    def test_polygon_fills_its_outline(self):
        self.p.polygon([(0, 0), (8, 0), (0, 8)], RED, facing="front", at=0, thick=1)
        self.assertIn((1, 1, 0), voxels(self.p))
        self.assertNotIn((6, 6, 0), voxels(self.p))
        self.assertEqual({v[2] for v in voxels(self.p)}, {0})

    def test_polygon_faces_any_axis(self):
        self.p.polygon([(2, 0), (6, 0), (6, 4), (2, 4)], RED, facing="left", at=0, thick=1)
        self.assertEqual({v[0] for v in voxels(self.p)}, {0})
        self.assertEqual({v[2] for v in voxels(self.p)}, {2, 3, 4, 5})

    def test_tube_runs_through_its_points(self):
        self.p.tube(sculpt.curve((0, 0, 0), (0, 10, 0), (10, 10, 0), n=8), 1.0, RED)
        self.assertIn((0, 0, 0), voxels(self.p))
        self.assertIn((9, 9, 0), voxels(self.p))
        self.assertNotIn((9, 0, 0), voxels(self.p))

    def test_shapes_combine(self):
        half = sculpt.ball((0, 0, 0), 5) & sculpt.box((-9, 0, -9), (9, 9, 9))
        self.p.add(half, RED)
        self.assertEqual(min(v[1] for v in voxels(self.p)), 0)
        ring = sculpt.Model("r").part("p")
        ring.add(sculpt.cylinder((0, 0, 0), (0, 1, 0), 5) - sculpt.cylinder((0, 0, 0), (0, 1, 0), 2), RED)
        self.assertNotIn((0, 0, 0), voxels(ring))
        self.assertIn((3, 0, 0), voxels(ring))

    def test_a_shape_can_be_rotated_on_the_grid(self):
        self.p.add(sculpt.box((-1, 0, -1), (1, 10, 1)).rotated((0, 0, -90)), RED)
        found = voxels(self.p)
        # Z rotation by -90 takes +Y to +X.
        self.assertIn((8, 0, 0), found)
        self.assertNotIn((0, 8, 0), found)

    def test_absurd_coordinates_are_refused(self):
        with self.assertRaisesRegex(ValueError, "Check its coordinates"):
            self.p.box((-5000, -5000, -5000), (5000, 5000, 5000), RED)

    def test_a_shape_needs_a_colour(self):
        with self.assertRaisesRegex(ValueError, "needs a colour"):
            self.p.ball((0, 0, 0), 3)


class Writing(unittest.TestCase):
    def setUp(self):
        self.m = sculpt.Model("writing")
        self.p = self.m.part("p")

    def test_later_shapes_overwrite_earlier_ones(self):
        self.p.box((0, 0, 0), (4, 4, 4), RED)
        self.p.box((2, 2, 2), (6, 6, 6), BLUE)
        self.assertEqual(color_at(self.p, (0, 0, 0)), (0xdd, 0x22, 0x22))
        self.assertEqual(color_at(self.p, (3, 3, 3)), (0x22, 0x22, 0xdd))
        self.assertEqual(color_at(self.p, (5, 5, 5)), (0x22, 0x22, 0xdd))

    def test_cut_removes_voxels(self):
        self.p.box((0, 0, 0), (4, 4, 4), RED)
        self.p.cut.box((1, 1, 1), (3, 3, 3))
        self.assertNotIn((1, 1, 1), voxels(self.p))
        self.assertIn((0, 0, 0), voxels(self.p))
        self.assertEqual(len(voxels(self.p)), 64 - 8)

    def test_cut_takes_a_shape_too(self):
        self.p.box((0, 0, 0), (4, 4, 4), RED)
        self.p.cut(sculpt.box((0, 0, 0), (2, 4, 4)))
        self.assertEqual({v[0] for v in voxels(self.p)}, {2, 3})

    def test_cut_on_nothing_is_harmless(self):
        self.p.cut.ball((0, 0, 0), 3)
        self.p.box((0, 0, 0), (1, 1, 1), RED)
        self.p.cut.box((50, 50, 50), (60, 60, 60))
        self.assertEqual(voxels(self.p), {(0, 0, 0)})

    def test_paint_changes_colour_without_changing_shape(self):
        self.p.box((0, 0, 0), (4, 4, 4), RED)
        before = voxels(self.p)
        self.p.paint.ball((0, 0, 0), 2, BLUE)
        self.assertEqual(voxels(self.p), before)
        self.assertEqual(color_at(self.p, (0, 0, 0)), (0x22, 0x22, 0xdd))
        self.assertEqual(color_at(self.p, (3, 3, 3)), (0xdd, 0x22, 0x22))

    def test_paint_that_lands_on_nothing_is_reported(self):
        self.p.box((0, 0, 0), (4, 4, 4), RED)
        self.p.paint.box((40, 40, 40), (44, 44, 44), BLUE)
        self.assertTrue(any("landed on nothing" in p for p in sculpt.check(self.m)))

    def test_the_grid_grows_and_keeps_what_it_had(self):
        self.p.box((0, 0, 0), (2, 2, 2), RED)
        self.p.box((-30, 40, 7), (-28, 42, 9), BLUE)
        self.assertEqual(color_at(self.p, (0, 0, 0)), (0xdd, 0x22, 0x22))
        self.assertEqual(color_at(self.p, (-30, 40, 7)), (0x22, 0x22, 0xdd))
        self.assertEqual(len(voxels(self.p)), 16)

    def test_mirror_option_draws_both_sides(self):
        self.p.ball((5, 0, 0), 2, RED, mirror="x")
        found = voxels(self.p)
        self.assertEqual(found, {(-x - 1, y, z) for x, y, z in found})
        self.assertTrue(any(v[0] > 0 for v in found) and any(v[0] < 0 for v in found))

    def test_mirror_reflects_a_colour_function(self):
        self.p.box((1, 0, 0), (5, 1, 1), lambda x, y, z: np.stack([x * 40, x * 0, x * 0], axis=1), mirror="x")
        self.assertEqual(color_at(self.p, (3, 0, 0)), color_at(self.p, (-4, 0, 0)))

    def test_mirroring_a_shape_returns_its_reflection(self):
        shape = sculpt.mirror(sculpt.box((1, 0, 0), (3, 1, 1)))
        self.p.add(shape, RED)
        self.assertEqual(voxels(self.p), {(-3, 0, 0), (-2, 0, 0)})

    def test_mirror_in_place_copies_across_the_middle(self):
        self.p.box((2, 0, 0), (4, 2, 1), RED)
        self.p.box((3, 1, 0), (4, 2, 1), BLUE)
        self.p.mirror("x")
        self.assertIn((-4, 1, 0), voxels(self.p))
        self.assertEqual(color_at(self.p, (-4, 1, 0)), (0x22, 0x22, 0xdd))
        self.assertEqual(color_at(self.p, (-3, 0, 0)), (0xdd, 0x22, 0x22))

    def test_mirroring_a_part_flips_its_pivot_rotation_and_children(self):
        arm = self.m.part("arm_r", parent=self.p, pivot=(4, 5, 0), rotation=(10, 20, 30))
        arm.box((4, 0, 0), (6, 5, 1), RED)
        hand = self.m.part("hand_r", parent=arm, pivot=(5, 0, 0))
        hand.box((4, -2, 0), (6, 0, 1), BLUE)
        left = sculpt.mirror(arm)
        self.assertEqual(left.name, "arm_l")
        self.assertEqual(left.pivot, (-4, 5, 0))
        self.assertEqual(left.rotation, (10, -20, -30))
        self.assertEqual(voxels(left), {(-x - 1, y, z) for x, y, z in voxels(arm)})
        self.assertEqual(self.m.parts["hand_l"].parent, "arm_l")

    def test_a_mirrored_part_stands_alone(self):
        arm = self.m.part("arm_r", parent=self.p, pivot=(4, 5, 0))
        arm.box((4, 0, 0), (6, 5, 1), RED)
        left = self.m.mirror(arm)
        arm.box((4, 5, 0), (6, 9, 1), BLUE)
        self.assertEqual(len(voxels(left)), 10)

    def test_mirror_names(self):
        for name, want in (("leg_r", "leg_l"), ("arm_left", "arm_right"), ("wing_l_tip", "wing_r_tip"), ("right_ear", "left_ear"), ("tail", "tail_mirror")):
            self.assertEqual(sculpt._swapped(name), want)


class Colour(unittest.TestCase):
    def setUp(self):
        self.x = np.arange(-20, 20, dtype=float) + 0.5
        self.y = self.x * 0 + 0.5
        self.z = self.x * 0 + 0.5

    def test_plain_colours(self):
        for color, want in (("#102030", (16, 32, 48, 255)), ((1, 2, 3), (1, 2, 3, 255)), ((1, 2, 3, 4), (1, 2, 3, 4))):
            self.assertEqual(tuple(sculpt._colors(color, self.x, self.y, self.z)[0]), want)

    def test_a_colour_function_may_return_one_colour_or_many(self):
        self.assertEqual(tuple(sculpt._colors(lambda x, y, z: "#010203", self.x, self.y, self.z)[3]), (1, 2, 3, 255))
        out = sculpt._colors(rainbow, self.x, self.y, self.z)
        self.assertEqual(out.shape, (40, 4))
        self.assertGreater(len(np.unique(out, axis=0)), 10)

    def test_a_colour_function_written_for_single_numbers_works(self):
        out = sculpt._colors(lambda x, y, z: (200, 0, 0) if math.sin(x) > 0 else (0, 200, 0), self.x, self.y, self.z)
        self.assertEqual(len(np.unique(out, axis=0)), 2)

    def test_gradient_runs_between_its_points_in_flat_steps(self):
        out = sculpt.gradient(["#000000", "#ff0000"], (-20, 0, 0), (20, 0, 0), steps=4)(self.x, self.y, self.z)
        self.assertEqual(out[0, 0], 0)
        self.assertEqual(out[-1, 0], 255)
        self.assertEqual(len(np.unique(out[:, 0])), 4)
        self.assertTrue((np.diff(out[:, 0]) >= 0).all())

    def test_bands_repeat(self):
        out = sculpt.bands([RED, BLUE], along="x", width=5)(self.x, self.y, self.z)
        self.assertEqual(out[0, 0], out[10, 0])
        self.assertNotEqual(out[0, 0], out[5, 0])

    def test_bands_along_a_function(self):
        out = sculpt.bands([RED, BLUE], along=lambda x, y, z: np.abs(x), width=100)(self.x, self.y, self.z)
        self.assertEqual(len(np.unique(out[:, 0])), 1)

    def test_stripes_keep_to_where_they_are_told(self):
        out = sculpt.stripes(RED, BLUE, along="x", every=10, width=2, start=0, stop=15, where=lambda x, y, z: x > 5)(self.x, self.y, self.z)
        blue = self.x[out[:, 2] == 0xdd]
        self.assertTrue(((blue >= 10) & (blue <= 12)).all())
        self.assertTrue(len(blue))

    def test_spots_are_clusters_and_repeat_for_a_seed(self):
        x, y, z = [a.ravel().astype(float) + 0.5 for a in np.mgrid[-15:15, -15:15, 0:1]]
        a = sculpt.spots(RED, BLUE, size=2, spacing=8, seed=1)(x, y, z)
        b = sculpt.spots(RED, BLUE, size=2, spacing=8, seed=1)(x, y, z)
        c = sculpt.spots(RED, BLUE, size=2, spacing=8, seed=2)(x, y, z)
        self.assertTrue((a == b).all())
        self.assertFalse((a == c).all())
        share = (a[:, 2] == 0xdd).mean()
        self.assertTrue(0.03 < share < 0.6, share)

    def test_patch_paints_inside_its_ellipsoid(self):
        out = sculpt.patch(RED, BLUE, (0, 0, 0), (5, 5, 5))(self.x, self.y, self.z)
        self.assertEqual(out[20, 2], 0xdd)
        self.assertEqual(out[0, 0], 0xdd)
        self.assertEqual(out[0, 2], 0x22)

    def test_mottle_covers_about_what_it_says(self):
        x, y, z = [a.ravel().astype(float) + 0.5 for a in np.mgrid[-20:20, -20:20, -20:20]]
        little = (sculpt.mottle(RED, BLUE, amount=0.1)(x, y, z)[:, 2] == 0xdd).mean()
        lots = (sculpt.mottle(RED, BLUE, amount=0.5)(x, y, z)[:, 2] == 0xdd).mean()
        self.assertLess(little, lots)
        self.assertGreater(lots, 0.25)

    def test_helpers_stack(self):
        paint = sculpt.patch(sculpt.gradient([RED, GREEN], (-20, 0, 0), (20, 0, 0)), BLUE, (0, 0, 0), (2, 2, 2))
        out = paint(self.x, self.y, self.z)
        self.assertEqual(tuple(out[20][:3]), (0x22, 0x22, 0xdd))
        self.assertEqual(out[0, 0], 0xdd)

    def test_where_chooses_between_paints(self):
        out = sculpt.where(lambda x, y, z: x > 0, RED, BLUE)(self.x, self.y, self.z)
        self.assertEqual(out[-1, 0], 0xdd)
        self.assertEqual(out[0, 2], 0xdd)

    def test_shading_moves_along_the_ramp_and_lights_the_top(self):
        m = sculpt.Model("lit")
        p = m.part("p")
        p.ball((0, 0, 0), 8, "#a06030")
        colors = p.final_colors()["south"]
        top, bottom = (0, 6, 0), (0, -7, 0)
        bright = lambda i: colors[tuple(np.array(i) - p.lo)][:3].astype(int).sum()
        self.assertGreater(bright(top), bright(bottom))
        self.assertGreater(len(np.unique(colors[p.solid_grid][:, :3], axis=0)), 2)

    def test_shade_false_keeps_a_colour_exact(self):
        m = sculpt.Model("flat")
        p = m.part("p")
        p.ball((0, 0, 0), 8, "#a06030", shade=False)
        for colors in p.final_colors().values():
            self.assertEqual(np.unique(colors[p.solid_grid][:, :3], axis=0).tolist(), [[0xa0, 0x60, 0x30]])

    def test_no_shading_at_all_for_a_model_that_asks(self):
        m = sculpt.Model("flat", shade=0)
        p = m.part("p")
        p.ball((0, 0, 0), 8, "#a06030")
        self.assertEqual(np.unique(p.final_colors()["up"][p.solid_grid][:, :3], axis=0).tolist(), [[0xa0, 0x60, 0x30]])

    def test_glow_keeps_its_colour_and_marks_the_cube(self):
        m = creature()
        m.parts["head"].ball((0, 13, -7), 1.5, "#ff0000", glow=12)
        doc = m.build()
        lit = [e for e in doc["elements"] if e.get("light_emission")]
        self.assertTrue(lit)
        self.assertEqual({e["light_emission"] for e in lit}, {12})
        self.assertEqual(bb.check(doc), [])


class Pixels(unittest.TestCase):
    def setUp(self):
        self.m = sculpt.Model("pixels")
        self.p = self.m.part("p")
        self.pal = {"r": RED, "b": BLUE, "g": GREEN}

    def test_decal_lands_where_its_aimed_and_reads_as_seen(self):
        self.p.box((-8, 0, -4), (8, 16, 4), "#808080")
        # Viewed from the front, +X is on the left, so "r" lands on the +X side.
        self.p.decal(["rb", "gb"], self.pal, at=(0, 8, 0), facing="front")
        self.assertEqual(color_at(self.p, (0, 8, -4)), (0xdd, 0x22, 0x22))
        self.assertEqual(color_at(self.p, (-1, 8, -4)), (0x22, 0x22, 0xdd))
        self.assertEqual(color_at(self.p, (0, 7, -4)), (0x22, 0xdd, 0x22))
        self.assertEqual(color_at(self.p, (-1, 7, -4)), (0x22, 0x22, 0xdd))
        # Only the surface: not the voxel behind, and not next to it.
        self.assertEqual(color_at(self.p, (0, 8, -3)), (0x80, 0x80, 0x80))
        self.assertEqual(color_at(self.p, (1, 8, -4)), (0x80, 0x80, 0x80))

    def test_decal_follows_a_curved_surface(self):
        self.p.ball((0, 0, 0), 8, "#808080")
        self.p.decal(["r" * 6] * 6, self.pal, at=(0, 0, 0), facing="front")
        for x in range(-3, 3):
            for y in range(-3, 3):
                z = min(v[2] for v in voxels(self.p) if v[0] == x and v[1] == y)
                self.assertEqual(color_at(self.p, (x, y, z)), (0xdd, 0x22, 0x22))
                self.assertEqual(color_at(self.p, (x, y, z + 1)), (0x80, 0x80, 0x80))

    def test_every_side_can_be_aimed_at(self):
        for facing, spot, row_axis in (("back", (0, 0, 3), 1), ("left", (-4, 0, 0), 1), ("right", (3, 0, 0), 1), ("top", (0, 3, 0), 2), ("bottom", (0, -4, 0), 2)):
            m = sculpt.Model("side")
            p = m.part("p")
            p.box((-4, -4, -4), (4, 4, 4), "#808080")
            p.decal(["r"], self.pal, at=(0.5, 0.5, 0.5), facing=facing)
            self.assertEqual(color_at(p, spot), (0xdd, 0x22, 0x22), facing)

    def test_decal_can_come_from_an_angle(self):
        self.p.ball((0, 0, 0), 8, "#808080")
        self.p.decal(["r" * 4] * 4, self.pal, at=(5, 0, -5), facing=(-0.707, 0, 0.707))
        red = [v for v in voxels(self.p) if color_at(self.p, v) == (0xdd, 0x22, 0x22)]
        self.assertTrue(red)
        self.assertGreater(min(v[0] for v in red), -1)
        self.assertLess(max(v[2] for v in red), 1)

    def test_mirrored_decal_lands_opposite_and_reads_reversed(self):
        self.p.box((-8, 0, -4), (8, 16, 4), "#808080")
        self.p.decal(["rb"], self.pal, at=(4, 8.5, 0), mirror="x")
        self.assertEqual(color_at(self.p, (4, 8, -4)), (0xdd, 0x22, 0x22))
        self.assertEqual(color_at(self.p, (3, 8, -4)), (0x22, 0x22, 0xdd))
        self.assertEqual(color_at(self.p, (-5, 8, -4)), (0xdd, 0x22, 0x22))
        self.assertEqual(color_at(self.p, (-4, 8, -4)), (0x22, 0x22, 0xdd))

    def test_transparent_pixels_leave_the_surface_alone(self):
        self.p.box((-8, 0, -4), (8, 16, 4), "#808080")
        self.p.decal(["r.r", ".. ", "r?r"], self.pal, at=(0, 8, 0))
        self.assertEqual(sum(1 for v in voxels(self.p) if color_at(self.p, v) == (0xdd, 0x22, 0x22)), 4)

    def test_decal_stays_exact_through_shading(self):
        self.p.ball((0, 0, 0), 8, "#808080")
        self.p.decal(["r"], self.pal, at=(0.5, 0.5, 0))
        index = tuple(np.array((0, 0, -8)) - self.p.lo)
        self.assertEqual(tuple(self.p.final_colors()["north"][index][:3]), (0xdd, 0x22, 0x22))

    def test_a_decal_that_misses_is_reported(self):
        self.p.box((0, 0, 0), (2, 2, 2), "#808080")
        self.p.decal(["rrrr"], self.pal, at=(1, 1, 0))
        self.assertTrue(any("missed the surface" in p for p in self.m._notes))
        self.m.part("q").decal(["r"], self.pal, at=(0, 0, 0))
        self.assertTrue(any("nothing to land on" in p for p in self.m._notes))

    def test_decal_near_reaches_past_what_is_in_the_way(self):
        self.p.box((-4, 0, -8), (4, 8, -6), "#808080")
        self.p.box((-8, 0, 0), (8, 8, 4), "#808080")
        self.p.decal(["r"], self.pal, at=(0.5, 4.5, -5), near=0)
        self.assertEqual(color_at(self.p, (0, 4, 0)), (0xdd, 0x22, 0x22))
        self.assertEqual(color_at(self.p, (0, 4, -8)), (0x80, 0x80, 0x80))

    def test_decal_paints_deeper_when_asked(self):
        self.p.box((-4, 0, -4), (4, 8, 4), "#808080")
        self.p.decal(["r"], self.pal, at=(0.5, 4.5, 0), depth=3)
        self.assertEqual(color_at(self.p, (0, 4, -2)), (0xdd, 0x22, 0x22))
        self.assertEqual(color_at(self.p, (0, 4, -1)), (0x80, 0x80, 0x80))

    def test_layers_place_exact_voxels_as_seen_from_the_front(self):
        self.p.layers([["rb"], ["g."]], self.pal, at=(0, 3.5, -2))
        self.assertEqual(voxels(self.p), {(0, 3, -2), (-1, 3, -2), (0, 3, -1)})
        self.assertEqual(color_at(self.p, (0, 3, -2)), (0xdd, 0x22, 0x22))
        self.assertEqual(color_at(self.p, (-1, 3, -2)), (0x22, 0x22, 0xdd))
        self.assertEqual(color_at(self.p, (0, 3, -1)), (0x22, 0xdd, 0x22))

    def test_one_list_of_strings_is_one_layer(self):
        self.p.layers(["r", "r"], self.pal, at=(0.5, 4, 0.5), facing="top")
        self.assertEqual(len(voxels(self.p)), 2)
        self.assertEqual({v[1] for v in voxels(self.p)}, {3})

    def test_layers_mirror(self):
        self.p.layers(["rb"], self.pal, at=(4, 4, 0), mirror="x")
        self.assertEqual(color_at(self.p, (4, 3, 0)), color_at(self.p, (-5, 3, 0)))
        self.assertEqual(color_at(self.p, (3, 3, 0)), color_at(self.p, (-4, 3, 0)))

    def test_uneven_rows_are_refused(self):
        with self.assertRaisesRegex(ValueError, "same length"):
            self.p.layers(["rr", "r"], self.pal, at=(0, 0, 0))


class Meshing(unittest.TestCase):
    def blob(self, seed):
        rng = np.random.default_rng(seed)
        x, y, z = np.mgrid[0:14, 0:12, 0:10]
        mask = ((x - 7) / 6.5) ** 2 + ((y - 6) / 5.5) ** 2 + ((z - 5) / 4.5) ** 2 < 1
        return mask ^ (rng.random(mask.shape) < 0.04)

    def test_boxes_cover_exactly_the_solid_voxels_with_no_overlap(self):
        for seed in range(6):
            mask = self.blob(seed)
            count = np.zeros(mask.shape, int)
            for lo, hi in sculpt.greedy_boxes(mask):
                count[lo[0]:hi[0], lo[1]:hi[1], lo[2]:hi[2]] += 1
            self.assertTrue((count == mask).all(), seed)

    def test_an_empty_grid_has_no_boxes(self):
        self.assertEqual(sculpt.greedy_boxes(np.zeros((3, 3, 3), bool)), [])

    def test_a_box_is_one_box_whatever_its_colours(self):
        m = sculpt.Model("one")
        p = m.part("p")
        p.box((0, 0, 0), (9, 7, 5), rainbow, shade=False)
        doc = m.build()
        self.assertEqual(len(doc["elements"]), 1)
        self.assertEqual(doc["elements"][0]["from"], [0, 0, 0])
        self.assertEqual(doc["elements"][0]["to"], [9, 7, 5])

    def test_a_round_shape_merges_far_below_its_voxels(self):
        m = sculpt.Model("round")
        p = m.part("p")
        p.ball((0, 0, 0), 8, RED)
        self.assertLess(len(m.build()["elements"]), 120)
        self.assertGreater(len(voxels(p)), 2000)

    def test_hidden_faces_are_left_out_and_a_box_with_nothing_showing_is_dropped(self):
        m = sculpt.Model("hidden", shade=0)
        p = m.part("p")
        p.box((0, 0, 0), (6, 6, 6), RED)
        p.box((6, 0, 0), (12, 3, 6), BLUE)  # a smaller box against one side, so a split of some kind is needed
        doc = m.build()
        count = sum(len(e["faces"]) for e in doc["elements"])
        self.assertLess(count, 6 * len(doc["elements"]) + 1)
        for e in doc["elements"]:
            self.assertTrue(e["faces"])

    def test_nested_core_makes_no_inner_cubes(self):
        m = sculpt.Model("core", shade=0)
        p = m.part("p")
        p.ball((0, 0, 0), 8, RED)
        p.ball((0, 0, 0), 3, BLUE, glow=5)
        doc = m.build()
        self.assertFalse(any(e.get("light_emission") for e in doc["elements"]), "nothing of the core shows")

    def skin_check(self, m):
        """Every exposed voxel face is on exactly one face of one cube, with the right colour on the right texel, using the
        same corner order the game maps a face's texture by."""
        doc = m.build()
        skin = np.asarray(bb.skin(doc))
        names = {g["uuid"]: g["name"] for g in doc["groups"]}
        owner = {}

        def walk(node):
            for child in node["children"]:
                if isinstance(child, dict):
                    walk(child)
                else:
                    owner[child] = names[node["uuid"]]

        for root in doc["outliner"]:
            walk(root)
        painted = set()
        normals = {"north": (0, 0, -1), "south": (0, 0, 1), "east": (1, 0, 0), "west": (-1, 0, 0), "up": (0, 1, 0), "down": (0, -1, 0)}
        for e in doc["elements"]:
            part = m.parts[owner[e["uuid"]]]
            colors = part.final_colors()
            corners = bb._corners(e["from"], e["to"])
            for face, data in e["faces"].items():
                u0, v0, u1, v1 = data["uv"]
                tl, tr, br, bl = (np.array(c, float) for c in corners[face])
                inward = -np.array(normals[face]) * part.grain / 2
                for row in range(v1 - v0):
                    for col in range(u1 - u0):
                        fu, fv = (col + 0.5) / (u1 - u0), (row + 0.5) / (v1 - v0)
                        point = tl + (tr - tl) * fu + (bl - tl) * fv + inward
                        index = tuple(int(i) for i in np.floor(point / part.grain + 1e-9).astype(int))
                        self.assertEqual(tuple(skin[v0 + row, u0 + col]), tuple(colors[face][tuple(np.array(index) - part.lo)]), f"{part.name} {face} {index}")
                        painted.add((part.name, index, face))
        for part in m.parts.values():
            if part.solid_grid is None:
                continue
            opaque = part.solid_grid & (part.rgba[..., 3] == 255)
            exposed = sculpt._exposed(part.solid_grid, opaque)
            for face, grid in exposed.items():
                for i in np.argwhere(grid):
                    index = tuple(int(v) for v in i + part.lo)
                    self.assertIn((part.name, index, face), painted)

    def test_every_exposed_face_is_painted_with_the_right_colour(self):
        m = sculpt.Model("rainbow", shade=0)
        p = m.part("p", pivot=(1, 2, 3))
        p.ball((0, 0, 0), (7, 5, 6), rainbow)
        p.cut.box((-2, -9, -9), (2, 9, -2))
        p.box((5, -9, -3), (9, 9, -1), rainbow)
        self.skin_check(m)

    def test_shaded_faces_are_right_too(self):
        m = sculpt.Model("shaded")
        p = m.part("p")
        p.ball((0, 0, 0), (6, 5, 4), rainbow)
        self.skin_check(m)

    def test_grain_faces_are_right_too(self):
        m = sculpt.Model("coarse", grain=2, shade=0)
        p = m.part("p")
        p.ball((1, 3, -5), (10, 8, 6), rainbow)
        self.skin_check(m)

    def test_translucent_faces_show_only_on_the_outside(self):
        m = sculpt.Model("glass", shade=0)
        p = m.part("p")
        p.ball((0, 0, 0), 7, (100, 100, 220, 150))
        p.ball((0, 0, 0), 2.5, (240, 80, 80))
        doc = m.build()
        skin = np.asarray(bb.skin(doc))
        # The opaque core has its own cubes, drawn before the glass around it.
        order = [e["faces"] for e in doc["elements"]]
        alphas = []
        for faces in order:
            u0, v0, u1, v1 = next(iter(faces.values()))["uv"]
            region = skin[v0:v1, u0:u1, 3]
            alphas.append(region.max())
        self.assertEqual(alphas[0], 255, "opaque first, since BIL keeps element order")
        self.assertLess(alphas[-1], 255)
        self.assertEqual(sorted(set(alphas), reverse=True)[0], 255)
        self.assertGreater(sum(a < 255 for a in alphas), 3)
        seen = (skin[..., 3] == 150).sum()
        self.assertGreater(seen, 100)

    def test_opaque_voxels_show_behind_glass(self):
        m = sculpt.Model("behind", shade=0)
        p = m.part("p")
        p.box((-3, 0, -3), (3, 6, 3), (240, 80, 80))
        p.box((-5, 0, -5), (5, 6, -3), (100, 100, 220, 150))
        doc = m.build()
        # The red block's front is behind the glass slab, and has to have been kept.
        red = [e for e in doc["elements"] if e["to"][0] == 3 and e["from"][0] == -3]
        self.assertTrue(any("north" in e["faces"] for e in red))

    def test_atlas_never_overlaps_and_is_a_power_of_two(self):
        for m in (creature(), creature(grain=2)):
            doc = m.build()
            side = doc["textures"][0]["width"]
            self.assertEqual(side, doc["textures"][0]["height"])
            self.assertEqual(side & (side - 1), 0)
            used = np.zeros((side, side), int)
            for e in doc["elements"]:
                for data in e["faces"].values():
                    u0, v0, u1, v1 = data["uv"]
                    self.assertTrue(0 <= u0 < u1 <= side and 0 <= v0 < v1 <= side)
                    used[v0:v1, u0:u1] += 1
            self.assertLessEqual(used.max(), 1)

    def test_uv_rectangles_are_one_texel_per_voxel(self):
        m = sculpt.Model("texels")
        m.part("p", grain=2).box((0, 0, 0), (8, 4, 12), RED)
        e = m.build()["elements"][0]
        self.assertEqual(e["to"], [8, 4, 12])
        u0, v0, u1, v1 = e["faces"]["north"]["uv"]
        self.assertEqual((u1 - u0, v1 - v0), (4, 2))
        u0, v0, u1, v1 = e["faces"]["east"]["uv"]
        self.assertEqual((u1 - u0, v1 - v0), (6, 2))
        u0, v0, u1, v1 = e["faces"]["up"]["uv"]
        self.assertEqual((u1 - u0, v1 - v0), (4, 6))

    def test_packing_fits_the_smallest_square_it_can(self):
        side, spots = sculpt._pack([(4, 4)] * 4)
        self.assertEqual(side, 16)
        self.assertEqual(len(set(spots)), 4)
        side, spots = sculpt._pack([(100, 3), (3, 100)])
        self.assertEqual(side, 128)
        self.assertEqual(sculpt._pack([])[0], 16)


class Grain(unittest.TestCase):
    def test_voxels_are_grain_units_across(self):
        m = sculpt.Model("coarse", grain=4)
        p = m.part("p")
        p.box((0, 0, 0), (16, 8, 4), RED)
        self.assertEqual(len(voxels(p)), 4 * 2 * 1)
        e = m.build()["elements"][0]
        self.assertEqual((e["from"], e["to"]), ([0, 0, 0], [16, 8, 4]))
        self.assertEqual(m.build()["textures"][0]["width"], 16)

    def test_shapes_stay_symmetric_at_a_coarse_grain(self):
        m = sculpt.Model("coarse", grain=2)
        p = m.part("p")
        p.box((-3, 0, -3), (3, 4, 3), RED)
        found = voxels(p)
        self.assertEqual(found, {(-x - 1, y, z) for x, y, z in found})

    def test_a_part_can_have_its_own_grain(self):
        m = sculpt.Model("mixed", grain=2)
        a = m.part("a")
        b = m.part("b", parent=a, grain=1)
        c = m.part("c", parent=a)
        self.assertEqual((a.grain, b.grain, c.grain), (2, 1, 2))

    def test_decal_pixels_are_grain_sized(self):
        m = sculpt.Model("coarse", grain=2)
        p = m.part("p")
        p.box((-8, 0, -8), (8, 16, 8), "#808080")
        p.decal(["rr"], {"r": RED}, at=(0, 9, 0))
        red = [v for v in voxels(p) if color_at(p, v) == (0xdd, 0x22, 0x22)]
        self.assertEqual(sorted(red), [(-1, 4, -4), (0, 4, -4)])

    def test_a_decal_can_be_scaled_up(self):
        m = sculpt.Model("scaled")
        p = m.part("p")
        p.box((-8, 0, -8), (8, 16, 8), "#808080")
        p.decal(["r"], {"r": RED}, at=(0, 8, 0), scale=2)
        self.assertEqual(sum(1 for v in voxels(p) if color_at(p, v) == (0xdd, 0x22, 0x22)), 4)


class Output(unittest.TestCase):
    def test_passes_the_bil_checks(self):
        self.assertEqual(bb.check(creature().build()), [])
        self.assertEqual(sculpt.check(creature()), [])

    def test_is_deterministic(self):
        self.assertEqual(json.dumps(creature().build()), json.dumps(creature().build()))

    def test_saves_and_reloads(self):
        m = creature()
        with tempfile.TemporaryDirectory() as d:
            path = m.save(pathlib.Path(d) / "sub" / "thing.bbmodel")
            loaded = bb.load(path)
        self.assertEqual(loaded, json.loads(json.dumps(m.build())))
        self.assertEqual(bb.check(loaded), [])
        self.assertEqual(sculpt.check(loaded), [])

    def test_a_built_model_is_rebuilt_only_when_something_changes(self):
        m = creature()
        first = m.build()
        self.assertIs(m.build(), first)
        m.parts["body"].ball((0, 6, 0), 2, RED)
        self.assertIsNot(m.build(), first)

    def test_format_fields_bil_needs(self):
        doc = creature().build()
        self.assertEqual(doc["meta"]["format_version"], "5.0")
        for g in doc["groups"]:
            self.assertEqual(len(g["origin"]), 3)
            self.assertEqual(len(g["rotation"]), 3)
            self.assertTrue(g["export"])
        for e in doc["elements"]:
            self.assertEqual(e["type"], "cube")
            self.assertEqual(len(e["origin"]), 3)
            for face in e["faces"]:
                self.assertIn(face, bb.FACES)
        texture = doc["textures"][0]
        self.assertTrue(texture["source"].startswith("data:image/png;base64,"))
        self.assertEqual(texture["uv_width"], texture["width"])

    def test_one_root_bone_whatever_the_author_makes(self):
        m = sculpt.Model("roots")
        m.part("a", pivot=(0, 0, 0)).box((0, 0, 0), (2, 2, 2), RED)
        m.part("b", pivot=(4, 0, 0)).box((4, 0, 0), (6, 2, 2), RED)
        doc = m.build()
        self.assertEqual(len(doc["outliner"]), 1)
        self.assertEqual({g["name"] for g in doc["groups"]}, {"root", "a", "b"})
        self.assertFalse(doc["outliner"][0]["children"][0]["children"] == [])

    def test_a_root_name_that_is_taken_is_avoided(self):
        m = sculpt.Model("roots")
        m.part("root").box((0, 0, 0), (2, 2, 2), RED)
        m.part("other").box((4, 0, 0), (6, 2, 2), RED)
        self.assertEqual({g["name"] for g in m.build()["groups"]}, {"root", "root_", "other"})

    def test_rest_rotation_reaches_the_file(self):
        m = sculpt.Model("posed")
        m.part("a", rotation=(10, 20, 30)).box((0, 0, 0), (2, 2, 2), RED)
        self.assertEqual(m.build()["groups"][0]["rotation"], [10, 20, 30])

    def test_geometry_stays_inside_the_item_model_limits_after_bils_scaling(self):
        """A port of BIL's postProcess: cubes are made relative to the bone pivot, scaled down if the bone spans over 24
        units counting the pivot, and moved by +8. The result must fit the -16..32 of a block model."""
        m = sculpt.Model("big", grain=2)
        p = m.part("p", pivot=(0, 40, 0))
        p.ball((0, 40, 0), (30, 40, 20), RED)
        far = m.part("far", parent=p, pivot=(90, 0, 0))
        far.box((30, 30, -10), (50, 50, 10), RED)
        doc = m.build()
        groups = {g["uuid"]: g for g in doc["groups"]}
        elements = {e["uuid"]: e for e in doc["elements"]}
        seen = []

        def walk(node):
            origin = np.array(groups[node["uuid"]]["origin"], float)
            cubes = [elements[c] for c in node["children"] if isinstance(c, str)]
            if cubes:
                lo, hi = np.zeros(3), np.zeros(3)
                for c in cubes:
                    lo, hi = np.minimum(lo, np.array(c["from"]) - origin), np.maximum(hi, np.array(c["to"]) - origin)
                scale = min(1.0, 24.0 / (hi - lo).max())
                seen.append(scale)
                self.assertGreaterEqual((lo * scale + 8).min(), -16 - 1e-6)
                self.assertLessEqual((hi * scale + 8).max(), 32 + 1e-6)
            for child in node["children"]:
                if isinstance(child, dict):
                    walk(child)

        walk(doc["outliner"][0])
        self.assertLess(min(seen), 1.0, "this test should exercise the scaling")

    def test_names_are_checked(self):
        for name in ("Bad Name", "UPPER", ""):
            with self.assertRaises(ValueError):
                sculpt.Model(name)
        m = sculpt.Model("named")
        m.part("a")
        with self.assertRaises(ValueError):
            m.part("a")
        with self.assertRaises(ValueError):
            m.part("b", parent="missing")
        with self.assertRaises(ValueError):
            m.part("With Space")

    def test_stats_give_the_numbers(self):
        m = sculpt.Model("sized")
        m.part("p").box((-8, 0, -4), (8, 32, 4), RED)
        m.animate("idle", 1, sculpt.bob("p"))
        m.animate("walk", 1, sculpt.bob("p"))
        s = sculpt.stats(m)
        self.assertEqual(s["size"], (1.0, 2.0, 0.5))
        self.assertEqual(s["height"], 2.0)
        self.assertEqual((s["bones"], s["drawn_bones"], s["elements"], s["faces"]), (1, 1, 1, 6))
        self.assertEqual(s["atlas"], m.build()["textures"][0]["width"])
        self.assertEqual(s["bytes"], len(json.dumps(m.build(), separators=(",", ":"))))
        self.assertEqual(sculpt.stats(m.build())["elements"], 1)

    def test_stats_width_goes_by_the_bulk_rather_than_the_wings(self):
        m = sculpt.Model("winged")
        body = m.part("body", pivot=(0, 8, 0))
        body.box((-8, 0, -8), (8, 16, 8), RED)
        wing = m.part("wing", parent=body, pivot=(8, 12, 0))
        wing.box((8, 12, -8), (72, 13, 8), RED)
        s = sculpt.stats(m)
        self.assertEqual(s["size"][0], 5.0)
        self.assertLess(s["width"], 2.5)
        self.assertGreater(s["width"], 0.9)

    def test_stats_take_rest_rotation_into_account(self):
        m = sculpt.Model("turned")
        m.part("p", pivot=(0, 0, 0), rotation=(0, 0, 90)).box((0, 0, 0), (32, 8, 8), RED)
        s = sculpt.stats(m)
        self.assertAlmostEqual(s["size"][1], 2.0, places=2)
        self.assertAlmostEqual(s["size"][0], 0.5, places=2)

    def test_finish_writes_everything(self):
        m = creature()
        with tempfile.TemporaryDirectory() as d, mock.patch("builtins.print"):
            problems = m.finish(pathlib.Path(d) / "t.bbmodel", preview=pathlib.Path(d) / "t.png")
            self.assertEqual(problems, [])
            self.assertTrue((pathlib.Path(d) / "t.bbmodel").exists())
            self.assertTrue((pathlib.Path(d) / "t.png").exists())


class Check(unittest.TestCase):
    def problems(self, m, needle):
        return [p for p in sculpt.check(m) if needle in p]

    def test_floating_voxels_are_caught_and_located(self):
        m = creature()
        m.parts["body"].box((30, 30, 30), (32, 32, 32), RED)
        found = self.problems(m, "float apart")
        self.assertEqual(len(found), 1)
        self.assertIn("part 'body'", found[0])
        self.assertIn("31.0", found[0])

    def test_corners_count_as_touching(self):
        m = creature()
        p = m.part("diag", parent="body")
        p.box((0, 0, 0), (1, 1, 1), RED)
        p.box((1, 1, 1), (2, 2, 2), RED)
        self.assertFalse(self.problems(m, "float apart"))

    def test_loose_parts_are_allowed_to_be_in_pieces(self):
        m = creature()
        p = m.part("swarm", parent="body", loose=True)
        p.box((0, 0, 0), (1, 1, 1), RED)
        p.box((5, 5, 5), (6, 6, 6), RED)
        self.assertFalse(self.problems(m, "float apart"))

    def test_a_part_that_doesnt_touch_its_parent_is_caught(self):
        m = creature()
        m.part("away", parent="body", pivot=(0, 0, 0)).box((40, 40, 40), (44, 44, 44), RED)
        self.assertEqual(len(self.problems(m, "doesn't touch")), 1)

    def test_touching_goes_by_the_rest_pose(self):
        m = sculpt.Model("posed")
        base = m.part("base", pivot=(0, 0, 0))
        base.box((-2, 0, -2), (2, 4, 2), RED)
        # Drawn far away, and swung by its rest rotation to meet its parent.
        arm = m.part("arm", parent=base, pivot=(0, 2, 0), rotation=(0, 0, 90))
        arm.box((-1, 3, -1), (1, 10, 1), RED)
        self.assertFalse(self.problems(m, "doesn't touch"))
        away = m.part("away", parent=base, pivot=(0, 30, 0), rotation=(0, 0, 90))
        away.box((-1, 3, -1), (1, 10, 1), RED)
        self.assertTrue(self.problems(m, "doesn't touch"))

    def test_touching_looks_past_an_empty_joint(self):
        m = sculpt.Model("joint")
        base = m.part("base")
        base.box((-2, 0, -2), (2, 4, 2), RED)
        joint = m.part("joint", parent=base, pivot=(0, 4, 0))
        m.part("arm", parent=joint, pivot=(0, 4, 0)).box((-1, 4, -1), (1, 8, 1), RED)
        self.assertFalse(self.problems(m, "doesn't touch"))

    def test_too_many_bones_are_caught(self):
        m = sculpt.Model("many")
        root = m.part("root")
        root.box((0, 0, 0), (40, 1, 1), RED)
        for i in range(sculpt.MAX_BONES + 1):
            m.part(f"bone{i}", parent=root).box((i, 1, 0), (i + 1, 2, 1), RED)
        self.assertTrue(self.problems(m, "too many bones"))

    def test_empty_joints_dont_count_as_bones(self):
        m = creature()
        for i in range(sculpt.MAX_BONES + 2):
            m.part(f"joint{i}", parent="body")
        found = self.problems(m, "too many bones")
        self.assertFalse(found)
        self.assertTrue(self.problems(m, "does nothing"))

    def test_too_many_cubes_are_caught(self):
        with mock.patch.object(sculpt, "MAX_BONE_CUBES", 3):
            m = creature()
            self.assertTrue(self.problems(m, "over the budget"))
        with mock.patch.object(sculpt, "MAX_CUBES", 3):
            self.assertTrue(self.problems(creature(), "cubes in all"))

    def test_a_real_part_over_budget_is_caught(self):
        m = sculpt.Model("huge")
        m.part("p", loose=True).solid(lambda x, y, z: (np.floor(x) + np.floor(y) + np.floor(z)) % 4 == 0, (0, 0, 0), (30, 30, 30), RED, shade=False)
        self.assertTrue(self.problems(m, "over the budget"))

    def test_an_atlas_over_the_limit_is_caught(self):
        with mock.patch.object(sculpt, "MAX_ATLAS", 16):
            self.assertTrue(self.problems(creature(), "over the limit"))

    def test_an_oversized_model_builds_rather_than_crashing(self):
        side, _ = sculpt._pack([(600, 600)])
        self.assertEqual(side, 1024)

    def test_nothing_on_the_front_is_caught(self):
        m = sculpt.Model("blank")
        m.part("body", pivot=(0, 0, 0)).ball((0, 8, 0), 8, GREEN)
        m.animate("idle", 1, sculpt.bob("body"))
        m.animate("walk", 1, sculpt.bob("body"))
        self.assertTrue(self.problems(m, "nothing on the front"))

    def test_a_face_on_the_back_says_so(self):
        m = sculpt.Model("backwards")
        p = m.part("body")
        p.ball((0, 8, 0), 8, GREEN)
        p.decal(["kk"] * 2, {"k": "#111111"}, at=(0, 8, 0), facing="back")
        found = self.problems(m, "nothing on the front")
        self.assertTrue(found)
        self.assertIn("the back", found[0])

    def test_shading_alone_doesnt_count_as_a_face(self):
        m = sculpt.Model("shaded")
        m.part("body").ball((0, 12, 0), 12, "#808080")
        self.assertTrue(self.problems(m, "nothing on the front"))

    def test_only_the_head_has_to_have_a_face(self):
        m = sculpt.Model("patterned")
        body = m.part("body")
        body.ball((0, 8, 0), 8, sculpt.bands([RED, BLUE], along="y", width=3))
        head = m.part("head", parent=body, pivot=(0, 14, 0))
        head.ball((0, 18, 0), 5, GREEN)
        self.assertTrue(self.problems(m, "nothing on the front"))

    def test_through_the_floor_is_caught(self):
        m = creature()
        m.parts["leg_r"].box((3, -4, 0), (5, 3, 2), GREEN)
        self.assertTrue(self.problems(m, "through the floor"))

    def test_child_bones_under_a_head_are_caught(self):
        m = creature()
        m.part("ear", parent="head", pivot=(0, 18, 0)).box((0, 17, -3), (1, 20, -2), GREEN)
        self.assertTrue(self.problems(m, "inside a head bone"))

    def test_a_missing_walk_is_caught(self):
        m = sculpt.Model("still")
        m.part("p").box((0, 0, 0), (2, 2, 2), RED)
        self.assertTrue(self.problems(m, "'walk'"))

    def test_reserved_bone_names_are_caught(self):
        m = creature()
        m.part("hitbox_a", parent="body").box((0, 6, 0), (1, 7, 1), GREEN)
        self.assertTrue(self.problems(m, "special meaning"))

    def test_a_part_with_nothing_is_caught(self):
        m = creature()
        m.part("empty", parent="body")
        self.assertTrue(self.problems(m, "does nothing"))

    def test_a_clean_model_has_no_problems(self):
        self.assertEqual(sculpt.check(creature()), [])


class Animation(unittest.TestCase):
    def keys(self, doc, anim, part, channel):
        a = next(x for x in doc["animations"] if x["name"] == anim)
        uid = next(g["uuid"] for g in doc["groups"] if g["name"] == part)
        return sorted((k for k in a["animators"][uid]["keyframes"] if k["channel"] == channel), key=lambda k: k["time"])

    def model(self):
        m = sculpt.Model("anim")
        root = m.part("root", pivot=(0, 8, 0))
        root.box((-4, 0, -4), (4, 8, 4), RED)
        for name, x in (("a", 4), ("b", -5), ("c", 3), ("d", -3)):
            m.part(name, parent=root, pivot=(x, 4, 0)).box((x, 0, -1), (x + 1, 4, 1), RED)
        return m

    def run_track(self, track, length=1.0, loop="loop"):
        m = self.model()
        m.animate("x", length, track, loop=loop)
        return m.build()

    def test_swing_gives_each_limb_a_phase(self):
        track = sculpt.swing(["a", "b", "c", "d"], 30)
        self.assertAlmostEqual(track["a"]["rotation"](0.25)[0], 30)
        self.assertAlmostEqual(track["b"]["rotation"](0.25)[0], -30)
        self.assertAlmostEqual(track["c"]["rotation"](0.25)[0], 30)

    def test_swing_takes_any_gait(self):
        track = sculpt.swing({"a": 0, "b": 0.25, "c": 0.5, "d": 0.75}, 10)
        self.assertAlmostEqual(track["a"]["rotation"](0.25)[0], 10)
        self.assertAlmostEqual(track["b"]["rotation"](0.25)[0], 0, places=6)
        self.assertAlmostEqual(track["c"]["rotation"](0.25)[0], -10)

    def test_swing_can_use_another_axis(self):
        self.assertEqual(sculpt.swing("a", 30, axis="z")["a"]["rotation"](0.25), (0.0, 0.0, 30.0))

    def test_flap_beats_both_sides_together(self):
        track = sculpt.flap("a", "b", 40, skew=0)
        self.assertAlmostEqual(track["a"]["rotation"](0.25)[2], 40)
        self.assertAlmostEqual(track["b"]["rotation"](0.25)[2], -40)

    def test_flap_joints_follow_each_other(self):
        track = sculpt.flap(["a", "c"], ["b", "d"], 40, lag=0.1)
        self.assertNotEqual(track["a"]["rotation"](0.25), track["c"]["rotation"](0.25))

    def test_wave_travels_down_the_chain(self):
        track = sculpt.wave(["a", "b", "c", "d"], 10, waves=1.0)
        at = lambda name, p: track[name]["rotation"](p)[1]
        # Each joint reaches its peak a quarter of the loop after the one before it.
        peaks = [max(range(100), key=lambda i: at(name, i / 100)) for name in ("a", "b", "c", "d")]
        self.assertEqual([(b - a) % 100 for a, b in zip(peaks, peaks[1:])], [25, 25, 25])

    def test_wave_can_grow_toward_the_tip(self):
        track = sculpt.wave(["a", "b"], 10, grow=1.0, waves=0.0)
        self.assertAlmostEqual(track["b"]["rotation"](0.25)[1], 2 * track["a"]["rotation"](0.25)[1])

    def test_bob_and_its_bounce(self):
        self.assertAlmostEqual(sculpt.bob("a", 2)["a"]["position"](0.25)[1], 2)
        self.assertAlmostEqual(sculpt.bob("a", 2)["a"]["position"](0.75)[1], -2)
        self.assertAlmostEqual(sculpt.bob("a", 2, bounce=True)["a"]["position"](0.75)[1], 2)

    def test_breathe_scales(self):
        self.assertAlmostEqual(sculpt.breathe("a", 0.1)["a"]["scale"](0.25)[0], 1.1)
        self.assertEqual(sculpt.breathe("a", 0.1, axes="y")["a"]["scale"](0.25)[0], 1.0)

    def test_lunge_draws_back_thrusts_and_returns(self):
        fn = sculpt.lunge("a", (0, 0, -8), over=0.1)["a"]["position"]
        self.assertAlmostEqual(fn(0)[2], 0)
        self.assertGreater(fn(0.2)[2], 0, "drawn back first")
        self.assertAlmostEqual(fn(0.45)[2], -8.8, msg="past the target")
        self.assertAlmostEqual(fn(0.6)[2], -8, delta=0.3, msg="settled onto it")
        self.assertAlmostEqual(fn(1)[2], 0)

    def test_strike_turns_and_returns(self):
        fn = sculpt.strike("a", (-70, 0, 0), over=0)["a"]["rotation"]
        self.assertAlmostEqual(fn(0)[0], 0)
        self.assertGreater(fn(0.2)[0], 0, "wound up the other way first")
        self.assertAlmostEqual(fn(0.45)[0], -70)
        self.assertAlmostEqual(fn(1)[0], 0)

    def test_spin_turns_a_whole_number_of_times_and_loops(self):
        doc = self.run_track(sculpt.spin("a", axis="z", turns=3), length=2.0)
        keys = self.keys(doc, "x", "a", "rotation")
        self.assertEqual(len(keys), 2, "a steady turn only needs its two ends")
        self.assertAlmostEqual(keys[0]["data_points"][0]["z"], 0)
        self.assertEqual(keys[-1]["time"], 1.95, "one tick short, because the next frame is the first again")
        self.assertAlmostEqual(keys[-1]["data_points"][0]["z"], 1080 * 39 / 40)

    def test_spin_lets_one_gear_drive_another_backwards(self):
        track = sculpt.spin({"a": 1, "b": -2}, axis="x")
        self.assertAlmostEqual(track["a"]["rotation"](0.5)[0], 180)
        self.assertAlmostEqual(track["b"]["rotation"](0.5)[0], -360)

    def test_helpers_take_part_objects(self):
        m = self.model()
        m.animate("x", 1, sculpt.spin(m.parts["a"]), sculpt.swing([m.parts["b"]], 10), sculpt.bob(m.parts["c"]))
        self.assertEqual(len(m.build()["animations"]), 1)

    def test_tracks_on_one_channel_add_up(self):
        m = self.model()
        m.animate("x", 1.0, sculpt.bob("a", 1), sculpt.bob("a", 2))
        keys = self.keys(m.build(), "x", "a", "position")
        peak = max(k["data_points"][0]["y"] for k in keys)
        self.assertGreater(peak, 2.5)

    def test_scales_multiply_rather_than_add(self):
        m = self.model()
        m.animate("x", 1.0, sculpt.breathe("a", 0.1), sculpt.breathe("a", 0.1))
        keys = self.keys(m.build(), "x", "a", "scale")
        self.assertLess(max(k["data_points"][0]["x"] for k in keys), 1.3)

    def test_animating_an_unknown_part_is_refused(self):
        m = self.model()
        with self.assertRaisesRegex(ValueError, "doesn't exist"):
            m.animate("x", 1, sculpt.bob("nope"))

    def test_a_loops_last_frame_is_one_step_before_its_first(self):
        # BIL goes from the last frame straight back to the first, so a last frame equal to the first would hold for a tick.
        doc = self.run_track(sculpt.swing("a", 30), length=1.0)
        self.assertEqual(doc["animations"][0]["length"], 0.95)
        scene = bb._Scene(doc)
        times = np.arange(20) * 0.05
        rot, _, _ = scene.tracks("x", times)
        angle = rot[:, scene.bones.index(next(g["uuid"] for g in doc["groups"] if g["name"] == "a")), 0]
        steps = np.abs(np.diff(np.append(angle, angle[0])))
        self.assertLess(steps[-1], steps.max() * 1.05)
        self.assertGreater(steps[-1], 0.5, "the seam has to move like any other step")

    def test_a_one_shot_ends_on_its_last_phase(self):
        doc = self.run_track(sculpt.strike("a", (-40, 0, 0)), length=1.0, loop="once")
        self.assertEqual(doc["animations"][0]["length"], 1.0)
        keys = self.keys(doc, "x", "a", "rotation")
        self.assertAlmostEqual(keys[-1]["data_points"][0]["x"], 0)

    def test_animations_pass_the_import_check(self):
        doc = self.run_track(sculpt.lunge("a"), loop="once")
        problems = [p for p in bb.check(doc) if "no animation named" not in p]
        self.assertEqual(problems, [])
        self.assertEqual(doc["animations"][0]["loop"], "once")


class Preview(unittest.TestCase):
    def two_boxes(self, near_first):
        m = sculpt.Model("depth", shade=0)
        parts = [("near", (-4, 0, -6), (4, 8, -4), RED), ("far", (-8, 0, 0), (8, 8, 4), BLUE)]
        for name, a, b, color in (parts if near_first else parts[::-1]):
            m.part(name).box(a, b, color)
        return m.build()

    def test_depth_is_right_whichever_order_the_cubes_come(self):
        for near_first in (True, False):
            img = np.asarray(bb.render(self.two_boxes(near_first), yaw=0, pitch=0, scale=4, size=(128, 128)))
            ys, xs = np.nonzero(img[..., 3])
            cx, cy = (xs.min() + xs.max()) // 2, (ys.min() + ys.max()) // 2
            pixel = img[cy, cx]
            self.assertGreater(pixel[0], pixel[2], f"near cube should be in front, got {pixel}")
            self.assertGreater(img[cy, xs.min() + 2][2], img[cy, xs.min() + 2][0], "the far cube shows beside it")

    def test_interlocking_cubes_draw_correctly(self):
        # Painter's ordering can't get these right: each is in front of the other somewhere.
        m = sculpt.Model("cross", shade=0)
        m.part("a").box((-8, 0, -1), (8, 2, 1), RED)
        m.part("b").box((-1, 0, -8), (1, 2, 8), BLUE)
        img = np.asarray(bb.render(m.build(), yaw=45, pitch=30, scale=4, size=(160, 160)))
        reds = (img[..., 0].astype(int) > img[..., 2].astype(int) + 40).sum()
        blues = (img[..., 2].astype(int) > img[..., 0].astype(int) + 40).sum()
        self.assertGreater(reds, 50)
        self.assertGreater(blues, 50)
        self.assertLess(abs(reds - blues), max(reds, blues) * 0.3, "the cross should look the same from both arms")

    def test_the_skin_lands_on_the_right_side(self):
        m = sculpt.Model("sides", shade=0)
        p = m.part("p")
        p.box((-8, 0, -8), (8, 16, 8), BLUE)
        p.paint.box((0, 0, -8), (8, 16, -7), RED)  # the +X half of the front
        img = np.asarray(bb.render(m.build(), yaw=0, pitch=0, scale=4, size=(128, 128)))
        ys, xs = np.nonzero(img[..., 3])
        cy = (ys.min() + ys.max()) // 2
        left, right = img[cy, xs.min() + 3], img[cy, xs.max() - 3]
        self.assertGreater(left[0], left[2], "+X is on the viewer's left when looking at a face")
        self.assertGreater(right[2], right[0])

    def test_the_games_light_is_on_the_top_and_weakest_beneath(self):
        m = sculpt.Model("light", shade=0)
        m.part("p").box((-8, 0, -8), (8, 16, 8), "#c0c0c0")
        doc = m.build()
        top = np.asarray(bb.render(doc, yaw=0, pitch=89, scale=3, size=(96, 96)))
        front = np.asarray(bb.render(doc, yaw=0, pitch=0, scale=3, size=(96, 96)))
        side = np.asarray(bb.render(doc, yaw=90, pitch=0, scale=3, size=(96, 96)))
        value = lambda a: a[a[..., 3] > 0][:, 0].mean()
        self.assertGreater(value(top), value(front))
        self.assertGreater(value(front), value(side))
        self.assertAlmostEqual(value(top), 0xc0, delta=2)
        self.assertAlmostEqual(value(side), 0xc0 * 0.497, delta=3)

    def test_rest_rotation_is_drawn_and_adds_to_animation(self):
        m = sculpt.Model("posed", shade=0)
        m.part("p", pivot=(0, 0, 0), rotation=(0, 0, 90)).box((0, 0, 0), (2, 16, 2), RED)
        m.animate("x", 1.0, {"p": {"rotation": lambda t: (0, 0, 90 * 1.0)}})
        doc = m.build()
        rest = bb._pose(doc)[doc["groups"][0]["uuid"]]
        self.assertTrue(np.allclose(rest[:3, :3], bb._mat(0, 0, 90)[:3, :3]))
        moved = bb._pose(doc, "x", 0.5)[doc["groups"][0]["uuid"]]
        self.assertTrue(np.allclose(moved[:3, :3], bb._mat(0, 0, 180)[:3, :3]))
        # The bone reaches sideways, since +Y turned 90 degrees around Z goes to -X, which is on the viewer's right.
        img = np.asarray(bb.render(doc, yaw=0, pitch=0, scale=4, size=(128, 128)))
        ys, xs = np.nonzero(img[..., 3])
        self.assertGreater(np.ptp(xs), np.ptp(ys) * 3)

    def test_missing_faces_draw_as_holes_without_trouble(self):
        doc = creature().build()
        doc = json.loads(json.dumps(doc))
        for e in doc["elements"]:
            e["faces"].pop("north", None)
        self.assertTrue(bb.render(doc).getbbox())

    def test_translucent_lets_what_is_behind_show(self):
        m = sculpt.Model("glass", shade=0)
        p = m.part("p")
        p.box((-8, 0, -8), (8, 16, 8), (240, 240, 240, 90))
        p.box((-3, 5, -3), (3, 11, 3), (230, 30, 30))
        img = np.asarray(bb.render(m.build(), yaw=0, pitch=0, scale=4, size=(128, 128)))
        ys, xs = np.nonzero(img[..., 3])
        cx, cy = (xs.min() + xs.max()) // 2, (ys.min() + ys.max()) // 2
        center, edge = img[cy, cx], img[cy, xs.min() + 2]
        self.assertGreater(int(center[0]) - int(center[2]), 40, "the red block shows through")
        self.assertLess(int(edge[0]) - int(edge[2]), 20)

    def test_render_keeps_its_signature_and_default_size(self):
        img = bb.render(bb.humanoid("legacy", seed=1), None, 0.0, -35.0, 22.0, 5)
        self.assertEqual(img.size, (280, 280))
        self.assertEqual(img.mode, "RGBA")
        self.assertEqual(bb.render(bb.humanoid("legacy", seed=1), scale=4).size, (224, 224))
        self.assertEqual(bb.render(bb.humanoid("legacy", seed=1), size=(100, 60)).size, (100, 60))

    def test_a_big_model_fits_rather_than_being_cut_off(self):
        m = sculpt.Model("huge", grain=2)
        m.part("p").box((-48, 0, -24), (48, 96, 24), RED)
        img = np.asarray(bb.render(m.build(), scale=4))
        ys, xs = np.nonzero(img[..., 3])
        self.assertGreater(xs.min(), 0)
        self.assertLess(xs.max(), img.shape[1] - 1)
        self.assertGreater(ys.min(), 0)
        self.assertLess(ys.max(), img.shape[0] - 1)

    def test_fit_can_be_turned_off(self):
        m = sculpt.Model("huge", grain=2)
        m.part("p").box((-48, 0, -24), (48, 96, 24), RED)
        img = np.asarray(bb.render(m.build(), scale=4, fit=False))
        ys, xs = np.nonzero(img[..., 3])
        self.assertEqual(xs.min(), 0, "drawn at the scale asked for, so it runs off the edge")

    def test_preview_makes_a_rich_sheet(self):
        m = creature()
        m.animate("attack", 0.5, sculpt.lunge("head"), loop="once")
        img = m.preview()
        self.assertLessEqual(img.width, 1500)
        self.assertLessEqual(img.height, 1500)
        colors = np.unique(np.asarray(img.convert("RGB")).reshape(-1, 3), axis=0)
        self.assertGreater(len(colors), 50)

    def test_preview_writes_its_file(self):
        with tempfile.TemporaryDirectory() as d:
            path = pathlib.Path(d) / "sub" / "p.png"
            creature().preview(path)
            self.assertTrue(path.stat().st_size > 1000)

    def test_preview_handles_old_mobs_and_many_animations(self):
        mob = bb.quadruped("old", seed=1)
        self.assertGreater(bb.preview(mob).height, 600)
        m = creature()
        for i in range(6):
            m.animate(f"extra{i}", 1.0, sculpt.bob("body", i + 1))
        self.assertLessEqual(m.preview().height, 1500)

    def test_preview_can_focus_on_any_bone(self):
        m = creature()
        self.assertEqual(m.preview(focus="leg_r").width, m.preview().width)
        self.assertNotEqual(m.preview(focus="leg_r").tobytes(), m.preview().tobytes())

    def test_preview_copes_with_a_model_that_has_no_voxels_yet(self):
        m = sculpt.Model("empty")
        m.part("p")
        m.animate("idle", 1, sculpt.bob("p"))
        self.assertGreater(m.preview().width, 0)

    def test_glowing_models_get_a_dark_view(self):
        plain, glowing = creature(), creature()
        glowing.parts["head"].ball((0, 15, -7), 1.5, "#40ffff", glow=15)
        dark = lambda m: (np.asarray(m.preview().convert("RGB")) == (34, 38, 52)).all(axis=2).sum()
        self.assertEqual(dark(plain), 0)
        self.assertGreater(dark(glowing), 1000)

    def test_preview_takes_about_two_seconds_at_most(self):
        import time
        m = sculpt.Model("timed")
        body = m.part("body", pivot=(0, 16, 0))
        body.ball((0, 16, 0), (10, 16, 8), sculpt.spots("#b08040", "#804020", seed=1))
        head = m.part("head", parent=body, pivot=(0, 30, 0))
        head.ball((0, 38, 0), 9, "#b08040")
        m.animate("idle", 1, sculpt.bob(body))
        m.animate("walk", 1, sculpt.swing(head, 10))
        m.animate("attack", 1, sculpt.lunge(head), loop="once")
        doc = m.build()
        start = time.time()
        bb.preview(doc)
        self.assertLess(time.time() - start, 4.0, "well above the target of 2, because test machines vary")


class Readme(unittest.TestCase):
    def test_the_worked_example_runs_clean(self):
        text = (pathlib.Path(__file__).parent / "README.md").read_text(encoding="utf-8")
        script = text.split("### The loop: write a script, read the preview, fix it")[1].split("```python\n")[1].split("```")[0]
        with tempfile.TemporaryDirectory() as d, mock.patch("builtins.print") as printed:
            old = pathlib.Path.cwd()
            os.chdir(d)
            try:
                exec(compile(script, "README example", "exec"), {})
                self.assertTrue((pathlib.Path(d) / "pebble_crab.bbmodel").exists())
                self.assertTrue((pathlib.Path(d) / "pebble_crab.png").exists())
            finally:
                os.chdir(old)
        said = " ".join(str(c.args[0]) for c in printed.call_args_list)
        self.assertNotIn("PROBLEM", said)


class Timing(unittest.TestCase):
    def test_eases_go_from_nothing_to_all_of_it(self):
        for kind in sculpt.EASES:
            self.assertAlmostEqual(sculpt.ease(kind, 0.0), 0.0, places=6, msg=kind)
            self.assertAlmostEqual(sculpt.ease(kind, 1.0), 1.0, places=6, msg=kind)

    def test_eases_have_their_shapes(self):
        self.assertLess(sculpt.ease("in", 0.5), 0.5, "it starts slowly")
        self.assertGreater(sculpt.ease("out", 0.5), 0.5, "it starts quickly")
        self.assertAlmostEqual(sculpt.ease("in_out", 0.5), 0.5)
        self.assertLess(min(sculpt.ease("anticipate", i / 50) for i in range(51)), -0.02, "it backs up first")
        self.assertGreater(max(sculpt.ease("back", i / 50) for i in range(51)), 1.02, "it goes past the end")
        self.assertGreater(max(sculpt.ease("settle", i / 50) for i in range(51)), 1.02)
        bounces = [sculpt.ease("bounce", i / 100) for i in range(101)]
        self.assertGreater(sum(1 for a, b in zip(bounces, bounces[1:]) if a > b), 3, "it comes back down between bounces")

    def test_an_ease_can_be_your_own(self):
        self.assertEqual(sculpt.ease(lambda t: 0.25, 0.5), 0.25)
        with self.assertRaisesRegex(ValueError, "no ease"):
            sculpt.ease("wobbly", 0.5)

    def test_beats_pass_through_their_stops(self):
        fn = sculpt.beats((0, 0.0), (0.5, 10.0, "linear"), (1, 4.0))
        self.assertAlmostEqual(fn(0), 0)
        self.assertAlmostEqual(fn(0.25), 5)
        self.assertAlmostEqual(fn(0.5), 10)
        self.assertAlmostEqual(fn(1), 4)

    def test_beats_hold_between_equal_stops_and_outside_their_range(self):
        fn = sculpt.beats((0.2, 3.0), (0.6, 3.0), (0.8, 7.0))
        self.assertEqual(fn(0), 3.0)
        self.assertEqual(fn(0.4), 3.0)
        self.assertEqual(fn(1), 7.0)

    def test_beats_take_vectors(self):
        fn = sculpt.beats((0, (0, 0, 0)), (1, (2, 4, 6), "linear"))
        self.assertEqual(fn(0.5), (1.0, 2.0, 3.0))

    def test_beats_have_to_be_in_order(self):
        with self.assertRaisesRegex(ValueError, "in order"):
            sculpt.beats((0.5, 0.0), (0.2, 1.0))

    def test_snap_winds_up_overshoots_settles_and_goes_home(self):
        k = sculpt.snap(windup=0.3, hit=0.5, back=0.3, over=0.2)
        self.assertEqual(k(0), 0.0)
        self.assertAlmostEqual(k(0.3), -0.3)
        self.assertAlmostEqual(k(0.5), 1.2)
        self.assertAlmostEqual(k(0.6), 1.0, delta=0.01)
        self.assertEqual(k(1), 0.0)

    def test_skew_bends_time_but_keeps_the_loop(self):
        fn = sculpt.swing("a", 10, skew=0.6)["a"]["rotation"]
        self.assertAlmostEqual(fn(0)[0], fn(1)[0], places=6)
        values = [fn(i / 200)[0] for i in range(201)]
        self.assertAlmostEqual(max(values), 10, delta=0.01)
        self.assertAlmostEqual(min(values), -10, delta=0.01)
        rising = values.index(max(values))
        self.assertLess(rising, 40, "the rise is over sooner than a quarter of the cycle")

    def test_every_cyclic_helper_takes_a_phase_or_a_skew(self):
        self.assertNotEqual(sculpt.swing("a", 10, phase=0.25)["a"]["rotation"](0), sculpt.swing("a", 10)["a"]["rotation"](0))
        self.assertNotEqual(sculpt.bob("a", 1, skew=0.5)["a"]["position"](0.1), sculpt.bob("a", 1)["a"]["position"](0.1))
        self.assertNotEqual(sculpt.breathe("a", 0.1, skew=0.5)["a"]["scale"](0.1), sculpt.breathe("a", 0.1)["a"]["scale"](0.1))
        self.assertNotEqual(sculpt.wave(["a"], 10, phase=0.25)["a"]["rotation"](0), sculpt.wave(["a"], 10)["a"]["rotation"](0))

    def test_strike_and_lunge_take_any_timing(self):
        timing = sculpt.beats((0, 0.0), (0.5, 1.0), (1, 0.0))
        self.assertAlmostEqual(sculpt.strike("a", (10, 0, 0), timing=timing)["a"]["rotation"](0.5)[0], 10)
        self.assertAlmostEqual(sculpt.lunge("a", (0, 0, 4), timing=timing)["a"]["position"](0.5)[2], 4)

    def test_lag_starts_each_part_after_the_one_before(self):
        track = sculpt.strike(["a", "b"], (10, 0, 0), lag=0.1)
        self.assertEqual(track["b"]["rotation"](0.05)[0], 0.0, "not started yet")
        self.assertAlmostEqual(track["b"]["rotation"](0.55)[0], track["a"]["rotation"](0.45)[0])

    def test_move_scales_toward_a_size(self):
        fn = sculpt.move("a", scale=(2, 1, 1), timing=lambda p: 0.5)["a"]["scale"]
        self.assertEqual(fn(0.3), (1.5, 1.0, 1.0))

    def test_keyed_goes_through_chosen_poses(self):
        track = sculpt.keyed("a", rotation=[(0, (0, 0, 0)), (0.5, (30, 0, 0), "linear"), (1, (0, 0, 0))], position=[(0, (0, 1, 0)), (1, (0, 1, 0))])
        self.assertEqual(track["a"]["rotation"](0.25), (15.0, 0.0, 0.0))
        self.assertEqual(track["a"]["position"](0.25), (0.0, 1.0, 0.0))

    def test_pose_holds_for_the_whole_animation(self):
        track = sculpt.pose("a", rotation=(5, 0, 0))
        self.assertEqual(track["a"]["rotation"](0.7), (5.0, 0.0, 0.0))
        self.assertNotIn("position", track["a"])

    def test_spin_can_lurch(self):
        fn = sculpt.spin("a", axis="x", turns=2, timing=lambda p: p * p)["a"]["rotation"]
        self.assertAlmostEqual(fn(0.5)[0], 180)
        self.assertAlmostEqual(fn(1)[0], 720)

    def test_squash_keeps_the_volume(self):
        x, y, z = sculpt.squash("a", amount=-0.3, timing=lambda p: 1.0)["a"]["scale"](0.5)
        self.assertAlmostEqual(y, 0.7)
        self.assertAlmostEqual(x * y * z, 1.0)

    def test_squash_happens_at_the_moments_given_and_wraps(self):
        fn = sculpt.squash("a", amount=-0.2, at=(0.5,), width=0.2)["a"]["scale"]
        self.assertAlmostEqual(fn(0.5)[1], 0.8)
        self.assertEqual(fn(0.1)[1], 1.0)
        wrapped = sculpt.squash("a", amount=-0.2, at=(0.0,), width=0.2)["a"]["scale"]
        self.assertAlmostEqual(wrapped(0.05)[1], wrapped(1.05)[1])
        self.assertLess(wrapped(0.99)[1], 1.0, "just before the landing at the seam it has started to squash")

    def test_hop_has_a_real_arc_and_squashes_on_the_ground(self):
        track = sculpt.hop("a", height=8, air=0.5, squash=0.2)["a"]
        self.assertAlmostEqual(track["position"](0.25)[1], 8)
        self.assertEqual(track["position"](0.75)[1], 0.0)
        heights = [track["position"](i / 100)[1] for i in range(0, 50)]
        self.assertEqual(heights, sorted(heights[:25]) + sorted(heights[25:], reverse=True))
        self.assertLess(min(track["scale"](i / 100)[1] for i in range(50, 100)), 0.85)
        self.assertGreater(track["scale"](0.0)[1], 1.05, "stretched as it takes off")
        self.assertAlmostEqual(track["scale"](0)[1], track["scale"](1)[1])

    def test_flicker_is_uneven_and_loops(self):
        fn = sculpt.flicker("a", scale=0.1, rate=7, seed=3, axes="y")["a"]["scale"]
        self.assertAlmostEqual(fn(0)[1], fn(1)[1])
        self.assertEqual(fn(0.3)[0], 1.0)
        steps = np.diff([fn(i / 60)[1] for i in range(61)])
        self.assertGreater(np.std(np.abs(steps)), 0.0005)
        self.assertNotEqual(fn(0.3)[1], sculpt.flicker("a", scale=0.1, rate=7, seed=4, axes="y")["a"]["scale"](0.3)[1])

    def test_fade_brings_a_track_to_rest(self):
        track = sculpt.fade(sculpt.flicker("a", scale=0.1, rotation=5, rate=5), out=0.3, into=0.1)
        self.assertEqual(track["a"]["rotation"](1.0), (0.0, 0.0, 0.0))
        self.assertEqual(track["a"]["scale"](0.0), (1.0, 1.0, 1.0))
        self.assertNotEqual(track["a"]["rotation"](0.5), (0.0, 0.0, 0.0))

    def test_glance_darts_and_holds(self):
        fn = sculpt.glance("a", (0.3, 20, 5), (0.7, -10, 0), speed=0.05)["a"]["rotation"]
        self.assertEqual(fn(0), (0.0, 0.0, 0.0))
        self.assertEqual(fn(0.2), (0.0, 0.0, 0.0), "looking ahead until the moment comes")
        self.assertAlmostEqual(fn(0.3)[1], 20)
        self.assertAlmostEqual(fn(0.5)[1], 20, msg="holding the look")
        self.assertAlmostEqual(fn(0.7)[1], -10)
        self.assertAlmostEqual(fn(1)[1], 0)

    def test_weight_drops_after_each_landing_and_sways_toward_the_foot_down(self):
        track = sculpt.weight("a", at=(0.0, 0.5), sides=(-1, 1), drop=2, sway=1, roll=4, duty=0.5, lag=0.05)["a"]
        y = [track["position"](i / 100)[1] for i in range(100)]
        self.assertAlmostEqual(min(y), -2, delta=0.01)
        self.assertEqual(y.index(min(y)) % 50, 5, "just after each landing")
        self.assertLess(track["position"](0.25)[0], 0, "over the left foot, which landed first")
        self.assertGreater(track["position"](0.75)[0], 0, "over the right")
        self.assertGreater(track["rotation"](0.25)[2], 0, "tilted over it too")
        self.assertAlmostEqual(track["position"](0)[0], track["position"](1)[0])


def walker(legs_at, **gait_options):
    """A box on any number of one-part legs, walking."""
    m = sculpt.Model("walker")
    body = m.part("body", pivot=(0, 10, 0))
    xs = [abs(x) for x, _ in legs_at] + [4]
    zs = [abs(z) for _, z in legs_at] + [4]
    body.box((-max(xs) - 2, 8, -max(zs) - 2), (max(xs) + 2, 14, max(zs) + 2), GREEN)
    body.decal(["kk"], {"k": "#111111"}, at=(0, 11, 0))
    names = []
    for i, (x, z) in enumerate(legs_at):
        leg = m.part(f"leg{i}", parent=body, pivot=(x, 9, z))
        leg.box((x - 1, 0, z - 1), (x + 1, 9, z + 1), GREEN)
        names.append(leg.name)
    options = dict(stride=4, lift=3, body=body)
    options.update(gait_options)
    m.animate("walk", 1.0, sculpt.gait(names, **options))
    m.animate("idle", 1.0, sculpt.bob(body, 0.3), sculpt.plant(names))
    return m, names


def feet_of(m):
    doc = m.build()
    motion = bb._Motion(doc, None, m._feet())
    walk = next(a for a in doc["animations"] if a["name"] == "walk")
    return motion, motion.foot_paths(walk)


class Gaits(unittest.TestCase):
    def phases(self, legs_at, pattern="walk"):
        described = [{"name": f"leg{i}", "x": x, "z": z} for i, (x, z) in enumerate(legs_at)]
        return sculpt._gait_phases(described, pattern)

    def test_any_number_of_legs_lands_evenly_in_a_walk(self):
        for count, legs in ((1, [(0, 0)]), (2, [(3, 0), (-3, 0)]), (3, [(3, 0), (-3, -4), (-3, 4)]), (4, [(3, -4), (-3, -4), (3, 4), (-3, 4)]),
                            (5, [(3, -4), (-3, -4), (3, 4), (-3, 4), (3, 0)]), (6, [(3, z) for z in (-4, 0, 4)] + [(-3, z) for z in (-4, 0, 4)]),
                            (8, [(3, z) for z in (-6, -2, 2, 6)] + [(-3, z) for z in (-6, -2, 2, 6)])):
            got = sorted(self.phases(legs))
            self.assertEqual(len(got), count)
            self.assertEqual(got, [i / count for i in range(count)], f"{count} legs")

    def test_a_four_legged_walk_is_the_one_animals_use(self):
        lf, lh, rf, rh = self.phases([(-3, -4), (-3, 4), (3, -4), (3, 4)])
        self.assertEqual((lh, lf, rh, rf), (0.0, 0.25, 0.5, 0.75), "back left, front left, back right, front right")

    def test_a_trot_moves_diagonal_pairs_and_an_ants_tripod(self):
        lf, lh, rf, rh = self.phases([(-3, -4), (-3, 4), (3, -4), (3, 4)], "trot")
        self.assertEqual(lf, rh)
        self.assertEqual(lh, rf)
        self.assertNotEqual(lf, lh)
        l1, l2, l3, r1, r2, r3 = self.phases([(-3, z) for z in (-4, 0, 4)] + [(3, z) for z in (-4, 0, 4)], "trot")
        self.assertEqual({l1, l3, r2}, {0.0})
        self.assertEqual({r1, r3, l2}, {0.5})

    def test_a_bound_moves_the_front_then_the_back(self):
        lf, lh, rf, rh = self.phases([(-3, -4), (-3, 4), (3, -4), (3, 4)], "bound")
        self.assertAlmostEqual(lf, rf, delta=0.05)
        self.assertAlmostEqual(lh, rh, delta=0.05)
        self.assertAlmostEqual(abs(lf - lh), 0.5, delta=0.05)

    def test_you_can_write_your_own_order(self):
        self.assertEqual(self.phases([(3, 0), (-3, 0)], {"leg0": 0.1, "leg1": 0.2}), [0.1, 0.2])

    def test_an_unknown_pattern_is_refused(self):
        m, names = walker([(3, 0), (-3, 0)], pattern="moonwalk")
        with self.assertRaisesRegex(ValueError, "pattern must be"):
            m.build()

    def test_feet_plant_on_the_ground_and_go_back_at_a_steady_speed(self):
        for legs in ([(3, 0), (-3, 0)], [(3, -4), (-3, -4), (3, 4), (-3, 4)], [(3, z) for z in (-4, 0, 4)] + [(-3, z) for z in (-4, 0, 4)]):
            m, names = walker(legs)
            motion, feet = feet_of(m)
            for name, foot in feet.items():
                self.assertGreater(foot["lift"], 1.5, f"{name} should lift")
                self.assertFalse(foot["contact"].all(), f"{name} should leave the ground")
                self.assertTrue(foot["contact"].any(), f"{name} should touch it")
                self.assertLess(foot["slide"], 0.5, f"{name} shouldn't slide")
                self.assertGreater(foot["velocity"][1], 0, "a planted foot goes back relative to the body")
                self.assertGreaterEqual(foot["low"].min(), -0.3, f"{name} shouldn't sink")
            self.assertEqual(sculpt.check(m, machine=True), [])

    def test_each_foot_spends_its_duty_on_the_ground(self):
        m, names = walker([(3, 0), (-3, 0)], duty=0.7)
        motion, feet = feet_of(m)
        for foot in feet.values():
            self.assertAlmostEqual(foot["contact"].mean(), 0.7, delta=0.1)

    def test_a_longer_stride_means_a_faster_ground_speed(self):
        slow, _ = walker([(3, 0), (-3, 0)], stride=3)
        fast, _ = walker([(3, 0), (-3, 0)], stride=6)
        self.assertGreater(sculpt.stats(fast)["walk_speed"], sculpt.stats(slow)["walk_speed"] * 1.7)

    def test_heading_walks_it_sideways(self):
        m, names = walker([(3, 0), (-3, 0)], heading=(1, 0))
        motion, feet = feet_of(m)
        for foot in feet.values():
            self.assertLess(foot["velocity"][0], -1, "feet go past the other way")
            self.assertAlmostEqual(foot["velocity"][1], 0, delta=0.1)

    def test_the_body_takes_the_weight(self):
        m, names = walker([(3, 0), (-3, 0)], drop=1.0)
        doc = m.build()
        scene = bb._Scene(doc)
        walk_pos = scene.tracks("walk", np.arange(20) * 0.05)[1][:, scene.bones.index(next(g["uuid"] for g in doc["groups"] if g["name"] == "body"))]
        self.assertGreater(np.ptp(walk_pos[:, 1]), 0.8)

    def two_part(self):
        m = sculpt.Model("kneed")
        body = m.part("body", pivot=(0, 18, 0))
        body.box((-5, 16, -4), (5, 24, 4), GREEN)
        body.decal(["kk"], {"k": "#111111"}, at=(0, 20, 0))
        thigh = m.part("thigh_r", parent=body, pivot=(3, 16, 0))
        thigh.box((2, 8, -1), (4, 16, 1), GREEN)
        shin = m.part("shin_r", parent=thigh, pivot=(3, 8, 0))
        shin.box((2, 0, -1), (4, 8, 1), GREEN)
        m.mirror(thigh)
        return m

    def test_a_two_part_leg_bends_at_the_knee_and_keeps_its_foot_planted(self):
        m = self.two_part()
        legs = [["thigh_r", "shin_r"], ["thigh_l", "shin_l"]]
        m.animate("walk", 1.0, sculpt.gait(legs, stride=6, lift=3, knee="front", crouch=0.1, body="body"))
        doc = m.build()
        scene = bb._Scene(doc)
        rot, pos, _ = scene.tracks("walk", np.arange(20) * 0.05)
        shin = scene.bones.index(next(g["uuid"] for g in doc["groups"] if g["name"] == "shin_r"))
        thigh = scene.bones.index(next(g["uuid"] for g in doc["groups"] if g["name"] == "thigh_r"))
        self.assertLess(rot[:, shin, 0].max(), 1.0, "a forward knee only ever bends one way, which folds the shin back")
        self.assertLess(rot[:, shin, 0].min(), -20)
        self.assertGreater(np.ptp(rot[:, thigh, 0]), 20)
        self.assertLess(np.abs(pos[:, thigh]).max(), 0.01, "a jointed leg doesn't need to slide in its socket")
        motion, feet = feet_of(m)
        for foot in feet.values():
            self.assertLess(foot["slide"], 1.0)
            self.assertGreater(foot["lift"], 1.5)

    def test_a_backward_knee_bends_the_other_way(self):
        m = self.two_part()
        m.animate("walk", 1.0, sculpt.gait([["thigh_r", "shin_r"], ["thigh_l", "shin_l"]], stride=6, lift=3, knee="back", crouch=0.1, body="body"))
        doc = m.build()
        scene = bb._Scene(doc)
        rot, _, _ = scene.tracks("walk", np.arange(20) * 0.05)
        shin = scene.bones.index(next(g["uuid"] for g in doc["groups"] if g["name"] == "shin_r"))
        self.assertGreater(rot[:, shin, 0].max(), 20)

    def three_part(self):
        m = sculpt.Model("footed")
        body = m.part("body", pivot=(0, 20, 0))
        body.box((-5, 18, -4), (5, 26, 4), GREEN)
        thigh = m.part("thigh_r", parent=body, pivot=(3, 18, 0))
        thigh.box((2, 10, -1), (4, 18, 1), GREEN)
        shin = m.part("shin_r", parent=thigh, pivot=(3, 10, 0))
        shin.box((2, 2, -1), (4, 10, 1), GREEN)
        foot = m.part("foot_r", parent=shin, pivot=(3, 2, 0))
        foot.box((1, 0, -5), (5, 2, 2), GREEN)
        m.mirror(thigh)
        return m, [["thigh_r", "shin_r", "foot_r"], ["thigh_l", "shin_l", "foot_l"]]

    def test_a_separate_foot_stays_level_on_the_ground(self):
        m, legs = self.three_part()
        m.animate("walk", 1.0, sculpt.gait(legs, stride=7, lift=3, crouch=0.1, knee="front", body="body", peel=0))
        doc = m.build()
        scene = bb._Scene(doc)
        matrices = scene.series("walk", np.arange(20) * 0.05)
        foot = scene.bones.index(next(g["uuid"] for g in doc["groups"] if g["name"] == "foot_r"))
        self.assertLess(np.abs(matrices[:, foot, :3, :3] - np.eye(3)).max(), 0.02, "level the whole way, whatever the leg does")

    def test_a_foot_points_its_toe_down_in_the_air(self):
        m, legs = self.three_part()
        m.animate("walk", 1.0, sculpt.gait(legs, stride=7, lift=3, crouch=0.1, knee="front", body="body", peel=30))
        doc = m.build()
        scene = bb._Scene(doc)
        matrices = scene.series("walk", np.arange(20) * 0.05)
        foot = scene.bones.index(next(g["uuid"] for g in doc["groups"] if g["name"] == "foot_r"))
        self.assertGreater(np.abs(matrices[:, foot, :3, :3] - np.eye(3)).max(), 0.3)

    def test_level_makes_two_parts_a_rigid_leg_on_a_foot(self):
        m = sculpt.Model("stubby")
        body = m.part("body", pivot=(0, 12, 0))
        body.box((-5, 10, -4), (5, 18, 4), GREEN)
        leg = m.part("leg_r", parent=body, pivot=(3, 10, 0))
        leg.box((2, 2, -1), (4, 10, 1), GREEN)
        foot = m.part("foot_r", parent=leg, pivot=(3, 2, 0))
        foot.box((1, 0, -5), (5, 2, 2), GREEN)
        m.mirror(leg)
        m.animate("walk", 1.0, sculpt.gait([["leg_r", "foot_r"], ["leg_l", "foot_l"]], level=True, stride=6, lift=3, peel=0))
        doc = m.build()
        scene = bb._Scene(doc)
        matrices = scene.series("walk", np.arange(20) * 0.05)
        b = scene.bones.index(next(g["uuid"] for g in doc["groups"] if g["name"] == "foot_r"))
        self.assertLess(np.abs(matrices[:, b, :3, :3] - np.eye(3)).max(), 0.02)
        motion, feet = feet_of(m)
        self.assertLess(feet["foot_r"]["slide"], 0.3)

    def test_a_leg_with_no_voxels_at_its_end_is_explained(self):
        m = sculpt.Model("nothing")
        m.part("body").box((-2, 4, -2), (2, 8, 2), GREEN)
        m.part("leg", parent="body", pivot=(0, 4, 0))
        m.animate("walk", 1.0, sculpt.gait(["leg"]))
        with self.assertRaisesRegex(ValueError, "no voxels to stand on"):
            m.build()

    def test_arms_swing_against_the_opposite_leg(self):
        m = sculpt.Model("armed")
        body = m.part("body", pivot=(0, 10, 0))
        body.box((-4, 8, -3), (4, 20, 3), GREEN)
        for side, x in (("r", 3), ("l", -3)):
            m.part(f"leg_{side}", parent=body, pivot=(x, 9, 0)).box((x - 1, 0, -1), (x + 1, 9, 1), GREEN)
            m.part(f"arm_{side}", parent=body, pivot=(x * 2, 18, 0)).box((x * 2 - 1, 10, -1), (x * 2 + 1, 18, 1), GREEN)
        m.animate("walk", 1.0, sculpt.gait(["leg_r", "leg_l"], stride=4, lift=2, body=body, arms=["arm_r", "arm_l"], arm_swing=20))
        doc = m.build()
        scene = bb._Scene(doc)
        rot = scene.tracks("walk", np.arange(20) * 0.05)[0]
        arm_r = rot[:, scene.bones.index(next(g["uuid"] for g in doc["groups"] if g["name"] == "arm_r")), 0]
        # The left foot lands first, at phase 0, and that's when the right arm is furthest forward.
        self.assertEqual(int(np.argmax(arm_r)), 0)
        self.assertAlmostEqual(arm_r.max(), 20, delta=1)

    def test_shoulders_turn_against_the_hips(self):
        m = sculpt.Model("twisty")
        hips = m.part("hips", pivot=(0, 10, 0))
        hips.box((-4, 8, -3), (4, 12, 3), GREEN)
        chest = m.part("chest", parent=hips, pivot=(0, 12, 0))
        chest.box((-4, 12, -3), (4, 20, 3), GREEN)
        for side, x in (("r", 3), ("l", -3)):
            m.part(f"leg_{side}", parent=hips, pivot=(x, 9, 0)).box((x - 1, 0, -1), (x + 1, 9, 1), GREEN)
        m.animate("walk", 1.0, sculpt.gait(["leg_r", "leg_l"], stride=4, lift=2, body=hips, twist=6, shoulders=chest))
        doc = m.build()
        scene = bb._Scene(doc)
        rot = scene.tracks("walk", np.arange(20) * 0.05)[0]
        ids = {g["name"]: scene.bones.index(g["uuid"]) for g in doc["groups"]}
        self.assertLess(np.corrcoef(rot[:, ids["hips"], 1], rot[:, ids["chest"], 1])[0, 1], -0.9)
        self.assertGreater(np.ptp(rot[:, ids["chest"], 1]), np.ptp(rot[:, ids["hips"], 1]), "more of it, since it starts from the hips")

    def test_plant_keeps_feet_exactly_where_they_are_while_the_body_moves(self):
        m, names = walker([(3, 0), (-3, 0)])
        m.animate("attack", 1.0, sculpt.lunge("body", (0, -1.5, -3), over=0), sculpt.plant(names), loop="once")
        doc = m.build()
        motion = bb._Motion(doc, None, m._feet())
        attack = next(a for a in doc["animations"] if a["name"] == "attack")
        for foot in motion.foot_paths(attack).values():
            self.assertLess(np.ptp(foot["path"][:, 2]), 0.1)
            self.assertLess(np.ptp(foot["path"][:, 1]), 0.3)

    def test_plant_bends_knees_when_the_body_dips(self):
        m = self.two_part()
        legs = [["thigh_r", "shin_r"], ["thigh_l", "shin_l"]]
        m.animate("idle", 1.0, sculpt.bob("body", 2), sculpt.plant(legs, knee="front"))
        doc = m.build()
        scene = bb._Scene(doc)
        rot = scene.tracks("idle", np.arange(20) * 0.05)[0]
        shin = scene.bones.index(next(g["uuid"] for g in doc["groups"] if g["name"] == "shin_r"))
        self.assertGreater(np.ptp(rot[:, shin, 0]), 20)

    def test_a_leg_at_rest_is_exactly_at_rest(self):
        m, legs = self.three_part()
        m.animate("idle", 1.0, sculpt.plant(legs))
        doc = m.build()
        idle = next(a for a in doc["animations"] if a["name"] == "idle")
        self.assertEqual(idle["animators"], {}, "with nothing moving there's nothing to write")


class FollowThrough(unittest.TestCase):
    def tailed(self):
        m = sculpt.Model("tailed")
        body = m.part("body", pivot=(0, 10, 0))
        body.box((-4, 6, -4), (4, 14, 4), GREEN)
        tail = m.part("tail", parent=body, pivot=(0, 10, 4))
        tail.box((-1, 9, 4), (1, 11, 12), GREEN)
        tip = m.part("tail_tip", parent=tail, pivot=(0, 10, 12))
        tip.box((-1, 9, 12), (1, 11, 20), GREEN)
        return m

    def angles(self, m, anim, part, axis):
        doc = m.build()
        scene = bb._Scene(doc)
        a = next(x for x in doc["animations"] if x["name"] == anim)
        frames = int(round(a["length"] / 0.05)) + 1
        rot = scene.tracks(anim, np.arange(frames) * 0.05)[0]
        return rot[:, scene.bones.index(next(g["uuid"] for g in doc["groups"] if g["name"] == part)), axis]

    def test_it_lags_behind_what_carries_it(self):
        def lag(stiffness):
            m = self.tailed()
            m.animate("x", 1.0, sculpt.swing("body", 20, axis="y"), sculpt.follow("tail", stiffness=stiffness, damping=0.3))
            carried = self.angles(m, "x", "body", 1)
            follows = self.angles(m, "x", "tail", 1)
            self.assertGreater(np.ptp(follows), 2)
            # The direction the tail points peaks later than the direction of the body it hangs from.
            return (int(np.argmax(carried + follows)) - int(np.argmax(carried))) % 20
        self.assertGreater(lag(1.0), 0)
        self.assertGreater(lag(1.0), lag(3.0), "a floppier one lags further")

    def test_a_loop_of_it_is_exactly_periodic(self):
        m = self.tailed()
        m.animate("x", 1.0, sculpt.bob("body", 2, cycles=2), sculpt.swing("body", 10, axis="y"), sculpt.follow(["tail", "tail_tip"], stiffness=2))
        for part in ("tail", "tail_tip"):
            for axis in (0, 1):
                values = self.angles(m, "x", part, axis)
                steps = np.abs(np.diff(values))
                self.assertLess(abs(values[0] - values[-1]), max(steps.max() * 1.2, 0.5), f"{part} {axis}")

    def test_it_answers_to_the_motion_of_its_carrier_not_to_a_fixed_rule(self):
        small, large = self.tailed(), self.tailed()
        small.animate("x", 1.0, sculpt.swing("body", 6, axis="y"), sculpt.follow("tail"))
        large.animate("x", 1.0, sculpt.swing("body", 24, axis="y"), sculpt.follow("tail", limit=200))
        self.assertAlmostEqual(np.ptp(self.angles(large, "x", "tail", 1)) / np.ptp(self.angles(small, "x", "tail", 1)), 4.0, delta=0.3)

    def test_a_still_carrier_moves_nothing(self):
        m = self.tailed()
        m.animate("x", 1.0, sculpt.follow(["tail", "tail_tip"]))
        doc = m.build()
        self.assertEqual(doc["animations"][0]["animators"], {})

    def test_it_keeps_moving_after_the_carrier_stops(self):
        m = self.tailed()
        m.animate("x", 2.0, sculpt.keyed("body", rotation=[(0, (0, 0, 0)), (0.2, (0, 30, 0), "in_out"), (1, (0, 30, 0), "linear")]),
                  sculpt.follow("tail", stiffness=2, damping=0.2, limit=90), loop="hold")
        after = self.angles(m, "x", "tail", 1)[9:30]
        self.assertGreater(np.ptp(after), 3, "the body stopped at 0.4 seconds, and the tail is still going")

    def test_a_one_shot_ends_at_rest(self):
        m = self.tailed()
        m.animate("x", 1.0, sculpt.strike("body", (0, 30, 0)), sculpt.follow(["tail", "tail_tip"], stiffness=2), loop="once")
        self.assertAlmostEqual(self.angles(m, "x", "tail", 1)[-1], 0, delta=0.5)

    def test_a_chain_passes_it_down(self):
        m = self.tailed()
        m.animate("x", 1.0, sculpt.swing("body", 15, axis="y", cycles=2), sculpt.follow(["tail", "tail_tip"], stiffness=3, damping=0.25))
        self.assertGreater(np.ptp(self.angles(m, "x", "tail_tip", 1)), 1)
        self.assertFalse(np.allclose(self.angles(m, "x", "tail", 1), self.angles(m, "x", "tail_tip", 1), atol=0.5))

    def test_the_limit_holds(self):
        m = self.tailed()
        m.animate("x", 0.5, sculpt.swing("body", 40, axis="y"), sculpt.follow("tail", limit=9, stiffness=2, damping=0.1))
        self.assertLessEqual(np.abs(self.angles(m, "x", "tail", 1)).max(), 9.01)

    def test_it_doesnt_twist_around_its_own_length(self):
        m = self.tailed()
        m.animate("x", 1.0, sculpt.swing("body", 20, axis="z"), sculpt.swing("body", 20, axis="y"), sculpt.follow("tail"))
        self.assertLess(np.abs(self.angles(m, "x", "tail", 2)).max(), 0.01, "the tail lies along Z")


class SteadyHead(unittest.TestCase):
    def model(self):
        m = sculpt.Model("steady")
        body = m.part("body", pivot=(0, 8, 0))
        body.box((-4, 4, -4), (4, 12, 4), GREEN)
        head = m.part("head", parent=body, pivot=(0, 12, -2))
        head.box((-3, 12, -5), (3, 18, 1), GREEN)
        return m

    def test_it_takes_out_most_of_what_the_body_does(self):
        loose, held = self.model(), self.model()
        motion = [sculpt.swing("body", 12, axis="z"), sculpt.bob("body", 2)]
        loose.animate("x", 1.0, *motion, sculpt.swing("head", 0.01))
        held.animate("x", 1.0, *motion, sculpt.steady("head", amount=0.8, level=0.6))
        measure = {}
        for name, m in (("loose", loose), ("held", held)):
            doc = m.build()
            scene = bb._Scene(doc)
            world = scene.series("x", np.arange(20) * 0.05)[:, scene.bones.index(next(g["uuid"] for g in doc["groups"] if g["name"] == "head"))]
            measure[name] = (np.arctan2(world[:, 1, 0], world[:, 0, 0]), world[:, 1, 3])
        self.assertLess(np.ptp(measure["held"][0]), np.ptp(measure["loose"][0]) * 0.35, "it turns less")
        self.assertLess(np.ptp(measure["held"][1]), np.ptp(measure["loose"][1]) * 0.6, "and it bobs less")


class HurtAndDeath(unittest.TestCase):
    def test_a_flinch_hits_at_once_and_recovers(self):
        fn = sculpt.flinch("a", move=(0, 0, 4), degrees=(10, 0, 0), hit=0.14)["a"]
        self.assertEqual(fn["position"](0), (0.0, 0.0, 0.0))
        self.assertAlmostEqual(fn["position"](0.14)[2], 4)
        self.assertAlmostEqual(fn["rotation"](0.14)[0], 10)
        self.assertAlmostEqual(fn["position"](1)[2], 0)
        path = [fn["position"](i / 50)[2] for i in range(51)]
        self.assertLess(min(path), -0.02, "it wobbles back through rest")

    def test_in_a_list_each_part_reacts_just_after(self):
        track = sculpt.flinch(["a", "b"], degrees=(10, 0, 0), lag=0.05)
        self.assertEqual(track["b"]["rotation"](0.04)[0], 0.0)
        self.assertGreater(track["a"]["rotation"](0.04)[0], 0)

    def body(self):
        m = sculpt.Model("faller")
        body = m.part("body", pivot=(0, 16, 0))
        body.box((-5, 8, -3), (5, 24, 3), GREEN)
        leg = m.part("leg_r", parent=body, pivot=(3, 8, 0))
        leg.box((2, 0, -1), (4, 8, 1), GREEN)
        m.mirror(leg)
        return m

    def low_points(self, m, name="death"):
        doc = m.build()
        motion = bb._Motion(doc)
        a = next(x for x in doc["animations"] if x["name"] == name)
        times, matrices = motion.frames(a)
        return np.array([min(motion._world(matrices[k], n)[:, 1].min() for n in motion.corners) for k in range(len(times))]), doc, motion, a

    def test_collapse_ends_lying_down_on_the_floor(self):
        m = self.body()
        m.animate("death", 2.0, sculpt.collapse("body", direction="forward", degrees=85), loop="hold")
        low, doc, motion, a = self.low_points(m)
        self.assertGreater(low.min(), -1.0, "never through the floor")
        self.assertAlmostEqual(low[-1], 0, delta=1.5, msg="and down on it at the end")
        times, matrices = motion.frames(a)
        up = matrices[-1, motion.index["body"], :3, 1]
        self.assertLess(up[1], 0.2, "lying down")
        self.assertLess(up[2], -0.8, "with its top toward the front, since it fell forward")

    def test_each_direction_falls_that_way(self):
        for direction, axis, sign in (("forward", 2, -1), ("back", 2, 1), ("left", 0, -1), ("right", 0, 1)):
            m = self.body()
            m.animate("death", 1.0, sculpt.collapse("body", direction=direction, degrees=80), loop="hold")
            _, doc, motion, a = self.low_points(m)
            up = motion.frames(a)[1][-1, motion.index["body"], :3, 1]
            self.assertGreater(sign * up[axis], 0.8, direction)

    def test_collapse_goes_faster_and_rebounds(self):
        k = sculpt.collapse("a", fall=0.5, bounce=0.1).timing()
        self.assertEqual(k(0), 0.0)
        self.assertEqual(k(0.5), 1.0)
        self.assertLess(k(0.57), 1.0, "it comes back up a little off the ground")
        self.assertEqual(k(1), 1.0)
        self.assertLess(k(0.45) - k(0.4), k(0.5) - k(0.45), "and it accelerates into the fall")

    def test_limbs_go_slack_and_stay_there(self):
        m = self.body()
        m.animate("death", 2.0, sculpt.collapse("body", degrees=85, limbs={"leg_r": (40, 0, 0)}), loop="hold")
        doc = m.build()
        scene = bb._Scene(doc)
        rot = scene.tracks("death", np.arange(41) * 0.05)[0][:, scene.bones.index(next(g["uuid"] for g in doc["groups"] if g["name"] == "leg_r")), 0]
        self.assertAlmostEqual(rot[-1], 40, delta=1)
        self.assertGreater(rot.max(), 42, "with a flop past it on impact")
        self.assertAlmostEqual(rot[0], 0)

    def test_a_death_holds_its_last_frame_in_the_file(self):
        m = self.body()
        m.animate("death", 2.0, sculpt.collapse("body"), loop="hold")
        a = next(x for x in m.build()["animations"] if x["name"] == "death")
        self.assertEqual(a["loop"], "hold")
        self.assertEqual(a["length"], 2.0)


class Keyframes(unittest.TestCase):
    def model(self):
        m = sculpt.Model("keys")
        m.part("a", pivot=(0, 4, 0)).box((-2, 0, -2), (2, 8, 2), GREEN)
        return m

    def keys(self, m, name="x"):
        a = next(x for x in m.build()["animations"] if x["name"] == name)
        return [k for animator in a["animators"].values() for k in animator["keyframes"]]

    def test_a_channel_that_doesnt_move_costs_nothing(self):
        m = self.model()
        m.animate("x", 1.0, {"a": {"rotation": lambda p: (0, 0, 0), "scale": lambda p: (1, 1, 1)}})
        self.assertEqual(self.keys(m), [])

    def test_a_straight_run_takes_two_keys(self):
        m = self.model()
        m.animate("x", 2.0, {"a": {"position": lambda p: (0, 10 * p, 0)}}, loop="once")
        self.assertEqual(len(self.keys(m)), 2)

    def test_a_hold_and_a_snap_keep_only_their_corners(self):
        m = self.model()
        fn = sculpt.beats((0, 0.0), (0.5, 0.0, "linear"), (0.55, 10.0, "linear"), (1, 10.0, "linear"))
        m.animate("x", 2.0, {"a": {"position": lambda p: (0, fn(p), 0)}}, loop="once")
        self.assertLessEqual(len(self.keys(m)), 4)

    def test_keys_stay_within_tolerance_of_the_curve(self):
        m = self.model()
        fn = lambda p: (20 * math.sin(2 * math.pi * p) + 7 * math.sin(6 * math.pi * p), 0, 0)
        m.animate("x", 2.0, {"a": {"rotation": fn}})
        doc = m.build()
        scene = bb._Scene(doc)
        rot = scene.tracks("x", np.arange(40) * 0.05)[0][:, 0, 0]
        want = np.array([fn(k / 40)[0] for k in range(40)])
        self.assertLess(np.abs(rot - want).max(), bb._KEY_TOLERANCE["rotation"] + 0.01)
        self.assertLess(len(self.keys(m)), 40, "and it's fewer than one for every frame")

    def test_keyframes_go_without_the_fields_bil_doesnt_read(self):
        m = self.model()
        m.animate("x", 1.0, sculpt.swing("a", 10))
        for k in self.keys(m):
            self.assertEqual(set(k), {"channel", "data_points", "time", "interpolation"})
            self.assertEqual(k["interpolation"], "linear")
            self.assertEqual(set(k["data_points"][0]), set("xyz"))

    def test_time_goes_in_whole_ticks(self):
        m = self.model()
        m.animate("x", 0.73, sculpt.swing("a", 10), loop="once")
        for k in self.keys(m):
            self.assertAlmostEqual(k["time"] * 20, round(k["time"] * 20))
        self.assertEqual(next(a for a in m.build()["animations"] if a["name"] == "x")["length"], 0.75)

    def test_samples_still_ask_for_the_old_way(self):
        m = self.model()
        m.animate("x", 1.0, sculpt.swing("a", 10), samples=4)
        self.assertEqual(len(self.keys(m)), 5)
        self.assertIn("uuid", self.keys(m)[0])

    def test_the_file_still_passes_the_import_check(self):
        m = creature()
        self.assertEqual(bb.check(m.build()), [])

    def test_everything_is_a_plain_number(self):
        m = creature()
        json.dumps(m.build())
        for a in m.build()["animations"]:
            for animator in a["animators"].values():
                for k in animator["keyframes"]:
                    self.assertTrue(all(isinstance(k["data_points"][0][v], (int, float)) for v in "xyz"))


class MotionNotes(unittest.TestCase):
    def notes(self, m, machine=False):
        return bb.motion_notes(m.build(), m._feet() if isinstance(m, sculpt.Model) else None, m._still(), machine)

    def standing(self):
        m = sculpt.Model("standing")
        body = m.part("body", pivot=(0, 10, 0))
        body.box((-4, 8, -3), (4, 16, 3), GREEN)
        for side, x in (("r", 3), ("l", -3)):
            m.part(f"leg_{side}", parent=body, pivot=(x, 8, 0)).box((x - 1, 0, -1), (x + 1, 8, 1), GREEN)
        m.animate("idle", 1.0, sculpt.bob(body, 0.4), sculpt.plant(LEGS))
        return m

    def test_a_good_walk_has_nothing_said_about_it(self):
        m = self.standing()
        m.animate("walk", 1.0, sculpt.gait(LEGS, stride=4, lift=2, body="body"))
        self.assertEqual(self.notes(m), [])

    def test_a_pendulum_walk_is_called_out(self):
        m = self.standing()
        m.animate("walk", 1.0, sculpt.swing(LEGS, 25), sculpt.bob("body", 0.3))
        said = " ".join(self.notes(m))
        self.assertTrue("slides" in said or "never lifts" in said, said)

    def test_feet_through_the_floor_are_called_out(self):
        m = self.standing()
        m.animate("walk", 1.0, sculpt.gait(LEGS, stride=4, lift=2, body="body"), sculpt.pose("body", position=(0, -4, 0)))
        self.assertEqual(self.notes(m), [], "a gait follows the body down")
        m.animate("walk", 1.0, sculpt.swing(LEGS, 25), sculpt.pose("body", position=(0, -4, 0)))
        self.assertTrue(any("through the floor" in n for n in self.notes(m)))

    def test_a_walk_with_a_dead_body_is_called_out(self):
        m = self.standing()
        m.animate("walk", 1.0, sculpt.gait(LEGS, stride=4, lift=2))
        self.assertTrue(any("doesn't move at all" in n for n in self.notes(m)))

    def test_a_part_that_never_moves_is_called_out(self):
        m = self.standing()
        m.part("fin", parent="body", pivot=(0, 16, 0)).box((-1, 16, -1), (1, 20, 1), GREEN)
        m.animate("walk", 1.0, sculpt.gait(LEGS, stride=4, lift=2, body="body"))
        self.assertTrue(any("'fin' never moves" in n and "limb" in n for n in self.notes(m)))

    def test_a_part_with_children_that_never_moves_says_so(self):
        m = sculpt.Model("carrier")
        root = m.part("root", pivot=(0, 4, 0))
        root.box((-2, 0, -2), (2, 8, 2), GREEN)
        arm = m.part("arm", parent=root, pivot=(0, 8, 0))
        arm.box((-1, 8, -1), (1, 12, 1), GREEN)
        m.animate("idle", 1.0, sculpt.swing(arm, 5))
        self.assertTrue(any("'root' never moves" in n and "hanging off" in n for n in self.notes(m)))

    def test_still_says_its_meant_to(self):
        m = self.standing()
        m.part("fin", parent="body", pivot=(0, 16, 0), still=True).box((-1, 16, -1), (1, 20, 1), GREEN)
        m.animate("walk", 1.0, sculpt.gait(LEGS, stride=4, lift=2, body="body"))
        self.assertEqual(self.notes(m), [])

    def test_a_machines_frame_can_stand_still(self):
        m = sculpt.Model("machine")
        frame = m.part("frame", pivot=(0, 0, 0))
        frame.box((-8, 0, -8), (8, 4, 8), GREEN)
        wheel = m.part("wheel", parent=frame, pivot=(0, 8, 0))
        wheel.box((-4, 4, -1), (4, 12, 1), GREEN)
        m.animate("idle", 1.0, sculpt.spin(wheel, axis="z"))
        self.assertEqual(self.notes(m, machine=True), [])
        self.assertTrue(any("'frame' never moves" in n for n in self.notes(m)))

    def test_a_loop_that_doesnt_meet_itself_is_called_out(self):
        m = self.standing()
        m.animate("walk", 1.0, sculpt.gait(LEGS, stride=4, lift=2, body="body"), {"body": {"rotation": lambda p: (0, 40 * p, 0)}})
        self.assertTrue(any("doesn't meet its first" in n for n in self.notes(m)))

    def test_a_spin_meets_itself_across_the_turn(self):
        m = self.standing()
        m.part("wheel", parent="body", pivot=(0, 16, 0)).box((-2, 16, -1), (2, 20, 1), GREEN)
        m.animate("walk", 1.0, sculpt.gait(LEGS, stride=4, lift=2, body="body"), sculpt.spin("wheel", axis="z"))
        self.assertEqual(self.notes(m), [])

    def test_a_one_shot_that_doesnt_come_home_is_called_out(self):
        m = self.standing()
        m.animate("attack", 1.0, {"body": {"rotation": lambda p: (30 * p, 0, 0)}}, sculpt.plant(LEGS), loop="once")
        self.assertTrue(any("attack:" in n and "ends away from rest" in n and "body" in n for n in self.notes(m)))

    def test_turning_too_fast_for_a_tick_is_called_out(self):
        m = self.standing()
        m.animate("idle", 0.5, sculpt.spin("body", axis="y", turns=4), sculpt.plant(LEGS))
        self.assertTrue(any("in a tick" in n for n in self.notes(m)))

    def test_check_carries_the_notes(self):
        m = self.standing()
        m.animate("walk", 1.0, sculpt.swing(LEGS, 25), sculpt.bob("body", 0.3))
        said = " ".join(sculpt.check(m))
        self.assertTrue("slides" in said or "never lifts" in said)

    def test_check_asks_for_hurt_and_death_on_a_mob_but_not_a_machine(self):
        m = self.standing()
        m.animate("walk", 1.0, sculpt.gait(LEGS, stride=4, lift=2, body="body"))
        for wanted in ("'hurt'", "'death'"):
            self.assertTrue(any(wanted in p for p in sculpt.check(m)), wanted)
            self.assertFalse(any(wanted in p for p in sculpt.check(m, machine=True)), wanted)

    def test_extra_animations_pass_the_import_check(self):
        m = creature()
        m.animate("dance", 1.0, sculpt.bob("body", 1))
        self.assertEqual(bb.check(m.build()), [])

    def test_feet_can_be_found_by_name_in_a_saved_file(self):
        m = self.standing()
        m.animate("walk", 1.0, sculpt.swing(LEGS, 25), sculpt.bob("body", 0.3))
        said = bb.motion_notes(json.loads(json.dumps(m.build())))
        self.assertTrue(any("leg_" in n for n in said))

    def test_legacy_mobs_can_be_measured(self):
        for fn in bb.KINDS.values():
            self.assertIsInstance(bb.motion_notes(fn("legacy", seed=1)), list)


class HeadBones(unittest.TestCase):
    def test_a_bone_named_for_the_head_can_hang_from_it(self):
        m = creature()
        m.part("head_ear", parent="head", pivot=(3, 17, -3)).box((2, 17, -4), (4, 21, -2), GREEN)
        m.animate("idle", 2.0, sculpt.bob("body", 0.5), sculpt.swing("head", 3), sculpt.swing("head_ear", 8), sculpt.plant(LEGS))
        self.assertEqual(bb.check(m.build()), [])
        self.assertEqual(sculpt.check(m), [])

    def test_anything_else_under_a_head_is_still_a_mistake(self):
        m = creature()
        m.part("ear", parent="head", pivot=(3, 17, -3)).box((2, 17, -4), (4, 21, -2), GREEN)
        self.assertTrue(any("inside a head bone" in p for p in bb.check(m.build())))


class MotionSheet(unittest.TestCase):
    def test_preview_writes_a_second_sheet_for_motion(self):
        with tempfile.TemporaryDirectory() as d:
            path = pathlib.Path(d) / "m.png"
            creature().preview(path)
            self.assertTrue(path.exists())
            self.assertTrue((pathlib.Path(d) / "m_motion.png").exists())

    def test_no_animations_means_no_motion_sheet(self):
        m = sculpt.Model("still")
        m.part("p").box((0, 0, 0), (2, 2, 2), GREEN)
        with tempfile.TemporaryDirectory() as d:
            path = pathlib.Path(d) / "m.png"
            m.preview(path)
            self.assertFalse((pathlib.Path(d) / "m_motion.png").exists())

    def test_it_fits_where_it_can_be_read_with_many_animations(self):
        m = creature()
        for i in range(9):
            m.animate(f"extra{i}", 1.0, sculpt.bob("body", i + 1))
        sheet = bb.motion_sheet(m.build())
        self.assertLessEqual(max(sheet.size), 1500)

    def test_its_problems_are_on_the_picture(self):
        m = sculpt.Model("dead")
        body = m.part("body", pivot=(0, 8, 0))
        body.box((-4, 8, -3), (4, 16, 3), GREEN)
        leg = m.part("leg_r", parent=body, pivot=(3, 8, 0))
        leg.box((2, 0, -1), (4, 8, 1), GREEN)
        m.animate("walk", 1.0, sculpt.swing("leg_r", 25))
        clean = bb.motion_sheet(creature().build())
        messy = bb.motion_sheet(m.build())
        warm = lambda img: int((np.asarray(img.convert("RGB")) == (255, 170, 130)).all(axis=2).sum())
        self.assertEqual(warm(clean), 0)
        self.assertGreater(warm(messy), 20)

    def test_a_walk_gets_a_side_view_and_a_foot_chart(self):
        m = creature()
        doc = m.build()
        motion = bb._Motion(doc, None, m._feet())
        walk = next(a for a in doc["animations"] if a["name"] == "walk")
        label, _ = bb._pick_view(motion, walk)
        self.assertEqual(label, "side on")
        self.assertGreater(bb.motion_sheet(doc, feet=m._feet()).height, bb.motion_sheet({**doc, "animations": [a for a in doc["animations"] if a["name"] != "walk"]}).height + 100)

    def test_something_walking_sideways_is_seen_from_the_front(self):
        m, _ = walker([(3, 0), (-3, 0)], heading=(1, 0))
        doc = m.build()
        motion = bb._Motion(doc, None, m._feet())
        walk = next(a for a in doc["animations"] if a["name"] == "walk")
        self.assertIn("from the front", bb._pick_view(motion, walk)[0])

    def test_something_long_with_no_feet_is_seen_from_above(self):
        m = sculpt.Model("worm")
        a = m.part("a", pivot=(0, 2, 0))
        a.box((-2, 0, -20), (2, 4, 20), GREEN)
        m.animate("walk", 1.0, sculpt.swing("a", 5, axis="y"))
        doc = m.build()
        motion = bb._Motion(doc)
        walk = doc["animations"][0]
        self.assertEqual(bb._pick_view(motion, walk)[0], "from above")

    def test_trails_follow_the_part_that_moves_most(self):
        m = creature()
        doc = m.build()
        motion = bb._Motion(doc)
        walk = next(a for a in doc["animations"] if a["name"] == "walk")
        names = [name for name, _ in bb._trails(motion, motion.frames(walk)[1])]
        self.assertTrue(set(names) & set(LEGS))

    def test_series_gives_what_pose_gives(self):
        m = creature()
        doc = m.build()
        scene = bb._Scene(doc)
        for anim, t in (("walk", 0.3), ("death", 0.7), (None, 0.0)):
            posed = bb._pose(doc, anim, t)
            many = scene.series(anim, [t])[0]
            for i, uuid_ in enumerate(scene.bones):
                self.assertTrue(np.allclose(posed[uuid_], many[i]), f"{anim} {uuid_}")

    def test_stats_count_keyframes_and_the_speed_to_walk_at(self):
        s = sculpt.stats(creature())
        self.assertGreater(s["keyframes"], 10)
        self.assertGreater(s["walk_speed"], 0)

    def test_the_sheets_take_a_couple_of_seconds_at_most(self):
        import time
        m = creature()
        doc = m.build()
        started = time.time()
        with tempfile.TemporaryDirectory() as d:
            m.preview(pathlib.Path(d) / "m.png")
        self.assertLess(time.time() - started, 5.0, "well above the target of 2, because test machines vary")


class Legacy(unittest.TestCase):
    def test_sculpted_and_older_mobs_share_one_document_builder(self):
        old, new = bb.slime("old", seed=1), creature().build()
        self.assertEqual(sorted(old), sorted(new))
        self.assertEqual(sorted(old["textures"][0]), sorted(new["textures"][0]))

    def test_older_mobs_still_pass_check(self):
        for fn in bb.KINDS.values():
            self.assertEqual(bb.check(fn("legacy", seed=2)), [])


if __name__ == "__main__":
    unittest.main()
