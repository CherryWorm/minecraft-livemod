package gm.conduit.modules;

import net.fabricmc.fabric.api.event.lifecycle.v1.ServerLifecycleEvents;
import net.minecraft.nbt.CompoundTag;
import net.minecraft.nbt.NbtAccounter;
import net.minecraft.nbt.NbtIo;
import net.minecraft.server.MinecraftServer;
import net.minecraft.world.level.storage.LevelResource;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.util.HashMap;
import java.util.Map;

/**
 * What each module has chosen to keep, in a file for each beside the world, so it's backed up and rolled back with it. Modules hold on to the same
 * tag from when they first ask for it, however many times they're replaced, and change it without saying so, so all of them get written at each save.
 */
final class ModuleStates {
	private static final Logger LOGGER = LoggerFactory.getLogger("Conduit");
	private static final String FOLDER = "conduit_modules";
	private final Map<String, CompoundTag> states = new HashMap<>();
	private Path folder;

	void register() {
		ServerLifecycleEvents.BEFORE_SAVE.register((server, flush, force) -> saveAll());
		ServerLifecycleEvents.SERVER_STOPPING.register(server -> saveAll());
	}

	void start(MinecraftServer server) {
		this.folder = server.getWorldPath(LevelResource.ROOT).resolve(FOLDER);
		this.states.clear();
	}

	CompoundTag of(String moduleId) {
		return this.states.computeIfAbsent(moduleId, this::read);
	}

	private Path file(String moduleId) {
		return this.folder.resolve(moduleId + ".nbt");
	}

	private CompoundTag read(String moduleId) {
		Path file = file(moduleId);
		if (!Files.exists(file)) {
			return new CompoundTag();
		}
		try {
			return NbtIo.readCompressed(file, NbtAccounter.unlimitedHeap());
		} catch (IOException error) {
			// Carrying on with nothing would then overwrite what's there, so it goes aside where someone can get it back.
			LOGGER.error("Can't read {}, which is being kept as .broken", file, error);
			try {
				Files.move(file, file.resolveSibling(moduleId + ".broken"), StandardCopyOption.REPLACE_EXISTING);
			} catch (IOException stillBroken) {
				LOGGER.error("Can't move {}", file, stillBroken);
			}
			return new CompoundTag();
		}
	}

	void save(String moduleId) {
		CompoundTag state = this.states.get(moduleId);
		if (state == null || this.folder == null) {
			return;
		}
		try {
			Files.createDirectories(this.folder);
			Path written = this.folder.resolve(moduleId + ".tmp");
			NbtIo.writeCompressed(state, written);
			Files.move(written, file(moduleId), StandardCopyOption.REPLACE_EXISTING, StandardCopyOption.ATOMIC_MOVE);
		} catch (IOException error) {
			LOGGER.error("Can't save what module {} keeps", moduleId, error);
		}
	}

	private void saveAll() {
		this.states.keySet().forEach(this::save);
	}
}
