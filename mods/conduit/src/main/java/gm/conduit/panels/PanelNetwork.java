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

	/** Clicks go as ordinary clicks on the chest underneath, so this and a click on a row too far down a long list are all a client ever sends that a plain chest wouldn't. */
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

	/** A click on a row that has no place of its own in the chest, because a list has more than a chest can hold. Like typing, it's only an id and a number. */
	public record RowClicked(int containerId, String id, int row, boolean rightClick, boolean shift) implements CustomPacketPayload {
		static final Type<RowClicked> TYPE = new Type<>(Identifier.fromNamespaceAndPath("gm", "panel_row"));
		static final StreamCodec<RegistryFriendlyByteBuf, RowClicked> CODEC = StreamCodec.composite(
				ByteBufCodecs.VAR_INT, RowClicked::containerId,
				ByteBufCodecs.stringUtf8(MOST_TYPED), RowClicked::id,
				ByteBufCodecs.VAR_INT, RowClicked::row,
				ByteBufCodecs.BOOL, RowClicked::rightClick,
				ByteBufCodecs.BOOL, RowClicked::shift,
				RowClicked::new);

		@Override
		public Type<RowClicked> type() {
			return TYPE;
		}
	}

	/** Never sent. A companion listening for it can draw filter slots, icons on tabs and lists too long for a chest, and one that isn't would draw them wrongly. */
	public record NewerWidgets() implements CustomPacketPayload {
		static final Type<NewerWidgets> TYPE = new Type<>(Identifier.fromNamespaceAndPath("gm", "panel_newer"));
		static final StreamCodec<RegistryFriendlyByteBuf, NewerWidgets> CODEC = StreamCodec.unit(new NewerWidgets());

		@Override
		public Type<NewerWidgets> type() {
			return TYPE;
		}
	}

	public static void register() {
		PayloadTypeRegistry.clientboundPlay().register(Shown.TYPE, Shown.CODEC);
		PayloadTypeRegistry.clientboundPlay().register(NewerWidgets.TYPE, NewerWidgets.CODEC);
		PayloadTypeRegistry.serverboundPlay().register(Typed.TYPE, Typed.CODEC);
		PayloadTypeRegistry.serverboundPlay().register(RowClicked.TYPE, RowClicked.CODEC);
		ServerPlayNetworking.registerGlobalReceiver(Typed.TYPE, (payload, context) -> {
			// Only ever about the panel this player really has open, whatever it says.
			if (context.player().containerMenu instanceof PanelMenu panel && panel.containerId == payload.containerId()) {
				panel.typedByClient(payload.id(), payload.value());
			}
		});
		ServerPlayNetworking.registerGlobalReceiver(RowClicked.TYPE, (payload, context) -> {
			if (context.player().containerMenu instanceof PanelMenu panel && panel.containerId == payload.containerId()) {
				panel.rowClickedByClient(payload.id(), payload.row(), payload.rightClick(), payload.shift());
			}
		});
		PanelDefinition.register();
	}

	static boolean canDraw(ServerPlayer player, PanelDefinition definition) {
		return ServerPlayNetworking.canSend(player, Shown.TYPE) && (!definition.needsNewerCompanion() || ServerPlayNetworking.canSend(player, NewerWidgets.TYPE));
	}

	static void send(ServerPlayer player, Shown shown) {
		ServerPlayNetworking.send(player, shown);
	}
}
