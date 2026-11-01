#!/usr/bin/env python3
"""The world check on region files built here, in the game's own format. Needs no server."""
import contextlib
import io
import json
import pathlib
import shutil
import struct
import sys
import tempfile
import unittest
import zlib
from unittest import mock

from broker import runtime
from broker.gates import GateFailed, shadow

GATES = pathlib.Path(__file__).resolve().parent.parent / "gates"
sys.path.insert(0, str(GATES))
import world_diff  # noqa: E402

SECTOR = 4096
BYTE, INT, LONG, STRING, LIST, COMPOUND, LONGS = 1, 3, 4, 8, 9, 10, 12
ORE = "gm:s0001"


def _name(text):
    encoded = text.encode()
    return struct.pack(">H", len(encoded)) + encoded


def _string(name, value):
    return bytes([STRING]) + _name(name) + _name(value)


def _section(palette):
    """One section of the first block in the palette, except that its very first block is the second, if there is one."""
    names = b"".join(_string("Name", name) + b"\0" for name in palette)
    states = bytes([LIST]) + _name("palette") + bytes([COMPOUND]) + struct.pack(">i", len(palette)) + names
    if len(palette) > 1:
        states += bytes([LONGS]) + _name("data") + struct.pack(">i", 256) + struct.pack(">q", 1) + bytes(8 * 255)
    return bytes([BYTE]) + _name("Y") + b"\0" + bytes([COMPOUND]) + _name("block_states") + states + b"\0" + b"\0"


def touched_first_block():
    """As the mod saves it: a list of sections, each with its y and a word for every 64 blocks, here with its very first block marked."""
    section = bytes([INT]) + _name("y") + struct.pack(">i", 0) + bytes([LONGS]) + _name("bits") + struct.pack(">i", 1) + struct.pack(">q", 1) + b"\0"
    return bytes([COMPOUND]) + _name("fabric:attachments") + bytes([LIST]) + _name("gm:touched") + bytes([COMPOUND]) + struct.pack(">i", 1) + section + b"\0"


def chunk(x, z, palette=("minecraft:stone",), chests=(), inhabited=0, touched=False):
    entities = b"".join(_string("id", "minecraft:chest")
                        + b"".join(bytes([INT]) + _name(axis) + struct.pack(">i", value) for axis, value in zip("xyz", position)) + b"\0"
                        for position in chests)
    body = (bytes([INT]) + _name("xPos") + struct.pack(">i", x) + bytes([INT]) + _name("zPos") + struct.pack(">i", z)
            + _string("Status", "minecraft:full")
            + bytes([LONG]) + _name("InhabitedTime") + struct.pack(">q", inhabited)
            + (touched_first_block() if touched else b"")
            + bytes([LIST]) + _name("sections") + bytes([COMPOUND]) + struct.pack(">i", 1) + _section(palette)
            + bytes([LIST]) + _name("block_entities") + bytes([COMPOUND if chests else 0]) + struct.pack(">i", len(chests)) + entities)
    return bytes([COMPOUND]) + _name("") + body + b"\0"


def write_region(path, chunks):
    header, data, sector = bytearray(SECTOR * 2), bytearray(), 2
    for x, z, raw in chunks:
        packed = zlib.compress(raw)
        record = struct.pack(">IB", len(packed) + 1, 2) + packed
        sectors = (len(record) + SECTOR - 1) // SECTOR
        struct.pack_into(">I", header, ((x & 31) + (z & 31) * 32) * 4, (sector << 8) | sectors)
        data += record.ljust(sectors * SECTOR, b"\0")
        sector += sectors
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(bytes(header) + bytes(data))


class EveryDimension(unittest.TestCase):
    """The gate on real files, with the servers left out of it."""

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = pathlib.Path(folder.name)
        self.world = self.root / "shadow" / "world"
        for patcher in (mock.patch.object(runtime, "server_folder", return_value=self.root / "shadow"), mock.patch.object(runtime, "DIFF", self.root / "diff"),
                        mock.patch.object(runtime, "sync_tree", side_effect=self.sync)):
            patcher.start()
            self.addCleanup(patcher.stop)

    @staticmethod
    def sync(source, target, *excludes, exact=False):
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(source, target)

    def land(self, dimension, *chunks):
        namespace, name = dimension.split(":")
        write_region(self.world / "dimensions" / namespace / name / "region" / "r.0.0.mca", list(chunks))

    def check(self, patches):
        before = shadow.copy_regions("before")
        self.change()
        after = shadow.copy_regions("after")
        real_run = runtime.run
        with mock.patch.object(runtime, "run", side_effect=lambda command, **fields: real_run([sys.executable, str(GATES / "world_diff.py"), *command[2:]], **fields)):
            shadow.run_diff(before, after, patches)

    def change(self):
        pass

    def test_a_block_of_ours_in_a_dimension_it_isnt_for_is_refused(self):
        self.land("minecraft:overworld", (0, 0, chunk(0, 0)))
        self.land("gm:d0001", (0, 0, chunk(0, 0)))
        self.change = lambda: self.land("minecraft:overworld", (0, 0, chunk(0, 0, ("minecraft:stone", ORE))))
        with self.assertRaises(GateFailed) as caught:
            self.check([{"block": ORE, "replaces": ["minecraft:stone"], "dimension": "gm:d0001"}])
        self.assertIn("minecraft:overworld", caught.exception.message)

    def test_a_patch_is_fine_in_the_dimension_its_for(self):
        self.land("minecraft:overworld", (0, 0, chunk(0, 0)))
        self.land("gm:d0001", (0, 0, chunk(0, 0)))
        self.change = lambda: self.land("gm:d0001", (0, 0, chunk(0, 0, ("minecraft:stone", ORE))))
        self.check([{"block": ORE, "replaces": ["minecraft:stone"], "dimension": "gm:d0001"}])

    def test_a_patch_with_no_dimension_is_for_the_overworld(self):
        self.land("minecraft:overworld", (0, 0, chunk(0, 0)))
        self.change = lambda: self.land("minecraft:overworld", (0, 0, chunk(0, 0, ("minecraft:stone", ORE))))
        self.check([{"block": ORE, "replaces": ["minecraft:stone"]}])

    def test_a_dimension_that_vanishes_is_refused_whether_or_not_a_patch_is_for_it(self):
        self.land("minecraft:overworld", (0, 0, chunk(0, 0)))
        self.land("gm:d0001", (0, 0, chunk(0, 0)))
        self.change = lambda: shutil.rmtree(self.world / "dimensions" / "gm")
        with self.assertRaises(GateFailed) as caught:
            self.check([{"block": ORE, "replaces": ["minecraft:stone"]}])
        self.assertIn("gm:d0001", caught.exception.message)
        self.assertIn("chunks lost", caught.exception.message)

    def test_a_copy_from_an_earlier_run_cant_hide_a_vanished_dimension(self):
        self.land("gm:d0001", (0, 0, chunk(0, 0)))
        shadow.copy_regions("after")
        shutil.rmtree(self.world / "dimensions" / "gm" / "d0001")
        self.land("minecraft:overworld", (0, 0, chunk(0, 0)))
        after = shadow.copy_regions("after")
        self.assertFalse((after / "gm" / "d0001").exists())

    def test_a_dimension_with_no_land_yet_needs_no_copy(self):
        (self.world / "dimensions" / "gm" / "d0001").mkdir(parents=True)
        self.assertFalse((shadow.copy_regions("before") / "gm" / "d0001").exists())

    def test_vanillas_blocks_can_form_by_themselves_elsewhere(self):
        rules = shadow.diff_rules([{"block": "minecraft:cobblestone", "replaces": ["minecraft:air"], "dimension": "gm:d0001"}], "minecraft:overworld")
        self.assertEqual(rules, {})

    def test_a_ruins_rooms_arent_held_to_anything(self):
        self.assertEqual(shadow.diff_rules([{"block": "minecraft:air", "replaces": ["minecraft:stone"]}], "minecraft:overworld"), {})

    def test_several_patches_of_one_block_add_up_in_their_dimension(self):
        patches = [{"block": ORE, "replaces": ["minecraft:stone"]}, {"block": ORE, "replaces": ["minecraft:air"]}, {"block": ORE, "replaces": ["minecraft:dirt"], "dimension": "gm:d0001"}]
        self.assertEqual(shadow.diff_rules(patches, "minecraft:overworld"), {ORE: ["minecraft:air", "minecraft:stone"]})
        self.assertEqual(shadow.diff_rules(patches, "gm:d0001"), {ORE: ["minecraft:dirt"]})


class WorldDiff(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.before, self.after = pathlib.Path(folder.name) / "before", pathlib.Path(folder.name) / "after"
        # The limit applies to the whole process, which here would be the test run.
        patcher = mock.patch.object(world_diff.resource, "setrlimit")
        patcher.start()
        self.addCleanup(patcher.stop)

    def check(self):
        return self.check_with(["--ore", ORE, "--allow", "minecraft:stone"])

    def check_with(self, arguments):
        output = io.StringIO()
        code = 0
        argv = ["world_diff.py", str(self.before), str(self.after), *arguments]
        with mock.patch.object(sys, "argv", argv), contextlib.redirect_stdout(output):
            try:
                world_diff.main()
            except SystemExit as stop:
                code = stop.code
        return code, output.getvalue()

    def test_an_identical_world_passes_without_parsing_anything(self):
        for folder in (self.before, self.after):
            write_region(folder / "r.0.0.mca", [(0, 0, chunk(0, 0)), (1, 0, chunk(1, 0))])
        with mock.patch.object(world_diff, "read_nbt") as parsing:
            code, output = self.check()
        self.assertEqual(code, 0, output)
        parsing.assert_not_called()
        self.assertIn("chunks compared: 2", output)

    def test_ore_replacing_what_it_may_passes(self):
        write_region(self.before / "r.0.0.mca", [(0, 0, chunk(0, 0))])
        write_region(self.after / "r.0.0.mca", [(0, 0, chunk(0, 0, ("minecraft:stone", ORE)))])
        code, output = self.check()
        self.assertEqual(code, 0, output)
        self.assertIn("1 blocks placed", output)
        self.assertIn("chunks compared: 1", output)

    def test_ore_replacing_anything_else_fails(self):
        write_region(self.before / "r.0.0.mca", [(0, 0, chunk(0, 0, ("minecraft:dirt",)))])
        write_region(self.after / "r.0.0.mca", [(0, 0, chunk(0, 0, ("minecraft:dirt", ORE)))])
        code, output = self.check()
        self.assertEqual(code, 1, output)
        self.assertIn("ore placed somewhere not allowed", output)

    def test_a_lost_chunk_fails(self):
        write_region(self.before / "r.0.0.mca", [(0, 0, chunk(0, 0)), (1, 0, chunk(1, 0))])
        write_region(self.after / "r.0.0.mca", [(0, 0, chunk(0, 0))])
        code, output = self.check()
        self.assertEqual(code, 1, output)
        self.assertIn("1 chunks lost", output)

    def test_a_lost_region_fails(self):
        write_region(self.before / "r.0.0.mca", [(0, 0, chunk(0, 0))])
        self.after.mkdir()
        code, output = self.check()
        self.assertEqual(code, 1, output)
        self.assertIn("1 chunks lost", output)

    def test_rules_check_each_block_by_what_it_may_replace(self):
        write_region(self.before / "r.0.0.mca", [(0, 0, chunk(0, 0)), (1, 0, chunk(1, 0, ("minecraft:dirt",)))])
        write_region(self.after / "r.0.0.mca", [(0, 0, chunk(0, 0, ("minecraft:stone", ORE))), (1, 0, chunk(1, 0, ("minecraft:dirt", "gm:s0002")))])
        rules = self.before.parent / "rules.json"
        rules.write_text(json.dumps({ORE: ["minecraft:stone"], "gm:s0002": ["minecraft:dirt"]}), encoding="utf-8")
        code, output = self.check_with(["--rules", str(rules)])
        self.assertEqual(code, 0, output)
        self.assertIn("2 blocks placed", output)
        rules.write_text(json.dumps({ORE: ["minecraft:stone"], "gm:s0002": []}), encoding="utf-8")
        code, output = self.check_with(["--rules", str(rules)])
        self.assertEqual(code, 1, output)
        self.assertIn("1 ore placed somewhere not allowed", output)

    def test_natural_means_anything_in_a_chunk_nobody_has_been_in(self):
        write_region(self.before / "r.0.0.mca", [(0, 0, chunk(0, 0, ("minecraft:dirt",)))])
        write_region(self.after / "r.0.0.mca", [(0, 0, chunk(0, 0, ("minecraft:dirt", ORE)))])
        rules = self.before.parent / "rules.json"
        rules.write_text(json.dumps({ORE: ["natural"]}), encoding="utf-8")
        code, output = self.check_with(["--rules", str(rules)])
        self.assertEqual(code, 0, output)

    def test_natural_doesnt_reach_a_chunk_someone_has_been_in(self):
        write_region(self.before / "r.0.0.mca", [(0, 0, chunk(0, 0, ("minecraft:dirt",), inhabited=500))])
        write_region(self.after / "r.0.0.mca", [(0, 0, chunk(0, 0, ("minecraft:dirt", ORE), inhabited=500))])
        rules = self.before.parent / "rules.json"
        rules.write_text(json.dumps({ORE: ["natural"]}), encoding="utf-8")
        code, output = self.check_with(["--rules", str(rules)])
        self.assertEqual(code, 1, output)
        self.assertIn("not allowed", output)

    def test_a_vanilla_block_getting_somewhere_by_itself_isnt_a_patch(self):
        # Sand falls into water by itself, and the mod records that as a change, which a patch never is.
        write_region(self.before / "r.0.0.mca", [(0, 0, chunk(0, 0, ("minecraft:water",)))])
        write_region(self.after / "r.0.0.mca", [(0, 0, chunk(0, 0, ("minecraft:water", "minecraft:sand"), touched=True))])
        rules = self.before.parent / "rules.json"
        rules.write_text(json.dumps({"minecraft:sand": ["minecraft:air"]}), encoding="utf-8")
        code, output = self.check_with(["--rules", str(rules)])
        self.assertEqual(code, 0, output)

    def test_a_vanilla_block_where_it_shouldnt_be_with_no_record_is_still_refused(self):
        write_region(self.before / "r.0.0.mca", [(0, 0, chunk(0, 0, ("minecraft:water",)))])
        write_region(self.after / "r.0.0.mca", [(0, 0, chunk(0, 0, ("minecraft:water", "minecraft:sand")))])
        rules = self.before.parent / "rules.json"
        rules.write_text(json.dumps({"minecraft:sand": ["minecraft:air"]}), encoding="utf-8")
        code, output = self.check_with(["--rules", str(rules)])
        self.assertEqual(code, 1, output)

    def test_this_worlds_own_blocks_cant_get_there_by_themselves(self):
        write_region(self.before / "r.0.0.mca", [(0, 0, chunk(0, 0, ("minecraft:water",)))])
        write_region(self.after / "r.0.0.mca", [(0, 0, chunk(0, 0, ("minecraft:water", ORE), touched=True))])
        rules = self.before.parent / "rules.json"
        rules.write_text(json.dumps({ORE: ["minecraft:stone"]}), encoding="utf-8")
        code, output = self.check_with(["--rules", str(rules)])
        self.assertEqual(code, 1, output)

    def test_it_has_to_be_told_the_rules(self):
        write_region(self.before / "r.0.0.mca", [(0, 0, chunk(0, 0))])
        write_region(self.after / "r.0.0.mca", [(0, 0, chunk(0, 0))])
        with contextlib.redirect_stderr(io.StringIO()):
            code, _ = self.check_with([])
        self.assertEqual(code, 2)

    def test_every_dimension_in_a_world_is_found(self):
        world = self.before.parent / "world"
        for name in ("minecraft/overworld", "minecraft/the_nether", "gm/d0001"):
            (world / "dimensions" / name / "region").mkdir(parents=True)
        (world / "dimensions" / "gm" / "d0002").mkdir()
        self.assertEqual(sorted(world_diff.dimension_folders(world)), ["gm:d0001", "gm:d0002", "minecraft:overworld", "minecraft:the_nether"])

    def test_a_dimension_gone_from_the_copy_after_is_land_lost(self):
        write_region(self.before / "r.0.0.mca", [(0, 0, chunk(0, 0))])
        code, output = self.check()
        self.assertEqual(code, 1, output)
        self.assertIn("1 chunks lost", output)

    def test_a_dimension_new_to_the_copy_after_has_nothing_to_compare(self):
        self.before.mkdir()
        write_region(self.after / "r.0.0.mca", [(0, 0, chunk(0, 0, ("minecraft:dirt", ORE)))])
        code, output = self.check()
        self.assertEqual(code, 0, output)

    def test_a_lost_chest_fails(self):
        write_region(self.before / "r.0.0.mca", [(0, 0, chunk(0, 0, chests=[(1, 2, 3)]))])
        write_region(self.after / "r.0.0.mca", [(0, 0, chunk(0, 0))])
        code, output = self.check()
        self.assertEqual(code, 1, output)
        self.assertIn("block entities changed", output)


if __name__ == "__main__":
    unittest.main()
