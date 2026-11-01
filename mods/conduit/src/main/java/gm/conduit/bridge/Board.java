package gm.conduit.bridge;

import com.google.gson.Gson;
import com.google.gson.JsonArray;
import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import com.google.gson.JsonPrimitive;
import com.mojang.brigadier.Command;
import net.fabricmc.fabric.api.command.v2.CommandRegistrationCallback;
import net.fabricmc.fabric.api.event.lifecycle.v1.ServerLifecycleEvents;
import net.fabricmc.fabric.api.event.lifecycle.v1.ServerTickEvents;
import net.fabricmc.fabric.api.networking.v1.ServerPlayConnectionEvents;
import net.minecraft.ChatFormatting;
import net.minecraft.commands.Commands;
import net.minecraft.network.chat.Component;
import net.minecraft.network.chat.numbers.BlankFormat;
import net.minecraft.network.chat.numbers.FixedFormat;
import net.minecraft.network.chat.numbers.NumberFormat;
import net.minecraft.network.protocol.game.ClientboundResetScorePacket;
import net.minecraft.network.protocol.game.ClientboundSetDisplayObjectivePacket;
import net.minecraft.network.protocol.game.ClientboundSetObjectivePacket;
import net.minecraft.network.protocol.game.ClientboundSetScorePacket;
import net.minecraft.server.MinecraftServer;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.world.scores.DisplaySlot;
import net.minecraft.world.scores.Objective;
import net.minecraft.world.scores.Scoreboard;
import net.minecraft.world.scores.criteria.ObjectiveCriteria;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.Set;
import java.util.UUID;

/**
 * A sidebar showing how the world's build is going, for whoever turns it on with /board. It goes to each of them as
 * packets, so nothing needs installing, and the server's real scoreboard, which everyone shares, stays out of it. The
 * agent says what to show through {@link Operations}, and if it stops saying, the board says that instead of showing old news.
 */
public final class Board {
	private static final Logger LOGGER = LoggerFactory.getLogger("Conduit");
	private static final Gson GSON = new Gson();
	private static final Path PLAYERS = Path.of("config", "conduit", "board_players.json");
	private static final String OBJECTIVE = "gm_board";
	private static final long AWAY_AFTER_MILLIS = 90_000;
	private static final int CHECK_TICKS = 100;
	private static final int MOST_LINES = 15;
	private static final int MOST_BEING_BUILT = 8;
	private static final int LONGEST_TEXT = 40;
	// Only these, so that nothing but the words on the left can come from a model.
	private static final Map<String, ChatFormatting> TAGS = Map.of("early", ChatFormatting.GREEN, "mid", ChatFormatting.YELLOW,
			"late", ChatFormatting.LIGHT_PURPLE, "small", ChatFormatting.AQUA);

	private static final Set<UUID> WATCHING = new HashSet<>();
	private static MinecraftServer server;
	private static JsonObject latest;
	private static long heardAt;
	private static List<Line> lines = List.of();

	private Board() {}

	public static void register() {
		ServerLifecycleEvents.SERVER_STARTED.register(started -> {
			server = started;
			load();
		});
		ServerPlayConnectionEvents.JOIN.register((handler, sender, srv) -> {
			if (WATCHING.contains(handler.player.getUUID())) {
				start(handler.player);
			}
		});
		ServerTickEvents.END_SERVER_TICK.register(srv -> {
			if (srv.getTickCount() % CHECK_TICKS == 0) {
				refresh();
			}
		});
		CommandRegistrationCallback.EVENT.register((dispatcher, registryAccess, environment) -> dispatcher.register(Commands.literal("board").executes(context -> {
			toggle(context.getSource().getPlayerOrException());
			return Command.SINGLE_SUCCESS;
		})));
	}

	/** What the agent wants shown now: counts of what's shipped, being built and queued, and a line for each thing being built. */
	static JsonElement update(JsonObject request) {
		latest = request;
		heardAt = System.currentTimeMillis();
		refresh();
		return new JsonPrimitive(true);
	}

	private static void toggle(ServerPlayer player) {
		if (WATCHING.remove(player.getUUID())) {
			player.connection.send(new ClientboundSetObjectivePacket(objective(), ClientboundSetObjectivePacket.METHOD_REMOVE));
			player.sendSystemMessage(Component.literal("§7The build board is off. Type §f/board§7 to bring it back."));
		} else {
			refresh();
			WATCHING.add(player.getUUID());
			start(player);
			player.sendSystemMessage(Component.literal("§7The build board is on. Type §f/board§7 again to hide it."));
		}
		save();
	}

	private static void start(ServerPlayer player) {
		// Adding one the client already has would disconnect it, and it can still have this one from before a restart.
		player.connection.send(new ClientboundSetObjectivePacket(objective(), ClientboundSetObjectivePacket.METHOD_REMOVE));
		player.connection.send(new ClientboundSetObjectivePacket(objective(), ClientboundSetObjectivePacket.METHOD_ADD));
		player.connection.send(new ClientboundSetDisplayObjectivePacket(DisplaySlot.SIDEBAR, objective()));
		sendChanges(player, List.of(), lines);
	}

	private static void refresh() {
		List<Line> fresh = render();
		if (fresh.equals(lines)) {
			return;
		}
		List<Line> old = lines;
		lines = fresh;
		for (UUID id : WATCHING) {
			ServerPlayer player = server.getPlayerList().getPlayer(id);
			if (player != null) {
				sendChanges(player, old, fresh);
			}
		}
	}

	private static List<Line> render() {
		List<Line> found = new ArrayList<>();
		if (latest != null) {
			found.add(Line.count("Shipped", latest.get("shipped").getAsInt(), ChatFormatting.GREEN));
			found.add(Line.count("In the works", latest.get("building").getAsInt(), ChatFormatting.YELLOW));
			found.add(Line.count("In the queue", latest.get("queued").getAsInt(), ChatFormatting.AQUA));
		}
		if (latest == null || System.currentTimeMillis() - heardAt > AWAY_AFTER_MILLIS) {
			found.add(Line.note(" ", ChatFormatting.GRAY));
			found.add(Line.note("The agent is away, so this", ChatFormatting.GRAY));
			found.add(Line.note("isn't updating right now", ChatFormatting.GRAY));
			return found;
		}
		found.add(Line.note(" ", ChatFormatting.GRAY));
		found.add(Line.note("Being built now", ChatFormatting.GOLD));
		JsonArray now = latest.getAsJsonArray("now");
		if (now.isEmpty()) {
			found.add(Line.note("Nothing this minute", ChatFormatting.GRAY));
		}
		for (int index = 0; index < Math.min(now.size(), MOST_BEING_BUILT); index++) {
			JsonObject item = now.get(index).getAsJsonObject();
			found.add(Line.building(item.get("text").getAsString(), item.get("tag").getAsString()));
		}
		return found;
	}

	private static void sendChanges(ServerPlayer player, List<Line> old, List<Line> fresh) {
		for (int index = 0; index < fresh.size(); index++) {
			if (index >= old.size() || !fresh.get(index).equals(old.get(index))) {
				player.connection.send(fresh.get(index).packet(index));
			}
		}
		for (int index = fresh.size(); index < old.size(); index++) {
			player.connection.send(new ClientboundResetScorePacket(owner(index), OBJECTIVE));
		}
	}

	private static Objective objective() {
		return new Objective(new Scoreboard(), OBJECTIVE, ObjectiveCriteria.DUMMY, Component.literal("Build Progress").withStyle(ChatFormatting.GOLD, ChatFormatting.BOLD),
				ObjectiveCriteria.RenderType.INTEGER, false, BlankFormat.INSTANCE);
	}

	private static String owner(int index) {
		return "line" + index;
	}

	private static void load() {
		WATCHING.clear();
		try {
			if (Files.exists(PLAYERS)) {
				for (JsonElement id : GSON.fromJson(Files.readString(PLAYERS), JsonArray.class)) {
					WATCHING.add(UUID.fromString(id.getAsString()));
				}
			}
		} catch (IOException | RuntimeException error) {
			LOGGER.warn("couldn't read who has the build board on", error);
		}
	}

	private static void save() {
		JsonArray ids = new JsonArray();
		WATCHING.forEach(id -> ids.add(id.toString()));
		try {
			Files.createDirectories(PLAYERS.getParent());
			Files.writeString(PLAYERS, GSON.toJson(ids));
		} catch (IOException error) {
			LOGGER.warn("couldn't save who has the build board on", error);
		}
	}

	/** Words on the left, and a short right-aligned value where the score would be. */
	private record Line(String text, ChatFormatting colour, String right, ChatFormatting rightColour) {
		static Line count(String label, int count, ChatFormatting colour) {
			return new Line(label, ChatFormatting.WHITE, String.valueOf(count), colour);
		}

		static Line note(String text, ChatFormatting colour) {
			return new Line(text, colour, "", colour);
		}

		static Line building(String text, String tag) {
			String clean = text.replace("§", "");
			String shown = clean.length() > LONGEST_TEXT ? clean.substring(0, LONGEST_TEXT - 1) + "…" : clean;
			ChatFormatting colour = TAGS.get(tag);
			return new Line(shown, ChatFormatting.WHITE, colour == null ? "" : tag, colour == null ? ChatFormatting.GRAY : colour);
		}

		ClientboundSetScorePacket packet(int index) {
			NumberFormat format = this.right.isEmpty() ? BlankFormat.INSTANCE : new FixedFormat(Component.literal(this.right).withStyle(this.rightColour));
			return new ClientboundSetScorePacket(owner(index), OBJECTIVE, MOST_LINES - index, Optional.of(Component.literal(this.text).withStyle(this.colour)), Optional.of(format));
		}
	}
}
