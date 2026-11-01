package gm.conduit.dimensions;

import com.google.gson.Gson;
import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import com.google.gson.JsonParseException;
import com.google.gson.reflect.TypeToken;
import com.mojang.serialization.JsonOps;
import net.fabricmc.fabric.api.entity.event.v1.ServerEntityLevelChangeEvents;
import net.fabricmc.fabric.api.entity.event.v1.ServerPlayerEvents;
import net.fabricmc.fabric.api.event.lifecycle.v1.ServerLifecycleEvents;
import net.fabricmc.fabric.api.event.lifecycle.v1.ServerTickEvents;
import net.fabricmc.fabric.api.networking.v1.ServerPlayConnectionEvents;
import net.minecraft.core.BlockPos;
import net.minecraft.core.Direction;
import net.minecraft.core.registries.Registries;
import net.minecraft.network.chat.Component;
import net.minecraft.resources.Identifier;
import net.minecraft.resources.RegistryOps;
import net.minecraft.resources.ResourceKey;
import net.minecraft.server.MinecraftServer;
import net.minecraft.server.level.ServerLevel;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.world.level.Level;
import net.minecraft.world.level.block.Blocks;
import net.minecraft.world.level.block.state.BlockState;
import net.minecraft.world.level.chunk.ChunkGenerator;
import net.minecraft.world.level.levelgen.Heightmap;
import net.minecraft.world.level.portal.TeleportTransition;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import xyz.nucleoid.fantasy.Fantasy;
import xyz.nucleoid.fantasy.RuntimeLevelConfig;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * The dimensions a release declares, opened while the server runs. Fantasy keeps them out of the world's own settings, which the game
 * reads at every boot, so a rollback can't leave a world that won't load: a dimension that's no longer declared just doesn't open, its land
 * stays on disk in case it comes back, and anyone who was in it is brought back when they next join.
 */
public final class Dimensions {
	private static final Logger LOGGER = LoggerFactory.getLogger("Conduit");
	private static final Path FILE = Path.of("config", "conduit", "dimensions.json");
	private static final Path RETURNS = Path.of("config", "conduit", "dimension_returns.json");
	private static final Gson GSON = new Gson();
	private static final int SEARCH_REACH = 16;
	private static final int SEARCH_STEP = 4;
	private static final int PLATFORM_Y = 64;
	private static final int PLATFORM_REACH = 2;
	private static final int HEAD_ROOM = 2;
	private static final Map<ResourceKey<Level>, Definition> OPEN = new HashMap<>();
	private static final Map<String, Return> RETURN_POINTS = new HashMap<>();
	private static final Set<ServerPlayer> JOINING = new HashSet<>();

	private record Spawn(int x, int z) {}

	private record Definition(String type, JsonObject generator, Spawn spawn) {}

	/** Where to send someone back to. A null level means wherever they'd respawn, for someone who didn't get there through {@link #enter}. */
	private record Return(String level, double x, double y, double z, float yaw, float pitch) {}

	private Dimensions() {}

	public static void register() {
		ServerLifecycleEvents.SERVER_STARTED.register(server -> {
			readReturns();
			reload(server);
		});
		// A release writes its files before it reloads, so this finds any dimension it added, with no restart.
		ServerLifecycleEvents.END_DATA_PACK_RELOAD.register((server, resources, success) -> reload(server));
		// Fabric says so before the player is in the world or the player list, so this waits for the next tick.
		ServerPlayConnectionEvents.JOIN.register((handler, sender, server) -> JOINING.add(handler.player));
		ServerTickEvents.END_SERVER_TICK.register(server -> {
			JOINING.stream().filter(player -> !player.hasDisconnected()).forEach(Dimensions::bringBackIfStranded);
			JOINING.clear();
		});
		ServerEntityLevelChangeEvents.AFTER_PLAYER_CHANGE_LEVEL.register((player, origin, destination) -> changedLevel(player, origin, destination));
		ServerPlayerEvents.AFTER_RESPAWN.register((old, player, alive) -> {
			if (!OPEN.containsKey(player.level().dimension())) {
				forget(player);
			}
		});
	}

	/** Which level a patch or a mob is for. Saying nothing means the overworld, as it always has. */
	public static ResourceKey<Level> levelKey(String id) {
		return id == null ? Level.OVERWORLD : ResourceKey.create(Registries.DIMENSION, Identifier.parse(id));
	}

	/** One of the dimensions by its slot, or null if it isn't open. */
	public static ServerLevel level(MinecraftServer server, String slot) {
		ResourceKey<Level> key = levelKey("gm:" + slot);
		return OPEN.containsKey(key) ? server.getLevel(key) : null;
	}

	private static void reload(MinecraftServer server) {
		if (!Files.exists(FILE)) {
			return;
		}
		try {
			JsonObject json = GSON.fromJson(Files.readString(FILE), JsonObject.class);
			for (Map.Entry<String, JsonElement> entry : json.entrySet()) {
				ResourceKey<Level> key = levelKey(entry.getKey());
				if (OPEN.containsKey(key)) {
					continue;
				}
				// One bad dimension shouldn't take the rest down too, and the error fails the release's log scan.
				try {
					Definition definition = GSON.fromJson(entry.getValue(), Definition.class);
					open(server, key.identifier(), definition);
					OPEN.put(key, definition);
					LOGGER.info("dimension {} open", key.identifier());
				} catch (RuntimeException error) {
					LOGGER.error("Can't open dimension {}", key.identifier(), error);
				}
			}
		} catch (IOException | RuntimeException error) {
			LOGGER.error("Can't open dimension from {}", FILE, error);
		}
	}

	private static void open(MinecraftServer server, Identifier id, Definition definition) {
		RegistryOps<JsonElement> ops = server.registryAccess().createSerializationContext(JsonOps.INSTANCE);
		ChunkGenerator generator = ChunkGenerator.CODEC.parse(ops, definition.generator()).getOrThrow();
		Fantasy.get(server).getOrOpenPersistentLevel(id, new RuntimeLevelConfig()
				.setDimensionType(ResourceKey.create(Registries.DIMENSION_TYPE, Identifier.parse(definition.type())))
				.setGenerator(generator)
				.setSeed(server.overworld().getSeed() + id.toString().hashCode())
				.mirrorOverworldGameState());
	}

	/** Sends a player to a dimension's spawn, or the nearest safe ground to it, and remembers where to send them back to. */
	public static void enter(ServerPlayer player, String slot) {
		ServerLevel from = player.level();
		ServerLevel level = level(from.getServer(), slot);
		if (level == null) {
			throw new IllegalStateException("Dimension " + slot + " isn't open");
		}
		if (!OPEN.containsKey(from.dimension())) {
			remember(player, new Return(from.dimension().identifier().toString(), player.getX(), player.getY(), player.getZ(), player.getYRot(), player.getXRot()));
		}
		Spawn spawn = OPEN.get(level.dimension()).spawn();
		BlockPos spot = safeSpot(level, spawn == null ? 0 : spawn.x(), spawn == null ? 0 : spawn.z());
		player.teleportTo(level, spot.getX() + 0.5, spot.getY(), spot.getZ() + 0.5, Set.of(), player.getYRot(), player.getXRot(), true);
	}

	/** Sends a player back to where they entered from, or to wherever they'd respawn if that's gone. Does nothing for someone who isn't in one. */
	public static void leave(ServerPlayer player) {
		Return home = RETURN_POINTS.get(player.getStringUUID());
		if (home == null && !OPEN.containsKey(player.level().dimension())) {
			return;
		}
		forget(player);
		ServerLevel level = home == null || home.level() == null ? null : player.level().getServer().getLevel(levelKey(home.level()));
		if (level != null) {
			player.teleportTo(level, home.x(), home.y(), home.z(), Set.of(), home.yaw(), home.pitch(), true);
		} else {
			player.teleport(player.findRespawnPositionAndUseSpawnBlock(false, TeleportTransition.DO_NOTHING));
		}
	}

	/** The game puts someone from a dimension that's gone into the overworld at the same coordinates, which could be inside a mountain. */
	private static void bringBackIfStranded(ServerPlayer player) {
		if (RETURN_POINTS.containsKey(player.getStringUUID()) && !OPEN.containsKey(player.level().dimension())) {
			leave(player);
			player.sendSystemMessage(Component.literal("The place you were in isn't there any more, so you've been brought back."));
		}
	}

	private static void changedLevel(ServerPlayer player, ServerLevel origin, ServerLevel destination) {
		if (!OPEN.containsKey(destination.dimension())) {
			forget(player);
		} else if (!RETURN_POINTS.containsKey(player.getStringUUID())) {
			// A module sent them in by itself, so there's no knowing exactly where from.
			remember(player, new Return(null, 0, 0, 0, 0, 0));
		}
	}

	/** Looks outward from a spot for somewhere to stand. With nothing to stand on at all, it makes a small platform, as the game does in the End. */
	private static BlockPos safeSpot(ServerLevel level, int x, int z) {
		for (int reach = 0; reach <= SEARCH_REACH; reach += SEARCH_STEP) {
			for (int dx = -reach; dx <= reach; dx += SEARCH_STEP) {
				for (int dz = -reach; dz <= reach; dz += SEARCH_STEP) {
					BlockPos found = Math.max(Math.abs(dx), Math.abs(dz)) == reach ? standingRoom(level, x + dx, z + dz) : null;
					if (found != null) {
						return found;
					}
				}
			}
		}
		BlockPos spot = new BlockPos(x, Math.clamp(PLATFORM_Y, level.getMinY() + 1, level.getMaxY() - HEAD_ROOM), z);
		for (BlockPos pos : BlockPos.betweenClosed(spot.offset(-PLATFORM_REACH, -1, -PLATFORM_REACH), spot.offset(PLATFORM_REACH, -1, PLATFORM_REACH))) {
			level.setBlockAndUpdate(pos, Blocks.STONE.defaultBlockState());
		}
		return spot;
	}

	/** The highest place to stand in a column. A dimension with a roof is searched from just under it, or everyone would end up on top. */
	private static BlockPos standingRoom(ServerLevel level, int x, int z) {
		level.getChunk(x >> 4, z >> 4);
		int top = level.dimensionType().hasCeiling() ? level.getMinY() + level.dimensionType().logicalHeight() - HEAD_ROOM : level.getHeight(Heightmap.Types.MOTION_BLOCKING_NO_LEAVES, x, z);
		for (int y = top; y > level.getMinY(); y--) {
			BlockPos spot = new BlockPos(x, y, z);
			if (isClear(level, spot) && isClear(level, spot.above()) && isFirm(level, spot.below())) {
				return spot;
			}
			// Under open water, the first place to stand could be anything, deep in a cave or a sealed room with mobs in it. So that's no place to arrive.
			if (!level.dimensionType().hasCeiling() && !level.getBlockState(spot).getFluidState().isEmpty()) {
				return null;
			}
		}
		return null;
	}

	private static boolean isClear(ServerLevel level, BlockPos pos) {
		BlockState state = level.getBlockState(pos);
		return state.getCollisionShape(level, pos).isEmpty() && state.getFluidState().isEmpty();
	}

	private static boolean isFirm(ServerLevel level, BlockPos pos) {
		BlockState state = level.getBlockState(pos);
		return state.isFaceSturdy(level, pos, Direction.UP) && !state.is(Blocks.MAGMA_BLOCK);
	}

	private static void remember(ServerPlayer player, Return home) {
		RETURN_POINTS.put(player.getStringUUID(), home);
		writeReturns();
	}

	private static void forget(ServerPlayer player) {
		if (RETURN_POINTS.remove(player.getStringUUID()) != null) {
			writeReturns();
		}
	}

	private static void readReturns() {
		if (!Files.exists(RETURNS)) {
			return;
		}
		try {
			Map<String, Return> saved = GSON.fromJson(Files.readString(RETURNS), new TypeToken<Map<String, Return>>() {}.getType());
			RETURN_POINTS.putAll(saved);
		} catch (IOException | JsonParseException error) {
			LOGGER.warn("Can't read {}, so nobody can be sent back from a dimension that's gone", RETURNS, error);
		}
	}

	private static void writeReturns() {
		try {
			Files.createDirectories(RETURNS.getParent());
			Files.writeString(RETURNS, GSON.toJson(RETURN_POINTS));
		} catch (IOException error) {
			LOGGER.warn("Can't write {}", RETURNS, error);
		}
	}
}
