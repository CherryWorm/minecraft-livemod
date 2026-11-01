package gm.conduit.bridge;

import com.google.gson.JsonArray;
import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import com.google.gson.JsonPrimitive;
import gm.conduit.KillSwitch;
import gm.conduit.Opening;
import gm.conduit.knowledge.Knowledge;
import gm.conduit.mobs.Minds;
import gm.conduit.pack.LiveAssets;
import gm.conduit.pack.Words;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.network.chat.ClickEvent;
import net.minecraft.network.chat.Component;
import net.minecraft.network.chat.HoverEvent;
import net.minecraft.network.chat.MutableComponent;
import net.minecraft.server.MinecraftServer;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.level.block.state.BlockState;
import net.minecraft.world.phys.BlockHitResult;
import net.minecraft.world.phys.HitResult;

import java.util.Set;

/**
 * Everything the agent can do in the world. Speaking is limited to system messages, and fairness rules can't be
 * talked around through chat. The only operation that can give anyone anything is a mob's own small stash, whose
 * size and price in trust come from the release and are enforced in {@link Minds#act}.
 */
final class Operations {
	private static final Set<String> READ_ONLY = Set.of("status", "players", "progress");
	private static final double REACH = 5.0;

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
			case "inspect_player" -> inspectPlayer(server, text(request, "player"));
			case "open_world" -> new JsonPrimitive(Opening.open(server));
			case "progress" -> Knowledge.instance().progress();
			case "mob_act" -> Minds.act(request);
			case "board" -> Board.update(request);
			default -> throw new IllegalArgumentException("Unknown operation " + op);
		};
	}

	private static String text(JsonObject request, String field) {
		return request.get(field).getAsString();
	}

	/** So a bug someone's reported can be checked against what's really in front of them. It only reads. */
	private static JsonElement inspectPlayer(MinecraftServer server, String name) {
		ServerPlayer player = server.getPlayerList().getPlayerByName(name);
		if (player == null) {
			throw new IllegalArgumentException(name + " isn't online");
		}
		JsonObject found = new JsonObject();
		found.addProperty("dimension", player.level().dimension().identifier().toString());
		found.addProperty("x", player.getBlockX());
		found.addProperty("y", player.getBlockY());
		found.addProperty("z", player.getBlockZ());
		found.addProperty("game_mode", player.gameMode.getGameModeForPlayer().getName());
		found.addProperty("health", player.getHealth());
		found.addProperty("food", player.getFoodData().getFoodLevel());
		found.addProperty("screen_open", player.containerMenu != player.inventoryMenu);
		if (player.pick(REACH, 1.0F, false) instanceof BlockHitResult block && block.getType() == HitResult.Type.BLOCK) {
			BlockState state = player.level().getBlockState(block.getBlockPos());
			found.addProperty("looking_at", BuiltInRegistries.BLOCK.getKey(state.getBlock()).toString());
			found.addProperty("looking_at_name", LiveAssets.shownName(state.getBlock().getName()));
		}
		JsonArray carrying = new JsonArray();
		for (int slot = 0; slot < player.getInventory().getContainerSize(); slot++) {
			ItemStack stack = player.getInventory().getItem(slot);
			if (!stack.isEmpty()) {
				JsonObject item = new JsonObject();
				item.addProperty("slot", slot);
				item.addProperty("item", BuiltInRegistries.ITEM.getKey(stack.getItem()).toString());
				item.addProperty("name", LiveAssets.shownName(stack.getHoverName()));
				item.addProperty("count", stack.getCount());
				carrying.add(item);
			}
		}
		found.add("carrying", carrying);
		return found;
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
					.withHoverEvent(new HoverEvent.ShowText(Words.say("conduit.reply_hover", "Click to start your reply"))));
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
