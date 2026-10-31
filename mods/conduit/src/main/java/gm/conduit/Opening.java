package gm.conduit;

import eu.pb4.polymer.virtualentity.api.ElementHolder;
import eu.pb4.polymer.virtualentity.api.attachment.ManualAttachment;
import eu.pb4.polymer.virtualentity.api.elements.BlockDisplayElement;
import net.fabricmc.fabric.api.entity.event.v1.ServerEntityLevelChangeEvents;
import net.fabricmc.fabric.api.event.lifecycle.v1.ServerLifecycleEvents;
import net.fabricmc.fabric.api.event.player.PlayerBlockBreakEvents;
import net.fabricmc.fabric.api.networking.v1.ServerPlayConnectionEvents;
import net.minecraft.core.BlockPos;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.network.chat.Component;
import net.minecraft.resources.Identifier;
import net.minecraft.server.MinecraftServer;
import net.minecraft.server.dedicated.DedicatedServer;
import net.minecraft.server.level.ServerLevel;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.util.Brightness;
import net.minecraft.world.Difficulty;
import net.minecraft.world.level.levelgen.Heightmap;
import net.minecraft.world.phys.Vec3;
import org.joml.Vector3f;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;

/**
 * The calm before the game starts. Players can talk to the agent and look around, in a small area with no hostile mobs
 * and no hunger, which Peaceful gives in one setting, and with nothing to break. Almost all the land stays ungenerated
 * and what's there stays untouched, so new content can appear in it naturally. It ends once, when the first release
 * reaches players: the border goes, the real difficulty comes back and it becomes morning.
 *
 * This is the game's to run, not the agent's, so it holds from the very first boot, whether or not an agent is up. The
 * server forces the difficulty from server.properties on every boot, so it's applied again each time until it's over.
 * It only runs where OPENING_BORDER is set, because tests and the shadow server need a normal world.
 */
public final class Opening {
	private static final Logger LOGGER = LoggerFactory.getLogger("Conduit");
	private static final Path OPENED = Path.of("config", "conduit", "world_open");
	private static final int SIZE = configuredSize(System.getenv("OPENING_BORDER"));
	private static final double OPEN_SIZE = 59_999_968;
	private static final int PANEL_SIZE = 16;
	private static final int WALL_ROWS = 6;
	private static final int WALL_BELOW_GROUND = 16;
	private static final float PANEL_THICKNESS = 0.1F;
	private static final float SEEN_FROM_FAR_AWAY = 8;

	private static ElementHolder wall;

	private Opening() {}

	private static int configuredSize(String text) {
		try {
			return text == null ? 0 : Integer.parseInt(text.strip());
		} catch (NumberFormatException error) {
			LOGGER.error("OPENING_BORDER isn't a number: {}", text);
			return 0;
		}
	}

	public static boolean isOn() {
		return SIZE > 0 && !Files.exists(OPENED);
	}

	/** How wide the opening's border is, or 0 once it's over. */
	public static int size() {
		return isOn() ? SIZE : 0;
	}

	public static void register() {
		ServerLifecycleEvents.SERVER_STARTED.register(Opening::onStart);
		PlayerBlockBreakEvents.BEFORE.register((level, player, pos, state, blockEntity) -> {
			if (!isOn()) {
				return true;
			}
			if (player instanceof ServerPlayer serverPlayer) {
				serverPlayer.sendSystemMessage(Component.literal("§7Nothing can be broken until the world opens."), true);
			}
			return false;
		});
		ServerPlayConnectionEvents.JOIN.register((handler, sender, server) -> {
			if (wall != null) {
				bringInside(server, handler.player);
				show(server, handler.player);
			}
		});
		ServerPlayConnectionEvents.DISCONNECT.register((handler, server) -> {
			if (wall != null) {
				wall.stopWatching(handler);
			}
		});
		ServerEntityLevelChangeEvents.AFTER_PLAYER_CHANGE_LEVEL.register((player, from, to) -> {
			if (wall != null) {
				wall.stopWatching(player);
				show(player.level().getServer(), player);
			}
		});
	}

	private static void onStart(MinecraftServer server) {
		ServerLevel overworld = server.overworld();
		if (isOn()) {
			BlockPos spawn = overworld.getRespawnData().pos();
			server.setDifficulty(Difficulty.PEACEFUL, true);
			overworld.getWorldBorder().setCenter(spawn.getX(), spawn.getZ());
			overworld.getWorldBorder().setSize(SIZE);
			wall = buildWall(overworld, spawn);
			LOGGER.info("the opening is on: a border {} wide around {} {}, with no hostile mobs and no hunger", SIZE, spawn.getX(), spawn.getZ());
		} else if ("shadow".equals(System.getenv("SERVER_ROLE"))) {
			// A copy of a world still in its opening shouldn't carry the small border into the tests.
			overworld.getWorldBorder().setSize(OPEN_SIZE);
		}
	}

	/** Ends the opening, if there is one. True if this is what ended it. */
	public static boolean open(MinecraftServer server) {
		if (!isOn()) {
			return false;
		}
		try {
			Files.createDirectories(OPENED.getParent());
			Files.writeString(OPENED, "");
		} catch (IOException error) {
			LOGGER.error("Can't record that the world has opened", error);
		}
		if (wall != null) {
			wall.destroy();
			wall = null;
		}
		server.overworld().getWorldBorder().setSize(OPEN_SIZE);
		server.setDifficulty(server instanceof DedicatedServer dedicated ? dedicated.getProperties().difficulty.get() : Difficulty.NORMAL, true);
		server.getCommands().performPrefixedCommand(server.createCommandSourceStack().withSuppressedOutput(), "time set day");
		server.getPlayerList().broadcastSystemMessage(Component.literal(
				"§e§lThe world has opened.§r§e The wall is gone, you can break things, monsters and hunger are back, and a new day is starting."), false);
		LOGGER.info("the opening is over");
		return true;
	}

	/**
	 * The border's own wall only shows up when you're nearly at it, so this puts a tall glowing wall along its whole
	 * length. It exists only on players' screens, so the world isn't touched and nothing's left behind afterwards.
	 */
	private static ElementHolder buildWall(ServerLevel overworld, BlockPos spawn) {
		ElementHolder holder = new ElementHolder();
		float half = SIZE / 2F;
		overworld.getChunk(spawn);
		int ground = overworld.getHeight(Heightmap.Types.MOTION_BLOCKING_NO_LEAVES, spawn.getX(), spawn.getZ());
		// Many small panels rather than one big sheet, because fog is worked out at a model's corners and blended across
		// it. A big sheet has its corners far out in the fog even when it's right in front of you, so all of it comes out
		// the colour of the fog, which is almost invisible.
		for (float along = -half; along < half; along += PANEL_SIZE) {
			float width = Math.min(PANEL_SIZE, half - along);
			for (int row = 0; row < WALL_ROWS; row++) {
				float bottom = ground - WALL_BELOW_GROUND + row * PANEL_SIZE;
				holder.addElement(panel(new Vec3(along, bottom, -half), new Vector3f(width, PANEL_SIZE, PANEL_THICKNESS)));
				holder.addElement(panel(new Vec3(along, bottom, half), new Vector3f(width, PANEL_SIZE, PANEL_THICKNESS)));
				holder.addElement(panel(new Vec3(-half, bottom, along), new Vector3f(PANEL_THICKNESS, PANEL_SIZE, width)));
				holder.addElement(panel(new Vec3(half, bottom, along), new Vector3f(PANEL_THICKNESS, PANEL_SIZE, width)));
			}
		}
		Vec3 centre = new Vec3(spawn.getX(), 0, spawn.getZ());
		new ManualAttachment(holder, overworld, () -> centre);
		return holder;
	}

	private static BlockDisplayElement panel(Vec3 corner, Vector3f size) {
		BlockDisplayElement panel = new BlockDisplayElement(BuiltInRegistries.BLOCK.getValue(Identifier.parse("minecraft:magenta_stained_glass")).defaultBlockState());
		panel.setOffset(corner);
		panel.setScale(size);
		panel.setBrightness(Brightness.FULL_BRIGHT);
		panel.setViewRange(SEEN_FROM_FAR_AWAY);
		return panel;
	}

	private static void show(MinecraftServer server, ServerPlayer player) {
		if (player.level() == server.overworld()) {
			wall.startWatching(player);
		}
	}

	/** Someone left outside a border slowly dies, which is no way to find out about it. */
	private static void bringInside(MinecraftServer server, ServerPlayer player) {
		ServerLevel overworld = server.overworld();
		if (player.level() != overworld || overworld.getWorldBorder().isWithinBounds(player.getX(), player.getZ())) {
			return;
		}
		BlockPos spawn = overworld.getRespawnData().pos();
		// Nobody may be near spawn, and an unloaded chunk reports its ground as the bottom of the world.
		overworld.getChunk(spawn);
		player.teleportTo(spawn.getX() + 0.5, overworld.getHeight(Heightmap.Types.MOTION_BLOCKING_NO_LEAVES, spawn.getX(), spawn.getZ()), spawn.getZ() + 0.5);
		player.sendSystemMessage(Component.literal("§7The world is still small for now, so you've been brought back to spawn."));
	}
}
