package gm.conduit.panels;

import net.fabricmc.fabric.api.networking.v1.PayloadTypeRegistry;
import net.fabricmc.fabric.api.networking.v1.ServerPlayNetworking;
import net.minecraft.network.RegistryFriendlyByteBuf;
import net.minecraft.network.codec.ByteBufCodecs;
import net.minecraft.network.codec.StreamCodec;
import net.minecraft.network.protocol.common.custom.CustomPacketPayload;
import net.minecraft.resources.Identifier;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.world.item.ItemStack;

import java.util.List;

/** What goes between a panel and a companion that can draw it. The companion's PanelClient must stay in step with this. */
public final class PanelNetwork {
	private static final int MOST_TEXT = 1 << 20;
	private static final int MOST_TYPED = 4096;

	private PanelNetwork() {}

	/**
	 * @param definition the whole panel, when it opens, or an empty string for an update
	 * @param state what's changed, with stacks referred to by where they are in the list
	 */
	public record Shown(int containerId, String definition, String state, List<ItemStack> stacks) implements CustomPacketPayload {
		static final Type<Shown> TYPE = new Type<>(Identifier.fromNamespaceAndPath("gm", "panel"));
		static final StreamCodec<RegistryFriendlyByteBuf, Shown> CODEC = StreamCodec.composite(
				ByteBufCodecs.VAR_INT, Shown::containerId,
				ByteBufCodecs.stringUtf8(MOST_TEXT), Shown::definition,
				ByteBufCodecs.stringUtf8(MOST_TEXT), Shown::state,
				ItemStack.OPTIONAL_STREAM_CODEC.apply(ByteBufCodecs.list()), Shown::stacks,
				Shown::new);

		@Override
		public Type<Shown> type() {
			return TYPE;
		}
	}

	/** Clicks go as ordinary clicks on the chest underneath, so this is the only thing a client ever sends that a plain chest wouldn't. */
	public record Typed(int containerId, String id, String value) implements CustomPacketPayload {
		static final Type<Typed> TYPE = new Type<>(Identifier.fromNamespaceAndPath("gm", "panel_typed"));
		static final StreamCodec<RegistryFriendlyByteBuf, Typed> CODEC = StreamCodec.composite(
				ByteBufCodecs.VAR_INT, Typed::containerId,
				ByteBufCodecs.stringUtf8(MOST_TYPED), Typed::id,
				ByteBufCodecs.stringUtf8(MOST_TYPED), Typed::value,
				Typed::new);

		@Override
		public Type<Typed> type() {
			return TYPE;
		}
	}

	public static void register() {
		PayloadTypeRegistry.clientboundPlay().register(Shown.TYPE, Shown.CODEC);
		PayloadTypeRegistry.serverboundPlay().register(Typed.TYPE, Typed.CODEC);
		ServerPlayNetworking.registerGlobalReceiver(Typed.TYPE, (payload, context) -> {
			// Only ever about the panel this player really has open, whatever it says.
			if (context.player().containerMenu instanceof PanelMenu panel && panel.containerId == payload.containerId()) {
				panel.typedByClient(payload.id(), payload.value());
			}
		});
		PanelDefinition.register();
	}

	static boolean canDraw(ServerPlayer player) {
		return ServerPlayNetworking.canSend(player, Shown.TYPE);
	}

	static void send(ServerPlayer player, Shown shown) {
		ServerPlayNetworking.send(player, shown);
	}
}
