package gm.conduit.panels;

import com.google.gson.Gson;
import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import gm.conduit.pack.Words;
import net.fabricmc.fabric.api.event.lifecycle.v1.ServerLifecycleEvents;
import net.minecraft.server.level.ServerPlayer;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import java.util.stream.Stream;

/**
 * A panel from the current release, as the broker rendered it. The companion draws it from the same text, and the server only
 * needs to know what can be clicked and where each thing sits in the chest it really is, which is what the broker worked out.
 *
 * @param text what the client is sent
 * @param chestRows how many rows the real chest underneath has
 * @param needsNewerCompanion whether it has something an older companion would draw wrongly, so that one gets the plain chest instead
 */
public record PanelDefinition(String name, String text, String title, int chestRows, List<Widget> widgets, Map<String, Widget> byId, Map<Integer, Widget> byChestSlot, boolean needsNewerCompanion) {
	private static final Logger LOGGER = LoggerFactory.getLogger("Conduit");
	private static final Path FOLDER = Path.of("config", "conduit");
	private static final Path FILE = FOLDER.resolve("panels.json");
	private static final Pattern IN_A_LANGUAGE = Pattern.compile("panels\\.([a-z_]+)\\.json");
	private static final Map<String, PanelDefinition> PANELS = new HashMap<>();
	// The same panels in other languages, with everything but what they say the same.
	private static final Map<String, Map<String, PanelDefinition>> TRANSLATED = new HashMap<>();

	/**
	 * @param id what a module calls it, or an empty string for something nothing needs to change
	 * @param chestSlot its first place in the chest, or -1 if it has none
	 * @param size how many places it has there
	 * @param containerSlot for an item slot, which slot of the inventory it shows
	 * @param page the tab it's on, or an empty string for all of them
	 * @param tabs for a row of tabs, their ids and what they say, in order
	 * @param startsHidden whether it isn't there until a module shows it
	 * @param mostRows for a list, how many rows it can ever have
	 * @param paged for a list with too many rows to fit in a chest, which shows them a page at a time there, with its last two places for turning the page
	 */
	public record Widget(String type, String id, int chestSlot, int size, int containerSlot, String page, String text, String tooltip,
			String icon, int maxLength, float value, boolean enabled, List<Tab> tabs, boolean startsHidden, int mostRows, boolean paged) {}

	public record Tab(String id, String text, String icon) {}

	public static void register() {
		ServerLifecycleEvents.SERVER_STARTED.register(server -> reload());
		ServerLifecycleEvents.END_DATA_PACK_RELOAD.register((server, resources, success) -> reload());
	}

	/** One named by a module, in its own feature or as "other_feature/name", in the player's language if there's a translation of it. */
	public static PanelDefinition find(String moduleId, String name, ServerPlayer player) {
		String key = name.contains("/") ? name : moduleId + "/" + name;
		PanelDefinition found = PANELS.get(key);
		if (found == null) {
			throw new IllegalArgumentException("No panel is called " + name + ". It has to be in \"panels\" in feature.json");
		}
		return TRANSLATED.getOrDefault(Words.languageOf(player), Map.of()).getOrDefault(key, found);
	}

	private static void reload() {
		PANELS.clear();
		TRANSLATED.clear();
		if (!Files.exists(FILE)) {
			return;
		}
		readInto(FILE, PANELS);
		try (Stream<Path> files = Files.list(FOLDER)) {
			files.forEach(file -> {
				Matcher language = IN_A_LANGUAGE.matcher(file.getFileName().toString());
				if (language.matches()) {
					readInto(file, TRANSLATED.computeIfAbsent(language.group(1), key -> new HashMap<>()));
				}
			});
		} catch (IOException error) {
			LOGGER.error("Can't look for panels in other languages", error);
		}
	}

	private static void readInto(Path file, Map<String, PanelDefinition> panels) {
		try {
			JsonObject json = new Gson().fromJson(Files.readString(file), JsonObject.class);
			for (Map.Entry<String, JsonElement> entry : json.entrySet()) {
				panels.put(entry.getKey(), parse(entry.getKey(), entry.getValue().getAsJsonObject()));
			}
		} catch (IOException | RuntimeException error) {
			LOGGER.error("Can't read {}", file, error);
		}
	}

	private static PanelDefinition parse(String name, JsonObject json) {
		List<Widget> widgets = new ArrayList<>();
		Map<String, Widget> byId = new HashMap<>();
		Map<Integer, Widget> byChestSlot = new HashMap<>();
		boolean needsNewer = false;
		for (JsonElement element : json.getAsJsonArray("widgets")) {
			JsonObject raw = element.getAsJsonObject();
			List<Tab> tabs = new ArrayList<>();
			if (raw.has("tabs")) {
				raw.getAsJsonArray("tabs").forEach(tab -> tabs.add(new Tab(string(tab.getAsJsonObject(), "id"), string(tab.getAsJsonObject(), "text"), string(tab.getAsJsonObject(), "icon"))));
			}
			Widget widget = new Widget(raw.get("type").getAsString(), string(raw, "id"), number(raw, "chest_slot", -1), number(raw, "chest_size", 0), number(raw, "slot", 0), string(raw, "page"),
					string(raw, "text"), string(raw, "tooltip"), string(raw, "icon"), number(raw, "max_length", 0), raw.has("value") ? raw.get("value").getAsFloat() : 0,
					!raw.has("enabled") || raw.get("enabled").getAsBoolean(), tabs, raw.has("visible") && !raw.get("visible").getAsBoolean(),
					number(raw, "max_rows", number(raw, "chest_size", 0)), raw.has("paged") && raw.get("paged").getAsBoolean());
			needsNewer |= widget.type().equals("filter") || widget.paged() || tabs.stream().anyMatch(tab -> !tab.icon().isEmpty());
			widgets.add(widget);
			if (!widget.id().isEmpty()) {
				byId.put(widget.id(), widget);
			}
			for (int offset = 0; offset < widget.size(); offset++) {
				byChestSlot.put(widget.chestSlot() + offset, widget);
			}
		}
		return new PanelDefinition(name, json.toString(), string(json, "title"), json.get("chest_rows").getAsInt(), widgets, byId, byChestSlot, needsNewer);
	}

	private static String string(JsonObject json, String field) {
		return json.has(field) ? json.get(field).getAsString() : "";
	}

	private static int number(JsonObject json, String field, int otherwise) {
		return json.has(field) ? json.get(field).getAsInt() : otherwise;
	}
}
