package gm.companion.guide;

import com.google.gson.JsonArray;
import com.google.gson.JsonObject;
import com.mojang.blaze3d.platform.InputConstants;
import gm.companion.KnownRecipes;
import net.fabricmc.fabric.api.client.event.lifecycle.v1.ClientTickEvents;
import net.fabricmc.fabric.api.client.keymapping.v1.KeyMappingHelper;
import net.fabricmc.fabric.api.client.networking.v1.ClientPlayNetworking;
import net.fabricmc.fabric.api.networking.v1.PayloadTypeRegistry;
import net.minecraft.client.KeyMapping;
import net.minecraft.client.Minecraft;
import net.minecraft.network.RegistryFriendlyByteBuf;
import net.minecraft.network.codec.ByteBufCodecs;
import net.minecraft.network.codec.StreamCodec;
import net.minecraft.network.protocol.common.custom.CustomPacketPayload;
import net.minecraft.resources.Identifier;
import vazkii.patchouli.api.PatchouliAPI;
import vazkii.patchouli.client.book.BookCategory;
import vazkii.patchouli.client.book.BookContents;
import vazkii.patchouli.client.book.BookEntry;
import vazkii.patchouli.client.book.ClientBookRegistry;
import vazkii.patchouli.client.book.gui.GuiBook;
import vazkii.patchouli.client.book.gui.GuiBookCategory;
import vazkii.patchouli.client.book.gui.GuiBookIndex;
import vazkii.patchouli.common.book.BookRegistry;

import java.util.List;

/**
 * The Codex, read in Patchouli. Its pages come in the resource pack (broker/guide.py), each behind a flag, and the server says which flags
 * this player has earned, so all a book holds is what they know. Only ever loaded alongside Patchouli, and without this the server falls
 * back to a plain written book. conduit's Codex must stay in step with the format.
 */
public final class Guide {
	private static final String NAMESPACE = "companion";
	private static final Identifier BOOK = Identifier.fromNamespaceAndPath(NAMESPACE, "guide");
	private static final KeyMapping OPEN_KEY = new KeyMapping("key.companion.guide", InputConstants.KEY_B, KeyMapping.Category.MISC);
	private static boolean stale;
	private static List<KnownRecipes.Shown> recipesInBook = List.of();
	private static String languageInBook = "";

	private Guide() {}

	public static void register() {
		PayloadTypeRegistry.clientboundPlay().register(Flags.TYPE, Flags.CODEC);
		PayloadTypeRegistry.clientboundPlay().register(Open.TYPE, Open.CODEC);
		ClientPlayNetworking.registerGlobalReceiver(Flags.TYPE, (payload, context) -> receive(payload));
		ClientPlayNetworking.registerGlobalReceiver(Open.TYPE, (payload, context) -> open(payload.entry()));
		ClientBookRegistry.INSTANCE.pageTypes.put(Identifier.fromNamespaceAndPath("gm", "recipe"), KnownRecipePage.class);
		KeyMappingHelper.registerKeyMapping(OPEN_KEY);
		ClientTickEvents.END_CLIENT_TICK.register(Guide::tick);
	}

	private static void receive(Flags flags) {
		flags.known().forEach(flag -> PatchouliAPI.get().setConfigFlag(flag, true));
		flags.unknown().forEach(flag -> PatchouliAPI.get().setConfigFlag(flag, false));
		stale = true;
	}

	private static void tick(Minecraft client) {
		if (client.level == null) {
			return;
		}
		if (KnownRecipes.known() != recipesInBook) {
			recipesInBook = KnownRecipes.known();
			stale = true;
		}
		// The book reads its pages in one language when it's built, and changing language in the options doesn't build it again.
		String language = client.getLanguageManager().getSelected();
		if (!language.equals(languageInBook)) {
			languageInBook = language;
			stale = true;
		}
		// Not under someone reading it, because that would take the page they're on away from them.
		if (stale && !isOpen()) {
			rebuild();
		}
		while (OPEN_KEY.consumeClick()) {
			open("");
		}
	}

	private static void rebuild() {
		stale = false;
		ClientBookRegistry.INSTANCE.reload();
	}

	private static void open(String entry) {
		if (stale) {
			rebuild();
		}
		if (entry.isEmpty()) {
			PatchouliAPI.get().openBookGUI(BOOK);
		} else {
			PatchouliAPI.get().openBookEntry(BOOK, Identifier.fromNamespaceAndPath(NAMESPACE, entry), 0);
		}
	}

	/** The key that opens it, for a test. */
	public static KeyMapping openKey() {
		return OPEN_KEY;
	}

	/** Whether the book's on screen, for a test. */
	public static boolean isOpen() {
		return Minecraft.getInstance().gui.screen() instanceof GuiBook;
	}

	/** Opens one entry at a page by the name players see, for a test. */
	public static void show(String title, int page) {
		for (BookEntry entry : contents().entries.values()) {
			if (entry.getName().getString().equals(title)) {
				PatchouliAPI.get().openBookEntry(BOOK, entry.getId(), page);
				return;
			}
		}
		throw new IllegalArgumentException("No entry called " + title);
	}

	/** Opens one category by the name players see, for a test. */
	public static void showCategory(String name) {
		for (BookCategory category : contents().categories.values()) {
			if (category.getName().getString().equals(name)) {
				contents().openLexiconGui(new GuiBookCategory(BookRegistry.INSTANCE.books.get(BOOK), category), false);
				return;
			}
		}
		throw new IllegalArgumentException("No category called " + name);
	}

	/** Opens the list of everything, which is where the search is, for a test. */
	public static void showIndex() {
		contents().openLexiconGui(new GuiBookIndex(BookRegistry.INSTANCE.books.get(BOOK)), false);
	}

	/** What this player's book holds, for a test. */
	public static String describe() {
		JsonObject out = new JsonObject();
		JsonArray categories = new JsonArray();
		for (BookCategory category : contents().categories.values()) {
			categories.add((category.getParentCategory() == null ? "" : category.getParentCategory().getName().getString() + " / ") + category.getName().getString());
		}
		JsonArray entries = new JsonArray();
		for (BookEntry entry : contents().entries.values()) {
			entries.add(entry.getName().getString());
		}
		out.add("categories", categories);
		out.add("entries", entries);
		return out.toString();
	}

	private static BookContents contents() {
		return BookRegistry.INSTANCE.books.get(BOOK).getContents();
	}

	private record Flags(List<String> known, List<String> unknown) implements CustomPacketPayload {
		static final Type<Flags> TYPE = new Type<>(Identifier.fromNamespaceAndPath("gm", "codex_flags"));
		static final StreamCodec<RegistryFriendlyByteBuf, Flags> CODEC = StreamCodec.composite(
				ByteBufCodecs.STRING_UTF8.apply(ByteBufCodecs.list()), Flags::known,
				ByteBufCodecs.STRING_UTF8.apply(ByteBufCodecs.list()), Flags::unknown,
				Flags::new);

		@Override
		public Type<Flags> type() {
			return TYPE;
		}
	}

	private record Open(String entry) implements CustomPacketPayload {
		static final Type<Open> TYPE = new Type<>(Identifier.fromNamespaceAndPath("gm", "codex_open"));
		static final StreamCodec<RegistryFriendlyByteBuf, Open> CODEC = StreamCodec.composite(ByteBufCodecs.STRING_UTF8, Open::entry, Open::new);

		@Override
		public Type<Open> type() {
			return TYPE;
		}
	}
}
