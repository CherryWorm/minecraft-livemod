package gm.conduit.retrogen;

import com.google.gson.Gson;
import com.google.gson.JsonParseException;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.core.registries.Registries;
import net.minecraft.resources.Identifier;
import net.minecraft.resources.ResourceKey;
import net.minecraft.world.level.biome.Biome;
import net.minecraft.world.level.block.Block;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
import java.util.Set;
import java.util.stream.Collectors;

/**
 * A small built thing that turns up in the world: a ruin, a shrine, a wreck. Only ever appears in a chunk
 * nobody has been in, because something appearing where people have already looked would be noticed. It must fit
 * in one chunk, which keeps placement simple and predictable and is plenty for something to stumble on.
 *
 * @param chance how likely a chunk is to get one, from 0 to 1
 * @param on what it can sit on, checked under its origin
 * @param replaces what its blocks may overwrite, so it never cuts through something unexpected
 * @param loot a loot table for any chest in it, or null
 */
public record RuinPatch(String id, List<Part> parts, Set<Block> on, Set<Block> replaces, float chance, int minY, int maxY,
		boolean underground, Set<ResourceKey<Biome>> biomes, String loot) {
	private static final Path FILE = Path.of("config", "conduit", "ruin_patches.json");
	private static final int CHUNK_SIDE = 16;

	public record Part(int x, int y, int z, Block block) {}

	private record PartDefinition(int x, int y, int z, String block) {}

	private record Definition(String id, List<PartDefinition> parts, List<String> on, List<String> replaces, float chance, int minY, int maxY,
			boolean underground, List<String> biomes, String loot) {}

	static List<RuinPatch> load() {
		if (!Files.exists(FILE)) {
			return List.of();
		}
		try {
			Definition[] definitions = new Gson().fromJson(Files.readString(FILE), Definition[].class);
			return List.of(definitions).stream().map(RuinPatch::resolve).toList();
		} catch (IOException | JsonParseException error) {
			throw new IllegalStateException("Can't read " + FILE, error);
		}
	}

	private static RuinPatch resolve(Definition definition) {
		for (PartDefinition part : definition.parts()) {
			if (part.x() < 0 || part.x() >= CHUNK_SIDE || part.z() < 0 || part.z() >= CHUNK_SIDE) {
				throw new IllegalStateException("Ruin " + definition.id() + " doesn't fit in one chunk");
			}
		}
		List<String> biomes = definition.biomes() == null ? List.of() : definition.biomes();
		return new RuinPatch(
				definition.id(),
				definition.parts().stream().map(part -> new Part(part.x(), part.y(), part.z(), block(part.block()))).toList(),
				definition.on().stream().map(RuinPatch::block).collect(Collectors.toUnmodifiableSet()),
				definition.replaces().stream().map(RuinPatch::block).collect(Collectors.toUnmodifiableSet()),
				definition.chance(),
				definition.minY(),
				definition.maxY(),
				definition.underground(),
				biomes.stream().map(id -> ResourceKey.create(Registries.BIOME, Identifier.parse(id))).collect(Collectors.toUnmodifiableSet()),
				definition.loot());
	}

	private static Block block(String id) {
		return BuiltInRegistries.BLOCK.getOptional(Identifier.parse(id))
				.orElseThrow(() -> new IllegalStateException("Unknown block in ruin: " + id));
	}
}
