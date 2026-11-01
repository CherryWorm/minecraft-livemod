package gm.conduit.modules;

import com.google.gson.Gson;
import com.google.gson.JsonObject;
import gm.conduit.api.BlockBehavior;
import gm.conduit.api.ItemBehavior;
import gm.conduit.api.MachineAttempt;
import gm.conduit.api.MachineBehavior;
import gm.conduit.api.MobBehavior;
import gm.conduit.api.ServerModule;
import gm.conduit.api.ServerModuleContext;
import gm.conduit.api.WorldEvents;
import gm.conduit.api.MenuBehavior;
import gm.conduit.knowledge.Codex;
import gm.conduit.knowledge.Knowledge;
import gm.conduit.provenance.Provenance;
import gm.conduit.slots.ButtonMenu;
import net.fabricmc.fabric.api.entity.event.v1.ServerLivingEntityEvents;
import net.fabricmc.fabric.api.event.player.PlayerBlockBreakEvents;
import net.fabricmc.fabric.api.networking.v1.ServerPlayConnectionEvents;
import net.minecraft.core.BlockPos;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.nbt.CompoundTag;
import net.minecraft.network.chat.Component;
import net.minecraft.resources.Identifier;
import net.minecraft.server.MinecraftServer;
import net.minecraft.server.level.ServerLevel;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.server.network.Filterable;
import net.minecraft.sounds.SoundEvent;
import net.minecraft.sounds.SoundSource;
import net.minecraft.world.SimpleMenuProvider;
import net.minecraft.world.entity.Entity;
import net.minecraft.world.entity.EntityType;
import net.minecraft.world.entity.player.Player;
import net.minecraft.world.item.Item;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.level.Level;
import net.minecraft.world.level.block.Block;
import net.minecraft.world.level.block.state.BlockState;
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
	private final Map<String, MobBehavior> mobs = new HashMap<>();
	private final List<ServerPlayer> joining = new ArrayList<>();
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

	public MobBehavior mobBehavior(String slotId) {
		return this.mobs.get(slotId);
	}

	public static void register() {
		PlayerBlockBreakEvents.AFTER.register((level, player, pos, state, blockEntity) -> {
			if (level instanceof ServerLevel serverLevel && player instanceof ServerPlayer serverPlayer) {
				INSTANCE.fire(events -> events.blockBroken(serverPlayer, serverLevel, pos, state, blockEntity));
			}
		});
		ServerLivingEntityEvents.AFTER_DEATH.register((entity, source) -> INSTANCE.fire(events -> events.mobKilled(entity, source)));
		// Fabric says so before the player is in the world or the player list, so a module would be handed someone half arrived.
		ServerPlayConnectionEvents.JOIN.register((handler, sender, server) -> INSTANCE.joining.add(handler.player));
	}

	public void start(MinecraftServer server) {
		this.server = server;
		reloadAll();
	}

	public void tick(MinecraftServer server) {
		for (ServerPlayer player : List.copyOf(this.joining)) {
			if (!player.hasDisconnected()) {
				fire(events -> events.playerJoined(player));
			}
		}
		this.joining.clear();
		for (LoadedModule module : List.copyOf(this.modules.values())) {
			for (Consumer<MinecraftServer> tick : module.ticks) {
				guard(module, () -> tick.accept(server));
			}
		}
	}

	/** Tells every module that's listening. One that throws only loses its own turn. */
	public void fire(Consumer<WorldEvents> event) {
		for (LoadedModule module : List.copyOf(this.modules.values())) {
			for (WorldEvents events : module.events) {
				guard(module, () -> event.accept(events));
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
		module.closeMenus();
		guard(module, module.module::disable);
		this.ownerBySlot.entrySet().removeIf(entry -> {
			if (entry.getValue() == module) {
				this.blocks.remove(entry.getKey());
				this.items.remove(entry.getKey());
				this.machines.remove(entry.getKey());
				this.mobs.remove(entry.getKey());
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
		private final List<WorldEvents> events = new ArrayList<>();
		private final List<ButtonMenu> menus = new ArrayList<>();
		private final Map<String, List<Consumer<CompoundTag>>> subscriptions = new HashMap<>();
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
		public void bindMob(String name, MobBehavior behavior) {
			ServerModuleHost.this.mobs.put(slot(name), behavior);
		}

		@Override
		public void onServerTick(Consumer<MinecraftServer> tick) {
			this.ticks.add(tick);
		}

		@Override
		public void listen(WorldEvents events) {
			this.events.add(events);
		}

		private Identifier idOf(String name) {
			String key = name.contains("/") ? name : this.moduleId + "/" + name;
			String slot = ServerModuleHost.this.slotsByName.get(key);
			if (slot == null) {
				throw new IllegalArgumentException("Nothing is called " + key);
			}
			return Identifier.fromNamespaceAndPath("gm", slot);
		}

		@Override
		public Block block(String name) {
			return BuiltInRegistries.BLOCK.getValue(idOf(name));
		}

		@Override
		public Item item(String name) {
			return BuiltInRegistries.ITEM.getValue(idOf(name));
		}

		@Override
		public EntityType<?> mob(String name) {
			return BuiltInRegistries.ENTITY_TYPE.getValue(idOf(name));
		}

		@Override
		public SoundEvent sound(String name) {
			String key = "sound:" + (name.contains("/") ? name : this.moduleId + "/" + name);
			String sound = ServerModuleHost.this.slotsByName.get(key);
			if (sound == null) {
				throw new IllegalArgumentException("No sound is called " + name + ". It has to be listed in \"sounds\" in feature.json");
			}
			return SoundEvent.createVariableRangeEvent(Identifier.fromNamespaceAndPath("gm", sound));
		}

		@Override
		public void playSound(String name, Level level, BlockPos pos, float volume, float pitch) {
			level.playSound(null, pos, sound(name), SoundSource.NEUTRAL, volume, pitch);
		}

		@Override
		public MachineAttempt attemptRecipe(Player player, String machine, List<ItemStack> inputs) {
			return Knowledge.instance().attempt(player, machine.contains("/") ? machine : this.moduleId + "/" + machine, inputs);
		}

		@Override
		public void openMenu(ServerPlayer player, Component title, int rows, MenuBehavior behavior) {
			if (rows < 1 || rows > 6) {
				throw new IllegalArgumentException("A menu has from 1 to 6 rows, not " + rows);
			}
			player.openMenu(new SimpleMenuProvider((id, inventory, who) -> {
				ButtonMenu menu = new ButtonMenu(id, inventory, player, rows, behavior, action -> guard(this, action));
				this.menus.removeIf(open -> open.player().containerMenu != open);
				this.menus.add(menu);
				return menu;
			}, title));
		}

		void closeMenus() {
			for (ButtonMenu menu : List.copyOf(this.menus)) {
				if (menu.player().containerMenu == menu) {
					menu.close();
				}
			}
		}

		@Override
		public void examine(ServerPlayer player, BlockState state) {
			Knowledge.instance().examineFor(player, BuiltInRegistries.BLOCK.getKey(state.getBlock()).toString());
		}

		@Override
		public void examine(ServerPlayer player, Entity target) {
			Knowledge.instance().examineFor(player, BuiltInRegistries.ENTITY_TYPE.getKey(target.getType()).toString());
		}

		@Override
		public boolean isNatural(Level level, BlockPos pos) {
			return !Provenance.isTouched(level.getChunk(pos), pos);
		}

		@Override
		public void publish(String topic, CompoundTag message) {
			String full = this.moduleId + "/" + topic;
			for (LoadedModule module : List.copyOf(ServerModuleHost.this.modules.values())) {
				for (Consumer<CompoundTag> listener : module.subscriptions.getOrDefault(full, List.of())) {
					guard(module, () -> listener.accept(message.copy()));
				}
			}
		}

		@Override
		public void subscribe(String topic, Consumer<CompoundTag> listener) {
			this.subscriptions.computeIfAbsent(topic, key -> new ArrayList<>()).add(listener);
		}

		@Override
		public void openBook(ServerPlayer player, String title, List<Component> pages) {
			Codex.showBook(player, title, pages.stream().map(Filterable::passThrough).toList());
		}

		@Override
		public boolean knows(Player player, String knowledge) {
			return Knowledge.instance().knows(player, this.moduleId + "/" + knowledge);
		}

		@Override
		public void teach(ServerPlayer player, String knowledge) {
			Knowledge.instance().learn(player, this.moduleId + "/" + knowledge);
		}
	}
}
