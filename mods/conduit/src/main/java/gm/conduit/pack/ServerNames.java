package gm.conduit.pack;

import com.google.gson.Gson;
import com.google.gson.JsonObject;
import net.fabricmc.fabric.api.event.lifecycle.v1.ServerLifecycleEvents;
import net.minecraft.locale.Language;
import net.minecraft.network.chat.FormattedText;
import net.minecraft.util.FormattedCharSequence;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.HashMap;
import java.util.Map;

/**
 * Tells the server what the resource pack calls things. Only clients read a pack, so to the server everything from this
 * world was called by its key, and a module writing a stack's name into a message sent players "3 item.gm.i0027". A name
 * that goes out as a translation is still sent as one, so clients go on showing it from their own copy of the pack.
 */
public final class ServerNames {
	private static final Logger LOGGER = LoggerFactory.getLogger("Conduit");
	private static final Path FILE = Path.of("live-assets", "assets", "gm", "lang", "en_us.json");
	private static final Language GAME = Language.getInstance();

	private ServerNames() {}

	public static void register() {
		ServerLifecycleEvents.SERVER_STARTED.register(server -> reload());
		// A release writes the pack's files before it reloads, so this always finds the release's own names.
		ServerLifecycleEvents.END_DATA_PACK_RELOAD.register((server, resources, success) -> reload());
	}

	private static void reload() {
		Map<String, String> names = read();
		Language.inject(new Language() {
			@Override
			public String getOrDefault(String key, String fallback) {
				String name = names.get(key);
				return name != null ? name : GAME.getOrDefault(key, fallback);
			}

			@Override
			public boolean has(String key) {
				return names.containsKey(key) || GAME.has(key);
			}

			@Override
			public boolean isDefaultRightToLeft() {
				return GAME.isDefaultRightToLeft();
			}

			@Override
			public FormattedCharSequence getVisualOrder(FormattedText text) {
				return GAME.getVisualOrder(text);
			}
		});
	}

	private static Map<String, String> read() {
		Map<String, String> names = new HashMap<>();
		if (!Files.exists(FILE)) {
			return names;
		}
		try {
			JsonObject json = new Gson().fromJson(Files.readString(FILE), JsonObject.class);
			json.entrySet().forEach(entry -> names.put(entry.getKey(), entry.getValue().getAsString()));
		} catch (IOException | RuntimeException error) {
			LOGGER.error("Can't read {}", FILE, error);
		}
		return names;
	}
}
