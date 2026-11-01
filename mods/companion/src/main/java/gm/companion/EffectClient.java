package gm.companion;

import net.fabricmc.fabric.api.client.event.lifecycle.v1.ClientTickEvents;
import net.fabricmc.fabric.api.client.networking.v1.ClientPlayNetworking;
import net.fabricmc.fabric.api.networking.v1.PayloadTypeRegistry;
import net.minecraft.client.Minecraft;
import net.minecraft.client.player.LocalPlayer;
import net.minecraft.core.Holder;
import net.minecraft.network.RegistryFriendlyByteBuf;
import net.minecraft.network.codec.ByteBufCodecs;
import net.minecraft.network.codec.StreamCodec;
import net.minecraft.network.protocol.common.custom.CustomPacketPayload;
import net.minecraft.resources.Identifier;
import net.minecraft.world.effect.MobEffect;
import net.minecraft.world.effect.MobEffectCategory;
import net.minecraft.world.effect.MobEffectInstance;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * Shows the status effects of this world that the server says the player has. The game can only be told about those it was shipped with, so these are put straight on the
 * player here, where the game's own HUD and inventory screen draw them with the rest. Conduit's SlotEffects must stay in step with the format.
 */
public final class EffectClient {
	private static final Map<Identifier, Holder<MobEffect>> OURS = new HashMap<>();
	private static List<Shown> wanted = List.of();
	private static LocalPlayer appliedTo;

	private EffectClient() {}

	/** What the game asks for in place of a registered effect's name and picture. */
	public static final class ClientEffect extends MobEffect {
		private final Identifier slot;

		ClientEffect(Identifier slot, MobEffectCategory category, int color) {
			super(category, color);
			this.slot = slot;
		}

		public Identifier sprite() {
			return this.slot.withPrefix("mob_effect/");
		}

		@Override
		public String getDescriptionId() {
			return "effect." + this.slot.getNamespace() + "." + this.slot.getPath();
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
	}

	record Active(List<Shown> effects) implements CustomPacketPayload {
		static final Type<Active> TYPE = new Type<>(Identifier.fromNamespaceAndPath("gm", "effects"));
		static final StreamCodec<RegistryFriendlyByteBuf, Active> CODEC = StreamCodec.composite(Shown.CODEC.apply(ByteBufCodecs.list()), Active::effects, Active::new);

		@Override
		public Type<Active> type() {
			return TYPE;
		}
	}

	static void register() {
		PayloadTypeRegistry.clientboundPlay().register(Active.TYPE, Active.CODEC);
		ClientPlayNetworking.registerGlobalReceiver(Active.TYPE, (payload, context) -> {
			wanted = payload.effects();
			apply();
		});
		// Respawning or changing dimension makes a new player here, and the server has nothing new to say.
		ClientTickEvents.END_CLIENT_TICK.register(client -> {
			if (client.player != appliedTo) {
				apply();
			}
		});
	}

	static void forget() {
		wanted = List.of();
		OURS.clear();
		appliedTo = null;
	}

	private static void apply() {
		LocalPlayer player = Minecraft.getInstance().player;
		appliedTo = player;
		if (player == null) {
			return;
		}
		List<Holder<MobEffect>> kept = new ArrayList<>();
		for (Shown shown : wanted) {
			Holder<MobEffect> effect = OURS.computeIfAbsent(Identifier.fromNamespaceAndPath("gm", shown.slot()), slot ->
					Holder.direct(new ClientEffect(slot, MobEffectCategory.values()[shown.category()], shown.color())));
			kept.add(effect);
			player.forceAddEffect(new MobEffectInstance(effect, shown.duration(), shown.amplifier(), shown.ambient(), shown.visible(), shown.icon()), null);
		}
		for (Holder<MobEffect> effect : OURS.values()) {
			if (!kept.contains(effect) && player.hasEffect(effect)) {
				player.removeEffectNoUpdate(effect);
			}
		}
	}
}
