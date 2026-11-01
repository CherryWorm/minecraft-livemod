package gm.conduit.modules;

import io.netty.buffer.ByteBuf;
import net.fabricmc.fabric.api.event.lifecycle.v1.ServerTickEvents;
import net.fabricmc.fabric.api.networking.v1.PayloadTypeRegistry;
import net.fabricmc.fabric.api.networking.v1.ServerPlayConnectionEvents;
import net.fabricmc.fabric.api.networking.v1.ServerPlayNetworking;
import net.minecraft.network.codec.ByteBufCodecs;
import net.minecraft.network.codec.StreamCodec;
import net.minecraft.network.protocol.common.custom.CustomPacketPayload;
import net.minecraft.resources.Identifier;
import net.minecraft.server.MinecraftServer;
import net.minecraft.server.level.ServerPlayer;

import java.util.HashMap;
import java.util.Iterator;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.UUID;

/**
 * Small values on their way from a server module to a client module on one player's computer. Only the latest of each is sent, once a tick,
 * and only if it's changed, so a module can say how things are as often as it likes. companion's ModulePayloads must stay in step with this.
 */
public final class ClientValues {
	private static final int MOST_KEY = 128;
	private static final int MOST_VALUE = 8192;
	// For one player. A module that goes past this is using a new key for every little thing, and those would never be freed.
	private static final int MOST_KEYS = 512;
	// For one player in one tick, which is about as much as a connection should have to carry for this. Whatever's left goes on the next tick.
	private static final int MOST_CHARS_A_TICK = 32768;

	private static final Map<UUID, Map<String, Value>> WAITING = new HashMap<>();
	private static final Map<UUID, Map<String, String>> SENT = new HashMap<>();

	private ClientValues() {}

	record Value(String moduleId, String key, String value) implements CustomPacketPayload {
		static final Type<Value> TYPE = new Type<>(Identifier.fromNamespaceAndPath("gm", "client_value"));
		static final StreamCodec<ByteBuf, Value> CODEC = StreamCodec.composite(
				ByteBufCodecs.STRING_UTF8, Value::moduleId,
				ByteBufCodecs.STRING_UTF8, Value::key,
				ByteBufCodecs.STRING_UTF8, Value::value,
				Value::new);

		@Override
		public Type<Value> type() {
			return TYPE;
		}
	}

	public static void register() {
		PayloadTypeRegistry.clientboundPlay().register(Value.TYPE, Value.CODEC);
		ServerTickEvents.END_SERVER_TICK.register(ClientValues::tick);
		ServerPlayConnectionEvents.DISCONNECT.register((handler, gone) -> {
			WAITING.remove(handler.player.getUUID());
			SENT.remove(handler.player.getUUID());
		});
	}

	static void send(String moduleId, ServerPlayer player, String key, String value) {
		if (key.length() > MOST_KEY || value.length() > MOST_VALUE) {
			throw new IllegalArgumentException("A client value can have a key of up to " + MOST_KEY + " characters and a value of up to " + MOST_VALUE + ", not " + key.length() + " and " + value.length());
		}
		if (!ServerPlayNetworking.canSend(player, Value.TYPE)) {
			return;
		}
		String name = moduleId + "/" + key;
		Map<String, String> sent = SENT.getOrDefault(player.getUUID(), Map.of());
		Map<String, Value> waiting = WAITING.computeIfAbsent(player.getUUID(), id -> new LinkedHashMap<>());
		if (value.equals(sent.get(name))) {
			// It may have changed and changed back, in which case what's waiting isn't what's wanted any more.
			waiting.remove(name);
			return;
		}
		if (!sent.containsKey(name) && !waiting.containsKey(name) && sent.size() + waiting.size() >= MOST_KEYS) {
			throw new IllegalStateException("A player can only be sent " + MOST_KEYS + " different client values, so a key can't be new every time");
		}
		waiting.put(name, new Value(moduleId, key, value));
	}

	/** So that it says everything again when it starts again, to a client that may have started again as well. */
	static void forget(String moduleId) {
		String named = moduleId + "/";
		WAITING.values().forEach(values -> values.keySet().removeIf(name -> name.startsWith(named)));
		SENT.values().forEach(values -> values.keySet().removeIf(name -> name.startsWith(named)));
	}

	private static void tick(MinecraftServer server) {
		Iterator<Map.Entry<UUID, Map<String, Value>>> players = WAITING.entrySet().iterator();
		while (players.hasNext()) {
			Map.Entry<UUID, Map<String, Value>> entry = players.next();
			ServerPlayer player = server.getPlayerList().getPlayer(entry.getKey());
			if (player != null) {
				sendSome(player, entry.getValue());
			}
			if (player == null || entry.getValue().isEmpty()) {
				players.remove();
			}
		}
	}

	private static void sendSome(ServerPlayer player, Map<String, Value> waiting) {
		Map<String, String> sent = SENT.computeIfAbsent(player.getUUID(), id -> new HashMap<>());
		int chars = 0;
		Iterator<Map.Entry<String, Value>> values = waiting.entrySet().iterator();
		while (values.hasNext() && chars < MOST_CHARS_A_TICK) {
			Map.Entry<String, Value> entry = values.next();
			Value value = entry.getValue();
			chars += value.value().length();
			sent.put(entry.getKey(), value.value());
			values.remove();
			ServerPlayNetworking.send(player, value);
		}
	}
}
