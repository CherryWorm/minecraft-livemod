package gm.conduit.retrogen;

import com.google.gson.Gson;
import com.google.gson.JsonParseException;
import gm.conduit.dimensions.Dimensions;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.core.registries.Registries;
import net.minecraft.resources.Identifier;
import net.minecraft.resources.ResourceKey;
import net.minecraft.world.level.Level;
import net.minecraft.world.level.biome.Biome;
import net.minecraft.world.level.block.Block;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
import java.util.Set;
import java.util.stream.Collectors;

/**
 * Something that grows on the ground, such as a plant, added to chunks old and new. Like ore, it's data, and
 * chunks remember which ids they've had, so an id must never be reused.
 *
 * @param perChunk how many to try for in a chunk, on average. Below 1 means some chunks get none
 * @param underground true for cave floors, false for the open surface
 * @param biomes where it grows, or empty for anywhere
 * @param dimension which one it grows in
 */
public record SurfacePatch(String id, Block block, Set<Block> on, float perChunk, int minY, int maxY, boolean underground, Set<ResourceKey<Biome>> biomes, ResourceKey<Level> dimension) {
	private static final Path FILE = Path.of("config", "conduit", "surface_patches.json");

	private record Definition(String id, String block, List<String> on, float perChunk, int minY, int maxY, boolean underground, List<String> biomes, String dimension) {}

	static List<SurfacePatch> load() {
		if (!Files.exists(FILE)) {
			return List.of();
		}
		try {
			Definition[] definitions = new Gson().fromJson(Files.readString(FILE), Definition[].class);
			return List.of(definitions).stream().map(SurfacePatch::resolve).toList();
		} catch (IOException | JsonParseException error) {
			throw new IllegalStateException("Can't read " + FILE, error);
		}
	}

	private static SurfacePatch resolve(Definition definition) {
		List<String> biomes = definition.biomes() == null ? List.of() : definition.biomes();
		return new SurfacePatch(
				definition.id(),
				block(definition.block()),
				definition.on().stream().map(SurfacePatch::block).collect(Collectors.toUnmodifiableSet()),
				definition.perChunk(),
				definition.minY(),
				definition.maxY(),
				definition.underground(),
				biomes.stream().map(id -> ResourceKey.create(Registries.BIOME, Identifier.parse(id))).collect(Collectors.toUnmodifiableSet()),
				Dimensions.levelKey(definition.dimension()));
	}

	private static Block block(String id) {
		return BuiltInRegistries.BLOCK.getOptional(Identifier.parse(id))
				.orElseThrow(() -> new IllegalStateException("Unknown block in surface patch: " + id));
	}
}
