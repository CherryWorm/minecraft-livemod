package gm.conduit.bridge;

import com.google.gson.JsonArray;
import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import com.google.gson.JsonPrimitive;
import net.minecraft.server.MinecraftServer;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.world.level.border.WorldBorder;

/**
 * Everything the agent can do in the world. Speaking is limited to system messages, and no operation
 * can give anyone anything, so fairness rules can't be talked around through chat.
 */
final class Operations {
	private Operations() {}

	static JsonElement run(MinecraftServer server, String op, JsonObject request) {
		return switch (op) {
			case "whisper" -> whisper(server, text(request, "player"), text(request, "text"));
			case "broadcast" -> broadcast(server, text(request, "text"));
			case "capture" -> capture(text(request, "player"), request.get("on").getAsBoolean());
			case "players" -> players(server);
			case "border" -> border(server, request.get("size").getAsDouble());
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
		border.setSize(size);
		return new JsonPrimitive(size);
	}
}
