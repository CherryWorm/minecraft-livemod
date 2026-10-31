package gm.conduit.slots;

import com.google.gson.Gson;
import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import de.tomalbrc.bil.core.model.Model;
import gm.conduit.mobs.SlotMobs;
import net.fabricmc.fabric.api.event.lifecycle.v1.ServerLifecycleEvents;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.HashMap;
import java.util.Map;

/** Which model the current release draws each model block with. A block placed before a release keeps its old look until its chunk reloads. */
public final class BlockModels {
	private static final Logger LOGGER = LoggerFactory.getLogger("Conduit");
	private static final Path FILE = Path.of("config", "conduit", "block_models.json");
	private static final Map<String, Model> MODELS = new HashMap<>();

	private BlockModels() {}

	public static void register() {
		// Now rather than when the server starts, because the resource pack is built before then and models go in it.
		reload();
		ServerLifecycleEvents.END_DATA_PACK_RELOAD.register((server, resources, success) -> reload());
	}

	static Model model(String slotId) {
		return MODELS.get(slotId);
	}

	private static void reload() {
		MODELS.clear();
		if (!Files.exists(FILE)) {
			return;
		}
		try {
			JsonObject json = new Gson().fromJson(Files.readString(FILE), JsonObject.class);
			for (Map.Entry<String, JsonElement> entry : json.entrySet()) {
				MODELS.put(entry.getKey(), SlotMobs.loadModel(entry.getValue().getAsString()));
			}
			LOGGER.info("block models bound: {}", MODELS.size());
		} catch (IOException | RuntimeException error) {
			LOGGER.error("Can't read {}", FILE, error);
		}
	}
}
