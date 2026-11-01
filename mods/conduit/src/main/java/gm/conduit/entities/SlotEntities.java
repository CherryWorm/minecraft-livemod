package gm.conduit.entities;

import com.google.gson.Gson;
import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import eu.pb4.polymer.core.api.entity.PolymerEntityUtils;
import gm.conduit.Conduit;
import gm.conduit.mobs.SlotMobs;
import net.fabricmc.fabric.api.event.lifecycle.v1.ServerLifecycleEvents;
import net.fabricmc.fabric.api.event.lifecycle.v1.ServerTickEvents;
import net.minecraft.core.Registry;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.core.registries.Registries;
import net.minecraft.resources.Identifier;
import net.minecraft.resources.ResourceKey;
import net.minecraft.server.level.ServerLevel;
import net.minecraft.world.entity.Entity;
import net.minecraft.world.entity.EntitySpawnReason;
import net.minecraft.world.entity.EntityType;
import net.minecraft.world.entity.MobCategory;
import net.minecraft.world.level.entity.EntityTypeTest;
import net.minecraft.world.phys.Vec3;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.HashMap;
import java.util.Map;
import java.util.function.Function;

/**
 * The pools of everything alive that isn't a mob, and the current release's definitions for them. Like mobs, these are fixed at
 * boot and mean nothing until a release says what each one is. Each pool has its own letter, so they can grow without moving each other.
 */
public final class SlotEntities {
	public static final int PROJECTILE_COUNT = 240;
	public static final int VEHICLE_COUNT = 120;
	public static final int PROP_COUNT = 480;

	private static final Logger LOGGER = LoggerFactory.getLogger("Conduit");
	private static final Path FILE = Path.of("config", "conduit", "entities.json");
	/** Far enough to see one coming, and no further, because a vehicle or a shot moves through hundreds of players' views. */
	private static final int TRACKING_CHUNKS = 10;
	/** However many a module asks for. Each is several entities for every player who can see it. */
	private static final int MOST_FLYING = 300;
	private static final int FORGET_SHOTS_AFTER = 4096;

	private static final Map<EntityType<?>, ProjectileDefinition> PROJECTILES = new HashMap<>();
	private static final Map<EntityType<?>, VehicleDefinition> VEHICLES = new HashMap<>();
	private static final Map<EntityType<?>, PropDefinition> PROPS = new HashMap<>();
	private static final Map<String, Long> LAST_SHOTS = new HashMap<>();
	private static long countedAt = -1;
	private static int counted;

	private SlotEntities() {}

	public static void register() {
		for (int i = 0; i < PROJECTILE_COUNT; i++) {
			// Never saved, because a shot isn't worth bringing back after a restart and would only build up in a world's files.
			register("p%04d".formatted(i + 1), EntityType.Builder.<SlotProjectile>of(SlotProjectile::new, MobCategory.MISC).noSave().noLootTable());
		}
		for (int i = 0; i < VEHICLE_COUNT; i++) {
			register("v%04d".formatted(i + 1), EntityType.Builder.<SlotVehicle>of(SlotVehicle::new, MobCategory.MISC).noLootTable());
		}
		for (int i = 0; i < PROP_COUNT; i++) {
			register("o%04d".formatted(i + 1), EntityType.Builder.<SlotProp>of(SlotProp::new, MobCategory.MISC).noLootTable());
		}
		// Now rather than when the server starts, because the resource pack is built before then and models go in it.
		reload();
		ServerLifecycleEvents.END_DATA_PACK_RELOAD.register((server, resources, success) -> reload());
		ServerTickEvents.END_SERVER_TICK.register(Beams::tick);
	}

	private static <T extends Entity> void register(String path, EntityType.Builder<T> builder) {
		Identifier id = Identifier.fromNamespaceAndPath(Conduit.NAMESPACE, path);
		// Every tick, because these are what a player is watching or sitting on, and a late position shows.
		EntityType<T> type = builder.sized(0.5F, 0.5F).clientTrackingRange(TRACKING_CHUNKS).updateInterval(1).build(ResourceKey.create(Registries.ENTITY_TYPE, id));
		Registry.register(BuiltInRegistries.ENTITY_TYPE, id, type);
		PolymerEntityUtils.registerType(type);
	}

	public static ProjectileDefinition projectile(EntityType<?> type) {
		return PROJECTILES.get(type);
	}

	public static VehicleDefinition vehicle(EntityType<?> type) {
		return VEHICLES.get(type);
	}

	public static PropDefinition prop(EntityType<?> type) {
		return PROPS.get(type);
	}

	private static void reload() {
		PROJECTILES.clear();
		VEHICLES.clear();
		PROPS.clear();
		LAST_SHOTS.clear();
		if (!Files.exists(FILE)) {
			return;
		}
		try {
			JsonObject json = new Gson().fromJson(Files.readString(FILE), JsonObject.class);
			read(json, "projectiles", ProjectileDefinition::parse, ProjectileDefinition::model, PROJECTILES);
			read(json, "vehicles", VehicleDefinition::parse, VehicleDefinition::model, VEHICLES);
			read(json, "props", PropDefinition::parse, PropDefinition::model, PROPS);
			LOGGER.info("entities bound: {} projectiles, {} vehicles, {} props", PROJECTILES.size(), VEHICLES.size(), PROPS.size());
		} catch (IOException | RuntimeException error) {
			LOGGER.error("Can't read {}", FILE, error);
		}
	}

	private static <D> void read(JsonObject json, String table, Function<JsonObject, D> parse, Function<D, String> model, Map<EntityType<?>, D> into) throws IOException {
		if (!json.has(table)) {
			return;
		}
		for (Map.Entry<String, JsonElement> entry : json.getAsJsonObject(table).entrySet()) {
			D definition = parse.apply(entry.getValue().getAsJsonObject());
			SlotMobs.loadModel(model.apply(definition));
			BuiltInRegistries.ENTITY_TYPE.getOptional(Identifier.parse(entry.getKey())).ifPresent(type -> into.put(type, definition));
		}
	}

	/**
	 * Fires a projectile, if it's allowed to go yet. Its damage and how often anyone can fire it are both in its definition, which is what the
	 * release gates checked, so a module asking more often gets null rather than more than a stage allows.
	 */
	public static SlotProjectile shoot(EntityType<?> type, ServerLevel level, Vec3 from, Vec3 direction, Entity owner) {
		ProjectileDefinition definition = PROJECTILES.get(type);
		if (definition == null || flying(level) >= MOST_FLYING || (owner != null && tooSoon(type, definition, owner, level.getGameTime()))) {
			return null;
		}
		Entity created = type.create(level, EntitySpawnReason.TRIGGERED);
		if (!(created instanceof SlotProjectile projectile)) {
			return null;
		}
		projectile.setPos(from);
		projectile.setOwner(owner);
		projectile.launch(direction);
		level.addFreshEntity(projectile);
		return projectile;
	}

	private static boolean tooSoon(EntityType<?> type, ProjectileDefinition definition, Entity owner, long now) {
		String key = owner.getStringUUID() + type.hashCode();
		Long last = LAST_SHOTS.get(key);
		if (last != null && now - last < definition.ticksBetweenShots()) {
			return true;
		}
		if (LAST_SHOTS.size() >= FORGET_SHOTS_AFTER) {
			LAST_SHOTS.clear();
		}
		LAST_SHOTS.put(key, now);
		return false;
	}

	/** Counted at most once a tick, however many shots ask. */
	private static int flying(ServerLevel level) {
		if (countedAt != level.getGameTime()) {
			countedAt = level.getGameTime();
			counted = level.getEntities(EntityTypeTest.forClass(SlotProjectile.class), projectile -> true).size();
		}
		return counted++;
	}
}
