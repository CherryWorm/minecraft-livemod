#!/usr/bin/env python3
"""The world check on region files built here, in the game's own format. Needs no server."""
import contextlib
import io
import pathlib
import struct
import sys
import tempfile
import unittest
import zlib
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "gates"))
import world_diff  # noqa: E402

SECTOR = 4096
BYTE, INT, STRING, LIST, COMPOUND, LONGS = 1, 3, 8, 9, 10, 12
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


def chunk(x, z, palette=("minecraft:stone",), chests=()):
    entities = b"".join(_string("id", "minecraft:chest")
                        + b"".join(bytes([INT]) + _name(axis) + struct.pack(">i", value) for axis, value in zip("xyz", position)) + b"\0"
                        for position in chests)
    body = (bytes([INT]) + _name("xPos") + struct.pack(">i", x) + bytes([INT]) + _name("zPos") + struct.pack(">i", z)
            + _string("Status", "minecraft:full")
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
        output = io.StringIO()
        code = 0
        argv = ["world_diff.py", str(self.before), str(self.after), "--ore", ORE, "--allow", "minecraft:stone"]
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

    def test_a_lost_chest_fails(self):
        write_region(self.before / "r.0.0.mca", [(0, 0, chunk(0, 0, chests=[(1, 2, 3)]))])
        write_region(self.after / "r.0.0.mca", [(0, 0, chunk(0, 0))])
        code, output = self.check()
        self.assertEqual(code, 1, output)
        self.assertIn("block entities changed", output)


if __name__ == "__main__":
    unittest.main()
