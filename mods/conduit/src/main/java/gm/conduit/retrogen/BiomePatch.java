package gm.conduit.retrogen;

import com.google.gson.Gson;
import com.google.gson.JsonParseException;
import com.terraformersmc.biolith.api.biome.BiomePlacement;
import net.minecraft.core.registries.Registries;
import net.minecraft.resources.Identifier;
import net.minecraft.resources.ResourceKey;
import net.minecraft.world.level.biome.Biome;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;

/**
 * A new biome. Land nobody has generated yet gets it through Biolith, in the normal way. A biome marked as a
 * sibling also spreads into land that already exists, because the broker has checked it has the same
 * temperature, rainfall and mob spawns as the biome it replaces: anything else could freeze water or break a
 * mob farm in a place someone has built.
 *
 * @param proportion how much of the old biome becomes this one, from 0 to 1
 */
public record BiomePatch(String id, ResourceKey<Biome> from, ResourceKey<Biome> to, double proportion, boolean sibling) {
	private static final Logger LOGGER = LoggerFactory.getLogger("Conduit");
	private static final Path FILE = Path.of("config", "conduit", "biome_patches.json");

	private record Definition(String id, String from, String to, double proportion, boolean sibling) {}

	static List<BiomePatch> load() {
		if (!Files.exists(FILE)) {
			return List.of();
		}
		try {
			Definition[] definitions = new Gson().fromJson(Files.readString(FILE), Definition[].class);
			return List.of(definitions).stream().map(BiomePatch::resolve).toList();
		} catch (IOException | JsonParseException error) {
			throw new IllegalStateException("Can't read " + FILE, error);
		}
	}

	private static BiomePatch resolve(Definition definition) {
		return new BiomePatch(definition.id(), key(definition.from()), key(definition.to()), definition.proportion(), definition.sibling());
	}

	private static ResourceKey<Biome> key(String id) {
		return ResourceKey.create(Registries.BIOME, Identifier.parse(id));
	}

	/** Has to run during mod init, because Biolith reads its placements when the world loads. */
	public static void registerPlacements() {
		for (BiomePatch patch : load()) {
			BiomePlacement.replaceOverworld(patch.from(), patch.to(), patch.proportion());
			LOGGER.info("biome {} placed over {} at {}", patch.to().identifier(), patch.from().identifier(), patch.proportion());
		}
	}
}
