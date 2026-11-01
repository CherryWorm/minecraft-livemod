package gm.conduit.slots;

import com.google.gson.Gson;
import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import net.fabricmc.fabric.api.event.lifecycle.v1.ServerLifecycleEvents;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.HashMap;
import java.util.Map;

/** How many slots of each kind the current release gives each machine. They're numbered inputs first, then fuel, then outputs. */
public final class MachineInventories {
	private static final Logger LOGGER = LoggerFactory.getLogger("Conduit");
	private static final Path FILE = Path.of("config", "conduit", "machine_inventories.json");
	private static final Map<String, Layout> LAYOUTS = new HashMap<>();
	private static final Layout NONE = new Layout(0, 0, 0, Map.of(), 0);

	/**
	 * @param limits how many fit in a slot, for those that say
	 * @param width how many of its inputs go in a row, for one that's a grid to look at, or 0 if it's not
	 */
	public record Layout(int inputs, int fuel, int outputs, Map<Integer, Integer> limits, int width) {
		public int size() {
			return this.inputs + this.fuel + this.outputs;
		}

		public boolean isOutput(int slot) {
			return slot >= this.inputs + this.fuel;
		}

		/** How many this slot holds at most, or the given number if it doesn't say. */
		int limit(int slot, int otherwise) {
			return this.limits.getOrDefault(slot, otherwise);
		}
	}

	private MachineInventories() {}

	public static void register() {
		ServerLifecycleEvents.SERVER_STARTED.register(server -> reload());
		ServerLifecycleEvents.END_DATA_PACK_RELOAD.register((server, resources, success) -> reload());
	}

	static Layout layout(String slotId) {
		return LAYOUTS.getOrDefault(slotId, NONE);
	}

	private static void reload() {
		LAYOUTS.clear();
		if (!Files.exists(FILE)) {
			return;
		}
		try {
			JsonObject json = new Gson().fromJson(Files.readString(FILE), JsonObject.class);
			for (Map.Entry<String, JsonElement> entry : json.entrySet()) {
				JsonObject layout = entry.getValue().getAsJsonObject();
				Map<Integer, Integer> limits = new HashMap<>();
				if (layout.has("limits")) {
					layout.getAsJsonObject("limits").asMap().forEach((slot, limit) -> limits.put(Integer.parseInt(slot), limit.getAsInt()));
				}
				LAYOUTS.put(entry.getKey(), new Layout(count(layout, "inputs"), count(layout, "fuel"), count(layout, "outputs"), limits, count(layout, "width")));
			}
		} catch (IOException | RuntimeException error) {
			LOGGER.error("Can't read {}", FILE, error);
		}
	}

	private static int count(JsonObject layout, String field) {
		return layout.has(field) ? layout.get(field).getAsInt() : 0;
	}
}
