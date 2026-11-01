package gm.companion;

import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import net.fabricmc.fabric.api.client.networking.v1.ClientPlayNetworking;
import net.fabricmc.fabric.api.networking.v1.PayloadTypeRegistry;
import net.minecraft.client.Minecraft;
import net.minecraft.network.RegistryFriendlyByteBuf;
import net.minecraft.network.chat.Component;
import net.minecraft.network.codec.ByteBufCodecs;
import net.minecraft.network.codec.StreamCodec;
import net.minecraft.network.protocol.common.custom.CustomPacketPayload;
import net.minecraft.resources.Identifier;
import net.minecraft.world.inventory.AbstractContainerMenu;
import net.minecraft.world.inventory.ChestMenu;
import net.minecraft.world.inventory.MenuType;
import net.minecraft.world.item.ItemStack;

import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * Panels as the server describes them. No code comes with one, only what to draw, so nothing a builder writes runs on anyone's computer.
 * conduit's PanelNetwork must stay in step with the format.
 */
public final class PanelClient {
	private static final int MOST_TEXT = 1 << 20;
	private static final int MOST_TYPED = 4096;
	private static final Map<Integer, Shown> WAITING = new HashMap<>();

	private PanelClient() {}

	public record Shown(int containerId, String definition, String state, List<ItemStack> stacks) implements CustomPacketPayload {
		public static final Type<Shown> TYPE = new Type<>(Identifier.fromNamespaceAndPath("gm", "panel"));
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

	record Typed(int containerId, String id, String value) implements CustomPacketPayload {
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

	static void register() {
		PayloadTypeRegistry.clientboundPlay().register(Shown.TYPE, Shown.CODEC);
		PayloadTypeRegistry.serverboundPlay().register(Typed.TYPE, Typed.CODEC);
		ClientPlayNetworking.registerGlobalReceiver(Shown.TYPE, (payload, context) -> receive(payload));
	}

	private static void receive(Shown shown) {
		if (!shown.definition().isEmpty()) {
			// It always comes just ahead of the game being told to open the chest it goes with.
			WAITING.put(shown.containerId(), shown);
		} else if (Minecraft.getInstance().gui.screen() instanceof PanelScreen screen && screen.getMenu().containerId == shown.containerId()) {
			screen.update(JsonParser.parseString(shown.state()).getAsJsonObject(), shown.stacks());
		}
	}

	static void forget() {
		WAITING.clear();
	}

	static void typed(int containerId, String id, String value) {
		ClientPlayNetworking.send(new Typed(containerId, id, value));
	}

	/** Whether this chest is really a panel, in which case it's on screen now and the game has nothing more to do. */
	public static <T extends AbstractContainerMenu> boolean open(MenuType<T> type, Minecraft client, int containerId, Component title) {
		Shown shown = WAITING.remove(containerId);
		if (shown == null) {
			return false;
		}
		if (!(type.create(containerId, client.player.getInventory()) instanceof ChestMenu menu)) {
			return false;
		}
		JsonObject definition = JsonParser.parseString(shown.definition()).getAsJsonObject();
		PanelScreen screen = new PanelScreen(menu, client.player.getInventory(), title, definition);
		screen.update(JsonParser.parseString(shown.state()).getAsJsonObject(), shown.stacks());
		client.player.containerMenu = menu;
		client.gui.setScreen(screen);
		return true;
	}
}
