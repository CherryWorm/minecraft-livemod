#!/usr/bin/env python3
"""Writes a data pack with N extra biomes, copied from plains with new colours.

Usage: make_biome_pack.py <server dir> <count>. Biomes are registered but not placed anywhere, which
is enough to test that a changed registry survives a restart with players connected.
"""
import json
import pathlib
import sys
import zipfile


def main():
    server = pathlib.Path(sys.argv[1])
    count = int(sys.argv[2])
    jar = next(server.glob("versions/*/server-*.jar"))
    with zipfile.ZipFile(jar) as archive:
        plains = json.loads(archive.read("data/minecraft/worldgen/biome/plains.json"))
        version = json.loads(archive.read("version.json"))
    data_format = version["pack_version"]["data_major"]

    root = server / "world" / "datapacks" / "s2"
    biomes = root / "data" / "s2" / "worldgen" / "biome"
    biomes.mkdir(parents=True, exist_ok=True)
    (root / "pack.mcmeta").write_text(json.dumps({
        "pack": {"description": "Spike S2", "min_format": data_format, "max_format": data_format},
    }))
    for index in range(1, count + 1):
        biome = json.loads(json.dumps(plains))
        biome.setdefault("effects", {})["water_color"] = (index * 2654435) % 0xFFFFFF
        (biomes / f"b{index:02d}.json").write_text(json.dumps(biome))


if __name__ == "__main__":
    main()
