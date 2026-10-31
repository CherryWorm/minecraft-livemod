#!/usr/bin/env python3
"""Compares two copies of a world by reading the raw region files.

This is the safety check for retroactive worldgen. It deliberately shares no code with the mod, so a
bug in the engine can't hide itself. Fails if our block appears anywhere it wasn't allowed to, if
anything changed inside a protected volume, or if any block entity (chests and so on) changed.

Usage: world_diff.py BEFORE AFTER --ore gm:s0001 --allow minecraft:stone minecraft:deepslate
                     [--protect X1 Y1 Z1 X2 Y2 Z2]... [--report-limit N]
BEFORE and AFTER are folders holding .mca files.
"""
import argparse
import collections
import gzip
import json
import math
import pathlib
import struct
import sys
import zlib


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


def read_chunks(path):
    """Yields (chunk x, chunk z, chunk data) for every chunk in one region file."""
    raw = path.read_bytes()
    if len(raw) < 8192:
        return
    for index in range(1024):
        location = struct.unpack_from(">I", raw, index * 4)[0]
        offset, sectors = location >> 8, location & 0xFF
        if not offset or not sectors:
            continue
        start = offset * 4096
        length = struct.unpack_from(">I", raw, start)[0]
        kind = raw[start + 4]
        body = raw[start + 5:start + 4 + length]
        data = gzip.decompress(body) if kind == 1 else zlib.decompress(body) if kind == 2 else body
        chunk = read_nbt(data)
        yield chunk.get("xPos"), chunk.get("zPos"), chunk


def load_world(folder):
    chunks = {}
    for path in sorted(pathlib.Path(folder).glob("*.mca")):
        for x, z, chunk in read_chunks(path):
            chunks[(x, z)] = chunk
    return chunks


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


# Timers the game itself advances, so they change with nobody touching anything. Named one by one, so
# any other change to a block entity still fails the check.
VOLATILE_FIELDS = {
    "minecraft:vault": {"server_data"},
    "minecraft:mob_spawner": {"Delay"},
    "minecraft:trial_spawner": {"cooldown_ends_at", "next_mob_spawns_at", "total_mobs_spawned"},
    "minecraft:sculk_catalyst": {"cursors"},
    "minecraft:beehive": {"bees", "flower_pos"},
    "minecraft:sculk_shrieker": {"warning_level", "listener"},
    "minecraft:sculk_sensor": {"listener", "last_vibration_frequency"},
    "minecraft:calibrated_sculk_sensor": {"listener", "last_vibration_frequency"},
}


def canonical(entities):
    """Compares block entities by position, since the list order isn't stable, ignoring natural timers."""
    cleaned = [
        {key: value for key, value in entity.items() if key not in VOLATILE_FIELDS.get(entity.get("id"), ())}
        for entity in entities
    ]
    return json.dumps(sorted(cleaned, key=lambda e: (e.get("x"), e.get("y"), e.get("z"))), sort_keys=True)


def touched_blocks(chunk):
    """How many blocks the mod has recorded as changed in this chunk."""
    sections = chunk.get("fabric:attachments", {}).get("gm:touched", [])
    return sum(bin(word & (2**64 - 1)).count("1") for section in sections for word in section.get("bits", []))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("before")
    parser.add_argument("after")
    parser.add_argument("--ore", required=True)
    parser.add_argument("--allow", nargs="+", required=True)
    parser.add_argument("--protect", nargs=6, type=int, action="append", default=[])
    parser.add_argument("--report-limit", type=int, default=8)
    args = parser.parse_args()

    before = load_world(args.before)
    after = load_world(args.after)
    allowed = set(args.allow)
    protected = [tuple(box) for box in args.protect]

    transitions = collections.Counter()
    bad_ore = []
    bad_protected = []
    bad_entities = []
    forgotten = []
    chunks_with_ore = 0
    unfinished = 0
    missing = [pos for pos in before if pos not in after]

    def in_protected(x, y, z):
        return any(
            min(a, d) <= x <= max(a, d) and min(b, e) <= y <= max(b, e) and min(c, f) <= z <= max(c, f)
            for a, b, c, d, e, f in protected
        )

    for pos, old in before.items():
        new = after.get(pos)
        if new is None:
            continue
        # Land still being generated when the copy was taken hasn't been seen by anyone, and carries on changing.
        if old.get("Status") != "minecraft:full":
            unfinished += 1
            continue
        if canonical(old.get("block_entities", [])) != canonical(new.get("block_entities", [])):
            bad_entities.append(pos)
        # Touched records can only ever grow. Shrinking means the mod forgot what players did.
        if touched_blocks(new) < touched_blocks(old):
            forgotten.append((pos, touched_blocks(old), touched_blocks(new)))
        old_sections, new_sections = sections_by_y(old), sections_by_y(new)
        placed_here = 0
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
                if new_name == args.ore:
                    placed_here += 1
                    if old_name not in allowed:
                        bad_ore.append((x, y, z, old_name))
                if in_protected(x, y, z):
                    bad_protected.append((x, y, z, old_name, new_name))
        chunks_with_ore += placed_here > 0

    print(f"chunks compared: {len(before) - len(missing) - unfinished}, still generating when copied: {unfinished}, "
          f"chunks missing afterwards: {len(missing)}")
    ore_total = sum(count for (_, new_name), count in transitions.items() if new_name == args.ore)
    print(f"chunks that received ore: {chunks_with_ore}, {ore_total} blocks placed")
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
