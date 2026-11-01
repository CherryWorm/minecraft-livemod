package gm.conduit.retrogen;

import com.google.gson.Gson;
import com.google.gson.JsonParseException;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.core.registries.Registries;
import net.minecraft.resources.Identifier;
import net.minecraft.resources.ResourceKey;
import net.minecraft.util.RandomSource;
import net.minecraft.world.level.ChunkPos;
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
 * @param layouts the shapes it can take, of which each one placed picks one
 * @param chance how likely a chunk is to get one, from 0 to 1. With spacing, it's how likely each spot is to get one
 * @param on what it can sit on, checked under its origin, or under every part that follows the terrain
 * @param replaces what its blocks may overwrite, so it never cuts through something unexpected
 * @param loot a loot table for any chest in it, or null
 * @param followTerrain counts each part's height from the ground under it, instead of from one level
 * @param maxSlope how far the ground may rise and fall under one that follows the terrain
 * @param spacing how many chunks apart two of these always are, or 0 if that doesn't matter
 */
public record RuinPatch(String id, List<List<Part>> layouts, Set<Block> on, Set<Block> replaces, float chance, int minY, int maxY,
		boolean underground, Set<ResourceKey<Biome>> biomes, String loot, boolean followTerrain, int maxSlope, int spacing) {
	private static final Path FILE = Path.of("config", "conduit", "ruin_patches.json");
	private static final int CHUNK_SIDE = 16;
	private static final int DEFAULT_MAX_SLOPE = 8;

	/** @param chance how often this part is there at all, from 0 to 1 */
	public record Part(int x, int y, int z, Block block, float chance) {}

	private record PartDefinition(int x, int y, int z, String block, Float chance) {}

	private record Definition(String id, List<PartDefinition> parts, List<List<PartDefinition>> layouts, List<String> on, List<String> replaces,
			Float chance, int minY, int maxY, boolean underground, List<String> biomes, String loot, boolean followTerrain, Integer maxSlope, int spacing) {}

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

	/**
	 * Whether this chunk is one where it can go. With spacing, each cell of a grid has one such chunk, chosen from the part of
	 * the cell near its corner, so even the closest two, in neighbouring cells, are further apart than spacing. It depends only
	 * on the world's seed, so it doesn't matter what order chunks load in.
	 */
	boolean spotAt(long seed, ChunkPos pos) {
		if (this.spacing <= 0) {
			return true;
		}
		int room = Math.max(1, this.spacing / 2);
		int cell = this.spacing + room;
		int cellX = Math.floorDiv(pos.x(), cell);
		int cellZ = Math.floorDiv(pos.z(), cell);
		RandomSource random = RandomSource.create(seed ^ (this.id.hashCode() * 0xC6A4A7935BD1E995L) ^ (cellX * 341873128712L) ^ (cellZ * 132897987541L));
		return pos.x() == cellX * cell + random.nextInt(room) && pos.z() == cellZ * cell + random.nextInt(room);
	}

	/** Picks a layout, and which of its parts are there this time. */
	List<Part> choose(RandomSource random) {
		List<Part> layout = this.layouts.size() == 1 ? this.layouts.getFirst() : this.layouts.get(random.nextInt(this.layouts.size()));
		return layout.stream().filter(part -> part.chance() >= 1 || random.nextFloat() < part.chance()).toList();
	}

	private static RuinPatch resolve(Definition definition) {
		List<List<PartDefinition>> layouts = definition.layouts() != null ? definition.layouts() : List.of(definition.parts());
		for (List<PartDefinition> layout : layouts) {
			for (PartDefinition part : layout) {
				if (part.x() < 0 || part.x() >= CHUNK_SIDE || part.z() < 0 || part.z() >= CHUNK_SIDE) {
					throw new IllegalStateException("Ruin " + definition.id() + " doesn't fit in one chunk");
				}
			}
		}
		List<String> biomes = definition.biomes() == null ? List.of() : definition.biomes();
		// Spacing says how rare it is by itself, so it's the only way to leave out a chance and still get any.
		float chance = definition.chance() != null ? definition.chance() : definition.spacing() > 0 ? 1 : 0;
		return new RuinPatch(
				definition.id(),
				layouts.stream().map(layout -> layout.stream().map(RuinPatch::part).toList()).toList(),
				definition.on().stream().map(RuinPatch::block).collect(Collectors.toUnmodifiableSet()),
				definition.replaces().stream().map(RuinPatch::block).collect(Collectors.toUnmodifiableSet()),
				chance,
				definition.minY(),
				definition.maxY(),
				definition.underground(),
				biomes.stream().map(id -> ResourceKey.create(Registries.BIOME, Identifier.parse(id))).collect(Collectors.toUnmodifiableSet()),
				definition.loot(),
				definition.followTerrain(),
				definition.maxSlope() != null ? definition.maxSlope() : DEFAULT_MAX_SLOPE,
				definition.spacing());
	}

	private static Part part(PartDefinition part) {
		return new Part(part.x(), part.y(), part.z(), block(part.block()), part.chance() != null ? part.chance() : 1);
	}

	private static Block block(String id) {
		return BuiltInRegistries.BLOCK.getOptional(Identifier.parse(id))
				.orElseThrow(() -> new IllegalStateException("Unknown block in ruin: " + id));
	}
}
