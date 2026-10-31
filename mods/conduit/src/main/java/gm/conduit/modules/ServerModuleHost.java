package gm.conduit.modules;

import com.google.gson.Gson;
import com.google.gson.JsonObject;
import gm.conduit.api.BlockBehavior;
import gm.conduit.api.ItemBehavior;
import gm.conduit.api.MachineBehavior;
import gm.conduit.api.ServerModule;
import gm.conduit.api.ServerModuleContext;
import net.minecraft.server.MinecraftServer;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.io.IOException;
import java.io.InputStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Properties;
import java.util.function.Consumer;
import java.util.function.Supplier;
import java.util.stream.Stream;

/**
 * Loads, swaps and unloads server modules while the game runs. Slots stay registered whatever happens
 * here, so removing a module leaves its blocks in the world as inert blanks, with nothing lost. A module
 * that keeps throwing is switched off rather than taking the server down.
 */
public final class ServerModuleHost {
	private static final Logger LOGGER = LoggerFactory.getLogger("Conduit");
	private static final ServerModuleHost INSTANCE = new ServerModuleHost();
	private static final Path DIRECTORY = Path.of("modules", "server");
	private static final Path BINDINGS = Path.of("config", "conduit", "bindings.json");
	private static final int MAX_FAILURES = 5;

	private final Map<String, LoadedModule> modules = new LinkedHashMap<>();
	private final Map<String, LoadedModule> ownerBySlot = new HashMap<>();
	private final Map<String, BlockBehavior> blocks = new HashMap<>();
	private final Map<String, ItemBehavior> items = new HashMap<>();
	private final Map<String, MachineBehavior> machines = new HashMap<>();
	private Map<String, String> slotsByName = Map.of();
	private MinecraftServer server;

	private ServerModuleHost() {}

	public static ServerModuleHost instance() {
		return INSTANCE;
	}

	public BlockBehavior blockBehavior(String slotId) {
		return this.blocks.get(slotId);
	}

	public ItemBehavior itemBehavior(String slotId) {
		return this.items.get(slotId);
	}

	public MachineBehavior machineBehavior(String slotId) {
		return this.machines.get(slotId);
	}

	public void start(MinecraftServer server) {
		this.server = server;
		reloadAll();
	}

	public void tick(MinecraftServer server) {
		for (LoadedModule module : List.copyOf(this.modules.values())) {
			for (Consumer<MinecraftServer> tick : module.ticks) {
				guard(module, () -> tick.accept(server));
			}
		}
	}

	/** Makes the running modules match the folder: new jars load, changed jars swap, missing jars unload. */
	public int reloadAll() {
		readBindings();
		Map<String, byte[]> found = new HashMap<>();
		if (Files.isDirectory(DIRECTORY)) {
			try (Stream<Path> files = Files.list(DIRECTORY)) {
				for (Path file : files.filter(path -> path.toString().endsWith(".jar")).toList()) {
					String name = file.getFileName().toString();
					found.put(name.substring(0, name.length() - 4), Files.readAllBytes(file));
				}
			} catch (IOException error) {
				LOGGER.error("Can't read {}", DIRECTORY, error);
				return 0;
			}
		}
		for (String moduleId : List.copyOf(this.modules.keySet())) {
			if (!found.containsKey(moduleId)) {
				unload(moduleId);
			}
		}
		int changed = 0;
		for (Map.Entry<String, byte[]> entry : found.entrySet()) {
			LoadedModule existing = this.modules.get(entry.getKey());
			if (existing == null || !java.util.Arrays.equals(existing.jar, entry.getValue())) {
				load(entry.getKey(), entry.getValue());
				changed++;
			}
		}
		return changed;
	}

	private void readBindings() {
		if (!Files.exists(BINDINGS)) {
			this.slotsByName = Map.of();
			return;
		}
		try {
			JsonObject json = new Gson().fromJson(Files.readString(BINDINGS), JsonObject.class);
			Map<String, String> map = new HashMap<>();
			json.entrySet().forEach(entry -> map.put(entry.getKey(), entry.getValue().getAsString()));
			this.slotsByName = map;
		} catch (IOException | RuntimeException error) {
			LOGGER.error("Can't read {}", BINDINGS, error);
		}
	}

	private void load(String moduleId, byte[] jar) {
		unload(moduleId);
		try {
			ModuleClassLoader loader = new ModuleClassLoader(jar, ServerModuleHost.class.getClassLoader());
			Properties properties = new Properties();
			try (InputStream input = loader.getResourceAsStream("module.properties")) {
				if (input == null) {
					throw new IOException("module.properties is missing");
				}
				properties.load(input);
			}
			ServerModule module = (ServerModule) loader.loadClass(properties.getProperty("entry"))
					.getDeclaredConstructor().newInstance();
			LoadedModule loaded = new LoadedModule(moduleId, jar, module);
			this.modules.put(moduleId, loaded);
			module.enable(loaded);
			LOGGER.info("server module {} enabled", moduleId);
		} catch (Exception | LinkageError error) {
			LOGGER.error("server module {} failed to load", moduleId, error);
			unload(moduleId);
		}
	}

	public void unload(String moduleId) {
		LoadedModule module = this.modules.remove(moduleId);
		if (module == null) {
			return;
		}
		guard(module, module.module::disable);
		this.ownerBySlot.entrySet().removeIf(entry -> {
			if (entry.getValue() == module) {
				this.blocks.remove(entry.getKey());
				this.items.remove(entry.getKey());
				this.machines.remove(entry.getKey());
				return true;
			}
			return false;
		});
		LOGGER.info("server module {} unloaded", moduleId);
	}

	public List<String> loadedModules() {
		return List.copyOf(this.modules.keySet());
	}

	public void guarded(String slotId, Runnable call) {
		LoadedModule owner = this.ownerBySlot.get(slotId);
		if (owner != null) {
			guard(owner, call);
		}
	}

	public <T> T guarded(String slotId, T fallback, Supplier<T> call) {
		LoadedModule owner = this.ownerBySlot.get(slotId);
		if (owner == null) {
			return fallback;
		}
		try {
			return call.get();
		} catch (Exception | LinkageError error) {
			fail(owner, error);
			return fallback;
		}
	}

	private void guard(LoadedModule module, Runnable call) {
		try {
			call.run();
		} catch (Exception | LinkageError error) {
			fail(module, error);
		}
	}

	private void fail(LoadedModule module, Throwable error) {
		if (module.failures++ == 0) {
			LOGGER.warn("server module {} threw an error", module.moduleId, error);
		}
		if (module.failures >= MAX_FAILURES && this.modules.get(module.moduleId) == module) {
			LOGGER.warn("server module {} disabled after repeated errors", module.moduleId);
			unload(module.moduleId);
		}
	}

	private final class LoadedModule implements ServerModuleContext {
		private final String moduleId;
		private final byte[] jar;
		private final ServerModule module;
		private final List<Consumer<MinecraftServer>> ticks = new ArrayList<>();
		private int failures;

		LoadedModule(String moduleId, byte[] jar, ServerModule module) {
			this.moduleId = moduleId;
			this.jar = jar;
			this.module = module;
		}

		@Override
		public String moduleId() {
			return this.moduleId;
		}

		@Override
		public MinecraftServer server() {
			return ServerModuleHost.this.server;
		}

		private String slot(String name) {
			String slot = ServerModuleHost.this.slotsByName.get(this.moduleId + "/" + name);
			if (slot == null) {
				throw new IllegalArgumentException("Module " + this.moduleId + " has no slot called " + name);
			}
			ServerModuleHost.this.ownerBySlot.put(slot, this);
			return slot;
		}

		@Override
		public void bindBlock(String name, BlockBehavior behavior) {
			ServerModuleHost.this.blocks.put(slot(name), behavior);
		}

		@Override
		public void bindItem(String name, ItemBehavior behavior) {
			ServerModuleHost.this.items.put(slot(name), behavior);
		}

		@Override
		public void bindMachine(String name, MachineBehavior behavior) {
			ServerModuleHost.this.machines.put(slot(name), behavior);
		}

		@Override
		public void onServerTick(Consumer<MinecraftServer> tick) {
			this.ticks.add(tick);
		}
	}
}
