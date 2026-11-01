package gm.companion;

import net.fabricmc.fabric.api.client.networking.v1.ClientPlayNetworking;
import net.fabricmc.fabric.api.networking.v1.PayloadTypeRegistry;
import net.minecraft.network.FriendlyByteBuf;
import net.minecraft.network.codec.StreamCodec;
import net.minecraft.network.protocol.common.custom.CustomPacketPayload;
import net.minecraft.resources.Identifier;

import java.util.ArrayList;
import java.util.List;

/** What the server asks to have drawn in the world. conduit's WorldEffects must stay in step with this. */
final class WorldPayloads {
	private static final int MOST_TEXT = 512;
	private static final int FLAG_GLOWING = 1;
	private static final int FLAG_THROUGH_WALLS = 2;
	private static final int PLACES = 9;
	// How many of the nine numbers each kind of thing has, in WorldDrawing's order: a box, a sheet, a beam, a billboard and a block.
	private static final int[] PLACES_USED = {6, 9, 6, 3, 3};

	private WorldPayloads() {}

	record Part(int kind, double[] places, float width, float height, int blockId) {
		static Part read(FriendlyByteBuf buffer) {
			int kind = buffer.readVarInt();
			double[] places = new double[PLACES];
			for (int index = 0; index < PLACES_USED[kind]; index++) {
				places[index] = buffer.readDouble();
			}
			return new Part(kind, places, buffer.readFloat(), buffer.readFloat(), buffer.readVarInt());
		}

		void write(FriendlyByteBuf buffer) {
			buffer.writeVarInt(this.kind);
			for (int index = 0; index < PLACES_USED[this.kind]; index++) {
				buffer.writeDouble(this.places[index]);
			}
			buffer.writeFloat(this.width);
			buffer.writeFloat(this.height);
			buffer.writeVarInt(this.blockId);
		}
	}

	record Show(String moduleId, String key, int color, int flags, String shader, String image, float seconds, float age, float fade, float moveX, float moveY, float moveZ, List<Part> parts) implements CustomPacketPayload {
		static final Type<Show> TYPE = new Type<>(Identifier.fromNamespaceAndPath("gm", "world_show"));
		static final StreamCodec<FriendlyByteBuf, Show> CODEC = StreamCodec.of((buffer, show) -> {
			buffer.writeUtf(show.moduleId, MOST_TEXT);
			buffer.writeUtf(show.key, MOST_TEXT);
			buffer.writeInt(show.color);
			buffer.writeVarInt(show.flags);
			buffer.writeUtf(show.shader, MOST_TEXT);
			buffer.writeUtf(show.image, MOST_TEXT);
			buffer.writeFloat(show.seconds);
			buffer.writeFloat(show.age);
			buffer.writeFloat(show.fade);
			buffer.writeFloat(show.moveX);
			buffer.writeFloat(show.moveY);
			buffer.writeFloat(show.moveZ);
			buffer.writeVarInt(show.parts.size());
			show.parts.forEach(part -> part.write(buffer));
		}, buffer -> {
			String moduleId = buffer.readUtf(MOST_TEXT);
			String key = buffer.readUtf(MOST_TEXT);
			int color = buffer.readInt();
			int flags = buffer.readVarInt();
			String shader = buffer.readUtf(MOST_TEXT);
			String image = buffer.readUtf(MOST_TEXT);
			float seconds = buffer.readFloat();
			float age = buffer.readFloat();
			float fade = buffer.readFloat();
			float moveX = buffer.readFloat();
			float moveY = buffer.readFloat();
			float moveZ = buffer.readFloat();
			int count = buffer.readVarInt();
			List<Part> parts = new ArrayList<>(Math.min(count, 1024));
			for (int index = 0; index < count; index++) {
				parts.add(Part.read(buffer));
			}
			return new Show(moduleId, key, color, flags, shader, image, seconds, age, fade, moveX, moveY, moveZ, parts);
		});

		@Override
		public Type<Show> type() {
			return TYPE;
		}
	}

	/** Takes away one thing, or everything of a module's with an empty key. */
	record TakeAway(String moduleId, String key) implements CustomPacketPayload {
		static final Type<TakeAway> TYPE = new Type<>(Identifier.fromNamespaceAndPath("gm", "world_take_away"));
		static final StreamCodec<FriendlyByteBuf, TakeAway> CODEC = StreamCodec.of((buffer, away) -> {
			buffer.writeUtf(away.moduleId, MOST_TEXT);
			buffer.writeUtf(away.key, MOST_TEXT);
		}, buffer -> new TakeAway(buffer.readUtf(MOST_TEXT), buffer.readUtf(MOST_TEXT)));

		@Override
		public Type<TakeAway> type() {
			return TYPE;
		}
	}

	record Shake(float strength, float seconds) implements CustomPacketPayload {
		static final Type<Shake> TYPE = new Type<>(Identifier.fromNamespaceAndPath("gm", "world_shake"));
		static final StreamCodec<FriendlyByteBuf, Shake> CODEC = StreamCodec.of((buffer, shake) -> {
			buffer.writeFloat(shake.strength);
			buffer.writeFloat(shake.seconds);
		}, buffer -> new Shake(buffer.readFloat(), buffer.readFloat()));

		@Override
		public Type<Shake> type() {
			return TYPE;
		}
	}

	static void register(ModuleHost host) {
		PayloadTypeRegistry.clientboundPlay().register(Show.TYPE, Show.CODEC);
		PayloadTypeRegistry.clientboundPlay().register(TakeAway.TYPE, TakeAway.CODEC);
		PayloadTypeRegistry.clientboundPlay().register(Shake.TYPE, Shake.CODEC);
		ClientPlayNetworking.registerGlobalReceiver(Show.TYPE, (payload, context) -> host.showInWorld(payload));
		ClientPlayNetworking.registerGlobalReceiver(TakeAway.TYPE, (payload, context) -> host.world().takeAway(payload.moduleId(), payload.key()));
		ClientPlayNetworking.registerGlobalReceiver(Shake.TYPE, (payload, context) -> host.shakeFromServer(payload.strength(), payload.seconds()));
	}

	static List<WorldDrawing.Shape> shapes(Show show) {
		Identifier image = WorldDrawing.imageId(show.moduleId(), show.image());
		Identifier shader = WorldDrawing.shaderId(show.moduleId(), show.shader());
		boolean glowing = (show.flags() & FLAG_GLOWING) != 0;
		boolean throughWalls = (show.flags() & FLAG_THROUGH_WALLS) != 0;
		List<WorldDrawing.Shape> shapes = new ArrayList<>(show.parts().size());
		for (Part part : show.parts()) {
			shapes.add(WorldDrawing.shape(part.kind(), part.places(), part.width(), part.height(), part.blockId(), show.color(), image, shader, glowing, throughWalls));
		}
		return shapes;
	}
}
