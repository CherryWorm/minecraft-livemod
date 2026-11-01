package gm.conduit.mobs;

import com.google.gson.Gson;
import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import de.tomalbrc.bil.core.model.Model;
import de.tomalbrc.bil.file.loader.BbModelLoader;
import eu.pb4.polymer.core.api.entity.PolymerEntityUtils;
import gm.conduit.Conduit;
import net.fabricmc.fabric.api.event.lifecycle.v1.ServerLifecycleEvents;
import net.fabricmc.fabric.api.event.lifecycle.v1.ServerTickEvents;
import net.fabricmc.fabric.api.object.builder.v1.entity.FabricDefaultAttributeRegistry;
import net.minecraft.core.BlockPos;
import net.minecraft.core.Registry;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.core.registries.Registries;
import net.minecraft.resources.Identifier;
import net.minecraft.resources.ResourceKey;
import net.minecraft.server.MinecraftServer;
import net.minecraft.server.level.ServerLevel;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.tags.TagKey;
import net.minecraft.util.RandomSource;
import net.minecraft.world.Difficulty;
import net.minecraft.world.entity.EntitySpawnReason;
import net.minecraft.world.entity.EntityType;
import net.minecraft.world.entity.Mob;
import net.minecraft.world.entity.MobCategory;
import net.minecraft.world.entity.ai.attributes.Attributes;
import net.minecraft.world.level.biome.Biome;
import net.minecraft.world.level.levelgen.Heightmap;
import net.minecraft.world.phys.AABB;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.io.IOException;
import java.io.InputStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * The pool of mob slots, and the current release's definitions for them. Monster and creature are separate
 * ranges because that one fact is fixed when a type is registered. Spawning is done here rather than through
 * biomes, because a biome's spawn list can't change without a restart.
 */
public final class SlotMobs {
	// Enough for a world that's all about its creatures. These can only grow while no world depends on them, because
	// creature IDs start where monster IDs end, and worlds store those IDs.
	public static final int MONSTER_COUNT = 240;
	public static final int CREATURE_COUNT = 480;

	private static final Logger LOGGER = LoggerFactory.getLogger("Conduit");
	private static final Path FILE = Path.of("config", "conduit", "mobs.json");
	private static final Path MODELS = Path.of("config", "conduit", "models");
	private static final int SPAWN_EVERY_TICKS = 40;
	private static final int SPAWN_MIN_DISTANCE = 24;
	private static final int SPAWN_MAX_DISTANCE = 48;
	private static final int CROWD_RADIUS = 64;
	private static final int CROWD_LIMIT = 14;

	private static final Map<EntityType<?>, MobDefinition> DEFINITIONS = new HashMap<>();
	private static final Map<String, Model> LOADED_MODELS = new HashMap<>();

	private SlotMobs() {}

	public static void register() {
		for (int i = 0; i < MONSTER_COUNT + CREATURE_COUNT; i++) {
			registerType("e%04d".formatted(i + 1), i < MONSTER_COUNT ? MobCategory.MONSTER : MobCategory.CREATURE);
		}
		// Now rather than when the server starts, because the resource pack is built before then and models go in it.
		reload();
		ServerLifecycleEvents.END_DATA_PACK_RELOAD.register((server, resources, success) -> reload());
		ServerTickEvents.END_SERVER_TICK.register(server -> {
			if (server.getTickCount() % SPAWN_EVERY_TICKS == 0 && !DEFINITIONS.isEmpty()) {
				server.getPlayerList().getPlayers().forEach(player -> trySpawn(server, player));
			}
		});
	}

	private static void registerType(String path, MobCategory category) {
		Identifier id = Identifier.fromNamespaceAndPath(Conduit.NAMESPACE, path);
		EntityType<SlotMob> type = EntityType.Builder.<SlotMob>of(SlotMob::new, category)
				.sized(0.9F, 0.9F)
				.clientTrackingRange(10)
				.build(ResourceKey.create(Registries.ENTITY_TYPE, id));
		Registry.register(BuiltInRegistries.ENTITY_TYPE, id, type);
		PolymerEntityUtils.registerType(type);
		FabricDefaultAttributeRegistry.register(type, Mob.createMobAttributes()
				.add(Attributes.ATTACK_DAMAGE, 1.0)
				.add(Attributes.FLYING_SPEED, 0.4)
				.add(Attributes.FOLLOW_RANGE, 24.0)
				.add(Attributes.ARMOR, 0.0));
	}

	public static MobDefinition definition(EntityType<?> type) {
		return DEFINITIONS.get(type);
	}

	public static Model model(String name) {
		return LOADED_MODELS.get(name);
	}

	private static void reload() {
		DEFINITIONS.clear();
		if (!Files.exists(FILE)) {
			return;
		}
		try {
			JsonObject json = new Gson().fromJson(Files.readString(FILE), JsonObject.class);
			for (Map.Entry<String, JsonElement> entry : json.entrySet()) {
				MobDefinition definition = MobDefinition.parse(entry.getValue().getAsJsonObject());
				loadModel(definition.model());
				BuiltInRegistries.ENTITY_TYPE.getOptional(Identifier.parse(entry.getKey()))
						.ifPresent(type -> DEFINITIONS.put(type, definition));
			}
			LOGGER.info("mobs bound: {}", DEFINITIONS.size());
		} catch (IOException | RuntimeException error) {
			LOGGER.error("Can't read {}", FILE, error);
		}
	}

	public static Model loadModel(String name) throws IOException {
		Model loaded = LOADED_MODELS.get(name);
		if (loaded != null) {
			return loaded;
		}
		// Named by hash, so a changed model is simply another file and nothing in the pack gives it away.
		try (InputStream input = Files.newInputStream(MODELS.resolve(name + ".bbmodel"))) {
			loaded = new BbModelLoader().load(input, name);
			LOADED_MODELS.put(name, loaded);
			return loaded;
		}
	}

	private static void trySpawn(MinecraftServer server, ServerPlayer player) {
		if (!(player.level() instanceof ServerLevel level) || player.isSpectator()) {
			return;
		}
		RandomSource random = level.getRandom();
		List<Map.Entry<EntityType<?>, MobDefinition>> candidates = new ArrayList<>();
		int total = 0;
		for (Map.Entry<EntityType<?>, MobDefinition> entry : DEFINITIONS.entrySet()) {
			if (entry.getValue().spawn() != null && entry.getValue().spawn().dimension().equals(level.dimension())) {
				candidates.add(entry);
				total += entry.getValue().spawn().weight();
			}
		}
		if (total == 0) {
			return;
		}
		int roll = random.nextInt(total);
		for (Map.Entry<EntityType<?>, MobDefinition> entry : candidates) {
			roll -= entry.getValue().spawn().weight();
			if (roll < 0) {
				spawnNear(level, player, entry.getKey(), entry.getValue().spawn(), random);
				return;
			}
		}
	}

	private static void spawnNear(ServerLevel level, ServerPlayer player, EntityType<?> type, MobDefinition.Spawn spawn, RandomSource random) {
		if (type.getCategory() == MobCategory.MONSTER && level.getDifficulty() == Difficulty.PEACEFUL) {
			return;
		}
		AABB area = player.getBoundingBox().inflate(CROWD_RADIUS);
		List<SlotMob> nearby = level.getEntitiesOfClass(SlotMob.class, area);
		if (nearby.size() >= CROWD_LIMIT || nearby.stream().filter(mob -> mob.getType() == type).count() >= spawn.cap()) {
			return;
		}
		double angle = random.nextDouble() * Math.PI * 2;
		int distance = SPAWN_MIN_DISTANCE + random.nextInt(SPAWN_MAX_DISTANCE - SPAWN_MIN_DISTANCE);
		int x = player.getBlockX() + (int) (Math.cos(angle) * distance);
		int z = player.getBlockZ() + (int) (Math.sin(angle) * distance);
		if (!level.hasChunk(x >> 4, z >> 4)) {
			return;
		}
		BlockPos spot = spawn.underground() ? caveSpot(level, x, z, spawn, random) : surfaceSpot(level, x, z, spawn);
		if (spot == null || !lightAllows(level, spot, spawn.light()) || !biomeAllows(level, spot, spawn.biomes())) {
			return;
		}
		type.spawn(level, spot, EntitySpawnReason.NATURAL);
	}

	private static BlockPos surfaceSpot(ServerLevel level, int x, int z, MobDefinition.Spawn spawn) {
		int y = level.getHeight(Heightmap.Types.MOTION_BLOCKING_NO_LEAVES, x, z);
		BlockPos spot = new BlockPos(x, y, z);
		return y >= spawn.minY() && y <= spawn.maxY() && canStand(level, spot) ? spot : null;
	}

	private static BlockPos caveSpot(ServerLevel level, int x, int z, MobDefinition.Spawn spawn, RandomSource random) {
		int top = Math.min(spawn.maxY(), level.getHeight(Heightmap.Types.WORLD_SURFACE, x, z) - 4);
		if (top <= spawn.minY()) {
			return null;
		}
		for (int tries = 0; tries < 6; tries++) {
			BlockPos spot = new BlockPos(x, spawn.minY() + random.nextInt(top - spawn.minY()), z);
			if (canStand(level, spot)) {
				return spot;
			}
		}
		return null;
	}

	private static boolean canStand(ServerLevel level, BlockPos spot) {
		return level.getBlockState(spot.below()).isSolidRender() && level.getBlockState(spot).isAir() && level.getBlockState(spot.above()).isAir();
	}

	private static boolean lightAllows(ServerLevel level, BlockPos spot, String rule) {
		int light = level.getMaxLocalRawBrightness(spot);
		return switch (rule) {
			case "dark" -> light <= 7;
			case "bright" -> light >= 9;
			default -> true;
		};
	}

	private static boolean biomeAllows(ServerLevel level, BlockPos spot, List<String> biomes) {
		if (biomes.isEmpty()) {
			return true;
		}
		var biome = level.getBiome(spot);
		for (String entry : biomes) {
			if (entry.startsWith("#")) {
				if (biome.is(TagKey.create(Registries.BIOME, Identifier.parse(entry.substring(1))))) {
					return true;
				}
			} else if (biome.is(ResourceKey.<Biome>create(Registries.BIOME, Identifier.parse(entry)))) {
				return true;
			}
		}
		return false;
	}
}
