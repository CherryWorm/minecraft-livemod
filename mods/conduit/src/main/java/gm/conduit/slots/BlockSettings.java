package gm.conduit.slots;

import com.google.gson.Gson;
import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import net.fabricmc.fabric.api.event.lifecycle.v1.ServerLifecycleEvents;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.resources.Identifier;
import net.minecraft.world.level.block.Block;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * What a release says about a block that the game asks about each time, so unlike a family's properties it can change on a live block.
 *
 * @param hardness how long it takes to break, or null for what its family says
 * @param growth how likely a crop is to grow a stage each time it's picked for a random tick
 * @param on what a crop can stand on, or empty for farmland
 * @param connects what a connected block reaches out to, as well as its own kind and machines
 * @param facing how it turns when placed: horizontal, all, or null for not at all
 * @param light how much light a new one gives, or null for what its family says
 * @param redstone whether redstone treats it as something that can give a signal
 * @param comparator whether a comparator can read it
 * @param unbreakable whether nothing in the game can break or move it
 * @param glowing the parts of its model drawn at full brightness
 */
public record BlockSettings(Float hardness, float growth, Set<Block> on, Set<Block> connects, String facing, Integer light,
		boolean redstone, boolean comparator, boolean unbreakable, List<String> glowing) {
	private static final Logger LOGGER = LoggerFactory.getLogger("Conduit");
	private static final Path FILE = Path.of("config", "conduit", "block_settings.json");
	private static final float DEFAULT_GROWTH = 0.2F;
	private static final BlockSettings NONE = new BlockSettings(null, DEFAULT_GROWTH, Set.of(), Set.of(), null, null, false, false, false, List.of());
	/** Replaced whole, because the game asks about this from redstone and explosions at any moment. */
	private static Map<String, BlockSettings> settings = Map.of();

	public static void register() {
		ServerLifecycleEvents.SERVER_STARTED.register(server -> reload());
		ServerLifecycleEvents.END_DATA_PACK_RELOAD.register((server, resources, success) -> reload());
	}

	static BlockSettings of(String slotId) {
		return settings.getOrDefault(slotId, NONE);
	}

	private static void reload() {
		settings = read();
		BuiltInRegistries.BLOCK.forEach(block -> {
			if (block instanceof SlotBlock slot) {
				slot.settingsChanged();
			}
		});
	}

	private static Map<String, BlockSettings> read() {
		Map<String, BlockSettings> found = new HashMap<>();
		if (!Files.exists(FILE)) {
			return found;
		}
		try {
			JsonObject json = new Gson().fromJson(Files.readString(FILE), JsonObject.class);
			for (Map.Entry<String, JsonElement> entry : json.entrySet()) {
				JsonObject raw = entry.getValue().getAsJsonObject();
				List<String> glowing = new ArrayList<>();
				if (raw.has("glowing")) {
					raw.getAsJsonArray("glowing").forEach(part -> glowing.add(part.getAsString()));
				}
				found.put(entry.getKey(), new BlockSettings(
						raw.has("hardness") ? raw.get("hardness").getAsFloat() : null,
						raw.has("growth") ? raw.get("growth").getAsFloat() : DEFAULT_GROWTH,
						blocks(raw, "on"),
						blocks(raw, "connects"),
						raw.has("facing") ? raw.get("facing").getAsString() : null,
						raw.has("light") ? raw.get("light").getAsInt() : null,
						flag(raw, "redstone"),
						flag(raw, "comparator"),
						flag(raw, "unbreakable"),
						glowing));
			}
		} catch (IOException | RuntimeException error) {
			LOGGER.error("Can't read {}", FILE, error);
		}
		return found;
	}

	private static boolean flag(JsonObject raw, String field) {
		return raw.has(field) && raw.get(field).getAsBoolean();
	}

	private static Set<Block> blocks(JsonObject raw, String field) {
		Set<Block> found = new HashSet<>();
		if (raw.has(field)) {
			raw.getAsJsonArray(field).forEach(id -> found.add(BuiltInRegistries.BLOCK.getValue(Identifier.parse(id.getAsString()))));
		}
		return found;
	}
}
