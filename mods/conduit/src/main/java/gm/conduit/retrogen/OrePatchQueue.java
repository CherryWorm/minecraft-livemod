package gm.conduit.retrogen;

import gm.conduit.provenance.Provenance;
import net.fabricmc.fabric.api.event.lifecycle.v1.ServerChunkEvents;
import net.fabricmc.fabric.api.event.lifecycle.v1.ServerLifecycleEvents;
import net.fabricmc.fabric.api.event.lifecycle.v1.ServerTickEvents;
import net.minecraft.core.BlockPos;
import net.minecraft.core.Direction;
import net.minecraft.core.Holder;
import net.minecraft.core.registries.Registries;
import net.minecraft.resources.Identifier;
import net.minecraft.resources.ResourceKey;
import net.minecraft.server.MinecraftServer;
import net.minecraft.server.level.ServerLevel;
import net.minecraft.tags.BlockTags;
import net.minecraft.util.RandomSource;
import net.minecraft.world.level.ChunkPos;
import net.minecraft.world.level.Level;
import net.minecraft.world.level.biome.Biome;
import net.minecraft.world.level.block.Block;
import net.minecraft.world.level.block.entity.RandomizableContainerBlockEntity;
import net.minecraft.world.level.block.state.BlockState;
import net.minecraft.world.level.chunk.LevelChunk;
import net.minecraft.world.level.chunk.LevelChunkSection;
import net.minecraft.world.level.levelgen.Heightmap;
import net.minecraft.world.level.levelgen.synth.SimplexNoise;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Deque;
import java.util.HashSet;
import java.util.List;
import java.util.Set;

/**
 * Adds ores to chunks as they load, old or new, a little per tick.
 *
 * <p>Placement depends only on the world seed, patch id and chunk position, so the same world always
 * gets the same veins and they continue across chunk borders. Only untouched natural stone is ever
 * replaced. A chunk someone has been in only gets ore hidden fully inside stone, so nothing appears
 * next to a player's base. The applied marker is saved with the chunk's blocks, so a crash either keeps
 * both or loses both, and a lost patch is simply applied again with the same result.
 */
public final class OrePatchQueue {
	private static final Logger LOGGER = LoggerFactory.getLogger("Conduit");
	private static final long DEFAULT_BUDGET_MICROS = 1_500;
	private static final Path BUDGET_FILE = Path.of("config", "conduit", "retrogen_budget_micros");
	private static final int STATUS_INTERVAL_TICKS = 100;
	/** A vein is a walk of at most veinSize steps, so this keeps it within the neighbouring chunks. */
	private static final int MAX_VEIN_SIZE = 16;
	private static final double BIOME_NOISE_SCALE = 0.02;

	private static final OrePatchQueue INSTANCE = new OrePatchQueue();

	private List<OrePatch> patches = List.of();
	private List<SurfacePatch> surfacePatches = List.of();
	private List<BiomePatch> biomePatches = List.of();
	private List<RuinPatch> ruinPatches = List.of();
	private final Deque<Waiting> queue = new ArrayDeque<>();
	private final Set<Waiting> queued = new HashSet<>();
	private final long budgetNanos = readBudgetMicros() * 1_000;
	private final long[] tickNanos = new long[STATUS_INTERVAL_TICKS];
	private int tickIndex;
	private long chunksPatched;
	private long oresPlaced;
	private long ruinsPlaced;

	private record Waiting(ServerLevel level, ChunkPos pos) {}

	private OrePatchQueue() {}

	private static long readBudgetMicros() {
		try {
			return Files.exists(BUDGET_FILE) ? Long.parseLong(Files.readString(BUDGET_FILE).trim()) : DEFAULT_BUDGET_MICROS;
		} catch (IOException | NumberFormatException error) {
			throw new IllegalStateException("Can't read " + BUDGET_FILE, error);
		}
	}

	public static void register() {
		ServerLifecycleEvents.SERVER_STARTED.register(OrePatchQueue::reload);
		ServerChunkEvents.CHUNK_LOAD.register((level, chunk, generated) -> INSTANCE.onLoad(level, chunk));
		ServerChunkEvents.CHUNK_UNLOAD.register(INSTANCE::onUnload);
		ServerTickEvents.END_SERVER_TICK.register(INSTANCE::tick);
	}

	/** Reads the patch list again and starts on any loaded chunks that need something new. */
	public static int reload(MinecraftServer server) {
		List<OrePatch> patches = OrePatch.load();
		for (OrePatch patch : patches) {
			if (patch.veinSize() > MAX_VEIN_SIZE) {
				throw new IllegalStateException("Vein too large to stay in neighbouring chunks: " + patch.id());
			}
		}
		INSTANCE.patches = patches;
		INSTANCE.surfacePatches = SurfacePatch.load();
		INSTANCE.biomePatches = BiomePatch.load();
		INSTANCE.ruinPatches = RuinPatch.load();
		int total = patches.size() + INSTANCE.surfacePatches.size() + INSTANCE.biomePatches.size() + INSTANCE.ruinPatches.size();
		if (total > 0) {
			LOGGER.info("retrogen: {} patches active", total);
			server.getAllLevels().forEach(INSTANCE::scanLoadedChunks);
		}
		return total;
	}

	private void scanLoadedChunks(ServerLevel level) {
		level.getChunkSource().chunkMap.forEachReadyToSendChunk(chunk -> this.onLoad(level, chunk));
	}

	private void onLoad(ServerLevel level, LevelChunk chunk) {
		if (!hasOutstanding(level, chunk)) {
			return;
		}
		Waiting waiting = new Waiting(level, chunk.getPos());
		if (this.queued.add(waiting)) {
			this.queue.addLast(waiting);
		}
	}

	private void onUnload(ServerLevel level, LevelChunk chunk) {
		Waiting waiting = new Waiting(level, chunk.getPos());
		if (this.queued.remove(waiting)) {
			this.queue.remove(waiting);
		}
	}

	private boolean hasOutstanding(ServerLevel level, LevelChunk chunk) {
		ResourceKey<Level> here = level.dimension();
		Set<String> applied = Provenance.appliedPatches(chunk);
		return this.patches.stream().anyMatch(patch -> patch.dimension().equals(here) && !applied.contains(patch.id()))
				|| this.surfacePatches.stream().anyMatch(patch -> patch.dimension().equals(here) && !applied.contains(patch.id()))
				|| here.equals(Level.OVERWORLD) && this.biomePatches.stream().anyMatch(patch -> !applied.contains(patch.id()))
				|| this.ruinPatches.stream().anyMatch(patch -> patch.dimension().equals(here) && !applied.contains(patch.id()));
	}

	private void tick(MinecraftServer server) {
		if (this.patches.isEmpty() && this.surfacePatches.isEmpty() && this.biomePatches.isEmpty() && this.ruinPatches.isEmpty()) {
			return;
		}
		long started = System.nanoTime();
		int attempts = this.queue.size();
		while (attempts-- > 0 && System.nanoTime() - started < this.budgetNanos) {
			Waiting waiting = this.queue.pollFirst();
			this.queued.remove(waiting);
			ServerLevel level = waiting.level();
			ChunkPos pos = waiting.pos();
			LevelChunk chunk = level.getChunkSource().getChunkNow(pos.x(), pos.z());
			if (chunk == null) {
				continue;
			}
			if (neighboursLoaded(level, pos)) {
				apply(level, chunk);
			} else {
				// Checked again later: the hidden-ore rule needs to see into the next chunk.
				this.queued.add(waiting);
				this.queue.addLast(waiting);
			}
		}
		recordTick(System.nanoTime() - started);
	}

	private void recordTick(long nanos) {
		this.tickNanos[this.tickIndex++] = nanos;
		if (this.tickIndex == STATUS_INTERVAL_TICKS) {
			this.tickIndex = 0;
			long[] sorted = this.tickNanos.clone();
			Arrays.sort(sorted);
			LOGGER.info("retrogen: queued={} chunks={} ores={} ruins={} tick_ms_p99={} tick_ms_max={}",
					this.queue.size(), this.chunksPatched, this.oresPlaced, this.ruinsPlaced,
					"%.2f".formatted(sorted[STATUS_INTERVAL_TICKS * 99 / 100] / 1e6),
					"%.2f".formatted(sorted[STATUS_INTERVAL_TICKS - 1] / 1e6));
		}
	}

	private static boolean neighboursLoaded(ServerLevel level, ChunkPos pos) {
		for (Direction direction : Direction.Plane.HORIZONTAL) {
			if (level.getChunkSource().getChunkNow(pos.x() + direction.getStepX(), pos.z() + direction.getStepZ()) == null) {
				return false;
			}
		}
		return true;
	}

	private void apply(ServerLevel level, LevelChunk chunk) {
		Set<String> applied = new HashSet<>(Provenance.appliedPatches(chunk));
		boolean visited = chunk.getInhabitedTime() > 0 || Provenance.hasAnyTouched(chunk);
		ResourceKey<Level> here = level.dimension();
		for (OrePatch patch : this.patches) {
			if (patch.dimension().equals(here) && applied.add(patch.id())) {
				placeVeins(level, chunk, patch, visited);
			}
		}
		// Nothing should spring up where someone has built, or it looks like the world is rearranging their base.
		boolean built = Provenance.hasAnyTouched(chunk);
		for (SurfacePatch patch : this.surfacePatches) {
			if (patch.dimension().equals(here) && applied.add(patch.id()) && !built) {
				growPlants(level, chunk, patch);
			}
		}
		if (here.equals(Level.OVERWORLD)) {
			for (BiomePatch patch : this.biomePatches) {
				if (applied.add(patch.id()) && patch.sibling()) {
					spreadBiome(level, chunk, patch);
				}
			}
		}
		for (RuinPatch patch : this.ruinPatches) {
			if (patch.dimension().equals(here) && applied.add(patch.id()) && !visited) {
				placeRuin(level, chunk, patch);
			}
		}
		Provenance.markApplied(chunk, applied);
		chunk.markUnsaved();
		this.chunksPatched++;
	}

	private void placeRuin(ServerLevel level, LevelChunk chunk, RuinPatch patch) {
		ChunkPos pos = chunk.getPos();
		RandomSource random = RandomSource.create(level.getSeed() ^ (patch.id().hashCode() * 0x9E3779B97F4A7C15L)
				^ (pos.x() * 341873128712L) ^ (pos.z() * 132897987541L));
		if (!patch.spotAt(level.getSeed(), pos) || random.nextFloat() >= patch.chance()) {
			return;
		}
		List<RuinPatch.Part> parts = patch.choose(random);
		int x = pos.getMinBlockX();
		int z = pos.getMinBlockZ();
		BlockPos origin = patch.underground()
				? new BlockPos(x, patch.minY() + random.nextInt(Math.max(1, patch.maxY() - patch.minY())), z)
				: new BlockPos(x, chunk.getHeight(Heightmap.Types.OCEAN_FLOOR, x & 15, z & 15) + 1, z);
		int[] ground = patch.followTerrain() ? groundUnder(chunk, patch, parts) : null;
		boolean suits = patch.followTerrain() ? ground != null
				: origin.getY() >= patch.minY() && origin.getY() <= patch.maxY() && patch.on().contains(chunk.getBlockState(origin.below()).getBlock());
		if (!suits || !onHighGround(level, chunk, patch) || !(patch.biomes().isEmpty() || patch.biomes().stream().anyMatch(level.getBiome(origin)::is))) {
			return;
		}
		List<BlockPos> spots = parts.stream().map(part -> ground == null ? origin.offset(part.x(), part.y(), part.z())
				: new BlockPos(x + part.x(), ground[column(part)] + 1 + part.y(), z + part.z())).toList();
		// All of it or none of it, so no half-built ruin ever appears.
		for (BlockPos spot : spots) {
			if (!patch.replaces().contains(chunk.getBlockState(spot).getBlock())) {
				return;
			}
		}
		Provenance.untracked(() -> {
			for (int i = 0; i < spots.size(); i++) {
				BlockPos spot = spots.get(i);
				level.setBlock(spot, parts.get(i).state(), Block.UPDATE_CLIENTS);
				String loot = parts.get(i).loot() != null ? parts.get(i).loot() : patch.loot();
				if (loot != null && level.getBlockEntity(spot) instanceof RandomizableContainerBlockEntity chest) {
					chest.setLootTable(ResourceKey.create(Registries.LOOT_TABLE, Identifier.parse(loot)), random.nextLong());
				}
			}
		});
		this.ruinsPlaced++;
	}

	/**
	 * Compares the middle of this chunk with the average of the middles of the four around it, which are as far as it can look,
	 * because further ones may not exist yet. On an even slope that's no difference, so only a real rise counts.
	 */
	private static boolean onHighGround(ServerLevel level, LevelChunk chunk, RuinPatch patch) {
		if (patch.highGround() <= 0) {
			return true;
		}
		int around = 0;
		for (Direction direction : Direction.Plane.HORIZONTAL) {
			LevelChunk next = level.getChunkSource().getChunkNow(chunk.getPos().x() + direction.getStepX(), chunk.getPos().z() + direction.getStepZ());
			if (next == null) {
				return false;
			}
			around += groundAt(next, 8, 8).getY();
		}
		return groundAt(chunk, 8, 8).getY() - around / 4.0 >= patch.highGround();
	}

	private static int column(RuinPatch.Part part) {
		return part.x() + part.z() * 16;
	}

	/** The height of the ground under each column these parts use, or null if somewhere here doesn't suit the ruin. */
	private static int[] groundUnder(LevelChunk chunk, RuinPatch patch, List<RuinPatch.Part> parts) {
		int[] ground = new int[16 * 16];
		Arrays.fill(ground, Integer.MIN_VALUE);
		int lowest = Integer.MAX_VALUE;
		int highest = Integer.MIN_VALUE;
		for (RuinPatch.Part part : parts) {
			if (ground[column(part)] != Integer.MIN_VALUE) {
				continue;
			}
			BlockPos floor = groundAt(chunk, part.x(), part.z());
			if (floor.getY() < patch.minY() - 1 || floor.getY() >= patch.maxY() || !patch.on().contains(chunk.getBlockState(floor).getBlock())) {
				return null;
			}
			ground[column(part)] = floor.getY();
			lowest = Math.min(lowest, floor.getY());
			highest = Math.max(highest, floor.getY());
		}
		return highest - lowest > patch.maxSlope() ? null : ground;
	}

	/** The heightmap stops at a tree's canopy, and a ruin under the trees should still sit on the forest floor. */
	private static BlockPos groundAt(LevelChunk chunk, int x, int z) {
		BlockPos.MutableBlockPos pos = new BlockPos.MutableBlockPos(chunk.getPos().getMinBlockX() + x, chunk.getHeight(Heightmap.Types.OCEAN_FLOOR, x, z), chunk.getPos().getMinBlockZ() + z);
		while (chunk.getBlockState(pos).is(BlockTags.LEAVES) || chunk.getBlockState(pos).is(BlockTags.LOGS)) {
			pos.move(Direction.DOWN);
		}
		return pos.immutable();
	}

	private void growPlants(ServerLevel level, LevelChunk chunk, SurfacePatch patch) {
		ChunkPos pos = chunk.getPos();
		RandomSource random = RandomSource.create(level.getSeed() ^ (patch.id().hashCode() * 0x9E3779B97F4A7C15L)
				^ (pos.x() * 341873128712L) ^ (pos.z() * 132897987541L));
		int count = (int) patch.perChunk() + (random.nextFloat() < patch.perChunk() % 1 ? 1 : 0);
		for (int i = 0; i < count; i++) {
			int x = pos.getMinBlockX() + random.nextInt(16);
			int z = pos.getMinBlockZ() + random.nextInt(16);
			BlockPos spot = patch.underground() ? caveFloor(chunk, patch, x, z, random) : surface(chunk, patch, x, z);
			if (spot != null && (patch.biomes().isEmpty() || patch.biomes().stream().anyMatch(level.getBiome(spot)::is))) {
				// Natural growth, so it mustn't count as a player's change.
				Provenance.untracked(() -> level.setBlock(spot, patch.block().defaultBlockState(), Block.UPDATE_CLIENTS));
				this.oresPlaced++;
			}
		}
	}

	private static BlockPos surface(LevelChunk chunk, SurfacePatch patch, int x, int z) {
		BlockPos spot = new BlockPos(x, chunk.getHeight(Heightmap.Types.MOTION_BLOCKING_NO_LEAVES, x & 15, z & 15) + 1, z);
		return spot.getY() >= patch.minY() && spot.getY() <= patch.maxY() && canGrow(chunk, patch, spot) ? spot : null;
	}

	private static BlockPos caveFloor(LevelChunk chunk, SurfacePatch patch, int x, int z, RandomSource random) {
		int surfaceY = chunk.getHeight(Heightmap.Types.WORLD_SURFACE, x & 15, z & 15);
		int top = Math.min(patch.maxY(), surfaceY - 5);
		if (top <= patch.minY()) {
			return null;
		}
		int startY = patch.minY() + random.nextInt(top - patch.minY());
		for (int y = startY; y > Math.max(patch.minY(), startY - 12); y--) {
			BlockPos spot = new BlockPos(x, y, z);
			if (canGrow(chunk, patch, spot)) {
				return spot;
			}
		}
		return null;
	}

	private static boolean canGrow(LevelChunk chunk, SurfacePatch patch, BlockPos spot) {
		return chunk.getBlockState(spot).isAir()
				&& patch.on().contains(chunk.getBlockState(spot.below()).getBlock())
				&& !Provenance.isTouched(chunk, spot)
				&& !Provenance.isTouched(chunk, spot.below());
	}

	private static void spreadBiome(ServerLevel level, LevelChunk chunk, BiomePatch patch) {
		var biomes = level.registryAccess().lookupOrThrow(Registries.BIOME);
		var target = biomes.get(patch.to());
		if (target.isEmpty()) {
			LOGGER.error("biome patch {} wants {}, which doesn't exist", patch.id(), patch.to().identifier());
			return;
		}
		SimplexNoise noise = new SimplexNoise(RandomSource.create(level.getSeed() ^ patch.id().hashCode()));
		// Noise runs from about -1 to 1, so a threshold puts a matching share of cells on one side of it.
		double threshold = patch.proportion() * 2 - 1;
		chunk.fillBiomesFromNoise((x, y, z) -> {
			Holder<Biome> existing = chunk.getNoiseBiome(x, y, z);
			return existing.is(patch.from()) && noise.get(x * BIOME_NOISE_SCALE, z * BIOME_NOISE_SCALE) < threshold ? target.get() : existing;
		});
		level.getChunkSource().chunkMap.resendBiomesForChunks(List.of(chunk));
	}

	private void placeVeins(ServerLevel level, LevelChunk chunk, OrePatch patch, boolean visited) {
		ChunkPos target = chunk.getPos();
		for (int originX = target.x() - 1; originX <= target.x() + 1; originX++) {
			for (int originZ = target.z() - 1; originZ <= target.z() + 1; originZ++) {
				RandomSource random = RandomSource.create(seedFor(level, patch, originX, originZ));
				for (int vein = 0; vein < patch.veinsPerChunk(); vein++) {
					walkVein(level, chunk, patch, visited, random, originX, originZ);
				}
			}
		}
	}

	private static long seedFor(ServerLevel level, OrePatch patch, int chunkX, int chunkZ) {
		return level.getSeed() ^ (patch.id().hashCode() * 0x9E3779B97F4A7C15L) ^ (chunkX * 341873128712L) ^ (chunkZ * 132897987541L);
	}

	private void walkVein(ServerLevel level, LevelChunk chunk, OrePatch patch, boolean visited, RandomSource random, int originX, int originZ) {
		BlockPos.MutableBlockPos pos = new BlockPos.MutableBlockPos(
				(originX << 4) + random.nextInt(16),
				patch.minY() + random.nextInt(Math.max(1, patch.maxY() - patch.minY())),
				(originZ << 4) + random.nextInt(16));
		// Worked out only for a range, so what a fixed size gets from the random numbers stays what it always was.
		int size = patch.smallestVein() == patch.veinSize() ? patch.veinSize() : patch.smallestVein() + random.nextInt(patch.veinSize() - patch.smallestVein() + 1);
		for (int step = 0; step < size; step++) {
			if (ChunkPos.containing(pos).equals(chunk.getPos())) {
				tryPlace(level, chunk, patch, visited, pos);
			}
			Direction direction = Direction.getRandom(random);
			pos.move(direction);
		}
	}

	private void tryPlace(ServerLevel level, LevelChunk chunk, OrePatch patch, boolean visited, BlockPos pos) {
		if (level.isOutsideBuildHeight(pos)) {
			return;
		}
		BlockState current = chunk.getBlockState(pos);
		if (!patch.replaces().contains(current.getBlock()) || Provenance.isTouched(chunk, pos)) {
			return;
		}
		if (visited && !fullyHidden(level, pos)) {
			return;
		}
		if (patch.touchingAir() && !touchesAir(level, pos)) {
			return;
		}
		if (!patch.biomes().isEmpty() && patch.biomes().stream().noneMatch(level.getBiome(pos)::is)) {
			return;
		}
		// Written to the section directly: this isn't a player or world change, so it shouldn't count as
		// touched, and replacing solid stone with solid ore needs no neighbour updates or lighting.
		LevelChunkSection section = chunk.getSection(chunk.getSectionIndex(pos.getY()));
		section.setBlockState(pos.getX() & 15, pos.getY() & 15, pos.getZ() & 15, patch.ore().defaultBlockState());
		level.getChunkSource().blockChanged(pos);
		this.oresPlaced++;
	}

	private static boolean touchesAir(ServerLevel level, BlockPos pos) {
		for (Direction direction : Direction.values()) {
			BlockPos next = pos.relative(direction);
			LevelChunk neighbour = level.getChunkSource().getChunkNow(next.getX() >> 4, next.getZ() >> 4);
			if (neighbour != null && neighbour.getBlockState(next).isAir()) {
				return true;
			}
		}
		return false;
	}

	private static boolean fullyHidden(ServerLevel level, BlockPos pos) {
		for (Direction direction : Direction.values()) {
			BlockPos next = pos.relative(direction);
			LevelChunk neighbour = level.getChunkSource().getChunkNow(next.getX() >> 4, next.getZ() >> 4);
			if (neighbour == null
					|| !neighbour.getBlockState(next).canOcclude()
					|| Provenance.isTouched(neighbour, next)) {
				return false;
			}
		}
		return true;
	}
}
