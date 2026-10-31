package gm.conduit.knowledge;

import com.google.gson.Gson;
import com.google.gson.JsonArray;
import com.google.gson.JsonObject;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.util.ArrayList;
import java.util.List;

/**
 * What's been learned, kept beside the world so it's backed up and restored with it. It only ever grows, so
 * a rolled-back release can't take away something a player earned. Each key is a player's id, or {@link #SHARED}
 * when the world's plan shares knowledge between everyone.
 */
final class KnowledgeLedger {
	static final String SHARED = "shared";
	private static final Logger LOGGER = LoggerFactory.getLogger("Conduit");

	private final Path path;
	private final JsonObject known;
	private final JsonObject found;
	private final JsonObject fragments;

	KnowledgeLedger(Path path) {
		this.path = path;
		JsonObject root = new JsonObject();
		try {
			if (Files.exists(path)) {
				root = new Gson().fromJson(Files.readString(path), JsonObject.class);
			}
		} catch (IOException | RuntimeException error) {
			// Carrying on with an empty ledger would then overwrite what players earned, so stop here instead.
			throw new IllegalStateException("Can't read " + path, error);
		}
		this.known = section(root, "known");
		this.found = section(root, "found");
		this.fragments = section(root, "fragments");
	}

	private static JsonObject section(JsonObject root, String name) {
		return root.has(name) ? root.getAsJsonObject(name) : new JsonObject();
	}

	boolean knows(String key, String entry) {
		return contains(this.known, key, entry);
	}

	/** Returns true if this is new. */
	boolean learn(String key, String entry) {
		return add(this.known, key, entry);
	}

	/** Returns true if this is the first time. */
	boolean markFound(String key, String what) {
		return add(this.found, key, what);
	}

	List<String> found(String key) {
		List<String> list = new ArrayList<>();
		if (this.found.has(key)) {
			this.found.getAsJsonArray(key).forEach(item -> list.add(item.getAsString()));
		}
		return list;
	}

	int addFragment(String key, String entry) {
		JsonObject counts = this.fragments.has(key) ? this.fragments.getAsJsonObject(key) : new JsonObject();
		int have = (counts.has(entry) ? counts.get(entry).getAsInt() : 0) + 1;
		counts.addProperty(entry, have);
		this.fragments.add(key, counts);
		save();
		return have;
	}

	private static boolean contains(JsonObject section, String key, String value) {
		if (!section.has(key)) {
			return false;
		}
		for (var item : section.getAsJsonArray(key)) {
			if (item.getAsString().equals(value)) {
				return true;
			}
		}
		return false;
	}

	private boolean add(JsonObject section, String key, String value) {
		if (contains(section, key, value)) {
			return false;
		}
		JsonArray list = section.has(key) ? section.getAsJsonArray(key) : new JsonArray();
		list.add(value);
		section.add(key, list);
		save();
		return true;
	}

	private void save() {
		JsonObject root = new JsonObject();
		root.add("known", this.known);
		root.add("found", this.found);
		root.add("fragments", this.fragments);
		Path temporary = this.path.resolveSibling(this.path.getFileName() + ".tmp");
		try {
			Files.writeString(temporary, new Gson().toJson(root));
			Files.move(temporary, this.path, StandardCopyOption.ATOMIC_MOVE, StandardCopyOption.REPLACE_EXISTING);
		} catch (IOException error) {
			LOGGER.error("Can't save {}", this.path, error);
		}
	}
}
