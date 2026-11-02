package gm.companion;

import com.google.gson.Gson;
import com.google.gson.JsonObject;
import com.mojang.blaze3d.platform.InputConstants;
import gm.companion.mixin.KeyMappingAccessor;
import gm.companion.mixin.OptionsAccessor;
import net.minecraft.client.KeyMapping;
import net.minecraft.client.Minecraft;
import net.minecraft.client.Options;
import net.minecraft.resources.Identifier;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * Keys that modules ask for, in the game's controls menu like any other. The game only reads its options as it starts, before there are any modules,
 * and it would lose a key it hasn't been told about, so what a player chose for each is kept here instead, for as long as they have the companion.
 */
final class ModuleKeys {
	private static final Logger LOGGER = LoggerFactory.getLogger("Companion");
	private static final Path SAVED = Path.of("config", "companion", "keys.json");
	private static final KeyMapping.Category HEADING = KeyMapping.Category.register(Identifier.fromNamespaceAndPath("gm", "modules"));

	private final Map<String, String> chosen = new HashMap<>();
	private final List<KeyMapping> active = new ArrayList<>();

	ModuleKeys() {
		try {
			if (Files.exists(SAVED)) {
				new Gson().fromJson(Files.readString(SAVED), JsonObject.class).asMap().forEach((name, key) -> this.chosen.put(name, key.getAsString()));
			}
		} catch (IOException | RuntimeException error) {
			LOGGER.warn("Can't read which keys were chosen", error);
		}
	}

	KeyMapping add(String name, int defaultKey) {
		KeyMapping mapping = new KeyMapping(name, defaultKey, HEADING);
		String kept = this.chosen.get(name);
		if (kept != null) {
			mapping.setKey(InputConstants.getKey(kept));
		}
		Options options = Minecraft.getInstance().options;
		KeyMapping[] more = Arrays.copyOf(options.keyMappings, options.keyMappings.length + 1);
		more[options.keyMappings.length] = mapping;
		((OptionsAccessor) options).companion$setKeyMappings(more);
		KeyMapping.resetMapping();
		this.active.add(mapping);
		return mapping;
	}

	void remove(KeyMapping mapping) {
		Options options = Minecraft.getInstance().options;
		((OptionsAccessor) options).companion$setKeyMappings(Arrays.stream(options.keyMappings).filter(key -> key != mapping).toArray(KeyMapping[]::new));
		KeyMappingAccessor.companion$all().remove(mapping.getName());
		KeyMapping.resetMapping();
		this.active.remove(mapping);
	}

	/** The controls menu tells nobody when a key changes, so this looks every tick, which is only comparing a few strings. */
	void keepWhatWasChosen() {
		boolean changed = false;
		for (KeyMapping mapping : this.active) {
			if (!mapping.saveString().equals(this.chosen.getOrDefault(mapping.getName(), mapping.getDefaultKey().getName()))) {
				this.chosen.put(mapping.getName(), mapping.saveString());
				changed = true;
			}
		}
		if (changed) {
			save();
		}
	}

	private void save() {
		JsonObject json = new JsonObject();
		this.chosen.forEach(json::addProperty);
		try {
			Files.createDirectories(SAVED.getParent());
			Files.writeString(SAVED, json.toString());
		} catch (IOException error) {
			LOGGER.warn("Can't save which keys were chosen", error);
		}
	}
}
