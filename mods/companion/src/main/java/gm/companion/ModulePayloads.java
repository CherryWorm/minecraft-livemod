package gm.companion;

import io.netty.buffer.ByteBuf;
import net.minecraft.network.codec.ByteBufCodecs;
import net.minecraft.network.codec.StreamCodec;
import net.minecraft.network.protocol.common.custom.CustomPacketPayload;
import net.minecraft.resources.Identifier;

/** The wire format for module delivery. conduit's ModulePush must stay in step with this. */
final class ModulePayloads {
	private ModulePayloads() {}

	record Chunk(String moduleId, int generation, int index, int total, String signature, byte[] data) implements CustomPacketPayload {
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

	record Unload(String moduleId) implements CustomPacketPayload {
		static final Type<Unload> TYPE = new Type<>(Identifier.fromNamespaceAndPath("gm", "module_unload"));
		static final StreamCodec<ByteBuf, Unload> CODEC = StreamCodec.composite(
				ByteBufCodecs.STRING_UTF8, Unload::moduleId,
				Unload::new);

		@Override
		public Type<Unload> type() {
			return TYPE;
		}
	}
}
