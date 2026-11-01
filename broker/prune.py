#!/usr/bin/env python3
"""Removes generated land nobody has been to, so it regenerates with new content the next time it's reached.

Only for when the server is stopped (tier T4). It reads the region files directly and deletes a chunk by
clearing its entry in the file's header, which is what the game itself reads, so the next visit generates it
fresh. A chunk is kept if anyone has spent time in it, anything in it has been changed, or it's near a chunk
like that, so nothing can regenerate next to someone's base or at the edge of explored land. Each dimension goes
by what's happened in it, and it never removes a dimension itself, only land nobody's been to.

Usage: prune.py WORLD_FOLDER [--margin CHUNKS] [--dimension NAME] [--dry-run]
"""
import argparse
import pathlib
import struct
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent / "gates"))
import world_diff  # noqa: E402

DEFAULT_MARGIN = 8
REGION_SIDE = 32
HEADER_ENTRIES = REGION_SIDE * REGION_SIDE
# Chunks, entities and points of interest are stored apart, and a pruned chunk must go from all of them.
FOLDERS = ("region", "entities", "poi")


def survey(region_folder):
    """Returns every chunk's position, and which of them someone has been in or changed."""
    every = set()
    visited = set()
    for path in sorted(region_folder.glob("*.mca")):
        for x, z, chunk in world_diff.read_chunks(path):
            every.add((x, z))
            # Natural chests exist, so a block entity proves nothing. Any change a player made is a touched block.
            if chunk.get("InhabitedTime", 0) > 0 or world_diff.touched_blocks(chunk) > 0:
                visited.add((x, z))
    return every, visited


def to_prune(every, visited, margin):
    keep = set()
    for x, z in visited:
        for dx in range(-margin, margin + 1):
            for dz in range(-margin, margin + 1):
                keep.add((x + dx, z + dz))
    return sorted(every - keep)


def clear_chunks(folder, chunks):
    """Clears header entries for these chunks. The old data becomes free space the game can reuse."""
    by_region = {}
    for x, z in chunks:
        by_region.setdefault((x >> 5, z >> 5), []).append((x & 31, z & 31))
    cleared = 0
    for (region_x, region_z), local in by_region.items():
        path = folder / f"r.{region_x}.{region_z}.mca"
        if not path.exists():
            continue
        with path.open("r+b") as stream:
            header = bytearray(stream.read(HEADER_ENTRIES * 8))
            if len(header) < HEADER_ENTRIES * 8:
                continue
            for x, z in local:
                index = x + z * REGION_SIDE
                if struct.unpack_from(">I", header, index * 4)[0]:
                    cleared += 1
                struct.pack_into(">I", header, index * 4, 0)
                struct.pack_into(">I", header, HEADER_ENTRIES * 4 + index * 4, 0)
            stream.seek(0)
            stream.write(header)
    return cleared


def prune_dimension(folder, margin, dry_run):
    every, visited = survey(folder / "region")
    chunks = to_prune(every, visited, margin)
    result = {"generated": len(every), "visited": len(visited), "pruned": len(chunks)}
    if not dry_run:
        for name in FOLDERS:
            if (folder / name).is_dir():
                result[f"cleared_{name}"] = clear_chunks(folder / name, chunks)
    return result


def prune(world, margin=DEFAULT_MARGIN, dry_run=False, dimension=None):
    """What it did in each dimension, and the totals."""
    folders = world_diff.dimension_folders(world)
    if dimension is not None and dimension not in folders:
        raise SystemExit(f"This world has no dimension called {dimension}. It has {', '.join(sorted(folders)) or 'none at all'}.")
    results = {name: prune_dimension(folder, margin, dry_run) for name, folder in folders.items() if dimension in (None, name)}
    return {**{field: sum(result[field] for result in results.values()) for field in ("generated", "visited", "pruned")}, "dimensions": results}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("world", type=pathlib.Path)
    parser.add_argument("--margin", type=int, default=DEFAULT_MARGIN)
    parser.add_argument("--dimension", help="only this one, like minecraft:overworld")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    print(prune(args.world, args.margin, args.dry_run, args.dimension))


if __name__ == "__main__":
    main()
