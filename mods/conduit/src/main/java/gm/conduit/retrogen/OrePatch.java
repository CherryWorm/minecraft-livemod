package gm.conduit.retrogen;

import com.google.gson.Gson;
import com.google.gson.JsonElement;
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
 * One ore added to the world. Patches are data, so a new ore needs no code and no restart. The id must
 * never be reused, because chunks remember which ids they've already had.
 *
 * @param veinSize the most blocks in a vein
 * @param smallestVein the fewest, which is the same as veinSize unless it's a range
 * @param biomes where it forms, or empty for anywhere
 * @param touchingAir only forms where it can be seen, on a cliff or a cave wall
 * @param dimension which one it forms in
 */
public record OrePatch(String id, Block ore, Set<Block> replaces, int veinsPerChunk, int veinSize, int smallestVein, int minY, int maxY, Set<ResourceKey<Biome>> biomes, boolean touchingAir,
		ResourceKey<Level> dimension) {
	private static final Path FILE = Path.of("config", "conduit", "ore_patches.json");

	private record Definition(String id, String block, List<String> replaces, int veinsPerChunk, JsonElement veinSize, int minY, int maxY, List<String> biomes, boolean touchingAir, String dimension) {}

	public static List<OrePatch> load() {
		if (!Files.exists(FILE)) {
			return List.of();
		}
		try {
			Definition[] definitions = new Gson().fromJson(Files.readString(FILE), Definition[].class);
			return List.of(definitions).stream().map(OrePatch::resolve).toList();
		} catch (IOException | JsonParseException error) {
			throw new IllegalStateException("Can't read " + FILE, error);
		}
	}

	private static OrePatch resolve(Definition definition) {
		List<String> biomes = definition.biomes() == null ? List.of() : definition.biomes();
		boolean range = definition.veinSize().isJsonArray();
		int largest = range ? definition.veinSize().getAsJsonArray().get(1).getAsInt() : definition.veinSize().getAsInt();
		int smallest = range ? definition.veinSize().getAsJsonArray().get(0).getAsInt() : largest;
		return new OrePatch(
				definition.id(),
				block(definition.block()),
				definition.replaces().stream().map(OrePatch::block).collect(Collectors.toUnmodifiableSet()),
				definition.veinsPerChunk(),
				largest,
				smallest,
				definition.minY(),
				definition.maxY(),
				biomes.stream().map(id -> ResourceKey.create(Registries.BIOME, Identifier.parse(id))).collect(Collectors.toUnmodifiableSet()),
				definition.touchingAir(),
				Dimensions.levelKey(definition.dimension()));
	}

	private static Block block(String id) {
		return BuiltInRegistries.BLOCK.getOptional(Identifier.parse(id))
				.orElseThrow(() -> new IllegalStateException("Unknown block in ore patch: " + id));
	}
}
