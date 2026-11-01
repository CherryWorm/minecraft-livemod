package gm.conduit.retrogen;

import com.google.gson.Gson;
import com.google.gson.JsonParseException;
import gm.conduit.Conduit;
import gm.conduit.api.RuinSpot;
import gm.conduit.modules.ServerModuleHost;
import gm.conduit.provenance.Provenance;
import net.minecraft.core.BlockPos;
import net.minecraft.core.Direction;
import net.minecraft.core.Registry;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.core.registries.Registries;
import net.minecraft.resources.Identifier;
import net.minecraft.resources.ResourceKey;
import net.minecraft.server.MinecraftServer;
import net.minecraft.server.level.ServerLevel;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.server.level.TicketType;
import net.minecraft.tags.BlockTags;
import net.minecraft.util.RandomSource;
import net.minecraft.world.level.ChunkPos;
import net.minecraft.world.level.block.Block;
import net.minecraft.world.level.block.entity.RandomizableContainerBlockEntity;
import net.minecraft.world.level.chunk.LevelChunk;
import net.minecraft.world.level.levelgen.Heightmap;
import net.minecraft.world.level.storage.LevelResource;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.io.IOException;
import java.nio.ByteBuffer;
import java.nio.channels.FileChannel;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.Collections;
import java.util.Comparator;
import java.util.Deque;
import java.util.HashMap;
import java.util.HashSet;
import java.util.Iterator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.function.Consumer;

/**
 * What's been decided about ruins, and the building of those too big for one chunk.
 *
 * <p>One chunk is saved as a whole, so a small ruin and the record of it in its chunk can't disagree. A big one crosses chunks that are
 * saved at different times, so a crash can leave any mix of them written. So it's decided once, for all of it, and written to a file of
 * its own before a single block is placed. After that, each chunk works out its own share from the world's seed, which always gives the
 * same answer, and records having it along with its blocks. A crash at any point then leaves chunks that either have their share or
 * know they don't, and those get it the next time they load. It can't be left half built for anyone to find, and it can't happen twice.
 *
 * <p>Deciding needs all of its land loaded, which happens a little ahead of anyone reaching it, so nobody should see it appear.
 */
public final class RuinPlans {
	private static final Logger LOGGER = LoggerFactory.getLogger("Conduit");
	private static final Gson GSON = new Gson();
	private static final String FILE = "conduit_ruins.jsonl";
	private static final TicketType TICKET = Registry.register(BuiltInRegistries.TICKET_TYPE, Identifier.fromNamespaceAndPath(Conduit.NAMESPACE, "ruin"),
			new TicketType(TicketType.NO_TIMEOUT, TicketType.FLAG_LOADING));
	/** Asked to stop partway through building one, for a test to crash the server there. */
	private static final Path PAUSE = Path.of("config", "conduit", "chaos_ruin_pause_after_chunks");
	/** As in the game's own ticket levels: fully loaded, but not ticking, so nothing there changes by itself while it's decided. */
	private static final int TICKET_RADIUS = 0;
	private static final int SCAN_INTERVAL_TICKS = 40;
	/** How far past what a player can see to start on one, so it's built before they get there. */
	private static final int AHEAD_OF_VIEW = 3;
	private static final int LOAD_TIMEOUT_TICKS = 2400;
	/** Most of a big ruin's land has to be what it asks for. A stray patch of gravel in sixty-four blocks across isn't a reason to leave it out. */
	private static final float MOST_OF_ITS_GROUND = 0.9F;
	private static final int MOST_SPOTS = 32;
	/** How far to look for a ruin with spacing, or without, in chunks, which is every chunk's roll and so has to stay small. */
	private static final int FURTHEST_SPACED = 2048;
	private static final int FURTHEST_UNSPACED = 128;
	private static final int HEIGHTS_GUESSED = 8;
	private static final int FURTHEST_TRIED_CELLS = 64;
	/** How finely to estimate the land under a spot, as how many steps across it. Each takes a moment, and it's only once for each spot. */
	private static final int LAND_SAMPLES = 2;
	/** Trees and the surface aren't in the estimate, so it's only trusted to rule out what's clearly wrong by this much. */
	private static final int LAND_ESTIMATE_MARGIN = 8;
	/** How far past each side of a ruin to look at the ground, to see if it stands above what's around it. */
	private static final int JUST_BEYOND = 8;
	/** What a ruin looks like is what's drawn. Nothing around it gets a say, the same as what the game places while it generates land, so loose gravel stays put until something next to it changes. */
	public static final int AS_DRAWN = Block.UPDATE_CLIENTS | Block.UPDATE_KNOWN_SHAPE | Block.UPDATE_SKIP_ON_PLACE;

	/** One line of the file. Something not placed has x, y and z of 0, and why says why not. Its seed is the seed of the dimension, so working it out again needn't wait for that to open. */
	private record Decision(String ruin, String dimension, long seed, int chunkX, int chunkZ, boolean placed, int x, int y, int z, String why) {
		String key() {
			return key(this.ruin, this.dimension, this.chunkX, this.chunkZ);
		}

		static String key(String ruin, String dimension, int chunkX, int chunkZ) {
			return dimension + "|" + ruin + "|" + chunkX + "|" + chunkZ;
		}

		BlockPos origin() {
			return new BlockPos(this.x, this.y, this.z);
		}
	}

	/** A big ruin that's been decided on, with the chunks it uses. The blocks themselves are worked out again whenever they're needed. */
	private record Plan(RuinPatch patch, Decision decision, Set<Long> chunks) {
		String marker() {
			return this.patch.id() + "@" + this.decision.chunkX() + "," + this.decision.chunkZ();
		}
	}

	/** A spot still to be decided on. */
	private record Wanted(ServerLevel level, RuinPatch patch, ChunkPos anchor) {}

	/** A part with what it needs to be placed the same way every time. */
	private record Piece(RuinPatch.Part part, long lootSeed) {}

	private final Map<String, Decision> decided = new HashMap<>();
	private final Map<String, Map<Long, List<Plan>>> plans = new HashMap<>();
	private final Map<String, Set<Long>> smallOnes = new HashMap<>();
	private final Deque<Wanted> waiting = new ArrayDeque<>();
	private final Set<String> waitingKeys = new HashSet<>();
	private final Set<String> tryingOut = new HashSet<>();
	private List<RuinPatch> bigRuins = List.of();
	private Path file;
	private Wanted loading;
	private List<ChunkPos> holding = List.of();
	private int loadingFor;
	private Building building;
	private int ticks;
	private int pauseAfter = -1;
	private long bigPlaced;

	/** Has to run while the game can still take new ticket types. */
	static void init() {
		LOGGER.debug("ruin tickets are {}", TICKET);
	}

	/** Reads what's been decided in this world, and keeps track of what the ruins that exist now still have to do. */
	void reload(MinecraftServer server, List<RuinPatch> ruins) {
		this.file = server.getWorldPath(LevelResource.ROOT).resolve(FILE);
		this.bigRuins = ruins.stream().filter(RuinPatch::big).toList();
		this.decided.clear();
		this.plans.clear();
		this.smallOnes.clear();
		this.pauseAfter = readPause();
		Map<String, RuinPatch> byId = new HashMap<>();
		ruins.forEach(patch -> byId.put(patch.id(), patch));
		for (Decision decision : read()) {
			this.decided.put(decision.key(), decision);
			if (!decision.placed()) {
				continue;
			}
			RuinPatch patch = byId.get(decision.ruin());
			if (patch != null && patch.big()) {
				ChunkPos anchor = new ChunkPos(decision.chunkX(), decision.chunkZ());
				index(new Plan(patch, decision, chunksOf(pieces(patch, decision.seed(), anchor), anchor)));
			} else {
				this.smallOnes.computeIfAbsent(decision.dimension(), dimension -> new HashSet<>()).add(new ChunkPos(decision.chunkX(), decision.chunkZ()).pack());
			}
		}
	}

	/** A line cut off by a crash was never finished being written, so nothing was built from it. It's left out, and whatever it was gets decided again. */
	private List<Decision> read() {
		List<Decision> found = new ArrayList<>();
		if (!Files.exists(this.file)) {
			return found;
		}
		try {
			for (String line : Files.readAllLines(this.file, StandardCharsets.UTF_8)) {
				try {
					Decision decision = GSON.fromJson(line, Decision.class);
					if (decision != null && decision.ruin() != null) {
						found.add(decision);
					}
				} catch (JsonParseException error) {
					LOGGER.warn("Leaving out a line of {} that was never finished: {}", FILE, line);
				}
			}
		} catch (IOException error) {
			throw new IllegalStateException("Can't read " + this.file, error);
		}
		return found;
	}

	/** False if it couldn't be written, and then nothing can depend on it. A full disk shouldn't take the server down with it. */
	private boolean write(Decision decision, boolean mustLast) {
		try (FileChannel channel = FileChannel.open(this.file, StandardOpenOption.CREATE, StandardOpenOption.WRITE, StandardOpenOption.APPEND)) {
			// A new line first, so a line a crash cut off can't run into this one.
			channel.write(ByteBuffer.wrap(("\n" + GSON.toJson(decision) + "\n").getBytes(StandardCharsets.UTF_8)));
			if (mustLast) {
				channel.force(false);
			}
		} catch (IOException error) {
			LOGGER.error("Can't write {}", this.file, error);
			return false;
		}
		this.decided.put(decision.key(), decision);
		return true;
	}

	private static int readPause() {
		try {
			return Files.exists(PAUSE) ? Integer.parseInt(Files.readString(PAUSE).trim()) : -1;
		} catch (IOException | NumberFormatException error) {
			return -1;
		}
	}

	private static String dimension(ServerLevel level) {
		return level.dimension().identifier().toString();
	}

	private static long seedOf(ServerLevel level) {
		return level.getSeed();
	}

	private void index(Plan plan) {
		Map<Long, List<Plan>> byChunk = this.plans.computeIfAbsent(plan.decision().dimension(), dimension -> new HashMap<>());
		plan.chunks().forEach(chunk -> byChunk.computeIfAbsent(chunk, key -> new ArrayList<>()).add(plan));
	}

	/** The same every time for one spot, whatever happens in between. */
	private static List<Piece> pieces(RuinPatch patch, long seed, ChunkPos anchor) {
		RandomSource random = patch.random(seed, anchor);
		random.nextFloat();
		List<Piece> pieces = new ArrayList<>();
		for (RuinPatch.Part part : patch.choose(random)) {
			pieces.add(new Piece(part, random.nextLong()));
		}
		return pieces;
	}

	private static Set<Long> chunksOf(List<Piece> pieces, ChunkPos anchor) {
		Set<Long> chunks = new HashSet<>();
		chunks.add(anchor.pack());
		for (Piece piece : pieces) {
			chunks.add(new ChunkPos(anchor.x() + (piece.part().x() >> 4), anchor.z() + (piece.part().z() >> 4)).pack());
		}
		return chunks;
	}

	/** The chunks this ruin would look at if it were placed there: its own, and the ones around it if it wants to compare heights with them. */
	private static List<ChunkPos> landFor(RuinPatch patch, ChunkPos anchor) {
		int edge = patch.highGround() > 0 ? 1 : 0;
		List<ChunkPos> chunks = new ArrayList<>();
		for (int x = anchor.x() - edge; x < anchor.x() + patch.chunksX() + edge; x++) {
			for (int z = anchor.z() - edge; z < anchor.z() + patch.chunksZ() + edge; z++) {
				chunks.add(new ChunkPos(x, z));
			}
		}
		return chunks;
	}

	/** Whether there's anything in this chunk the ruins here still have to do. */
	boolean owes(ServerLevel level, LevelChunk chunk) {
		Map<Long, List<Plan>> here = this.plans.get(dimension(level));
		if (here == null) {
			return false;
		}
		List<Plan> plansHere = here.get(chunk.getPos().pack());
		if (plansHere == null) {
			return false;
		}
		Set<String> applied = Provenance.appliedPatches(chunk);
		return plansHere.stream().anyMatch(plan -> !applied.contains(plan.marker()));
	}

	/** Places this chunk's share of anything that's been decided on, however it's come to be missing. */
	void settle(ServerLevel level, LevelChunk chunk) {
		Map<Long, List<Plan>> here = this.plans.get(dimension(level));
		// A test stopping one partway needs the rest to really be missing.
		if (here != null && this.pauseAfter < 0) {
			here.getOrDefault(chunk.getPos().pack(), List.of()).forEach(plan -> placeShare(level, plan, chunk));
		}
	}

	private void placeShare(ServerLevel level, Plan plan, LevelChunk chunk) {
		Set<String> applied = new HashSet<>(Provenance.appliedPatches(chunk));
		if (!applied.add(plan.marker())) {
			return;
		}
		ChunkPos anchor = new ChunkPos(plan.decision().chunkX(), plan.decision().chunkZ());
		BlockPos origin = plan.decision().origin();
		List<Piece> share = pieces(plan.patch(), plan.decision().seed(), anchor).stream()
				.filter(piece -> anchor.x() + (piece.part().x() >> 4) == chunk.getPos().x() && anchor.z() + (piece.part().z() >> 4) == chunk.getPos().z())
				.toList();
		// Worked out first, because each block placed changes what the height is.
		Map<Piece, BlockPos> spots = new LinkedHashMap<>();
		for (Piece piece : share) {
			spots.put(piece, plan.patch().followTerrain()
					? new BlockPos(origin.getX() + piece.part().x(), ground(chunk, (origin.getX() + piece.part().x()) & 15, (origin.getZ() + piece.part().z()) & 15).getY() + 1 + piece.part().y(), origin.getZ() + piece.part().z())
					: origin.offset(piece.part().x(), piece.part().y(), piece.part().z()));
		}
		Provenance.untracked(() -> spots.forEach((piece, spot) -> {
			// It all fitted when it was decided. If a crash lost this chunk's blocks, it may have changed since, and nobody's work is overwritten for the sake of a ruin.
			if (plan.patch().canReplace(chunk.getBlockState(spot)) && !Provenance.isTouched(chunk, spot)) {
				place(level, spot, piece.part(), plan.patch(), piece.lootSeed());
			}
		}));
		Provenance.markApplied(chunk, applied);
		chunk.markUnsaved();
	}

	/** Puts one block of a ruin in the world. */
	static void place(ServerLevel level, BlockPos spot, RuinPatch.Part part, RuinPatch patch, long lootSeed) {
		level.setBlock(spot, part.state(), AS_DRAWN);
		String loot = part.loot() != null ? part.loot() : patch.loot();
		if (loot != null && level.getBlockEntity(spot) instanceof RandomizableContainerBlockEntity chest) {
			chest.setLootTable(ResourceKey.create(Registries.LOOT_TABLE, Identifier.parse(loot)), lootSeed);
		}
	}

	/** A small ruin is safe from a crash without any of this, and is only written down so it can be found, and so nothing big is built over it. */
	void recordSmall(ServerLevel level, RuinPatch patch, ChunkPos pos, BlockPos origin) {
		write(new Decision(patch.id(), dimension(level), seedOf(level), pos.x(), pos.z(), true, origin.getX(), origin.getY(), origin.getZ(), null), false);
		this.smallOnes.computeIfAbsent(dimension(level), dimension -> new HashSet<>()).add(pos.pack());
	}

	/** Whether something big is, or is going to be, in this chunk. */
	boolean taken(ServerLevel level, ChunkPos pos) {
		Map<Long, List<Plan>> here = this.plans.get(dimension(level));
		return here != null && here.containsKey(pos.pack());
	}

	/** Looks for spots whose land reaches into this area and that haven't been decided on, and gets in line to decide them. */
	void considerArea(ServerLevel level, int minX, int minZ, int maxX, int maxZ) {
		for (RuinPatch patch : this.bigRuins) {
			if (!patch.dimension().equals(level.dimension())) {
				continue;
			}
			int cell = patch.cell();
			for (int cellX = Math.floorDiv(minX - patch.chunksX() + 1, cell); cellX <= Math.floorDiv(maxX, cell); cellX++) {
				for (int cellZ = Math.floorDiv(minZ - patch.chunksZ() + 1, cell); cellZ <= Math.floorDiv(maxZ, cell); cellZ++) {
					ChunkPos anchor = patch.spotIn(seedOf(level), cellX, cellZ);
					if (anchor.x() <= maxX && anchor.x() + patch.chunksX() - 1 >= minX && anchor.z() <= maxZ && anchor.z() + patch.chunksZ() - 1 >= minZ) {
						want(level, patch, anchor);
					}
				}
			}
		}
	}

	private void want(ServerLevel level, RuinPatch patch, ChunkPos anchor) {
		String key = Decision.key(patch.id(), dimension(level), anchor.x(), anchor.z());
		if (this.decided.containsKey(key) || this.waitingKeys.contains(key) || !rolls(level, patch, anchor) || !suitsBiome(level, patch, anchor)
				|| !level.getWorldBorder().isWithinBounds(anchor)) {
			return;
		}
		if (!goodLandLikely(level, patch, anchor)) {
			return;
		}
		this.waitingKeys.add(key);
		this.waiting.addLast(new Wanted(level, patch, anchor));
	}

	/**
	 * Generating a big ruin's land is the costly part, so land that's plainly no use isn't made just to find that out. The game can work out
	 * roughly how high land will be with nothing generated, so where that's far outside what it asks for, this decides no, for good.
	 */
	private boolean goodLandLikely(ServerLevel level, RuinPatch patch, ChunkPos anchor) {
		if (patch.underground()) {
			return true;
		}
		int lowest = Integer.MAX_VALUE;
		int highest = Integer.MIN_VALUE;
		for (int across = 0; across <= LAND_SAMPLES; across++) {
			for (int down = 0; down <= LAND_SAMPLES; down++) {
				int x = anchor.getMinBlockX() + patch.chunksX() * 16 * across / LAND_SAMPLES;
				int z = anchor.getMinBlockZ() + patch.chunksZ() * 16 * down / LAND_SAMPLES;
				int height = level.getChunkSource().getGenerator().getBaseHeight(x, z, Heightmap.Types.OCEAN_FLOOR_WG, level, level.getChunkSource().randomState());
				lowest = Math.min(lowest, height);
				highest = Math.max(highest, height);
			}
		}
		String why = highest - lowest > patch.maxSlope() + LAND_ESTIMATE_MARGIN ? "the land under it will go from about " + lowest + " to " + highest + ", which is more than its maxSlope of " + patch.maxSlope()
				: highest < patch.minY() - LAND_ESTIMATE_MARGIN || lowest > patch.maxY() + LAND_ESTIMATE_MARGIN ? "the land there will be at about " + lowest + " to " + highest + ", and it's only for " + patch.minY() + " to " + patch.maxY()
				: null;
		if (why == null) {
			return true;
		}
		write(new Decision(patch.id(), dimension(level), seedOf(level), anchor.x(), anchor.z(), false, 0, 0, 0, why), false);
		return false;
	}

	private static boolean rolls(ServerLevel level, RuinPatch patch, ChunkPos anchor) {
		return patch.random(seedOf(level), anchor).nextFloat() < patch.chance();
	}

	/** Whether the land there will have the right biome, which needs nothing there to exist yet. It's looked at again when it does. */
	private static boolean suitsBiome(ServerLevel level, RuinPatch patch, ChunkPos anchor) {
		if (patch.biomes().isEmpty()) {
			return true;
		}
		int x = (anchor.x() + patch.chunksX() / 2) << 2;
		int z = (anchor.z() + patch.chunksZ() / 2) << 2;
		for (int y : new int[] {level.getSeaLevel(), (patch.minY() + patch.maxY()) / 2}) {
			if (patch.biomes().stream().anyMatch(level.getUncachedNoiseBiome(x, y >> 2, z)::is)) {
				return true;
			}
		}
		return false;
	}

	/** How many spots are still being worked on, so the gates can wait for them. */
	int busy() {
		return this.waiting.size() + (this.loading != null || this.building != null ? 1 : 0);
	}

	void tick(MinecraftServer server, long deadline) {
		if (!this.bigRuins.isEmpty() && this.ticks++ % SCAN_INTERVAL_TICKS == 0) {
			lookAheadOfPlayers(server);
		}
		if (this.building != null) {
			this.building.carryOn(deadline);
			return;
		}
		if (this.loading == null && !this.waiting.isEmpty()) {
			startLoading(this.waiting.pollFirst());
		}
		if (this.loading != null) {
			checkLoaded();
		}
	}

	private void lookAheadOfPlayers(MinecraftServer server) {
		int reach = server.getPlayerList().getViewDistance() + AHEAD_OF_VIEW;
		for (ServerPlayer player : server.getPlayerList().getPlayers()) {
			ChunkPos pos = player.chunkPosition();
			considerArea(player.level(), pos.x() - reach, pos.z() - reach, pos.x() + reach, pos.z() + reach);
		}
	}

	private void startLoading(Wanted wanted) {
		this.loading = wanted;
		this.loadingFor = 0;
		this.holding = landFor(wanted.patch(), wanted.anchor());
		this.holding.forEach(pos -> wanted.level().getChunkSource().addTicketWithRadius(TICKET, pos, TICKET_RADIUS));
	}

	private void release(Wanted wanted, List<ChunkPos> chunks) {
		chunks.forEach(pos -> wanted.level().getChunkSource().removeTicketWithRadius(TICKET, pos, TICKET_RADIUS));
	}

	private void checkLoaded() {
		Wanted wanted = this.loading;
		String key = Decision.key(wanted.patch().id(), dimension(wanted.level()), wanted.anchor().x(), wanted.anchor().z());
		boolean loaded = this.holding.stream().allMatch(pos -> wanted.level().getChunkSource().getChunkNow(pos.x(), pos.z()) != null);
		if (!loaded) {
			if (++this.loadingFor > LOAD_TIMEOUT_TICKS) {
				LOGGER.warn("ruin {} at chunk {} {}: its land took too long to load, so nothing's been decided", wanted.patch().id(), wanted.anchor().x(), wanted.anchor().z());
				this.waitingKeys.remove(key);
				release(wanted, this.holding);
				this.loading = null;
			}
			return;
		}
		this.loading = null;
		this.waitingKeys.remove(key);
		List<Piece> pieces = pieces(wanted.patch(), seedOf(wanted.level()), wanted.anchor());
		Fit fit = fit(wanted, pieces);
		if (fit.why() != null) {
			LOGGER.info("ruin {} at chunk {} {} wasn't placed: {}", wanted.patch().id(), wanted.anchor().x(), wanted.anchor().z(), fit.why());
			write(new Decision(wanted.patch().id(), dimension(wanted.level()), seedOf(wanted.level()), wanted.anchor().x(), wanted.anchor().z(), false, 0, 0, 0, fit.why()), false);
			release(wanted, this.holding);
			return;
		}
		// Before any block goes in, and it has to be on the disk by then, because everything after this depends on it.
		Decision decision = new Decision(wanted.patch().id(), dimension(wanted.level()), seedOf(wanted.level()), wanted.anchor().x(), wanted.anchor().z(), true,
				fit.origin().getX(), fit.origin().getY(), fit.origin().getZ(), null);
		if (!write(decision, true)) {
			release(wanted, this.holding);
			return;
		}
		Plan plan = new Plan(wanted.patch(), decision, chunksOf(pieces, wanted.anchor()));
		index(plan);
		this.building = new Building(wanted, plan, this.holding);
		// That proves it can go somewhere, so there's no need to make any more land to find out.
		if (this.tryingOut.remove(wanted.patch().id())) {
			this.waiting.removeIf(other -> {
				boolean same = other.patch().id().equals(wanted.patch().id());
				if (same) {
					this.waitingKeys.remove(Decision.key(other.patch().id(), dimension(other.level()), other.anchor().x(), other.anchor().z()));
				}
				return same;
			});
		}
	}

	/** Building a ruin that's been decided on, a chunk at a time, while its land is held loaded. */
	private final class Building {
		private final Wanted wanted;
		private final Plan plan;
		private final List<ChunkPos> held;
		private final Iterator<Long> remaining;
		private int done;
		private boolean paused;

		Building(Wanted wanted, Plan plan, List<ChunkPos> held) {
			this.wanted = wanted;
			this.plan = plan;
			this.held = held;
			this.remaining = plan.chunks().iterator();
		}

		void carryOn(long deadline) {
			if (this.paused) {
				return;
			}
			do {
				if (RuinPlans.this.pauseAfter >= 0 && this.done >= RuinPlans.this.pauseAfter) {
					LOGGER.info("chaos: ruin {} paused after {} of {} chunks", this.plan.patch().id(), this.done, this.plan.chunks().size());
					this.paused = true;
					return;
				}
				if (!this.remaining.hasNext()) {
					finish();
					return;
				}
				ChunkPos pos = ChunkPos.unpack(this.remaining.next());
				LevelChunk chunk = this.wanted.level().getChunkSource().getChunkNow(pos.x(), pos.z());
				if (chunk != null) {
					placeShare(this.wanted.level(), this.plan, chunk);
				}
				this.done++;
			} while (System.nanoTime() < deadline);
		}

		private void finish() {
			RuinPlans.this.building = null;
			RuinPlans.this.bigPlaced++;
			release(this.wanted, this.held);
			LOGGER.info("ruin {} placed at {} across {} chunks", this.plan.patch().id(), this.plan.decision().origin().toShortString(), this.plan.chunks().size());
			String name = this.plan.patch().name();
			BlockPos origin = this.plan.decision().origin();
			ServerModuleHost.instance().fire(events -> events.ruinPlaced(this.wanted.level(), name, origin));
		}
	}

	long bigPlaced() {
		return this.bigPlaced;
	}

	/** Either where it goes, or why it doesn't go here. */
	private record Fit(BlockPos origin, String why) {
		static Fit no(String why) {
			return new Fit(null, why);
		}
	}

	/** All of it or none of it, which is decided here and then never again. */
	private Fit fit(Wanted wanted, List<Piece> pieces) {
		ServerLevel level = wanted.level();
		RuinPatch patch = wanted.patch();
		ChunkPos anchor = wanted.anchor();
		for (long packed : chunksOf(pieces, anchor)) {
			ChunkPos pos = ChunkPos.unpack(packed);
			LevelChunk chunk = level.getChunkSource().getChunkNow(pos.x(), pos.z());
			if (chunk.getInhabitedTime() > 0 || Provenance.hasAnyTouched(chunk)) {
				return Fit.no("someone has been in chunk " + pos.x() + " " + pos.z());
			}
			if (taken(level, pos) || this.smallOnes.getOrDefault(dimension(level), Set.of()).contains(packed)) {
				return Fit.no("another ruin is already in chunk " + pos.x() + " " + pos.z());
			}
		}
		Fit origin = patch.underground() ? undergroundOrigin(level, patch, pieces, anchor) : surfaceOrigin(level, patch, pieces, anchor);
		if (origin.why() != null) {
			return origin;
		}
		BlockPos middle = new BlockPos(anchor.getMinBlockX() + patch.chunksX() * 8, origin.origin().getY(), anchor.getMinBlockZ() + patch.chunksZ() * 8);
		if (!patch.biomes().isEmpty() && patch.biomes().stream().noneMatch(level.getBiome(middle)::is)) {
			return Fit.no("it's in the wrong biome, " + level.getBiome(middle).getRegisteredName());
		}
		if (patch.highGround() > 0) {
			String low = highGround(level, patch, anchor);
			if (low != null) {
				return Fit.no(low);
			}
		}
		return origin;
	}

	private static BlockPos spot(ServerLevel level, RuinPatch patch, RuinPatch.Part part, BlockPos origin) {
		if (!patch.followTerrain()) {
			return origin.offset(part.x(), part.y(), part.z());
		}
		int x = origin.getX() + part.x();
		int z = origin.getZ() + part.z();
		LevelChunk chunk = level.getChunkSource().getChunkNow(x >> 4, z >> 4);
		return new BlockPos(x, ground(chunk, x & 15, z & 15).getY() + 1 + part.y(), z);
	}

	private Fit undergroundOrigin(ServerLevel level, RuinPatch patch, List<Piece> pieces, ChunkPos anchor) {
		RandomSource random = patch.random(seedOf(level), anchor);
		int room = Math.max(1, patch.maxY() - patch.minY());
		int start = random.nextInt(room);
		String last = "there's nowhere from " + patch.minY() + " to " + patch.maxY() + " it fits";
		// Without having to find a cave, there's just the one height to try, the same as a small one.
		for (int step = 0; step < (patch.opensOntoCave() ? room : 1); step++) {
			BlockPos origin = new BlockPos(anchor.getMinBlockX(), patch.minY() + (start + step) % room, anchor.getMinBlockZ());
			String problem = fits(level, patch, pieces.stream().map(Piece::part).toList(), origin);
			if (problem != null) {
				last = problem;
			} else if (!patch.opensOntoCave() || opensOntoCave(level, pieces.stream().map(Piece::part).toList(), origin)) {
				return new Fit(origin, null);
			} else {
				last = "it fits, but no cave reaches it, at any height from " + patch.minY() + " to " + patch.maxY();
			}
		}
		return Fit.no(last);
	}

	private static String fits(ServerLevel level, RuinPatch patch, List<RuinPatch.Part> parts, BlockPos origin) {
		for (RuinPatch.Part part : parts) {
			BlockPos spot = origin.offset(part.x(), part.y(), part.z());
			if (level.isOutsideBuildHeight(spot)) {
				return "it would stick out of the world at " + spot.toShortString();
			}
			LevelChunk chunk = level.getChunkSource().getChunkNow(spot.getX() >> 4, spot.getZ() >> 4);
			if (!patch.canReplace(chunk.getBlockState(spot))) {
				return BuiltInRegistries.BLOCK.getKey(chunk.getBlockState(spot).getBlock()) + " at " + spot.toShortString() + " isn't in what it replaces";
			}
		}
		return null;
	}

	/**
	 * Whether a cave's air reaches it. If it has any air of its own, that's its rooms, and it's one of those that has to touch the cave, so
	 * there's a way in. Otherwise any of it will do. It also has to be under the ground there, because open air doesn't make it a cave.
	 */
	static boolean opensOntoCave(ServerLevel level, List<RuinPatch.Part> parts, BlockPos origin) {
		boolean hollow = parts.stream().anyMatch(part -> part.state().isAir());
		Set<BlockPos> own = new HashSet<>();
		parts.forEach(part -> own.add(origin.offset(part.x(), part.y(), part.z())));
		for (RuinPatch.Part part : parts) {
			if (hollow && !part.state().isAir()) {
				continue;
			}
			BlockPos spot = origin.offset(part.x(), part.y(), part.z());
			for (Direction direction : Direction.values()) {
				BlockPos next = spot.relative(direction);
				if (own.contains(next)) {
					continue;
				}
				LevelChunk chunk = level.getChunkSource().getChunkNow(next.getX() >> 4, next.getZ() >> 4);
				if (chunk != null && next.getY() < chunk.getHeight(Heightmap.Types.WORLD_SURFACE, next.getX() & 15, next.getZ() & 15) && chunk.getBlockState(next).isAir()) {
					return true;
				}
			}
		}
		return false;
	}

	private Fit surfaceOrigin(ServerLevel level, RuinPatch patch, List<Piece> pieces, ChunkPos anchor) {
		int x = anchor.getMinBlockX();
		int z = anchor.getMinBlockZ();
		Set<Long> columns = new HashSet<>();
		List<Integer> heights = new ArrayList<>();
		Map<Block, Integer> others = new HashMap<>();
		int right = 0;
		for (Piece piece : pieces) {
			int partX = x + piece.part().x();
			int partZ = z + piece.part().z();
			if (!columns.add(((long) partX << 32) ^ (partZ & 0xFFFFFFFFL))) {
				continue;
			}
			LevelChunk chunk = level.getChunkSource().getChunkNow(partX >> 4, partZ >> 4);
			BlockPos floor = ground(chunk, partX & 15, partZ & 15);
			heights.add(floor.getY());
			Block found = chunk.getBlockState(floor).getBlock();
			if (patch.sitsOn(found)) {
				right++;
			} else {
				others.merge(found, 1, Integer::sum);
			}
		}
		if (right < heights.size() * MOST_OF_ITS_GROUND) {
			Block most = Collections.max(others.entrySet(), Map.Entry.comparingByValue()).getKey();
			return Fit.no("only " + right + " of the " + heights.size() + " columns it uses have ground in what it sits on, and most of the rest is " + BuiltInRegistries.BLOCK.getKey(most));
		}
		heights.sort(Comparator.naturalOrder());
		int lowest = heights.getFirst();
		int highest = heights.getLast();
		int middle = heights.get(heights.size() / 2);
		if (highest - lowest > patch.maxSlope()) {
			return Fit.no("the ground under it goes from " + lowest + " to " + highest + ", which is more than its maxSlope of " + patch.maxSlope());
		}
		if (lowest < patch.minY() - 1 || highest >= patch.maxY()) {
			return Fit.no("the ground under it goes from " + lowest + " to " + highest + ", and it's only for " + patch.minY() + " to " + patch.maxY());
		}
		BlockPos origin = new BlockPos(x, middle + 1, z);
		if (patch.followTerrain()) {
			// Each column goes by its own ground, so all this has to say is roughly where it is.
			for (Piece piece : pieces) {
				BlockPos spot = spot(level, patch, piece.part(), origin);
				LevelChunk chunk = level.getChunkSource().getChunkNow(spot.getX() >> 4, spot.getZ() >> 4);
				if (level.isOutsideBuildHeight(spot) || !patch.canReplace(chunk.getBlockState(spot))) {
					return Fit.no(BuiltInRegistries.BLOCK.getKey(chunk.getBlockState(spot).getBlock()) + " at " + spot.toShortString() + " isn't in what it replaces");
				}
			}
			return new Fit(origin, null);
		}
		String problem = fits(level, patch, pieces.stream().map(Piece::part).toList(), origin);
		return problem != null ? Fit.no(problem) : new Fit(origin, null);
	}

	/** Compares the ground in the middle of it with the ground just beyond each of its sides. */
	private static String highGround(ServerLevel level, RuinPatch patch, ChunkPos anchor) {
		int minX = anchor.getMinBlockX();
		int minZ = anchor.getMinBlockZ();
		int wide = patch.chunksX() * 16;
		int deep = patch.chunksZ() * 16;
		int middleX = minX + wide / 2;
		int middleZ = minZ + deep / 2;
		int[][] around = {{minX - JUST_BEYOND, middleZ}, {minX + wide + JUST_BEYOND, middleZ}, {middleX, minZ - JUST_BEYOND}, {middleX, minZ + deep + JUST_BEYOND}};
		double total = 0;
		for (int[] place : around) {
			total += groundHeight(level, place[0], place[1]);
		}
		double rise = groundHeight(level, middleX, middleZ) - total / around.length;
		return rise >= patch.highGround() ? null : "its middle is only " + "%.1f".formatted(rise) + " above what's around it, and it wants " + patch.highGround();
	}

	private static int groundHeight(ServerLevel level, int x, int z) {
		return ground(level.getChunkSource().getChunkNow(x >> 4, z >> 4), x & 15, z & 15).getY();
	}

	/** The heightmap stops at a tree's canopy, and a ruin under the trees should still sit on the forest floor. */
	static BlockPos ground(LevelChunk chunk, int x, int z) {
		BlockPos.MutableBlockPos pos = new BlockPos.MutableBlockPos(chunk.getPos().getMinBlockX() + x, chunk.getHeight(Heightmap.Types.OCEAN_FLOOR, x, z), chunk.getPos().getMinBlockZ() + z);
		while (chunk.getBlockState(pos).is(BlockTags.LEAVES) || chunk.getBlockState(pos).is(BlockTags.LOGS)) {
			pos.move(Direction.DOWN);
		}
		return pos.immutable();
	}

	/** Where this ruin is, or may turn up, nearest first, without loading anything. */
	List<RuinSpot> near(RuinPatch patch, ServerLevel level, BlockPos near, int chunks) {
		ChunkPos centre = ChunkPos.containing(near);
		int reach = Math.min(chunks, patch.spacing() > 0 ? FURTHEST_SPACED : FURTHEST_UNSPACED);
		List<ChunkPos> spots = new ArrayList<>();
		if (patch.spacing() > 0) {
			int cell = patch.cell();
			for (int cellX = Math.floorDiv(centre.x() - reach, cell); cellX <= Math.floorDiv(centre.x() + reach, cell); cellX++) {
				for (int cellZ = Math.floorDiv(centre.z() - reach, cell); cellZ <= Math.floorDiv(centre.z() + reach, cell); cellZ++) {
					spots.add(patch.spotIn(seedOf(level), cellX, cellZ));
				}
			}
		} else {
			for (int x = centre.x() - reach; x <= centre.x() + reach; x++) {
				for (int z = centre.z() - reach; z <= centre.z() + reach; z++) {
					spots.add(new ChunkPos(x, z));
				}
			}
		}
		List<RuinSpot> found = new ArrayList<>();
		spots.stream()
				.filter(pos -> Math.abs(pos.x() - centre.x()) <= reach && Math.abs(pos.z() - centre.z()) <= reach)
				.sorted(Comparator.comparingInt(pos -> pos.distanceSquared(centre)))
				.forEach(pos -> {
					if (found.size() < MOST_SPOTS) {
						Decision decision = this.decided.get(Decision.key(patch.id(), dimension(level), pos.x(), pos.z()));
						if (decision != null && decision.placed()) {
							found.add(new RuinSpot(decision.origin(), true));
						} else if (decision == null && rolls(level, patch, pos) && suitsBiome(level, patch, pos) && !alreadyDecided(level, patch, pos)) {
							found.add(new RuinSpot(guess(level, patch, pos, found.size()), false));
						}
					}
				});
		return found;
	}

	/** A small ruin has no line in the file unless it was placed, so a chunk that's here and has had its chance has said no. */
	private static boolean alreadyDecided(ServerLevel level, RuinPatch patch, ChunkPos pos) {
		LevelChunk chunk = level.getChunkSource().getChunkNow(pos.x(), pos.z());
		return !patch.big() && chunk != null && Provenance.appliedPatches(chunk).contains(patch.id());
	}

	private static BlockPos guess(ServerLevel level, RuinPatch patch, ChunkPos pos, int already) {
		int x = pos.getMinBlockX();
		int z = pos.getMinBlockZ();
		if (patch.underground()) {
			return new BlockPos(x, (patch.minY() + patch.maxY()) / 2, z);
		}
		// Working out the land costs something, so only for those most likely to matter.
		int y = already < HEIGHTS_GUESSED
				? level.getChunkSource().getGenerator().getBaseHeight(x, z, Heightmap.Types.OCEAN_FLOOR_WG, level, level.getChunkSource().randomState())
				: level.getSeaLevel();
		return new BlockPos(x, y, z);
	}

	/**
	 * For the gate to prove a new one can be placed at all: decides the nearest spots to a place with the right biome, whether or not they'd have rolled it, until one takes it.
	 * It goes further out until it has enough, because a biome can be a long way from anywhere. Only for a test world.
	 */
	void tryOut(ServerLevel level, RuinPatch patch, BlockPos near, int spots, Consumer<String> report) {
		ChunkPos centre = ChunkPos.containing(near);
		int cell = patch.cell();
		int queued = 0;
		this.tryingOut.add(patch.id());
		for (int ring = 0; ring <= FURTHEST_TRIED_CELLS && queued < spots; ring++) {
			for (int dx = -ring; dx <= ring; dx++) {
				for (int dz = -ring; dz <= ring; dz++) {
					if (Math.max(Math.abs(dx), Math.abs(dz)) != ring || queued >= spots) {
						continue;
					}
					ChunkPos anchor = patch.spotIn(seedOf(level), Math.floorDiv(centre.x(), cell) + dx, Math.floorDiv(centre.z(), cell) + dz);
					String key = Decision.key(patch.id(), dimension(level), anchor.x(), anchor.z());
					if (!this.decided.containsKey(key) && !this.waitingKeys.contains(key) && suitsBiome(level, patch, anchor) && goodLandLikely(level, patch, anchor)) {
						this.waitingKeys.add(key);
						this.waiting.addLast(new Wanted(level, patch, anchor));
						queued++;
					}
				}
			}
		}
		report.accept("Trying " + queued + " spots for " + patch.id() + ", nearest first");
	}

	/** How many of this ruin are really there, and the reasons it wasn't placed anywhere else, for the gate to report. */
	String summary(RuinPatch patch) {
		long placed = this.decided.values().stream().filter(decision -> decision.ruin().equals(patch.id()) && decision.placed()).count();
		List<String> why = this.decided.values().stream().filter(decision -> decision.ruin().equals(patch.id()) && !decision.placed()).map(Decision::why).distinct().limit(5).toList();
		return patch.id() + ": placed " + placed + (why.isEmpty() ? "" : ", elsewhere " + String.join("; ", why));
	}
}
