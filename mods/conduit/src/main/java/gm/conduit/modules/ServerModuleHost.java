package gm.conduit.modules;

import com.google.gson.Gson;
import com.google.gson.JsonObject;
import gm.conduit.api.BlockBehavior;
import gm.conduit.api.Beam;
import gm.conduit.api.EffectBehavior;
import gm.conduit.api.ItemBehavior;
import gm.conduit.api.MachineAttempt;
import gm.conduit.api.MachineBehavior;
import gm.conduit.api.MobBehavior;
import gm.conduit.api.PlayerKey;
import gm.conduit.api.ProjectileBehavior;
import gm.conduit.api.PropBehavior;
import gm.conduit.api.VehicleBehavior;
import gm.conduit.api.ServerModule;
import gm.conduit.api.ServerModuleContext;
import gm.conduit.api.WorldEvents;
import gm.conduit.api.MenuBehavior;
import gm.conduit.api.PanelBehavior;
import gm.conduit.entities.Beams;
import gm.conduit.entities.SlotEntities;
import gm.conduit.entities.SlotProjectile;
import gm.conduit.entities.SlotProp;
import gm.conduit.entities.SlotVehicle;
import gm.conduit.pack.ServerNames;
import gm.conduit.pack.Words;
import gm.conduit.panels.PanelDefinition;
import gm.conduit.panels.PanelMenu;
import gm.conduit.dimensions.Dimensions;
import gm.conduit.knowledge.Codex;
import gm.conduit.knowledge.Knowledge;
import gm.conduit.provenance.Provenance;
import gm.conduit.slots.ButtonMenu;
import gm.conduit.slots.ItemBars;
import gm.conduit.slots.SlotBlock;
import net.fabricmc.fabric.api.entity.event.v1.ServerLivingEntityEvents;
import net.fabricmc.fabric.api.event.lifecycle.v1.ServerChunkEvents;
import net.fabricmc.fabric.api.event.player.PlayerBlockBreakEvents;
import net.fabricmc.fabric.api.networking.v1.ServerPlayConnectionEvents;
import net.minecraft.core.BlockPos;
import net.minecraft.core.Holder;
import net.minecraft.core.Direction;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.nbt.CompoundTag;
import net.minecraft.network.chat.Component;
import net.minecraft.network.chat.MutableComponent;
import net.minecraft.resources.Identifier;
import net.minecraft.server.MinecraftServer;
import net.minecraft.server.level.ServerLevel;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.server.network.Filterable;
import net.minecraft.sounds.SoundEvent;
import net.minecraft.sounds.SoundSource;
import net.minecraft.tags.DamageTypeTags;
import net.minecraft.world.Container;
import net.minecraft.world.damagesource.DamageSource;
import net.minecraft.world.effect.MobEffect;
import net.minecraft.world.SimpleMenuProvider;
import net.minecraft.world.entity.Entity;
import net.minecraft.world.entity.EntitySpawnReason;
import net.minecraft.world.entity.EntityType;
import net.minecraft.world.entity.LivingEntity;
import net.minecraft.world.entity.player.Input;
import net.minecraft.world.entity.player.Player;
import net.minecraft.world.item.Item;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.level.Level;
import net.minecraft.world.level.block.Block;
import net.minecraft.world.level.block.state.BlockState;
import net.minecraft.world.level.material.Fluid;
import net.minecraft.world.phys.Vec3;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.ArrayList;
import java.util.EnumMap;
import java.util.HashMap;
import java.util.HexFormat;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Properties;
import java.util.UUID;
import java.util.function.Consumer;
import java.util.function.Predicate;
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
	private static final int TEXT_ID_LENGTH = 16;
	private static final float LEFT_ON = 1.0F;
	/** What the game itself wants for sprinting by double tapping. */
	private static final int DOUBLE_TAP_TICKS = 7;

	private final Map<String, LoadedModule> modules = new LinkedHashMap<>();
	private final Map<String, LoadedModule> ownerBySlot = new HashMap<>();
	private final Map<String, BlockBehavior> blocks = new HashMap<>();
	private final Map<String, ItemBehavior> items = new HashMap<>();
	private final Map<String, MachineBehavior> machines = new HashMap<>();
	private final Map<String, MobBehavior> mobs = new HashMap<>();
	private final Map<String, EffectBehavior> effects = new HashMap<>();
	private final Map<String, ProjectileBehavior> projectiles = new HashMap<>();
	private final Map<String, VehicleBehavior> vehicles = new HashMap<>();
	private final Map<String, PropBehavior> props = new HashMap<>();
	private final List<ServerPlayer> joining = new ArrayList<>();
	private Map<String, String> slotsByName = Map.of();
	private MinecraftServer server;
	private boolean askingAboutHit;
	private final Map<UUID, Map<PlayerKey, Integer>> lastPresses = new HashMap<>();
	private final ModuleStates states = new ModuleStates();

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

	public EffectBehavior effectBehavior(String slotId) {
		return this.effects.get(slotId);
	}

	public ProjectileBehavior projectileBehavior(String slotId) {
		return this.projectiles.get(slotId);
	}

	public VehicleBehavior vehicleBehavior(String slotId) {
		return this.vehicles.get(slotId);
	}

	public PropBehavior propBehavior(String slotId) {
		return this.props.get(slotId);
	}

	public static void register() {
		PlayerBlockBreakEvents.BEFORE.register((level, player, pos, state, blockEntity) -> {
			if (!(level instanceof ServerLevel serverLevel) || !(player instanceof ServerPlayer serverPlayer)) {
				return true;
			}
			return INSTANCE.mayBreak(serverPlayer, serverLevel, pos, state);
		});
		PlayerBlockBreakEvents.AFTER.register((level, player, pos, state, blockEntity) -> {
			if (level instanceof ServerLevel serverLevel && player instanceof ServerPlayer serverPlayer) {
				INSTANCE.fire(events -> events.blockBroken(serverPlayer, serverLevel, pos, state, blockEntity));
			}
		});
		ServerLivingEntityEvents.ALLOW_DEATH.register((entity, source, amount) -> {
			if (source.is(DamageTypeTags.BYPASSES_INVULNERABILITY) || INSTANCE.allAgree(events -> !events.survives(entity, source, amount))) {
				return true;
			}
			// Anything still at no health is taken for dead on its next tick, so a module has to leave it something.
			if (entity.getHealth() <= 0) {
				entity.setHealth(LEFT_ON);
			}
			return false;
		});
		ServerLivingEntityEvents.AFTER_DEATH.register((entity, source) -> INSTANCE.fire(events -> events.mobKilled(entity, source)));
		ServerChunkEvents.CHUNK_LOAD.register((level, chunk, isNew) -> INSTANCE.fire(events -> events.chunkLoaded(level, chunk, isNew)));
		ServerChunkEvents.CHUNK_UNLOAD.register((level, chunk) -> INSTANCE.fire(events -> events.chunkUnloaded(level, chunk)));
		ServerPlayConnectionEvents.DISCONNECT.register((handler, server) -> INSTANCE.lastPresses.remove(handler.player.getUUID()));
		INSTANCE.states.register();
		// Fabric says so before the player is in the world or the player list, so a module would be handed someone half arrived.
		ServerPlayConnectionEvents.JOIN.register((handler, sender, server) -> INSTANCE.joining.add(handler.player));
	}

	public void start(MinecraftServer server) {
		this.server = server;
		this.states.start(server);
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

	private boolean mayBreak(ServerPlayer player, ServerLevel level, BlockPos pos, BlockState state) {
		if (state.getBlock() instanceof SlotBlock block) {
			BlockBehavior behavior = this.blocks.get(block.slotId());
			if (behavior != null && !guarded(block.slotId(), true, () -> behavior.canBreak(state, level, pos, player))) {
				return false;
			}
		}
		return allAgree(events -> events.canBreak(player, level, pos, state));
	}

	/** Asks every module that's listening, until one says no. One that throws doesn't get a say. */
	private boolean allAgree(Predicate<WorldEvents> question) {
		for (LoadedModule module : List.copyOf(this.modules.values())) {
			for (WorldEvents events : module.events) {
				boolean[] agrees = {true};
				guard(module, () -> agrees[0] = question.test(events));
				if (!agrees[0]) {
					return false;
				}
			}
		}
		return true;
	}

	/** How much a hit really does, once every module has had its say. A module hurting something from in here doesn't ask again, or it would never finish. */
	public float damage(LivingEntity target, DamageSource source, float amount) {
		if (this.askingAboutHit) {
			return amount;
		}
		this.askingAboutHit = true;
		float[] left = {amount};
		fire(events -> {
			float said = events.damage(target, source, left[0]);
			left[0] = Float.isNaN(said) ? left[0] : said;
		});
		this.askingAboutHit = false;
		return left[0];
	}

	/** How hard a hit really pushes, in the same way. */
	public double knockback(LivingEntity target, DamageSource source, double power) {
		if (this.askingAboutHit) {
			return power;
		}
		this.askingAboutHit = true;
		double[] left = {power};
		fire(events -> {
			double said = events.knockback(target, source, left[0]);
			left[0] = Double.isNaN(said) ? left[0] : said;
		});
		this.askingAboutHit = false;
		return left[0];
	}

	/** What a client now says it's holding, against what it said before. */
	public void keysChanged(ServerPlayer player, Input before, Input after) {
		for (PlayerKey key : PlayerKey.values()) {
			boolean was = key.isHeldIn(before);
			boolean is = key.isHeldIn(after);
			if (is && !was) {
				fire(events -> events.keyPressed(player, key));
				int now = this.server.getTickCount();
				Map<PlayerKey, Integer> presses = this.lastPresses.computeIfAbsent(player.getUUID(), id -> new EnumMap<>(PlayerKey.class));
				Integer last = presses.get(key);
				if (last != null && now - last <= DOUBLE_TAP_TICKS) {
					presses.remove(key);
					fire(events -> events.keyDoubleTapped(player, key));
				} else {
					presses.put(key, now);
				}
			} else if (was && !is) {
				fire(events -> events.keyReleased(player, key));
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
		module.removeBeams();
		guard(module, module.module::disable);
		this.states.save(moduleId);
		this.ownerBySlot.entrySet().removeIf(entry -> {
			if (entry.getValue() == module) {
				this.blocks.remove(entry.getKey());
				this.items.remove(entry.getKey());
				this.machines.remove(entry.getKey());
				this.mobs.remove(entry.getKey());
				this.effects.remove(entry.getKey());
				this.projectiles.remove(entry.getKey());
				this.vehicles.remove(entry.getKey());
				this.props.remove(entry.getKey());
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
		private static final double PANEL_REACH = 8.0;

		private final String moduleId;
		private final byte[] jar;
		private final ServerModule module;
		private final List<Consumer<MinecraftServer>> ticks = new ArrayList<>();
		private final List<WorldEvents> events = new ArrayList<>();
		private final List<ButtonMenu> menus = new ArrayList<>();
		private final List<PanelMenu> panels = new ArrayList<>();
		private final List<Beam> beams = new ArrayList<>();
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
		public void bindEffect(String name, EffectBehavior behavior) {
			String slot = effectSlot(name);
			if (name.contains("/")) {
				throw new IllegalArgumentException("A module can only bind its own effects, not " + name);
			}
			ServerModuleHost.this.ownerBySlot.put(slot, this);
			ServerModuleHost.this.effects.put(slot, behavior);
		}

		/** Marked as effects in the list of names, so one can share its name with a block or a mob, as a sound can. */
		private String effectSlot(String name) {
			String slot = ServerModuleHost.this.slotsByName.get("effect:" + (name.contains("/") ? name : this.moduleId + "/" + name));
			if (slot == null) {
				throw new IllegalArgumentException("No effect is called " + name + ". It has to be listed in \"effects\" in feature.json");
			}
			return slot;
		}

		@Override
		public Holder<MobEffect> effect(String name) {
			return BuiltInRegistries.MOB_EFFECT.wrapAsHolder(BuiltInRegistries.MOB_EFFECT.getValue(Identifier.fromNamespaceAndPath("gm", effectSlot(name))));
		}

		@Override
		public void bindProjectile(String name, ProjectileBehavior behavior) {
			ServerModuleHost.this.projectiles.put(slot(name), behavior);
		}

		@Override
		public void bindVehicle(String name, VehicleBehavior behavior) {
			ServerModuleHost.this.vehicles.put(slot(name), behavior);
		}

		@Override
		public void bindProp(String name, PropBehavior behavior) {
			ServerModuleHost.this.props.put(slot(name), behavior);
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
		public Fluid fluid(String name) {
			return BuiltInRegistries.BLOCK.getValue(idOf(name)).defaultBlockState().getFluidState().getType();
		}

		@Override
		public EntityType<?> mob(String name) {
			return BuiltInRegistries.ENTITY_TYPE.getValue(idOf(name));
		}

		@Override
		public SlotProjectile shoot(String name, LivingEntity shooter) {
			return shoot(name, shooter.level(), shooter.getEyePosition(), shooter.getViewVector(1.0F), shooter);
		}

		@Override
		public SlotProjectile shoot(String name, LivingEntity shooter, Entity target) {
			Vec3 from = shooter.getEyePosition();
			return shoot(name, shooter.level(), from, target.getBoundingBox().getCenter().subtract(from), shooter);
		}

		@Override
		public SlotProjectile shoot(String name, Level level, Vec3 from, Vec3 direction, Entity owner) {
			return SlotEntities.shoot(BuiltInRegistries.ENTITY_TYPE.getValue(idOf(name)), (ServerLevel) level, from, direction, owner);
		}

		@Override
		public SlotVehicle placeVehicle(String name, Level level, Vec3 position, float yaw) {
			return place(name, level, position, yaw) instanceof SlotVehicle vehicle ? vehicle : null;
		}

		@Override
		public SlotProp placeProp(String name, Level level, Vec3 position, float yaw) {
			return place(name, level, position, yaw) instanceof SlotProp prop ? prop : null;
		}

		private Entity place(String name, Level level, Vec3 position, float yaw) {
			Entity entity = BuiltInRegistries.ENTITY_TYPE.getValue(idOf(name)).create(level, EntitySpawnReason.TRIGGERED);
			if (entity == null) {
				return null;
			}
			entity.snapTo(position.x, position.y, position.z, yaw, 0.0F);
			level.addFreshEntity(entity);
			return entity;
		}

		@Override
		public Beam beam(Level level, Vec3 from, Vec3 to, float thickness, BlockState looks, int seconds) {
			Beam beam = Beams.create((ServerLevel) level, from, to, thickness, looks, seconds);
			if (beam != null) {
				this.beams.removeIf(Beam::isRemoved);
				this.beams.add(beam);
			}
			return beam;
		}

		void removeBeams() {
			this.beams.forEach(Beam::remove);
			this.beams.clear();
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
		public MachineAttempt attemptRecipe(Player player, String machine, List<ItemStack> inputs, int gridWidth) {
			return Knowledge.instance().attempt(player, machine.contains("/") ? machine : this.moduleId + "/" + machine, inputs, gridWidth);
		}

		@Override
		public void setBar(ItemStack stack, float fraction) {
			ItemBars.set(stack, fraction);
		}

		@Override
		public float bar(ItemStack stack) {
			return ItemBars.fraction(stack);
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
			for (PanelMenu panel : List.copyOf(this.panels)) {
				if (panel.player().containerMenu == panel) {
					panel.close();
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
		public void setLight(Level level, BlockPos pos, int light) {
			BlockState state = level.getBlockState(pos);
			if (state.getBlock() instanceof SlotBlock) {
				level.setBlock(pos, state.setValue(SlotBlock.LIGHT, Math.clamp(light, 0, 15)), Block.UPDATE_ALL);
			}
		}

		/** Strong redstone reaches through the block next to it, so what's around those has to ask again too. */
		@Override
		public void redstoneChanged(Level level, BlockPos pos) {
			Block block = level.getBlockState(pos).getBlock();
			level.updateNeighborsAt(pos, block, null);
			for (Direction side : Direction.values()) {
				level.updateNeighborsAt(pos.relative(side), block, null);
			}
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
		public void openPanel(ServerPlayer player, String name, PanelBehavior behavior) {
			open(player, name, null, who -> true, behavior);
		}

		@Override
		public void openPanel(ServerPlayer player, String name, Container container, PanelBehavior behavior) {
			open(player, name, container, container::stillValid, behavior);
		}

		@Override
		public void openPanel(ServerPlayer player, String name, Entity near, PanelBehavior behavior) {
			open(player, name, null, who -> near.isAlive() && who.closerThan(near, PANEL_REACH), behavior);
		}

		private void open(ServerPlayer player, String name, Container container, Predicate<Player> stillThere, PanelBehavior behavior) {
			PanelDefinition definition = PanelDefinition.find(this.moduleId, name, player);
			player.openMenu(new SimpleMenuProvider((id, inventory, who) -> {
				PanelMenu panel = new PanelMenu(id, inventory, player, definition, container, stillThere, behavior, action -> guard(this, action));
				this.panels.removeIf(open -> open.player().containerMenu != open);
				this.panels.add(panel);
				return panel;
			}, Component.literal(definition.title())));
		}

		@Override
		public MutableComponent text(String name, Object... args) {
			String key = textKey(name);
			return Words.say(key, english(key, name), args);
		}

		@Override
		public String textFor(Player player, String name, Object... args) {
			String key = textKey(name);
			return Words.shown(player, key, english(key, name), args);
		}

		/** The name it has in the resource pack, which the broker works out the same way, so that it gives nothing away. */
		private String textKey(String name) {
			try {
				byte[] digest = MessageDigest.getInstance("SHA-256").digest((name.contains("/") ? name : this.moduleId + "/" + name).getBytes(StandardCharsets.UTF_8));
				return "text.gm.t" + HexFormat.of().formatHex(digest).substring(0, TEXT_ID_LENGTH);
			} catch (NoSuchAlgorithmException error) {
				throw new IllegalStateException(error);
			}
		}

		private static String english(String key, String name) {
			String found = ServerNames.english(key);
			if (found == null) {
				throw new IllegalArgumentException("No text is called " + name + ". It has to be in \"texts\" in feature.json");
			}
			return found;
		}

		@Override
		public void openBook(ServerPlayer player, String title, List<Component> pages) {
			Codex.showBook(player, title, pages.stream().map(Filterable::passThrough).toList());
		}

		@Override
		public CompoundTag state() {
			return ServerModuleHost.this.states.of(this.moduleId);
		}

		@Override
		public boolean knows(Player player, String knowledge) {
			return Knowledge.instance().knows(player, this.moduleId + "/" + knowledge);
		}

		@Override
		public void teach(ServerPlayer player, String knowledge) {
			Knowledge.instance().learn(player, this.moduleId + "/" + knowledge);
		}

		@Override
		public ServerLevel dimension(String name) {
			return Dimensions.level(ServerModuleHost.this.server, dimensionSlot(name));
		}

		@Override
		public void enterDimension(ServerPlayer player, String name) {
			Dimensions.enter(player, dimensionSlot(name));
		}

		@Override
		public void leaveDimension(ServerPlayer player) {
			Dimensions.leave(player);
		}

		private String dimensionSlot(String name) {
			String key = "dimension:" + (name.contains("/") ? name : this.moduleId + "/" + name);
			String slot = ServerModuleHost.this.slotsByName.get(key);
			if (slot == null) {
				throw new IllegalArgumentException("No dimension is called " + name + ". It has to be in \"dimensions\" in feature.json");
			}
			return slot;
		}
	}
}
