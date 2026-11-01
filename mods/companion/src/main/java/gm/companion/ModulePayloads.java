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

	/** A value a server module sent to a client module on this computer. conduit's ClientValues must stay in step with this. */
	record ServerValue(String moduleId, String key, String value) implements CustomPacketPayload {
		static final Type<ServerValue> TYPE = new Type<>(Identifier.fromNamespaceAndPath("gm", "client_value"));
		static final StreamCodec<ByteBuf, ServerValue> CODEC = StreamCodec.composite(
				ByteBufCodecs.STRING_UTF8, ServerValue::moduleId,
				ByteBufCodecs.STRING_UTF8, ServerValue::key,
				ByteBufCodecs.STRING_UTF8, ServerValue::value,
				ServerValue::new);

		@Override
		public Type<ServerValue> type() {
			return TYPE;
		}
	}

	/** Never sent. A client that listens for this is new enough for inventory hooks, and the server can see that it does. */
	record InventoryHooksSupported() implements CustomPacketPayload {
		static final Type<InventoryHooksSupported> TYPE = new Type<>(Identifier.fromNamespaceAndPath("gm", "inventory_hooks"));
		static final StreamCodec<ByteBuf, InventoryHooksSupported> CODEC = StreamCodec.unit(new InventoryHooksSupported());

		@Override
		public Type<InventoryHooksSupported> type() {
			return TYPE;
		}
	}
}
