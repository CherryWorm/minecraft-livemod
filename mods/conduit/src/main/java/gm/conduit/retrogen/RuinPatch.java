package gm.conduit.retrogen;

import com.google.gson.Gson;
import com.google.gson.JsonParseException;
import com.mojang.brigadier.exceptions.CommandSyntaxException;
import gm.conduit.dimensions.Dimensions;
import net.minecraft.commands.arguments.blocks.BlockStateParser;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.core.registries.Registries;
import net.minecraft.resources.Identifier;
import net.minecraft.resources.ResourceKey;
import net.minecraft.util.RandomSource;
import net.minecraft.world.level.ChunkPos;
import net.minecraft.world.level.Level;
import net.minecraft.world.level.biome.Biome;
import net.minecraft.world.level.block.Block;
import net.minecraft.world.level.block.Blocks;
import net.minecraft.world.level.block.state.BlockState;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import java.util.Set;
import java.util.stream.Collectors;

/**
 * A built thing that turns up in the world: a ruin, a shrine, a wreck. Only ever appears on land nobody has been on, because
 * something appearing where people have already looked would be noticed. One that fits in a chunk goes in as that chunk is
 * looked at. One that doesn't is decided on as a whole first: see {@link RuinPlans}.
 *
 * @param name what modules call it, as "feature/name"
 * @param layouts the shapes it can take, of which each one placed picks one
 * @param chance how likely a chunk is to get one, from 0 to 1. With spacing, it's how likely each spot is to get one
 * @param on what it can sit on, checked under its origin, or under every part that follows the terrain
 * @param replaces what its blocks may overwrite, so it never cuts through something unexpected
 * @param onNatural it can sit on any ground, which is written as "natural"
 * @param replacesNatural it can go through anything as the world made it, which is written as "natural"
 * @param loot a loot table for any chest in it that hasn't got its own, or null
 * @param followTerrain counts each part's height from the ground under it, instead of from one level
 * @param maxSlope how far the ground may rise and fall under one that follows the terrain, or under a big one
 * @param spacing how many chunks apart two of these always are, or 0 if that doesn't matter
 * @param highGround how many blocks above the land around it, on average, it has to stand, or 0 if that doesn't matter
 * @param opensOntoCave underground, it's only placed where a cave reaches it
 * @param chunksX how many chunks it can reach across, from the chunk of its corner, which is 1 for one that fits in a chunk
 * @param dimension which one it turns up in
 */
public record RuinPatch(String id, String name, List<List<Part>> layouts, Set<Block> on, Set<Block> replaces, boolean onNatural, boolean replacesNatural, float chance, int minY, int maxY,
		boolean underground, Set<ResourceKey<Biome>> biomes, String loot, boolean followTerrain, int maxSlope, int spacing, int highGround, boolean opensOntoCave,
		int chunksX, int chunksZ, ResourceKey<Level> dimension) {
	private static final Path FILE = Path.of("config", "conduit", "ruin_patches.json");
	private static final int DEFAULT_MAX_SLOPE = 8;
	private static final String NATURAL = "natural";

	/**
	 * @param chance how often this part is there at all, from 0 to 1
	 * @param loot a loot table for this part alone, if it's a container, or null
	 */
	public record Part(int x, int y, int z, BlockState state, float chance, String loot) {}

	/** @param to the far corner, for a part that's a box of this block, or null for one block */
	private record PartDefinition(int x, int y, int z, String block, Float chance, String loot, int[] to) {}

	private record Definition(String id, String name, List<PartDefinition> parts, List<List<PartDefinition>> layouts, List<String> on, List<String> replaces,
			Float chance, int minY, int maxY, boolean underground, List<String> biomes, String loot, boolean followTerrain, Integer maxSlope, int spacing, int highGround,
			boolean opensOntoCave, String dimension) {}

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
		return this.spacing <= 0 || pos.equals(spotIn(seed, Math.floorDiv(pos.x(), cell()), Math.floorDiv(pos.z(), cell())));
	}

	/** The one chunk in a cell of the grid where it can go. */
	ChunkPos spotIn(long seed, int cellX, int cellZ) {
		int room = Math.max(1, this.spacing / 2);
		RandomSource random = RandomSource.create(seed ^ (this.id.hashCode() * 0xC6A4A7935BD1E995L) ^ (cellX * 341873128712L) ^ (cellZ * 132897987541L));
		int x = cellX * cell() + random.nextInt(room);
		return new ChunkPos(x, cellZ * cell() + random.nextInt(room));
	}

	/** How wide a cell of the grid is, which is one and a half times its spacing, because a spot only uses the part near the corner. */
	int cell() {
		return this.spacing + Math.max(1, this.spacing / 2);
	}

	/** The numbers that decide everything about one placed at this chunk, which only ever depend on the world's seed. */
	RandomSource random(long seed, ChunkPos pos) {
		return RandomSource.create(seed ^ (this.id.hashCode() * 0x9E3779B97F4A7C15L) ^ (pos.x() * 341873128712L) ^ (pos.z() * 132897987541L));
	}

	/** Whether it's too big for one chunk, and has to be decided on before any of it is placed. */
	boolean big() {
		return this.chunksX > 1 || this.chunksZ > 1;
	}

	/** Picks a layout, and which of its parts are there this time. */
	List<Part> choose(RandomSource random) {
		List<Part> layout = this.layouts.size() == 1 ? this.layouts.getFirst() : this.layouts.get(random.nextInt(this.layouts.size()));
		return layout.stream().filter(part -> part.chance() >= 1 || random.nextFloat() < part.chance()).toList();
	}

	private static RuinPatch resolve(Definition definition) {
		List<List<PartDefinition>> layouts = definition.layouts() != null ? definition.layouts() : List.of(definition.parts());
		List<List<Part>> resolved = layouts.stream().map(layout -> layout.stream().flatMap(part -> parts(part).stream()).toList()).toList();
		int chunksX = 1;
		int chunksZ = 1;
		for (List<Part> layout : resolved) {
			for (Part part : layout) {
				if (part.x() < 0 || part.z() < 0) {
					throw new IllegalStateException("Ruin " + definition.id() + " has a part behind its corner");
				}
				chunksX = Math.max(chunksX, (part.x() >> 4) + 1);
				chunksZ = Math.max(chunksZ, (part.z() >> 4) + 1);
			}
		}
		if ((chunksX > 1 || chunksZ > 1) && definition.spacing() < Math.max(chunksX, chunksZ)) {
			throw new IllegalStateException("Ruin " + definition.id() + " is too big to go without a spacing as wide as it is");
		}
		List<String> biomes = definition.biomes() == null ? List.of() : definition.biomes();
		// Spacing says how rare it is by itself, so it's the only way to leave out a chance and still get any.
		float chance = definition.chance() != null ? definition.chance() : definition.spacing() > 0 ? 1 : 0;
		return new RuinPatch(
				definition.id(),
				definition.name() != null ? definition.name() : definition.id(),
				resolved,
				blocks(definition.on()),
				blocks(definition.replaces()),
				definition.on().contains(NATURAL),
				definition.replaces().contains(NATURAL),
				chance,
				definition.minY(),
				definition.maxY(),
				definition.underground(),
				biomes.stream().map(id -> ResourceKey.create(Registries.BIOME, Identifier.parse(id))).collect(Collectors.toUnmodifiableSet()),
				definition.loot(),
				definition.followTerrain(),
				definition.maxSlope() != null ? definition.maxSlope() : DEFAULT_MAX_SLOPE,
				definition.spacing(),
				definition.highGround(),
				definition.opensOntoCave(),
				chunksX,
				chunksZ,
				Dimensions.levelKey(definition.dimension()));
	}

	/** One block, or every block of a box. A chance on a box is for each block in it, which is how to make something crumbled. */
	private static List<Part> parts(PartDefinition part) {
		BlockState state = state(part.block());
		float chance = part.chance() != null ? part.chance() : 1;
		if (part.to() == null) {
			return List.of(new Part(part.x(), part.y(), part.z(), state, chance, part.loot()));
		}
		List<Part> box = new ArrayList<>();
		for (int x = Math.min(part.x(), part.to()[0]); x <= Math.max(part.x(), part.to()[0]); x++) {
			for (int z = Math.min(part.z(), part.to()[2]); z <= Math.max(part.z(), part.to()[2]); z++) {
				for (int y = Math.min(part.y(), part.to()[1]); y <= Math.max(part.y(), part.to()[1]); y++) {
					box.add(new Part(x, y, z, state, chance, part.loot()));
				}
			}
		}
		return box;
	}

	/** Reads a block the way commands do, so it can say which way it faces, like {@code minecraft:ladder[facing=north]}. */
	private static BlockState state(String text) {
		try {
			return BlockStateParser.parseForBlock(BuiltInRegistries.BLOCK, text, false).blockState();
		} catch (CommandSyntaxException error) {
			throw new IllegalStateException("Can't read block in ruin: " + text + ": " + error.getMessage(), error);
		}
	}

	private static Set<Block> blocks(List<String> ids) {
		return ids.stream().filter(id -> !id.equals(NATURAL)).map(RuinPatch::block).collect(Collectors.toUnmodifiableSet());
	}

	/** Whether this can be the ground under it. */
	boolean sitsOn(Block ground) {
		return this.onNatural || this.on.contains(ground);
	}

	/**
	 * Whether a block of it can go where this is. With "natural", that's anything at all as the world made it, which is safe because it only ever goes where nobody's been.
	 * It still won't go through a natural chest or spawner, or the bottom of the world.
	 */
	boolean canReplace(BlockState state) {
		return this.replacesNatural ? !state.hasBlockEntity() && !state.is(Blocks.BEDROCK) : this.replaces.contains(state.getBlock());
	}

	private static Block block(String id) {
		return BuiltInRegistries.BLOCK.getOptional(Identifier.parse(id))
				.orElseThrow(() -> new IllegalStateException("Unknown block in ruin: " + id));
	}
}
