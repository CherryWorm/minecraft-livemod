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
import java.util.stream.Stream;

/**
 * Tells the server what the resource pack calls things. Only clients read a pack, so to the server everything from this
 * world was called by its key, and a module writing a stack's name into a message sent players "3 item.gm.i0027". A name
 * that goes out as a translation is still sent as one, so clients go on showing it from their own copy of the pack.
 */
public final class ServerNames {
	private static final Logger LOGGER = LoggerFactory.getLogger("Conduit");
	public static final String ENGLISH = "en_us";
	private static final Path FOLDER = Path.of("live-assets", "assets", "gm", "lang");
	private static final Language GAME = Language.getInstance();
	private static Map<String, Map<String, String>> languages = Map.of();

	private ServerNames() {}

	public static void register() {
		ServerLifecycleEvents.SERVER_STARTED.register(server -> reload());
		// A release writes the pack's files before it reloads, so this always finds the release's own names.
		ServerLifecycleEvents.END_DATA_PACK_RELOAD.register((server, resources, success) -> reload());
	}

	/** What the pack says for a key in one language, going by English if it doesn't say, and otherwise by what it's given. */
	static String in(String language, String key, String otherwise) {
		String found = languages.getOrDefault(language, Map.of()).get(key);
		return found != null ? found : languages.getOrDefault(ENGLISH, Map.of()).getOrDefault(key, otherwise);
	}

	/** The English for a key, or null if the pack has no such key. */
	public static String english(String key) {
		return languages.getOrDefault(ENGLISH, Map.of()).get(key);
	}

	private static void reload() {
		languages = readAll();
		Map<String, String> names = languages.getOrDefault(ENGLISH, Map.of());
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

	private static Map<String, Map<String, String>> readAll() {
		Map<String, Map<String, String>> found = new HashMap<>();
		if (!Files.isDirectory(FOLDER)) {
			return found;
		}
		try (Stream<Path> files = Files.list(FOLDER)) {
			files.filter(file -> file.toString().endsWith(".json")).forEach(file -> found.put(file.getFileName().toString().replace(".json", ""), read(file)));
		} catch (IOException error) {
			LOGGER.error("Can't read {}", FOLDER, error);
		}
		return found;
	}

	private static Map<String, String> read(Path file) {
		Map<String, String> names = new HashMap<>();
		try {
			JsonObject json = new Gson().fromJson(Files.readString(file), JsonObject.class);
			json.entrySet().forEach(entry -> names.put(entry.getKey(), entry.getValue().getAsString()));
		} catch (IOException | RuntimeException error) {
			LOGGER.error("Can't read {}", file, error);
		}
		return names;
	}
}
