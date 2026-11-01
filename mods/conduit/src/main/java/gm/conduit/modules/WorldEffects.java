package gm.conduit.modules;

import eu.pb4.polymer.core.api.block.PolymerBlock;
import gm.conduit.api.WorldEffect;
import net.fabricmc.fabric.api.entity.event.v1.ServerEntityLevelChangeEvents;
import net.fabricmc.fabric.api.event.lifecycle.v1.ServerTickEvents;
import net.fabricmc.fabric.api.networking.v1.PayloadTypeRegistry;
import net.fabricmc.fabric.api.networking.v1.ServerPlayConnectionEvents;
import net.fabricmc.fabric.api.networking.v1.ServerPlayNetworking;
import net.fabricmc.fabric.api.networking.v1.context.PacketContext;
import net.minecraft.network.FriendlyByteBuf;
import net.minecraft.network.codec.StreamCodec;
import net.minecraft.network.protocol.common.custom.CustomPacketPayload;
import net.minecraft.resources.Identifier;
import net.minecraft.resources.ResourceKey;
import net.minecraft.server.MinecraftServer;
import net.minecraft.server.level.ServerLevel;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.world.level.Level;
import net.minecraft.world.level.block.Block;
import net.minecraft.world.level.block.state.BlockState;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.HashSet;
import java.util.Iterator;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.UUID;

/**
 * Shows effects in the world on players' computers. Someone whose companion doesn't know about this just never gets them, and what they
 * can see of the world is otherwise the same. One that stays a while is kept here, so whoever comes near later, or back from another
 * dimension, gets it too. The wire format must stay in step with the companion's WorldPayloads.
 */
public final class WorldEffects {
	private static final int MOST_TEXT = 512;
	private static final int FLAG_GLOWING = 1;
	private static final int FLAG_THROUGH_WALLS = 2;
	private static final int[] PLACES_USED = {6, 9, 6, 3, 3};
	private static final int CHECK_EVERY_TICKS = 20;
	private static final float TICKS_A_SECOND = 20;
	// Starting values. The companion has its own limit on what it will draw, and this keeps a module with a mistake in it from flooding anyone's connection.
	private static final int MOST_SHOWN_A_TICK = 64;
	private static final int MOST_KEPT = 1024;

	private static final List<Active> ACTIVE = new ArrayList<>();
	private static final Map<UUID, Integer> SHOWN_THIS_TICK = new HashMap<>();
	private static MinecraftServer server;
	private static int nextKey;

	private WorldEffects() {}

	private record Part(int kind, double[] places, float width, float height, int blockId) {
		void write(FriendlyByteBuf buffer) {
			buffer.writeVarInt(this.kind);
			for (int index = 0; index < PLACES_USED[this.kind]; index++) {
				buffer.writeDouble(this.places[index]);
			}
			buffer.writeFloat(this.width);
			buffer.writeFloat(this.height);
			buffer.writeVarInt(this.blockId);
		}

		static Part read(FriendlyByteBuf buffer) {
			int kind = buffer.readVarInt();
			double[] places = new double[PLACES_USED[kind]];
			for (int index = 0; index < places.length; index++) {
				places[index] = buffer.readDouble();
			}
			return new Part(kind, places, buffer.readFloat(), buffer.readFloat(), buffer.readVarInt());
		}
	}

	private record Show(String moduleId, String key, int color, int flags, String shader, String image, float seconds, float age, float fade, float moveX, float moveY, float moveZ, List<Part> parts) implements CustomPacketPayload {
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
			List<Part> parts = new ArrayList<>();
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

	private record TakeAway(String moduleId, String key) implements CustomPacketPayload {
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

	private record Shake(float strength, float seconds) implements CustomPacketPayload {
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

	/** One that stays a while, and who's been told about it. */
	private static final class Active {
		final Show show;
		final ResourceKey<Level> dimension;
		final UUID only;
		final double x;
		final double y;
		final double z;
		final double range;
		final int started;
		final Set<UUID> told = new HashSet<>();

		Active(Show show, ResourceKey<Level> dimension, UUID only, double[] place, double range, int started) {
			this.show = show;
			this.dimension = dimension;
			this.only = only;
			this.x = place[0];
			this.y = place[1];
			this.z = place[2];
			this.range = range;
			this.started = started;
		}

		boolean reaches(ServerPlayer player) {
			return (this.only == null || this.only.equals(player.getUUID())) && player.level().dimension() == this.dimension
					&& player.distanceToSqr(this.x, this.y, this.z) <= this.range * this.range;
		}

		float age(int tick) {
			return (tick - this.started) / TICKS_A_SECOND;
		}
	}

	public static void register() {
		PayloadTypeRegistry.clientboundPlay().register(Show.TYPE, Show.CODEC);
		PayloadTypeRegistry.clientboundPlay().register(TakeAway.TYPE, TakeAway.CODEC);
		PayloadTypeRegistry.clientboundPlay().register(Shake.TYPE, Shake.CODEC);
		ServerTickEvents.END_SERVER_TICK.register(WorldEffects::tick);
		// A client drops what it's kept when it changes dimension or leaves, so it needs telling again when it comes back.
		ServerEntityLevelChangeEvents.AFTER_PLAYER_CHANGE_LEVEL.register((player, from, to) -> forgetTold(player.getUUID()));
		ServerPlayConnectionEvents.DISCONNECT.register((handler, gone) -> forgetTold(handler.player.getUUID()));
	}

	private static void forgetTold(UUID player) {
		ACTIVE.forEach(active -> active.told.remove(player));
	}

	private static void tick(MinecraftServer running) {
		server = running;
		SHOWN_THIS_TICK.clear();
		int tick = running.getTickCount();
		if (tick % CHECK_EVERY_TICKS != 0 || ACTIVE.isEmpty()) {
			return;
		}
		Iterator<Active> each = ACTIVE.iterator();
		while (each.hasNext()) {
			Active active = each.next();
			if (active.show.seconds() > 0 && active.age(tick) >= active.show.seconds()) {
				each.remove();
				continue;
			}
			ServerLevel level = running.getLevel(active.dimension);
			if (level != null) {
				for (ServerPlayer player : level.players()) {
					tell(player, active, tick);
				}
			}
		}
	}

	private static void tell(ServerPlayer player, Active active, int tick) {
		if (active.reaches(player) && !active.told.contains(player.getUUID()) && ServerPlayNetworking.canSend(player, Show.TYPE)
				&& SHOWN_THIS_TICK.merge(player.getUUID(), 1, Integer::sum) <= MOST_SHOWN_A_TICK) {
			active.told.add(player.getUUID());
			Show base = active.show;
			ServerPlayNetworking.send(player, new Show(base.moduleId, base.key, base.color, base.flags, base.shader, base.image, base.seconds, active.age(tick), base.fade, base.moveX, base.moveY, base.moveZ, base.parts));
		}
	}

	/** Shows an effect to everyone close enough in a level, or to only one player if there is one. */
	static void show(String moduleId, ServerLevel level, ServerPlayer only, WorldEffect effect) {
		List<WorldEffect.Part> parts = effect.parts();
		if (parts.isEmpty()) {
			throw new IllegalArgumentException("A world effect needs something in it");
		}
		if (parts.size() > WorldEffect.MOST_PARTS) {
			throw new IllegalArgumentException("A world effect can have at most " + WorldEffect.MOST_PARTS + " things in it, and this one has " + parts.size());
		}
		if (effect.seconds() <= 0 && effect.key().isEmpty()) {
			throw new IllegalArgumentException("A world effect that stays until it's taken away needs a key to take it away by");
		}
		String key = effect.key().isEmpty() ? "#" + nextKey++ : effect.key();
		List<Part> sent = new ArrayList<>(parts.size());
		for (WorldEffect.Part part : parts) {
			sent.add(new Part(part.kind(), part.places(), part.width(), part.height(), part.block() == null ? 0 : clientBlockId(part.block())));
		}
		int flags = (effect.isGlowing() ? FLAG_GLOWING : 0) | (effect.isThroughWalls() ? FLAG_THROUGH_WALLS : 0);
		Show show = new Show(moduleId, key, effect.color(), flags, effect.shader(), effect.image(), effect.seconds(), 0, effect.fade(), effect.moveX(), effect.moveY(), effect.moveZ(), sent);
		Active active = new Active(show, level.dimension(), only == null ? null : only.getUUID(), parts.getFirst().places(), effect.range(), level.getServer().getTickCount());
		ACTIVE.removeIf(old -> old.show.moduleId().equals(moduleId) && old.show.key().equals(key));
		for (ServerPlayer player : level.players()) {
			tell(player, active, active.started);
		}
		if ((effect.seconds() <= 0 || effect.seconds() * TICKS_A_SECOND > CHECK_EVERY_TICKS) && ACTIVE.size() < MOST_KEPT) {
			ACTIVE.add(active);
		}
	}

	static void clear(String moduleId, String key) {
		ACTIVE.removeIf(active -> active.show.moduleId().equals(moduleId) && (key.isEmpty() || active.show.key().equals(key)));
		if (server != null) {
			for (ServerPlayer player : server.getPlayerList().getPlayers()) {
				if (ServerPlayNetworking.canSend(player, TakeAway.TYPE)) {
					ServerPlayNetworking.send(player, new TakeAway(moduleId, key));
				}
			}
		}
	}

	static void shake(ServerPlayer player, float strength, float seconds) {
		if (ServerPlayNetworking.canSend(player, Shake.TYPE)) {
			ServerPlayNetworking.send(player, new Shake(strength, seconds));
		}
	}

	/** The number a client knows a block by, which for one of this world's is the vanilla block that stands in for it. */
	static int clientBlockId(BlockState state) {
		BlockState shown = state.getBlock() instanceof PolymerBlock polymer ? polymer.getPolymerBlockState(state, PacketContext.get()) : state;
		return Block.BLOCK_STATE_REGISTRY.getId(shown);
	}
}
