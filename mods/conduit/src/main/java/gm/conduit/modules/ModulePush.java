package gm.conduit.modules;

import com.google.gson.Gson;
import com.google.gson.JsonObject;
import com.mojang.brigadier.arguments.IntegerArgumentType;
import com.mojang.brigadier.arguments.StringArgumentType;
import io.netty.buffer.ByteBuf;
import net.fabricmc.fabric.api.command.v2.CommandRegistrationCallback;
import net.fabricmc.fabric.api.networking.v1.PayloadTypeRegistry;
import net.fabricmc.fabric.api.networking.v1.ServerPlayConnectionEvents;
import net.fabricmc.fabric.api.networking.v1.ServerPlayNetworking;
import net.minecraft.commands.CommandSourceStack;
import net.minecraft.commands.Commands;
import net.minecraft.network.chat.Component;
import net.minecraft.network.codec.ByteBufCodecs;
import net.minecraft.network.codec.StreamCodec;
import net.minecraft.network.protocol.common.custom.CustomPacketPayload;
import net.minecraft.resources.Identifier;
import net.minecraft.server.MinecraftServer;
import net.minecraft.server.level.ServerPlayer;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Arrays;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.stream.Stream;

/**
 * Sends client modules to players running the companion mod. The server only relays them: each one is
 * signed by the broker, and the companion checks that itself, so this class needs no special trust.
 * The wire format must stay in step with the companion's ModulePayloads.
 */
public final class ModulePush {
	private static final Logger LOGGER = LoggerFactory.getLogger("Conduit");
	private static final Path DIRECTORY = Path.of("modules", "client");
	private static final Path REQUIRE_COMPANION = Path.of("config", "conduit", "require_companion");
	private static final int CHUNK_BYTES = 512 * 1024;
	/** A companion listens for this if it has inventory hooks. Only its name is ever used, so it's never sent. */
	private static final CustomPacketPayload.Type<?> INVENTORY_HOOKS = new CustomPacketPayload.Type<>(Identifier.fromNamespaceAndPath("gm", "inventory_hooks"));
	private static final String OUT_OF_DATE = "§6Your Companion mod is out of date, so anything on your inventory screens won't work. Download the pack from the website again, and import it the same way.";

	private static final Map<String, Module> ACTIVE = new HashMap<>();

	private ModulePush() {}

	private record Module(String id, int generation, String signature, byte[] jar) {}

	private record Chunk(String moduleId, int generation, int index, int total, String signature, byte[] data) implements CustomPacketPayload {
		static final Type<Chunk> TYPE = new Type<>(Identifier.fromNamespaceAndPath("gm", "module_chunk"));
		static final StreamCodec<ByteBuf, Chunk> CODEC = StreamCodec.composite(
				ByteBufCodecs.STRING_UTF8, Chunk::moduleId,
				ByteBufCodecs.VAR_INT, Chunk::generation,
				ByteBufCodecs.VAR_INT, Chunk::index,
				ByteBufCodecs.VAR_INT, Chunk::total,
				ByteBufCodecs.STRING_UTF8, Chunk::signature,
				ByteBufCodecs.BYTE_ARRAY, Chunk::data,
				Chunk::new);

		@Override
		public Type<Chunk> type() {
			return TYPE;
		}
	}

	private record Unload(String moduleId) implements CustomPacketPayload {
		static final Type<Unload> TYPE = new Type<>(Identifier.fromNamespaceAndPath("gm", "module_unload"));
		static final StreamCodec<ByteBuf, Unload> CODEC = StreamCodec.composite(
				ByteBufCodecs.STRING_UTF8, Unload::moduleId,
				Unload::new);

		@Override
		public Type<Unload> type() {
			return TYPE;
		}
	}

	public static void register() {
		PayloadTypeRegistry.clientboundPlay().register(Chunk.TYPE, Chunk.CODEC);
		PayloadTypeRegistry.clientboundPlay().register(Unload.TYPE, Unload.CODEC);

		ServerPlayConnectionEvents.JOIN.register((handler, sender, server) -> {
			ServerPlayer player = handler.player;
			if (!ServerPlayNetworking.canSend(player, Chunk.TYPE)) {
				// Once client modules exist, everyone needs the companion, or some players get a UI others lack.
				if (Files.exists(REQUIRE_COMPANION)) {
					handler.disconnect(Component.literal("This server needs the Companion mod. Ask whoever runs it for the install file."));
				}
				return;
			}
			if (!ServerPlayNetworking.canSend(player, INVENTORY_HOOKS)) {
				player.sendSystemMessage(Component.literal(OUT_OF_DATE));
			}
			ACTIVE.values().forEach(module -> send(player, module));
		});

		CommandRegistrationCallback.EVENT.register((dispatcher, registryAccess, environment) -> dispatcher.register(
				Commands.literal("conduit")
						.requires(Commands.hasPermission(Commands.LEVEL_GAMEMASTERS))
						.then(Commands.literal("module")
								.then(Commands.literal("reload").executes(context -> reload(context.getSource())))
								// Spike S4 and the module tests use these two, with modules that aren't signed.
								.then(Commands.literal("push")
										.then(Commands.argument("file", StringArgumentType.word())
												.then(Commands.argument("id", StringArgumentType.word())
														.then(Commands.argument("generation", IntegerArgumentType.integer(0))
																.executes(context -> pushOne(context.getSource(),
																		StringArgumentType.getString(context, "file"),
																		StringArgumentType.getString(context, "id"),
																		IntegerArgumentType.getInteger(context, "generation")))))))
								.then(Commands.literal("unload")
										.then(Commands.argument("id", StringArgumentType.word())
												.executes(context -> unloadOne(context.getSource(),
														StringArgumentType.getString(context, "id"))))))));
	}

	/** Makes running modules match the folder, sending what changed to everyone with the companion. */
	private static int reload(CommandSourceStack source) {
		Map<String, Module> found = readFolder();
		MinecraftServer server = source.getServer();
		int changed = 0;
		for (String id : List.copyOf(ACTIVE.keySet())) {
			if (!found.containsKey(id)) {
				ACTIVE.remove(id);
				sendToAll(server, new Unload(id));
				changed++;
			}
		}
		for (Module module : found.values()) {
			Module existing = ACTIVE.get(module.id());
			if (existing == null || existing.generation() != module.generation() || !Arrays.equals(existing.jar(), module.jar())) {
				ACTIVE.put(module.id(), module);
				server.getPlayerList().getPlayers().forEach(player -> {
					if (ServerPlayNetworking.canSend(player, Chunk.TYPE)) {
						send(player, module);
					}
				});
				changed++;
			}
		}
		int total = changed;
		source.sendSuccess(() -> Component.literal("Client modules changed: " + total + ", active: " + ACTIVE.size()), false);
		return changed;
	}

	public static void loadOnStart() {
		ACTIVE.putAll(readFolder());
	}

	private static Map<String, Module> readFolder() {
		Map<String, Module> found = new HashMap<>();
		if (!Files.isDirectory(DIRECTORY)) {
			return found;
		}
		try (Stream<Path> files = Files.list(DIRECTORY)) {
			for (Path jar : files.filter(path -> path.toString().endsWith(".jar")).toList()) {
				String name = jar.getFileName().toString();
				String id = name.substring(0, name.length() - 4);
				Path signatureFile = DIRECTORY.resolve(id + ".json");
				if (!Files.exists(signatureFile)) {
					LOGGER.warn("client module {} has no signature, so it won't be sent", id);
					continue;
				}
				JsonObject signature = new Gson().fromJson(Files.readString(signatureFile), JsonObject.class);
				found.put(id, new Module(id, signature.get("generation").getAsInt(), signature.get("signature").getAsString(), Files.readAllBytes(jar)));
			}
		} catch (IOException | RuntimeException error) {
			LOGGER.error("Can't read {}", DIRECTORY, error);
		}
		return found;
	}

	private static void send(ServerPlayer player, Module module) {
		byte[] jar = module.jar();
		int total = Math.max(1, (jar.length + CHUNK_BYTES - 1) / CHUNK_BYTES);
		for (int index = 0; index < total; index++) {
			int from = index * CHUNK_BYTES;
			byte[] part = Arrays.copyOfRange(jar, from, Math.min(jar.length, from + CHUNK_BYTES));
			ServerPlayNetworking.send(player, new Chunk(module.id(), module.generation(), index, total, module.signature(), part));
		}
	}

	private static void sendToAll(MinecraftServer server, CustomPacketPayload payload) {
		for (ServerPlayer player : server.getPlayerList().getPlayers()) {
			if (ServerPlayNetworking.canSend(player, payload.type())) {
				ServerPlayNetworking.send(player, payload);
			}
		}
	}

	private static int pushOne(CommandSourceStack source, String file, String moduleId, int generation) {
		byte[] jar;
		String signature = "";
		try {
			jar = Files.readAllBytes(Path.of("modules").resolve(file + ".jar"));
			Path signatureFile = Path.of("modules").resolve(file + ".sig");
			if (Files.exists(signatureFile)) {
				signature = Files.readString(signatureFile).trim();
			}
		} catch (IOException error) {
			source.sendFailure(Component.literal("Can't read module " + file + ": " + error.getMessage()));
			return 0;
		}
		Module module = new Module(moduleId, generation, signature, jar);
		int players = 0;
		for (ServerPlayer player : source.getServer().getPlayerList().getPlayers()) {
			if (ServerPlayNetworking.canSend(player, Chunk.TYPE)) {
				send(player, module);
				players++;
			}
		}
		int sentTo = players;
		source.sendSuccess(() -> Component.literal("Pushed " + moduleId + " generation " + generation + " to " + sentTo + " player(s)"), false);
		return sentTo;
	}

	private static int unloadOne(CommandSourceStack source, String moduleId) {
		sendToAll(source.getServer(), new Unload(moduleId));
		source.sendSuccess(() -> Component.literal("Unloaded " + moduleId), false);
		return 1;
	}
}
