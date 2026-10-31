package gm.conduit.modules;

import com.mojang.brigadier.arguments.IntegerArgumentType;
import com.mojang.brigadier.arguments.StringArgumentType;
import io.netty.buffer.ByteBuf;
import net.fabricmc.fabric.api.command.v2.CommandRegistrationCallback;
import net.fabricmc.fabric.api.networking.v1.PayloadTypeRegistry;
import net.fabricmc.fabric.api.networking.v1.ServerPlayNetworking;
import net.minecraft.commands.CommandSourceStack;
import net.minecraft.commands.Commands;
import net.minecraft.network.chat.Component;
import net.minecraft.network.codec.ByteBufCodecs;
import net.minecraft.network.codec.StreamCodec;
import net.minecraft.network.protocol.common.custom.CustomPacketPayload;
import net.minecraft.resources.Identifier;
import net.minecraft.server.level.ServerPlayer;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Arrays;

/**
 * Pushes client module jars to players running the companion mod. Players without it are skipped.
 * The wire format must stay in step with the companion's ModulePayloads.
 */
public final class ModulePush {
	private static final Path DIRECTORY = Path.of("modules");
	private static final int CHUNK_BYTES = 512 * 1024;

	private ModulePush() {}

	private record Chunk(String moduleId, int generation, int index, int total, byte[] data) implements CustomPacketPayload {
		static final Type<Chunk> TYPE = new Type<>(Identifier.fromNamespaceAndPath("gm", "module_chunk"));
		static final StreamCodec<ByteBuf, Chunk> CODEC = StreamCodec.composite(
				ByteBufCodecs.STRING_UTF8, Chunk::moduleId,
				ByteBufCodecs.VAR_INT, Chunk::generation,
				ByteBufCodecs.VAR_INT, Chunk::index,
				ByteBufCodecs.VAR_INT, Chunk::total,
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

		CommandRegistrationCallback.EVENT.register((dispatcher, registryAccess, environment) -> dispatcher.register(
				Commands.literal("conduit")
						.requires(Commands.hasPermission(Commands.LEVEL_GAMEMASTERS))
						.then(Commands.literal("module")
								.then(Commands.literal("push")
										.then(Commands.argument("file", StringArgumentType.word())
												.then(Commands.argument("id", StringArgumentType.word())
														.then(Commands.argument("generation", IntegerArgumentType.integer(0))
																.executes(context -> push(context.getSource(),
																		StringArgumentType.getString(context, "file"),
																		StringArgumentType.getString(context, "id"),
																		IntegerArgumentType.getInteger(context, "generation")))))))
								.then(Commands.literal("unload")
										.then(Commands.argument("id", StringArgumentType.word())
												.executes(context -> unload(context.getSource(),
														StringArgumentType.getString(context, "id"))))))));
	}

	private static int push(CommandSourceStack source, String file, String moduleId, int generation) {
		byte[] jar;
		try {
			jar = Files.readAllBytes(DIRECTORY.resolve(file + ".jar"));
		} catch (IOException error) {
			source.sendFailure(Component.literal("Can't read module " + file + ": " + error.getMessage()));
			return 0;
		}
		int total = Math.max(1, (jar.length + CHUNK_BYTES - 1) / CHUNK_BYTES);
		int players = 0;
		for (ServerPlayer player : source.getServer().getPlayerList().getPlayers()) {
			if (ServerPlayNetworking.canSend(player, Chunk.TYPE)) {
				for (int index = 0; index < total; index++) {
					int from = index * CHUNK_BYTES;
					byte[] part = Arrays.copyOfRange(jar, from, Math.min(jar.length, from + CHUNK_BYTES));
					ServerPlayNetworking.send(player, new Chunk(moduleId, generation, index, total, part));
				}
				players++;
			}
		}
		int sentTo = players;
		source.sendSuccess(() -> Component.literal("Pushed " + moduleId + " generation " + generation + " to " + sentTo + " player(s)"), false);
		return sentTo;
	}

	private static int unload(CommandSourceStack source, String moduleId) {
		int players = 0;
		for (ServerPlayer player : source.getServer().getPlayerList().getPlayers()) {
			if (ServerPlayNetworking.canSend(player, Unload.TYPE)) {
				ServerPlayNetworking.send(player, new Unload(moduleId));
				players++;
			}
		}
		int sentTo = players;
		source.sendSuccess(() -> Component.literal("Unloaded " + moduleId + " on " + sentTo + " player(s)"), false);
		return sentTo;
	}
}
