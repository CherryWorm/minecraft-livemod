package gm.companion;

import com.mojang.blaze3d.platform.InputConstants;
import gm.companion.api.ClientModule;
import gm.companion.api.InventoryHooks;
import gm.companion.api.InventoryView;
import gm.companion.api.KeyInput;
import gm.companion.api.ModuleContext;
import gm.companion.api.ModuleImage;
import gm.companion.api.WorldCanvas;
import gm.companion.api.WorldView;
import net.fabricmc.fabric.api.client.rendering.v1.hud.HudElement;
import net.fabricmc.fabric.api.client.rendering.v1.level.LevelRenderContext;
import net.minecraft.client.DeltaTracker;
import net.minecraft.client.Minecraft;
import net.minecraft.client.gui.GuiGraphicsExtractor;
import net.minecraft.client.input.KeyEvent;
import net.minecraft.client.multiplayer.ClientLevel;
import net.minecraft.network.chat.Component;
import net.minecraft.network.chat.MutableComponent;
import net.minecraft.resources.Identifier;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.HexFormat;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Properties;
import java.util.function.Consumer;
import java.util.function.Predicate;

/**
 * Loads, runs and unloads client modules. Vanilla hooks can't be removed once added, so the host
 * registers one of each and dispatches to its modules. A module that keeps throwing or slows the game
 * down is switched off rather than taking the game with it.
 *
 * <p>Two safety nets live outside the JVM's reach, because code can't be sandboxed in-process on Java 25:
 * a crash while modules were active starts the next launch in safe mode, and any player can turn modules
 * off for themselves.
 */
public final class ModuleHost {
	private static final Logger LOGGER = LoggerFactory.getLogger("Companion");
	private static final int MAX_FAILURES = 3;
	private static final long FRAME_BUDGET_NANOS = 3_000_000;
	private static final int FRAME_WINDOW = 240;
	private static final Path CONFIG = Path.of("config", "companion");
	private static final Path RUNNING_MARKER = CONFIG.resolve("modules_running");
	private static final Path TURNED_OFF = CONFIG.resolve("modules_off");

	private final Map<String, LoadedModule> modules = new LinkedHashMap<>();
	private final Map<String, byte[][]> incoming = new HashMap<>();
	private final ModuleVerifier verifier = new ModuleVerifier();
	private final boolean safeMode = Files.exists(RUNNING_MARKER);
	private final WorldDrawing world = new WorldDrawing();
	private final WorldView worldView = new ClientWorldView();
	// The last of each value the server sent, by module, so that a module starting later still hears how things are. They last as long as the connection.
	private final Map<String, Map<String, String>> serverValues = new HashMap<>();
	private boolean turnedOff = Files.exists(TURNED_OFF);
	private ClientLevel lastLevel;
	private int completedUnloads;
	private int disabledForErrors;
	private int refused;

	ModuleHost() {
		if (this.safeMode) {
			LOGGER.warn("The game didn't shut down cleanly while modules were running. Starting without them this time.");
			try {
				Files.deleteIfExists(RUNNING_MARKER);
			} catch (IOException error) {
				LOGGER.warn("Couldn't clear the safe mode marker", error);
			}
		}
	}

	public boolean isActive(String moduleId) {
		return this.modules.containsKey(moduleId);
	}

	public int completedUnloads() {
		return this.completedUnloads;
	}

	public int disabledForErrors() {
		return this.disabledForErrors;
	}

	public int refused() {
		return this.refused;
	}

	public boolean turnedOff() {
		return this.turnedOff;
	}

	/** The player's own switch. It always wins, and it's remembered between sessions. */
	public void setTurnedOff(boolean off) {
		this.turnedOff = off;
		try {
			Files.createDirectories(CONFIG);
			if (off) {
				Files.writeString(TURNED_OFF, "");
			} else {
				Files.deleteIfExists(TURNED_OFF);
			}
		} catch (IOException error) {
			LOGGER.warn("Couldn't save the module setting", error);
		}
		if (off) {
			unloadAll();
			this.world.forget();
		}
	}

	void onChunk(ModulePayloads.Chunk chunk) {
		if (this.turnedOff || this.safeMode) {
			return;
		}
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
		load(chunk.moduleId(), chunk.generation(), jar.toByteArray(), chunk.signature());
	}

	private void load(String moduleId, int generation, byte[] jar, String signature) {
		String refusal = this.verifier.refusal(moduleId, generation, jar, signature);
		if (refusal != null) {
			this.refused++;
			LOGGER.warn("module {} generation {} refused: {}", moduleId, generation, refusal);
			return;
		}
		unload(moduleId);
		try {
			ModuleClassLoader loader = new ModuleClassLoader(jar, ModuleHost.class.getClassLoader());
			ClientModule module = (ClientModule) loader.loadClass(readEntryClass(loader)).getDeclaredConstructor().newInstance();
			LoadedModule loaded = new LoadedModule(moduleId, generation, module);
			module.enable(loaded);
			this.modules.put(moduleId, loaded);
			this.verifier.accepted(moduleId, generation);
			markRunning(true);
			LOGGER.info("module {} generation {} enabled", moduleId, generation);
		} catch (Exception | LinkageError error) {
			LOGGER.error("module {} generation {} failed to load", moduleId, generation, error);
		}
	}

	private void markRunning(boolean running) {
		try {
			Files.createDirectories(CONFIG);
			if (running) {
				Files.writeString(RUNNING_MARKER, "");
			} else {
				Files.deleteIfExists(RUNNING_MARKER);
			}
		} catch (IOException error) {
			LOGGER.warn("Couldn't update the safe mode marker", error);
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
		if (this.modules.isEmpty()) {
			markRunning(false);
		}
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
		ContainerView.newTick();
		dispatch(module -> module.tick(client));
	}

	/** Asks each module's hooks in turn. The first to say it's dealt with this is the last to hear of it. */
	boolean handleInventory(Predicate<InventoryHooks> call) {
		boolean[] handled = {false};
		dispatch(module -> {
			if (!handled[0]) {
				handled[0] = module.handleInventory(call);
			}
		});
		return handled[0];
	}

	public void keyPressed(KeyEvent event) {
		KeyInput key = InventoryScreens.key(event);
		dispatch(module -> module.keyPressed(key));
	}

	public void addScreenEffects(List<Identifier> requested) {
		for (LoadedModule module : this.modules.values()) {
			if (module.screenEffect != null) {
				requested.add(module.screenEffect);
			}
		}
	}

	public WorldDrawing world() {
		return this.world;
	}

	/** A shader from the server can crash a graphics driver as well as a module can, so the same safety nets apply. */
	void showInWorld(WorldPayloads.Show show) {
		if (this.turnedOff || this.safeMode) {
			return;
		}
		// It may have come straight after the news of a new level, ahead of the next frame, and this has to be about the new one.
		noticeLevel();
		this.world.keep(show.moduleId(), show.key(), WorldPayloads.shapes(show), show.seconds(), show.age(), show.fade(), show.moveX(), show.moveY(), show.moveZ());
		if (!show.shader().isEmpty()) {
			markRunning(true);
		}
	}

	void hearServerValue(ModulePayloads.ServerValue value) {
		this.serverValues.computeIfAbsent(value.moduleId(), id -> new HashMap<>()).put(value.key(), value.value());
		LoadedModule module = this.modules.get(value.moduleId());
		if (module != null) {
			module.hearValue(value.key(), value.value());
		}
	}

	void shakeFromServer(float strength, float seconds) {
		if (!this.turnedOff && !this.safeMode) {
			this.world.shake(strength, seconds);
		}
	}

	private void noticeLevel() {
		ClientLevel level = Minecraft.getInstance().level;
		if (level != this.lastLevel) {
			this.lastLevel = level;
			this.world.levelChanged();
		}
	}

	void renderWorld(LevelRenderContext context) {
		if (this.turnedOff || this.safeMode) {
			return;
		}
		noticeLevel();
		this.world.render(() -> dispatch(LoadedModule::drawsInWorld, module -> module.drawWorld(this.world)), context.gameRenderer().mainRenderTarget(), context.levelState().cameraRenderState);
	}

	void disconnected() {
		unloadAll();
		this.world.forget();
		this.serverValues.clear();
		this.lastLevel = null;
		markRunning(false);
	}

	private void dispatch(Consumer<LoadedModule> call) {
		dispatch(module -> true, call);
	}

	/** Only those it's about, so that calling everything that has nothing to do doesn't water down the average that says who's too slow. */
	private void dispatch(Predicate<LoadedModule> which, Consumer<LoadedModule> call) {
		List<String> broken = new ArrayList<>();
		for (LoadedModule module : this.modules.values()) {
			if (!which.test(module)) {
				continue;
			}
			long started = System.nanoTime();
			call.accept(module);
			if (module.failures >= MAX_FAILURES) {
				broken.add(module.moduleId);
				LOGGER.warn("module {} disabled after repeated errors", module.moduleId);
			} else if (module.overBudget(System.nanoTime() - started)) {
				broken.add(module.moduleId);
				LOGGER.warn("module {} disabled for slowing the game down", module.moduleId);
			}
		}
		for (String moduleId : broken) {
			this.disabledForErrors++;
			unload(moduleId);
		}
	}

	private static final class LoadedModule implements ModuleContext {
		private static final int EFFECT_ID_LENGTH = 16;
		private static final int MOST_IMAGE_SIZE = 512;
		private static final int MOST_IMAGES = 4;

		private final String moduleId;
		private final int generation;
		private final List<HudElement> hudElements = new ArrayList<>();
		private final List<Consumer<Minecraft>> ticks = new ArrayList<>();
		private final List<InventoryHooks> inventoryHooks = new ArrayList<>();
		private final List<Consumer<KeyInput>> keyHooks = new ArrayList<>();
		private final List<Consumer<WorldCanvas>> worldHooks = new ArrayList<>();
		private final Map<String, List<Consumer<String>>> valueListeners = new HashMap<>();
		private final List<PaintedImage> images = new ArrayList<>();
		private ClientModule module;
		private Identifier screenEffect;
		private int failures;
		private long windowNanos;
		private int windowCalls;

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

		@Override
		public void onInventory(InventoryHooks hooks) {
			this.inventoryHooks.add(hooks);
		}

		@Override
		public void onKeyPressed(Consumer<KeyInput> hook) {
			this.keyHooks.add(hook);
		}

		@Override
		public boolean keyDown(int key) {
			return InventoryScreens.keysAreSafe() && InputConstants.isKeyDown(key);
		}

		@Override
		public InventoryView inventory() {
			return InventoryScreens.current();
		}

		@Override
		public void screenEffect(String name) {
			this.screenEffect = name == null ? null : Identifier.fromNamespaceAndPath("gm", effectId(this.moduleId, name));
		}

		@Override
		public MutableComponent text(String name, Object... args) {
			return Component.translatable("text.gm.t" + hashed(name.contains("/") ? name : this.moduleId + "/" + name), args);
		}

		@Override
		public void onServerValue(String key, Consumer<String> listener) {
			this.valueListeners.computeIfAbsent(key, name -> new ArrayList<>()).add(listener);
			String value = Companion.host().serverValues.getOrDefault(this.moduleId, Map.of()).get(key);
			if (value != null) {
				guarded(() -> listener.accept(value));
			}
		}

		void hearValue(String key, String value) {
			for (Consumer<String> listener : this.valueListeners.getOrDefault(key, List.of())) {
				guarded(() -> listener.accept(value));
			}
		}

		@Override
		public WorldView world() {
			return Companion.host().worldView;
		}

		@Override
		public ModuleImage newImage(int width, int height) {
			if (width < 1 || height < 1 || width > MOST_IMAGE_SIZE || height > MOST_IMAGE_SIZE) {
				throw new IllegalArgumentException("An image can be at most " + MOST_IMAGE_SIZE + " across, not " + width + " by " + height);
			}
			if (this.images.size() >= MOST_IMAGES) {
				throw new IllegalStateException("A module can have at most " + MOST_IMAGES + " images");
			}
			PaintedImage image = new PaintedImage(this.moduleId, this.images.size(), width, height);
			this.images.add(image);
			return image;
		}

		@Override
		public void onWorld(Consumer<WorldCanvas> draw) {
			this.worldHooks.add(draw);
		}

		@Override
		public void shakeCamera(float strength, float seconds) {
			Companion.host().world().shake(strength, seconds);
		}

		boolean drawsInWorld() {
			return !this.worldHooks.isEmpty();
		}

		void drawWorld(WorldDrawing drawing) {
			WorldCanvas canvas = drawing.canvas(this.moduleId);
			for (Consumer<WorldCanvas> hook : this.worldHooks) {
				guarded(() -> hook.accept(canvas));
			}
		}

		/** The name it has in the resource pack, which the broker works out the same way, so that it gives nothing away. */
		private static String effectId(String moduleId, String name) {
			return "p" + hashed(moduleId + "/" + name);
		}

		private static String hashed(String name) {
			try {
				byte[] digest = MessageDigest.getInstance("SHA-256").digest(name.getBytes(StandardCharsets.UTF_8));
				return HexFormat.of().formatHex(digest).substring(0, EFFECT_ID_LENGTH);
			} catch (NoSuchAlgorithmException error) {
				throw new IllegalStateException(error);
			}
		}

		/** An average over many calls, so one slow frame while chunks load doesn't count. */
		boolean overBudget(long nanos) {
			this.windowNanos += nanos;
			if (++this.windowCalls < FRAME_WINDOW) {
				return false;
			}
			boolean over = this.windowNanos / this.windowCalls > FRAME_BUDGET_NANOS;
			this.windowCalls = 0;
			this.windowNanos = 0;
			return over;
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

		boolean handleInventory(Predicate<InventoryHooks> call) {
			boolean[] handled = {false};
			for (InventoryHooks hooks : this.inventoryHooks) {
				guarded(() -> handled[0] = call.test(hooks));
				if (handled[0]) {
					return true;
				}
			}
			return false;
		}

		void keyPressed(KeyInput key) {
			for (Consumer<KeyInput> hook : this.keyHooks) {
				guarded(() -> hook.accept(key));
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
			this.inventoryHooks.clear();
			this.keyHooks.clear();
			this.worldHooks.clear();
			this.valueListeners.clear();
			this.images.forEach(PaintedImage::close);
			this.images.clear();
			this.screenEffect = null;
			this.module = null;
		}
	}
}
