"""Run from the repository root:  python3 -m unittest assetkit.test_assetkit"""
import base64
import colorsys
import contextlib
import io
import json
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import numpy as np
from PIL import Image

from assetkit import bbmodel as bb, sheet, sounds as sd, textures as tx

ROOT = pathlib.Path(__file__).resolve().parent.parent
SEEDS = range(12)

SEAMLESS = {
    "stone": lambda s, **k: tx.stone(seed=s, **k),
    "deepslate": lambda s, **k: tx.stone((76, 76, 84), seed=s, style="deepslate", **k),
    "cobble": lambda s, **k: tx.stone(seed=s, style="cobble", **k),
    "bricks": lambda s, **k: tx.stone((150, 92, 78), seed=s, style="bricks", **k),
    "ore": lambda s, **k: tx.ore("#e8742c", seed=s, **k),
    "deep_ore": lambda s, **k: tx.ore("#4fd0d8", base="deepslate", seed=s, **k),
    "dirt": lambda s, **k: tx.soil(seed=s, **k),
    "gravel": lambda s, **k: tx.soil((130, 124, 120), seed=s, style="gravel", **k),
    "sand": lambda s, **k: tx.soil((219, 207, 163), seed=s, style="sand", **k),
    "mud": lambda s, **k: tx.soil((70, 58, 62), seed=s, style="mud", **k),
    "planks": lambda s, **k: tx.planks(seed=s, **k),
    "log_side": lambda s, **k: tx.log_side(seed=s, **k),
    "glow": lambda s, **k: tx.glow(seed=s, **k),
    "leaves": lambda s, **k: tx.leaves(seed=s, **k),
}
FRAMED = {
    "smooth": lambda s, **k: tx.stone(seed=s, style="smooth", **k),
    "metal": lambda s, **k: tx.metal(seed=s, **k),
    "rivets": lambda s, **k: tx.metal((240, 196, 70), seed=s, style="rivets", **k),
    "metal_gem": lambda s, **k: tx.metal((84, 200, 214), seed=s, style="gem", **k),
    "lamp": lambda s, **k: tx.glow(seed=s, style="lamp", **k),
    "log_top": lambda s, **k: tx.log_top(seed=s, **k),
    **{f"machine_{f}": (lambda f: lambda s, **k: tx.machine(f, seed=s, **k))(f)
       for f in ("front", "side", "top", "bottom", "back")},
    "machine_on": lambda s, **k: tx.machine("front", on=True, seed=s, **k),
}
BLOCKS = {**SEAMLESS, **FRAMED}
ITEMS = {
    "ingot": lambda s, **k: tx.ingot(seed=s, **k),
    "gem0": lambda s, **k: tx.gem(cut=0, seed=s, **k),
    "gem1": lambda s, **k: tx.gem(cut=1, seed=s, **k),
    "gem2": lambda s, **k: tx.gem(cut=2, seed=s, **k),
    "nugget": lambda s, **k: tx.nugget(seed=s, **k),
    "raw_chunk": lambda s, **k: tx.raw_chunk(seed=s, **k),
    "dust": lambda s, **k: tx.dust(seed=s, **k),
    "rod": lambda s, **k: tx.rod(seed=s, **k),
    "seeds": lambda s, **k: tx.seeds(seed=s, **k),
    **{f"food_{f}": (lambda f: lambda s, **k: tx.food(f, seed=s, **k))(f)
       for f in ("fruit", "berries", "loaf", "meat", "stew", "cookie")},
    "pickaxe": lambda s, **k: tx.pickaxe(seed=s, **k),
    "axe": lambda s, **k: tx.axe(seed=s, **k),
    "sword": lambda s, **k: tx.sword(seed=s, **k),
    "shovel": lambda s, **k: tx.shovel(seed=s, **k),
    "hoe": lambda s, **k: tx.hoe(seed=s, **k),
}
PLANTS = {k: (lambda k: lambda s, **kw: tx.plant(k, seed=s, **kw))(k) for k in tx._PLANTS}
SOUNDS = {
    **{f"hit_{m}": (lambda m: lambda s: sd.block_hit(m, s))(m) for m in sd.MATERIALS},
    **{f"break_{m}": (lambda m: lambda s: sd.block_break(m, s))(m) for m in sd.MATERIALS},
    "hum": lambda s: sd.machine_hum(seed=s), "done": lambda s: sd.machine_done(seed=s),
    "pickup": lambda s: sd.item_pickup(seed=s),
    **{f"idle_{v}": (lambda v: lambda s: sd.mob_idle(v, s))(v) for v in sd.VOICES},
    **{f"hurt_{v}": (lambda v: lambda s: sd.mob_hurt(v, s))(v) for v in sd.VOICES},
    **{f"death_{v}": (lambda v: lambda s: sd.mob_death(v, s))(v) for v in sd.VOICES},
}


def lum(c):
    return 0.3 * c[0] + 0.59 * c[1] + 0.11 * c[2]


def lone_pixels(img):
    """The share of pixels with no 4-neighbour of the same colour: a direct measure of per-pixel noise."""
    a = np.asarray(img.convert("RGBA"))
    same = np.zeros(a.shape[:2], dtype=bool)
    for axis, step in ((0, 1), (0, -1), (1, 1), (1, -1)):
        same |= (a == np.roll(a, step, axis=axis)).all(axis=2)
    return float(1 - same.mean())


class Ramps(unittest.TestCase):
    def test_keeps_base_in_the_middle_and_gets_lighter(self):
        for base in ("#7f7f7f", "#e8742c", "#4fd0d8", (72, 132, 44), (20, 20, 60)):
            r = tx.ramp(base, 5)
            self.assertEqual(r[2], tx.rgb(base))
            self.assertEqual(len(r), 5)
            values = [lum(c) for c in r]
            self.assertEqual(values, sorted(values), f"{base} isn't dark to light")

    def test_shadows_shift_cooler_and_highlights_warmer(self):
        r = tx.ramp("#c08040", 5, shift=2.0)  # an orange: shadows move toward red-purple, highlights toward yellow
        hue = [colorsys.rgb_to_hsv(*(v / 255 for v in c))[0] for c in r]
        self.assertLess(hue[0], hue[2])
        self.assertGreater(hue[4], hue[2])
        g = tx.ramp("#40a050", 5, shift=2.0)  # a green: shadows move toward teal
        hue = [colorsys.rgb_to_hsv(*(v / 255 for v in c))[0] for c in g]
        self.assertGreater(hue[0], hue[2])
        self.assertLess(hue[4], hue[2])

    def test_a_grey_ramp_is_tinted_not_flat(self):
        r = tx.ramp((128, 128, 128), 5)
        self.assertGreater(r[0][2], r[0][0], "grey shadows should lean blue")
        self.assertGreater(r[4][0], r[4][2], "grey highlights should lean warm")


class Recolor(unittest.TestCase):
    def test_keeps_structure_and_alpha_on_a_new_colour(self):
        src = tx.leaves(seed=2)
        out = tx.recolor(src, "#c04040")
        a, b = np.asarray(src), np.asarray(out)
        self.assertTrue((a[..., 3] == b[..., 3]).all())
        self.assertEqual(len(tx.palette(out)), len(tx.palette(src)))
        self.assertGreater(b[b[..., 3] > 0, 0].mean(), b[b[..., 3] > 0, 1].mean(), "should now be red")


class Generators(unittest.TestCase):
    def test_same_seed_gives_identical_pixels(self):
        for name, fn in {**BLOCKS, **ITEMS, **PLANTS}.items():
            self.assertEqual(fn(5).tobytes(), fn(5).tobytes(), name)

    def test_procedural_generators_change_with_the_seed(self):
        for name in ("stone", "ore", "deep_ore", "dirt", "planks", "log_side", "leaves", "glow", "cobble"):
            self.assertGreater(len({BLOCKS[name](s).tobytes() for s in SEEDS}), 6, name)
        for name in ("raw_chunk", "dust", "seeds", "nugget"):
            self.assertGreater(len({ITEMS[name](s).tobytes() for s in SEEDS}), 6, name)

    def test_16x16_rgba_by_default(self):
        for name, fn in {**BLOCKS, **ITEMS, **PLANTS}.items():
            img = fn(1)
            self.assertEqual((img.size, img.mode), ((16, 16), "RGBA"), name)

    def test_size_can_be_asked_for(self):
        for name, fn in {**BLOCKS, **ITEMS, **PLANTS}.items():
            self.assertEqual(fn(1, size=32).size, (32, 32), name)

    def test_blocks_are_opaque_except_leaves(self):
        for name, fn in BLOCKS.items():
            if name != "leaves":
                self.assertEqual(np.asarray(fn(3))[..., 3].min(), 255, name)

    def test_palettes_stay_small(self):
        limits = {"ore": 10, "deep_ore": 10, "log_top": 6, "machine_on": 10, "machine_front": 7}
        for name, fn in BLOCKS.items():
            for s in SEEDS:
                self.assertLessEqual(len(tx.palette(fn(s))), limits.get(name, 6), f"{name} seed {s}")
        for name, fn in ITEMS.items():  # one material, or two for a head and handle
            self.assertLessEqual(len(tx.palette(fn(1))), 10, name)

    def test_block_surfaces_are_clusters_not_noise(self):
        for name in ("stone", "deepslate", "dirt", "sand", "mud", "log_side", "planks", "bricks"):
            for s in SEEDS:
                self.assertLess(lone_pixels(BLOCKS[name](s)), 0.2, f"{name} seed {s} looks like noise")

    def test_contrast_is_soft_on_stone(self):
        for s in SEEDS:
            values = [lum(c) for c in tx.palette(tx.stone(seed=s))]
            self.assertLess(max(values) - min(values), 70)


class Tiling(unittest.TestCase):
    def test_seamless_blocks_have_no_visible_seam(self):
        """In a wrapped texture the seam is just one more row, so it's rarely the strongest one. A single
        seed can get unlucky, hence looking at the spread of 60 seeds."""
        for name, fn in SEAMLESS.items():
            scores = [tx.tile_score(fn(s)) for s in range(60)]
            self.assertLessEqual(np.median(scores), 1.0, f"{name} shows a seam on most seeds")
            self.assertLess(np.percentile(scores, 90), 1.35, f"{name} shows a seam on too many seeds")

    def test_framed_blocks_score_as_framed(self):
        self.assertGreater(tx.tile_score(tx.metal(seed=1)), 1.4)
        self.assertGreater(tx.tile_score(tx.machine("side", seed=1)), 1.4)

    def test_the_score_catches_a_texture_that_does_not_tile(self):
        ramp = np.tile(np.linspace(60, 200, 16)[None, :, None], (16, 1, 3)).astype(np.uint8)
        alpha = np.full((16, 16, 1), 255, dtype=np.uint8)
        gradient = Image.fromarray(np.concatenate([ramp, alpha], axis=2))
        self.assertGreater(tx.tile_score(gradient), 3)

    def test_clusters_continue_across_the_edge(self):
        """Stamp only runs of exactly 3. If any were clipped at an edge instead of wrapping, a row would
        hold a circular run shorter than 3."""
        idx = np.zeros((16, 16), dtype=int)
        with mock.patch.object(tx, "_grow", lambda *_a, **_k: [(0, 0), (-1, 0), (-2, 0)]):
            tx._stamp(idx, tx._rng(1), 12, (3, 3), 1)
        crossed = 0
        for row in idx:
            if row.all() or not row.any():
                continue
            crossed += int(row[0] and row[-1])
            starts = np.nonzero((row == 1) & (np.roll(row, 1) == 0))[0]
            for start in starts:
                self.assertTrue(row[(start + 1) % 16] and row[(start + 2) % 16], "a clipped cluster")
        self.assertGreater(crossed, 0, "no cluster happened to cross the edge, so this proved nothing")


class Ores(unittest.TestCase):
    def test_flecks_are_readable_against_the_base(self):
        for base in ("stone", "deepslate"):
            for s in SEEDS:
                img = tx.ore("#e8742c", base=base, seed=s)
                rock = {tuple(c) for c in tx.palette(tx.stone((76, 76, 84) if base == "deepslate" else (126, 126, 126), s, 16, base))}
                a = np.asarray(img)[..., :3].reshape(-1, 3)
                ore_pixels = [tuple(int(v) for v in p) for p in a if tuple(int(v) for v in p) not in rock]
                self.assertGreaterEqual(len(ore_pixels), 10, f"{base} seed {s}: too few ore pixels")
                self.assertLess(len(ore_pixels), 70, f"{base} seed {s}: the ore swamps the rock")

    def test_deepslate_variant_is_darker(self):
        for s in SEEDS:
            light = np.asarray(tx.ore("#e8742c", seed=s))[..., :3].mean()
            dark = np.asarray(tx.ore("#e8742c", base="deepslate", seed=s))[..., :3].mean()
            self.assertLess(dark, light - 15)


class Items(unittest.TestCase):
    def test_background_is_transparent_with_hard_alpha(self):
        for name, fn in {**ITEMS, **PLANTS}.items():
            for s in range(4):
                a = np.asarray(fn(s))[..., 3]
                self.assertTrue(set(np.unique(a)) <= {0, 255}, f"{name} has soft alpha")
                self.assertGreater((a == 0).mean(), 0.25, f"{name} has too little transparency")
                self.assertGreater((a == 255).mean(), 0.05, f"{name} is nearly empty")
                self.assertEqual(a[0, 0], 0, f"{name} has a filled corner")

    def test_items_stay_inside_the_frame(self):
        for name, fn in ITEMS.items():
            for s in range(4):
                a = np.asarray(fn(s))[..., 3]
                self.assertFalse(a[:, 0].all() or a[:, -1].all() or a[0].all() or a[-1].all(), name)

    def test_items_have_dark_outlines(self):
        for name, fn in ITEMS.items():
            a = np.asarray(fn(2))
            opaque = a[..., 3] > 0
            edge = opaque & ~(np.roll(opaque, 1, 0) & np.roll(opaque, -1, 0) & np.roll(opaque, 1, 1) & np.roll(opaque, -1, 1))
            inner = opaque & ~edge
            self.assertGreater(inner.sum(), 0, name)
            rgb = a[..., :3].astype(float)
            self.assertLess(rgb[edge].mean(), rgb[inner].mean() * 0.72, f"{name}: outline isn't dark")
            self.assertGreater(rgb[edge].max(), 0, f"{name}: outline shouldn't be pure black only")

    def test_tools_take_the_head_colour(self):
        for fn in (tx.pickaxe, tx.axe, tx.sword, tx.shovel, tx.hoe):
            orange = np.asarray(fn("#e8742c")).reshape(-1, 4)
            cyan = np.asarray(fn("#4fd0d8")).reshape(-1, 4)
            self.assertGreater(orange[orange[:, 3] > 0, 0].mean(), cyan[cyan[:, 3] > 0, 0].mean())

    def test_plants_are_rooted_on_the_bottom_row(self):
        for name, fn in PLANTS.items():
            for s in range(4):
                self.assertTrue(np.asarray(fn(s))[-1, :, 3].any(), name)


class Animation(unittest.TestCase):
    def test_save_animated_writes_a_strip_and_mcmeta(self):
        frames = tx.glow_frames(seed=1, frames=8)
        with tempfile.TemporaryDirectory() as d:
            png, meta = tx.save_animated(frames, pathlib.Path(d) / "lamp.png", frametime=3, interpolate=True)
            self.assertEqual(meta.name, "lamp.png.mcmeta")
            strip = Image.open(png)
            self.assertEqual(strip.size, (16, 128))
            self.assertEqual(json.loads(meta.read_text()), {"animation": {"frametime": 3, "interpolate": True}})
            cut = tx.split_frames(strip.convert("RGBA"))
            self.assertEqual(len(cut), 8)
            self.assertEqual(cut[3].tobytes(), frames[3].tobytes())

    def test_frames_really_change(self):
        for frames in (tx.glow_frames(seed=1), tx.machine_frames(seed=1), tx.scroll(tx.soil(seed=1))):
            self.assertGreater(len({f.tobytes() for f in frames}), 2)

    def test_scroll_loops_cleanly(self):
        img = tx.soil(seed=2)
        frames = tx.scroll(img, dy=1)
        self.assertEqual(len(frames), 16)
        self.assertEqual(np.roll(np.asarray(frames[-1]), 1, axis=0).tobytes(), np.asarray(img).tobytes())

    def test_machine_casing_holds_still(self):
        frames = tx.machine_frames(seed=4)
        a, b = np.asarray(frames[0]).copy(), np.asarray(frames[1]).copy()
        a[4:13, 4:12] = b[4:13, 4:12] = 0
        self.assertEqual(a.tobytes(), b.tobytes())


class ContactSheet(unittest.TestCase):
    def test_tells_blocks_from_items(self):
        self.assertTrue(sheet.is_block(tx.stone()))
        self.assertTrue(sheet.is_block(tx.leaves()))
        self.assertFalse(sheet.is_block(tx.pickaxe()))
        self.assertFalse(sheet.is_block(tx.plant("flower")))

    def test_sheet_scales_tiles_and_checks(self):
        with tempfile.TemporaryDirectory() as d:
            d = pathlib.Path(d)
            tx.stone(seed=1).save(d / "a_stone.png")
            tx.pickaxe().save(d / "b_pick.png")
            tx.save_animated(tx.glow_frames(), d / "c_glow.png")
            out = d / "out" / "sheet.png"
            img = sheet.contact_sheet([d], out, columns=1)
            self.assertTrue(out.exists())
            arr = np.asarray(img.convert("RGB"))
            src = np.asarray(Image.open(d / "a_stone.png").convert("RGB"))
            x0, y0 = sheet.GAP * 2, sheet.GAP * 2
            # The block is at 8x with nearest neighbour.
            self.assertTrue((arr[y0:y0 + 8, x0:x0 + 8] == src[0, 0]).all())
            self.assertTrue((arr[y0 + 8 * 15, x0 + 8 * 15] == src[15, 15]).all())
            # Its 3x3 tiling sits to the right at the tile scale.
            tx0 = x0 + 128 + sheet.GAP
            ts = sheet.TILE_SCALE
            self.assertTrue((arr[y0, tx0] == src[0, 0]).all())
            self.assertTrue((arr[y0 + 16 * ts, tx0 + 16 * ts] == src[0, 0]).all())

    def test_checkerboard_shows_through_transparency(self):
        with tempfile.TemporaryDirectory() as d:
            p = pathlib.Path(d) / "item.png"
            tx.pickaxe().save(p)
            arr = np.asarray(sheet.contact_sheet([p], columns=1).convert("RGB"))
            corner = arr[sheet.GAP * 2:sheet.GAP * 2 + 16, sheet.GAP * 2:sheet.GAP * 2 + 16]
            self.assertEqual(len({tuple(c) for c in corner.reshape(-1, 3)}), 2)

    def test_flags_too_many_colours(self):
        noise = np.random.default_rng(1).integers(0, 255, (16, 16, 4), dtype=np.uint8)
        noise[..., 3] = 255
        with tempfile.TemporaryDirectory() as d:
            p = pathlib.Path(d) / "noise.png"
            Image.fromarray(noise).save(p)
            arr = np.asarray(sheet.contact_sheet([p], columns=1).convert("RGB"))
            self.assertTrue((arr == np.array(sheet.WARN)).all(axis=2).any())

    def test_empty_input_is_an_error(self):
        with tempfile.TemporaryDirectory() as d, self.assertRaises(ValueError):
            sheet.contact_sheet([d])


class Sounds(unittest.TestCase):
    def test_mono_short_and_clean(self):
        for name, fn in SOUNDS.items():
            s = fn(1)
            self.assertEqual(s.ndim, 1, name)
            self.assertLess(s.size / sd.RATE, sd.MAX_SECONDS, name)
            self.assertGreater(s.size / sd.RATE, 0.05, name)
            self.assertLessEqual(float(np.abs(s).max()), 1.0, name)
            self.assertGreater(float(np.abs(s).max()), 0.3, f"{name} is too quiet")
            self.assertLess(abs(float(s.mean())), 0.02, f"{name} has a DC offset")

    def test_deterministic_for_a_seed(self):
        for name, fn in SOUNDS.items():
            self.assertEqual(fn(4).tobytes(), fn(4).tobytes(), name)
        self.assertNotEqual(sd.block_hit("stone", 1).tobytes(), sd.block_hit("stone", 2).tobytes())

    def test_one_shot_sounds_start_and_end_silently(self):
        for name, fn in SOUNDS.items():
            if name != "hum":
                s = fn(1)
                self.assertLess(abs(float(s[0])), 0.01, name)
                self.assertLess(abs(float(s[-1])), 0.01, name)

    def test_hum_loops_without_a_click(self):
        h = sd.machine_hum(seed=3)
        self.assertLess(abs(float(h[0] - h[-1])), 4 * float(np.abs(np.diff(h)).max()))

    def test_materials_differ_in_brightness(self):
        def centroid(s):
            spec = np.abs(np.fft.rfft(s))
            return float((spec * np.fft.rfftfreq(s.size, 1 / sd.RATE)).sum() / spec.sum())
        self.assertLess(centroid(sd.block_hit("soil", 1)), centroid(sd.block_hit("glass", 1)))
        self.assertLess(centroid(sd.block_hit("wood", 1)), centroid(sd.block_hit("metal", 1)))

    def test_death_is_longer_than_hurt(self):
        self.assertGreater(sd.mob_death("grunt", 1).size, 2 * sd.mob_hurt("grunt", 1).size)

    def test_refuses_stereo_and_long_sounds(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError):
                sd.save(np.zeros((100, 2)), pathlib.Path(d) / "x.ogg")
            with self.assertRaises(ValueError):
                sd.save(np.zeros(sd.RATE * 3), pathlib.Path(d) / "x.ogg")

    @unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg isn't installed")
    def test_ogg_is_mono_vorbis(self):
        with tempfile.TemporaryDirectory() as d:
            p = sd.save(sd.block_break("wood", 1), pathlib.Path(d) / "sub" / "x.ogg")
            self.assertEqual(p.suffix, ".ogg")
            self.assertEqual(p.read_bytes()[:4], b"OggS")
            if shutil.which("ffprobe"):
                info = json.loads(subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(p)],
                                                 capture_output=True, text=True, check=True).stdout)["streams"][0]
                self.assertEqual((info["codec_name"], info["channels"]), ("vorbis", 1))
                self.assertLess(float(info["duration"]), sd.MAX_SECONDS)

    def test_without_ffmpeg_it_writes_wav_and_says_so(self):
        err = io.StringIO()
        with tempfile.TemporaryDirectory() as d, mock.patch.object(shutil, "which", return_value=None), contextlib.redirect_stderr(err):
            p = sd.save(sd.item_pickup(1), pathlib.Path(d) / "x.ogg")
            self.assertEqual(p.suffix, ".wav")
            self.assertEqual(p.read_bytes()[:4], b"RIFF")
        self.assertIn("WARNING", err.getvalue())
        self.assertIn(".wav", err.getvalue())

    def test_mob_set_writes_three_files(self):
        if not shutil.which("ffmpeg"):
            self.skipTest("ffmpeg isn't installed")
        with tempfile.TemporaryDirectory() as d:
            names = [p.name for p in sd.mob_set(d, "husk", voice="growl", seed=2)]
            self.assertEqual(names, ["husk_idle.ogg", "husk_hurt.ogg", "husk_death.ogg"])


MOBS = {kind: (lambda fn: lambda seed=1: fn(f"test_{fn.__name__}", seed=seed))(fn) for kind, fn in bb.KINDS.items()}


class Mobs(unittest.TestCase):
    def test_every_kind_passes_the_import_check(self):
        for kind, fn in MOBS.items():
            for s in range(3):
                self.assertEqual(bb.check(fn(s)), [], kind)

    def test_deterministic_for_a_seed(self):
        for kind, fn in MOBS.items():
            self.assertEqual(json.dumps(fn(2)), json.dumps(fn(2)), kind)
            self.assertNotEqual(json.dumps(fn(2)), json.dumps(fn(3)), kind)

    def test_round_trips_as_plain_json(self):
        for kind, fn in MOBS.items():
            with tempfile.TemporaryDirectory() as d:
                model = fn()
                path = bb.save(model, pathlib.Path(d) / "sub" / f"{kind}.bbmodel")
                self.assertEqual(bb.load(path), json.loads(json.dumps(model)))

    def test_file_shape_matches_the_blockbench_5_layout_bil_reads(self):
        for kind, fn in MOBS.items():
            m = fn()
            self.assertEqual(m["meta"]["format_version"], "5.0")
            self.assertEqual(m["meta"]["model_format"], "free")
            self.assertEqual(m["resolution"], {"width": 64, "height": 64})
            for g in m["groups"]:
                self.assertEqual(set(g) & {"origin", "rotation", "uuid", "export", "name", "scale"},
                                 {"origin", "rotation", "uuid", "export", "name", "scale"})
            for e in m["elements"]:
                self.assertEqual(e["type"], "cube")
                self.assertEqual(set(e["faces"]), set(bb.FACES))

    def test_head_bone_rules(self):
        for kind in ("humanoid", "quadruped", "flying"):
            m = MOBS[kind]()
            heads = [g for g in m["groups"] if g["name"].startswith("head")]
            self.assertEqual(len(heads), 1, kind)

            def find(node):
                if node["uuid"] == heads[0]["uuid"]:
                    return node
                for child in node["children"]:
                    if isinstance(child, dict) and (found := find(child)):
                        return found
                return None

            self.assertFalse([c for c in find(m["outliner"][0])["children"] if isinstance(c, dict)],
                             "BIL's docs warn about child bones under a head bone")

    def test_idle_and_walk_loop_and_touch_real_bones(self):
        for kind, fn in MOBS.items():
            m = fn()
            names = {g["uuid"]: g["name"] for g in m["groups"]}
            anims = {a["name"]: a for a in m["animations"]}
            self.assertEqual(set(anims), {"idle", "walk"}, kind)
            for a in anims.values():
                self.assertEqual(a["loop"], "loop")
                self.assertTrue(a["animators"], kind)
                for key, animator in a["animators"].items():
                    self.assertEqual(names[key], animator["name"])
                    self.assertTrue(animator["keyframes"])
                    for k in animator["keyframes"]:
                        self.assertLessEqual(k["time"], a["length"] + 1e-6)
                        self.assertTrue(all(isinstance(k["data_points"][0][v], (int, float)) for v in "xyz"),
                                        "numbers need no Molang compile in BIL")

    def test_animations_end_where_they_begin(self):
        for kind, fn in MOBS.items():
            for a in fn()["animations"]:
                for animator in a["animators"].values():
                    for channel in {k["channel"] for k in animator["keyframes"]}:
                        keys = sorted((k for k in animator["keyframes"] if k["channel"] == channel), key=lambda k: k["time"])
                        for v in "xyz":
                            self.assertAlmostEqual(keys[0]["data_points"][0][v], keys[-1]["data_points"][0][v], places=2,
                                                   msg=f"{kind} {a['name']} {animator['name']} {channel}")

    def test_walk_actually_moves_the_limbs(self):
        for kind, bone in (("humanoid", "leg_left"), ("quadruped", "leg_back_left"), ("flying", "wing_left")):
            m = MOBS[kind]()
            uid = next(g["uuid"] for g in m["groups"] if g["name"] == bone)
            walk = next(a for a in m["animations"] if a["name"] == "walk")
            rot = [k["data_points"][0] for k in walk["animators"][uid]["keyframes"] if k["channel"] == "rotation"]
            self.assertGreater(max(abs(r["x"]) + abs(r["z"]) for r in rot), 15, kind)

    def test_skin_is_embedded_and_lands_on_every_face(self):
        for kind, fn in MOBS.items():
            m = fn()
            skin = np.asarray(bb.skin(m))
            self.assertEqual(skin.shape[0], m["textures"][0]["height"])
            for e in m["elements"]:
                for face, data in e["faces"].items():
                    u0, v0, u1, v1 = data["uv"]
                    self.assertTrue((skin[v0:v1, u0:u1, 3] > 0).all(), f"{kind} {e['name']} {face}")

    def test_unwraps_do_not_overlap(self):
        for kind, fn in MOBS.items():
            m = fn()
            used = np.zeros((m["textures"][0]["height"], m["textures"][0]["width"]), dtype=int)
            for e in m["elements"]:
                for data in e["faces"].values():
                    u0, v0, u1, v1 = data["uv"]
                    used[v0:v1, u0:u1] += 1
            self.assertLessEqual(used.max(), 1, kind)

    def test_uv_size_matches_cube_size(self):
        m = MOBS["humanoid"]()
        head = next(e for e in m["elements"] if e["name"] == "head")
        u0, v0, u1, v1 = head["faces"]["north"]["uv"]
        self.assertEqual((u1 - u0, v1 - v0), (8, 8))

    def test_front_of_the_face_is_on_the_north_face(self):
        # BIL turns models by 180 degrees around Y, so -Z (north in Blockbench) ends up looking forward.
        for kind in ("humanoid", "quadruped", "flying"):
            m = MOBS[kind]()
            head = next(e for e in m["elements"] if e["name"] == "head")
            skin = np.asarray(bb.skin(m)).astype(float)
            region = lambda f: skin[head["faces"][f]["uv"][1]:head["faces"][f]["uv"][3], head["faces"][f]["uv"][0]:head["faces"][f]["uv"][2], :3]
            self.assertLess(region("north").min(), region("east").min() - 10, f"{kind} has no eyes on its front")

    def test_geometry_stays_inside_the_item_model_limits(self):
        """A port of BIL's postProcess: cubes are made relative to the bone pivot, scaled down if a bone
        spans over 24 units, and moved by +8. The result must fit the -16..32 model space."""
        for kind, fn in MOBS.items():
            m = fn()
            groups = {g["uuid"]: g for g in m["groups"]}
            elements = {e["uuid"]: e for e in m["elements"]}

            def walk(node):
                origin = np.array(groups[node["uuid"]]["origin"], float)
                cubes = [elements[c] for c in node["children"] if isinstance(c, str)]
                if cubes:
                    lo, hi = np.zeros(3), np.zeros(3)
                    for c in cubes:
                        lo = np.minimum(lo, np.array(c["from"]) - origin)
                        hi = np.maximum(hi, np.array(c["to"]) - origin)
                    scale = min(1.0, 24.0 / (hi - lo).max())
                    self.assertEqual(scale, 1.0, f"{kind}: a bone needs scaling, keep bones under 24 units")
                    self.assertGreaterEqual((lo * scale + 8).min(), -16)
                    self.assertLessEqual((hi * scale + 8).max(), 32)
                for child in node["children"]:
                    if isinstance(child, dict):
                        walk(child)

            walk(m["outliner"][0])

    def test_feet_on_the_floor(self):
        for kind in ("humanoid", "quadruped", "slime"):
            self.assertEqual(min(e["from"][1] for e in MOBS[kind]()["elements"]), 0, kind)

    def test_check_catches_what_would_break_the_import(self):
        def broken(change):
            m = json.loads(json.dumps(MOBS["humanoid"]()))
            change(m)
            return bb.check(m)

        cases = {
            "uv_width": lambda m: m["textures"][0].pop("uv_width"),
            "frame_time": lambda m: m["textures"][0].update(frame_time=0),
            "embedded PNG": lambda m: m["textures"][0].update(source="skin.png"),
            "type must be": lambda m: m["elements"][0].pop("type"),
            "export must be": lambda m: m["groups"][1].update(export=False),
            "rotation must be": lambda m: m["groups"][1].pop("rotation"),
            "loop must be": lambda m: m["animations"][0].pop("loop"),
            "needs an interpolation": lambda m: next(iter(m["animations"][0]["animators"].values()))["keyframes"][0].pop("interpolation"),
            "'walk'": lambda m: m["animations"].pop(1),
            "one root bone": lambda m: m["outliner"].append(m["outliner"][0]),
            "isn't an element": lambda m: m["outliner"][0]["children"].append("not-a-real-uuid"),
            "special meaning": lambda m: m["groups"][1].update(name="hitbox_extra"),
            "inside a head bone": lambda m: _nest_under_head(m),
            "unrotated": lambda m: m["elements"][0].update(rotation=[0, 45, 0]),
        }
        for needle, change in cases.items():
            problems = broken(change)
            self.assertTrue(any(needle in p for p in problems), f"{needle!r} not caught, got {problems}")

    def test_bad_names_are_refused(self):
        for name in ("Ember Husk", "UPPER", "with-dash", ""):
            with self.assertRaises(ValueError):
                bb.humanoid(name)

    def test_preview_draws_something(self):
        for kind, fn in MOBS.items():
            img = bb.preview(fn())
            a = np.asarray(img.convert("RGB")).astype(int)
            self.assertGreater(len(np.unique(a.reshape(-1, 3), axis=0)), 30, kind)

    def test_preview_pose_follows_the_animation(self):
        m = MOBS["humanoid"]()
        rest = bb.render(m)
        walking = bb.render(m, "walk", 0.25)
        self.assertNotEqual(rest.tobytes(), walking.tobytes())


def _nest_under_head(m):
    def find(node, name):
        groups = {g["uuid"]: g["name"] for g in m["groups"]}
        if groups[node["uuid"]] == name:
            return node
        for child in node["children"]:
            if isinstance(child, dict) and (found := find(child, name)):
                return found
        return None

    root = m["outliner"][0]
    head, arm, body = find(root, "head"), find(root, "arm_right"), find(root, "body")
    body["children"].remove(arm)
    head["children"].append(arm)


class CommandLines(unittest.TestCase):
    def run_tool(self, *args):
        return subprocess.run([sys.executable, *args], cwd=ROOT, capture_output=True, text=True, check=False)

    def test_textures_and_sheet(self):
        with tempfile.TemporaryDirectory() as d:
            d = pathlib.Path(d)
            done = self.run_tool("assetkit/textures.py", "ore", "--color", "#e8742c", "--base", "deepslate", "--seed", "3", "-o", str(d / "o.png"))
            self.assertEqual(done.returncode, 0, done.stderr)
            self.assertEqual(Image.open(d / "o.png").tobytes(), tx.ore("#e8742c", base="deepslate", seed=3).tobytes())
            done = self.run_tool("assetkit/textures.py", "glow_frames", "--seed", "2", "--frames", "4", "--frametime", "5", "-o", str(d / "g.png"))
            self.assertEqual(done.returncode, 0, done.stderr)
            self.assertEqual(json.loads((d / "g.png.mcmeta").read_text())["animation"]["frametime"], 5)
            done = self.run_tool("assetkit/sheet.py", str(d / "s.png"), str(d))
            self.assertEqual(done.returncode, 0, done.stderr)
            self.assertTrue((d / "s.png").exists())
            self.assertIn("ore(", self.run_tool("assetkit/textures.py", "list").stdout)

    def test_module_form_works_too(self):
        done = self.run_tool("-m", "assetkit.textures", "list")
        self.assertEqual(done.returncode, 0, done.stderr)

    def test_bbmodel(self):
        with tempfile.TemporaryDirectory() as d:
            d = pathlib.Path(d)
            done = self.run_tool("assetkit/bbmodel.py", "slime", "gloop", "--primary", "#7040a0", "--seed", "4",
                                 "-o", str(d / "g.bbmodel"), "--preview", str(d / "g.png"))
            self.assertEqual(done.returncode, 0, done.stderr)
            self.assertEqual(done.stderr, "")
            self.assertEqual(bb.check(bb.load(d / "g.bbmodel")), [])
            self.assertTrue((d / "g.png").exists())

    def test_sounds(self):
        with tempfile.TemporaryDirectory() as d:
            done = self.run_tool("assetkit/sounds.py", "block_hit", "--material", "wood", "--seed", "2", "-o", str(pathlib.Path(d) / "h.ogg"))
            self.assertEqual(done.returncode, 0, done.stderr)
            self.assertTrue(list(pathlib.Path(d).glob("h.*")))
            self.assertIn("voices", self.run_tool("assetkit/sounds.py", "list").stdout)


if __name__ == "__main__":
    unittest.main()
