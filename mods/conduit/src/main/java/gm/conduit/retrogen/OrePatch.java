package gm.conduit.retrogen;

import com.google.gson.Gson;
import com.google.gson.JsonParseException;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.resources.Identifier;
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
 */
public record OrePatch(String id, Block ore, Set<Block> replaces, int veinsPerChunk, int veinSize, int minY, int maxY) {
	private static final Path FILE = Path.of("config", "conduit", "ore_patches.json");

	private record Definition(String id, String block, List<String> replaces, int veinsPerChunk, int veinSize, int minY, int maxY) {}

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
		return new OrePatch(
				definition.id(),
				block(definition.block()),
				definition.replaces().stream().map(OrePatch::block).collect(Collectors.toUnmodifiableSet()),
				definition.veinsPerChunk(),
				definition.veinSize(),
				definition.minY(),
				definition.maxY());
	}

	private static Block block(String id) {
		return BuiltInRegistries.BLOCK.getOptional(Identifier.parse(id))
				.orElseThrow(() -> new IllegalStateException("Unknown block in ore patch: " + id));
	}
}
