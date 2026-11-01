package gm.conduit.panels;

import com.google.gson.Gson;
import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import net.fabricmc.fabric.api.event.lifecycle.v1.ServerLifecycleEvents;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * A panel from the current release, as the broker rendered it. The companion draws it from the same text, and the server only
 * needs to know what can be clicked and where each thing sits in the chest it really is, which is what the broker worked out.
 *
 * @param text what the client is sent
 * @param chestRows how many rows the real chest underneath has
 */
public record PanelDefinition(String name, String text, String title, int chestRows, List<Widget> widgets, Map<String, Widget> byId, Map<Integer, Widget> byChestSlot) {
	private static final Logger LOGGER = LoggerFactory.getLogger("Conduit");
	private static final Path FILE = Path.of("config", "conduit", "panels.json");
	private static final Map<String, PanelDefinition> PANELS = new HashMap<>();

	/**
	 * @param id what a module calls it, or an empty string for something nothing needs to change
	 * @param chestSlot its first place in the chest, or -1 if it has none
	 * @param size how many places it has there
	 * @param containerSlot for an item slot, which slot of the inventory it shows
	 * @param page the tab it's on, or an empty string for all of them
	 * @param tabs for a row of tabs, their ids and what they say, in order
	 */
	public record Widget(String type, String id, int chestSlot, int size, int containerSlot, String page, String text, String tooltip,
			String icon, int maxLength, float value, boolean enabled, List<Tab> tabs) {}

	public record Tab(String id, String text) {}

	public static void register() {
		ServerLifecycleEvents.SERVER_STARTED.register(server -> reload());
		ServerLifecycleEvents.END_DATA_PACK_RELOAD.register((server, resources, success) -> reload());
	}

	/** One named by a module, in its own feature or as "other_feature/name". */
	public static PanelDefinition find(String moduleId, String name) {
		PanelDefinition found = PANELS.get(name.contains("/") ? name : moduleId + "/" + name);
		if (found == null) {
			throw new IllegalArgumentException("No panel is called " + name + ". It has to be in \"panels\" in feature.json");
		}
		return found;
	}

	private static void reload() {
		PANELS.clear();
		if (!Files.exists(FILE)) {
			return;
		}
		try {
			JsonObject json = new Gson().fromJson(Files.readString(FILE), JsonObject.class);
			for (Map.Entry<String, JsonElement> entry : json.entrySet()) {
				PANELS.put(entry.getKey(), parse(entry.getKey(), entry.getValue().getAsJsonObject()));
			}
		} catch (IOException | RuntimeException error) {
			LOGGER.error("Can't read {}", FILE, error);
		}
	}

	private static PanelDefinition parse(String name, JsonObject json) {
		List<Widget> widgets = new ArrayList<>();
		Map<String, Widget> byId = new HashMap<>();
		Map<Integer, Widget> byChestSlot = new HashMap<>();
		for (JsonElement element : json.getAsJsonArray("widgets")) {
			JsonObject raw = element.getAsJsonObject();
			List<Tab> tabs = new ArrayList<>();
			if (raw.has("tabs")) {
				raw.getAsJsonArray("tabs").forEach(tab -> tabs.add(new Tab(tab.getAsJsonObject().get("id").getAsString(), tab.getAsJsonObject().get("text").getAsString())));
			}
			Widget widget = new Widget(raw.get("type").getAsString(), string(raw, "id"), number(raw, "chest_slot", -1), number(raw, "chest_size", 0), number(raw, "slot", 0), string(raw, "page"),
					string(raw, "text"), string(raw, "tooltip"), string(raw, "icon"), number(raw, "max_length", 0), raw.has("value") ? raw.get("value").getAsFloat() : 0,
					!raw.has("enabled") || raw.get("enabled").getAsBoolean(), tabs);
			widgets.add(widget);
			if (!widget.id().isEmpty()) {
				byId.put(widget.id(), widget);
			}
			for (int offset = 0; offset < widget.size(); offset++) {
				byChestSlot.put(widget.chestSlot() + offset, widget);
			}
		}
		return new PanelDefinition(name, json.toString(), string(json, "title"), json.get("chest_rows").getAsInt(), widgets, byId, byChestSlot);
	}

	private static String string(JsonObject json, String field) {
		return json.has(field) ? json.get(field).getAsString() : "";
	}

	private static int number(JsonObject json, String field, int otherwise) {
		return json.has(field) ? json.get(field).getAsInt() : otherwise;
	}
}
