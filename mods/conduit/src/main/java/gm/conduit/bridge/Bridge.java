package gm.conduit.bridge;

import com.google.gson.Gson;
import com.google.gson.JsonObject;
import net.fabricmc.fabric.api.entity.event.v1.ServerLivingEntityEvents;
import net.fabricmc.fabric.api.event.lifecycle.v1.ServerLifecycleEvents;
import net.fabricmc.fabric.api.message.v1.ServerMessageEvents;
import net.fabricmc.fabric.api.networking.v1.ServerPlayConnectionEvents;
import net.minecraft.network.chat.Component;
import net.minecraft.server.MinecraftServer;
import net.minecraft.server.level.ServerPlayer;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.io.BufferedReader;
import java.io.BufferedWriter;
import java.io.IOException;
import java.io.InputStreamReader;
import java.io.OutputStreamWriter;
import java.net.InetSocketAddress;
import java.net.ServerSocket;
import java.net.Socket;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
import java.util.Set;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.CopyOnWriteArrayList;

/**
 * How the agent talks to the game, as JSON lines over a local socket that only the internal network can
 * reach. It sends events out and accepts a small set of typed operations in. There's deliberately no
 * way to run an arbitrary command: anything the agent should do in the world has an operation here, so
 * nothing injected through chat can reach a console.
 */
public final class Bridge {
	private static final Logger LOGGER = LoggerFactory.getLogger("Conduit");
	private static final Gson GSON = new Gson();
	private static final Path SECRET = Path.of("/run/secrets/bridge");
	private static final int PORT = 25580;

	private static final List<Client> CLIENTS = new CopyOnWriteArrayList<>();
	private static final Set<String> CAPTURED = ConcurrentHashMap.newKeySet();
	private static MinecraftServer server;

	private Bridge() {}

	public static void register() {
		ServerLifecycleEvents.SERVER_STARTED.register(started -> {
			server = started;
			if (Files.exists(SECRET)) {
				Thread.ofVirtual().name("conduit-bridge").start(Bridge::listen);
			} else {
				LOGGER.warn("bridge disabled: {} is missing", SECRET);
			}
		});

		ServerPlayConnectionEvents.JOIN.register((handler, sender, srv) -> emit(event("join", handler.player)));
		ServerPlayConnectionEvents.DISCONNECT.register((handler, srv) -> {
			CAPTURED.remove(handler.player.getGameProfile().name());
			emit(event("leave", handler.player));
		});

		// Captured players are in a private interview, so their chat goes to the agent and nobody else.
		ServerMessageEvents.ALLOW_CHAT_MESSAGE.register((message, sender, type) -> {
			boolean captured = CAPTURED.contains(sender.getGameProfile().name());
			JsonObject chat = event("chat", sender);
			chat.addProperty("text", message.signedContent());
			chat.addProperty("private", captured);
			emit(chat);
			return !captured;
		});

		ServerLivingEntityEvents.AFTER_DEATH.register((entity, source) -> {
			if (entity instanceof ServerPlayer player) {
				JsonObject death = event("death", player);
				death.addProperty("cause", source.getMsgId());
				emit(death);
			}
		});
	}

	public static JsonObject event(String kind, ServerPlayer player) {
		JsonObject json = new JsonObject();
		json.addProperty("event", kind);
		json.addProperty("player", player.getGameProfile().name());
		return json;
	}

	public static void emit(JsonObject json) {
		String line = GSON.toJson(json);
		for (Client client : CLIENTS) {
			client.send(line);
		}
	}

	private static void listen() {
		String secret;
		try {
			secret = Files.readString(SECRET).trim();
		} catch (IOException error) {
			LOGGER.error("bridge disabled: can't read the secret", error);
			return;
		}
		try (ServerSocket socket = new ServerSocket()) {
			socket.bind(new InetSocketAddress(PORT));
			LOGGER.info("bridge listening on port {}", PORT);
			while (!socket.isClosed()) {
				Socket connection = socket.accept();
				Thread.ofVirtual().name("conduit-bridge-client").start(() -> serve(connection, secret));
			}
		} catch (IOException error) {
			LOGGER.error("bridge stopped", error);
		}
	}

	private static void serve(Socket connection, String secret) {
		try (connection;
				BufferedReader reader = new BufferedReader(new InputStreamReader(connection.getInputStream(), StandardCharsets.UTF_8));
				BufferedWriter writer = new BufferedWriter(new OutputStreamWriter(connection.getOutputStream(), StandardCharsets.UTF_8))) {
			JsonObject hello = GSON.fromJson(reader.readLine(), JsonObject.class);
			if (hello == null || !hello.has("auth") || !secret.equals(hello.get("auth").getAsString())) {
				LOGGER.warn("bridge refused a connection with a bad secret");
				return;
			}
			Client client = new Client(writer);
			CLIENTS.add(client);
			try {
				String line;
				while ((line = reader.readLine()) != null) {
					handle(client, GSON.fromJson(line, JsonObject.class));
				}
			} finally {
				CLIENTS.remove(client);
			}
		} catch (IOException | RuntimeException error) {
			LOGGER.debug("bridge client closed", error);
		}
	}

	private static void handle(Client client, JsonObject request) {
		long id = request.has("id") ? request.get("id").getAsLong() : 0;
		String op = request.get("op").getAsString();
		// Everything touches game state, so it runs on the server thread.
		server.execute(() -> {
			JsonObject reply = new JsonObject();
			reply.addProperty("reply", id);
			try {
				reply.add("result", Operations.run(server, op, request));
				reply.addProperty("ok", true);
			} catch (RuntimeException error) {
				reply.addProperty("ok", false);
				reply.addProperty("error", String.valueOf(error.getMessage()));
			}
			client.send(GSON.toJson(reply));
		});
	}

	static void setCaptured(String player, boolean captured) {
		if (captured) {
			CAPTURED.add(player);
		} else {
			CAPTURED.remove(player);
		}
	}

	static Component literal(String text) {
		return Component.literal(text);
	}

	private record Client(BufferedWriter writer) {
		synchronized void send(String line) {
			try {
				this.writer.write(line);
				this.writer.newLine();
				this.writer.flush();
			} catch (IOException error) {
				LOGGER.debug("bridge client write failed", error);
			}
		}
	}
}
