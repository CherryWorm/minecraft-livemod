package gm.companion;

import net.minecraft.network.RegistryFriendlyByteBuf;
import net.minecraft.network.codec.ByteBufCodecs;
import net.minecraft.network.codec.StreamCodec;
import net.minecraft.network.protocol.common.custom.CustomPacketPayload;
import net.minecraft.resources.Identifier;
import net.minecraft.world.item.ItemStack;

import java.util.ArrayList;
import java.util.List;

/**
 * This world's recipes that the player knows, as the server sends them. Nothing here touches JEI, because plenty of
 * people won't have it, and it's the plugin that reads this. conduit's KnownRecipes must stay in step with the format.
 */
public final class KnownRecipes {
	private static List<Shown> known = List.of();
	private static List<Shown> arriving = new ArrayList<>();
	private static Runnable listener = () -> {};

	private KnownRecipes() {}

	public static List<Shown> known() {
		return known;
	}

	/** The one with this id, or null if they don't know it. */
	public static Shown find(String id) {
		for (Shown recipe : known) {
			if (recipe.id().equals(id)) {
				return recipe;
			}
		}
		return null;
	}

	public static void onChange(Runnable newListener) {
		listener = newListener;
	}

	static void receive(Part part) {
		if (part.index() == 0) {
			arriving = new ArrayList<>();
		}
		arriving.addAll(part.recipes());
		if (part.index() == part.total() - 1) {
			known = List.copyOf(arriving);
			listener.run();
		}
	}

	static void forget() {
		known = List.of();
		listener.run();
	}

	/** One recipe. A width of 0 means its inputs can go in any order, and the station is what it's made at, if anything. */
	public record Shown(String id, String station, int width, List<List<ItemStack>> inputs, ItemStack output) {
		static final StreamCodec<RegistryFriendlyByteBuf, Shown> CODEC = StreamCodec.composite(
				ByteBufCodecs.STRING_UTF8, Shown::id,
				ByteBufCodecs.STRING_UTF8, Shown::station,
				ByteBufCodecs.VAR_INT, Shown::width,
				ItemStack.OPTIONAL_STREAM_CODEC.apply(ByteBufCodecs.list()).apply(ByteBufCodecs.list()), Shown::inputs,
				ItemStack.OPTIONAL_STREAM_CODEC, Shown::output,
				Shown::new);
	}

	record Part(int index, int total, List<Shown> recipes) implements CustomPacketPayload {
		static final Type<Part> TYPE = new Type<>(Identifier.fromNamespaceAndPath("gm", "known_recipes"));
		static final StreamCodec<RegistryFriendlyByteBuf, Part> CODEC = StreamCodec.composite(
				ByteBufCodecs.VAR_INT, Part::index,
				ByteBufCodecs.VAR_INT, Part::total,
				Shown.CODEC.apply(ByteBufCodecs.list()), Part::recipes,
				Part::new);

		@Override
		public Type<Part> type() {
			return TYPE;
		}
	}
}
