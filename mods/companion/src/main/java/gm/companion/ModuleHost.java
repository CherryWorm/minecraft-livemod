package gm.companion;

import gm.companion.api.ClientModule;
import gm.companion.api.ModuleContext;
import net.fabricmc.fabric.api.client.rendering.v1.hud.HudElement;
import net.minecraft.client.DeltaTracker;
import net.minecraft.client.Minecraft;
import net.minecraft.client.gui.GuiGraphicsExtractor;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Properties;
import java.util.function.Consumer;

/**
 * Loads, runs and unloads client modules. Vanilla hooks can't be removed once added, so the host
 * registers one of each and dispatches to its modules. A module that keeps throwing is switched off
 * rather than taking the game down.
 */
public final class ModuleHost {
	private static final Logger LOGGER = LoggerFactory.getLogger("Companion");
	private static final int MAX_FAILURES = 3;

	private final Map<String, LoadedModule> modules = new LinkedHashMap<>();
	private final Map<String, byte[][]> incoming = new HashMap<>();
	private int completedUnloads;
	private int disabledForErrors;

	public boolean isActive(String moduleId) {
		return this.modules.containsKey(moduleId);
	}

	public int completedUnloads() {
		return this.completedUnloads;
	}

	public int disabledForErrors() {
		return this.disabledForErrors;
	}

	void onChunk(ModulePayloads.Chunk chunk) {
		String key = chunk.moduleId() + "#" + chunk.generation();
		byte[][] parts = this.incoming.computeIfAbsent(key, k -> new byte[chunk.total()][]);
		parts[chunk.index()] = chunk.data();
		for (byte[] part : parts) {
			if (part == null) {
				return;
			}
		}
		this.incoming.remove(key);
		ByteArrayOutputStream jar = new ByteArrayOutputStream();
		for (byte[] part : parts) {
			jar.writeBytes(part);
		}
		load(chunk.moduleId(), chunk.generation(), jar.toByteArray());
	}

	private void load(String moduleId, int generation, byte[] jar) {
		unload(moduleId);
		try {
			ModuleClassLoader loader = new ModuleClassLoader(jar, ModuleHost.class.getClassLoader());
			ClientModule module = (ClientModule) loader.loadClass(readEntryClass(loader)).getDeclaredConstructor().newInstance();
			LoadedModule loaded = new LoadedModule(moduleId, generation, module);
			module.enable(loaded);
			this.modules.put(moduleId, loaded);
			LOGGER.info("module {} generation {} enabled", moduleId, generation);
		} catch (Exception | LinkageError error) {
			LOGGER.error("module {} generation {} failed to load", moduleId, generation, error);
		}
	}

	private static String readEntryClass(ModuleClassLoader loader) throws IOException {
		try (InputStream input = loader.getResourceAsStream("module.properties")) {
			if (input == null) {
				throw new IOException("module.properties is missing");
			}
			Properties properties = new Properties();
			properties.load(input);
			return properties.getProperty("entry");
		}
	}

	void unload(String moduleId) {
		LoadedModule loaded = this.modules.remove(moduleId);
		if (loaded == null) {
			return;
		}
		loaded.shutdown();
		this.completedUnloads++;
		LOGGER.info("module {} generation {} unloaded", moduleId, loaded.generation);
	}

	void unloadAll() {
		for (String moduleId : List.copyOf(this.modules.keySet())) {
			unload(moduleId);
		}
		this.incoming.clear();
	}

	void renderHud(GuiGraphicsExtractor graphics, DeltaTracker deltaTracker) {
		dispatch(module -> module.renderHud(graphics, deltaTracker));
	}

	void tick(Minecraft client) {
		dispatch(module -> module.tick(client));
	}

	private void dispatch(Consumer<LoadedModule> call) {
		List<String> broken = new ArrayList<>();
		for (LoadedModule module : this.modules.values()) {
			call.accept(module);
			if (module.failures >= MAX_FAILURES) {
				broken.add(module.moduleId);
			}
		}
		for (String moduleId : broken) {
			LOGGER.warn("module {} disabled after repeated errors", moduleId);
			this.disabledForErrors++;
			unload(moduleId);
		}
	}

	private static final class LoadedModule implements ModuleContext {
		private final String moduleId;
		private final int generation;
		private final List<HudElement> hudElements = new ArrayList<>();
		private final List<Consumer<Minecraft>> ticks = new ArrayList<>();
		private ClientModule module;
		private int failures;

		LoadedModule(String moduleId, int generation, ClientModule module) {
			this.moduleId = moduleId;
			this.generation = generation;
			this.module = module;
		}

		@Override
		public String moduleId() {
			return this.moduleId;
		}

		@Override
		public int generation() {
			return this.generation;
		}

		@Override
		public void onHud(HudElement element) {
			this.hudElements.add(element);
		}

		@Override
		public void onClientTick(Consumer<Minecraft> tick) {
			this.ticks.add(tick);
		}

		void renderHud(GuiGraphicsExtractor graphics, DeltaTracker deltaTracker) {
			for (HudElement element : this.hudElements) {
				guarded(() -> element.extractRenderState(graphics, deltaTracker));
			}
		}

		void tick(Minecraft client) {
			for (Consumer<Minecraft> tick : this.ticks) {
				guarded(() -> tick.accept(client));
			}
		}

		private void guarded(Runnable call) {
			try {
				call.run();
			} catch (Exception | LinkageError error) {
				if (this.failures++ == 0) {
					LOGGER.warn("module {} threw an error", this.moduleId, error);
				}
			}
		}

		void shutdown() {
			if (this.module != null) {
				guarded(this.module::disable);
			}
			// Dropping every reference is what lets the module's class loader be collected.
			this.hudElements.clear();
			this.ticks.clear();
			this.module = null;
		}
	}
}
