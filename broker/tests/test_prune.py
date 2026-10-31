#!/usr/bin/env python3
"""The pruning tool on region files built here, in the game's own format. Needs no server."""
import pathlib
import struct
import sys
import tempfile
import unittest
import zlib

from broker import prune

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "gates"))
import world_diff  # noqa: E402

SECTOR = 4096
TAG_INT, TAG_LONG, TAG_LIST, TAG_COMPOUND = 3, 4, 9, 10


def _name(text):
    encoded = text.encode()
    return struct.pack(">H", len(encoded)) + encoded


def chunk_bytes(x, z, inhabited=0, touched=False):
    body = (bytes([TAG_INT]) + _name("xPos") + struct.pack(">i", x)
            + bytes([TAG_INT]) + _name("zPos") + struct.pack(">i", z)
            + bytes([TAG_LONG]) + _name("InhabitedTime") + struct.pack(">q", inhabited))
    if touched:
        section = bytes([12]) + _name("bits") + struct.pack(">i", 1) + struct.pack(">q", 1) + b"\0"
        touched_list = bytes([TAG_LIST]) + _name("gm:touched") + bytes([TAG_COMPOUND]) + struct.pack(">i", 1) + section
        body += bytes([TAG_COMPOUND]) + _name("fabric:attachments") + touched_list + b"\0"
    return bytes([TAG_COMPOUND]) + _name("") + body + b"\0"


def write_region(path, chunks):
    header = bytearray(SECTOR * 2)
    data = bytearray()
    sector = 2
    for raw in chunks:
        x, z = raw["x"], raw["z"]
        packed = zlib.compress(chunk_bytes(x, z, raw.get("inhabited", 0), raw.get("touched", False)))
        record = struct.pack(">IB", len(packed) + 1, 2) + packed
        sectors = (len(record) + SECTOR - 1) // SECTOR
        struct.pack_into(">I", header, ((x & 31) + (z & 31) * 32) * 4, (sector << 8) | sectors)
        struct.pack_into(">I", header, SECTOR + ((x & 31) + (z & 31) * 32) * 4, 1)
        data += record.ljust(sectors * SECTOR, b"\0")
        sector += sectors
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(bytes(header) + bytes(data))


def positions(path):
    return {(x, z) for x, z, _ in world_diff.read_chunks(path)}


class Prune(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.world = pathlib.Path(folder.name)
        self.chunks = [
            {"x": 0, "z": 0, "inhabited": 500},   # someone has been here
            {"x": 2, "z": 0},                     # beside it, so regenerating would show a seam
            {"x": 20, "z": 20, "touched": True},  # nobody stood here, but a block was changed
            {"x": 21, "z": 21},                   # beside that
            {"x": 30, "z": 5},                    # nobody near it at all
            {"x": 31, "z": 31},                   # and this
        ]
        for name in prune.FOLDERS:
            write_region(self.world / name / "r.0.0.mca", self.chunks)
        self.region = self.world / "region" / "r.0.0.mca"

    def test_only_land_far_from_anyone_goes(self):
        result = prune.prune(self.world, margin=3)
        self.assertEqual(result["pruned"], 2)
        self.assertEqual(positions(self.region), {(0, 0), (2, 0), (20, 20), (21, 21)})

    def test_every_store_for_a_chunk_is_cleared(self):
        prune.prune(self.world, margin=3)
        for name in prune.FOLDERS:
            self.assertNotIn((30, 5), positions(self.world / name / "r.0.0.mca"), name)

    def test_a_dry_run_changes_nothing(self):
        before = self.region.read_bytes()
        result = prune.prune(self.world, margin=3, dry_run=True)
        self.assertEqual(result["pruned"], 2)
        self.assertEqual(self.region.read_bytes(), before)

    def test_what_stays_is_still_readable_afterwards(self):
        prune.prune(self.world, margin=3)
        for x, z, chunk in world_diff.read_chunks(self.region):
            self.assertEqual((chunk["xPos"], chunk["zPos"]), (x, z))

    def test_a_wide_margin_keeps_everything(self):
        self.assertEqual(prune.prune(self.world, margin=32)["pruned"], 0)
        self.assertEqual(len(positions(self.region)), len(self.chunks))

    def test_a_negative_region_lands_in_the_right_file(self):
        write_region(self.world / "region" / "r.-1.-1.mca", [{"x": -1, "z": -1}])
        write_region(self.world / "region" / "r.0.0.mca", [{"x": 31, "z": 31, "inhabited": 5}])
        prune.prune(self.world, margin=2)
        self.assertEqual(positions(self.world / "region" / "r.-1.-1.mca"), set())


if __name__ == "__main__":
    unittest.main()
