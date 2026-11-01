package gm.conduit.effects;

import com.google.gson.Gson;
import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import gm.conduit.Conduit;
import net.fabricmc.fabric.api.event.lifecycle.v1.ServerLifecycleEvents;
import net.fabricmc.fabric.api.event.lifecycle.v1.ServerTickEvents;
import net.fabricmc.fabric.api.networking.v1.PayloadTypeRegistry;
import net.fabricmc.fabric.api.networking.v1.ServerPlayConnectionEvents;
import net.fabricmc.fabric.api.networking.v1.ServerPlayNetworking;
import net.minecraft.core.Registry;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.network.RegistryFriendlyByteBuf;
import net.minecraft.network.codec.ByteBufCodecs;
import net.minecraft.network.codec.StreamCodec;
import net.minecraft.network.protocol.common.custom.CustomPacketPayload;
import net.minecraft.resources.Identifier;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.world.effect.MobEffectCategory;
import net.minecraft.world.effect.MobEffectInstance;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;

/**
 * The pool of blank status effects, and the current release's definitions for them. A game client can only show effects it was shipped with, so nothing short of something on
 * its own computer can show one of these: with no companion, one works as usual and just doesn't show. A companion is told what's on its own player, and draws it the way the
 * game draws its own, so the two lists can't disagree for long. Its EffectClient must stay in step with this.
 */
public final class SlotEffects {
	public static final int EFFECT_COUNT = 100;
	static final int NO_COLOUR = 0xFFFFFF;
	private static final Logger LOGGER = LoggerFactory.getLogger("Conduit");
	private static final Path FILE = Path.of("config", "conduit", "effects.json");
	private static final Definition NONE = new Definition(MobEffectCategory.NEUTRAL, NO_COLOUR);
	/** How often a companion's told the time left on what it knows about anyway, in case the two have drifted. */
	private static final int RESEND_TICKS = 100;
	private static final Map<UUID, List<Shown>> SENT = new HashMap<>();
	private static Map<String, Definition> definitions = Map.of();

	record Definition(MobEffectCategory category, int color) {}

	private SlotEffects() {}

	public static void register() {
		for (int index = 0; index < EFFECT_COUNT; index++) {
			String path = "fx%04d".formatted(index + 1);
			Registry.register(BuiltInRegistries.MOB_EFFECT, Identifier.fromNamespaceAndPath(Conduit.NAMESPACE, path), new SlotEffect(path));
		}
		PayloadTypeRegistry.clientboundPlay().register(Active.TYPE, Active.CODEC);
		ServerLifecycleEvents.SERVER_STARTED.register(server -> reload());
		ServerLifecycleEvents.END_DATA_PACK_RELOAD.register((server, resources, success) -> reload());
		ServerPlayConnectionEvents.DISCONNECT.register((handler, server) -> SENT.remove(handler.player.getUUID()));
		ServerTickEvents.END_SERVER_TICK.register(server -> server.getPlayerList().getPlayers().forEach(player -> sendIfChanged(player, server.getTickCount())));
	}

	static Definition definition(String slotId) {
		return definitions.getOrDefault(slotId, NONE);
	}

	private static void reload() {
		Map<String, Definition> found = new HashMap<>();
		if (Files.exists(FILE)) {
			try {
				JsonObject json = new Gson().fromJson(Files.readString(FILE), JsonObject.class);
				for (Map.Entry<String, JsonElement> entry : json.entrySet()) {
					JsonObject raw = entry.getValue().getAsJsonObject();
					found.put(entry.getKey(), new Definition(MobEffectCategory.valueOf(raw.get("category").getAsString().toUpperCase(java.util.Locale.ROOT)), raw.get("color").getAsInt()));
				}
			} catch (IOException | RuntimeException error) {
				LOGGER.error("Can't read {}", FILE, error);
			}
		}
		definitions = found;
	}

	private static void sendIfChanged(ServerPlayer player, int tick) {
		if (!ServerPlayNetworking.canSend(player, Active.TYPE)) {
			return;
		}
		List<Shown> now = new ArrayList<>();
		for (MobEffectInstance instance : player.getActiveEffects()) {
			if (instance.getEffect().value() instanceof SlotEffect effect) {
				now.add(new Shown(effect.slotId(), effect.getCategory().ordinal(), effect.getColor(), instance.getAmplifier(), instance.getDuration(), instance.isAmbient(), instance.isVisible(), instance.showIcon()));
			}
		}
		List<Shown> sent = SENT.getOrDefault(player.getUUID(), List.of());
		boolean same = sent.size() == now.size();
		for (int index = 0; same && index < now.size(); index++) {
			same = sent.get(index).sameLook(now.get(index));
		}
		if (!same || (!now.isEmpty() && tick % RESEND_TICKS == 0)) {
			SENT.put(player.getUUID(), now);
			ServerPlayNetworking.send(player, new Active(now));
		}
	}

	record Shown(String slot, int category, int color, int amplifier, int duration, boolean ambient, boolean visible, boolean icon) {
		static final StreamCodec<RegistryFriendlyByteBuf, Shown> CODEC = StreamCodec.of((buffer, shown) -> {
			buffer.writeUtf(shown.slot);
			buffer.writeVarInt(shown.category);
			buffer.writeInt(shown.color);
			buffer.writeVarInt(shown.amplifier);
			buffer.writeVarInt(shown.duration);
			buffer.writeBoolean(shown.ambient);
			buffer.writeBoolean(shown.visible);
			buffer.writeBoolean(shown.icon);
		}, buffer -> new Shown(buffer.readUtf(), buffer.readVarInt(), buffer.readInt(), buffer.readVarInt(), buffer.readVarInt(), buffer.readBoolean(), buffer.readBoolean(), buffer.readBoolean()));

		/** Everything but the time left, which a client counts down for itself. */
		boolean sameLook(Shown other) {
			return this.slot.equals(other.slot) && this.category == other.category && this.color == other.color && this.amplifier == other.amplifier
					&& this.ambient == other.ambient && this.visible == other.visible && this.icon == other.icon && this.duration <= other.duration + RESEND_TICKS;
		}
	}

	record Active(List<Shown> effects) implements CustomPacketPayload {
		static final Type<Active> TYPE = new Type<>(Identifier.fromNamespaceAndPath("gm", "effects"));
		static final StreamCodec<RegistryFriendlyByteBuf, Active> CODEC = StreamCodec.composite(Shown.CODEC.apply(ByteBufCodecs.list()), Active::effects, Active::new);

		@Override
		public Type<Active> type() {
			return TYPE;
		}
	}
}
