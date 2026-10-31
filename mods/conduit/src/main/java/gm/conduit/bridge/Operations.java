package gm.conduit.bridge;

import com.google.gson.JsonArray;
import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import com.google.gson.JsonPrimitive;
import gm.conduit.KillSwitch;
import gm.conduit.knowledge.Knowledge;
import gm.conduit.mobs.Minds;
import net.minecraft.server.MinecraftServer;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.world.level.border.WorldBorder;

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
		return status;
	}

	static JsonElement run(MinecraftServer server, String op, JsonObject request) {
		if (KillSwitch.on() && !READ_ONLY.contains(op)) {
			throw new IllegalStateException("The kill switch is on");
		}
		return switch (op) {
			case "status" -> status();
			case "whisper" -> whisper(server, text(request, "player"), text(request, "text"));
			case "broadcast" -> broadcast(server, text(request, "text"));
			case "capture" -> capture(text(request, "player"), request.get("on").getAsBoolean());
			case "players" -> players(server);
			case "border" -> border(server, request.get("size").getAsDouble());
			case "progress" -> Knowledge.instance().progress();
			case "mob_act" -> Minds.act(request);
			default -> throw new IllegalArgumentException("Unknown operation " + op);
		};
	}

	private static String text(JsonObject request, String field) {
		return request.get(field).getAsString();
	}

	private static JsonElement whisper(MinecraftServer server, String name, String text) {
		ServerPlayer player = server.getPlayerList().getPlayerByName(name);
		if (player == null) {
			throw new IllegalArgumentException(name + " isn't online");
		}
		player.sendSystemMessage(Bridge.literal(text));
		return new JsonPrimitive(true);
	}

	private static JsonElement broadcast(MinecraftServer server, String text) {
		server.getPlayerList().broadcastSystemMessage(Bridge.literal(text), false);
		return new JsonPrimitive(true);
	}

	private static JsonElement capture(String name, boolean on) {
		Bridge.setCaptured(name, on);
		return new JsonPrimitive(on);
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

	private static JsonElement border(MinecraftServer server, double size) {
		WorldBorder border = server.overworld().getWorldBorder();
		// Around spawn, not the world's origin: players left outside a border take damage until they die.
		var spawn = server.overworld().getRespawnData().pos();
		border.setCenter(spawn.getX(), spawn.getZ());
		border.setSize(size);
		return new JsonPrimitive(size);
	}
}
