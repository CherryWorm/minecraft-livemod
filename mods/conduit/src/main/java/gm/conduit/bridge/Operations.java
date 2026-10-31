package gm.conduit.bridge;

import com.google.gson.JsonArray;
import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import com.google.gson.JsonPrimitive;
import gm.conduit.KillSwitch;
import gm.conduit.Opening;
import gm.conduit.knowledge.Knowledge;
import gm.conduit.mobs.Minds;
import net.minecraft.network.chat.ClickEvent;
import net.minecraft.network.chat.Component;
import net.minecraft.network.chat.HoverEvent;
import net.minecraft.network.chat.MutableComponent;
import net.minecraft.server.MinecraftServer;
import net.minecraft.server.level.ServerPlayer;

import java.util.Set;

/**
 * Everything the agent can do in the world. Speaking is limited to system messages, and fairness rules can't be
 * talked around through chat. The only operation that can give anyone anything is a mob's own small stash, whose
 * size and price in trust come from the release and are enforced in {@link Minds#act}.
 */
final class Operations {
	private static final Set<String> READ_ONLY = Set.of("status", "players", "progress");

	private Operations() {}

	private static JsonElement status() {
		JsonObject status = new JsonObject();
		status.addProperty("agent_disabled", KillSwitch.on());
		status.addProperty("opening", Opening.size());
		return status;
	}

	static JsonElement run(MinecraftServer server, String op, JsonObject request) {
		if (KillSwitch.on() && !READ_ONLY.contains(op)) {
			throw new IllegalStateException("The kill switch is on");
		}
		return switch (op) {
			case "status" -> status();
			case "whisper" -> whisper(server, text(request, "player"), text(request, "text"), request.has("reply_click"));
			case "broadcast" -> broadcast(server, text(request, "text"));
			case "players" -> players(server);
			case "open_world" -> new JsonPrimitive(Opening.open(server));
			case "progress" -> Knowledge.instance().progress();
			case "mob_act" -> Minds.act(request);
			default -> throw new IllegalArgumentException("Unknown operation " + op);
		};
	}

	private static String text(JsonObject request, String field) {
		return request.get(field).getAsString();
	}

	private static JsonElement whisper(MinecraftServer server, String name, String text, boolean replyClick) {
		ServerPlayer player = server.getPlayerList().getPlayerByName(name);
		if (player == null) {
			throw new IllegalArgumentException(name + " isn't online");
		}
		MutableComponent message = Bridge.literal(text);
		if (replyClick) {
			// Always exactly this, so nothing a model writes can put another command in a player's chat box.
			message.withStyle(style -> style.withClickEvent(new ClickEvent.SuggestCommand("/dm "))
					.withHoverEvent(new HoverEvent.ShowText(Component.literal("Click to start your reply"))));
		}
		player.sendSystemMessage(message);
		return new JsonPrimitive(true);
	}

	private static JsonElement broadcast(MinecraftServer server, String text) {
		server.getPlayerList().broadcastSystemMessage(Bridge.literal(text), false);
		return new JsonPrimitive(true);
	}

	private static JsonElement players(MinecraftServer server) {
		JsonArray list = new JsonArray();
		for (ServerPlayer player : server.getPlayerList().getPlayers()) {
			JsonObject entry = new JsonObject();
			entry.addProperty("name", player.getGameProfile().name());
			entry.addProperty("health", player.getHealth());
			entry.addProperty("x", player.getBlockX());
			entry.addProperty("y", player.getBlockY());
			entry.addProperty("z", player.getBlockZ());
			entry.addProperty("dimension", player.level().dimension().identifier().toString());
			entry.addProperty("safe", SafeMoment.isSafe(player));
			list.add(entry);
		}
		return list;
	}
}
