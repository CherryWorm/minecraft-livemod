package gm.conduit.retrogen;

import gm.conduit.provenance.Provenance;
import net.fabricmc.fabric.api.event.lifecycle.v1.ServerChunkEvents;
import net.fabricmc.fabric.api.event.lifecycle.v1.ServerLifecycleEvents;
import net.fabricmc.fabric.api.event.lifecycle.v1.ServerTickEvents;
import net.minecraft.core.BlockPos;
import net.minecraft.core.Direction;
import net.minecraft.server.MinecraftServer;
import net.minecraft.server.level.ServerLevel;
import net.minecraft.util.RandomSource;
import net.minecraft.world.level.ChunkPos;
import net.minecraft.world.level.Level;
import net.minecraft.world.level.block.state.BlockState;
import net.minecraft.world.level.chunk.LevelChunk;
import net.minecraft.world.level.chunk.LevelChunkSection;
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

	private final List<OrePatch> patches;
	private final Deque<ChunkPos> queue = new ArrayDeque<>();
	private final Set<Long> queued = new HashSet<>();
	private final long budgetNanos = readBudgetMicros() * 1_000;
	private final long[] tickNanos = new long[STATUS_INTERVAL_TICKS];
	private int tickIndex;
	private long chunksPatched;
	private long oresPlaced;

	private OrePatchQueue(List<OrePatch> patches) {
		this.patches = patches;
		for (OrePatch patch : patches) {
			if (patch.veinSize() > MAX_VEIN_SIZE) {
				throw new IllegalStateException("Vein too large to stay in neighbouring chunks: " + patch.id());
			}
		}
	}

	private static long readBudgetMicros() {
		try {
			return Files.exists(BUDGET_FILE) ? Long.parseLong(Files.readString(BUDGET_FILE).trim()) : DEFAULT_BUDGET_MICROS;
		} catch (IOException | NumberFormatException error) {
			throw new IllegalStateException("Can't read " + BUDGET_FILE, error);
		}
	}

	public static void register() {
		ServerLifecycleEvents.SERVER_STARTED.register(server -> {
			List<OrePatch> patches = OrePatch.load();
			if (patches.isEmpty()) {
				return;
			}
			LOGGER.info("retrogen: {} ore patches active", patches.size());
			OrePatchQueue queue = new OrePatchQueue(patches);
			ServerChunkEvents.CHUNK_LOAD.register((level, chunk, generated) -> queue.onLoad(level, chunk));
			ServerChunkEvents.CHUNK_UNLOAD.register(queue::onUnload);
			ServerTickEvents.END_SERVER_TICK.register(queue::tick);
			ServerLevel overworld = server.overworld();
			queue.scanLoadedChunks(overworld);
		});
	}

	private void scanLoadedChunks(ServerLevel level) {
		level.getChunkSource().chunkMap.forEachReadyToSendChunk(chunk -> this.onLoad(level, chunk));
	}

	private void onLoad(ServerLevel level, LevelChunk chunk) {
		if (level.dimension() != Level.OVERWORLD || !hasOutstanding(chunk)) {
			return;
		}
		if (this.queued.add(chunk.getPos().pack())) {
			this.queue.addLast(chunk.getPos());
		}
	}

	private void onUnload(ServerLevel level, LevelChunk chunk) {
		if (level.dimension() == Level.OVERWORLD && this.queued.remove(chunk.getPos().pack())) {
			this.queue.remove(chunk.getPos());
		}
	}

	private boolean hasOutstanding(LevelChunk chunk) {
		Set<String> applied = Provenance.appliedPatches(chunk);
		return this.patches.stream().anyMatch(patch -> !applied.contains(patch.id()));
	}

	private void tick(MinecraftServer server) {
		long started = System.nanoTime();
		ServerLevel level = server.overworld();
		int attempts = this.queue.size();
		while (attempts-- > 0 && System.nanoTime() - started < this.budgetNanos) {
			ChunkPos pos = this.queue.pollFirst();
			this.queued.remove(pos.pack());
			LevelChunk chunk = level.getChunkSource().getChunkNow(pos.x(), pos.z());
			if (chunk == null) {
				continue;
			}
			if (neighboursLoaded(level, pos)) {
				apply(level, chunk);
			} else {
				// Checked again later: the hidden-ore rule needs to see into the next chunk.
				this.queued.add(pos.pack());
				this.queue.addLast(pos);
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
			LOGGER.info("retrogen: queued={} chunks={} ores={} tick_ms_p99={} tick_ms_max={}",
					this.queue.size(), this.chunksPatched, this.oresPlaced,
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
		for (OrePatch patch : this.patches) {
			if (applied.add(patch.id())) {
				placeVeins(level, chunk, patch, visited);
			}
		}
		Provenance.markApplied(chunk, applied);
		chunk.markUnsaved();
		this.chunksPatched++;
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
		for (int step = 0; step < patch.veinSize(); step++) {
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
		// Written to the section directly: this isn't a player or world change, so it shouldn't count as
		// touched, and replacing solid stone with solid ore needs no neighbour updates or lighting.
		LevelChunkSection section = chunk.getSection(chunk.getSectionIndex(pos.getY()));
		section.setBlockState(pos.getX() & 15, pos.getY() & 15, pos.getZ() & 15, patch.ore().defaultBlockState());
		level.getChunkSource().blockChanged(pos);
		this.oresPlaced++;
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
