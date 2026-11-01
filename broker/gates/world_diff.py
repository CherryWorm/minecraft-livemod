#!/usr/bin/env python3
"""Compares two copies of a world by reading the raw region files.

This is the safety check for retroactive worldgen. It deliberately shares no code with the mod, so a
bug in the engine can't hide itself. Fails if our block appears anywhere it wasn't allowed to, if
anything changed inside a protected volume, or if any block entity (chests and so on) changed.

Goes through the worlds one chunk at a time, and doesn't parse a chunk whose stored bytes are the same in both. A parsed
chunk takes far more memory than it does on disk, so a world people have really played wouldn't fit if it were all loaded.

Usage: world_diff.py BEFORE AFTER --ore gm:s0001 --allow minecraft:stone minecraft:deepslate
                     [--protect X1 Y1 Z1 X2 Y2 Z2]... [--report-limit N]
       world_diff.py BEFORE AFTER --rules RULES.json
BEFORE and AFTER are folders holding .mca files, from one dimension. RULES.json says what each block may replace, as
{"gm:s0001": ["minecraft:stone"]}, which checks them all in one pass, and an empty list means it shouldn't appear at all.
"natural" in the list lets it replace anything at all in a chunk nobody had been in or changed anything in, which the raw files can show.
"""
import argparse
import collections
import gzip
import json
import math
import pathlib
import resource
import struct
import sys
import zlib

# Far more than one region at a time needs. Going over fails this check, instead of the system killing whatever it chooses.
MEMORY_LIMIT = 2 * 1024 ** 3
# In place of a block it may replace: it can replace anything in a chunk nobody had been in or changed anything in.
NATURAL = "natural"


def dimension_folders(world):
    """Every dimension in a world, by its name, whether or not it has any land yet. Each keeps its own region files, so a
    check of one tells you nothing about the others."""
    world = pathlib.Path(world)
    found = {f"{folder.parent.name}:{folder.name}": folder for folder in sorted(world.glob("dimensions/*/*")) if folder.is_dir()}
    # Worlds from before the game moved these have the overworld's right there.
    if (world / "region").is_dir():
        found.setdefault("minecraft:overworld", world)
    return found


def read_nbt(data):
    """Reads a whole NBT document into Python values."""
    pos = 0

    def take(fmt):
        nonlocal pos
        value = struct.unpack_from(">" + fmt, data, pos)[0]
        pos += struct.calcsize(">" + fmt)
        return value

    def string():
        nonlocal pos
        length = take("H")
        text = data[pos:pos + length].decode("utf-8", "replace")
        pos += length
        return text

    def array(fmt):
        nonlocal pos
        count = take("i")
        size = struct.calcsize(">" + fmt)
        values = struct.unpack_from(f">{count}{fmt}", data, pos)
        pos += count * size
        return list(values)

    def payload(kind):
        if kind == 1:
            return take("b")
        if kind == 2:
            return take("h")
        if kind == 3:
            return take("i")
        if kind == 4:
            return take("q")
        if kind == 5:
            return take("f")
        if kind == 6:
            return take("d")
        if kind == 7:
            return array("b")
        if kind == 8:
            return string()
        if kind == 9:
            inner = take("b")
            return [payload(inner) for _ in range(take("i"))]
        if kind == 10:
            out = {}
            while (tag := take("b")) != 0:
                name = string()
                out[name] = payload(tag)
            return out
        if kind == 11:
            return array("i")
        if kind == 12:
            return array("q")
        raise ValueError(f"unknown NBT tag {kind}")

    root = take("b")
    string()
    return payload(root)


def stored_chunks(path):
    """Every chunk in one region file as it's stored, compression and bytes, by its place in the file."""
    raw = path.read_bytes()
    if len(raw) < 8192:
        return {}
    stored = {}
    for index in range(1024):
        location = struct.unpack_from(">I", raw, index * 4)[0]
        offset, sectors = location >> 8, location & 0xFF
        if not offset or not sectors:
            continue
        start = offset * 4096
        length = struct.unpack_from(">I", raw, start)[0]
        stored[index] = (raw[start + 4], raw[start + 5:start + 4 + length])
    return stored


def parse_chunk(kind, body):
    data = gzip.decompress(body) if kind == 1 else zlib.decompress(body) if kind == 2 else body
    return read_nbt(data)


def read_chunks(path):
    """Yields (chunk x, chunk z, chunk data) for every chunk in one region file."""
    for kind, body in stored_chunks(path).values():
        chunk = parse_chunk(kind, body)
        yield chunk.get("xPos"), chunk.get("zPos"), chunk


def chunk_pairs(before, after):
    """Yields (position, old, new) for every chunk in the first world that isn't identical in the second, one at a time.
    A chunk's place in a region file follows from where it is, so the same file and place is the same chunk. New is None
    if it's gone. Ends with (None, how many were identical, None)."""
    skipped = 0
    for path in sorted(pathlib.Path(before).glob("*.mca")):
        other = pathlib.Path(after) / path.name
        new_stored = stored_chunks(other) if other.exists() else {}
        for index, old_stored in stored_chunks(path).items():
            new = new_stored.get(index)
            if new == old_stored:
                skipped += 1
                continue
            old = parse_chunk(*old_stored)
            yield (old.get("xPos"), old.get("zPos")), old, parse_chunk(*new) if new else None
    yield None, skipped, None


def block_name(entry):
    """Palette entries are a bare string, a string wrapped under an empty key, or a compound with an id."""
    if isinstance(entry, str):
        return entry
    for key in ("id", "", "Name"):
        if key in entry:
            return entry[key]
    raise ValueError(f"unknown palette entry: {entry}")


def decode(section):
    """Returns the section's 4096 block indexes and its palette of names."""
    states = section.get("block_states", {})
    palette = [block_name(entry) for entry in states.get("palette", [{"Name": "minecraft:air"}])]
    data = states.get("data")
    if not data:
        return [0] * 4096, palette
    bits = max(4, math.ceil(math.log2(len(palette))) if len(palette) > 1 else 4)
    per_long = 64 // bits
    mask = (1 << bits) - 1
    out = []
    for value in data:
        value &= (1 << 64) - 1
        for _ in range(per_long):
            out.append(value & mask)
            value >>= bits
            if len(out) == 4096:
                return out, palette
    return out, palette


def sections_by_y(chunk):
    return {section["Y"]: section for section in chunk.get("sections", [])}


# What a world would really lose: anything that holds items, plus our own machines. Most other block entities carry timers
# the game advances by itself, and every new Minecraft adds more of them, so comparing those would refuse good releases in
# any world that happens to contain one. The contents aren't compared either, because a furnace or hopper can be busy while
# a chunk is loaded. A patch can only change blocks, so it can only harm these by replacing them, and that's what's checked.
HOLDS_THINGS = {"minecraft:chest", "minecraft:trapped_chest", "minecraft:barrel", "minecraft:shulker_box", "minecraft:hopper", "minecraft:dispenser",
                "minecraft:dropper", "minecraft:furnace", "minecraft:blast_furnace", "minecraft:smoker", "minecraft:brewing_stand", "minecraft:lectern",
                "minecraft:chiseled_bookshelf", "minecraft:decorated_pot", "minecraft:crafter", "minecraft:shelf"}


def holders(entities):
    """Where things that hold items are, and what they are."""
    return {(entity.get("x"), entity.get("y"), entity.get("z")): entity.get("id") for entity in entities
            if entity.get("id") in HOLDS_THINGS or str(entity.get("id")).startswith("gm:")}


def entities_kept(old, new, allow_added):
    """Whether everything holding items is still there. A ruin adds a chest of its own, and that's the only reason to allow one."""
    before, after = holders(old), holders(new)
    if any(after.get(position) != kind for position, kind in before.items()):
        return False
    return allow_added or before.keys() == after.keys()


def touched_blocks(chunk):
    """How many blocks the mod has recorded as changed in this chunk."""
    sections = chunk.get("fabric:attachments", {}).get("gm:touched", [])
    return sum(bin(word & (2**64 - 1)).count("1") for section in sections for word in section.get("bits", []))


def peak_memory():
    """The most this has used, in MB. What getrusage says would include whatever started it."""
    for line in pathlib.Path("/proc/self/status").read_text(encoding="utf-8").splitlines():
        if line.startswith("VmHWM:"):
            return int(line.split()[1]) // 1024
    return 0


def is_touched(chunk, x, y, z):
    """Whether the mod recorded this block as having changed since the land was made."""
    index = (y & 15) << 8 | (z & 15) << 4 | x & 15
    for section in chunk.get("fabric:attachments", {}).get("gm:touched", []):
        bits = section.get("bits", [])
        if section.get("y") == y >> 4 and index // 64 < len(bits):
            return bool((bits[index // 64] >> (index % 64)) & 1)
    return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("before")
    parser.add_argument("after")
    parser.add_argument("--ore")
    parser.add_argument("--allow", nargs="+")
    parser.add_argument("--rules", type=pathlib.Path)
    parser.add_argument("--protect", nargs=6, type=int, action="append", default=[])
    parser.add_argument("--report-limit", type=int, default=8)
    parser.add_argument("--allow-new-block-entities", action="store_true", help="existing ones must still be unchanged")
    args = parser.parse_args()

    resource.setrlimit(resource.RLIMIT_AS, (MEMORY_LIMIT, MEMORY_LIMIT))
    if args.rules is None and not (args.ore and args.allow):
        parser.error("say what can replace what, with --rules or with --ore and --allow")
    allowed = {block: set(replaces) for block, replaces in json.loads(args.rules.read_text(encoding="utf-8")).items()} if args.rules else {args.ore: set(args.allow)}
    protected = [tuple(box) for box in args.protect]

    transitions = collections.Counter()
    bad_ore = []
    bad_protected = []
    bad_entities = []
    forgotten = []
    chunks_with_ore = 0
    unfinished = 0
    compared = 0
    missing = []

    def in_protected(x, y, z):
        return any(
            min(a, d) <= x <= max(a, d) and min(b, e) <= y <= max(b, e) and min(c, f) <= z <= max(c, f)
            for a, b, c, d, e, f in protected
        )

    for pos, old, new in chunk_pairs(args.before, args.after):
        if pos is None:
            compared += old
            continue
        if new is None:
            missing.append(pos)
            continue
        # Land still being generated when the copy was taken hasn't been seen by anyone, and carries on changing.
        if old.get("Status") != "minecraft:full":
            unfinished += 1
            continue
        compared += 1
        if not entities_kept(old.get("block_entities", []), new.get("block_entities", []), args.allow_new_block_entities):
            bad_entities.append(pos)
        # Touched records can only ever grow. Shrinking means the mod forgot what players did.
        if touched_blocks(new) < touched_blocks(old):
            forgotten.append((pos, touched_blocks(old), touched_blocks(new)))
        old_sections, new_sections = sections_by_y(old), sections_by_y(new)
        placed_here = 0
        nobody_there = old.get("InhabitedTime", 0) == 0 and touched_blocks(old) == 0
        for y_index, old_section in old_sections.items():
            new_section = new_sections.get(y_index)
            if new_section is None:
                continue
            if old_section.get("block_states") == new_section.get("block_states"):
                continue
            old_blocks, old_palette = decode(old_section)
            new_blocks, new_palette = decode(new_section)
            for index in range(4096):
                old_name = old_palette[old_blocks[index]]
                new_name = new_palette[new_blocks[index]]
                if old_name == new_name:
                    continue
                x = pos[0] * 16 + (index & 15)
                z = pos[1] * 16 + ((index >> 4) & 15)
                y = y_index * 16 + ((index >> 8) & 15)
                transitions[(old_name, new_name)] += 1
                if new_name in allowed:
                    placed_here += 1
                    # Vanilla's blocks can get there by themselves, like sand falling into water. A patch never records what it does as a
                    # change, so if this was recorded, it wasn't one. This world's own blocks can't do that, so they don't get this.
                    by_itself = not new_name.startswith("gm:") and is_touched(new, x, y, z)
                    if old_name not in allowed[new_name] and not (NATURAL in allowed[new_name] and nobody_there) and not by_itself:
                        bad_ore.append((x, y, z, old_name, new_name))
                if in_protected(x, y, z):
                    bad_protected.append((x, y, z, old_name, new_name))
        chunks_with_ore += placed_here > 0

    print(f"chunks compared: {compared}, still generating when copied: {unfinished}, "
          f"chunks missing afterwards: {len(missing)}")
    ore_total = sum(count for (_, new_name), count in transitions.items() if new_name in allowed)
    print(f"chunks that received ore: {chunks_with_ore}, {ore_total} blocks placed")
    print(f"peak memory: {peak_memory()} MB")
    print("block changes:")
    for (old_name, new_name), count in transitions.most_common(20):
        print(f"  {count:>8}  {old_name} -> {new_name}")
    if not transitions:
        print("  (none)")

    failed = False
    for label, items in (
        ("ore placed somewhere not allowed", bad_ore),
        ("changes inside a protected volume", bad_protected),
        ("chunks whose block entities changed", bad_entities),
        ("chunks that forgot touched blocks", forgotten),
        ("chunks lost", missing),
    ):
        if items:
            failed = True
            print(f"FAIL: {len(items)} {label}, for example {items[:args.report_limit]}")
    if failed:
        sys.exit(1)
    print("PASS")


if __name__ == "__main__":
    main()
