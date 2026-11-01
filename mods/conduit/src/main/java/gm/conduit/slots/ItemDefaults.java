package gm.conduit.slots;

import com.google.gson.Gson;
import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import com.mojang.serialization.JsonOps;
import net.fabricmc.fabric.api.event.lifecycle.v1.ServerLifecycleEvents;
import net.minecraft.core.component.DataComponentMap;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.resources.Identifier;
import net.minecraft.resources.RegistryOps;
import net.minecraft.server.MinecraftServer;
import net.minecraft.world.entity.EntityType;
import net.minecraft.world.item.Item;
import net.minecraft.world.level.block.Block;
import net.minecraft.world.level.material.Fluid;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.HashMap;
import java.util.HashSet;
import java.util.Map;
import java.util.Set;

/**
 * What a release says its items are: food, a tool, how far they stack, whether they plant something. A stack
 * takes these when it's created or loaded, so anything already in an inventory catches up the next time it loads.
 */
public final class ItemDefaults {
	private static final Logger LOGGER = LoggerFactory.getLogger("Conduit");
	private static final Path FILE = Path.of("config", "conduit", "item_defaults.json");
	private static final Map<Item, Placement> PLACEMENTS = new HashMap<>();
	private static final Set<Item> TIMED_USE = new HashSet<>();
	private static final Map<Item, Fluid> BUCKETS = new HashMap<>();
	private static final Map<Item, EntityType<?>> VEHICLES = new HashMap<>();

	/** @param on what it can be placed on, or empty for anything solid */
	record Placement(Block block, Set<Block> on) {}

	private ItemDefaults() {}

	public static void register() {
		ServerLifecycleEvents.SERVER_STARTED.register(ItemDefaults::reload);
		ServerLifecycleEvents.END_DATA_PACK_RELOAD.register((server, resources, success) -> reload(server));
	}

	static Placement placement(Item item) {
		return PLACEMENTS.get(item);
	}

	/** What it empties into the world, if it's a bucket of something. */
	static Fluid bucket(Item item) {
		return BUCKETS.get(item);
	}

	/** The vehicle this item puts in the world, if it's one that does. */
	static EntityType<?> vehicle(Item item) {
		return VEHICLES.get(item);
	}

	/** Whether using this runs for a while and then goes to a module, instead of it being eaten. */
	static boolean isTimedUse(Item item) {
		return TIMED_USE.contains(item);
	}

	private static void reload(MinecraftServer server) {
		PLACEMENTS.clear();
		TIMED_USE.clear();
		BUCKETS.clear();
		VEHICLES.clear();
		BuiltInRegistries.ITEM.forEach(item -> {
			if (item instanceof SlotItem slot) {
				slot.setReleaseComponents(null);
			}
		});
		if (!Files.exists(FILE)) {
			return;
		}
		try {
			RegistryOps<JsonElement> ops = server.registryAccess().createSerializationContext(JsonOps.INSTANCE);
			JsonObject json = new Gson().fromJson(Files.readString(FILE), JsonObject.class);
			for (Map.Entry<String, JsonElement> entry : json.entrySet()) {
				// One bad item shouldn't take every item after it down too, and the error fails the release's log scan.
				try {
					Item item = BuiltInRegistries.ITEM.getValue(Identifier.parse(entry.getKey()));
					JsonObject defaults = entry.getValue().getAsJsonObject();
					if (defaults.has("components") && item instanceof SlotItem slot) {
						slot.setReleaseComponents(DataComponentMap.CODEC.parse(ops, defaults.get("components")).getOrThrow());
					}
					if (defaults.has("timed_use")) {
						TIMED_USE.add(item);
					}
					if (defaults.has("bucket_of")) {
						BUCKETS.put(item, BuiltInRegistries.FLUID.getValue(Identifier.parse(defaults.get("bucket_of").getAsString())));
					}
					if (defaults.has("vehicle")) {
						VEHICLES.put(item, BuiltInRegistries.ENTITY_TYPE.getValue(Identifier.parse(defaults.get("vehicle").getAsString())));
					}
					if (defaults.has("places")) {
						PLACEMENTS.put(item, readPlacement(defaults.getAsJsonObject("places")));
					}
				} catch (RuntimeException error) {
					LOGGER.error("Can't read the defaults for {}", entry.getKey(), error);
				}
			}
			LOGGER.info("item defaults loaded for {} items", json.size());
		} catch (IOException | RuntimeException error) {
			LOGGER.error("Can't read {}", FILE, error);
		}
	}

	private static Placement readPlacement(JsonObject json) {
		Set<Block> on = new HashSet<>();
		if (json.has("on")) {
			json.getAsJsonArray("on").forEach(id -> on.add(BuiltInRegistries.BLOCK.getValue(Identifier.parse(id.getAsString()))));
		}
		return new Placement(BuiltInRegistries.BLOCK.getValue(Identifier.parse(json.get("block").getAsString())), on);
	}
}
